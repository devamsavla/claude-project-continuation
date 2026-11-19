"""Mindy, the tech friend: small, specific skills that do real things. Each one is a defined task (not open-ended chat),
so they are allowed on WhatsApp as well as Telegram and the app.

- do_it: "book an uber to Phoenix Mall" -> one link that opens Uber with the drop already filled in. Also Google Maps
  directions, calls, WhatsApp chats and UPI payments (through /go, because chat apps only make http links tappable).
- scam_check: patterns + community reports -> a verdict and what to do. Reports build our own spam database.
- screen_help: a screenshot + a question -> the same screenshot with a circle where to tap, and the step in simple words.
- file tools: compress a video, turn a video or voice note into an MP3, shrink a photo (ffmpeg / Pillow)."""
import hashlib
import io
import json
import os
import re
import secrets
import subprocess
import tempfile
from urllib.parse import quote, urlencode

from . import llm
from .config import settings
from .db import DB, now_iso

MEDIA_DIR = os.environ.get("MEDIA_DIR") or os.path.join(os.path.dirname(os.path.abspath(settings.database_path)) or ".", "media")


# ---------------------------------------------------------------- do it for me
def go_link(target: str) -> str:
    """A tappable https link that opens an app link (upi:, tel:) through our /go page."""
    return f"{settings.app_url.rstrip('/')}/go?" + urlencode({"to": target})


def do_it(text: str) -> dict | None:
    """Returns {reply, links:[(label, url)]} for things Mindy can open for you, or None."""
    t = text.strip()
    low = t.lower()
    m = re.search(r"\b(?:book|get|call|order|need)\b.*?\b(uber|cab|taxi|ola|rapido|auto|ride)\b.*?\b(?:to|for|till)\b\s+(.+)", low)
    if m:
        dest = t[m.start(2):].strip(" .?!")
        uber = "https://m.uber.com/ul/?" + urlencode({"action": "setPickup", "pickup": "my_location", "dropoff[formatted_address]": dest})
        maps = "https://www.google.com/maps/dir/?" + urlencode({"api": 1, "destination": dest, "travelmode": "driving"})
        return {"reply": f"🚕 Tap *Open Uber*: your pickup is where you are and the drop is *{dest}*. Check the price, then tap *Confirm*.\n"
                         "Want to see the route first? Tap *Directions*.",
                "links": [("Open Uber", uber), ("Directions", maps)]}
    m = re.search(r"\b(?:directions|route|navigate|way|take me|how (?:do i|to) (?:get|go|reach))\b.*?\bto\b\s+(.+)", low)
    if m:
        dest = t[m.start(1):].strip(" .?!")
        mode = "walking" if "walk" in low else "transit" if re.search(r"\b(train|metro|bus|tube)\b", low) else "driving"
        return {"reply": f"🗺️ Here's the way to *{dest}* ({mode}). Tap and press *Start*.",
                "links": [("Directions", "https://www.google.com/maps/dir/?" + urlencode({"api": 1, "destination": dest, "travelmode": mode}))]}
    m = re.search(r"\bpay\b.*?(?:₹|rs\.?|inr)?\s?(\d[\d,]*)\b.*?\b(?:to|on)\b\s+([\w.\-]{2,}@[a-z]{2,})", low)
    if m:
        amt, vpa = m.group(1).replace(",", ""), m.group(2)
        upi = "upi://pay?" + urlencode({"pa": vpa, "am": amt, "cu": "INR", "tn": "via Mindy"})
        return {"reply": f"💸 Tap to pay *₹{int(amt):,}* to *{vpa}* in your UPI app. Check the name it shows before you enter your PIN.",
                "links": [("Pay with UPI", go_link(upi))]}
    m = re.search(r"\b(?:call|ring|phone)\b\s+(\+?\d[\d\s\-]{7,})", low)
    if m:
        num = re.sub(r"[^\d+]", "", m.group(1))
        return {"reply": f"📞 Tap to call {num}.", "links": [("Call", go_link("tel:" + num))]}
    m = re.search(r"\b(?:whatsapp|message|text)\b\s+(\+?\d[\d\s\-]{7,})(?:\s+(.+))?", low)
    if m:
        num = re.sub(r"\D", "", m.group(1))
        return {"reply": "💬 Tap to open the chat.", "links": [("Open chat", f"https://wa.me/{num}" + (f"?text={quote(m.group(2))}" if m.group(2) else ""))]}
    return None


