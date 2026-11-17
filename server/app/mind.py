"""Mindy asks. Every person is their own small database, and Mindy fills it by asking, not by waiting to be told.

- One short question at a time, with tap answers. Each answer unlocks something real (a reminder, a care loop, a gift nudge).
- Facts are grouped into regions of "your mind" (family, goals, habits, schedule, money, places, documents, style, work, travel);
  the app draws them as a brain that lights up as it fills.
- Whatever Mindy can work out by itself it does without being asked: a trip becomes a checklist, an expiry date becomes
  reminders, a birthday becomes a gift nudge.
People can see, edit and delete every fact ("what do you know about me")."""
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .db import DB, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, user_id INTEGER, key TEXT, value TEXT, region TEXT, source TEXT,
  created_at TEXT, updated_at TEXT, UNIQUE(user_id, key));
CREATE TABLE IF NOT EXISTS asked(user_id INTEGER, key TEXT, asked_at TEXT, PRIMARY KEY(user_id, key));
CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, relation TEXT, parent_id INTEGER,
  birthday TEXT, phone TEXT, gift_ideas TEXT, notes TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, created_at TEXT, done_at TEXT);
CREATE TABLE IF NOT EXISTS habits(id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, created_at TEXT, archived INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS habit_log(habit_id INTEGER, day TEXT, PRIMARY KEY(habit_id, day));
CREATE TABLE IF NOT EXISTS docs(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, expires TEXT, note TEXT, created_at TEXT);
"""

REGIONS = ["family", "goals", "habits", "schedule", "money", "places", "documents", "style", "work", "travel"]
REGION_LABEL = {"family": "Family", "goals": "Goals", "habits": "Habits", "schedule": "Schedule", "money": "Money",
                "places": "Places", "documents": "Documents", "style": "Style", "work": "Work", "travel": "Travel"}


def init(db: DB):
    with db.lock:
        db.conn.executescript(SCHEMA)
        have = {r[1] for r in db.conn.execute("PRAGMA table_info(users)").fetchall()}
        for col, decl in (("lang", "TEXT"), ("voice", "INTEGER DEFAULT 0"), ("country", "TEXT"), ("pay_link", "TEXT"),
                          ("photo", "TEXT"), ("brief_at", "TEXT")):
            if col not in have:
                db.conn.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        db.conn.commit()


# ---------------------------------------------------------------- the question bank
# opts: list of (value, label); free: what kind of typed answer ("text", "date", "name", "day"); when: needs these facts
Q = [
    {"key": "goal", "region": "goals", "q": "What's one thing you want to get better at this month?",
     "opts": [("save", "💰 Save money"), ("fit", "🏃 Get fit"), ("study", "📚 Study"), ("job", "💼 Find work"), ("family", "👨‍👩‍👧 Family time")]},
    {"key": "pet", "region": "family", "q": "Random question: did you ever have a pet? What was their name? 🐾 (or say skip)", "free": "name"},
    {"key": "wake", "region": "schedule", "q": "What time do you usually wake up? I'll send your morning brief then.",
     "opts": [("06:00", "6 am"), ("07:00", "7 am"), ("08:00", "8 am"), ("09:00", "9 am or later")]},
    {"key": "work", "region": "work", "q": "What do you do most days?",
     "opts": [("student", "🎓 Study"), ("job", "💼 A job"), ("business", "🏪 My business"), ("home", "🏠 Home"), ("retired", "🌿 Retired")]},
    {"key": "home_with", "region": "family", "q": "Who do you live with?",
     "opts": [("family", "Family"), ("partner", "Partner"), ("flatmates", "Flatmates"), ("alone", "On my own")]},
    {"key": "parents_meds", "region": "family", "q": "Do your parents (or anyone you look after) take daily medicine?",
     "opts": [("yes", "Yes"), ("no", "No"), ("na", "Not relevant")]},
    {"key": "close_person", "region": "family", "q": "Whose birthday should I never let you forget? Just type their name.", "free": "name"},
    {"key": "close_bday", "region": "family", "q": "When is {close_person}'s birthday? (e.g. 12 March)", "free": "day", "when": ["close_person"]},
    {"key": "habit", "region": "habits", "q": "Pick one small daily habit. I'll keep your streak.",
     "opts": [("Drink 8 glasses of water", "💧 Water"), ("Walk 20 minutes", "🚶 Walk"), ("Read 10 pages", "📖 Read"),
              ("Sleep before 11", "😴 Sleep on time"), ("No phone in bed", "📵 No phone in bed")]},
    {"key": "drive", "region": "places", "q": "Do you drive or ride?", "opts": [("car", "🚗 Car"), ("bike", "🛵 Bike/scooter"), ("no", "No")]},
    {"key": "insurance_exp", "region": "documents", "q": "When does your vehicle insurance run out? (e.g. 3 May 2027)", "free": "date",
     "when": ["drive=car|bike"]},
    {"key": "monthly", "region": "money", "q": "What do you pay every month that you'd hate to forget?",
     "opts": [("rent", "🏠 Rent"), ("emi", "💳 EMI / card"), ("staff", "🧹 Maid / staff"), ("subs", "📺 Subscriptions"), ("none", "Nothing")]},
    {"key": "rent_day", "region": "money", "q": "Which day of the month is it due?", "opts": [("1", "1st"), ("5", "5th"), ("10", "10th"), ("15", "15th"), ("28", "End of month")],
     "when": ["monthly=rent|emi|staff"]},
    {"key": "passport", "region": "documents", "q": "Do you have a passport?", "opts": [("yes", "Yes"), ("no", "No")]},
    {"key": "passport_exp", "region": "documents", "q": "When does it expire? (e.g. Aug 2031) I'll remind you well before.", "free": "date", "when": ["passport=yes"]},
    {"key": "my_bday", "region": "family", "q": "And when's your birthday? 🎂", "free": "day"},
    {"key": "style", "region": "style", "q": "How do you dress most days?", "opts": [("casual", "Casual"), ("formal", "Formal"), ("traditional", "Traditional"), ("sporty", "Sporty")]},
    {"key": "size", "region": "style", "q": "Your usual top size? (helps with gifts and shopping)", "opts": [("S", "S"), ("M", "M"), ("L", "L"), ("XL", "XL"), ("XXL", "XXL")]},
    {"key": "travel", "region": "travel", "q": "Any trip coming up in the next 3 months?", "opts": [("yes", "Yes"), ("no", "Not yet")]},
    {"key": "trip", "region": "travel", "q": "Where and when? (e.g. Dubai on 20 Dec)", "free": "text", "when": ["travel=yes"]},
    {"key": "scam_seen", "region": "money", "q": "Has anyone tried to scam you or your family in the last year?", "opts": [("yes", "Yes"), ("no", "No")]},
    {"key": "city", "region": "places", "q": "Which city do you live in?", "free": "text"},
    {"key": "lang_pref", "region": "work", "q": "Which language should I talk to you in?",
     "opts": [("en", "English"), ("hi", "हिंदी"), ("hinglish", "Hinglish"), ("es", "Español"), ("ar", "العربية")]},
    {"key": "pet_care", "region": "family", "q": "Does {pet} still live with you? I can keep their vet and vaccine dates.", "opts": [("yes", "Yes!"), ("no", "No, sadly")], "when": ["pet"]},
]
QBY = {q["key"]: q for q in Q}


class _Safe(dict):
    def __missing__(self, k):
        return "them"


def facts(db: DB, uid: int) -> dict:
    return {r["key"]: r["value"] for r in db.q("SELECT key, value FROM facts WHERE user_id=?", (uid,))}


def set_fact(db: DB, uid: int, key: str, value: str, region: str | None = None, source: str = "asked"):
    region = region or (QBY.get(key) or {}).get("region") or "other"
    db.x("INSERT INTO facts(user_id,key,value,region,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
         "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
         (uid, key, str(value), region, source, now_iso(), now_iso()))


def _ok(cond: str, f: dict) -> bool:
    if "=" in cond:
        k, vals = cond.split("=", 1)
        return f.get(k) in vals.split("|")
    return cond in f


def next_question(db: DB, uid: int, region: str | None = None, ignore_recent: bool = False) -> dict | None:
    f = facts(db, uid)
    recent = {r["key"] for r in db.q("SELECT key FROM asked WHERE user_id=? AND asked_at>?", (uid, (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()))}
    for q in Q:
        if q["key"] in f or (region and q["region"] != region):
            continue
        if not all(_ok(c, f) for c in q.get("when", [])):
            continue
        if q["key"] in recent and not ignore_recent:
            continue
        return {**q, "q": q["q"].format_map(_Safe({k: v.title() for k, v in f.items()}))}
    return None


def mark_asked(db: DB, uid: int, key: str):
    db.x("INSERT OR REPLACE INTO asked(user_id,key,asked_at) VALUES(?,?,?)", (uid, key, now_iso()))


def asked_today(db: DB, uid: int) -> bool:
    return bool(db.one("SELECT 1 FROM asked WHERE user_id=? AND asked_at>?", (uid, (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat())))


def buttons_for(q: dict) -> list[tuple[str, str]]:
    return [(f"q:{q['key']}:{v}", l) for v, l in q.get("opts", [])][:3]


def list_rows(q: dict) -> list[tuple[str, str, str]]:
    return [(f"q:{q['key']}:{v}", l[:24], "") for v, l in q.get("opts", [])]


# ---------------------------------------------------------------- dates
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(text: str, today: date | None = None, future: bool = True) -> date | None:
    """'12 March 2029', '2029-03-12', '12/03/2029', 'March 2029', 'Aug 2031', '3 May' -> date. Day-first like most of the world."""
    t = text.lower().strip()
    today = today or date.today()
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b", t)
    if m:
        y = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
        return _mk(y, int(m.group(2)), int(m.group(1)))
    m = re.search(r"\b([a-z]{3})[a-z]*\.?,?\s+(\d{4})\b", t)
    if m and m.group(1) in MONTHS and not re.search(r"\b\d{1,2}(?:st|nd|rd|th)?\s+" + m.group(1), t):
        return _mk(int(m.group(2)), MONTHS[m.group(1)], 1)
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3})[a-z]*\.?(?:,?\s+(\d{4}))?", t) or \
        re.search(r"\b([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", t)
    if m:
        a, b, y = m.group(1), m.group(2), m.group(3)
        day, mon = (int(a), b) if a.isdigit() else (int(b), a)
        if mon[:3] in MONTHS:
            mo = MONTHS[mon[:3]]
            if y:
                return _mk(int(y), mo, day)
            d = _mk(today.year, mo, day)
            if d and future and d < today:
                d = _mk(today.year + 1, mo, day)
            return d
    m = re.search(r"\b([a-z]{3})[a-z]*\.?\s+(\d{4})\b", t)
    if m and m.group(1) in MONTHS:
        return _mk(int(m.group(2)), MONTHS[m.group(1)], 1)
    return None


def _mk(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


# ---------------------------------------------------------------- documents with expiry (the vault)
def add_doc(db: DB, user: dict, name: str, expires: date, note: str = "") -> dict:
    """Saves a document's expiry and sets reminders 60 days, 14 days and 1 day before (only the ones still ahead)."""
    did = db.x("INSERT INTO docs(user_id,name,expires,note,created_at) VALUES(?,?,?,?,?)", (user["id"], name, expires.isoformat(), note, now_iso()))
    z = ZoneInfo(user.get("tz") or "UTC")
    now = datetime.now(z)
    set_ = []
    for days in (60, 14, 1):
        at = datetime(expires.year, expires.month, expires.day, 9, 0, tzinfo=z) - timedelta(days=days)
        if at > now:
            db.add_reminder(user["id"], f"Your {name} expires on {expires:%d %b %Y}. Time to renew.", at.astimezone(timezone.utc).replace(microsecond=0).isoformat(), kind="doc")
            set_.append(days)
    return {"id": did, "name": name, "expires": expires.isoformat(), "reminders": set_}


def docs(db: DB, uid: int) -> list[dict]:
    return db.q("SELECT * FROM docs WHERE user_id=? ORDER BY expires", (uid,))


def monthly_reminder(db: DB, user: dict, text: str, day: int, hour: int = 9) -> int:
    z = ZoneInfo(user.get("tz") or "UTC")
    now = datetime.now(z)
    y, mo = now.year, now.month
    d = min(day, 28)
    at = datetime(y, mo, d, hour, 0, tzinfo=z)
    if at <= now:
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
        at = datetime(y, mo, d, hour, 0, tzinfo=z)
    return db.add_reminder(user["id"], text, at.astimezone(timezone.utc).isoformat(), "monthly")


# ---------------------------------------------------------------- answering
UNLOCK = {
    "save": "I'll check in every Sunday with how you're doing, and flag money leaks I notice (subscriptions, late fees).",
    "fit": "I'll nudge you at a sensible time each day and keep your streak.",
    "study": "Send me any notes or photos of questions, and I'll quiz you and give hints, not answers.",
    "job": "Send me job messages before you reply: fake recruiters asking for fees are everywhere. I'll check each one.",
    "family": "Tell me birthdays and plans, and I'll make sure none slip.",
}


def answer(db: DB, user: dict, key: str, value: str) -> dict:
    """Stores the answer, does whatever it unlocks, and returns {reply, next}."""
    uid = user["id"]
    q = QBY.get(key) or {"region": "other"}
    value = value.strip()
    reply = "👍 Got it."
    if q.get("free") == "date":
        d = parse_date(value)
        if not d:
            return {"reply": "I couldn't read that date. Try like *3 May 2027*.", "next": q, "again": True}
        name = {"insurance_exp": "vehicle insurance", "passport_exp": "passport"}.get(key, key.replace("_exp", ""))
        r = add_doc(db, user, name, d)
        value = d.isoformat()
        reply = f"🗂️ Saved. I'll remind you {', '.join(f'{x} days' if x > 1 else 'the day' for x in r['reminders']) or 'when it is close'} before your {name} expires."
    elif q.get("free") == "day":
        d = parse_date(value, future=False)
        if not d:
            return {"reply": "Just the date, like *12 March*.", "next": q, "again": True}
        person = facts(db, uid).get("close_person") if key == "close_bday" else "you"
        value = f"{d:%m-%d}"
        if key == "close_bday" and person:
            db.add_occasion(uid, person.title(), "birthday", d.month, d.day)
            p = db.one("SELECT id FROM people WHERE user_id=? AND lower(name)=?", (uid, person.lower()))
            if p:
                db.x("UPDATE people SET birthday=? WHERE id=?", (value, p["id"]))
            reply = f"🎂 Locked in. 3 days before {person.title()}'s birthday I'll send a gift idea, and on the day a message you can send in one tap."
        else:
            reply = "🎂 Noted. I won't make a fuss. Maybe a little one."
    elif key == "close_person":
        name = re.sub(r"[^\w .'-]", "", value)[:40].strip()
        if not name:
            return {"reply": "Just their name is fine.", "next": q, "again": True}
        value = name
        add_person(db, uid, name, "")
        reply = f"💚 {name.title()} is in your family tree."
    elif key == "goal":
        db.x("INSERT INTO goals(user_id,title,created_at) VALUES(?,?,?)", (uid, dict(QBY["goal"]["opts"]).get(value, value).split(" ", 1)[-1], now_iso()))
        z = ZoneInfo(user.get("tz") or "UTC")
        now = datetime.now(z)
        sun = now + timedelta(days=(6 - now.weekday()) % 7 or 7)
        db.add_reminder(uid, "Weekly check-in: how did your goal go this week? Reply 1 to 5.", sun.replace(hour=18, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat(), "weekly")
        reply = "🎯 Goal set. " + UNLOCK.get(value, "")
    elif key == "habit":
        db.x("INSERT INTO habits(user_id,title,created_at) VALUES(?,?,?)", (uid, value, now_iso()))
        reply = f"✅ Habit: *{value}*. Reply *done* any day you do it and I'll keep your streak."
    elif key == "wake":
        db.x("UPDATE users SET brief_at=? WHERE id=?", (value, uid))
        reply = f"☀️ Your morning brief will come at {value}: today's reminders, bills, birthdays and one tip."
    elif key == "parents_meds" and value == "yes":
        reply = "💊 Mindy Care can remind them at the right times and tell you if a dose is missed. Open the app → Family → *Add family* to start."
    elif key == "rent_day":
        what = {"rent": "Pay rent", "emi": "EMI / card payment due", "staff": "Pay staff salary"}.get(facts(db, uid).get("monthly"), "Monthly payment")
        monthly_reminder(db, user, what, int(value))
        reply = f"📅 Every month on the {value}{'st' if value == '1' else 'th'}, I'll remind you: *{what}*."
    elif key == "trip":
        t = trip_from(value, user.get("tz") or "UTC", force=True)
        if t:
            res = auto_trip(db, user, t["place"], t["date"])
            reply = res["reply"]
        else:
            reply = "✈️ Noted. Send me the ticket or booking when you have it and I'll do the rest."
    elif key == "lang_pref":
        db.x("UPDATE users SET lang=? WHERE id=?", (value, uid))
        reply = "🌍 Done."
    elif key == "pet_care" and value == "yes":
        reply = "🐾 Tell me their next vet or vaccine date like *Bruno vaccine 3 Jan* and I'll remind you."
    elif key == "scam_seen" and value == "yes":
        reply = "🛡️ I'm sorry. From now on, forward me anything that looks off, for you or family. Every report also warns everyone else on Mindy."
    elif key == "monthly" and value == "subs":
        reply = "📺 Tell me each one like *Netflix 649 on the 5th*. I'll remind you before it renews and total them up."
    set_fact(db, uid, key, value, q.get("region"))
    nxt = next_question(db, uid, ignore_recent=True)
    nxt = nxt if nxt and nxt["region"] == q.get("region") else None  # follow-ups chain only within the same topic
    return {"reply": reply, "next": nxt}


# ---------------------------------------------------------------- family tree
def add_person(db: DB, uid: int, name: str, relation: str, birthday: str | None = None, parent_id: int | None = None, phone: str | None = None) -> int:
    ex = db.one("SELECT id FROM people WHERE user_id=? AND lower(name)=?", (uid, name.lower()))
    if ex:
        if relation:
            db.x("UPDATE people SET relation=? WHERE id=?", (relation, ex["id"]))
        return ex["id"]
    pid = db.x("INSERT INTO people(user_id,name,relation,parent_id,birthday,phone,created_at) VALUES(?,?,?,?,?,?,?)",
               (uid, name.strip().title(), relation, parent_id, birthday, phone, now_iso()))
    if birthday and re.match(r"^\d{2}-\d{2}$", birthday):
        db.add_occasion(uid, name.strip().title(), "birthday", int(birthday[:2]), int(birthday[3:]))
    return pid


def tree(db: DB, uid: int) -> list[dict]:
    return db.q("SELECT id, name, relation, parent_id, birthday, gift_ideas FROM people WHERE user_id=? ORDER BY id", (uid,))


# ---------------------------------------------------------------- habits and goals
def habit_done(db: DB, uid: int, tz: str, habit_id: int | None = None) -> dict | None:
    h = db.one("SELECT * FROM habits WHERE user_id=? AND archived=0" + (" AND id=?" if habit_id else "") + " ORDER BY id DESC LIMIT 1",
               (uid, habit_id) if habit_id else (uid,))
    if not h:
        return None
    today = datetime.now(ZoneInfo(tz)).date()
    db.x("INSERT OR IGNORE INTO habit_log(habit_id,day) VALUES(?,?)", (h["id"], today.isoformat()))
    return {**h, "streak": streak(db, h["id"], today)}


def streak(db: DB, hid: int, today: date) -> int:
    days = {r["day"] for r in db.q("SELECT day FROM habit_log WHERE habit_id=?", (hid,))}
    n, d = 0, today
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


# ---------------------------------------------------------------- what Mindy knows (for the 3D brain)
def mind(db: DB, user: dict) -> dict:
    uid = user["id"]
    f = db.q("SELECT id, key, value, region, updated_at FROM facts WHERE user_id=? ORDER BY region, key", (uid,))
    per = {r: 0 for r in REGIONS}
    for r in f:
        per[r["region"]] = per.get(r["region"], 0) + 1
    extra = {"family": db.one("SELECT COUNT(*) n FROM people WHERE user_id=?", (uid,))["n"],
             "documents": db.one("SELECT COUNT(*) n FROM docs WHERE user_id=?", (uid,))["n"],
             "habits": db.one("SELECT COUNT(*) n FROM habits WHERE user_id=? AND archived=0", (uid,))["n"],
             "goals": db.one("SELECT COUNT(*) n FROM goals WHERE user_id=? AND done_at IS NULL", (uid,))["n"],
             "places": db.one("SELECT COUNT(*) n FROM places WHERE user_id=?", (uid,))["n"] if _table(db, "places") else 0,
             "style": db.one("SELECT COUNT(*) n FROM items WHERE user_id=? AND collection='Wardrobe'", (uid,))["n"]}
    totals = {r: sum(1 for q in Q if q["region"] == r) + 3 for r in REGIONS}
    regions = []
    for r in REGIONS:
        have = per.get(r, 0) + extra.get(r, 0)
        regions.append({"id": r, "label": REGION_LABEL[r], "count": have, "fill": round(min(1, have / totals[r]), 2)})
    tz = user.get("tz") or "UTC"
    today = datetime.now(ZoneInfo(tz)).date()
    habits = [{**h, "streak": streak(db, h["id"], today),
               "today": bool(db.one("SELECT 1 FROM habit_log WHERE habit_id=? AND day=?", (h["id"], today.isoformat())))}
              for h in db.q("SELECT id, title FROM habits WHERE user_id=? AND archived=0", (uid,))]
    nq = next_question(db, uid, ignore_recent=True)
    return {"regions": regions, "facts": f, "people": tree(db, uid), "docs": docs(db, uid), "habits": habits,
            "goals": db.q("SELECT id, title, created_at FROM goals WHERE user_id=? AND done_at IS NULL", (uid,)),
            "next": _public_q(nq), "score": round(sum(x["fill"] for x in regions) / len(regions) * 100)}


def _public_q(q):
    if not q:
        return None
    return {"key": q["key"], "region": q["region"], "q": q["q"], "opts": [{"value": v, "label": l} for v, l in q.get("opts", [])], "free": q.get("free")}


def question_for(db: DB, uid: int, region: str | None) -> dict | None:
    return _public_q(next_question(db, uid, region, ignore_recent=True))


def _table(db, name):
    return bool(db.one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)))


