"""whatsonyourmind backend: Mindy on WhatsApp + Instagram, the Mindy web app (API, live socket and the app's files),
the reminders scheduler and the website waitlist.
Run:  uvicorn app.main:app --reload     then open http://localhost:8000"""
import logging
import re
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
import json
import os
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from html import escape
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import realtime
from .api import make_router
from .auth import user_for_token
from .config import settings
from .db import DB
from .handlers import Mindy, care_check, occasion_nudges, send_due, weekly_summary
from .instagram import normalise as ig_normalise
from . import jobs, llm, more, skills
from .routes_more import make_more_router
from .telegram import normalise as tg_normalise, tg
from .whatsapp import verify_signature, wa

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("mindy")

db = DB(settings.database_path)
more.init(db)
from .handlers import CLIENTS as _CLIENTS
_CLIENTS["sms"] = more.SmsClient(db)
mindy = Mindy(db)
scheduler: AsyncIOScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    scheduler = AsyncIOScheduler(timezone="UTC")  # a fresh one per start, bound to the running loop
    scheduler.add_job(send_due, "interval", seconds=30, args=[db], id="reminders", max_instances=1, coalesce=True)
    scheduler.add_job(care_check, "interval", seconds=60, args=[db], id="care", max_instances=1, coalesce=True)
    scheduler.add_job(clean_media, "interval", hours=1, id="media")
    scheduler.add_job(occasion_nudges, "cron", hour=9, minute=0, args=[db], id="occasions")
    scheduler.add_job(weekly_summary, "cron", day_of_week="sun", hour=18, minute=0, args=[db], id="weekly")
    jobs.add_jobs(scheduler, db)
    import asyncio as _a
    realtime.hub.loop = _a.get_running_loop()
    scheduler.start()
    log.info("Mindy is up. WhatsApp live=%s, Instagram live=%s, AI live=%s", settings.whatsapp_live, settings.instagram_live, settings.ai_live)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="whatsonyourmind", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])


app.include_router(make_router(db, wa, mindy))
app.include_router(make_more_router(db, mindy))


@app.websocket("/ws")
async def live(ws: WebSocket):
    """One socket per open app: presence, chat, games, watch parties and in-app reminders."""
    user = user_for_token(db, ws.query_params.get("token"))
    await ws.accept()
    if not user:
        await ws.send_json({"type": "auth.failed"})
        return await ws.close(code=4401)
    first = not realtime.hub.online(user["id"])
    await realtime.hub.connect(user["id"], ws)
    await ws.send_json({"type": "hello", "user": user["id"], "online": [f for f in realtime.friend_ids(db, user["id"]) if realtime.hub.online(f)]})
    if first and user.get("status") != "ghost":
        await realtime.presence(db, user["id"], True)
    try:
        while True:
            data = await ws.receive_json()
            user = db.one("SELECT * FROM users WHERE id=?", (user["id"],)) or user
            try:
                await realtime.handle(db, user, data, ws)
            except Exception as e:  # one bad message never kills the socket
                log.exception("ws handle failed: %s", e)
                await ws.send_json({"type": "error", "message": "Something went wrong with that. Try again."})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        realtime.hub.disconnect(user["id"], ws)
        if not realtime.hub.online(user["id"]):
            await realtime.presence(db, user["id"], False)


@app.get("/health")
def health():
    return {"ok": True, "whatsapp_live": settings.whatsapp_live, "instagram_live": settings.instagram_live,
            "telegram_live": settings.telegram_live, "ai_live": settings.ai_live, "ai_model": settings.llm_model if settings.ai_live else None}


# ---------------------------------------------------------------- WhatsApp webhook
@app.get("/webhook")
def verify(request: Request):
    """Meta calls this once when you register the webhook URL."""
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == settings.wa_verify_token:
        return Response(content=q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403, "Verification failed")


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401, "Bad signature")
    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                # Reply fast (Meta retries slow webhooks); do the work in the background.
                background.add_task(mindy.handle, msg, names.get(msg.get("from")))
            for st in value.get("statuses", []):
                if st.get("status") == "failed":
                    log.warning("Delivery failed: %s", st.get("errors"))
    return {"ok": True}


