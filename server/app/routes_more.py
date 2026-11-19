"""Routes for the newer skills: magic links, calendar feed, email-in, the SMS gateway phone, the clipboard,
"your mind" (questions, facts, family tree, habits), Brain Score cards, public number check, and the admin queues."""
import asyncio
import hmac
import io
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import care, countries, mind, more, skills
from .auth import make_dependency, new_session, too_many
from .config import settings
from .db import DB, now_iso


class Body(BaseModel):
    model_config = {"extra": "allow"}


def _user_by_key(db: DB, key: str) -> dict:
    u = db.one("SELECT * FROM users WHERE button_key=?", (key,)) if re.match(r"^[\w-]{6,40}$", key or "") else None
    if not u:
        raise HTTPException(404)
    return u


def share_key(db: DB, uid: int) -> str:
    """A public key for the shareable Brain Score card. Separate from the private key behind calendar, clipboard and email."""
    import secrets as _s
    with db.lock:
        if "share_key" not in {r[1] for r in db.conn.execute("PRAGMA table_info(users)").fetchall()}:
            db.conn.execute("ALTER TABLE users ADD COLUMN share_key TEXT")
            db.conn.commit()
    row = db.one("SELECT share_key FROM users WHERE id=?", (uid,))
    if row and row.get("share_key"):
        return row["share_key"]
    k = _s.token_urlsafe(8)
    db.x("UPDATE users SET share_key=? WHERE id=?", (k, uid))
    return k


def _user_by_share(db: DB, key: str) -> dict:
    share_key(db, 0)  # makes sure the column exists
    u = db.one("SELECT * FROM users WHERE share_key=?", (key,)) if re.match(r"^[\w-]{6,40}$", key or "") else None
    if not u:
        raise HTTPException(404)
    return u


