"""Mindy-to-Mindy: your Mindy talks to their Mindy, so you don't have to have the awkward conversation.

Each person has their own Mindy. A request (money owed, "are you free Saturday?", "did you reach home?", "can't make it")
goes from the asker's Mindy to the other person's Mindy, which asks them with tap answers and carries the reply back.
If the other person has no Mindy yet, the asker gets a ready message to forward that asks the question AND invites them:
every request is also how Mindy spreads. Only people you are linked to (friends or family) can reach you this way,
and anyone can mute a person."""
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from . import care, countries
from .config import settings
from .db import DB, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS m2m(id INTEGER PRIMARY KEY, from_uid INTEGER, to_uid INTEGER, kind TEXT, text TEXT, amount REAL,
  status TEXT DEFAULT 'open', answer TEXT, created_at TEXT, answered_at TEXT);
CREATE TABLE IF NOT EXISTS m2m_mute(user_id INTEGER, other INTEGER, PRIMARY KEY(user_id, other));
"""
KINDS = {
    "money": [("paid", "✅ Paid"), ("tomorrow", "⏰ Tomorrow"), ("talk", "💬 Let's talk")],
    "ask": [("yes", "👍 Yes"), ("no", "👎 No"), ("later", "⏳ Tell you later")],
    "safe": [("yes", "💚 All good"), ("call", "📞 Call me")],
    "decline": [("ok", "👍 No worries"), ("sad", "🥺 Next time!")],
}
ANSWER_TEXT = {"paid": "says it's *paid* ✅", "tomorrow": "will pay *tomorrow* ⏰", "talk": "wants to *talk about it* 💬", "yes": "says *yes* 👍",
               "no": "says *no* 👎", "later": "will *tell you later* ⏳", "call": "asks you to *call them* 📞", "ok": "says *no worries* 👍", "sad": "says *next time!* 🥺"}


def init(db: DB):
    with db.lock:
        db.conn.executescript(SCHEMA)
        db.conn.commit()


def R(text, **kw):
    return {"text": text, **kw}


def linked(db: DB, uid: int) -> list[dict]:
    rows = db.q("SELECT u.id, u.name FROM friends f JOIN users u ON u.id=f.b WHERE f.a=?", (uid,)) + care.family_of(db, uid)
    seen, out = set(), []
    for r in rows:
        if r["id"] not in seen and r["id"] != uid:
            seen.add(r["id"])
            out.append({"id": r["id"], "name": r["name"] or ""})
    return out


def find(db: DB, uid: int, name: str) -> dict | None:
    n = name.strip().lower()
    n = {"mum": "mum", "mom": "mum", "mummy": "mum", "maa": "mum", "dad": "dad", "papa": "dad"}.get(n, n)
    people = linked(db, uid)
    return next((p for p in people if p["name"].lower() == n), None) or next((p for p in people if p["name"].lower().split(" ")[0] == n), None) \
        or next((p for p in people if n and n in p["name"].lower()), None)


def invite_code(db: DB, uid: int) -> str:
    row = db.one("SELECT code FROM invites WHERE user_id=?", (uid,))
    if row:
        return row["code"]
    code = secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")[:8]
    db.x("INSERT INTO invites(code,user_id,created_at) VALUES(?,?,?)", (code, uid, now_iso()))
    return code


def join(db: DB, user: dict, code: str) -> dict | None:
    row = db.one("SELECT user_id FROM invites WHERE code=?", (code.strip(),))
    if not row or row["user_id"] == user["id"]:
        return None
    for a, b in ((user["id"], row["user_id"]), (row["user_id"], user["id"])):
        db.x("INSERT OR IGNORE INTO friends(a,b,created_at) VALUES(?,?,?)", (a, b, now_iso()))
    other = db.one("SELECT name FROM users WHERE id=?", (row["user_id"],)) or {}
    return R(f"🤝 You and *{other.get('name') or 'your friend'}* are linked. Now your Mindys can talk: try _ask {(other.get('name') or 'them').split(' ')[0]} if they're free Saturday_.",
             notify=[(row["user_id"], f"🤝 *{user.get('name') or 'Your friend'}* joined with your link. Your Mindys can talk now.", [])])


def send(db: DB, user: dict, to: dict, kind: str, text: str, amount: float | None = None) -> dict:
    """Creates the request and returns the reply for the asker plus the notification for the other person's Mindy."""
    me = user.get("name") or "Your friend"
    if db.one("SELECT 1 FROM m2m_mute WHERE user_id=? AND other=?", (to["id"], user["id"])):
        return R(f"{to['name']} has paused requests from you on Mindy. Best to talk to them directly.")
    day = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    if db.one("SELECT COUNT(*) n FROM m2m WHERE from_uid=? AND to_uid=? AND created_at>?", (user["id"], to["id"], day))["n"] >= 5:
        return R(f"That's a lot of nudges for {to['name']} today. I'll hold this one; try again tomorrow.")
    mid = db.x("INSERT INTO m2m(from_uid,to_uid,kind,text,amount,created_at) VALUES(?,?,?,?,?,?)", (user["id"], to["id"], kind, text, amount, now_iso()))
    body = {"money": f"💸 *{me}'s Mindy here.* A gentle nudge: {text}. No rush, just tap one:",
            "ask": f"💬 *{me}'s Mindy here.* {me} asks: {text}",
            "safe": f"💚 *{me}'s Mindy here.* {me} wants to know you're OK. {text}".strip(),
            "decline": f"💌 *{me}'s Mindy here.* {text}"}[kind]
    buttons = [(f"m2m:{mid}:{a}", label) for a, label in KINDS[kind]]
    done = {"money": f"💸 Done. My Mindy asked {to['name']}'s Mindy, politely. I'll tell you what they say.",
            "ask": f"💬 Asked {to['name']}'s Mindy. I'll bring back the answer.",
            "safe": f"💚 Checking with {to['name']}'s Mindy. I'll tell you as soon as they tap.",
            "decline": f"💌 Told {to['name']}, kindly, so you don't have to."}[kind]
    return R(done, notify=[(to["id"], body, buttons)])