SAFE_SCHEMES = ("upi:", "tel:", "uber:", "geo:", "sms:", "mailto:", "intent:")


def safe_target(target: str) -> bool:
    return target.startswith(SAFE_SCHEMES)


# ---------------------------------------------------------------- scam shield
SCAM = [
    (r"\bkyc\b.*\b(update|expire|block|suspend)", 3, "asks you to update KYC urgently"),
    (r"\b(account|card|sim|number)\b.*\b(block|suspend|deactivat|clos)", 3, "threatens to block your account or SIM"),
    (r"\botp\b|one.?time password|verification code", 2, "mentions an OTP (never share it)"),
    (r"\b(lottery|lucky draw|you (have )?won|prize|reward points|cashback of)\b", 3, "promises a prize or lottery"),
    (r"\b(digital arrest|cbi|ed officer|police case|narcotics|customs)\b", 4, "pretends to be police or officials (\"digital arrest\")"),
    (r"\b(parcel|courier|fedex|dhl)\b.*\b(held|seized|illegal|drugs)", 4, "says a parcel was seized"),
    (r"\b(electricity|power)\b.*\b(disconnect|cut)", 3, "threatens to cut your electricity tonight"),
    (r"\b(part.?time|work from home|like (videos|youtube)|daily earn|earn ₹?\d+ ?(per|a) day)\b", 3, "offers easy money for simple tasks"),
    (r"\b(double your|guaranteed returns?|crypto|forex|trading group|stock tips)\b", 3, "promises guaranteed or doubled returns"),
    (r"\b(refund|income tax refund)\b.*\b(click|link|claim)", 3, "offers a refund through a link"),
    (r"\.apk\b|anydesk|teamviewer|quicksupport|screen share", 4, "asks you to install an app or share your screen"),
    (r"bit\.ly|tinyurl|cutt\.ly|rb\.gy|t\.co/|is\.gd", 1, "uses a hidden short link"),
    (r"\b(urgent|immediately|within 24 hours|today only|last chance)\b", 1, "rushes you"),
    (r"\b(gift card|google play card|amazon voucher)\b", 3, "asks for gift cards"),
    (r"\b(hi (mum|mom|dad)|new number|lost my phone)\b", 3, "claims to be family on a new number"),
    (r"\b(processing|registration|release|clearance|redelivery|customs|small|handling) fee\b|\bpay (a )?(small|£|\$|€|₹|rs)", 2, "asks for a small fee first"),
    (r"\b(could not be delivered|delivery (failed|attempt)|missed (a )?delivery|redeliver)", 2, "fake missed-delivery message"),
    (r"\b(send|transfer)\b.{0,30}\b(money|£|\$|€|₹|rs\.?|\d{3,})\b.{0,40}\b(urgent|now|today|asap|quick)", 1, "asks for money urgently"),
]
BARE_DOMAIN = re.compile(r"(?<![@\w/.])((?:[a-z0-9](?:[a-z0-9-]{0,40}[a-z0-9])?\.)+(?:com|in|co|uk|info|xyz|top|link|online|site|net|org|shop|live|app|io|me|club|vip|icu|buzz|cc|ws|tk|ml|ga|cf|gq|support|help|services)(?:\.(?:uk|in))?)(?:/\S*)?\b", re.I)


def _nums(text: str) -> list[str]:
    return list({re.sub(r"\D", "", n)[-10:] for n in re.findall(r"\+?\d[\d\s\-]{8,}\d", text)})


