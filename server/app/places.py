"""Places: "here's where I parked", "where's my car", "take me home".
A location sent on WhatsApp or Telegram is saved with a label (car, home, office, or any name). Asking for it
later gets back the pin, a one-tap walking or driving route, a 3D Street View of the exact spot and any photo
or note you left ("B2, pillar 14"). Built for people who can't use maps but can send a message."""
import re
from urllib.parse import urlencode

from .db import DB, now_iso

LABELS = {"car": r"\b(car|parked|parking|bike|scooter|gaadi|gadi)\b", "home": r"\b(home|ghar|house)\b",
          "office": r"\b(office|work|college|uni|university|school)\b", "hotel": r"\b(hotel|airbnb|hostel|stay)\b"}


def label_of(text: str) -> str | None:
    low = (text or "").lower()
    for k, p in LABELS.items():
        if re.search(p, low):
            return k
    m = re.search(r"\b(?:save|call) (?:this|it|here) (?:as )?([a-z][a-z ]{1,20})$", low)
    return m.group(1).strip() if m else None


def save(db: DB, uid: int, lat: float, lng: float, label: str | None = None, note: str = "", name: str = "") -> int:
    if label:
        db.x("DELETE FROM places WHERE user_id=? AND label=?", (uid, label))  # one "car", one "home"
    return db.x("INSERT INTO places(user_id,label,lat,lng,name,note,created_at) VALUES(?,?,?,?,?,?,?)",
                (uid, label, lat, lng, name[:120], note[:300], now_iso()))


def latest(db: DB, uid: int, label: str | None = None) -> dict | None:
    if label:
        return db.one("SELECT * FROM places WHERE user_id=? AND label=? ORDER BY id DESC LIMIT 1", (uid, label))
    return db.one("SELECT * FROM places WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,))


def set_label(db: DB, uid: int, pid: int, label: str):
    db.x("DELETE FROM places WHERE user_id=? AND label=? AND id!=?", (uid, label, pid))
    db.x("UPDATE places SET label=? WHERE id=? AND user_id=?", (label, pid, uid))


def add_note(db: DB, uid: int, label: str, note: str = "", photo: str | None = None) -> dict | None:
    p = latest(db, uid, label)
    if not p:
        return None
    if note:
        db.x("UPDATE places SET note=? WHERE id=?", ((p["note"] + " · " if p["note"] else "") + note[:200], p["id"]))
    if photo:
        db.x("UPDATE places SET photo=? WHERE id=?", (photo, p["id"]))
    return latest(db, uid, label)


def links(p: dict, mode: str = "walking") -> list[tuple[str, str]]:
    ll = f"{p['lat']},{p['lng']}"
    return [("Walk there" if mode == "walking" else "Directions", "https://www.google.com/maps/dir/?" + urlencode({"api": 1, "destination": ll, "travelmode": mode})),
            ("Street View", "https://www.google.com/maps/@?" + urlencode({"api": 1, "map_action": "pano", "viewpoint": ll})),
            ("Open map", "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": ll}))]


def ask(text: str) -> tuple[str, str] | None:
    """'where's my car' -> ('car','walking'); 'take me home' -> ('home','driving'); 'directions to office'."""
    low = text.lower().strip(" ?!.")
    if re.search(r"\b(where('?s| is| did i (park|leave))|find|kahan|kaha)\b.*\b(car|bike|scooter|gaadi|gadi|parked|park)\b|\bwhere did i park\b", low):
        return "car", "walking"
    m = re.search(r"\b(?:take me|go|get me|directions?|route|way|navigate)\b(?: back)?(?: to)? (?:my |the )?(home|ghar|office|work|hotel|college|uni|school|[a-z]{2,20})$", low)
    if m:
        lab = label_of(m.group(1)) or m.group(1)
        return lab, "driving" if lab in ("home", "office", "hotel") else "walking"
    return None
