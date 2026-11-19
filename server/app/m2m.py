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
CREATE TABLE IF NOT EXISTS m2m_group(id INTEGER PRIMARY KEY, from_uid INTEGER, question TEXT, options TEXT, created_at TEXT, closed INTEGER DEFAULT 0);
"""
KINDS = {
    "money": [("paid", "✅ Paid"), ("tomorrow", "⏰ Tomorrow"), ("talk", "💬 Let's talk")],
    "ask": [("yes", "👍 Yes"), ("no", "👎 No"), ("later", "⏳ Tell you later")],
    "safe": [("yes", "💚 All good"), ("call", "📞 Call me")],
    "remind": [("done", "✅ Done"), ("hour", "⏰ In 1 hour")],
    "note": [("seen", "👍 Got it"), ("love", "❤️")],
    "decline": [("ok", "👍 No worries"), ("sad", "🥺 Next time!")],
}
ANSWER_TEXT = {"paid": "says it's *paid* ✅", "tomorrow": "will pay *tomorrow* ⏰", "talk": "wants to *talk about it* 💬", "yes": "says *yes* 👍",
               "no": "says *no* 👎", "later": "will *tell you later* ⏳", "call": "asks you to *call them* 📞", "ok": "says *no worries* 👍", "sad": "says *next time!* 🥺",
               "done": "did it ✅", "hour": "will do it in an hour ⏰", "seen": "got your message 👍", "love": "sent ❤️"}


def init(db: DB):
    with db.lock:
        db.conn.executescript(SCHEMA)
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(m2m)").fetchall()}
        if "group_id" not in cols:
            db.conn.execute("ALTER TABLE m2m ADD COLUMN group_id INTEGER")
        if "due_at" not in cols:
            db.conn.execute("ALTER TABLE m2m ADD COLUMN due_at TEXT")
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
    hit = next((p for p in people if p["name"].lower() == n), None) or next((p for p in people if p["name"].lower().split(" ")[0] == n), None) \
        or next((p for p in people if n and len(n) > 2 and n in p["name"].lower()), None)
    if hit or len(n) < 3:
        return hit
    import difflib  # typos: "Rahool" still finds Rahul
    firsts = {p["name"].lower().split(" ")[0]: p for p in people if p["name"]}
    close = difflib.get_close_matches(n.split(" ")[0], list(firsts), n=1, cutoff=0.72)
    return firsts[close[0]] if close else None


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
            "decline": f"💌 *{me}'s Mindy here.* {text}",
            "remind": f"⏰ *{me}'s Mindy here.* {me} asked me to remind you: *{text}*",
            "note": f"💬 *{me}'s Mindy here.* {me} says: “{text}”"}[kind]
    buttons = [(f"m2m:{mid}:{a}", label) for a, label in KINDS[kind]]
    done = {"money": f"💸 Done. My Mindy asked {to['name']}'s Mindy, politely. I'll tell you what they say.",
            "ask": f"💬 Asked {to['name']}'s Mindy. I'll bring back the answer.",
            "safe": f"💚 Checking with {to['name']}'s Mindy. I'll tell you as soon as they tap.",
            "decline": f"💌 Told {to['name']}, kindly, so you don't have to.",
            "remind": f"⏰ Reminded {to['name']}. I'll tell you when they tap Done.",
            "note": f"💬 Told {to['name']}."}[kind]
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
    g = group_ask(db, user, t) or remind_other(db, user, t) or tell(db, user, t)
    if g:
        return g
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
    if r["kind"] == "poll":
        return poll_answer(db, user, r, ans)
    if r["kind"] == "remind" and ans == "hour":
        db.x("UPDATE m2m SET status='scheduled', due_at=? WHERE id=?", ((datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0).isoformat(), r["id"]))
        return R("⏰ Okay, I'll remind you again in an hour.")
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


# ---------------------------------------------------------------- group asks: one question to many Mindys
DAYS = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday"}
GROUP_RX = re.compile(r"^ask\s+(everyone|everybody|all|the group|all my people|(?:[a-z][a-z' ]{0,20}?)(?:\s*,\s*[a-z][a-z' ]{0,20}?)*(?:\s*,?\s+and\s+[a-z][a-z' ]{0,20}?))\s+"
                      r"(which|what|when|if|whether|are|is|can|could|do|does|will)\b\s*(.+)$", re.I)


def options_from(q: str) -> tuple[str, list[str]]:
    """'which night works: fri, sat or sun' -> ('Which night works?', ['Friday', 'Saturday', 'Sunday'])."""
    q = q.strip().rstrip("?").strip()
    head, opts = q, []
    m = re.search(r"[:\-–]\s*(.+)$", q) or re.search(r"\b(?:between|from)\s+(.+)$", q)
    if m:
        head = q[:m.start()].strip()
        opts = [o.strip() for o in re.split(r",|/|\bor\b|\band\b", m.group(1)) if o.strip()]
    elif re.search(r"\b(night|day|evening|weekend|date|time)\b", q, re.I):
        opts = ["Friday", "Saturday", "Sunday"]
    opts = [DAYS.get(o.lower()[:3], o[:20]) if o.lower()[:3] in DAYS and len(o) <= 9 else o[:20] for o in opts][:3]
    return head, opts


def group_ask(db: DB, user: dict, text: str) -> dict | None:
    m = GROUP_RX.match(text.strip())
    if not m:
        return None
    who, verb, rest = m.group(1).strip(), m.group(2), m.group(3)
    people = linked(db, user["id"])
    if who.lower() in ("everyone", "everybody", "all", "the group", "all my people"):
        targets, missing = people, []
    else:
        names = [n.strip() for n in re.split(r",|\band\b", who) if n.strip()]
        if len(names) < 2:
            return None  # one person: the single ask handles it
        found = [(n, find(db, user["id"], n)) for n in names]
        targets, missing = [p for _, p in found if p], [n.title() for n, p in found if not p]
    if not targets:
        return R("🤝 You haven't linked anyone yet. Say _my link_ and send it to your friends; when they tap it, your Mindys can talk.")
    head, opts = options_from(f"{verb} {rest}")
    head = re.sub(r"\b(they|they're|their|we|we're|our)\b", lambda x: {"they": "you", "they're": "you're", "their": "your", "we": "we", "we're": "we're", "our": "our"}[x.group(1).lower()], head, flags=re.I)
    head = re.sub(r"\b(he|she)\b", "you", head, flags=re.I)
    head = re.sub(r"^(if|whether)\s+you\s+are\b", "are you", head, flags=re.I)
    head = re.sub(r"^(if|whether)\s+you('re)?\b", lambda x: "are you" if x.group(2) else "do you", head, flags=re.I)
    q = head[0].upper() + head[1:] + "?"
    return start_poll(db, user, targets, q, opts, missing)


def start_poll(db: DB, user: dict, targets: list[dict], q: str, opts: list[str], missing: list[str] | None = None) -> dict:
    import json
    opts = opts or ["Yes", "No"]
    gid = db.x("INSERT INTO m2m_group(from_uid,question,options,created_at) VALUES(?,?,?,?)", (user["id"], q, json.dumps(opts), now_iso()))
    me = user.get("name") or "Your friend"
    notify = []
    for p in targets:
        if db.one("SELECT 1 FROM m2m_mute WHERE user_id=? AND other=?", (p["id"], user["id"])):
            continue
        mid = db.x("INSERT INTO m2m(from_uid,to_uid,kind,text,created_at,group_id) VALUES(?,?,?,?,?,?)", (user["id"], p["id"], "poll", q, now_iso(), gid))
        btns = [(f"m2m:{mid}:o{i}", o[:20]) for i, o in enumerate(opts)]
        if len(btns) < 3:
            btns.append((f"m2m:{mid}:none", "None work" if len(opts) > 2 or opts != ["Yes", "No"] else "Not sure"))
        notify.append((p["id"], f"🗳️ *{me}'s Mindy here.* {me} is asking {len(targets)} people: {q}", btns[:3]))
    names = ", ".join(p["name"].split(" ")[0] for p in targets)
    extra = f"\nI couldn't reach {', '.join(missing)}: they're not linked with you yet. Say _my link_ to invite them." if missing else ""
    return R(f"🗳️ Asked {len(notify)} Mindys ({names}): *{q}*\nI'll tell you as answers come in, and the moment there's a winner.{extra}", notify=notify)


def tally(db: DB, gid: int) -> dict:
    import json
    g = db.one("SELECT * FROM m2m_group WHERE id=?", (gid,))
    opts = json.loads(g["options"])
    rows = db.q("SELECT m.*, u.name FROM m2m m JOIN users u ON u.id=m.to_uid WHERE group_id=?", (gid,))
    votes = {o: [] for o in opts}
    for r in rows:
        if r["answer"] and r["answer"].startswith("o"):
            votes[opts[int(r["answer"][1:])]].append((r["name"] or "?").split(" ")[0])
    waiting = [(r["name"] or "?").split(" ")[0] for r in rows if r["status"] == "open"]
    return {"group": g, "opts": opts, "votes": votes, "waiting": waiting, "total": len(rows)}


def tally_text(t: dict) -> str:
    lines = [f"{'✅' if v and len(v) == t['total'] else '•'} {o}: {len(v)}" + (f" ({', '.join(v)})" if v else "") for o, v in t["votes"].items()]
    return "\n".join(lines) + (f"\n⏳ Waiting for {', '.join(t['waiting'])}" if t["waiting"] else "")


def poll_answer(db: DB, user: dict, r: dict, ans: str) -> dict:
    import json
    g = db.one("SELECT * FROM m2m_group WHERE id=?", (r["group_id"],))
    opts = json.loads(g["options"])
    if ans != "none" and not (ans.startswith("o") and ans[1:].isdigit() and int(ans[1:]) < len(opts)):
        return R("👍")
    db.x("UPDATE m2m SET status='answered', answer=?, answered_at=? WHERE id=?", (ans, now_iso(), r["id"]))
    me = (user.get("name") or "Someone").split(" ")[0]
    t = tally(db, g["id"])
    picked = "none of them" if ans == "none" else opts[int(ans[1:])]
    head = f"🗳️ *{g['question']}*\n{me} picked *{picked}*.\n\n"
    if not t["waiting"]:
        db.x("UPDATE m2m_group SET closed=1 WHERE id=?", (g["id"],))
        best = max(t["votes"].items(), key=lambda kv: len(kv[1]))
        if len(best[1]) == t["total"]:
            head = f"🎉 *{best[0]}* works for everyone! ({g['question']})\n\n"
        elif best[1]:
            head = f"🗳️ Everyone answered. *{best[0]}* works for the most people ({len(best[1])} of {t['total']}).\n\n"
        else:
            head = "🗳️ Everyone answered, but no option worked for anyone. Try other options?\n\n"
    return R(f"Got it: *{picked}*. I've told {(db.one('SELECT name FROM users WHERE id=?', (g['from_uid'],)) or {}).get('name') or 'them'}. 👍",
             notify=[(g["from_uid"], head + tally_text(t), [])])


# ---------------------------------------------------------------- remind someone else, through their Mindy
REMIND_RX = re.compile(r"^remind\s+([a-z][a-z .']{0,24}?)\s+to\s+(.+)$", re.I)


def remind_other(db: DB, user: dict, text: str) -> dict | None:
    m = REMIND_RX.match(text.strip())
    if not m or m.group(1).strip().lower() in ("me", "us", "myself", "everyone", "mindy"):
        return None
    to = find(db, user["id"], m.group(1))
    from .brain import parse_when, strip_when
    task = m.group(2).strip().rstrip(".")
    when = parse_when(task, user.get("tz") or "UTC")
    if not to:  # not linked: remind the user to remind them, and offer to link
        if when is None:
            return None
        from .handlers import fmt_local
        name = m.group(1).strip().title()
        due = when.astimezone(timezone.utc).replace(microsecond=0).isoformat()
        what = strip_when("remind me " + task)
        db.add_reminder(user["id"], f"Remind {name} to {what}", due)
        return R(f"⏰ I'll remind *you* to remind {name} to {what}, {fmt_local(due, user.get('tz') or 'UTC')}.\n"
                 f"Link with {name} (say _my link_) and next time I'll remind them directly on their own Mindy.")
    if when is None:
        res = send(db, user, to, "remind", task)
        return res
    clean = re.sub(r"\s+(?:at|by|on|tomorrow|today|tonight|this|next|in)\b.*$", "", task, flags=re.I).strip() or task
    due = when.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    db.x("INSERT INTO m2m(from_uid,to_uid,kind,text,created_at,status,due_at) VALUES(?,?,?,?,?,?,?)", (user["id"], to["id"], "remind", clean, now_iso(), "scheduled", due))
    from .handlers import fmt_local
    return R(f"⏰ I'll remind {to['name']} to *{clean}* {fmt_local(due, user.get('tz') or 'UTC')}, on their own Mindy. You'll hear when they tap Done.")


async def due_reminders(db: DB, now: datetime | None = None):
    """Sends scheduled 'remind them' requests when they're due. Runs every minute."""
    from .handlers import deliver
    from .config import settings
    now = now or datetime.now(timezone.utc)
    for r in db.q("SELECT m.*, u.name FROM m2m m JOIN users u ON u.id=m.from_uid WHERE m.status='scheduled' AND m.due_at<=?", (now.isoformat(),)):
        db.x("UPDATE m2m SET status='open' WHERE id=?", (r["id"],))
        me = r["name"] or "Your friend"
        await deliver(db, r["to_uid"], f"⏰ *{me}'s Mindy here.* {me} asked me to remind you: *{r['text']}*",
                      [(f"m2m:{r['id']}:{a}", l) for a, l in KINDS["remind"]], settings.reminder_template, [f"{me} asked me to remind you: {r['text']}"], now)