def scam_check(db: DB, text: str, who: str | None = None) -> dict:
    low = text.lower()
    score, reasons = 0, []
    for pat, w, why in SCAM:
        if re.search(pat, low):
            score += w
            reasons.append(why)
    nums = _nums(text)
    reports = 0
    for n in nums:
        reports += db.one("SELECT COUNT(*) n FROM scam_reports WHERE number=?", (n,))["n"]
    h = hashlib.sha256(re.sub(r"\s+", " ", low).encode()).hexdigest()[:24]
    reports += db.one("SELECT COUNT(*) n FROM scam_reports WHERE text_hash=?", (h,))["n"]
    if reports:
        score += 2 + reports
        reasons.insert(0, f"reported by {reports} Mindy user{'s' if reports > 1 else ''}")
    if 1 <= score <= 3 and llm.live():
        out = llm.chat_json("Is this message a scam? Fields: scam (true/false), why (one short line).\nMESSAGE: " + text[:1500], who=who, max_tokens=80)
        if out and out.get("scam"):
            score += 2
            reasons.append(str(out.get("why") or "looks like a known scam pattern")[:120])
    verdict = "scam" if score >= 4 else "careful" if score >= 2 else "ok"
    head = {"scam": "🚨 *This looks like a SCAM.*", "careful": "⚠️ *Be careful with this one.*", "ok": "✅ *I don't see scam signs.*"}[verdict]
    why = ("\nWhy: " + "; ".join(reasons[:4]) + ".") if reasons else ""
    advice = {"scam": "\nDon't click links, don't share OTPs or PINs, don't install apps. Block the number. If money is gone, call 1930 (India cyber helpline) at once.",
              "careful": "\nDon't share OTPs or PINs. If it says it's your bank, call the number on the back of your card instead.",
              "ok": "\nStill, never share an OTP or PIN with anyone, even if they say they're from your bank."}[verdict]
    return {"verdict": verdict, "score": score, "reasons": reasons, "numbers": nums, "reply": head + why + advice, "hash": h}


def report_scam(db: DB, uid: int, text: str) -> int:
    nums = _nums(text) or [None]
    h = hashlib.sha256(re.sub(r"\s+", " ", text.lower()).encode()).hexdigest()[:24]
    for n in nums:
        db.x("INSERT INTO scam_reports(number,text_hash,reporter,created_at) VALUES(?,?,?,?)", (n, h, uid, now_iso()))
    return len(nums)


def number_lookup(db: DB, number: str) -> dict:
    n = re.sub(r"\D", "", number)[-10:]
    reports = db.one("SELECT COUNT(*) n, MAX(created_at) last FROM scam_reports WHERE number=?", (n,))
    biz = db.one("SELECT name FROM verified_numbers WHERE number=?", (n,))
    return {"number": n, "reports": reports["n"], "last": reports["last"], "verified": biz["name"] if biz else None}


# ---------------------------------------------------------------- screenshot help
def screen_help(image: bytes, mime: str, question: str, who: str | None = None) -> dict | None:
    """Asks the cheap vision model where to tap. Returns {step, x, y, r} (0-1 coordinates) or None."""
    out = llm.chat_json(
        "This is a screenshot of a phone app. The person (maybe older, not techy) asks: " + (question or "what do I do next?") +
        "\nFields: step (one short, kind instruction for the next action only, simple words), target (the label of the button or box), "
        "x and y (centre of that thing as fractions 0-1 of the image width and height), r (radius as fraction of width, 0.05-0.2), "
        "done (true if the task already looks finished).", "You help people use their phones, one step at a time.",
        image=image, mime=mime, who=who, max_tokens=200)
    if not out or "step" not in out:
        return None
    try:
        out["x"], out["y"] = min(max(float(out.get("x", 0.5)), 0), 1), min(max(float(out.get("y", 0.5)), 0), 1)
        out["r"] = min(max(float(out.get("r", 0.08)), 0.04), 0.25)
    except (TypeError, ValueError):
        out.update(x=None, y=None)
    return out


def circle(image: bytes, x: float, y: float, r: float, label: str = "") -> bytes:
    from PIL import Image, ImageDraw
    im = Image.open(io.BytesIO(image)).convert("RGB")
    w, h = im.size
    d = ImageDraw.Draw(im, "RGBA")
    cx, cy, rad = x * w, y * h, max(r * w, 28)
    for i, a in ((10, 70), (0, 255)):
        d.ellipse([cx - rad - i, cy - rad - i, cx + rad + i, cy + rad + i], outline=(37, 211, 102, a), width=max(6, int(w / 90)))
    # an arrow from below pointing at the circle
    ay = min(h - 10, cy + rad * 2.6)
    d.line([cx, ay, cx, cy + rad + 8], fill=(255, 92, 92, 255), width=max(6, int(w / 110)))
    d.polygon([(cx, cy + rad + 4), (cx - w / 40, cy + rad + w / 22), (cx + w / 40, cy + rad + w / 22)], fill=(255, 92, 92, 255))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85)
    return out.getvalue()


