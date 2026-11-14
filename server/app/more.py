"""Mindy's everyday skills, rules first (no AI needed), each one small and isolated.

`handle(db, user, text)` returns a reply dict, or None to let the normal brain take over:
  {"text": str, "links": [(label, url)], "buttons": [(id, label)], "notify": [(user_id, body, buttons)], "app": (label, path)}
`on_button(db, user, bid)` handles taps for these skills. Every skill is wrapped so one failure never blocks the rest."""
import hashlib
import logging
import math
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, quote_plus, urlencode
from zoneinfo import ZoneInfo

from . import care, countries, llm, mind, skills
from .config import settings
from .db import DB, now_iso

log = logging.getLogger("mindy.more")

SCHEMA = """
CREATE TABLE IF NOT EXISTS staff(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, salary INTEGER, created_at TEXT, UNIQUE(user_id, name));
CREATE TABLE IF NOT EXISTS staff_log(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, kind TEXT, amount INTEGER, day TEXT);
CREATE TABLE IF NOT EXISTS gifts(id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, total INTEGER, share INTEGER, created_at TEXT, closed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS gift_people(gift_id INTEGER, name TEXT, paid INTEGER DEFAULT 0, PRIMARY KEY(gift_id, name));
CREATE TABLE IF NOT EXISTS codewords(user_id INTEGER PRIMARY KEY, hash TEXT, set_by INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS verify_req(id INTEGER PRIMARY KEY, asker INTEGER, target INTEGER, created_at TEXT, answer TEXT);
CREATE TABLE IF NOT EXISTS impersonation(id INTEGER PRIMARY KEY, name_key TEXT, url TEXT, reporter INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS official_handles(name_key TEXT, url TEXT, created_at TEXT, PRIMARY KEY(name_key, url));
CREATE TABLE IF NOT EXISTS help_queue(id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT, created_at TEXT, answered_at TEXT, answer TEXT);
CREATE TABLE IF NOT EXISTS business_apps(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, number TEXT, created_at TEXT, status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS safety(id INTEGER PRIMARY KEY, user_id INTEGER, kind TEXT, due_at TEXT, created_at TEXT, cleared_at TEXT, alerted_at TEXT);
CREATE TABLE IF NOT EXISTS capsules(id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT, open_at TEXT, created_at TEXT, opened INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS magic(token_hash TEXT PRIMARY KEY, user_id INTEGER, path TEXT, expires TEXT, used INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sms_out(id INTEGER PRIMARY KEY, to_number TEXT, body TEXT, created_at TEXT, sent_at TEXT);
CREATE TABLE IF NOT EXISTS tryon_use(user_id INTEGER, day TEXT, n INTEGER, PRIMARY KEY(user_id, day));
"""


def init(db: DB):
    mind.init(db)
    with db.lock:
        db.conn.executescript(SCHEMA)
        have = {r[1] for r in db.conn.execute("PRAGMA table_info(users)").fetchall()}
        for col, decl in (("mindy_name", "TEXT"), ("mindy_hue", "INTEGER"), ("persona", "TEXT DEFAULT 'sweet'"), ("ok_daily", "INTEGER DEFAULT 0")):
            if col not in have:
                db.conn.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        db.conn.commit()


def R(text, **kw) -> dict:
    return {"text": text, **kw}


def _today(user) -> date:
    return datetime.now(ZoneInfo(user.get("tz") or "UTC")).date()


def _kv_get(db, k):
    r = db.one("SELECT v FROM kv WHERE k=?", (k,))
    return r["v"] if r else None


def _kv_set(db, k, v):
    if v is None:
        db.x("DELETE FROM kv WHERE k=?", (k,))
    else:
        db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (k, str(v)))


