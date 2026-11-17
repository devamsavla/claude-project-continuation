"""Live features over one WebSocket per open app: presence, chat delivery, multiplayer games, watch parties,
in-app reminders, and phone notifications through Web Push."""
import asyncio
import base64
import json
import logging
import re
import secrets
import time
from collections import defaultdict

from .db import DB, now_iso
from .games import BOT, HandCricket, LastCard

log = logging.getLogger("mindy.realtime")


class Hub:
    def __init__(self):
        self.conns: dict[int, set] = defaultdict(set)
        self.games: dict[str, dict] = {}
        self.parties: dict[str, dict] = {}

    def online(self, uid: int) -> bool:
        return bool(self.conns.get(uid))

    async def connect(self, uid, ws):
        self.conns[uid].add(ws)

    def disconnect(self, uid, ws):
        self.conns[uid].discard(ws)
        if not self.conns[uid]:
            self.conns.pop(uid, None)

    async def send(self, uid: int, event: dict):
        for ws in list(self.conns.get(uid, ())):
            try:
                await ws.send_json(event)
            except Exception:
                self.disconnect(uid, ws)

    async def send_many(self, uids, event):
        await asyncio.gather(*(self.send(u, event) for u in set(uids)))


hub = Hub()


def fire(coro):
    """Run a coroutine from anywhere: inside the server's loop, or from a worker thread."""
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        loop = getattr(hub, "loop", None)
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            coro.close()


def friend_ids(db: DB, uid: int) -> list[int]:
    return [r["b"] for r in db.q("SELECT b FROM friends WHERE a=?", (uid,))]


def names(db: DB, ids) -> dict:
    out = {BOT: "Mindy"}
    for i in ids:
        if i != BOT:
            u = db.one("SELECT name FROM users WHERE id=?", (i,))
            out[i] = (u or {}).get("name") or "Friend"
    return out


async def presence(db: DB, uid: int, online: bool):
    await hub.send_many(friend_ids(db, uid), {"type": "presence", "user": uid, "online": online})


YT = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/|live/|embed/)|youtu\.be/)([\w-]{11})")


async def handle(db: DB, user: dict, data: dict, ws):
    uid, t = user["id"], data.get("type")
    if t == "ping":
        return await ws.send_json({"type": "pong"})

    # ---------------- games
    if t == "game.new":
        others = [int(x) for x in data.get("with", []) if int(x) in friend_ids(db, uid)][:3]
        kind = data.get("game")
        if kind == "hand":
            players = [uid, others[0] if others else BOT]
            game = HandCricket(*players)
        elif kind == "lastcard":
            players = [uid] + others + ([BOT] if not others else [])
            game = LastCard(players, names=names(db, players))
        else:
            return await ws.send_json({"type": "error", "message": "Unknown game"})
        room = secrets.token_hex(4)
        hub.games[room] = {"game": game, "kind": kind, "players": players, "names": names(db, players), "at": time.time()}
        for p in players:
            if p not in (uid, BOT):
                await hub.send(p, {"type": "game.invite", "room": room, "game": kind, "from": user.get("name") or "A friend"})
        return await _game_push(room)
    if t in ("game.move", "game.view"):
        g = hub.games.get(data.get("room"))
        if not g or uid not in g["players"]:
            return await ws.send_json({"type": "error", "message": "That game has ended."})
        if t == "game.move":
            err = g["game"].move(uid, data.get("move") or {})
            if err:
                return await ws.send_json({"type": "game.error", "room": data["room"], "message": err})
        return await _game_push(data["room"], only=None if t == "game.move" else uid)

    # ---------------- watch parties
    if t == "party.new":
        url = (data.get("url") or "").strip()
        m = YT.search(url)
        service = data.get("service")
        if not m and not service:
            return await ws.send_json({"type": "error", "message": "Paste a YouTube link, or pick Netflix, Prime Video, Hotstar or another app."})
        room = secrets.token_hex(4)
        p = {"id": room, "host": uid, "title": (data.get("title") or ("YouTube" if m else service))[:80], "video": m.group(1) if m else None,
             "service": service, "link": data.get("link") or "", "members": {uid}, "playing": False, "t": 0.0, "at": time.time(), "countdown": None}
        hub.parties[room] = p
        for f in [int(x) for x in data.get("with", []) if int(x) in friend_ids(db, uid)]:
            await hub.send(f, {"type": "party.invite", "room": room, "title": p["title"], "from": user.get("name") or "A friend"})
        return await _party_push(db, room)
    if t and t.startswith("party."):
        p = hub.parties.get(data.get("room"))
        if not p:
            return await ws.send_json({"type": "error", "message": "That watch party has ended."})
        if t == "party.join":
            p["members"].add(uid)
            return await _party_push(db, p["id"])
        if uid not in p["members"]:
            return
        if t == "party.sync":
            p.update(playing=bool(data.get("playing")), t=float(data.get("t") or 0), at=time.time())
            return await hub.send_many(p["members"] - {uid}, {"type": "party.sync", "room": p["id"], "playing": p["playing"], "t": p["t"], "by": uid})
        if t == "party.countdown":
            p["countdown"] = time.time() + 4
            return await hub.send_many(p["members"], {"type": "party.countdown", "room": p["id"], "start": p["countdown"]})
        if t in ("party.react", "party.chat"):
            payload = {"type": t, "room": p["id"], "from": user.get("name") or "Friend", "user": uid,
                       "emoji": (data.get("emoji") or "")[:4], "text": (data.get("text") or "")[:300]}
            return await hub.send_many(p["members"], payload)
        if t == "party.leave":
            p["members"].discard(uid)
            if not p["members"]:
                hub.parties.pop(p["id"], None)
            else:
                await _party_push(db, p["id"])
            return
    await ws.send_json({"type": "error", "message": "Unknown request"})