def forward_invite(db: DB, user: dict, name: str, kind: str, text: str) -> dict:
    """They are not on Mindy yet: give the asker a message to forward that carries the ask and the invite."""
    code = invite_code(db, user["id"])
    link = f"https://wa.me/{settings.public_wa_number}?text=" + quote(f"Hi Mindy! join {code}")
    me = user.get("name") or "me"
    msg = {"money": f"Hi {name}! My assistant Mindy is nudging you for me 😄: {text}. Tap to answer in one tap (and get your own Mindy): {link}",
           "ask": f"Hi {name}! {text} Answer in one tap through my Mindy (and get your own): {link}",
           "safe": f"Hi {name}! Just checking you're OK 💚 Tap to tell my Mindy: {link}",
           "decline": f"Hi {name}! {text}"}[kind]
    return R(f"{name} doesn't have a Mindy yet, so I can't ask theirs. Forward this and they're linked to you the moment they tap:",
             links=[(f"Send to {name}", "https://wa.me/?text=" + quote(msg))])


ASK_MONEY = re.compile(r"^(?:ask|nudge|remind|tell)\s+([a-z][a-z .']{0,24}?)\s+(?:for|about|to pay(?: me)?(?: back)?|to return)\s+(?:the\s+|my\s+)?(?:₹|rs\.?|\$|£|€)?\s*(\d[\d,]*)(?:\s*(?:rs|rupees|bucks|quid|pounds|dollars))?(?:\s+(?:for|from)\s+(.+))?$", re.I)
ASK_ANY = re.compile(r"^ask\s+([a-z][a-z .']{0,24}?)\s+(if|whether|when|what|where|to|can|could|is|are|will|did|do|does)\b\s*(.+)$", re.I)
SAFE = re.compile(r"^(?:(?:check on|check in on)\s+([a-z][a-z .']{0,24}?)|is\s+([a-z][a-z .']{0,24}?)\s+(?:ok|okay|fine|safe|home|alright))\??$", re.I)
DECLINE = re.compile(r"^(?:tell|let)\s+([a-z][a-z .']{0,24}?)\s+(?:know\s+)?(?:that\s+)?i\s+(?:can'?t|cannot|won'?t be able to)\s+(?:make it|come|join|attend)(?:\s+(?:to|for)\s+(.+))?$", re.I)