# ---------------------------------------------------------------- Instagram webhook
@app.get("/webhook/instagram")
def verify_instagram(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == settings.ig_verify_token:
        return Response(content=q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403, "Verification failed")


@app.post("/webhook/instagram")
async def receive_instagram(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Hub-Signature-256"), settings.ig_app_secret):
        raise HTTPException(401, "Bad signature")
    payload = await request.json()
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            msg = ig_normalise(event)
            if msg:
                background.add_task(mindy.handle, msg, None)
    return {"ok": True}


# ---------------------------------------------------------------- Telegram webhook
@app.post("/webhook/telegram")
async def receive_telegram(request: Request, background: BackgroundTasks):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.tg_secret:
        raise HTTPException(401, "Bad secret")
    update = await request.json()
    msg, name = tg_normalise(update)
    if msg:
        if msg.get("cb"):
            background.add_task(tg._call, "answerCallbackQuery", {"callback_query_id": msg["cb"]})
        background.add_task(mindy.handle, msg, name)
    return {"ok": True}


# ---------------------------------------------------------------- tap-to-open links and files Mindy sends
@app.get("/go", response_class=HTMLResponse)
def go(to: str):
    """Chat apps only make https links tappable, so upi:// and tel:// links go through this tiny page."""
    if not skills.safe_target(to):
        raise HTTPException(400, "Not an allowed link")
    import html as _h
    label = "Pay with UPI" if to.startswith("upi:") else "Call" if to.startswith("tel:") else "Open"
    t = _h.escape(to, quote=True)
    return f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>Mindy</title>
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#000;color:#F5F3EE;font-family:system-ui;text-align:center">
<div><p style="font-size:18px">Opening your app…</p><a href="{t}" style="display:inline-block;background:#25D366;color:#000;font-weight:800;padding:18px 28px;border-radius:999px;text-decoration:none;font-size:20px">{label}</a>
<p style="color:#8C959D;font-size:14px;max-width:320px">Check the name before you pay. Mindy never asks for your PIN or OTP.</p></div>
<script>setTimeout(function(){{location.href={json.dumps(to)}}},300)</script></body>"""


@app.get("/media/{name}")
def media(name: str):
    import os as _os
    from fastapi.responses import FileResponse
    if not re.fullmatch(r"[\w-]{16,40}\.(jpg|mp3|mp4|png)", name):
        raise HTTPException(404)
    path = _os.path.join(skills.MEDIA_DIR, name)
    if not _os.path.exists(path):
        raise HTTPException(404, "This file has expired.")
    return FileResponse(path)


async def clean_media():
    import os as _os, time as _t
    if _os.path.isdir(skills.MEDIA_DIR):
        for f in _os.listdir(skills.MEDIA_DIR):
            p = _os.path.join(skills.MEDIA_DIR, f)
            if not f.startswith("keep-") and _t.time() - _os.path.getmtime(p) > 86400:
                _os.remove(p)


# ---------------------------------------------------------------- Mindy buttons (one tap from the home screen)
BUTTONS = {"park": ("🚗", "I parked here", "Saving where you parked…"), "car": ("📍", "Where's my car", "Finding your car…"),
           "home": ("🏠", "Take me home", "Getting directions home…"), "sos": ("🆘", "SOS to family", "Sending your location to your family…")}


def _button_user(key: str):
    if not re.fullmatch(r"[\w-]{8,20}", key):
        raise HTTPException(404)
    u = db.one("SELECT * FROM users WHERE button_key=?", (key,))
    if not u:
        raise HTTPException(404, "This button isn't linked to anyone. Ask Mindy for new buttons.")
    return u


@app.get("/b/{key}/{action}/manifest.json")
def button_manifest(key: str, action: str):
    _button_user(key)
    icon, title, _ = BUTTONS.get(action) or (None, None, None)
    if not title:
        raise HTTPException(404)
    return {"name": title, "short_name": title, "start_url": f"/b/{key}/{action}", "display": "standalone", "background_color": "#000000",
            "theme_color": "#000000", "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"}, {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}]}


@app.get("/b/{key}/{action}", response_class=HTMLResponse)
def button_page(key: str, action: str):
    _button_user(key)
    if action not in BUTTONS:
        raise HTTPException(404)
    icon, title, doing = BUTTONS[action]
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{title}</title><meta name=apple-mobile-web-app-title content="{title}"><meta name=apple-mobile-web-app-capable content=yes>
<link rel=apple-touch-icon href=/icon-192.png><link rel=manifest href="/b/{key}/{action}/manifest.json"><meta name=theme-color content="#000">
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#000;color:#F5F3EE;font-family:system-ui;text-align:center;padding:24px;box-sizing:border-box}}
.i{{font-size:96px}}h1{{font-size:28px;margin:8px 0}}p{{color:#B9C0C6;font-size:18px;max-width:340px;margin:8px auto}}a.b,button{{display:inline-block;background:#25D366;color:#000;font-weight:800;font-size:20px;padding:16px 26px;border-radius:999px;border:0;text-decoration:none;margin-top:14px}}
.tip{{font-size:14px;color:#8C959D;margin-top:26px}}</style></head><body><div><div class=i>{icon}</div><h1>{title}</h1><p id=s>{doing}</p><div id=x></div>
<p class=tip>Tip: add this page to your home screen for a one-tap button.<br>iPhone: Share → Add to Home Screen · Android: ⋮ → Add to Home screen</p></div>
<script>
const A={json.dumps(action)}, K={json.dumps(key)}, s=document.getElementById('s'), x=document.getElementById('x');
function where(cb){{ if(!navigator.geolocation){{s.textContent='This phone can\'t share location here.';return}}
  navigator.geolocation.getCurrentPosition(p=>cb(p.coords.latitude,p.coords.longitude),()=>{{s.textContent='Please allow location, then tap again.';x.innerHTML='<button onclick="location.reload()">Try again</button>'}},{{enableHighAccuracy:true,timeout:15000}}); }}
async function post(lat,lng){{ const r=await fetch('/b/'+K+'/'+A,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{lat,lng}})}}); return r.json(); }}
if(A==='park') where(async(a,b)=>{{const r=await post(a,b); s.textContent=r.message; x.innerHTML='<a class=b href="/b/'+K+'/car">Where\'s my car?</a>';}});
if(A==='sos') where(async(a,b)=>{{const r=await post(a,b); s.textContent=r.message;}});
if(A==='car'||A==='home') fetch('/b/'+K+'/'+A,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}}).then(r=>r.json()).then(r=>{{
  s.textContent=r.message; if(r.url){{x.innerHTML='<a class=b href="'+r.url+'">Go</a>'+(r.street?'<br><a class=b style="background:#F5F3EE" href="'+r.street+'">Street View</a>':''); setTimeout(()=>location.href=r.url,900);}} }});
</script></body></html>"""


@app.post("/b/{key}/{action}")
async def button_do(key: str, action: str, request: Request):
    from . import places as _pl
    from .care import family_of
    from .handlers import deliver
    from .realtime import hub
    u = _button_user(key)
    body = await request.json()
    if action == "park":
        _pl.save(db, u["id"], float(body["lat"]), float(body["lng"]), "car")
        return {"message": "Saved ✅ Tap “Where's my car?” when you need it."}
    if action in ("car", "home"):
        p = _pl.latest(db, u["id"], action)
        if not p:
            return {"message": "Nothing saved yet. " + ("Use the 🚗 I parked here button when you park." if action == "car" else "Send Mindy your home location on WhatsApp and say it's home.")}
        lk = _pl.links(p, "walking" if action == "car" else "driving")
        return {"message": "Opening the route…", "url": lk[0][1], "street": lk[1][1]}
    if action == "sos":
        lat, lng = float(body["lat"]), float(body["lng"])
        maps = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
        who = u.get("name") or "Your family member"
        fam = family_of(db, u["id"])
        for f in fam:
            await hub.send(f["id"], {"type": "notify", "title": f"🆘 {who} needs help", "body": "Tap to see where they are.", "url": maps})
            await deliver(db, f["id"], f"🆘 *{who} pressed SOS.*\nTheir location: {maps}\nCall them now.", [], settings.sos_template, [who, maps],
                          title=f"🆘 {who} needs help", url=maps)
        return {"message": f"Sent to {len(fam)} family member{'s' if len(fam) != 1 else ''} ✅ Stay where you are if you can." if fam else
                "You haven't linked family yet. Ask Mindy “family” to set it up. Call 112 in an emergency."}
    raise HTTPException(404)


# ---------------------------------------------------------------- website waitlist
class Signup(BaseModel):
    email: str
    phone: str | None = None
    interest: str | None = None   # "whatsapp", "app", "both"
    source: str | None = "website"


@app.post("/api/waitlist")
def waitlist(s: Signup):
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s.email):
        raise HTTPException(422, "Please enter a valid email address.")
    added = db.waitlist_add(s.email.lower().strip(), s.phone, s.interest, s.source)
    count = db.one("SELECT COUNT(*) n FROM waitlist")["n"]
    return {"ok": True, "new": added, "position": count}


# ---------------------------------------------------------------- admin
@app.get("/admin/stats")
def stats(key: str):
    if key != settings.admin_key:
        raise HTTPException(403)
    n = lambda sql: db.one(sql)["n"]
    return {"users": n("SELECT COUNT(*) n FROM users"), "items": n("SELECT COUNT(*) n FROM items"),
            "reminders_pending": n("SELECT COUNT(*) n FROM reminders WHERE status='pending'"),
            "reminders_undelivered": n("SELECT COUNT(*) n FROM reminders WHERE status='undelivered'"),
            "whatsapp_accounts": n("SELECT COUNT(*) n FROM accounts WHERE channel='wa'"),
            "instagram_accounts": n("SELECT COUNT(*) n FROM accounts WHERE channel='ig'"),
            "messages_7d": n("SELECT COUNT(*) n FROM messages WHERE created_at > datetime('now','-7 days')"),
            "telegram_accounts": n("SELECT COUNT(*) n FROM accounts WHERE channel='tg'"),
            "care_doses_taken_7d": n("SELECT COUNT(*) n FROM care_log WHERE took_at > datetime('now','-7 days')"),
            "saves_done_7d": n("SELECT COUNT(*) n FROM items WHERE done_at > datetime('now','-7 days')"),
            "scam_reports": n("SELECT COUNT(*) n FROM scam_reports"),
            "ai": dict(llm.STATS), "waitlist": n("SELECT COUNT(*) n FROM waitlist")}


@app.get("/admin", response_class=HTMLResponse)
def admin_page(key: str):
    """A one-page dashboard for you: numbers and the latest waitlist sign-ups."""
    if key != settings.admin_key:
        raise HTTPException(403)
    s = stats(key)
    wl = db.q("SELECT email, interest, source, created_at FROM waitlist ORDER BY id DESC LIMIT 100")
    tiles = "".join(f"<div><b>{v}</b><span>{k.replace('_', ' ')}</span></div>" for k, v in s.items())
    rows = "".join(f"<tr><td>{escape(w['email'])}</td><td>{escape(w['interest'] or '')}</td><td>{escape(w['source'] or '')}</td><td>{w['created_at'][:16].replace('T', ' ')}</td></tr>" for w in wl)
    return f"""<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mindy admin</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;margin:0;background:#FBFDFB;color:#0E1B17;padding:32px max(16px,4vw)}}h1{{margin:0 0 20px}}
.t{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:28px}}.t div{{background:#08382F;color:#fff;border-radius:16px;padding:16px}}
.t b{{display:block;font-size:30px;color:#25D366}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #D5E3DB}}</style></head>
<body><h1>whatsonyourmind</h1><div class="t">{tiles}</div><h2>Waitlist (latest 100)</h2><div style="overflow-x:auto"><table><tr><th>Email</th><th>Interest</th><th>Source</th><th>Joined (UTC)</th></tr>{rows}</table></div></body></html>"""


# ---------------------------------------------------------------- the web app's files (served last, at /)
WEBAPP = Path(settings.webapp_dir or Path(__file__).resolve().parent.parent / "webapp")
if WEBAPP.is_dir():
    app.mount("/", StaticFiles(directory=WEBAPP, html=True), name="webapp")
