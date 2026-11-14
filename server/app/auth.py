"""Signing in to the web app with WhatsApp.
Two ways, both prove you own the number:
1. Type your number in the app; Mindy sends a 6-digit code to your WhatsApp.
2. Send LOGIN to Mindy on WhatsApp (or Instagram); Mindy replies with a code; type it in the app.
A session is a random token; only its SHA-256 hash is stored."""
import hashlib
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException

from .config import settings
from .db import DB, now_iso

APP_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS login_codes(code TEXT PRIMARY KEY, user_id INTEGER, expires TEXT);
CREATE TABLE IF NOT EXISTS friends(a INTEGER, b INTEGER, created_at TEXT, PRIMARY KEY(a, b));
CREATE TABLE IF NOT EXISTS invites(code TEXT PRIMARY KEY, user_id INTEGER UNIQUE, created_at TEXT);
CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY, name TEXT, is_group INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS chat_members(chat_id INTEGER, user_id INTEGER, last_read INTEGER DEFAULT 0, PRIMARY KEY(chat_id, user_id));
CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY, chat_id INTEGER, user_id INTEGER, body TEXT, kind TEXT DEFAULT 'text', created_at TEXT);
CREATE INDEX IF NOT EXISTS chat_messages_chat ON chat_messages(chat_id, id);
CREATE TABLE IF NOT EXISTS moods(user_id INTEGER, day TEXT, mood INTEGER, energy INTEGER, PRIMARY KEY(user_id, day));
CREATE TABLE IF NOT EXISTS stamps(id INTEGER PRIMARY KEY, user_id INTEGER, kind TEXT, title TEXT, place TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, title TEXT, when_at TEXT, place TEXT, created_by INTEGER, chat_id INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS plan_people(plan_id INTEGER, user_id INTEGER, rsvp TEXT DEFAULT 'invited', PRIMARY KEY(plan_id, user_id));
CREATE TABLE IF NOT EXISTS push_subs(endpoint TEXT PRIMARY KEY, user_id INTEGER, sub TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS family(a INTEGER, b INTEGER, created_at TEXT, PRIMARY KEY(a, b));
CREATE TABLE IF NOT EXISTS family_codes(code TEXT PRIMARY KEY, user_id INTEGER, expires TEXT);
CREATE TABLE IF NOT EXISTS care_log(id INTEGER PRIMARY KEY, reminder_id INTEGER, user_id INTEGER, set_by INTEGER, text TEXT,
  due_at TEXT, sent_at TEXT, took_at TEXT, alerted_at TEXT);
CREATE TABLE IF NOT EXISTS scam_reports(id INTEGER PRIMARY KEY, number TEXT, text_hash TEXT, reporter INTEGER, created_at TEXT);
CREATE INDEX IF NOT EXISTS scam_num ON scam_reports(number);
CREATE INDEX IF NOT EXISTS scam_hash ON scam_reports(text_hash);
CREATE TABLE IF NOT EXISTS khata(id INTEGER PRIMARY KEY, user_id INTEGER, person TEXT, delta INTEGER, kind TEXT, note TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS khata_user ON khata(user_id, person);
CREATE TABLE IF NOT EXISTS verified_numbers(number TEXT PRIMARY KEY, name TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS care_log_open ON care_log(took_at, alerted_at, sent_at);
"""
USER_COLUMNS = [("status", "TEXT DEFAULT 'free'"), ("status_at", "TEXT"), ("notify", "TEXT DEFAULT 'both'"), ("hue", "INTEGER"),
                ("share_matches", "INTEGER DEFAULT 1"), ("simple", "INTEGER DEFAULT 0"), ("email", "TEXT"), ("upi", "TEXT")]
EXTRA_COLUMNS = {"items": [("rkind", "TEXT"), ("title", "TEXT"), ("place", "TEXT"), ("done_at", "TEXT")],
                 "reminders": [("kind", "TEXT DEFAULT 'normal'"), ("set_by", "INTEGER"), ("item_id", "INTEGER")]}


def init_app_schema(db: DB):
    with db.lock:
        db.conn.executescript(APP_SCHEMA)
        have = {r[1] for r in db.conn.execute("PRAGMA table_info(users)").fetchall()}
        for col, decl in USER_COLUMNS:
            if col not in have:
                db.conn.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        for table, cols in EXTRA_COLUMNS.items():
            have = {r[1] for r in db.conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for col, decl in cols:
                if col not in have:
                    db.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        db.conn.commit()


def phone_ext(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if raw.strip().startswith("00"):
        digits = digits[2:]
    return digits if 8 <= len(digits) <= 15 else None


def new_code(db: DB, user_id: int, minutes: int = 10) -> str:
    db.x("DELETE FROM login_codes WHERE user_id=? OR expires<?", (user_id, now_iso()))
    while True:
        code = f"{secrets.randbelow(900000) + 100000}"
        if not db.one("SELECT 1 FROM login_codes WHERE code=?", (code,)):
            break
    exp = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
    db.x("INSERT INTO login_codes(code,user_id,expires) VALUES(?,?,?)", (code, user_id, exp))
    return code


_tries: dict[str, list[float]] = {}


def too_many(key: str, limit: int = 8, window: float = 600) -> bool:
    """Simple brute-force guard: at most `limit` code attempts per 10 minutes per caller."""
    now = time.time()
    hits = [t for t in _tries.get(key, []) if now - t < window]
    hits.append(now)
    _tries[key] = hits
    return len(hits) > limit


def use_code(db: DB, code: str, ext: str | None = None) -> int | None:
    row = db.one("SELECT * FROM login_codes WHERE code=? AND expires>?", (code.strip(), now_iso()))
    if not row:
        return None
    if ext:
        acc = db.one("SELECT user_id FROM accounts WHERE ext=?", (ext,))
        if not acc or acc["user_id"] != row["user_id"]:
            return None
    db.x("DELETE FROM login_codes WHERE code=?", (row["code"],))
    return row["user_id"]


def new_session(db: DB, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.x("INSERT INTO sessions(token_hash,user_id,created_at,last_seen) VALUES(?,?,?,?)",
         (hashlib.sha256(token.encode()).hexdigest(), user_id, now_iso(), now_iso()))
    return token


def user_for_token(db: DB, token: str | None) -> dict | None:
    if not token:
        return None
    s = db.one("SELECT * FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    if not s:
        return None
    return db.one("SELECT * FROM users WHERE id=?", (s["user_id"],))


def end_session(db: DB, token: str):
    db.x("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))


def make_dependency(db: DB):
    def current_user(authorization: str | None = Header(default=None)) -> dict:
        token = (authorization or "").removeprefix("Bearer ").strip()
        u = user_for_token(db, token)
        if not u:
            raise HTTPException(401, "Please sign in again.")
        return u
    return current_user