def handle(db: DB, user: dict, text: str) -> dict | None:
    t = text.strip()
    low = t.lower()
    m = re.match(r"^(?:hi mindy!?\s*)?join\s+([\w]{6,10})$", t, re.I)
    if m:
        return join(db, user, m.group(1)) or R("That invite code didn't work. Ask them to send it again?")
    if low in ("my link", "invite", "invite link", "link a friend", "add friend"):
        link = f"https://wa.me/{settings.public_wa_number}?text=" + quote(f"Hi Mindy! join {invite_code(db, user['id'])}")
        return R("🤝 Send this to anyone. When they tap it, your Mindys are linked:", links=[("Share my link", "https://wa.me/?text=" + quote("Get your own Mindy and link with me: " + link))])
    if low in ("my people", "who can my mindy talk to", "linked"):
        ppl = linked(db, user["id"])
        return R("🤝 *Your Mindy can talk to:*\n" + ("\n".join("• " + p["name"] for p in ppl) or "Nobody yet. Say _my link_ to invite someone."))
    m = re.match(r"^(?:mute|pause|stop requests from)\s+([a-z][a-z .']{0,24})$", low)
    if m and (p := find(db, user["id"], m.group(1))):
        db.x("INSERT OR IGNORE INTO m2m_mute(user_id,other) VALUES(?,?)", (user["id"], p["id"]))
        return R(f"🔕 {p['name']}'s Mindy can't send you requests any more. Say _unmute {p['name'].split(' ')[0]}_ to undo.")
    m = re.match(r"^unmute\s+([a-z][a-z .']{0,24})$", low)
    if m and (p := find(db, user["id"], m.group(1))):
        db.x("DELETE FROM m2m_mute WHERE user_id=? AND other=?", (user["id"], p["id"]))
        return R(f"🔔 {p['name']} can reach your Mindy again.")
    kind = name = body = None
    amount = None
    if m := ASK_MONEY.match(t):
        cur = countries.for_user(db, user)
        amount = float(m.group(2).replace(",", ""))
        kind, name, body = "money", m.group(1), f"{countries.money(cur, amount)}" + (f" for {m.group(3).strip()}" if m.group(3) else "")
    elif m := DECLINE.match(t):
        kind, name = "decline", m.group(1)
        body = f"{user.get('name') or 'They'} can't make it" + (f" to {m.group(2).strip()}" if m.group(2) else "") + ", and is sorry to miss it."
    elif m := ASK_ANY.match(t):
        kind, name = "ask", m.group(1)
        q = f"{m.group(2)} {m.group(3)}".strip().rstrip("?")
        q = re.sub(r"\b(she|he)('s| is)\b", "you are", q, flags=re.I)
        q = re.sub(r"\bthey('re| are)\b", "you are", q, flags=re.I)
        q = re.sub(r"\b(she|he|they)\b", "you", q, flags=re.I)
        q = re.sub(r"\b(her|his|their)\b", "your", q, flags=re.I)
        body = re.sub(r"^(if|whether)\s+you are\b", "are you", q, flags=re.I)
        body = re.sub(r"^(if|whether)\s+you\b", "do you", body, flags=re.I)
        body = body[0].upper() + body[1:] + "?"
    elif (m := SAFE.match(t)) and not low.startswith("is this"):
        kind, name, body = "safe", m.group(1) or m.group(2), ""
    if not kind:
        return None
    name = name.strip()
    if name.lower() in ("me", "mindy", "this", "it", "number"):
        return None
    to = find(db, user["id"], name)
    if not to:
        if kind in ("ask", "safe") and not linked(db, user["id"]) and kind == "ask" and len(body) < 8:
            return None
        return forward_invite(db, user, name.title(), kind, body)
    return send(db, user, to, kind, body, amount)