def make_more_router(db: DB, mindy) -> APIRouter:
    r = APIRouter()
    me_dep = make_dependency(db)

    # ------------------------------------------------------------ magic link: WhatsApp -> the app, signed in, on the right screen
    @r.get("/m/{tok}", response_class=HTMLResponse)
    def magic(tok: str):
        row = more.use_magic(db, tok)
        if not row:
            return HTMLResponse(f"<meta http-equiv=refresh content='0;url=/'>This link has expired. Opening Mindy…", status_code=410)
        token = new_session(db, row["user_id"])
        path = re.sub(r"[^\w/-]", "", row["path"] or "now")
        return HTMLResponse("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>Mindy</title>"
                            f"<script>try{{localStorage.setItem('mindy_token',{json.dumps(token)})}}catch(e){{}}location.replace('/#{path}')</script>")

    # ------------------------------------------------------------ calendar feed (subscribe from Google / Apple / Outlook; no OAuth)
    @r.get("/cal/{key}.ics")
    def calendar(key: str):
        u = _user_by_key(db, key)
        rows = db.q("SELECT id, text, due_at FROM reminders WHERE user_id=? AND status='pending' ORDER BY due_at LIMIT 500", (u["id"],))
        esc = lambda s: re.sub(r"([,;\\])", r"\\\1", s).replace("\n", "\\n")
        ev = []
        for x in rows:
            d = datetime.fromisoformat(x["due_at"]).astimezone(timezone.utc)
            ev.append(f"BEGIN:VEVENT\r\nUID:mindy-{x['id']}@whatsonyourmind\r\nDTSTAMP:{d:%Y%m%dT%H%M%SZ}\r\nDTSTART:{d:%Y%m%dT%H%M%SZ}\r\n"
                      f"DTEND:{(d + timedelta(minutes=15)):%Y%m%dT%H%M%SZ}\r\nSUMMARY:{esc(x['text'][:200])}\r\nEND:VEVENT")
        body = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//whatsonyourmind//Mindy//EN\r\nX-WR-CALNAME:Mindy\r\n" + "\r\n".join(ev) + "\r\nEND:VCALENDAR\r\n"
        return Response(body, media_type="text/calendar")

    # ------------------------------------------------------------ email in (Cloudflare Email Routing worker posts here)
    @r.post("/webhook/email")
    async def email_in(request: Request):
        if not settings.secret_ok(settings.email_secret) or not hmac.compare_digest(request.headers.get("X-Mindy-Secret") or "", settings.email_secret):
            raise HTTPException(401)
        b = await request.json()
        key = (b.get("to") or "").split("@")[0].strip().lower()
        u = db.one("SELECT * FROM users WHERE lower(button_key)=?", (key,))
        if not u:
            return {"ok": False}
        subject, text = (b.get("subject") or "(no subject)")[:200], (b.get("text") or "")[:4000]
        db.save_item(u["id"], "email", f"{subject}\n{text[:1500]}", collection="Email")
        chk = skills.check_message(db, f"{b.get('from', '')} {subject} {text[:1500]}", use_ai=False)
        warn = "\n⚠️ This looks like phishing. Don't click its links." if chk.get("verdict") == "scam" else ""
        t = mind.trip_from(f"{subject} {text[:600]}", u.get("tz") or "UTC")
        extra = ""
        if t and t["date"] >= datetime.now(ZoneInfo(u.get("tz") or "UTC")).date():
            extra = "\n" + mind.auto_trip(db, u, t["place"], t["date"], t["flight"])["reply"]
        from .handlers import deliver
        await deliver(db, u["id"], f"📧 Saved email: *{subject}*{warn}{extra}", [], None, [], title="📧 Email saved", url="/#mind")
        return {"ok": True}

    # ------------------------------------------------------------ the SMS gateway phone (missed calls and SMS for basic phones)
    def _gw(request: Request):
        if not settings.secret_ok(settings.gateway_secret) or not hmac.compare_digest(request.headers.get("X-Gateway-Secret") or "", settings.gateway_secret):
            raise HTTPException(401)

    @r.post("/api/gateway/missed")
    async def gw_missed(b: Body, request: Request):
        _gw(request)
        num = re.sub(r"\D", "", str(getattr(b, "from_", None) or (b.model_extra or {}).get("from", "")))
        if len(num) < 8 or too_many("gw:" + num, 3, 3600):
            return {"ok": False}
        db.x("INSERT INTO sms_out(to_number,body,created_at) VALUES(?,?,?)", (num, more.SMS_WELCOME, now_iso()))
        db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"sms_menu:{num}", "sms:schemes|sms:remind|sms:scam"))
        return {"ok": True}

    @r.post("/api/gateway/sms")
    async def gw_sms(b: Body, request: Request):
        _gw(request)
        x = b.model_extra or {}
        num, body = re.sub(r"\D", "", str(x.get("from", ""))), str(x.get("body", ""))[:1000]
        if len(num) < 8 or not body.strip():
            return {"ok": False}
        await mindy.handle({"from": num, "id": f"sms-{num}-{now_iso()}", "type": "text", "text": {"body": body}, "channel": "sms"})
        return {"ok": True}

    @r.get("/api/gateway/outbox")
    def gw_outbox(request: Request):
        _gw(request)
        rows = db.q("SELECT id, to_number, body FROM sms_out WHERE sent_at IS NULL ORDER BY id LIMIT 20")
        for x in rows:
            db.x("UPDATE sms_out SET sent_at=? WHERE id=?", (now_iso(), x["id"]))
        return {"messages": rows}

    # ------------------------------------------------------------ the clipboard (iPhone Back Tap shortcut, or any device)
    @r.post("/clip/{key}")
    async def clip_in(key: str, request: Request):
        u = _user_by_key(db, key)
        raw = (await request.body()).decode("utf-8", "ignore").strip()
        try:
            raw = json.loads(raw).get("text", raw) if raw.startswith("{") else raw
        except ValueError:
            pass
        if not raw or too_many("clip:" + key, 60, 600):
            return {"ok": False}
        db.save_item(u["id"], "clip", raw[:5000], collection="Clipboard")
        from .realtime import hub
        await hub.send(u["id"], {"type": "clip", "text": raw[:5000]})
        warn = skills.check_message(db, raw[:1500], use_ai=False) if re.search(r"https?://|www\.", raw) else None
        return {"ok": True, "message": "Saved to Mindy ✓" + (" ⚠️ That link looks like a scam." if warn and warn.get("verdict") == "scam" else "")}

    @r.get("/api/clipboard")
    def clipboard(me=Depends(me_dep)):
        return db.q("SELECT id, text, created_at FROM items WHERE user_id=? AND collection='Clipboard' ORDER BY id DESC LIMIT 100", (me["id"],))

    # ------------------------------------------------------------ your mind: questions, facts, family tree, habits, goals
    @r.get("/api/mind")
    def get_mind(me=Depends(me_dep)):
        return {**mind.mind(db, me), "brain": more.brain_score(db, me), "mindy": {"name": more.mindy_name(me), "hue": me.get("mindy_hue"),
                "persona": me.get("persona") or "sweet", "lang": me.get("lang") or "en"}, "country": countries.for_user(db, me)}

    @r.get("/api/mind/question")
    def mind_question(region: str | None = None, me=Depends(me_dep)):
        return {"next": mind.question_for(db, me["id"], region)}

    @r.post("/api/mind/answer")
    def mind_answer(b: Body, me=Depends(me_dep)):
        x = b.model_extra or {}
        key, value = str(x.get("key", "")), str(x.get("value", "")).strip()[:200]
        if key not in mind.QBY or not value:
            raise HTTPException(400, "Unknown question.")
        if value.lower() == "skip":
            mind.set_fact(db, me["id"], key, "skipped")
            return {"reply": "Skipped.", "next": mind.question_for(db, me["id"], mind.QBY[key]["region"]), "brain": more.brain_score(db, me)}
        res = mind.answer(db, me, key, value)
        if key == "pet" and value:
            res["reply"] = f"🥹 {value.split()[0].title()}… can I have that name?"
            res["rename"] = value.split()[0].title()[:16]
        return {"reply": res["reply"], "rename": res.get("rename"), "again": res.get("again"),
                "next": mind._public_q(res.get("next")) or mind.question_for(db, me["id"], mind.QBY[key]["region"]), "brain": more.brain_score(db, me)}

    @r.delete("/api/mind/fact/{fid}")
    def del_fact(fid: int, me=Depends(me_dep)):
        db.x("DELETE FROM facts WHERE id=? AND user_id=?", (fid, me["id"]))
        return {"ok": True}

    @r.post("/api/tree")
    def add_person(b: Body, me=Depends(me_dep)):
        x = b.model_extra or {}
        name = re.sub(r"[^\w .'-]", "", str(x.get("name", ""))).strip()[:40]
        if not name:
            raise HTTPException(400, "Add a name.")
        bd = None
        if x.get("birthday"):
            d = mind.parse_date(str(x["birthday"]), future=False)
            bd = f"{d:%m-%d}" if d else None
        pid = mind.add_person(db, me["id"], name, str(x.get("relation", ""))[:30], bd, x.get("parent_id"), None)
        if x.get("gift_ideas"):
            db.x("UPDATE people SET gift_ideas=? WHERE id=? AND user_id=?", (str(x["gift_ideas"])[:300], pid, me["id"]))
        return {"id": pid, "people": mind.tree(db, me["id"]), "brain": more.brain_score(db, me)}

    @r.delete("/api/tree/{pid}")
    def del_person(pid: int, me=Depends(me_dep)):
        db.x("DELETE FROM people WHERE id=? AND user_id=?", (pid, me["id"]))
        return {"people": mind.tree(db, me["id"])}

    @r.post("/api/habits")
    def add_habit(b: Body, me=Depends(me_dep)):
        t = str((b.model_extra or {}).get("title", "")).strip()[:60]
        if not t:
            raise HTTPException(400, "Name the habit.")
        db.x("INSERT INTO habits(user_id,title,created_at) VALUES(?,?,?)", (me["id"], t, now_iso()))
        return mind.mind(db, me)["habits"]

    @r.post("/api/habits/{hid}/done")
    def habit_done(hid: int, me=Depends(me_dep)):
        h = mind.habit_done(db, me["id"], me.get("tz") or "UTC", hid)
        if not h:
            raise HTTPException(404)
        return {"streak": h["streak"], "brain": more.brain_score(db, me)}

    @r.delete("/api/habits/{hid}")
    def del_habit(hid: int, me=Depends(me_dep)):
        db.x("UPDATE habits SET archived=1 WHERE id=? AND user_id=?", (hid, me["id"]))
        return {"ok": True}

    @r.post("/api/goals")
    def add_goal(b: Body, me=Depends(me_dep)):
        t = str((b.model_extra or {}).get("title", "")).strip()[:80]
        if not t:
            raise HTTPException(400, "Name the goal.")
        db.x("INSERT INTO goals(user_id,title,created_at) VALUES(?,?,?)", (me["id"], t, now_iso()))
        return {"ok": True}

    @r.post("/api/goals/{gid}/done")
    def goal_done(gid: int, me=Depends(me_dep)):
        db.x("UPDATE goals SET done_at=? WHERE id=? AND user_id=?", (now_iso(), gid, me["id"]))
        return {"ok": True}

    @r.post("/api/docs")
    def add_doc(b: Body, me=Depends(me_dep)):
        x = b.model_extra or {}
        d = mind.parse_date(str(x.get("expires", "")))
        name = str(x.get("name", "")).strip()[:40]
        if not d or not name:
            raise HTTPException(400, "Add the document and its expiry date, like 3 May 2027.")
        return mind.add_doc(db, me, name.lower(), d)

    @r.patch("/api/mindy")
    def set_mindy(b: Body, me=Depends(me_dep)):
        x = b.model_extra or {}
        if "name" in x:
            n = re.sub(r"[^\w ]", "", str(x["name"])).strip()[:18]
            db.x("UPDATE users SET mindy_name=? WHERE id=?", (n or None, me["id"]))
        if "hue" in x:
            db.x("UPDATE users SET mindy_hue=? WHERE id=?", (int(x["hue"]) % 360, me["id"]))
        if x.get("persona") in more.PERSONAS:
            db.x("UPDATE users SET persona=? WHERE id=?", (x["persona"], me["id"]))
        if "lang" in x and (x["lang"] in more.LANG_NAME or x["lang"] in ("en", "hinglish")):
            db.x("UPDATE users SET lang=? WHERE id=?", (x["lang"], me["id"]))
        if "country" in x and (x["country"] or "").upper() in countries.PACKS:
            db.x("UPDATE users SET country=? WHERE id=?", (x["country"].upper(), me["id"]))
        if "pay_link" in x and re.match(r"^https://\S{4,200}$", str(x["pay_link"]) or ""):
            db.x("UPDATE users SET pay_link=? WHERE id=?", (x["pay_link"], me["id"]))
        if x.get("delete_photo"):
            ph = (db.one("SELECT photo FROM users WHERE id=?", (me["id"],)) or {}).get("photo")
            if ph:
                skills.delete_media(ph)
            db.x("UPDATE users SET photo=NULL WHERE id=?", (me["id"],))
        u = db.one("SELECT * FROM users WHERE id=?", (me["id"],))
        return {"name": more.mindy_name(u), "hue": u.get("mindy_hue"), "persona": u.get("persona"), "lang": u.get("lang") or "en"}

    @r.get("/api/me/key")
    def my_key(me=Depends(me_dep)):
        return {"button_key": mindy.button_key(me), "share_key": share_key(db, me["id"])}

    @r.get("/api/money")
    def money_summary(me=Depends(me_dep)):
        from . import money
        s = money.summary(db, me)
        return {**s, "cur": countries.for_user(db, me).get("cur") or ""}

    # ------------------------------------------------------------ Mindy-to-Mindy in the app
    async def _notify(res):
        from .handlers import deliver
        for uid, body, btns in res.get("notify") or []:
            await deliver(db, uid, body, btns, settings.reminder_template, [re.sub(r"[*_]", "", body)[:900]], title="Mindy", url="/#people")

    @r.get("/api/m2m")
    def m2m_home(me=Depends(me_dep)):
        from . import m2m
        from urllib.parse import quote
        names = {p["id"]: p["name"] for p in m2m.linked(db, me["id"])}
        who = lambda uid: names.get(uid) or (db.one("SELECT name FROM users WHERE id=?", (uid,)) or {}).get("name") or "Someone"
        import json as _j

        def taps(x):
            if x["kind"] != "poll":
                return [{"value": a, "label": l} for a, l in m2m.KINDS[x["kind"]]]
            g = db.one("SELECT options FROM m2m_group WHERE id=?", (x["group_id"],))
            return [{"value": f"o{i}", "label": o} for i, o in enumerate(_j.loads(g["options"]))] + [{"value": "none", "label": "None work"}]
        inbox = [{"id": x["id"], "from": who(x["from_uid"]), "kind": x["kind"], "text": x["text"], "taps": taps(x)}
                 for x in db.q("SELECT * FROM m2m WHERE to_uid=? AND status='open' ORDER BY id DESC LIMIT 20", (me["id"],))]
        polls = [{"id": g["id"], "question": g["question"], "text": m2m.tally_text(m2m.tally(db, g["id"])), "closed": bool(g["closed"])}
                 for g in db.q("SELECT * FROM m2m_group WHERE from_uid=? ORDER BY id DESC LIMIT 5", (me["id"],))]
        sent = [{"id": x["id"], "to": who(x["to_uid"]), "kind": x["kind"], "text": x["text"], "status": x["status"],
                 "answer": dict(m2m.KINDS[x["kind"]]).get(x["answer"]) if x["answer"] else None}
                for x in db.q("SELECT * FROM m2m WHERE from_uid=? AND kind!='poll' ORDER BY id DESC LIMIT 15", (me["id"],))]
        link = f"https://wa.me/{settings.public_wa_number}?text=" + quote(f"Hi Mindy! join {m2m.invite_code(db, me['id'])}")
        return {"people": [{"id": i, "name": n} for i, n in names.items()], "inbox": inbox, "sent": sent, "polls": polls, "link": link, "handled": m2m.handled(db, me)}

    @r.post("/api/m2m/send")
    async def m2m_send(b: Body, me=Depends(me_dep)):
        from . import m2m
        x = b.model_extra or {}
        to = next((p for p in m2m.linked(db, me["id"]) if p["id"] == x.get("to")), None)
        kind = x.get("kind")
        if not to or kind not in m2m.KINDS:
            raise HTTPException(400, "Pick one of your people.")
        text = str(x.get("text", "")).strip()[:200]
        amount = None
        if kind == "money":
            try:
                amount = float(x.get("amount"))
            except (TypeError, ValueError):
                raise HTTPException(400, "How much?")
            text = countries.money(countries.for_user(db, me), amount) + (f" for {text}" if text else "")
        elif kind == "ask":
            if len(text) < 3:
                raise HTTPException(400, "What should I ask?")
            text = text[0].upper() + text[1:].rstrip("?") + "?"
        elif kind == "decline":
            text = f"{me.get('name') or 'They'} can't make it" + (f" to {text}" if text else "") + ", and is sorry to miss it."
        res = m2m.send(db, me, to, kind, text, amount)
        await _notify(res)
        return {"reply": res["text"]}

    @r.post("/api/m2m/group")
    async def m2m_group(b: Body, me=Depends(me_dep)):
        from . import m2m
        x = b.model_extra or {}
        ids = {int(i) for i in (x.get("to") or []) if str(i).isdigit()}
        people = m2m.linked(db, me["id"])
        targets = [p for p in people if p["id"] in ids] if ids else people
        q = str(x.get("question", "")).strip()[:160]
        opts = [str(o).strip()[:20] for o in (x.get("options") or []) if str(o).strip()][:3]
        if not targets or len(q) < 3:
            raise HTTPException(400, "Pick people and write the question.")
        res = m2m.start_poll(db, me, targets, q[0].upper() + q[1:].rstrip("?") + "?", opts)
        await _notify(res)
        return {"reply": res["text"]}

    @r.post("/api/m2m/{mid}/answer")
    async def m2m_answer(mid: int, b: Body, me=Depends(me_dep)):
        from . import m2m
        row = db.one("SELECT kind FROM m2m WHERE id=? AND to_uid=?", (mid, me["id"]))
        ans = str((b.model_extra or {}).get("answer", ""))
        if not row or (row["kind"] != "poll" and ans not in dict(m2m.KINDS[row["kind"]])):
            raise HTTPException(404)
        res = m2m.on_button(db, me, f"m2m:{mid}:{ans}")
        await _notify(res)
        return {"reply": res["text"]}

    @r.get("/api/brain")
    def brain(me=Depends(me_dep)):
        return more.brain_score(db, me)

    # ------------------------------------------------------------ Brain Score share card (an image for Stories) and its page
    @r.get("/card/{key}.png")
    def card(key: str):
        u = _user_by_share(db, key)
        s = more.brain_score(db, u)
        return Response(_card_png(s["score"], s["level"], more.mindy_name(u), u.get("mindy_hue")), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=600"})

    @r.get("/s/{key}", response_class=HTMLResponse)
    def share_page(key: str):
        u = _user_by_share(db, key)
        s = more.brain_score(db, u)
        img = f"{settings.app_url.rstrip('/')}/card/{key}.png"
        wa = f"https://wa.me/{settings.public_wa_number}?text=" + "Hi%20Mindy"
        return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Brain score {s['score']} · Mindy</title><meta property=og:title content="My brain score is {s['score']} 🧠"><meta property=og:image content="{img}">
<meta property=og:description content="Mindy remembers everything so I don't have to. What's yours?"><meta name=twitter:card content=summary_large_image>
<style>body{{margin:0;background:#0B0E10;color:#F5F3EE;font-family:system-ui;display:grid;place-items:center;min-height:100vh;text-align:center;padding:20px}}
img{{width:min(360px,90vw);border-radius:24px}}a{{display:inline-block;margin-top:18px;background:#25D366;color:#0B0E10;font-weight:800;padding:14px 22px;border-radius:999px;text-decoration:none}}</style>
</head><body><div><img src="{img}" alt="Brain score {s['score']}"><br><a href="{wa}">Get your own Mindy on WhatsApp</a></div></body></html>"""

    # ------------------------------------------------------------ public number check (the Android caller-ID uses this)
    @r.get("/api/number/{num}")
    def number(num: str, request: Request):
        ip = request.client.host if request.client else "x"
        if too_many("num:" + ip, 60, 600):
            raise HTTPException(429, "Slow down.")
        info = skills.number_lookup(db, num)
        return {"verified": info["verified"], "reports": info["reports"], "label": ("Verified: " + info["verified"]) if info["verified"]
                else (f"Reported as scam by {info['reports']} people" if info["reports"] >= 2 else None)}

    # ------------------------------------------------------------ admin queues: human helpers, business verification, official handles
    def _admin(key):
        if not settings.secret_ok(settings.admin_key) or not hmac.compare_digest(str(key or ""), settings.admin_key):
            raise HTTPException(403)

    @r.get("/admin/queue")
    def queue(key: str):
        _admin(key)
        return {"help": db.q("SELECT h.*, u.name FROM help_queue h JOIN users u ON u.id=h.user_id WHERE answered_at IS NULL ORDER BY h.id"),
                "business": db.q("SELECT * FROM business_apps WHERE status='pending' ORDER BY id")}

    @r.get("/admin/fumbles", response_class=HTMLResponse)
    def fumbles(key: str, days: int = 7):
        """Every message Mindy probably didn't understand, or that errored, for launch-week fixing."""
        _admin(key)
        db.x("CREATE TABLE IF NOT EXISTS fumbles(id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT, reply TEXT, kind TEXT, created_at TEXT)")
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = db.q("SELECT kind, text, reply, created_at FROM fumbles WHERE created_at>? ORDER BY id DESC LIMIT 500", (since,))
        top = db.q("SELECT lower(text) t, COUNT(*) n FROM fumbles WHERE created_at>? GROUP BY lower(text) ORDER BY n DESC LIMIT 20", (since,))
        users = db.one("SELECT COUNT(DISTINCT user_id) n FROM messages WHERE created_at>?", (since,))["n"]
        msgs = db.one("SELECT COUNT(*) n FROM messages WHERE direction='in' AND created_at>?", (since,))["n"]
        esc = lambda x: (x or "").replace("&", "&amp;").replace("<", "&lt;")
        errs = sum(1 for r_ in rows if r_["kind"] == "error")
        return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>Mindy fumbles</title>"
                "<style>body{font:15px system-ui;margin:20px;max-width:900px}td{border-top:1px solid #ddd;padding:6px;vertical-align:top}.e{color:#b00}</style>"
                f"<h1>Last {days} days</h1><p>{users} people · {msgs} messages · <b>{len(rows)}</b> fumbled ({round(100 * len(rows) / max(msgs, 1))}%) · "
                f"<span class=e>{errs} errors</span></p><h2>Most repeated</h2><table>"
                + "".join(f"<tr><td>{t['n']}×</td><td>{esc(t['t'])}</td></tr>" for t in top)
                + "</table><h2>All</h2><table>"
                + "".join(f"<tr><td class={'e' if r_['kind'] == 'error' else ''}>{r_['kind']}</td><td>{esc(r_['text'])}</td><td>{esc(r_['reply'])}</td><td>{r_['created_at'][:16]}</td></tr>" for r_ in rows)
                + "</table>")

    @r.post("/admin/answer")
    async def answer(b: Body, key: str):
        _admin(key)
        x = b.model_extra or {}
        h = db.one("SELECT * FROM help_queue WHERE id=?", (int(x.get("id", 0)),))
        if not h:
            raise HTTPException(404)
        db.x("UPDATE help_queue SET answered_at=?, answer=? WHERE id=?", (now_iso(), str(x.get("answer", ""))[:2000], h["id"]))
        from .handlers import deliver
        used = await deliver(db, h["user_id"], "🙋 *From the Mindy team:*\n" + str(x.get("answer", "")), [], settings.reminder_template, [str(x.get("answer", ""))[:900]])
        return {"ok": True, "channel": used}

    @r.post("/admin/verify-business")
    def verify_business(b: Body, key: str):
        _admin(key)
        x = b.model_extra or {}
        num = re.sub(r"\D", "", str(x.get("number", "")))[-10:]
        db.x("INSERT OR REPLACE INTO verified_numbers(number,name,created_at) VALUES(?,?,?)", (num, str(x.get("name", ""))[:80], now_iso()))
        if x.get("app_id"):
            db.x("UPDATE business_apps SET status='verified' WHERE id=?", (int(x["app_id"]),))
        return {"ok": True}

    @r.post("/admin/official")
    def official(b: Body, key: str):
        _admin(key)
        x = b.model_extra or {}
        name_key = re.sub(r"\W+", " ", str(x.get("name", "")).lower()).strip()
        db.x("INSERT OR IGNORE INTO official_handles(name_key,url,created_at) VALUES(?,?,?)", (name_key, str(x.get("url", "")).rstrip("/"), now_iso()))
        return {"ok": True}

    return r


def _card_png(score: int, level: str, name: str, hue: int | None) -> bytes:
    """A 1080x1920 Stories card: the score, the level and the person's own Mindy colour."""
    from PIL import Image, ImageDraw, ImageFont
    import colorsys
    W, H = 1080, 1920
    h = ((hue if hue is not None else 150) % 360) / 360
    accent = tuple(int(c * 255) for c in colorsys.hls_to_rgb(h, 0.52, 0.62))
    img = Image.new("RGB", (W, H), (11, 14, 16))
    d = ImageDraw.Draw(img)
    for r_ in range(520, 0, -8):  # soft glow behind the score
        a = int(40 * (1 - r_ / 520))
        d.ellipse([W / 2 - r_, 820 - r_, W / 2 + r_, 820 + r_], fill=tuple(int(11 + (c - 11) * a / 100) for c in accent))

    def font(size, bold=True):
        for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
        return ImageFont.load_default()

    def center(y, text, f, fill):
        w = d.textlength(text, font=f)
        d.text(((W - w) / 2, y), text, font=f, fill=fill)
    center(300, "MY BRAIN SCORE", font(54), (185, 192, 198))
    center(560, str(score), font(300), (245, 243, 238))
    center(930, level, font(84), accent)
    bar_w = 760
    d.rounded_rectangle([(W - bar_w) / 2, 1110, (W + bar_w) / 2, 1140], 15, fill=(38, 44, 48))
    d.rounded_rectangle([(W - bar_w) / 2, 1110, (W - bar_w) / 2 + bar_w * min(1, score / 1000), 1140], 15, fill=accent)
    center(1300, f"{name} remembers everything", font(52, False), (245, 243, 238))
    center(1370, "so I don't have to.", font(52, False), (245, 243, 238))
    center(1700, "whatsonyourmind.online", font(44), accent)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