def store_media(data: bytes, ext: str, keep: bool = False) -> str:
    """Keeps a file (a day, or for good with keep=True) and returns its public URL (chat apps need a link to send media)."""
    os.makedirs(MEDIA_DIR, exist_ok=True)
    name = ("keep-" if keep else "") + secrets.token_urlsafe(16) + "." + ext
    with open(os.path.join(MEDIA_DIR, name), "wb") as f:
        f.write(data)
    return f"{settings.app_url.rstrip('/')}/media/{name}"


def read_media(url: str) -> bytes | None:
    """Reads back a file stored with store_media (by its public URL)."""
    name = url.rsplit("/media/", 1)[-1]
    if not re.match(r"^[\w\-.]+$", name):
        return None
    try:
        with open(os.path.join(MEDIA_DIR, name), "rb") as f:
            return f.read()
    except OSError:
        return None


# ---------------------------------------------------------------- file tools
TOOL_WORDS = {"mp3": r"\b(mp3|audio only|extract audio|to audio|song)\b", "compress": r"\b(compress|smaller|reduce|shrink|size kam)\b"}


def wants_tool(caption: str) -> str | None:
    low = (caption or "").lower()
    for k, p in TOOL_WORDS.items():
        if re.search(p, low):
            return k
    return None


def convert(data: bytes, mime: str, tool: str) -> tuple[bytes, str, str] | None:
    """Returns (bytes, extension, mime) or None. Videos/audio through ffmpeg, photos through Pillow."""
    if mime.startswith("image/") and tool == "compress":
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((1600, 1600))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=72, optimize=True)
        return out.getvalue(), "jpg", "image/jpeg"
    if not (mime.startswith("video/") or mime.startswith("audio/")):
        return None
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "in")
        with open(src, "wb") as f:
            f.write(data)
        if tool == "mp3":
            dst, args, out_mime = os.path.join(d, "out.mp3"), ["-vn", "-acodec", "libmp3lame", "-q:a", "4"], "audio/mpeg"
        elif mime.startswith("video/"):
            dst, args, out_mime = os.path.join(d, "out.mp4"), ["-vf", "scale='min(854,iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
                                                               "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"], "video/mp4"
        else:
            dst, args, out_mime = os.path.join(d, "out.mp3"), ["-acodec", "libmp3lame", "-b:a", "64k"], "audio/mpeg"
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, *args, dst], check=True, timeout=240)
        except (subprocess.SubprocessError, FileNotFoundError):
            return None
        with open(dst, "rb") as f:
            return f.read(), dst.rsplit(".", 1)[1], out_mime


# ---------------------------------------------------------------- suspicious links
BRANDS = r"sbi|hdfc|icici|axis|kotak|paytm|phonepe|gpay|googlepay|amazon|flipkart|netflix|whatsapp|instagram|facebook|apple|microsoft|paypal|hmrc|royalmail|dhl|fedex|bluedart|indiapost|irctc|uidai|aadhaar|incometax|epfo|npci|bhim|airtel|jio|vodafone|bsnl|uber|ola|zomato|swiggy"
OFFICIAL = {"sbi": "onlinesbi.sbi", "hdfc": "hdfcbank.com", "icici": "icicibank.com", "amazon": "amazon.", "flipkart": "flipkart.com", "paytm": "paytm.com",
            "phonepe": "phonepe.com", "netflix": "netflix.com", "whatsapp": "whatsapp.com", "instagram": "instagram.com", "irctc": "irctc.co.in",
            "uidai": "uidai.gov.in", "incometax": "incometax.gov.in", "hmrc": "gov.uk", "royalmail": "royalmail.com", "apple": "apple.com", "paypal": "paypal.com"}
BAD_TLD = r"\.(xyz|top|click|link|buzz|rest|cam|work|live|shop|icu|cfd|sbs|monster|gq|tk|ml|cf|ga)(/|$)"