# ---------------------------------------------------------------- pass a message on (one person or everyone)
TELL_RX = re.compile(r"^(?:tell|let|message|text)\s+(everyone|everybody|all|the group|[a-z][a-z .']{0,24}?)\s+(?:know\s+)?(?:that\s+)?(.{3,300})$", re.I)


def tell(db: DB, user: dict, text: str) -> dict | None:
    m = TELL_RX.match(text.strip())
    if not m or DECLINE.match(text.strip()):
        return None
    who, msg = m.group(1).strip(), m.group(2).strip()
    if who.lower() in ("me", "mindy", "you"):
        return None
    if who.lower() in ("everyone", "everybody", "all", "the group"):
        people = linked(db, user["id"])
        if not people:
            return R("🤝 You haven't linked anyone yet. Say _my link_ and send it to your people.")
        notify, me = [], user.get("name") or "Your friend"
        for p in people:
            if db.one("SELECT 1 FROM m2m_mute WHERE user_id=? AND other=?", (p["id"], user["id"])):
                continue
            mid = db.x("INSERT INTO m2m(from_uid,to_uid,kind,text,created_at) VALUES(?,?,?,?,?)", (user["id"], p["id"], "note", msg, now_iso()))
            notify.append((p["id"], f"💬 *{me}'s Mindy here.* {me} says: “{msg}”", [(f"m2m:{mid}:{a}", l) for a, l in KINDS["note"]]))
        return R(f"💬 Told {len(notify)} people: “{msg}”", notify=notify)
    to = find(db, user["id"], who)
    if not to:
        if len(who.split()) > 2 or who.lower() in ("him", "her", "them", "it"):
            return None
        return forward_invite(db, user, who.title(), "ask", f"{user.get('name') or 'Your friend'} says: “{msg}”")
    return send(db, user, to, "note", msg)