async def _game_push(room: str, only: int | None = None):
    g = hub.games[room]
    for p in g["players"]:
        if p != BOT and (only is None or p == only):
            await hub.send(p, {"type": "game.state", "room": room, "game": g["kind"], "names": {str(k): v for k, v in g["names"].items()}, "state": g["game"].view(p)})


async def _party_push(db: DB, room: str):
    p = hub.parties[room]
    now = time.time()
    t_now = p["t"] + (now - p["at"] if p["playing"] else 0)
    state = {"type": "party.state", "room": room, "host": p["host"], "title": p["title"], "video": p["video"], "service": p["service"],
             "link": p["link"], "playing": p["playing"], "t": t_now, "countdown": p["countdown"],
             "members": [{"id": m, "name": n} for m, n in names(db, p["members"]).items() if m != BOT]}
    await hub.send_many(p["members"], state)


# ---------------------------------------------------------------- Web Push (phone notifications)
def vapid(db: DB):
    """VAPID keys: from env if set, otherwise generated once and kept in the database."""
    import os
    from py_vapid import Vapid02
    from cryptography.hazmat.primitives import serialization
    pem = os.environ.get("VAPID_PRIVATE_KEY_PEM")
    if not pem:
        row = db.one("SELECT v FROM kv WHERE k='vapid_pem'")
        if row:
            pem = row["v"]
        else:
            v = Vapid02()
            v.generate_keys()
            pem = v.private_pem().decode()
            db.x("INSERT OR REPLACE INTO kv(k,v) VALUES('vapid_pem',?)", (pem,))
    v = Vapid02.from_pem(pem.encode())
    pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return v, base64.urlsafe_b64encode(pub).decode().rstrip("=")


def send_push(db: DB, uid: int, title: str, body: str, url: str = "/") -> int:
    """Sends a phone notification to every device the person turned notifications on for. Returns how many went."""
    import os
    subs = db.q("SELECT * FROM push_subs WHERE user_id=?", (uid,))
    if not subs:
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return 0
    v, _ = vapid(db)
    sent = 0
    for s in subs:
        try:
            webpush(json.loads(s["sub"]), json.dumps({"title": title, "body": body, "url": url}), vapid_private_key=v,
                    vapid_claims={"sub": os.environ.get("VAPID_SUBJECT", "mailto:hello@whatsonyourmind.online")}, timeout=10)
            sent += 1
        except WebPushException as e:
            if getattr(e, "response", None) is not None and e.response.status_code in (404, 410):
                db.x("DELETE FROM push_subs WHERE endpoint=?", (s["endpoint"],))
            log.warning("push failed: %s", e)
        except Exception as e:  # network trouble: never break the reminder loop
            log.warning("push failed: %s", e)
    return sent