def on_button(db: DB, user: dict, bid: str) -> dict | None:
    if not bid.startswith("m2m:"):
        return None
    _, mid, ans = bid.split(":", 2)
    r = db.one("SELECT * FROM m2m WHERE id=? AND to_uid=?", (int(mid), user["id"]))
    if not r:
        return R("👍")
    if r["status"] != "open":
        return R("Already answered. 👍")
    db.x("UPDATE m2m SET status='answered', answer=?, answered_at=? WHERE id=?", (ans, now_iso(), r["id"]))
    me = user.get("name") or "They"
    what = f" (about {r['text']})" if r["kind"] == "money" else ""
    back = f"📬 *{me}* {ANSWER_TEXT.get(ans, ans)}{what}."
    if r["kind"] == "money" and ans == "paid":
        back += " Say _settled " + me.split(" ")[0] + "_ once you see the money, and I'll clear it from your khata."
    if r["kind"] == "money" and ans == "tomorrow":
        db.add_reminder(r["from_uid"], f"{me} said they'd pay {r['text']} today. Check?", (datetime.now(timezone.utc) + timedelta(hours=26)).replace(microsecond=0).isoformat())
        back += " I'll check back with you tomorrow."
    thanks = {"paid": "Thank you! I've let them know. 🙌", "tomorrow": "Okay, I've told them tomorrow. I'll hold you to it 😄", "talk": "I've told them you'd like to talk.",
              "call": "I've asked them to call you now."}.get(ans, "Got it. I've passed that on. 👍")
    return R(thanks, notify=[(r["from_uid"], back, [])])


def handled(db: DB, user: dict, days: int = 7) -> dict:
    """What Mindy handled for you: the weekly receipt."""
    uid = user["id"]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    n = lambda sql, *a: db.one(sql, (uid, *a))["n"]
    rows = [
        ("⏰", n("SELECT COUNT(*) n FROM reminders WHERE user_id=? AND status IN ('sent','done') AND due_at>?", since), "reminders delivered on time"),
        ("🤝", n("SELECT COUNT(*) n FROM m2m WHERE from_uid=? AND created_at>?", since), "awkward conversations had for you"),
        ("📬", n("SELECT COUNT(*) n FROM m2m WHERE from_uid=? AND status='answered' AND created_at>?", since), "answers brought back"),
        ("💊", n("SELECT COUNT(*) n FROM care_log WHERE carer_id=? AND taken_at IS NOT NULL AND due_at>?", since) if _col(db, "care_log", "carer_id") else 0, "doses your family confirmed"),
        ("🗂️", n("SELECT COUNT(*) n FROM docs WHERE user_id=?"), "documents watched for expiry"),
        ("📌", n("SELECT COUNT(*) n FROM items WHERE user_id=? AND created_at>?", since), "things remembered"),
    ]
    rows = [r for r in rows if r[1]]
    return {"rows": [{"icon": i, "n": c, "label": l} for i, c, l in rows], "total": sum(r[1] for r in rows)}


def handled_text(db: DB, user: dict) -> str:
    h = handled(db, user)
    if not h["rows"]:
        return "🧾 Nothing handled yet this week. Give me something: a reminder, a bill, someone who owes you."
    return "🧾 *Handled for you this week*\n" + "\n".join(f"{r['icon']} {r['n']} {r['label']}" for r in h["rows"])


def _col(db, table, col):
    try:
        return any(r[1] == col for r in db.conn.execute(f"PRAGMA table_info({table})").fetchall())
    except Exception:
        return False
