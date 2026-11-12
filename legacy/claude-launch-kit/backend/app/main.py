"""whatsonyourmind backend: Mindy on WhatsApp + Instagram, the Mindy web app (API, live socket and the app's files),
the reminders scheduler and the website waitlist.
Run:  uvicorn app.main:app --reload     then open http://localhost:8000"""
import logging
import re
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
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
from .handlers import Mindy, occasion_nudges, send_due, weekly_summary
from .instagram import normalise as ig_normalise
from .whatsapp import verify_signature, wa

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("mindy")

db = DB(settings.database_path)
mindy = Mindy(db)
scheduler = AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(send_due, "interval", seconds=30, args=[db], id="reminders", max_instances=1, coalesce=True)
    scheduler.add_job(occasion_nudges, "cron", hour=9, minute=0, args=[db], id="occasions")
    scheduler.add_job(weekly_summary, "cron", day_of_week="sun", hour=18, minute=0, args=[db], id="weekly")
    scheduler.start()
    log.info("Mindy is up. WhatsApp live=%s, Instagram live=%s, AI live=%s", settings.whatsapp_live, settings.instagram_live, settings.ai_live)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="whatsonyourmind", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])


app.include_router(make_router(db, wa, mindy))


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
    return {"ok": True, "whatsapp_live": settings.whatsapp_live, "instagram_live": settings.instagram_live, "ai_live": settings.ai_live}


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
            "waitlist": n("SELECT COUNT(*) n FROM waitlist")}


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
