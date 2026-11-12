"""SQLite storage. One file, no server, fine for the first 10k users.
Swap for Postgres (same SQL, plus pgvector) when you outgrow it."""
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, wa_id TEXT UNIQUE NOT NULL, name TEXT, tz TEXT,
  plan TEXT DEFAULT 'free', created_at TEXT, last_inbound_at TEXT, onboarded INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY, user_id INTEGER, direction TEXT, body TEXT,
  wa_message_id TEXT UNIQUE, created_at TEXT);
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT, text TEXT, url TEXT,
  media_id TEXT, collection TEXT, tags TEXT, created_at TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(text, collection, tags, content='items', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
  INSERT INTO items_fts(rowid, text, collection, tags) VALUES (new.id, new.text, new.collection, new.tags); END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, text, collection, tags) VALUES('delete', old.id, old.text, old.collection, old.tags); END;
CREATE TABLE IF NOT EXISTS reminders(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, text TEXT, due_at TEXT, repeat TEXT,
  status TEXT DEFAULT 'pending', created_at TEXT);
CREATE INDEX IF NOT EXISTS reminders_due ON reminders(status, due_at);
CREATE TABLE IF NOT EXISTS lists(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, UNIQUE(user_id, name));
CREATE TABLE IF NOT EXISTS list_items(id INTEGER PRIMARY KEY, list_id INTEGER, text TEXT, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS occasions(
  id INTEGER PRIMARY KEY, user_id INTEGER, person TEXT, kind TEXT, month INTEGER, day INTEGER, year INTEGER);
CREATE TABLE IF NOT EXISTS accounts(
  ext TEXT PRIMARY KEY, user_id INTEGER NOT NULL, channel TEXT, last_inbound_at TEXT);
CREATE TABLE IF NOT EXISTS link_codes(code TEXT PRIMARY KEY, user_id INTEGER, expires TEXT);
CREATE TABLE IF NOT EXISTS waitlist(
  id INTEGER PRIMARY KEY, email TEXT, phone TEXT, interest TEXT, source TEXT, created_at TEXT, UNIQUE(email));
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            # older databases: every user row is also a WhatsApp account
            self.conn.execute("INSERT OR IGNORE INTO accounts(ext,user_id,channel,last_inbound_at) "
                              "SELECT wa_id,id,CASE WHEN wa_id LIKE 'ig:%' THEN 'ig' ELSE 'wa' END,last_inbound_at FROM users")
            self.conn.commit()
        from .auth import init_app_schema  # the web app's tables (sessions, friends, chats...)
        init_app_schema(self)

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql, args=()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    # ---- users and their channel accounts ----
    # ext is the id on a channel: a WhatsApp number ("447700900123") or "ig:<instagram-scoped id>".
    def user(self, ext: str, name: str | None, default_tz: str, channel: str = "wa") -> dict:
        acc = self.one("SELECT * FROM accounts WHERE ext=?", (ext,))
        if acc:
            return self.one("SELECT * FROM users WHERE id=?", (acc["user_id"],))
        uid = self.x("INSERT INTO users(wa_id,name,tz,created_at) VALUES(?,?,?,?)", (ext, name, default_tz, now_iso()))
        self.x("INSERT INTO accounts(ext,user_id,channel) VALUES(?,?,?)", (ext, uid, channel))
        u = self.one("SELECT * FROM users WHERE id=?", (uid,))
        u["_new"] = True
        return u

    def touch_inbound(self, user_id: int, ext: str | None = None):
        t = now_iso()
        self.x("UPDATE users SET last_inbound_at=? WHERE id=?", (t, user_id))
        if ext:
            self.x("UPDATE accounts SET last_inbound_at=? WHERE ext=?", (t, ext))

    def accounts(self, user_id: int):
        return self.q("SELECT * FROM accounts WHERE user_id=? ORDER BY channel DESC", (user_id,))

    # ---- linking WhatsApp, Instagram and the app into one person ----
    def link_code(self, user_id: int) -> str:
        import secrets
        from datetime import datetime, timedelta, timezone
        code = f"{secrets.randbelow(900000) + 100000}"
        exp = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(microsecond=0).isoformat()
        self.x("DELETE FROM link_codes WHERE user_id=?", (user_id,))
        self.x("INSERT OR REPLACE INTO link_codes(code,user_id,expires) VALUES(?,?,?)", (code, user_id, exp))
        return code

    def use_link_code(self, code: str):
        row = self.one("SELECT * FROM link_codes WHERE code=? AND expires>?", (code, now_iso()))
        if row:
            self.x("DELETE FROM link_codes WHERE code=?", (code,))
        return row["user_id"] if row else None

    def merge(self, src: int, dst: int):
        """Moves everything from user src into user dst, then removes src."""
        for t in ("items", "reminders", "occasions", "messages", "accounts"):
            self.x(f"UPDATE {t} SET user_id=? WHERE user_id=?", (dst, src))
        for l in self.q("SELECT * FROM lists WHERE user_id=?", (src,)):
            same = self.one("SELECT id FROM lists WHERE user_id=? AND name=?", (dst, l["name"]))
            if same:
                self.x("UPDATE list_items SET list_id=? WHERE list_id=?", (same["id"], l["id"]))
                self.x("DELETE FROM lists WHERE id=?", (l["id"],))
            else:
                self.x("UPDATE lists SET user_id=? WHERE id=?", (dst, l["id"]))
        self.x("DELETE FROM users WHERE id=?", (src,))

    def seen(self, wa_message_id: str) -> bool:
        """WhatsApp retries webhooks; ignore anything we've already handled."""
        if not wa_message_id:
            return False
        if self.one("SELECT 1 FROM messages WHERE wa_message_id=?", (wa_message_id,)):
            return True
        return False

    def log(self, user_id, direction, body, wa_message_id=None):
        try:
            self.x("INSERT INTO messages(user_id,direction,body,wa_message_id,created_at) VALUES(?,?,?,?,?)",
                   (user_id, direction, body, wa_message_id, now_iso()))
        except sqlite3.IntegrityError:
            pass

    # ---- items ----
    def save_item(self, user_id, kind, text, url=None, media_id=None, collection=None, tags=None) -> int:
        return self.x("INSERT INTO items(user_id,kind,text,url,media_id,collection,tags,created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (user_id, kind, text, url, media_id, collection or "Inbox", ",".join(tags or []), now_iso()))

    def search(self, user_id, query, limit=8):
        terms = [t for t in "".join(c if c.isalnum() else " " for c in query.lower()).split() if len(t) > 2]
        stop = {"what", "was", "that", "the", "where", "did", "save", "saved", "find", "show", "about", "with", "from", "this", "and", "for", "you", "have", "any", "which"}
        terms = [t for t in terms if t not in stop]
        if not terms:
            return self.q("SELECT * FROM items WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
        match = " OR ".join(f'"{t}"*' for t in terms)
        return self.q("SELECT items.* FROM items_fts JOIN items ON items.id=items_fts.rowid "
                      "WHERE items_fts MATCH ? AND items.user_id=? ORDER BY bm25(items_fts) LIMIT ?", (match, user_id, limit))

    # ---- reminders ----
    def add_reminder(self, user_id, text, due_at_utc_iso, repeat=None) -> int:
        return self.x("INSERT INTO reminders(user_id,text,due_at,repeat,created_at) VALUES(?,?,?,?,?)",
                      (user_id, text, due_at_utc_iso, repeat, now_iso()))

    def due_reminders(self, now_utc_iso):
        return self.q("SELECT r.*, u.tz FROM reminders r JOIN users u ON u.id=r.user_id "
                      "WHERE r.status='pending' AND r.due_at<=? ORDER BY r.due_at LIMIT 200", (now_utc_iso,))

    def upcoming(self, user_id, limit=10):
        return self.q("SELECT * FROM reminders WHERE user_id=? AND status='pending' ORDER BY due_at LIMIT ?", (user_id, limit))

    # ---- lists ----
    def list_add(self, user_id, name, entries):
        name = name.strip().title()
        self.x("INSERT OR IGNORE INTO lists(user_id,name) VALUES(?,?)", (user_id, name))
        lid = self.one("SELECT id FROM lists WHERE user_id=? AND name=?", (user_id, name))["id"]
        for e in entries:
            self.x("INSERT INTO list_items(list_id,text) VALUES(?,?)", (lid, e.strip()))
        return name, self.q("SELECT * FROM list_items WHERE list_id=? AND done=0", (lid,))

    def list_show(self, user_id, name):
        lst = self.one("SELECT id,name FROM lists WHERE user_id=? AND name=?", (user_id, name.strip().title()))
        if not lst:
            return None, []
        return lst["name"], self.q("SELECT * FROM list_items WHERE list_id=? AND done=0", (lst["id"],))

    # ---- occasions ----
    def add_occasion(self, user_id, person, kind, month, day, year=None):
        return self.x("INSERT INTO occasions(user_id,person,kind,month,day,year) VALUES(?,?,?,?,?,?)", (user_id, person, kind, month, day, year))

    def occasions_on(self, month, day):
        return self.q("SELECT o.* FROM occasions o WHERE month=? AND day=?", (month, day))

    # ---- waitlist ----
    def waitlist_add(self, email, phone, interest, source):
        try:
            self.x("INSERT INTO waitlist(email,phone,interest,source,created_at) VALUES(?,?,?,?,?)", (email, phone, interest, source, now_iso()))
            return True
        except sqlite3.IntegrityError:
            return False

    def export_user(self, user_id):
        return {t: self.q(f"SELECT * FROM {t} WHERE user_id=?", (user_id,)) for t in ("items", "reminders", "occasions")}

    def delete_user(self, user_id):
        for t in ("items", "reminders", "occasions", "messages", "accounts", "link_codes"):
            self.x(f"DELETE FROM {t} WHERE user_id=?", (user_id,))
        for l in self.q("SELECT id FROM lists WHERE user_id=?", (user_id,)):
            self.x("DELETE FROM list_items WHERE list_id=?", (l["id"],))
        self.x("DELETE FROM lists WHERE user_id=?", (user_id,))
        self.x("DELETE FROM users WHERE id=?", (user_id,))
