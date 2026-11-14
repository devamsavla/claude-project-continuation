"""Family care: the loop a personal assistant can't run, because it spans people.
A son in London links with his mum in Pune. He sets "BP tablet, every day 9am" for her. At 9:00 her phone gets
it on WhatsApp (or the app) with a big "I took it" button. If she hasn't tapped it after CARE_ALERT_MINUTES,
everyone in the family who cares for her gets an alert. When she taps, they see it in the app.
Mindy never gives medical advice: it only reminds, confirms and alerts."""
import secrets
from datetime import datetime, timedelta, timezone

from .config import settings
from .db import DB, now_iso


def _iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def family_code(db: DB, uid: int) -> str:
    db.x("DELETE FROM family_codes WHERE user_id=? OR expires<?", (uid, now_iso()))
    code = f"{secrets.randbelow(900000) + 100000}"
    db.x("INSERT INTO family_codes(code,user_id,expires) VALUES(?,?,?)", (code, uid, _iso(datetime.now(timezone.utc) + timedelta(days=7))))
    return code


def join_family(db: DB, uid: int, code: str) -> int | None:
    row = db.one("SELECT * FROM family_codes WHERE code=? AND expires>?", (code.strip(), now_iso()))
    if not row or row["user_id"] == uid:
        return None
    other = row["user_id"]
    for a, b in ((uid, other), (other, uid)):
        db.x("INSERT OR IGNORE INTO family(a,b,created_at) VALUES(?,?,?)", (a, b, now_iso()))
        db.x("INSERT OR IGNORE INTO friends(a,b,created_at) VALUES(?,?,?)", (a, b, now_iso()))
    return other


def family_of(db: DB, uid: int) -> list[dict]:
    return db.q("SELECT u.id, u.name, u.tz FROM family f JOIN users u ON u.id=f.b WHERE f.a=? ORDER BY u.name", (uid,))


def is_family(db: DB, a: int, b: int) -> bool:
    return a == b or bool(db.one("SELECT 1 FROM family WHERE a=? AND b=?", (a, b)))


def add_care(db: DB, carer: dict, member_id: int, text: str, due_utc: str, repeat: str | None) -> int:
    return db.add_reminder(member_id, text, due_utc, repeat, kind="care", set_by=carer["id"])


def open_log(db: DB, reminder: dict) -> int:
    return db.x("INSERT INTO care_log(reminder_id,user_id,set_by,text,due_at,sent_at) VALUES(?,?,?,?,?,?)",
                (reminder["id"], reminder["user_id"], reminder.get("set_by"), reminder["text"], reminder["due_at"], now_iso()))


def took(db: DB, uid: int, log_id: int | None = None) -> dict | None:
    """Marks a dose taken: a specific one (button), or the latest open one (they typed 'took it')."""
    if log_id:
        row = db.one("SELECT * FROM care_log WHERE id=? AND user_id=?", (log_id, uid))
    else:
        row = db.one("SELECT * FROM care_log WHERE user_id=? AND took_at IS NULL ORDER BY id DESC LIMIT 1", (uid,))
    if not row:
        return None
    if not row["took_at"]:
        db.x("UPDATE care_log SET took_at=? WHERE id=?", (now_iso(), row["id"]))
    return db.one("SELECT * FROM care_log WHERE id=?", (row["id"],))


def overdue(db: DB, now: datetime | None = None) -> list[dict]:
    cutoff = _iso((now or datetime.now(timezone.utc)) - timedelta(minutes=settings.care_alert_minutes))
    return db.q("SELECT c.*, u.name FROM care_log c JOIN users u ON u.id=c.user_id WHERE c.took_at IS NULL AND c.alerted_at IS NULL AND c.sent_at<=?", (cutoff,))


def carers(db: DB, row: dict) -> list[int]:
    ids = {f["id"] for f in family_of(db, row["user_id"])}
    if row.get("set_by") and row["set_by"] != row["user_id"]:
        ids.add(row["set_by"])
    return sorted(ids)


def today(db: DB, uid: int) -> list[dict]:
    """Each family member's care reminders for the last 24 hours and next 24 hours, with taken / missed / waiting."""
    out = []
    now = datetime.now(timezone.utc)
    for m in [{"id": uid, "name": "You"}] + family_of(db, uid):
        logs = db.q("SELECT * FROM care_log WHERE user_id=? AND sent_at>? ORDER BY due_at", (m["id"], _iso(now - timedelta(hours=24))))
        nxt = db.q("SELECT id, text, due_at, repeat, set_by FROM reminders WHERE user_id=? AND kind='care' AND status='pending' AND due_at<? ORDER BY due_at",
                   (m["id"], _iso(now + timedelta(hours=24))))
        if not logs and not nxt:
            continue
        rows = [{"id": l["id"], "text": l["text"], "due_at": l["due_at"], "state": "taken" if l["took_at"] else "missed" if l["alerted_at"] else "waiting",
                 "took_at": l["took_at"]} for l in logs]
        rows += [{"id": None, "reminder": n["id"], "text": n["text"], "due_at": n["due_at"], "state": "upcoming", "repeat": n["repeat"]} for n in nxt]
        out.append({"member": m, "doses": rows})
    return out
