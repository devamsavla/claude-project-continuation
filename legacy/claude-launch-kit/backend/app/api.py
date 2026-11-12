"""The web app's API. Every route works on the signed-in person's real data, the same data Mindy uses on
WhatsApp and Instagram."""
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import brain
from .auth import end_session, make_dependency, new_code, new_session, phone_ext, too_many, use_code
from .config import settings
from .db import DB, now_iso
from .realtime import hub, send_push, vapid

PLAN_WORDS = re.compile(r"\b(plan|hang|hangout|movie|dinner|lunch|brunch|party|watch|match|meet|nets|drinks|game night|trip|coffee|chai)\b", re.I)
MONEY = re.compile(r"(?:₹|rs\.?|inr|\$|£|€)\s?([\d,]+)|([\d,]+)\s?(?:rupees|rs|quid|pounds|dollars|euros)", re.I)


class Body(BaseModel):
    model_config = {"extra": "allow"}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def make_router(db: DB, wa, mindy) -> APIRouter:
    r = APIRouter(prefix="/api")
    me_dep = make_dependency(db)

    def friends_of(uid):
        return db.q("SELECT u.id, u.name, u.status, u.status_at, u.hue FROM friends f JOIN users u ON u.id=f.b WHERE f.a=? ORDER BY u.name", (uid,))

    def public(u):
        return {"id": u["id"], "name": u.get("name") or "You", "tz": u.get("tz"), "status": u.get("status") or "free", "hue": u.get("hue")}

    async def notify_friends(uid, event):
        await hub.send_many([f["id"] for f in friends_of(uid)], event)

    @r.get("/config")
    def config():
        """What the app needs before sign-in: Mindy's public WhatsApp number and Instagram handle."""
        return {"wa_number": settings.public_wa_number, "ig_handle": settings.public_ig_handle,
                "whatsapp_live": settings.whatsapp_live, "ai": settings.ai_live, "test_mode": settings.dev_codes}

    # ------------------------------------------------------------ sign in
    @r.post("/auth/start")
    async def auth_start(b: Body, request: Request):
        ext = phone_ext(getattr(b, "phone", "") or "")
        if not ext:
            raise HTTPException(422, "Enter your WhatsApp number with the country code, like +91 98200 00000.")
        if too_many("start:" + (request.client.host if request.client else "x"), limit=10):
            raise HTTPException(429, "Too many tries. Wait a few minutes.")
        from .handlers import tz_for
        user = db.user(ext, None, tz_for(ext), "wa")
        code = new_code(db, user["id"])
        acc = db.one("SELECT * FROM accounts WHERE ext=?", (ext,))
        recent = acc and acc["last_inbound_at"] and datetime.now(timezone.utc) - datetime.fromisoformat(acc["last_inbound_at"]) < timedelta(hours=23)
        if recent:
            await wa.text(ext, f"Your Mindy sign-in code is *{code}*. It expires in 10 minutes. If you didn't ask for it, ignore this.")
        else:
            await wa.login_code(ext, code)
        out = {"sent": "whatsapp", "hint": "Check WhatsApp for a message from Mindy."}
        if settings.dev_codes:
            out["dev_code"] = code
        return out

    @r.post("/auth/verify")
    async def auth_verify(b: Body, request: Request):
        code = re.sub(r"\D", "", str(getattr(b, "code", "") or ""))
        if too_many("verify:" + (request.client.host if request.client else "x")):
            raise HTTPException(429, "Too many tries. Wait a few minutes.")
        ext = phone_ext(getattr(b, "phone", "") or "") if getattr(b, "phone", None) else None
        uid = use_code(db, code, ext)
        if not uid:
            raise HTTPException(401, "That code didn't work. Codes last 10 minutes; ask for a new one.")
        token = new_session(db, uid)
        invite = getattr(b, "invite", None)
        if invite:
            await _accept(uid, invite)
        return {"token": token, "me": public(db.one("SELECT * FROM users WHERE id=?", (uid,)))}

    @r.post("/auth/logout")
    def logout(request: Request, me=Depends(me_dep)):
        end_session(db, (request.headers.get("authorization") or "").removeprefix("Bearer ").strip())
        return {"ok": True}

    # ------------------------------------------------------------ me
    @r.get("/me")
    def get_me(me=Depends(me_dep)):
        chans = [a["channel"] for a in db.accounts(me["id"])]
        return {**public(me), "channels": chans, "notify": me.get("notify") or "both",
                "push": bool(db.one("SELECT 1 FROM push_subs WHERE user_id=?", (me["id"],)))}

    @r.patch("/me")
    async def patch_me(b: Body, me=Depends(me_dep)):
        d = b.model_dump()
        if "name" in d and d["name"] and str(d["name"]).strip()[:40] != me.get("name"):
            db.x("UPDATE users SET name=? WHERE id=?", (str(d["name"]).strip()[:40], me["id"]))
            await notify_friends(me["id"], {"type": "friend.update", "user": me["id"], "name": str(d["name"]).strip()[:40]})
        if d.get("tz"):
            if d["tz"] not in available_timezones():
                raise HTTPException(422, "Unknown time zone.")
            db.x("UPDATE users SET tz=? WHERE id=?", (d["tz"], me["id"]))
        if d.get("status") in ("free", "study", "game", "match", "busy", "ghost"):
            db.x("UPDATE users SET status=?, status_at=? WHERE id=?", (d["status"], now_iso(), me["id"]))
            shown = "ghost" if d["status"] == "ghost" else d["status"]
            await notify_friends(me["id"], {"type": "status", "user": me["id"], "status": shown})
        if d.get("notify") in ("app", "whatsapp", "both"):
            db.x("UPDATE users SET notify=? WHERE id=?", (d["notify"], me["id"]))
        return get_me(db.one("SELECT * FROM users WHERE id=?", (me["id"],)))

    @r.post("/link-code")
    def link_code(me=Depends(me_dep)):
        """A code to join this account with Instagram (send `link 123456` to Mindy there)."""
        return {"code": db.link_code(me["id"])}

    # ------------------------------------------------------------ home
    @r.get("/home")
    def home(me=Depends(me_dep)):
        fr = friends_of(me["id"])
        for f in fr:
            f["online"] = hub.online(f["id"])
            if f["status"] == "ghost":
                f["status"], f["online"] = "away", False
        today = datetime.now(ZoneInfo(me["tz"])).date().isoformat()
        return {"me": public(me), "friends": fr, "reminders": db.upcoming(me["id"], 5),
                "items": db.q("SELECT * FROM items WHERE user_id=? ORDER BY id DESC LIMIT 6", (me["id"],)),
                "plans": _plans(me["id"], 3), "mood": db.one("SELECT * FROM moods WHERE user_id=? AND day=?", (me["id"], today)),
                "unread": _unread(me["id"])}

    # ------------------------------------------------------------ reminders
    @r.get("/reminders")
    def reminders(me=Depends(me_dep)):
        return db.q("SELECT * FROM reminders WHERE user_id=? AND status IN ('pending','sent','undelivered') ORDER BY status='pending' DESC, due_at LIMIT 100", (me["id"],))

    @r.post("/reminders")
    async def add_reminder(b: Body, me=Depends(me_dep)):
        text = (getattr(b, "text", "") or "").strip()
        rr = await asyncio.to_thread(brain.route, text if re.match(r"^(remind|reminder)", text, re.I) else "remind me " + text, me["tz"])
        due = rr.get("due") or brain.parse_when(text, me["tz"])
        if not due:
            raise HTTPException(422, "When? Add a time like “tomorrow 9am”, “Friday 6pm” or “in 2 hours”.")
        rep = rr.get("repeat") if rr.get("repeat") not in (None, "none") else None
        rid = db.add_reminder(me["id"], rr.get("text") or brain.strip_when(text), iso(due), rep)
        return db.one("SELECT * FROM reminders WHERE id=?", (rid,))

    @r.post("/reminders/{rid}/done")
    def done(rid: int, me=Depends(me_dep)):
        db.x("UPDATE reminders SET status='done' WHERE id=? AND user_id=?", (rid, me["id"]))
        return {"ok": True}

    @r.post("/reminders/{rid}/snooze")
    def snooze(rid: int, b: Body, me=Depends(me_dep)):
        mins = max(5, min(int(getattr(b, "minutes", 60) or 60), 60 * 24 * 7))
        row = db.one("SELECT * FROM reminders WHERE id=? AND user_id=?", (rid, me["id"]))
        if not row:
            raise HTTPException(404, "Reminder not found.")
        db.x("UPDATE reminders SET status='pending', due_at=? WHERE id=?", (iso(datetime.now(timezone.utc) + timedelta(minutes=mins)), rid))
        return db.one("SELECT * FROM reminders WHERE id=?", (rid,))

    @r.delete("/reminders/{rid}")
    def cancel(rid: int, me=Depends(me_dep)):
        db.x("UPDATE reminders SET status='cancelled' WHERE id=? AND user_id=?", (rid, me["id"]))
        return {"ok": True}

    # ------------------------------------------------------------ saves (WhatsApp, Instagram and app, all together)
    @r.get("/items")
    def items(q: str = "", collection: str = "", me=Depends(me_dep)):
        if q:
            return db.search(me["id"], q, 40)
        if collection:
            return db.q("SELECT * FROM items WHERE user_id=? AND collection=? ORDER BY id DESC LIMIT 100", (me["id"], collection))
        return db.q("SELECT * FROM items WHERE user_id=? ORDER BY id DESC LIMIT 100", (me["id"],))

    @r.get("/collections")
    def collections(me=Depends(me_dep)):
        return db.q("SELECT collection, COUNT(*) n FROM items WHERE user_id=? GROUP BY collection ORDER BY n DESC", (me["id"],))

    @r.post("/items")
    async def add_item(b: Body, me=Depends(me_dep)):
        text = (getattr(b, "text", "") or "").strip()
        if not text:
            raise HTTPException(422, "Nothing to save.")
        rr = await asyncio.to_thread(brain.route, text, me["tz"]) if settings.ai_live else brain.route_rules(text)
        um = brain.URL_RE.search(text)
        url = um.group(0) if um else None
        coll = rr.get("collection") or ("Reels" if url and "instagram.com" in url else "Links" if url else "Notes")
        iid = db.save_item(me["id"], "reel" if url and "instagram.com" in url else "link" if url else "note", text, url=url, collection=coll, tags=rr.get("tags"))
        return db.one("SELECT * FROM items WHERE id=?", (iid,))

    @r.delete("/items/{iid}")
    def del_item(iid: int, me=Depends(me_dep)):
        db.x("DELETE FROM items WHERE id=? AND user_id=?", (iid, me["id"]))
        return {"ok": True}

    @r.post("/items/{iid}/recipe")
    async def recipe(iid: int, me=Depends(me_dep)):
        it = db.one("SELECT * FROM items WHERE id=? AND user_id=?", (iid, me["id"]))
        if not it:
            raise HTTPException(404, "Not found.")
        if not settings.ai_live:
            raise HTTPException(503, "Recipe cards need the AI key (ANTHROPIC_API_KEY) switched on.")
        out = await asyncio.to_thread(brain.recipe_from, it["text"])
        return out

    @r.post("/ask")
    async def ask(b: Body, me=Depends(me_dep)):
        q = (getattr(b, "q", "") or "").strip()
        found = db.search(me["id"], q)
        return {"answer": await asyncio.to_thread(brain.answer, q, found), "items": found}

    # ------------------------------------------------------------ lists and birthdays
    @r.get("/lists")
    def lists(me=Depends(me_dep)):
        out = []
        for l in db.q("SELECT * FROM lists WHERE user_id=? ORDER BY name", (me["id"],)):
            out.append({**l, "items": db.q("SELECT * FROM list_items WHERE list_id=? ORDER BY done, id", (l["id"],))})
        return out

    @r.post("/lists/{name}/items")
    def list_add(name: str, b: Body, me=Depends(me_dep)):
        entries = [e.strip() for e in re.split(r",| and ", getattr(b, "text", "") or "") if e.strip()]
        if not entries:
            raise HTTPException(422, "Type something to add.")
        db.list_add(me["id"], name, entries)
        return lists(me)

    @r.post("/list-items/{lid}/toggle")
    def list_toggle(lid: int, me=Depends(me_dep)):
        row = db.one("SELECT li.* FROM list_items li JOIN lists l ON l.id=li.list_id WHERE li.id=? AND l.user_id=?", (lid, me["id"]))
        if not row:
            raise HTTPException(404, "Not found.")
        db.x("UPDATE list_items SET done=? WHERE id=?", (0 if row["done"] else 1, lid))
        return {"ok": True}

    @r.get("/occasions")
    def occasions(me=Depends(me_dep)):
        return db.q("SELECT * FROM occasions WHERE user_id=? ORDER BY month, day", (me["id"],))

    # ------------------------------------------------------------ the bubble: say anything, Mindy does it
    @r.post("/think")
    async def think(b: Body, me=Depends(me_dep)):
        text = (getattr(b, "text", "") or "").strip()
        if not text:
            raise HTTPException(422, "Say something first.")
        return await mindy_do(me, text)

    async def mindy_do(me, text, chat_id=None):
        did, reply = [], None
        low = text.lower()
        fr = friends_of(me["id"])
        named = [f for f in fr if f["name"] and re.search(rf"\b{re.escape(f['name'].split()[0].lower())}\b", low)]
        when = brain.parse_when(text, me["tz"])
        rr = await asyncio.to_thread(brain.route, text, me["tz"])
        if PLAN_WORDS.search(low) and (named or chat_id or "with" in low):
            title = brain.strip_when(re.sub(r"(?i)@?mindy,?\s*", "", text)).split(" with ")[0]
            title = re.sub(r"(?i)\b(on |this |next )?(mon|tues|wednes|thurs|fri|satur|sun)day\b|\b(tonight|tomorrow|today)\b", "", title)
            title = re.sub(r"(?i)^(let'?s\s+)?(make a plan for|make a plan|plan|organi[sz]e)\s+(a\s+)?", "", title.strip())
            title = re.sub(r"\s{2,}", " ", title).strip(" ,.-")[:60] or "Plan"
            title = title[0].upper() + title[1:]
            at = re.search(r"\bat ((?:[A-Z][\w'&]*\s?){1,4})", text)
            if at and at.group(1).strip().lower() not in title.lower():
                title = f"{title} at {at.group(1).strip()}"[:60]
            people = [f["id"] for f in named]
            if chat_id:
                people = [m["user_id"] for m in db.q("SELECT user_id FROM chat_members WHERE chat_id=? AND user_id!=?", (chat_id, me["id"]))]
            pid = _new_plan(me, title, when, people, chat_id)
            did.append({"kind": "plan", "id": pid, "title": title, "when": iso(when) if when else None, "with": [f["name"] for f in named]})
        m = MONEY.search(text)
        if m and re.search(r"\b(pay|owe|split|send|transfer)\b", low):
            amt = (m.group(1) or m.group(2)).replace(",", "")
            if "split" in low and chat_id:
                n = db.one("SELECT COUNT(*) n FROM chat_members WHERE chat_id=?", (chat_id,))["n"] or 1
                sym = re.match(r"[^\d\s]*", m.group(0).strip()).group(0).strip() if m.group(1) else ""
                did.append({"kind": "split", "amount": sym + f"{int(amt):,}", "each": sym + f"{round(int(amt) / n, 2):,g}", "people": n})
            else:
                who = named[0]["name"] if named else "them"
                rid = db.add_reminder(me["id"], f"Pay {who} {m.group(0).strip()}", iso(when or datetime.now(ZoneInfo(me["tz"])).replace(hour=10, minute=0, second=0) + timedelta(days=1)))
                did.append({"kind": "remind", "id": rid, "title": f"Pay {who} {m.group(0).strip()}"})
        intent = rr.get("intent")
        if not did or intent in ("remind", "list_add", "occasion"):
            if intent == "remind" and rr.get("due") and not any(d["kind"] == "remind" for d in did):
                rep = rr.get("repeat") if rr.get("repeat") not in (None, "none") else None
                rid = db.add_reminder(me["id"], rr.get("text") or text, iso(rr["due"]), rep)
                did.append({"kind": "remind", "id": rid, "title": rr.get("text") or text, "when": iso(rr["due"]), "repeat": rep})
            elif intent == "list_add":
                name, _ = db.list_add(me["id"], rr.get("list_name") or "Shopping", rr.get("list_entries") or [])
                did.append({"kind": "list", "list": name, "added": rr.get("list_entries")})
            elif intent == "occasion" and rr.get("month"):
                db.add_occasion(me["id"], rr.get("person"), rr.get("occasion_kind") or "birthday", rr["month"], rr["day"])
                did.append({"kind": "occasion", "person": rr.get("person"), "day": rr["day"], "month": rr["month"]})
            elif intent == "ask" and not did:
                found = db.search(me["id"], rr.get("text") or text)
                reply = await asyncio.to_thread(brain.answer, text, found)
            elif intent in ("save",) and not did and not chat_id:
                um = brain.URL_RE.search(text)
                url = um.group(0) if um else None
                iid = db.save_item(me["id"], "link" if url else "note", text, url=url, collection=rr.get("collection") or "Notes", tags=rr.get("tags"))
                did.append({"kind": "save", "id": iid, "collection": rr.get("collection") or "Notes"})
            elif intent == "help":
                reply = "I can plan with friends, set reminders in any time zone, keep lists and birthdays, save anything, and find it again. Try “movie night Friday 9pm with Zoya”."
        if not reply:
            reply = describe(did, me["tz"]) if did else ("Tell me what you want to do, like “dinner Saturday 8pm with Priya” or “remind me to call mum at 7pm IST”."
                                                         if chat_id is None else "On it. I can plan, split, remind or start a game. Try “@mindy plan Friday 9pm”.")
        return {"reply": reply, "did": did}

    def describe(did, tz):
        parts = []
        for d in did:
            when = ""
            if d.get("when"):
                w = datetime.fromisoformat(d["when"]).astimezone(ZoneInfo(tz))
                when = f" for {w:%a} {w.day} {w:%b}, {w:%H:%M}"
            if d["kind"] == "plan":
                parts.append(f"🗓️ Plan made: {d['title']}{when}" + (f" with {', '.join(d['with'])}" if d.get("with") else "") + ". Invites sent.")
            elif d["kind"] == "remind":
                parts.append(f"⏰ Reminder set: {d['title']}{when}.")
            elif d["kind"] == "split":
                parts.append(f"💸 {d['amount']} between {d['people']} is {d['each']} each.")
            elif d["kind"] == "list":
                parts.append(f"🛒 Added to {d['list']}.")
            elif d["kind"] == "occasion":
                parts.append(f"🎂 Saved {d['person']}'s day: {d['day']}/{d['month']}.")
            elif d["kind"] == "save":
                parts.append(f"🧠 Saved to {d['collection']}.")
        return " ".join(parts)

    # ------------------------------------------------------------ friends
    @r.get("/invite")
    def invite(request: Request, me=Depends(me_dep)):
        row = db.one("SELECT code FROM invites WHERE user_id=?", (me["id"],))
        if not row:
            import secrets
            code = secrets.token_urlsafe(6)
            db.x("INSERT INTO invites(code,user_id,created_at) VALUES(?,?,?)", (code, me["id"], now_iso()))
        else:
            code = row["code"]
        base = str(request.base_url).rstrip("/")
        return {"code": code, "url": f"{base}/?invite={code}"}

    async def _accept(uid, code):
        row = db.one("SELECT user_id FROM invites WHERE code=?", (code,))
        if not row or row["user_id"] == uid:
            return None
        other = row["user_id"]
        for a, b2 in ((uid, other), (other, uid)):
            db.x("INSERT OR IGNORE INTO friends(a,b,created_at) VALUES(?,?,?)", (a, b2, now_iso()))
        me_name = (db.one("SELECT name FROM users WHERE id=?", (uid,)) or {}).get("name") or "A friend"
        await hub.send(other, {"type": "friend.new", "user": uid, "name": me_name})
        return other

    @r.post("/friends/accept")
    async def accept(b: Body, me=Depends(me_dep)):
        other = await _accept(me["id"], getattr(b, "code", ""))
        if not other:
            raise HTTPException(404, "That invite link didn't work.")
        return {"ok": True, "friends": friends_of(me["id"])}

    @r.get("/friends")
    def friends(me=Depends(me_dep)):
        fr = friends_of(me["id"])
        for f in fr:
            f["online"] = hub.online(f["id"]) and f["status"] != "ghost"
            if f["status"] == "ghost":
                f["status"] = "away"
        return fr

    @r.delete("/friends/{fid}")
    def unfriend(fid: int, me=Depends(me_dep)):
        db.x("DELETE FROM friends WHERE (a=? AND b=?) OR (a=? AND b=?)", (me["id"], fid, fid, me["id"]))
        return {"ok": True}

    # ------------------------------------------------------------ chats
    def _unread(uid):
        return db.one("SELECT COUNT(*) n FROM chat_messages m JOIN chat_members cm ON cm.chat_id=m.chat_id AND cm.user_id=? "
                      "WHERE m.id>cm.last_read AND COALESCE(m.user_id,-1)!=?", (uid, uid))["n"]

    @r.get("/chats")
    def chats(me=Depends(me_dep)):
        rows = db.q("SELECT c.*, cm.last_read FROM chats c JOIN chat_members cm ON cm.chat_id=c.id WHERE cm.user_id=?", (me["id"],))
        out = []
        for c in rows:
            members = db.q("SELECT u.id, u.name FROM chat_members cm JOIN users u ON u.id=cm.user_id WHERE cm.chat_id=?", (c["id"],))
            last = db.one("SELECT * FROM chat_messages WHERE chat_id=? ORDER BY id DESC LIMIT 1", (c["id"],))
            unread = db.one("SELECT COUNT(*) n FROM chat_messages WHERE chat_id=? AND id>? AND COALESCE(user_id,-1)!=?", (c["id"], c["last_read"], me["id"]))["n"]
            name = c["name"] or ", ".join(m["name"] or "Friend" for m in members if m["id"] != me["id"]) or "Just you"
            out.append({"id": c["id"], "name": name, "is_group": c["is_group"], "members": members, "last": last, "unread": unread})
        out.sort(key=lambda c: (c["last"] or {}).get("id", 0), reverse=True)
        return out

    @r.post("/chats")
    def new_chat(b: Body, me=Depends(me_dep)):
        allowed = {f["id"] for f in friends_of(me["id"])}
        members = sorted({int(x) for x in getattr(b, "members", []) or [] if int(x) in allowed})
        if not members:
            raise HTTPException(422, "Pick at least one friend.")
        if len(members) == 1:
            ex = db.one("SELECT c.id FROM chats c WHERE c.is_group=0 AND (SELECT COUNT(*) FROM chat_members WHERE chat_id=c.id)=2 "
                        "AND EXISTS(SELECT 1 FROM chat_members WHERE chat_id=c.id AND user_id=?) AND EXISTS(SELECT 1 FROM chat_members WHERE chat_id=c.id AND user_id=?)",
                        (me["id"], members[0]))
            if ex:
                return {"id": ex["id"]}
        cid = db.x("INSERT INTO chats(name,is_group,created_at) VALUES(?,?,?)", ((getattr(b, "name", "") or "")[:60] or None, int(len(members) > 1), now_iso()))
        for u in [me["id"]] + members:
            db.x("INSERT INTO chat_members(chat_id,user_id) VALUES(?,?)", (cid, u))
        return {"id": cid}

    def _member(cid, uid):
        if not db.one("SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?", (cid, uid)):
            raise HTTPException(404, "Chat not found.")

    @r.get("/chats/{cid}/messages")
    def messages(cid: int, after: int = 0, me=Depends(me_dep)):
        _member(cid, me["id"])
        rows = db.q("SELECT m.*, u.name FROM chat_messages m LEFT JOIN users u ON u.id=m.user_id WHERE m.chat_id=? AND m.id>? ORDER BY m.id DESC LIMIT 200", (cid, after))[::-1]
        if rows:
            db.x("UPDATE chat_members SET last_read=? WHERE chat_id=? AND user_id=?", (rows[-1]["id"], cid, me["id"]))
        return rows

    async def post_message(cid, uid, body, kind="text"):
        mid = db.x("INSERT INTO chat_messages(chat_id,user_id,body,kind,created_at) VALUES(?,?,?,?,?)", (cid, uid, body, kind, now_iso()))
        msg = db.one("SELECT m.*, u.name FROM chat_messages m LEFT JOIN users u ON u.id=m.user_id WHERE m.id=?", (mid,))
        if uid is None:
            msg["name"] = "Mindy"
        members = [m["user_id"] for m in db.q("SELECT user_id FROM chat_members WHERE chat_id=?", (cid,))]
        await hub.send_many(members, {"type": "chat.message", "chat": cid, "message": msg})
        return msg

    @r.post("/chats/{cid}/messages")
    async def send(cid: int, b: Body, me=Depends(me_dep)):
        _member(cid, me["id"])
        body = (getattr(b, "body", "") or "").strip()[:4000]
        if not body:
            raise HTTPException(422, "Empty message.")
        msg = await post_message(cid, me["id"], body)
        db.x("UPDATE chat_members SET last_read=? WHERE chat_id=? AND user_id=?", (msg["id"], cid, me["id"]))
        if re.search(r"@mindy\b", body, re.I):
            res = await mindy_do(me, body, chat_id=cid)
            await post_message(cid, None, res["reply"], "mindy")
        return msg

    # ------------------------------------------------------------ plans
    def _new_plan(me, title, when, people, chat_id=None):
        pid = db.x("INSERT INTO plans(title,when_at,created_by,chat_id,created_at) VALUES(?,?,?,?,?)", (title, iso(when) if when else None, me["id"], chat_id, now_iso()))
        db.x("INSERT INTO plan_people(plan_id,user_id,rsvp) VALUES(?,?,'going')", (pid, me["id"]))
        for u in people:
            db.x("INSERT OR IGNORE INTO plan_people(plan_id,user_id) VALUES(?,?)", (pid, u))
        asyncio.create_task(hub.send_many(people, {"type": "plan.invite", "plan": pid, "title": title, "from": me.get("name") or "A friend"}))
        return pid

    def _plans(uid, limit=50):
        rows = db.q("SELECT p.*, pp.rsvp FROM plans p JOIN plan_people pp ON pp.plan_id=p.id WHERE pp.user_id=? AND (p.when_at IS NULL OR p.when_at>?) ORDER BY p.when_at IS NULL, p.when_at LIMIT ?",
                    (uid, iso(datetime.now(timezone.utc) - timedelta(hours=6)), limit))
        for p in rows:
            p["people"] = db.q("SELECT u.id, u.name, pp.rsvp FROM plan_people pp JOIN users u ON u.id=pp.user_id WHERE pp.plan_id=?", (p["id"],))
        return rows

    @r.get("/plans")
    def plans(me=Depends(me_dep)):
        return _plans(me["id"])

    @r.post("/plans")
    async def add_plan(b: Body, me=Depends(me_dep)):
        title = (getattr(b, "title", "") or "").strip()
        if not title:
            raise HTTPException(422, "What's the plan?")
        allowed = {f["id"] for f in friends_of(me["id"])}
        people = [int(x) for x in getattr(b, "people", []) or [] if int(x) in allowed]
        when = brain.parse_when(getattr(b, "when", "") or title, me["tz"])
        pid = _new_plan(me, title, when, people)
        return next(p for p in _plans(me["id"]) if p["id"] == pid)

    @r.post("/plans/{pid}/rsvp")
    def rsvp(pid: int, b: Body, me=Depends(me_dep)):
        v = getattr(b, "rsvp", "")
        if v not in ("going", "maybe", "no"):
            raise HTTPException(422, "Choose going, maybe or no.")
        if not db.one("SELECT 1 FROM plan_people WHERE plan_id=? AND user_id=?", (pid, me["id"])):
            raise HTTPException(404, "Plan not found.")
        db.x("UPDATE plan_people SET rsvp=? WHERE plan_id=? AND user_id=?", (v, pid, me["id"]))
        return {"ok": True}

    # ------------------------------------------------------------ mind: check-ins, passport, charts
    @r.post("/moods")
    def mood(b: Body, me=Depends(me_dep)):
        day = datetime.now(ZoneInfo(me["tz"])).date().isoformat()
        m, e = int(getattr(b, "mood", 3)), getattr(b, "energy", None)
        db.x("INSERT INTO moods(user_id,day,mood,energy) VALUES(?,?,?,?) ON CONFLICT(user_id,day) DO UPDATE SET mood=excluded.mood, energy=COALESCE(excluded.energy, moods.energy)",
             (me["id"], day, max(1, min(m, 5)), int(e) if e else None))
        return db.one("SELECT * FROM moods WHERE user_id=? AND day=?", (me["id"], day))

    @r.get("/stamps")
    def stamps(me=Depends(me_dep)):
        return db.q("SELECT * FROM stamps WHERE user_id=? ORDER BY id DESC", (me["id"],))

    @r.post("/stamps")
    def add_stamp(b: Body, me=Depends(me_dep)):
        kind = getattr(b, "kind", "city")
        title = (getattr(b, "title", "") or "").strip()[:40]
        if kind not in ("country", "city", "cafe", "people", "wish") or not title:
            raise HTTPException(422, "Choose a kind and a name.")
        sid = db.x("INSERT INTO stamps(user_id,kind,title,place,created_at) VALUES(?,?,?,?,?)", (me["id"], kind, title, (getattr(b, "place", "") or "")[:60], now_iso()))
        return db.one("SELECT * FROM stamps WHERE id=?", (sid,))

    @r.delete("/stamps/{sid}")
    def del_stamp(sid: int, me=Depends(me_dep)):
        db.x("DELETE FROM stamps WHERE id=? AND user_id=?", (sid, me["id"]))
        return {"ok": True}

    @r.get("/stats")
    def stats(me=Depends(me_dep)):
        now = datetime.now(timezone.utc)
        weeks = []
        for w in range(5, -1, -1):
            a, z = iso(now - timedelta(weeks=w + 1)), iso(now - timedelta(weeks=w))
            row = db.one("SELECT SUM(status='done') d, COUNT(*) n FROM reminders WHERE user_id=? AND due_at>? AND due_at<=? AND status!='cancelled'", (me["id"], a, z))
            weeks.append({"label": "now" if w == 0 else f"-{w}w", "done": row["d"] or 0, "total": row["n"] or 0})
        tz = ZoneInfo(me["tz"])
        days = [(datetime.now(tz).date() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
        moods = {r["day"]: r for r in db.q("SELECT * FROM moods WHERE user_id=? AND day>=?", (me["id"], days[0]))}
        return {"reminders": weeks, "collections": collections(me), "moods": [{"day": d, "mood": (moods.get(d) or {}).get("mood")} for d in days],
                "saved_total": db.one("SELECT COUNT(*) n FROM items WHERE user_id=?", (me["id"],))["n"]}

    # ------------------------------------------------------------ phone notifications
    @r.get("/push/key")
    def push_key(me=Depends(me_dep)):
        return {"key": vapid(db)[1]}

    @r.post("/push/subscribe")
    def push_sub(b: Body, me=Depends(me_dep)):
        sub = getattr(b, "subscription", None)
        if not sub or "endpoint" not in sub:
            raise HTTPException(422, "Bad subscription.")
        db.x("INSERT OR REPLACE INTO push_subs(endpoint,user_id,sub,created_at) VALUES(?,?,?,?)", (sub["endpoint"], me["id"], json.dumps(sub), now_iso()))
        return {"ok": True}

    @r.post("/push/test")
    def push_test(me=Depends(me_dep)):
        return {"sent": send_push(db, me["id"], "Mindy 🧠", "Notifications are on. I'll only ping you about things you asked for.")}

    # ------------------------------------------------------------ your data
    @r.get("/export")
    def export(me=Depends(me_dep)):
        data = db.export_user(me["id"])
        data["lists"] = lists(me)
        data["stamps"] = stamps(me)
        data["moods"] = db.q("SELECT * FROM moods WHERE user_id=?", (me["id"],))
        return JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="mindy-export.json"'})

    @r.post("/delete-account")
    def delete_account(b: Body, me=Depends(me_dep)):
        if getattr(b, "confirm", "") != "DELETE":
            raise HTTPException(422, "Type DELETE to confirm.")
        for t, col in (("sessions", "user_id"), ("moods", "user_id"), ("stamps", "user_id"), ("push_subs", "user_id"), ("invites", "user_id"), ("chat_members", "user_id"), ("plan_people", "user_id")):
            db.x(f"DELETE FROM {t} WHERE {col}=?", (me["id"],))
        db.x("DELETE FROM friends WHERE a=? OR b=?", (me["id"], me["id"]))
        db.delete_user(me["id"])
        return {"ok": True}

    r.mindy_do = mindy_do
    r.post_message = post_message
    return r