# ---------------------------------------------------------------- magic links: WhatsApp -> the exact app screen, signed in
def magic_link(db: DB, uid: int, path: str = "now", minutes: int = 15) -> str:
    tok = secrets.token_urlsafe(18)
    db.x("INSERT INTO magic(token_hash,user_id,path,expires) VALUES(?,?,?,?)",
         (hashlib.sha256(tok.encode()).hexdigest(), uid, path, (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()))
    return f"{settings.app_url.rstrip('/')}/m/{tok}"


def use_magic(db: DB, tok: str) -> dict | None:
    h = hashlib.sha256(tok.encode()).hexdigest()
    r = db.one("SELECT * FROM magic WHERE token_hash=?", (h,))
    if not r or r["used"] or r["expires"] < datetime.now(timezone.utc).isoformat():
        return None
    db.x("UPDATE magic SET used=1 WHERE token_hash=?", (h,))
    return r


# ---------------------------------------------------------------- languages
LANGS = {"english": "en", "hindi": "hi", "हिंदी": "hi", "hinglish": "hinglish", "gujarati": "gu", "marathi": "mr", "tamil": "ta", "telugu": "te",
         "bengali": "bn", "bangla": "bn", "kannada": "kn", "malayalam": "ml", "punjabi": "pa", "urdu": "ur", "spanish": "es", "español": "es",
         "portuguese": "pt", "português": "pt", "french": "fr", "français": "fr", "german": "de", "deutsch": "de", "arabic": "ar", "العربية": "ar",
         "swahili": "sw", "kiswahili": "sw", "indonesian": "id", "bahasa": "id", "filipino": "tl", "tagalog": "tl", "yoruba": "yo", "hausa": "ha",
         "italian": "it", "turkish": "tr", "russian": "ru", "chinese": "zh", "japanese": "ja", "korean": "ko", "polish": "pl", "dutch": "nl"}
LANG_NAME = {v: k.title() for k, v in LANGS.items() if k.isascii()}


def translate(text: str, lang: str | None, who: str | None = None) -> str:
    """Translates Mindy's reply into the person's language with the cheap model (cached). Falls back to the original."""
    if not lang or lang == "en" or not text.strip():
        return text
    name = "Hinglish (Hindi in Latin letters, mixed with English)" if lang == "hinglish" else LANG_NAME.get(lang, lang)
    out = llm.chat("Translate this WhatsApp message into " + name + ". Keep emojis, *bold* markers, links, numbers and names exactly. "
                   "Warm and simple words. Output only the translation.\n\n" + text, who=who, max_tokens=700)
    return out.strip() if out else text


# ---------------------------------------------------------------- your own Mindy
PERSONAS = {"sweet": "Sweet", "cheeky": "Cheeky", "calm": "Calm"}
HUES = {"green": 150, "blue": 210, "purple": 270, "pink": 330, "red": 0, "orange": 30, "yellow": 50, "teal": 175}


def mindy_name(user: dict) -> str:
    return user.get("mindy_name") or "Mindy"


def rename_out(text: str, user: dict) -> str:
    n = user.get("mindy_name")
    if not n or n == "Mindy":
        return text
    return re.sub(r"\bMindy\b(?! (?:app|Care|Plus|buttons|team|Wrapped))", n, text)


# ---------------------------------------------------------------- brain score (0-1000)
def brain_score(db: DB, user: dict) -> dict:
    uid = user["id"]
    m = mind.mind(db, user)
    fill = sum(r["fill"] for r in m["regions"]) / len(m["regions"])               # up to 400: how well Mindy knows you
    streak = max([h["streak"] for h in m["habits"]] or [0])                       # up to 150: habits
    done = db.one("SELECT COUNT(*) n FROM items WHERE user_id=? AND done_at IS NOT NULL", (uid,))["n"]  # up to 150: saves made real
    scams = db.one("SELECT COUNT(*) n FROM scam_reports WHERE reporter=?", (uid,))["n"]                 # up to 100: protecting others
    people = len(m["people"])                                                                         # up to 100: people remembered
    kept = db.one("SELECT COUNT(*) n FROM reminders WHERE user_id=? AND status IN ('sent','done')", (uid,))["n"]  # up to 100
    parts = {"knows you": round(fill * 400), "habits": min(150, streak * 15), "saves made real": min(150, done * 15),
             "scams stopped": min(100, scams * 25), "people remembered": min(100, people * 10), "reminders kept": min(100, kept * 4)}
    total = sum(parts.values())
    level = next(l for t, l in ((900, "Legend"), (700, "Mastermind"), (500, "Sharp"), (300, "Switched on"), (120, "Warming up"), (0, "Just met")) if total >= t)
    return {"score": total, "level": level, "parts": parts, "next": mind._public_q(mind.next_question(db, uid, ignore_recent=True))}


# ---------------------------------------------------------------- schemes and benefits
SCHEMES_IN = [
    ("PM-KISAN", "farmer", "Yearly income support paid to farmer families in instalments.", "https://pmkisan.gov.in"),
    ("Crop insurance (PMFBY)", "farmer", "Insurance against crop loss. Watch the enrolment deadline each season.", "https://pmfby.gov.in"),
    ("Ayushman Bharat PM-JAY", "health poor senior", "Free hospital treatment cover for eligible families, and for everyone aged 70+.", "https://pmjay.gov.in"),
    ("e-Shram card", "worker labour domestic vendor driver rider", "ID and benefits for unorganised workers aged 16–59.", "https://eshram.gov.in"),
    ("PM SVANidhi", "vendor", "Small working-capital loans for street vendors.", "https://pmsvanidhi.mohua.gov.in"),
    ("Construction worker (BOCW) card", "construction labour", "State welfare board benefits for building workers. Register with your state board.", "https://www.myscheme.gov.in/search?q=construction%20worker"),
    ("PM Awas Yojana", "house poor", "Help to build or buy a first pucca house.", "https://pmay-urban.gov.in"),
    ("PM Ujjwala", "woman poor gas", "LPG connection for women from poor households.", "https://www.pmuy.gov.in"),
    ("Sukanya Samriddhi", "girl daughter", "High-interest savings for a daughter under 10, at a post office or bank.", "https://www.myscheme.gov.in/search?q=sukanya"),
    ("Jan Dhan account", "bank poor", "Zero-balance bank account with RuPay card and insurance.", "https://pmjdy.gov.in"),
    ("PM Suraksha Bima", "insurance worker", "Accident cover for about ₹20 a year, from your bank (age 18–70).", "https://www.jansuraksha.gov.in"),
    ("PM Jeevan Jyoti Bima", "insurance worker", "Life cover for about ₹436 a year, from your bank (age 18–50).", "https://www.jansuraksha.gov.in"),
    ("Atal Pension Yojana", "pension worker", "Small guaranteed pension from 60, join between 18 and 40.", "https://www.myscheme.gov.in/search?q=atal%20pension"),
    ("National Scholarship Portal", "student", "Central and state scholarships in one place.", "https://scholarships.gov.in"),
    ("PM Matru Vandana", "pregnant mother", "Cash support for pregnant women and new mothers.", "https://pmmvy.wcd.gov.in"),
    ("Mudra loan", "business shop", "Loans for small businesses without collateral.", "https://www.mudra.org.in"),
    ("Jeevan Pramaan", "pension pensioner senior", "Digital life certificate for pensioners, from home.", "https://jeevanpramaan.gov.in"),
    ("UDID card", "disability", "One disability ID for benefits across India.", "https://www.swavlambancard.gov.in"),
]
SCHEME_WORDS = {"farmer": r"farm|kisan|crop|kheti", "vendor": r"vendor|thela|hawker|stall|street food", "construction": r"construction|mason|site",
                "labour": r"labou?r|mazdoor|daily wage", "worker": r"worker|job|kaam", "domestic": r"maid|domestic|bai", "driver": r"driver|auto|taxi|rider|delivery",
                "student": r"student|school|college|scholarship|padhai", "girl": r"girl|daughter|beti", "woman": r"woman|women|mahila|wife",
                "senior": r"senior|old|70|elderly|buzurg", "pensioner": r"pension", "pregnant": r"pregnan", "business": r"business|shop|dukaan",
                "house": r"house|ghar|home", "gas": r"gas|lpg|cylinder", "health": r"health|hospital|ill|bimari|ilaj", "disability": r"disab|handicap|divyang",
                "poor": r"poor|garib|bpl|ration"}


def schemes(user: dict, text: str, db: DB) -> dict:
    p = countries.for_user(db, user)
    low = text.lower()
    if p.get("code") not in ("IN", "") or (p.get("code") == "" and not re.search(r"yojana|scheme|sarkari", low)):
        portal = p.get("benefits")
        return R(f"🏛️ In {p['name']}, the official place to check what you can get is: {portal}\nTell me your situation (work, age, family) and I'll explain what to look for there."
                 if portal else "🏛️ Tell me your country and situation (work, age, family) and I'll point you to the official benefits page.")
    tags = {t for t, rx in SCHEME_WORDS.items() if re.search(rx, low)}
    if not tags:
        return R("🏛️ Tell me a little so I can match schemes, like:\n• _schemes farmer_\n• _schemes street vendor_\n• _schemes student girl_\n• _schemes senior 72_\n"
                 "Or check everything at myscheme.gov.in")
    hits = [s for s in SCHEMES_IN if tags & set(s[1].split())][:6]
    lines = "\n\n".join(f"*{n}*\n{d}\n{u}" for n, _, d, u in hits) or "I couldn't match one. Try myscheme.gov.in"
    return R(f"🏛️ Schemes you may qualify for:\n\n{lines}\n\n_Rules change, so confirm on the official site. Never pay an agent to apply._")


# ---------------------------------------------------------------- loan-app alert
LOAN_RX = re.compile(r"\b(loan|karz|karza|credit line|cash advance)\b", re.I)
LOAN_RED = re.compile(r"(pre.?approved|instant|processing fee|advance fee|harass|contacts|morph|recovery agent|abuse|threat|\.apk|7 days|no documents|without cibil)", re.I)


def loan_alert(user, text, db) -> dict | None:
    if not (LOAN_RX.search(text) and LOAN_RED.search(text)):
        return None
    p = countries.for_user(db, user)
    india = p.get("code") == "IN"
    lines = ["🚨 *This looks like a predatory loan.*", "• Real lenders never ask for a fee *before* paying you.",
             "• Never install a loan app from a link or .apk file; it can read your contacts and photos.",
             "• If an app is threatening you or your contacts: don't pay more, screenshot everything, and report it."]
    if india:
        lines.append("• Check if the lender is RBI-regulated and report illegal apps at sachet.rbi.org.in. Harassment: call 1930 or cybercrime.gov.in")
    else:
        lines.append("• " + p["scam"])
    return R("\n".join(lines))


# ---------------------------------------------------------------- subscriptions and card due dates
SUBS = r"netflix|spotify|prime|amazon prime|hotstar|disney|youtube premium|youtube|icloud|google one|chatgpt|claude|gym|jio|airtel|vi |broadband|wifi|apple music|canva|adobe|xbox|playstation|zee5|sonyliv|audible|kindle|linkedin|duolingo"
SUB_RX = re.compile(rf"^(?:(?:add )?sub(?:scription)?:?\s+)?({SUBS}|[a-z][\w ]{{1,20}}?)\s+(?:₹|rs\.?|inr|\$|£|€|aed|r\$)?\s*(\d[\d,]*)(?:\s*(?:per|a|/|every)\s*(month|year|week))?(?:\s+on\s+(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?)?\s*$", re.I)


def subscription(user, text, db) -> dict | None:
    low = text.lower().strip()
    if low in ("my subscriptions", "subscriptions", "subs", "show subscriptions"):
        rows = db.q("SELECT text FROM reminders WHERE user_id=? AND kind='sub' AND status='pending' ORDER BY due_at", (user["id"],))
        if not rows:
            return R("📺 No subscriptions yet. Tell me like _Netflix 649 on the 5th_.")
        total = sum(int(re.search(r"(\d[\d,]*)", r["text"]).group(1).replace(",", "")) for r in rows if re.search(r"\d", r["text"]))
        p = countries.for_user(db, user)
        return R("📺 *Your subscriptions*\n" + "\n".join("• " + r["text"] for r in rows) + f"\n\nAbout *{countries.money(p, total)} a month*. Reply _cancel Netflix_ to drop one.",
                 app=("See them all", "mind"))
    m = re.match(r"^cancel ([a-z][\w ]{1,20})$", low)
    if m:
        n = db.x("UPDATE reminders SET status='cancelled' WHERE user_id=? AND kind='sub' AND status='pending' AND lower(text) LIKE ?", (user["id"], f"%{m.group(1)}%"))
        return R(f"🗑️ Stopped tracking {m.group(1).title()}. Remember to cancel it in the app too!") if n else None
    m = re.match(r"^(?:my )?(?:credit )?card(?: bill)? (?:is )?due (?:on )?(?:the )?(\d{1,2})(?:st|nd|rd|th)?", low)
    if m:
        day = int(m.group(1))
        mind.monthly_reminder(db, user, "💳 Card bill due in 2 days. Pay in full to avoid interest.", max(1, day - 2))
        return R(f"💳 Every month I'll remind you 2 days before the {day}th.")
    m = SUB_RX.match(low)
    if not m or not (re.match(SUBS, m.group(1)) or low.startswith(("sub ", "subscription"))):
        return None
    name, amt, per, day = m.group(1).strip().title(), int(m.group(2).replace(",", "")), (m.group(3) or "month"), int(m.group(4) or _today(user).day)
    p = countries.for_user(db, user)
    rid = mind.monthly_reminder(db, user, f"{name} {countries.money(p, amt)} renews in 2 days", max(1, day - 2))
    db.x("UPDATE reminders SET kind='sub' WHERE id=?", (rid,))
    return R(f"📺 Tracking *{name}* ({countries.money(p, amt)}/{per}). I'll ping you 2 days before it renews, so you can cancel if you don't use it.")


# ---------------------------------------------------------------- documents with expiry
DOC_RX = re.compile(r"\b(passport|driving licen[cs]e|licen[cs]e|dl|insurance|puc|mot|car tax|road tax|tv licen[cs]e|visa|brp|residence permit|emirates id|"
                    r"id card|rc|permit|warranty|lease|rent agreement|agreement|policy|railcard|pollution|fitness|registration|itv|tüv|contrôle technique)\b"
                    r".{0,30}?\b(expires?|expiring|expiry|valid (?:till|until|to)|renew(?:al)?(?: due)?|due)\b(?:\s+(?:on|by|in))?\s*(.+)$", re.I)


def vault(user, text, db) -> dict | None:
    low = text.lower().strip()
    if low in ("my documents", "documents", "vault", "my vault", "expiry", "expiries"):
        ds = mind.docs(db, user["id"])
        if not ds:
            return R("🗂️ Nothing saved yet. Tell me like _passport expires 12 March 2029_ or _MOT due 3 June_.")
        return R("🗂️ *Your documents*\n" + "\n".join(f"• {d['name'].title()}: {date.fromisoformat(d['expires']):%d %b %Y}" for d in ds), app=("Open the vault", "mind"))
    m = DOC_RX.search(text)
    if not m:
        return None
    d = mind.parse_date(m.group(3))
    if not d:
        return R(f"🗂️ When does your {m.group(1)} expire? Send it like _3 May 2027_.")
    r = mind.add_doc(db, user, m.group(1).lower(), d)
    mind.set_fact(db, user["id"], f"doc_{m.group(1).lower().replace(' ', '_')}", d.isoformat(), "documents", "told")
    when = ", ".join(f"{x} days" if x > 1 else "the day" for x in r["reminders"])
    return R(f"🗂️ Saved: *{m.group(1).title()}* expires {d:%d %b %Y}." + (f" I'll remind you {when} before." if when else " That's very soon. Renew now!"))


# ---------------------------------------------------------------- business: customer reminders and bills
PHONE_RX = re.compile(r"(\+?\d[\d \-]{8,14}\d)")


def business(user, text, db) -> dict | None:
    low = text.lower()
    m = re.match(r"^(?:customer|client|patient)\s+([a-z][a-z .']{1,30}?)\s+(\+?\d[\d \-]{8,14}\d)\s+(.+)$", text, re.I)
    if m:
        name, phone, what = m.group(1).strip().title(), re.sub(r"\D", "", m.group(2)), m.group(3).strip()
        from .brain import parse_when
        when = parse_when(what, user.get("tz") or "UTC")
        biz = mind.facts(db, user["id"]).get("business_name") or user.get("name") or "us"
        msg = f"Hi {name}, a reminder of your {re.sub(r'(?i)^(appointment|booking)', 'appointment', what)} with {biz}. Reply here if you need to change it. Thank you!"
        if when:
            db.add_reminder(user["id"], f"Send {name} their reminder ({what})", (when - timedelta(hours=3)).astimezone(timezone.utc).replace(microsecond=0).isoformat())
        return R(f"🏪 Saved *{name}*. Tap to send them the reminder now" + (", and I'll ping you again 3 hours before." if when else "."),
                 links=[("Send to " + name, f"https://wa.me/{phone}?text={quote(msg)}")])
    m = re.match(r"^(?:bill|invoice|charge)\s+([a-z][a-z .']{1,30}?)\s+(?:(\+?\d[\d\-]{8,14}\d)\s+)?(?:₹|rs\.?|\$|£|€)?\s*(\d[\d,]*)(?:\s+(?:for\s+)?(.+))?$", text, re.I)
    if m:
        name, phone, amt = m.group(1).strip().title(), m.group(2), int(m.group(3).replace(",", ""))
        req = pay_request(db, user, name, amt, phone, m.group(4))
        return R(f"🧾 Bill for *{name}*: {req['amount']}. Tap to send it with a pay link.", links=[("Send bill", req["whatsapp"])])
    if low.startswith("my business is "):
        mind.set_fact(db, user["id"], "business_name", text[15:].strip(), "work", "told")
        return R(f"🏪 Got it: *{text[15:].strip()}*. Customer reminders will be signed with that name.")
    return None


def pay_request(db, user, person, amount, phone=None, note=None) -> dict:
    p = countries.for_user(db, user)
    link = None
    if user.get("upi") and p.get("code") in ("IN", ""):
        link = skills.go_link("upi://pay?" + urlencode({"pa": user["upi"], "pn": user.get("name") or "", "am": amount, "cu": "INR", "tn": (note or "via Mindy")[:40]}))
    elif user.get("pay_link"):
        link = user["pay_link"]
    amt = countries.money(p, amount)
    msg = f"Hi {person}! " + (f"For {note}: " if note else "Gentle reminder: ") + f"{amt} 🙂" + (f" Pay in one tap: {link}" if link else "") + " Thanks!"
    to = re.sub(r"\D", "", phone) if phone else ""
    return {"amount": amt, "message": msg, "whatsapp": (f"https://wa.me/{to}?text=" if to else "https://wa.me/?text=") + quote(msg)}


# ---------------------------------------------------------------- household and shop staff
def staff(user, text, db) -> dict | None:
    low = text.lower().strip()
    uid = user["id"]
    m = re.match(r"^(?:add )?staff:?\s+([a-z][a-z .']{1,24}?)\s+(?:salary\s+)?(?:₹|rs\.?|\$|£|€)?\s*(\d[\d,]*)(?:\s*(?:a|per|/)\s*month)?$", low)
    if m:
        name = m.group(1).strip().title()
        db.x("INSERT INTO staff(user_id,name,salary,created_at) VALUES(?,?,?,?) ON CONFLICT(user_id,name) DO UPDATE SET salary=excluded.salary",
             (uid, name, int(m.group(2).replace(",", "")), now_iso()))
        return R(f"🧹 Added *{name}*. Tell me _{name} absent_, _{name} half day_ or _{name} advance 2000_, and say _staff pay_ at month end.")
    names = {r["name"].lower(): r for r in db.q("SELECT * FROM staff WHERE user_id=?", (uid,))}
    if low in ("staff pay", "salary sheet", "staff salary", "pay staff", "staff"):
        if not names:
            return R("🧹 No staff yet. Add like _staff Sunita 12000_.")
        p = countries.for_user(db, user)
        month = _today(user).strftime("%Y-%m")
        lines = []
        for s in names.values():
            logs = db.q("SELECT kind, amount FROM staff_log WHERE user_id=? AND name=? AND day LIKE ?", (uid, s["name"], month + "%"))
            absent = sum(1 for l in logs if l["kind"] == "absent") + 0.5 * sum(1 for l in logs if l["kind"] == "half")
            adv = sum(l["amount"] or 0 for l in logs if l["kind"] == "advance")
            pay = round(s["salary"] - absent * s["salary"] / 30 - adv)
            lines.append(f"• *{s['name']}*: {countries.money(p, pay)}  ({countries.money(p, s['salary'])} − {absent:g} days off − {countries.money(p, adv)} advance)")
        return R("🧹 *Staff pay this month*\n" + "\n".join(lines) + "\n\n_Days off are counted at salary ÷ 30. Paid leave is your call; say _remove absent Sunita_ to undo one._")
    m = re.match(r"^([a-z][a-z .']{1,24}?)\s+(absent|leave|off|chutti|half day|half|advance|took advance)(?:\s+(?:today)?)?\s*(?:₹|rs\.?|\$|£|€)?\s*(\d[\d,]*)?$", low)
    if m and m.group(1).strip() in names:
        s = names[m.group(1).strip()]
        kind = "advance" if "advance" in m.group(2) else "half" if "half" in m.group(2) else "absent"
        if kind == "advance" and not m.group(3):
            return R(f"How much advance did {s['name']} take? Like _{s['name']} advance 2000_.")
        db.x("INSERT INTO staff_log(user_id,name,kind,amount,day) VALUES(?,?,?,?,?)", (uid, s["name"], kind, int((m.group(3) or "0").replace(",", "")), _today(user).isoformat()))
        return R(f"📝 Noted for {s['name']}: {'advance ' + m.group(3) if kind == 'advance' else 'half day' if kind == 'half' else 'day off'} today.")
    m = re.match(r"^remove absent ([a-z][a-z .']{1,24})$", low)
    if m and m.group(1).strip() in names:
        r = db.one("SELECT id FROM staff_log WHERE user_id=? AND name=? AND kind IN ('absent','half') ORDER BY id DESC LIMIT 1", (uid, names[m.group(1).strip()]["name"]))
        if r:
            db.x("DELETE FROM staff_log WHERE id=?", (r["id"],))
            return R("↩️ Removed the last day off.")
    return None


# ---------------------------------------------------------------- connect calendar and email (free, no OAuth)
def connect(user, text, db, key: str) -> dict | None:
    low = text.lower().strip()
    if re.match(r"^(connect|add|sync)( my)? (google |apple |outlook )?calendar$", low):
        url = f"{settings.app_url.rstrip('/')}/cal/{key}.ics"
        return R("📅 Add this link as a *subscribed calendar* and your Mindy reminders show up there:\n"
                 f"{url}\n\nGoogle Calendar: Other calendars → + → From URL. iPhone: Settings → Calendar → Accounts → Add Subscribed Calendar. Keep the link private.")
    if re.match(r"^(connect|forward|link)( my)? (e-?mail|gmail|outlook|inbox)$", low):
        addr = f"{key}@{settings.email_domain}"
        return R(f"📧 Forward any email to *{addr}* and I'll save it, set reminders for dates in it, and warn you if it looks like phishing.\n"
                 "Tip: in Gmail, set a filter to auto-forward bills and tickets there.")
    return None


# ---------------------------------------------------------------- family code word and "is it really them?"
def _hash(word: str) -> str:
    return hashlib.sha256(("mindy-cw:" + word.strip().lower()).encode()).hexdigest()


def codeword(user, text, db) -> dict | None:
    low = text.lower().strip()
    m = re.match(r"^(?:set )?(?:family )?code ?word(?: is)?:?\s+([a-z0-9]{3,30})$", low)
    if m and not low.startswith(("check", "is ")):
        fam = [user["id"]] + [f["id"] for f in care.family_of(db, user["id"])]
        for uid in fam:
            db.x("INSERT OR REPLACE INTO codewords(user_id,hash,set_by,created_at) VALUES(?,?,?,?)", (uid, _hash(m.group(1)), user["id"], now_iso()))
        notify = [(f, f"🔐 {user.get('name') or 'Your family'} set a family code word on Mindy. Ask them for it in person, never by message. "
                      "If anyone calls 'from the family' asking for money, ask for the word.", []) for f in fam if f != user["id"]]
        return R(f"🔐 Family code word set for {len(fam)} people. Tell them the word *in person or on a call*, not by text. "
                 "If a voice or video call asks for money, ask for the word. AI can copy a voice, not a secret.", notify=notify)
    m = re.match(r"^(?:check|is the)? ?code ?word (?:is )?([a-z0-9]{3,30})\??$", low)
    if m and low.startswith(("check", "is")):
        r = db.one("SELECT hash FROM codewords WHERE user_id=?", (user["id"],))
        if not r:
            return R("No family code word yet. Set one: _code word mango_ (pick your own).")
        return R("✅ That's your family's word." if r["hash"] == _hash(m.group(1)) else "❌ That's *not* the word. Treat the call as a scam: hang up and call them back on their saved number.")
    m = re.match(r"^(?:verify|is (?:this|it) really|check(?: if)? (?:it'?s)? ?really)\s+(?:my\s+)?([a-z][a-z .']{1,24}?)\??$", low)
    if m:
        who = m.group(1).strip()
        fam = care.family_of(db, user["id"])
        hit = next((f for f in fam if (f["name"] or "").lower().startswith(who) or who in (f["name"] or "").lower()), None)
        if not hit:
            return R(f"I can only check people linked to you as family on Mindy. Meanwhile: hang up and call {who.title()} back on the number saved in your phone.")
        rid = db.x("INSERT INTO verify_req(asker,target,created_at) VALUES(?,?,?)", (user["id"], hit["id"], now_iso()))
        return R(f"📨 I've asked {hit['name']} directly on their own Mindy. Don't send money until they answer.",
                 notify=[(hit["id"], f"🔐 {user.get('name') or 'Your family member'} is getting a call or message that claims to be you. "
                                     "Is it really you contacting them right now?", [(f"verify:yes:{rid}", "Yes, it's me"), (f"verify:no:{rid}", "No, not me!")])])
    return None


# ---------------------------------------------------------------- numbers, businesses, impersonation
def numbers(user, text, db) -> dict | None:
    low = text.lower().strip()
    m = re.match(r"^(?:check|who is|whose|who's|caller|is)\s*(?:number|no\.?|this number)?\s*(\+?\d[\d \-]{6,15}\d)\s*(?:safe|real|scam)?\??$", low)
    if m:
        info = skills.number_lookup(db, m.group(1))
        if info["verified"]:
            return R(f"✅ *{m.group(1)}* is a verified business on Mindy: *{info['verified']}*.")
        if info["reports"]:
            return R(f"🚩 *{info['reports']} people* reported this number as a scam. Don't share codes or pay. Block it.")
        return R(f"ℹ️ Nobody on Mindy has reported {m.group(1)}, and it isn't a verified business. That doesn't prove it's safe: never share OTPs or pay on a call you didn't expect.")
    m = re.match(r"^(?:register|verify) my business(?: as)?:?\s+(.{2,60})$", text.strip(), re.I)
    if m:
        acc = db.one("SELECT ext FROM accounts WHERE user_id=? AND ext GLOB '[0-9]*' LIMIT 1", (user["id"],))
        db.x("INSERT INTO business_apps(user_id,name,number,created_at) VALUES(?,?,?,?)", (user["id"], m.group(1).strip(), (acc or {}).get("ext"), now_iso()))
        return R(f"🏪 Thanks! *{m.group(1).strip()}* is in the queue. A person checks every business before the ✅ goes live, so customers can trust your number.")
    return None


def impersonation(user, text, db) -> dict | None:
    m = re.match(r"^(?:fake|impersonat\w*)\s+(?:profile|account|page|ad)?\s*(?:of|for|using)?\s+(.+?)\s+((?:https?://|www\.)\S+)$", text.strip(), re.I)
    if m:
        key = re.sub(r"\W+", " ", m.group(1).lower()).strip()
        db.x("INSERT INTO impersonation(name_key,url,reporter,created_at) VALUES(?,?,?,?)", (key, m.group(2), user["id"], now_iso()))
        n = db.one("SELECT COUNT(*) n FROM impersonation WHERE name_key=?", (key,))["n"]
        return R(f"🙏 Reported. {n} report{'s' if n != 1 else ''} about fakes of *{m.group(1).strip()}* so far. Also report it on the platform itself (⋯ → Report → Pretending to be someone).")
    m = re.match(r"^is (?:this|it) (?:really|the real)\s+(.+?)\??\s+((?:https?://|www\.)\S+)$", text.strip(), re.I)
    if m:
        key = re.sub(r"\W+", " ", m.group(1).lower()).strip()
        url = m.group(2).rstrip("/").lower()
        if db.one("SELECT 1 FROM official_handles WHERE name_key=? AND lower(rtrim(url,'/'))=?", (key, url)):
            return R(f"✅ That's on {m.group(1).strip()}'s official list.")
        n = db.one("SELECT COUNT(*) n FROM impersonation WHERE name_key=? AND lower(rtrim(url,'/'))=?", (key, url))["n"]
        if n:
            return R(f"🚩 {n} people reported this as a *fake* {m.group(1).strip()}. Don't follow, pay or invest.")
        return R(f"⚠️ It's not on {m.group(1).strip()}'s official list on Mindy. Famous people never DM you about investments, giveaways or crypto. Treat it as fake unless they post it on their verified account.")
    return None


# ---------------------------------------------------------------- a real person, and iPhone screen help
def human(user, text, db) -> dict | None:
    if re.match(r"^(human|real person|talk to (a )?(human|person)|need a person|insaan|agent|person please|help me person)\b", text.lower().strip()):
        db.x("INSERT INTO help_queue(user_id,text,created_at) VALUES(?,?,?)", (user["id"], text, now_iso()))
        return R("🙋 A real person from the Mindy team will reply right here, usually within a few hours. Send a screenshot of where you're stuck meanwhile.")
    return None


def screen_share(user, text, db) -> dict | None:
    if not re.search(r"\b(share (my )?screen|screen ?share|show (my|them) (my )?screen|see my screen)\b", text.lower()):
        return None
    return R("📱 *Show your screen to family, live:*\n1. Start a WhatsApp *video call* with them\n2. Tap the screen once, then the *share screen* icon (phone with an arrow)\n"
             "3. Tap *Start broadcast / Start now*\nThey'll see your screen and can guide you. Or send me a screenshot and I'll circle where to tap.")


# ---------------------------------------------------------------- gifts
def gifts(user, text, db) -> dict | None:
    low = text.lower().strip()
    uid = user["id"]
    p = countries.for_user(db, user)
    m = re.match(r"^(?:group gift|gift pool|pool)\s+(?:for\s+)?(.+?)\s+(?:₹|rs\.?|\$|£|€)?\s*(\d[\d,]*)\s+(?:with|between|from)\s+(.+)$", text.strip(), re.I)
    if m:
        title, total = m.group(1).strip(), int(m.group(2).replace(",", ""))
        people = [x.strip().title() for x in re.split(r",|\band\b|&", m.group(3)) if x.strip()][:20]
        share = math.ceil(total / (len(people) + 1))
        gid = db.x("INSERT INTO gifts(user_id,title,total,share,created_at) VALUES(?,?,?,?,?)", (uid, title, total, share, now_iso()))
        for n in people:
            db.x("INSERT OR IGNORE INTO gift_people(gift_id,name) VALUES(?,?)", (gid, n))
        links = [(f"Ask {n}", pay_request(db, user, n, share, None, f"our gift for {title}")["whatsapp"]) for n in people[:3]]
        return R(f"🎁 *Gift for {title}*: {countries.money(p, total)}, {countries.money(p, share)} each ({len(people) + 1} people incl. you).\n"
                 f"Tap to send each person their share. Say _gift paid {people[0]}_ as money comes in, and _gift status_ to see who's left.", links=links)
    m = re.match(r"^gift paid ([a-z][a-z .']{1,24})$", low)
    if m:
        g = db.one("SELECT * FROM gifts WHERE user_id=? AND closed=0 ORDER BY id DESC LIMIT 1", (uid,))
        if g and db.x("UPDATE gift_people SET paid=1 WHERE gift_id=? AND lower(name)=?", (g["id"], m.group(1).strip())):
            left = db.one("SELECT COUNT(*) n FROM gift_people WHERE gift_id=? AND paid=0", (g["id"],))["n"]
            return R(f"✅ {m.group(1).title()} paid. " + ("Everyone's in! 🎉 Time to buy it." if not left else f"{left} still to pay."))
    if low in ("gift status", "gift pool status", "who paid"):
        g = db.one("SELECT * FROM gifts WHERE user_id=? AND closed=0 ORDER BY id DESC LIMIT 1", (uid,))
        if g:
            ppl = db.q("SELECT * FROM gift_people WHERE gift_id=?", (g["id"],))
            return R(f"🎁 *{g['title']}* ({countries.money(p, g['share'])} each)\n" + "\n".join(f"{'✅' if x['paid'] else '⏳'} {x['name']}" for x in ppl))
    m = re.match(r"^(?:my )?wish ?list:?\s+(.+)$", text.strip(), re.I)
    if m and not low.startswith(("show", "my wishlist$")):
        name, rows = db.list_add(uid, "Wishlist", [x for x in re.split(r",|\n", m.group(1)) if x.strip()])
        return R(f"🎁 Added to your wishlist ({len(rows)} things). Close friends on Mindy can see it near your birthday, so you get things you actually want.")
    m = re.match(r"^(?:what does |what do )?([a-z][a-z .']{1,24}?)(?:'s| s)? (?:wish ?list|want(?:s)? for (?:her|his|their) birthday)\??$", low)
    if m and m.group(1) not in ("my", "show", "show my"):
        who = m.group(1).strip()
        fr = db.one("SELECT u.id, u.name FROM friends f JOIN users u ON u.id=f.b WHERE f.a=? AND lower(u.name) LIKE ? AND u.share_matches=1", (uid, who + "%"))
        if fr:
            _, items = db.list_show(fr["id"], "Wishlist")
            if items:
                return R(f"🎁 *{fr['name']}'s wishlist*\n" + "\n".join("• " + i["text"] for i in items[:10]))
        return R(f"🎁 {who.title()} hasn't shared a wishlist with you on Mindy. Ask them to send me _wishlist: ..._, or tell me their age and what they like and I'll suggest ideas.")
    m = re.match(r"^(?:gift ideas?|what (?:should i )?(?:gift|get))\s+(?:for\s+)?(.+?)(?:\s+(?:under|below|budget)\s+(?:₹|rs\.?|\$|£|€)?\s*(\d[\d,]*))?\??$", low)
    if m:
        who, budget = m.group(1).strip(), m.group(2)
        person = db.one("SELECT * FROM people WHERE user_id=? AND lower(name)=?", (uid, who))
        facts_about = f" They like: {person['gift_ideas']}." if person and person.get("gift_ideas") else ""
        out = llm.chat(f"Suggest 5 thoughtful gift ideas for {who}{' under ' + countries.money(p, int(budget.replace(',', ''))) if budget else ''}.{facts_about} "
                       f"Country: {p['name']}. One short line each, practical things people actually love. No intro.", who=str(uid), max_tokens=250)
        ideas = out or "• Something they mentioned wanting lately\n• An experience together (a meal, a show)\n• A framed photo of you both\n• A good-quality everyday item they use\n• A handwritten note with any gift"
        return R(f"🎁 Ideas for *{who.title()}*:\n{ideas}", links=[("Browse ideas", "https://www.google.com/search?tbm=shop&q=" + quote_plus(f"gift for {who}"))])
    m = re.match(r"^(?:shagun|gift money|send gift|eidi|ang ?pao|hongbao|cash gift)\s+(?:₹|rs\.?|\$|£|€)?\s*(\d[\d,]*)\s+(?:to|for)\s+([a-z][a-z .']{1,24}?)(?:\s+for\s+(.+))?$", low)
    if m:
        amt, who, occ = int(m.group(1).replace(",", "")), m.group(2).strip().title(), (m.group(3) or "birthday")
        from .brain import draft_wish
        wish = draft_wish(who, occ, str(uid))
        return R(f"💌 For {who}, {countries.money(p, amt)}:\n\n_{wish}_\n\nSend the money from your payments app, then tap to send the wish.",
                 links=[("Send the wish", "https://wa.me/?text=" + quote(wish))])
    return None


# ---------------------------------------------------------------- wardrobe and outfits
def wardrobe(user, text, db) -> dict | None:
    low = text.lower().strip()
    uid = user["id"]
    m = re.match(r"^(?:i )?wore (?:my |the )?(.+?) (?:to|at|for) (.+)$", low)
    if m:
        db.save_item(uid, "note", f"Wore {m.group(1)} to {m.group(2)} on {_today(user):%d %b %Y}", collection="Outfits")
        return R("👗 Noted. I'll warn you before you repeat it at the same crowd.")
    m = re.match(r"^what did i wear (?:to|at|for) (.+?)\??$", low)
    if m:
        hits = [i for i in db.search(uid, m.group(1)) if i.get("collection") == "Outfits"]
        return R("👗 " + (hits[0]["text"] if hits else f"I don't have that one. Next time say _wore the blue kurta to {m.group(1)}_."))
    m = re.match(r"^what (?:should|shall|can) i wear(?: (?:to|for|at|on))?\s*(.*?)\??$", low)
    if m:
        items = db.q("SELECT title, text FROM items WHERE user_id=? AND collection='Wardrobe' ORDER BY id DESC LIMIT 40", (uid,))
        if not items:
            return R("👗 Your wardrobe is empty! Send me photos of your clothes with the caption *wardrobe*, one at a time, and I'll start picking outfits for you.")
        worn = [i["text"].lower() for i in db.q("SELECT text FROM items WHERE user_id=? AND collection='Outfits'", (uid,))]
        listing = "\n".join(f"- {(i.get('title') or i['text'])[:80]}" for i in items)
        out = llm.chat(f"Wardrobe:\n{listing}\n\nRecently worn: {'; '.join(worn[-6:]) or 'nothing noted'}\nOccasion: {m.group(1) or 'today'}\n"
                       "Pick one outfit from the wardrobe only (2 to 4 pieces) and say why in one line. Avoid repeats for the same crowd.",
                       who=str(uid), max_tokens=160)
        pick = out or "Try: " + ", ".join((i.get("title") or i["text"])[:30] for i in items[:3])
        return R("👗 " + pick, app=("See your wardrobe", "mind"))
    return None


def tryon_allowed(db, uid) -> bool:
    day = date.today().isoformat()
    r = db.one("SELECT n FROM tryon_use WHERE user_id=? AND day=?", (uid, day))
    if r and r["n"] >= settings.tryon_daily:
        return False
    db.x("INSERT INTO tryon_use(user_id,day,n) VALUES(?,?,1) ON CONFLICT(user_id,day) DO UPDATE SET n=n+1", (uid, day))
    return True


# ---------------------------------------------------------------- safety: "I'm OK" and "check on me"
def safety(user, text, db) -> dict | None:
    low = text.lower().strip()
    uid = user["id"]
    m = re.match(r"^check on me(?: in (\d+) ?(min|mins|minutes|hour|hours|hr|hrs))?$", low)
    if m:
        n = int(m.group(1) or 30) * (60 if (m.group(2) or "m").startswith("h") else 1)
        due = datetime.now(timezone.utc) + timedelta(minutes=n)
        db.x("UPDATE safety SET cleared_at=? WHERE user_id=? AND kind='check' AND cleared_at IS NULL", (now_iso(), uid))
        db.x("INSERT INTO safety(user_id,kind,due_at,created_at) VALUES(?,?,?,?)", (uid, "check", due.replace(microsecond=0).isoformat(), now_iso()))
        fam = len(care.family_of(db, uid))
        return R(f"🫶 I'll check on you in {n} minutes. Reply *safe* any time. If you don't answer within 10 minutes of my check, "
                 + (f"I'll alert your {fam} family member{'s' if fam != 1 else ''} with your last saved location." if fam else "I can't alert anyone yet: link family in the app first."))
    if low in ("safe", "i'm safe", "im safe", "home", "reached", "pahunch gaya", "pahunch gayi"):
        n = db.x("UPDATE safety SET cleared_at=? WHERE user_id=? AND kind='check' AND cleared_at IS NULL", (now_iso(), uid))
        if n:
            return R("💚 Glad you're safe. Check cleared.")
    if low in ("i'm ok", "im ok", "i am ok", "ok today", "theek hoon", "theek hu", "all good"):
        db.x("INSERT INTO safety(user_id,kind,due_at,created_at,cleared_at) VALUES(?,?,?,?,?)", (uid, "ok", now_iso(), now_iso(), now_iso()))
        return R("💚 Thank you! Your family can see you're OK today.")
    if low in ("daily ok on", "i'm ok daily", "daily check in", "daily check-in"):
        db.x("UPDATE users SET ok_daily=1 WHERE id=?", (uid,))
        return R("💚 From tomorrow I'll ask *Are you OK today?* at 10 am. If there's no tap by 1 pm, your family gets a gentle heads-up.")
    return None


# ---------------------------------------------------------------- small lovely things
def little(user, text, db) -> dict | None:
    low = text.lower().strip()
    uid = user["id"]
    m = re.match(r"^(?:i )?(?:kept|put|left|placed|rakha|rakhi)\s+(?:my |the )?(.+?)\s+(in|on|under|behind|inside|at|near)\s+(.+)$", low)
    if m:
        db.save_item(uid, "note", f"{m.group(1)} is {m.group(2)} {m.group(3)} (since {_today(user):%d %b})", collection="Where things are")
        return R(f"📍 Got it: *{m.group(1)}* → {m.group(2)} {m.group(3)}. Ask _where's my {m.group(1)}?_ any time.")
    m = re.match(r"^where(?:'s| is| are| did i (?:keep|put))\s+(?:my |the )?(.+?)\??$", low)
    if m:
        hits = [i for i in db.search(uid, m.group(1)) if i.get("collection") == "Where things are"]
        if hits:
            return R("📍 " + hits[0]["text"])
    m = re.match(r"^(?:time capsule|future me|note to future me|letter to future me)(?: in (\d+) ?(year|years|month|months))?:?\s*(.+)$", text.strip(), re.I)
    if m:
        n, unit = int(m.group(1) or 1), (m.group(2) or "year")
        open_at = datetime.now(timezone.utc) + (timedelta(days=365 * n) if unit.startswith("y") else timedelta(days=30 * n))
        db.x("INSERT INTO capsules(user_id,text,open_at,created_at) VALUES(?,?,?,?)", (uid, m.group(3).strip(), open_at.replace(microsecond=0).isoformat(), now_iso()))
        return R(f"💌 Sealed. I'll give it back to you on {open_at:%d %b %Y}. No peeking, not even me.")
    m = re.match(r"^(?:grateful|thankful|gratitude|good thing)(?: for| today)?:?\s+(.+)$", text.strip(), re.I)
    if m:
        db.save_item(uid, "note", m.group(1).strip(), collection="Gratitude")
        n = db.one("SELECT COUNT(*) n FROM items WHERE user_id=? AND collection='Gratitude'", (uid,))["n"]
        return R(f"🫙 In the jar. That's {n} good thing{'s' if n != 1 else ''}. At the end of the month I'll send you all of them on one card.")
    m = re.match(r"^split (?:₹|rs\.?|\$|£|€)?\s*(\d[\d,.]*)\s+(?:between|among|with|by)\s+(.+)$", low)
    if m:
        total = float(m.group(1).replace(",", ""))
        who = [x.strip().title() for x in re.split(r",|\band\b|&", m.group(2)) if x.strip()]
        if len(who) == 1 and who[0].isdigit():
            n = int(who[0])
            return R(f"🧮 {countries.money(countries.for_user(db, user), total / n)} each ({n} people).")
        share = math.ceil(total / (len(who) + 1))
        links = [(f"Ask {n}", pay_request(db, user, n, share, None, "our bill")["whatsapp"]) for n in who[:3]]
        for n in who:
            skills.khata_add(db, uid, {"person": n.lower(), "delta": share, "kind": "split"}, f"split {total}")
        return R(f"🧮 {countries.money(countries.for_user(db, user), share)} each, you included. Added to your khata; tap to send their share.", links=links)
    if re.match(r"^(what did i copy|clipboard|my clipboard|last copied|copied)\??$", low):
        rows = db.q("SELECT text FROM items WHERE user_id=? AND collection='Clipboard' ORDER BY id DESC LIMIT 5", (uid,))
        if not rows:
            return R("📋 Nothing yet. Set up the Mindy Clipboard shortcut (say _clipboard setup_) and double-tap the back of your iPhone after you copy.")
        return R("📋 *Your last copies*\n" + "\n".join(f"{i}. {r['text'][:200]}" for i, r in enumerate(rows, 1)), app=("Open clipboard", "clip"))
    if low in ("clipboard setup", "setup clipboard", "clipboard shortcut"):
        return R("📋 *Mindy Clipboard for iPhone*\n1. Install the shortcut (link in the app → Clipboard)\n2. Settings → Accessibility → Touch → *Back Tap* → Double Tap → *Save to Mindy*\n"
                 "Now copy anything, double-tap the back of your phone, and it's saved here and on your laptop.", app=("Open clipboard", "clip"))
    m = re.match(r"^help me (?:reply|respond|text|write|answer)(?: to)?\s*(.*)$", text.strip(), re.I)
    if m:
        _kv_set(db, f"await_reply:{uid}", m.group(1) or "them")
        return R("💬 Paste or forward their message, and tell me the vibe: _sweet_, _flirty_, _funny_, _firm_ or _sorry_.")
    return None


def draft_reply(user, text, db) -> dict | None:
    to = _kv_get(db, f"await_reply:{user['id']}")
    if not to:
        return None
    _kv_set(db, f"await_reply:{user['id']}", None)
    vibe = next((v for v in ("flirty", "funny", "firm", "sorry", "sweet", "formal") if v in text.lower()), "warm")
    out = llm.chat(f"Write 3 short alternative WhatsApp replies ({vibe} tone) to this message, numbered. Natural, not cheesy, respectful. Same language as the message.\n\n{text[:1500]}",
                   who=str(user["id"]), max_tokens=300)
    return R("💬 " + (out or "Here's one: _Haha, you made my day. Free this weekend?_ 😊") + "\n\nTap and hold to copy the one you like.")


# ---------------------------------------------------------------- personalise
def personalise(user, text, db) -> dict | None:
    low = text.lower().strip()
    m = re.match(r"^(?:call yourself|rename (?:mindy|yourself)(?: to)?|your name is|i'?ll call you|call you)\s+([a-z][a-z0-9 ]{1,18})$", low)
    if m:
        name = m.group(1).strip().title()
        db.x("UPDATE users SET mindy_name=? WHERE id=?", (name, user["id"]))
        return R(f"💚 {name} it is. I love it. (Say _call yourself Mindy_ to switch back.)")
    m = re.match(r"^(?:be|personality|mode|mood)\s+(sweet|cheeky|calm)$", low)
    if m:
        db.x("UPDATE users SET persona=? WHERE id=?", (m.group(1), user["id"]))
        return R({"sweet": "🥰 Sweet mode on.", "cheeky": "😏 Oh, you asked for it. Cheeky mode on.", "calm": "🌿 Calm mode. Short and gentle."}[m.group(1)])
    m = re.match(r"^(?:your|mindy'?s?) colou?r(?: is)?\s+([a-z]+)$", low)
    if m and m.group(1) in HUES:
        db.x("UPDATE users SET mindy_hue=? WHERE id=?", (HUES[m.group(1)], user["id"]))
        return R(f"🎨 Done: I'm {m.group(1)} now. Looks good on me, right?", app=("See me", "now"))
    m = re.match(r"^(?:language|reply in|speak|talk in|bhasha)\s+(.+)$", low)
    if m:
        code = LANGS.get(m.group(1).strip())
        if not code:
            return R("I can speak most languages. Try _language Hindi_, _language Spanish_, _language Arabic_, _language Swahili_…")
        db.x("UPDATE users SET lang=? WHERE id=?", (code, user["id"]))
        return R(f"🌍 Done. I'll reply in {m.group(1).strip().title()} from now on." + ("" if llm.live() else " (Translation switches on once my AI is connected.)"))
    if low in ("voice replies on", "reply in voice", "voice on", "talk to me"):
        db.x("UPDATE users SET voice=1 WHERE id=?", (user["id"],))
        return R("🔊 When you send a voice note, I'll answer with one too.")
    if low in ("voice replies off", "voice off", "text only"):
        db.x("UPDATE users SET voice=0 WHERE id=?", (user["id"],))
        return R("🔇 Text only from now on.")
    if low in ("brain score", "my score", "score", "my brain"):
        s = brain_score(db, user)
        best = sorted(s["parts"].items(), key=lambda kv: kv[1])[0][0]
        return R(f"🧠 *Brain score {s['score']}* · {s['level']}\nBiggest boost available: *{best}*.", app=("See your brain", "brain"))
    if low in ("what do you know about me", "what do you know", "my profile", "my data"):
        f = mind.facts(db, user["id"])
        lines = "\n".join(f"• {k.replace('_', ' ')}: {v}" for k, v in list(f.items())[:20]) or "Nothing yet. Let's fix that."
        return R(f"🗂️ *What I know about you*\n{lines}\n\nEdit or delete anything in the app.", app=("Open your mind", "brain"))
    return None


# ---------------------------------------------------------------- habits ("done")
def habits(user, text, db) -> dict | None:
    low = text.lower().strip()
    if low in ("done", "did it", "habit done", "✅"):
        h = mind.habit_done(db, user["id"], user.get("tz") or "UTC")
        if h:
            s = h["streak"]
            cheer = {1: "Day one. Every streak starts here.", 3: "3 days! You're building something.", 7: "A whole week!! 🔥", 30: "30 DAYS. Legend. 👑"}
            return R(f"✅ *{h['title']}*: {s}-day streak. {cheer.get(s, '🔥 Keep going.')}")
    m = re.match(r"^(?:new )?habit:?\s+(.{3,40})$", low)
    if m:
        db.x("INSERT INTO habits(user_id,title,created_at) VALUES(?,?,?)", (user["id"], m.group(1).strip().capitalize(), now_iso()))
        return R(f"✅ New habit: *{m.group(1).strip().capitalize()}*. Reply *done* when you've done it today.")
    return None


# ---------------------------------------------------------------- trips noticed in plain text
def trips(user, text, db) -> dict | None:
    t = mind.trip_from(text, user.get("tz") or "UTC")
    if not t or t["date"] < _today(user):
        return None
    r = mind.auto_trip(db, user, t["place"], t["date"], t["flight"])
    return R(r["reply"], buttons=[("trip:share", "Share with family"), ("trip:ok", "Looks good")], app=("Open your trip list", "mind"))


# ---------------------------------------------------------------- the dispatcher
ORDER = [personalise, safety, habits, codeword, numbers, impersonation, human, screen_share, gifts, staff, business, vault,
         subscription, wardrobe, little, loan_alert, trips]


def handle(db: DB, user: dict, text: str, key: str | None = None) -> dict | None:
    if not text or not text.strip():
        return None
    try:
        r = draft_reply(user, text, db)
        if r:
            return r
    except Exception:
        log.exception("draft_reply failed")
    low = text.lower().strip()
    if re.match(r"^(schemes?|yojana|sarkari yojana|benefits|government help|govt help|am i eligible)\b", low):
        return _safe(schemes, user, text, db)
    if key and re.search(r"\b(calendar|e-?mail|gmail|outlook|inbox)\b", low):
        r = _safe(connect, user, text, db, key)
        if r:
            return r
    for fn in ORDER:
        r = _safe(fn, user, text, db)
        if r:
            return r
    return None


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        log.exception("skill %s failed", fn.__name__)
        return None


def on_button(db: DB, user: dict, bid: str) -> dict | None:
    if bid.startswith("q:"):
        _, k, v = bid.split(":", 2)
        res = mind.answer(db, user, k, v)
        return _with_next(db, user, res)
    if bid.startswith("verify:"):
        _, ans, rid = bid.split(":", 2)
        r = db.one("SELECT * FROM verify_req WHERE id=? AND target=?", (int(rid), user["id"]))
        if not r:
            return R("👍")
        db.x("UPDATE verify_req SET answer=? WHERE id=?", (ans, r["id"]))
        me = user.get("name") or "They"
        body = (f"✅ {me} confirmed: it's really them." if ans == "yes"
                else f"🚨 *{me} says it is NOT them.* Hang up / stop replying. Don't send money. Report it: forward the message to me and say *report*.")
        return R("Thank you. I've told them." if ans == "yes" else "Thank you. I've warned them it's a scam. 🛡️", notify=[(r["asker"], body, [])])
    if bid == "okday":
        db.x("INSERT INTO safety(user_id,kind,due_at,created_at,cleared_at) VALUES(?,?,?,?,?)", (user["id"], "ok", now_iso(), now_iso(), now_iso()))
        return R("💚 Thank you! Your family can see you're OK today.")
    if bid == "safe":
        db.x("UPDATE safety SET cleared_at=? WHERE user_id=? AND kind='check' AND cleared_at IS NULL", (now_iso(), user["id"]))
        return R("💚 Glad you're safe.")
    if bid == "sms:schemes":
        return R("Tell me your work and age, like: schemes farmer 45, or schemes street vendor.")
    if bid == "sms:remind":
        return R("Tell me what and when, like: remind me medicine 9am every day.")
    if bid == "sms:scam":
        return R("Send me the message or number you got, and I'll check it.")
    if bid == "trip:share":
        fam = care.family_of(db, user["id"])
        f = mind.facts(db, user["id"]).get("next_trip", "")
        return R(f"✈️ Shared with {len(fam)} family." if fam else "Link family in the app first, then I can share trips with them.",
                 notify=[(x["id"], f"✈️ {user.get('name') or 'Your family'} shared a trip: {f}", []) for x in fam])
    if bid == "trip:ok":
        return R("🧳 Have a brilliant trip!")
    if bid.startswith("name:"):
        name = bid[5:]
        if name != "keep":
            db.x("UPDATE users SET mindy_name=? WHERE id=?", (name, user["id"]))
            return R(f"🥹 {name}. I'll wear it with pride.")
        return R("Mindy it stays! 💚")
    return None


def _with_next(db, user, res) -> dict:
    out = R(res["reply"])
    q = res.get("next")
    if q:
        mind.mark_asked(db, user["id"], q["key"])
        out["text"] += "\n\n" + q["q"]
        out["buttons"] = mind.buttons_for(q)
        if q.get("free"):
            _kv_set(db, f"await_q:{user['id']}", q["key"])
    if res.get("again"):
        _kv_set(db, f"await_q:{user['id']}", q["key"])
    return out


def free_answer(db: DB, user: dict, text: str) -> dict | None:
    """A typed answer to Mindy's last typed-answer question."""
    k = _kv_get(db, f"await_q:{user['id']}")
    if not k:
        return None
    _kv_set(db, f"await_q:{user['id']}", None)
    if text.lower().strip() in ("skip", "later", "no", "not now", "don't know", "dont know"):
        mind.set_fact(db, user["id"], k, "skipped")
        return R("No problem. 👍")
    res = mind.answer(db, user, k, text)
    if k == "pet":
        name = text.strip().split()[0].title()[:16]
        out = _with_next(db, user, res)
        out["buttons"] = [(f"name:{name}", f"Call me {name}!"), ("name:keep", "Keep Mindy")]
        out["text"] = f"🥹 {name}… that's such a good name. Can I have it? Say yes and I'll be *{name}* from now on."
        return out
    return _with_next(db, user, res)


def tail_question(db: DB, user: dict) -> tuple[str, list] | None:
    """One question at the end of a conversation the person started (free on WhatsApp). At most one per ~20 hours."""
    if mind.asked_today(db, user["id"]):
        return None
    q = mind.next_question(db, user["id"])
    if not q:
        return None
    mind.mark_asked(db, user["id"], q["key"])
    if q.get("free"):
        _kv_set(db, f"await_q:{user['id']}", q["key"])
    return ("💭 Quick one: " + q["q"], mind.buttons_for(q))


# ---------------------------------------------------------------- the SMS channel (missed-call / SMS gateway phone)
class SmsClient:
    """Mindy over plain SMS for basic phones, through a spare Android phone running the helper app in gateway mode.
    Outgoing texts are queued; the gateway phone collects and sends them. Buttons become numbered choices."""

    def __init__(self, db: DB | None = None):
        self.db = db

    async def text(self, to, body, reply_to=None, preview_url=True):
        plain = re.sub(r"[*_~]", "", body)
        for i in range(0, min(len(plain), 640), 320):
            self.db.x("INSERT INTO sms_out(to_number,body,created_at) VALUES(?,?,?)", (to, plain[i:i + 320], now_iso()))
        return {"ok": True}

    async def buttons(self, to, body, buttons, header=None):
        self.db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"sms_menu:{to}", "|".join(b[0] for b in buttons)))
        return await self.text(to, body + "\n" + "\n".join(f"{i}. {b[1]}" for i, b in enumerate(buttons, 1)))

    async def link_button(self, to, body, label, url):
        return await self.text(to, f"{body}\n{label}: {url}")

    async def list_menu(self, to, body, button, rows, section="Options"):
        return await self.buttons(to, body, [(r[0], r[1]) for r in rows])

    async def location(self, to, lat, lng, name="", address=""):
        return await self.text(to, f"{name} https://maps.google.com/?q={lat},{lng}")

    async def image(self, to, link, caption=""):
        return await self.text(to, f"{caption} {link}")

    async def document(self, to, link, filename, caption=""):
        return await self.text(to, f"{caption} {link}")

    async def audio(self, to, link):
        return {"ok": False}

    async def react(self, *a, **k):
        return {}

    async def read_and_typing(self, *a, **k):
        return {}

    async def template(self, to, name, params, lang=None):
        return await self.text(to, " ".join(params))

    async def download_media(self, *a):
        return None, None


SMS_WELCOME = ("Mindy here. Free help on your phone. Reply with a number:\n1. Government schemes for me\n2. Set a reminder\n3. Check a scam message\n"
               "Or just type your question. Hindi or English is fine.")