def link_check(db: DB, url: str) -> dict:
    """Risk signals for a link, without opening it."""
    from urllib.parse import urlparse
    u = urlparse(url if "://" in url else "http://" + url)
    host = (u.hostname or "").lower()
    reasons, score = [], 0
    if re.fullmatch(r"[\d.]+", host):
        score, _ = score + 3, reasons.append("it's a raw number address, not a real website name")
    if host.startswith("xn--") or ".xn--" in host:
        score, _ = score + 3, reasons.append("it uses look-alike letters")
    if re.search(BAD_TLD, host + "/"):
        score, _ = score + 2, reasons.append(f"the ending “.{host.rsplit('.', 1)[-1]}” is common in scams")
    if re.search(r"bit\.ly|tinyurl|cutt\.ly|rb\.gy|is\.gd|t\.ly|shorturl|tiny\.cc", host):
        score, _ = score + 1, reasons.append("it's a short link that hides where it goes")
    if u.path.lower().endswith(".apk"):
        score, _ = score + 4, reasons.append("it downloads an app (.apk) from outside the Play Store")
    m = re.search(BRANDS, host)
    if m:
        official = OFFICIAL.get(m.group(0))
        if not official or official not in host:
            if re.search(r"kyc|verify|update|secure|login|reward|refund|support|help|bonus|offer|gift", host + u.path.lower()) or host.count("-") >= 1:
                score, _ = score + 4, reasons.append(f"it uses the name “{m.group(0)}” but isn't their real website")
    if u.scheme == "http":
        score, _ = score + 1, reasons.append("it isn't secure (no https)")
    reports = db.one("SELECT COUNT(*) n FROM scam_reports WHERE text_hash=?", ("url:" + host,))["n"]
    if reports:
        score += 3 + reports
        reasons.insert(0, f"reported by {reports} Mindy user{'s' if reports > 1 else ''}")
    key = os.environ.get("SAFE_BROWSING_KEY")
    if key:
        try:
            import httpx
            r = httpx.post(f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={key}", timeout=8, json={
                "client": {"clientId": "whatsonyourmind", "clientVersion": "1"},
                "threatInfo": {"threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"], "platformTypes": ["ANY_PLATFORM"],
                               "threatEntryTypes": ["URL"], "threatEntries": [{"url": url}]}})
            if r.json().get("matches"):
                score, _ = score + 6, reasons.insert(0, "Google lists it as dangerous")
        except Exception:
            pass
    verdict = "scam" if score >= 4 else "careful" if score >= 2 else "ok"
    return {"url": url, "host": host, "verdict": verdict, "score": score, "reasons": reasons}


def check_message(db: DB, text: str, who: str | None = None, use_ai: bool = True) -> dict:
    """Scam check for a whole message: words, numbers, reports and every link in it."""
    res = scam_check(db, text, who if use_ai else None) if use_ai else _scam_patterns_only(db, text)
    urls = re.findall(r"(?:https?://|www\.)\S+", text)
    if not urls:  # "pay at royalmail-redelivery.info" has no http:// but is still a link
        urls = ["http://" + m.group(0) for m in BARE_DOMAIN.finditer(text) if not re.search(r"\d+\.\d+", m.group(1))][:3]
    for url in urls[:5]:
        lc = link_check(db, url)
        if lc["score"]:
            res["score"] += lc["score"]
            res["reasons"] = lc["reasons"] + res["reasons"]
    res["verdict"] = "scam" if res["score"] >= 4 else "careful" if res["score"] >= 2 else "ok"
    head = {"scam": "🚨 *This looks like a SCAM.*", "careful": "⚠️ *Be careful with this one.*", "ok": "✅ *I don't see scam signs.*"}[res["verdict"]]
    why = ("\nWhy: " + "; ".join(list(dict.fromkeys(res["reasons"]))[:4]) + ".") if res["reasons"] else ""
    advice = {"scam": "\nDon't open links, share OTPs or PINs, or install apps. Block the number. Lost money? Call 1930 (India) or your bank straight away. Reply *report* to warn others.",
              "careful": "\nDon't share OTPs or PINs. If it says it's your bank, call the number on the back of your card instead.",
              "ok": "\nStill, never share an OTP or PIN with anyone, even if they say they're from your bank."}[res["verdict"]]
    res["reply"] = head + why + advice
    return res


def _scam_patterns_only(db: DB, text: str) -> dict:
    low, score, reasons = text.lower(), 0, []
    for pat, w, why in SCAM:
        if re.search(pat, low):
            score += w
            reasons.append(why)
    return {"verdict": "ok", "score": score, "reasons": reasons, "numbers": _nums(text), "reply": "", "hash": ""}


def report_link(db: DB, uid: int, url: str):
    from urllib.parse import urlparse
    host = (urlparse(url if "://" in url else "http://" + url).hostname or "").lower()
    db.x("INSERT INTO scam_reports(number,text_hash,reporter,created_at) VALUES(?,?,?,?)", (None, "url:" + host, uid, now_iso()))