# ---------------------------------------------------------------- trips: noticed, not asked for
TRIP_RE = re.compile(r"(?i:\b(?:fly(?:ing)?|flight|train|trip|travel(?:l?ing)?|holiday|vacation|visiting|boarding|going)\b)[^.\n]{0,40}?\b(?i:to)\s+"
                     r"((?!The\b|My\b|A\b)[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){0,2})")


def trip_from(text: str, tz: str, force: bool = False) -> dict | None:
    m = TRIP_RE.search(text)
    place = None
    if m:
        place = m.group(1).strip()
    elif force:
        m2 = re.match(r"^\s*([A-Za-z][\w'’ -]{1,30}?)\s+(?:on|from|in|next)\b", text)
        place = m2.group(1).strip() if m2 else None
    if not place:
        return None
    d = parse_date(text)
    if not d:
        from .brain import parse_when
        w = parse_when(text, tz)
        d = w.date() if w else None
    if not d:
        return None
    place = re.split(r"\s+(?:on|from|in|next|this|at)\b", place, flags=re.I)[0].strip()
    return {"place": place.title(), "date": d, "flight": bool(re.search(r"\b(fly|flying|flight|boarding|airport|pnr)\b", text, re.I))}


def auto_trip(db: DB, user: dict, place: str, when: date, flight: bool = True) -> dict:
    """Builds the checklist from this person's own data and sets the reminders. Nobody had to ask."""
    uid = user["id"]
    z = ZoneInfo(user.get("tz") or "UTC")
    f = facts(db, uid)
    items = []
    pp = next((d for d in docs(db, uid) if "passport" in d["name"]), None)
    if pp:
        exp = date.fromisoformat(pp["expires"])
        months = (exp.year - when.year) * 12 + exp.month - when.month
        items.append("⚠️ Passport: renew first, it expires within 6 months of the trip" if months < 6 else f"Passport ✓ (valid till {exp:%b %Y})")
    else:
        items.append("Passport / ID (tell me its expiry and I'll check it against trip dates)")
    items += ["Tickets and booking saved here", "Phone charger + power bank", "Some local currency or a travel card", "Travel insurance"]
    wardrobe = db.q("SELECT title, text FROM items WHERE user_id=? AND collection='Wardrobe' ORDER BY id DESC LIMIT 4", (uid,))
    if wardrobe:
        items.append("Pack: " + ", ".join((w.get("title") or w["text"])[:30] for w in wardrobe))
    if f.get("parents_meds") == "yes":
        items.append("Set up care reminders for family while you're away")
    db.list_add(uid, f"Trip to {place}", items)
    now = datetime.now(z)
    start = datetime(when.year, when.month, when.day, 9, 0, tzinfo=z)
    set_ = []
    for text, at in ((f"Trip to {place} in 3 days: check your list (say 'show trip to {place} list')", start - timedelta(days=3)),
                     (f"Online check-in for {place} usually opens now" if flight else f"Trip to {place} tomorrow: pack tonight", start - timedelta(days=1))):
        if at > now:
            db.add_reminder(uid, text, at.astimezone(timezone.utc).isoformat(), kind="trip")
            set_.append(text)
    set_fact(db, uid, "next_trip", f"{place} {when.isoformat()}", "travel", "noticed")
    return {"place": place, "date": when.isoformat(), "list": items,
            "reply": f"✈️ *{place}, {when:%a %d %b}*. I've made your trip list and set reminders:\n" + "\n".join("• " + i for i in items[:6])}
