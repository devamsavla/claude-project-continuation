"""Money and life admin: bank statements -> spend by category, tax-season help, life-moment checklists, and the tap menu.

Statements are processed and thrown away: only dated, categorised amounts are kept, never account numbers or the file."""
import csv
import io
import re
from datetime import date, datetime

from . import countries, llm, mind
from .db import DB, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS spend(id INTEGER PRIMARY KEY, user_id INTEGER, day TEXT, amount REAL, category TEXT, merchant TEXT, created_at TEXT,
  UNIQUE(user_id, day, amount, merchant));
"""

CATS = [
    ("Subscriptions", r"netflix|spotify|prime video|hotstar|disney|youtube|apple\.com|icloud|google ?one|chatgpt|openai|anthropic|canva|adobe|audible|zee5|sonyliv"),
    ("Food delivery", r"swiggy|zomato|deliveroo|uber ?eats|just ?eat|doordash|grubhub|talabat|foodpanda|ifood|rappi|grabfood|glovo"),
    ("Groceries", r"blinkit|zepto|instamart|bigbasket|dmart|tesco|sainsbury|asda|aldi|lidl|waitrose|walmart|kroger|carrefour|lulu|grocery|kirana|supermarket|whole foods|ocado"),
    ("Shopping", r"amazon|flipkart|myntra|ajio|meesho|nykaa|ebay|etsy|shein|zara|h&m|primark|ikea|argos|target|noon|shopee|lazada|mercado ?libre"),
    ("Transport", r"\buber\b|\bola\b|rapido|lyft|\bbolt\b|careem|\bgrab\b|\btfl\b|metro|irctc|railway|trainline|petrol|fuel|shell|bp |indian oil|hpcl|bpcl|parking|fastag"),
    ("Travel", r"makemytrip|goibibo|booking\.com|airbnb|expedia|indigo|air india|vistara|emirates|ryanair|easyjet|british airways|hotel|agoda|cleartrip"),
    ("Bills", r"electricity|bescom|tata power|adani|mseb|water|gas bill|broadband|jio|airtel|vodafone|\bvi\b|ee |o2 |three|bt |virgin media|council tax|tv licen|insurance|premium"),
    ("Rent and EMI", r"\brent\b|landlord|emi\b|loan|mortgage|nach|ecs"),
    ("Health", r"pharmacy|apollo|1mg|pharmeasy|netmeds|boots|cvs|walgreens|hospital|clinic|doctor|dental|lab"),
    ("Eating out", r"restaurant|cafe|café|starbucks|costa|pret|mcdonald|kfc|domino|pizza|burger|chaayos|barista|dhaba|bar |pub "),
    ("Cash", r"\batm\b|cash withdrawal|cash wdl|nwd"),
    ("Transfers", r"upi/|imps|neft|rtgs|transfer|sent to|paid to|zelle|venmo|revolut|wise|paypal|faster payment"),
]


def init(db: DB):
    with db.lock:
        db.conn.executescript(SCHEMA)
        db.conn.commit()


def category(desc: str) -> str:
    d = desc.lower()
    for name, rx in CATS:
        if re.search(rx, d):
            return name
    return "Other"


AMT = r"-?\(?[\d,]+\.\d{2}\)?"
DATE_RX = re.compile(r"\b(\d{1,2}[/\-.](?:\d{1,2}|[A-Za-z]{3})[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2} [A-Za-z]{3} \d{2,4})\b")


def _date(s: str) -> date | None:
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d", "%d %b %Y", "%d %b %y", "%d-%b-%Y", "%d-%b-%y", "%d/%b/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _num(s: str) -> float | None:
    s = (s or "").strip().replace(",", "")
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("-()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def parse_statement(data: bytes, mime: str = "", name: str = "") -> list[dict]:
    """Returns [{day, amount (positive = money out), merchant}] from a CSV or text PDF statement. Credits are skipped."""
    is_pdf = data[:4] == b"%PDF" or "pdf" in (mime or "") or name.lower().endswith(".pdf")
    if is_pdf:
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages[:40])
        except Exception:
            return []
        return _from_lines(text.splitlines())
    text = data.decode("utf-8-sig", "ignore")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    head_i = next((i for i, r in enumerate(rows[:15]) if any(re.search(r"date", c, re.I) for c in r)), None)
    if head_i is None:
        return _from_lines(text.splitlines())
    head = [c.strip().lower() for c in rows[head_i]]
    col = lambda *names: next((i for i, h in enumerate(head) if any(n in h for n in names)), None)
    di, de = col("date"), col("description", "narration", "details", "particulars", "merchant", "payee", "reference", "name")
    dr, cr, am = col("debit", "withdrawal", "paid out", "money out", "dr"), col("credit", "deposit", "paid in", "money in", "cr"), col("amount", "value")
    out = []
    for r in rows[head_i + 1:]:
        if di is None or len(r) <= di:
            continue
        d = _date(r[di])
        if not d:
            continue
        desc = r[de] if de is not None and de < len(r) else " ".join(r)
        amt = None
        if dr is not None and dr < len(r) and _num(r[dr]):
            amt = abs(_num(r[dr]))
        elif am is not None and am < len(r) and _num(r[am]) is not None:
            v = _num(r[am])
            amt = -v if v < 0 else None  # signed amount column: negatives are money out
        if amt:
            out.append({"day": d.isoformat(), "amount": round(amt, 2), "merchant": _clean(desc)})
    return out


def _from_lines(lines: list[str]) -> list[dict]:
    out = []
    for ln in lines:
        m = DATE_RX.search(ln)
        nums = re.findall(AMT, ln)
        if not m or not nums:
            continue
        d = _date(m.group(1))
        if not d:
            continue
        low = ln.lower()
        if re.search(r"\b(cr|credit|deposit|salary|refund|interest)\b", low) and not re.search(r"\b(dr|debit)\b", low):
            continue
        amt = _num(nums[0]) if len(nums) < 2 else _num(nums[-2])  # usually "... amount balance"
        if amt:
            desc = ln[m.end():].split(nums[0])[0]
            out.append({"day": d.isoformat(), "amount": round(abs(amt), 2), "merchant": _clean(desc)})
    return out


def _clean(desc: str) -> str:
    d = re.sub(r"\b\d{6,}\b", "", desc)  # drop account / reference numbers
    d = re.sub(r"[^\w&@./ -]", " ", d)
    return re.sub(r"\s{2,}", " ", d).strip()[:60]


def save_spend(db: DB, uid: int, txns: list[dict]) -> int:
    n = 0
    for t in txns:
        try:
            db.x("INSERT INTO spend(user_id,day,amount,category,merchant,created_at) VALUES(?,?,?,?,?,?)",
                 (uid, t["day"], t["amount"], category(t["merchant"]), t["merchant"], now_iso()))
            n += 1
        except Exception:
            pass  # duplicate line from an overlapping statement
    return n


def summary(db: DB, user: dict, month: str | None = None) -> dict:
    uid = user["id"]
    last = db.one("SELECT MAX(substr(day,1,7)) m FROM spend WHERE user_id=?", (uid,))["m"]
    month = month or last
    if not month:
        return {"month": None, "total": 0, "cats": []}
    y, mo = int(month[:4]), int(month[5:7])
    prev = f"{y - (mo == 1)}-{12 if mo == 1 else mo - 1:02d}"
    cats = db.q("SELECT category, ROUND(SUM(amount)) total, COUNT(*) n FROM spend WHERE user_id=? AND substr(day,1,7)=? GROUP BY category ORDER BY total DESC", (uid, month))
    before = {r["category"]: r["total"] for r in db.q("SELECT category, ROUND(SUM(amount)) total FROM spend WHERE user_id=? AND substr(day,1,7)=? GROUP BY category", (uid, prev))}
    for c in cats:
        b = before.get(c["category"])
        c["change"] = round((c["total"] - b) / b * 100) if b else None
    top = db.q("SELECT merchant, ROUND(SUM(amount)) total, COUNT(*) n FROM spend WHERE user_id=? AND substr(day,1,7)=? GROUP BY merchant ORDER BY total DESC LIMIT 5", (uid, month))
    return {"month": month, "total": sum(c["total"] for c in cats), "cats": cats, "top": top}


def summary_text(db: DB, user: dict) -> str:
    s = summary(db, user)
    if not s["month"]:
        return "💸 No spending yet. Forward me a bank statement (PDF or CSV) and I'll sort it. The file is deleted after reading."
    p = countries.for_user(db, user)
    lines = []
    for c in s["cats"][:7]:
        ch = f" ({'+' if c['change'] > 0 else ''}{c['change']}%)" if c.get("change") is not None and abs(c["change"]) >= 10 else ""
        lines.append(f"• {c['category']}: {countries.money(p, c['total'])}{ch}")
    worst = next((c for c in s["cats"] if c.get("change") and c["change"] >= 25 and c["category"] not in ("Rent and EMI", "Transfers")), None)
    tip = f"\n\n👀 {worst['category']} is up {worst['change']}% on last month." if worst else ""
    return f"💸 *{datetime.strptime(s['month'], '%Y-%m'):%B %Y}*: {countries.money(p, s['total'])} out\n" + "\n".join(lines) + tip


# ---------------------------------------------------------------- tax season
def tax_help(db: DB, user: dict, text: str) -> str:
    p = countries.for_user(db, user)
    code = p.get("code") or ""
    low = text.lower()
    m = re.search(r"(?:income|salary|ctc|earn\w*)\D{0,12}([\d,.]+)\s*(l|lakh|lakhs|lac|k|cr|crore)?", low)
    if code in ("IN", "") and m:
        inc = float(m.group(1).replace(",", "")) * {"l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "k": 1e3, "cr": 1e7, "crore": 1e7}.get(m.group(2) or "", 1)
        tax = india_new_regime(inc, salaried=not re.search(r"business|freelanc|self.?employ", low))
        return (f"🧾 *Estimate, new regime (FY 2025-26)*\nIncome {countries.money(p, inc)} → tax about *{countries.money(p, tax)}* incl. 4% cess."
                "\n\n_A rough guide only: deductions, capital gains and the old regime can change it. Check on incometax.gov.in or with a CA._")
    if code in ("IN", ""):
        return ("🧾 *ITR checklist*\n☐ Form 16 from your employer\n☐ AIS and Form 26AS (download from incometax.gov.in)\n☐ Bank interest certificates\n"
                "☐ Rent receipts / home-loan certificate (old regime only)\n☐ Capital gains statement if you sold shares or funds\n☐ Pick old vs new regime\n\n"
                "Filing is on incometax.gov.in with *your own* login. Stuck on a screen? Send me a screenshot and I'll circle where to tap.\n"
                "Tell me _my income is 14 lakh_ for an estimate.")
    if code == "GB":
        return ("🧾 *Self Assessment*\n☐ Do you need to file? (self-employed income, rental income, untaxed income over the limits)\n☐ UTR number and Government Gateway login\n"
                "☐ P60 / P45, interest, dividends, rental and trading records\n☐ Online deadline: *31 January*. Payment also due then.\nFile at gov.uk/self-assessment-tax-returns")
    if code == "US":
        return ("🧾 *Tax season*\n☐ W-2s / 1099s\n☐ 1098 (mortgage interest), 1098-T/E (education)\n☐ Last year's return\n☐ Deadline usually *15 April*\n"
                "Free options: IRS Free File at irs.gov/freefile")
    return f"🧾 Check your country's official tax site. Tell me your deadline and I'll remind you a month and a week before."


def india_new_regime(income: float, salaried: bool = True) -> int:
    """FY 2025-26 new regime: standard deduction 75,000 (salaried), slabs 4/8/12/16/20/24 lakh, rebate up to 12 lakh taxable, 4% cess.
    Ignores surcharge (incomes above 50 lakh) and marginal relief."""
    t = max(0.0, income - (75000 if salaried else 0))
    slabs = [(4e5, 0), (8e5, .05), (12e5, .10), (16e5, .15), (20e5, .20), (24e5, .25), (float("inf"), .30)]
    tax, low = 0.0, 0.0
    for top, rate in slabs:
        if t > low:
            tax += (min(t, top) - low) * rate
        low = top
    if t <= 12e5:
        tax = 0
    return round(tax * 1.04)


# ---------------------------------------------------------------- life-moment checklists
CHECKLISTS = {
    "lost phone": ["Call your mobile operator: block the SIM and ask for a replacement", "Lock or erase it: Find My (iPhone) / Find My Device (Android)",
                   "Block UPI / mobile banking: call your bank's helpline", "Change your email and WhatsApp-linked passwords",
                   "Report it to the police (needed for insurance) — in India also block the IMEI at sancharsaathi.gov.in",
                   "Tell family the phone is lost so they ignore money requests from it"],
    "moving house": ["Give notice / set the move date", "Book movers or a van", "Change address: bank, employer, insurance, voter/ID, doctor",
                     "Set up electricity, internet and gas at the new place", "Redirect post", "Meter readings on move day", "Keys handed over + deposit receipt"],
    "new job": ["Offer letter and joining documents", "Bank details and tax forms to HR", "Transfer your pension / PF", "Update LinkedIn", "Health insurance details",
                "Calendar: probation end date", "Thank-you note to your old manager"],
    "new baby": ["Birth certificate", "Add baby to health insurance", "Vaccination schedule reminders", "Passport/ID application if travelling",
                 "Savings account for the baby", "Tell work: parental leave dates"],
    "wedding": ["Budget and guest list", "Venue and date", "Invites out 6 weeks before", "Outfits and fittings", "Gift registry / wishlist",
                "Marriage registration documents", "Thank-you messages after"],
    "travel abroad": ["Passport valid 6+ months after return", "Visa if needed", "Travel insurance", "Tell your bank / get a travel card",
                      "Local SIM or roaming plan", "Copies of documents in Mindy", "Plug adapter"],
    "first car": ["Insurance in your name", "Registration and road tax", "Pollution / MOT / inspection date", "Save the service schedule",
                  "Parking spot saved in Mindy", "Emergency number of your insurer"],
    "new phone for parents": ["Bigger font and display size", "WhatsApp backup restored", "Add family as favourites", "Install Mindy and turn on simple mode",
                              "Set up screen lock they can remember", "Turn off unknown app installs", "Teach: 'forward any odd message to Mindy'"],
    "exam": ["Admit card downloaded", "Exam centre route saved", "Syllabus photo sent to Mindy for a revision plan", "ID proof ready", "Night-before checklist alarm"],
    "starting a business": ["Business name and registration", "Bank account for the business", "Tax registration if needed (GST / VAT)",
                            "Price list", "Customer reminders on Mindy", "Book-keeping: khata or spreadsheet"],
}
ALIASES = {"phone lost": "lost phone", "stolen phone": "lost phone", "mobile lost": "lost phone", "phone chori": "lost phone", "moving": "moving house",
           "shifting": "moving house", "relocating": "moving house", "job": "new job", "baby": "new baby", "marriage": "wedding", "shaadi": "wedding",
           "trip abroad": "travel abroad", "international trip": "travel abroad", "car": "first car", "parents phone": "new phone for parents",
           "mum's phone": "new phone for parents", "business": "starting a business"}


def checklist(db: DB, user: dict, text: str) -> dict | None:
    low = text.lower().strip()
    if re.search(r"\b(lost|stolen|chori|missing)\b.{0,15}\b(phone|mobile|iphone)\b|\b(phone|mobile|iphone)\b.{0,15}\b(lost|stolen|chori ho gaya|missing)\b", low) and len(low) < 60:
        low = "checklist lost phone"
    m = re.match(r"^(?:checklist|check list|list for|i'?m|we'?re|i am|we are|i have|i've|my)\s*(?:for\s+)?(?:a\s+|an\s+|my\s+)?(.+?)[.!]?$", low)
    if not m:
        return None
    what = m.group(1).strip()
    what = re.sub(r"^(lost my phone|lost phone|my phone (?:is )?(?:lost|stolen)|phone (?:got )?stolen)$", "lost phone", what)
    key = what if what in CHECKLISTS else ALIASES.get(what) or next((k for k in CHECKLISTS if k in what), None) or next((v for a, v in ALIASES.items() if a in what), None)
    if not key or (not low.startswith(("checklist", "check list", "list for")) and key != "lost phone"):
        return None
    name, _ = db.list_add(user["id"], f"Checklist: {key.title()}", CHECKLISTS[key])
    urgent = "🚨 Do these now, in order:\n" if key == "lost phone" else ""
    return {"text": f"✅ *{key.title()}*\n{urgent}" + "\n".join(f"☐ {x}" for x in CHECKLISTS[key]) + "\n\nSaved as a list. Tick things off in the app.",
            "app": ("Open the checklist", "mind")}


# ---------------------------------------------------------------- the tap menu: WhatsApp as a portal to your brain
MENU = [("menu:brain", "🧠 My brain", "Score, what I know, next question"), ("menu:family", "🌳 Family", "Tree, birthdays, care"),
        ("menu:money", "💸 Money", "Spend, khata, subscriptions"), ("menu:docs", "🗂️ Documents", "Expiry dates, vault"),
        ("menu:lists", "✅ Checklists", "Lost phone, moving, travel…"), ("menu:safety", "🛡️ Safety", "Scams, check on me, code word"),
        ("menu:style", "👗 Style", "Wardrobe, what to wear, try-on"), ("menu:plans", "📅 Today", "Reminders and plans"),
        ("menu:help", "🙋 A real person", "Talk to the Mindy team")]