# ---------------------------------------------------------------- khata: who owes what, with UPI links
def parse_khata(text: str) -> dict | None:
    """'Ramesh owes me 500', 'I owe Priya 200', 'paid Sunil 300', 'got 200 from Ramesh', 'lent Arjun 1000'."""
    low = text.lower().strip()
    amt = r"(?:₹|rs\.?\s?|inr\s?)?(\d[\d,]*)(?:\s?(?:rs|rupees|/-))?"
    name = r"([a-z][a-z .']{0,30}?)"
    pats = [
        (rf"^{name} owes? me {amt}", +1), (rf"^i lent {name} {amt}", +1), (rf"^lent {name} {amt}", +1), (rf"^gave {name} {amt}", +1),
        (rf"^{name} (?:ko|को) {amt} (?:diye|udhaar)", +1), (rf"^{name} se {amt} (?:lene|lena)", +1),
        (rf"^{name} (?:took|borrowed|ne) {amt}(?: (?:udhaar|udhar|liye|uthaye))?\s*$", +1), (rf"^{name} ne {amt} (?:diye|lautaye|wapas kiye|de diye)", -2),
        (rf"^i owe {name} {amt}", -1), (rf"^owe {name} {amt}", -1), (rf"^borrowed {amt} from {name}\s*$", -1),
        (rf"^(?:got|received) {amt} from {name}\s*$", -2), (rf"^{name} paid (?:me )?(?:back )?{amt}", -2),
        (rf"^(?:i )?paid {name} (?:back )?{amt}", +2), (rf"^(?:i )?paid {amt} to {name}\s*$", +2),
    ]
    for p, sign in pats:
        m = re.match(p, low)
        if not m:
            continue
        g = m.groups()
        person, money = (g[1], g[0]) if g[0] and g[0].replace(",", "").isdigit() else (g[0], g[1])
        person = re.sub(r"\b(back|me)\b", "", person).strip(" .").title()
        n = int(money.replace(",", ""))
        # +1 they owe me more; -1 I owe them; -2 they paid me (they owe me less); +2 I paid them (I owe less / they owe me more)
        delta = {1: n, -1: -n, -2: -n, 2: n}[sign]
        return {"person": person, "amount": n, "delta": delta, "kind": {1: "lent", -1: "borrowed", -2: "received", 2: "paid"}[sign]}
    return None


def khata_add(db: DB, uid: int, entry: dict, note: str = "") -> dict:
    db.x("INSERT INTO khata(user_id,person,delta,kind,note,created_at) VALUES(?,?,?,?,?,?)",
         (uid, entry["person"], entry["delta"], entry["kind"], note[:200], now_iso()))
    return khata_balance(db, uid, entry["person"])


def khata_balance(db: DB, uid: int, person: str) -> dict:
    row = db.one("SELECT SUM(delta) b, COUNT(*) n FROM khata WHERE user_id=? AND lower(person)=lower(?)", (uid, person))
    return {"person": person, "balance": row["b"] or 0, "entries": row["n"]}


def khata_all(db: DB, uid: int) -> list[dict]:
    return db.q("SELECT person, SUM(delta) balance, COUNT(*) entries, MAX(created_at) last FROM khata WHERE user_id=? GROUP BY lower(person) "
                "HAVING SUM(delta)!=0 ORDER BY ABS(SUM(delta)) DESC", (uid,))


def balance_line(b: dict) -> str:
    n = b["balance"]
    return f"{b['person']} owes you ₹{n:,}" if n > 0 else f"You owe {b['person']} ₹{-n:,}" if n < 0 else f"You and {b['person']} are settled ✅"


def pay_request(user: dict, person: str, amount: int, phone: str | None = None) -> dict:
    """A friendly WhatsApp message to send someone, with a UPI link to pay you."""
    vpa = user.get("upi")
    upi = "upi://pay?" + urlencode({"pa": vpa, "pn": user.get("name") or "", "am": amount, "cu": "INR", "tn": "via Mindy"}) if vpa else None
    msg = f"Hi {person}! Gentle reminder about ₹{amount:,} 🙂" + (f" You can pay here in one tap: {go_link(upi)}" if upi else "") + " Thanks!"
    wa_link = (f"https://wa.me/{re.sub(r'[^0-9]', '', phone)}?text=" if phone else "https://wa.me/?text=") + quote(msg)
    return {"message": msg, "whatsapp": wa_link, "upi": go_link(upi) if upi else None}
