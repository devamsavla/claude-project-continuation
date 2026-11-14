import asyncio
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app, db
from app.instagram import ig, normalise, _plain
from app.whatsapp import wa
from app.handlers import send_due

client = TestClient(app)
IGSID = "17841400000000001"
WA = "919820000001"


def ig_send(message, mid):
    ig.outbox.clear()
    payload = {"object": "instagram", "entry": [{"id": "999", "time": 1, "messaging": [
        {"sender": {"id": IGSID}, "recipient": {"id": "999"}, "timestamp": 1, "message": {"mid": mid, **message}}]}]}
    assert client.post("/webhook/instagram", json=payload).status_code == 200
    return [m["message"]["text"] for m in ig.outbox if "message" in m]


def wa_send(text, mid):
    wa.outbox.clear()
    payload = {"entry": [{"changes": [{"value": {"contacts": [{"wa_id": WA, "profile": {"name": "Aanya"}}],
               "messages": [{"from": WA, "id": mid, "type": "text", "text": {"body": text}}]}}]}]}
    assert client.post("/webhook", json=payload).status_code == 200
    return [m.get("text", {}).get("body") or m.get("interactive", {}).get("body", {}).get("text") for m in wa.outbox if m.get("type") in ("text", "interactive")]


def test_verify_instagram():
    r = client.get("/webhook/instagram", params={"hub.mode": "subscribe", "hub.verify_token": "dev-verify-token", "hub.challenge": "7"})
    assert r.text == "7"


def test_normalise_shapes():
    reel = normalise({"sender": {"id": "1"}, "message": {"mid": "a", "attachments": [{"type": "ig_reel", "payload": {"url": "https://www.instagram.com/reel/x", "title": "Paneer tikka", "reel_video_id": "5"}}]}})
    assert reel["type"] == "text" and reel["share"] == "reel" and "Paneer tikka" in reel["text"]["body"]
    post = normalise({"sender": {"id": "1"}, "message": {"mid": "b", "attachments": [{"type": "ig_post", "payload": {"url": "https://www.instagram.com/p/y", "title": "Lisbon", "ig_post_media_id": "9"}}]}})
    assert post["share"] == "post"
    assert normalise({"sender": {"id": "1"}, "message": {"mid": "c", "text": "hi", "is_echo": True}}) is None
    qr = normalise({"sender": {"id": "1"}, "message": {"mid": "d", "text": "My reminders", "quick_reply": {"payload": "upcoming"}}})
    assert qr["type"] == "interactive"
    assert _plain("Saved to *Reels* in _your_ mind") == "Saved to Reels in your mind"


def test_instagram_flow_and_linking():
    out = ig_send({"text": "hi"}, "ig1")
    assert "Mindy" in out[0] and "24 hours" in out[0]
    out = ig_send({"attachments": [{"type": "ig_reel", "payload": {"url": "https://www.instagram.com/reel/abc", "title": "Air fryer paneer tikka", "reel_video_id": "1"}}]}, "ig2")
    assert "Recipe saved" in out[-1] and "*" not in out[-1]
    out = ig_send({"text": "what was that paneer recipe?"}, "ig3")
    assert "paneer" in out[-1].lower()
    out = ig_send({"text": "remind me to cook it in 3 days at 7pm"}, "ig4")
    assert "Heads up" in out[-1]
    # link Instagram to WhatsApp
    out = ig_send({"text": "link"}, "ig5")
    code = [w for w in out[-1].replace("*", "").split() if w.isdigit() and len(w) == 6][0]
    wa_send("hi", "w1")
    out = wa_send(f"link {code}", "w2")
    assert "Linked" in out[-1] and "WhatsApp" in out[-1] and "Instagram" in out[-1]
    u = db.one("SELECT u.* FROM users u JOIN accounts a ON a.user_id=u.id WHERE a.ext=?", (f"ig:{IGSID}",))
    assert {a["channel"] for a in db.accounts(u["id"])} == {"wa", "ig"}
    # the Instagram reel is now findable from WhatsApp
    out = wa_send("where's that paneer reel?", "w3")
    assert "paneer" in out[-1].lower()
    # a due reminder goes to WhatsApp (template if outside its window)
    db.add_reminder(u["id"], "cook paneer", (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0).isoformat())
    wa.outbox.clear(); ig.outbox.clear()
    asyncio.run(send_due(db))
    assert any("cook paneer" in str(m) for m in wa.outbox) and not ig.outbox


def test_instagram_only_reminder_outside_window_is_marked():
    sid = "17841400000000077"
    payload = {"object": "instagram", "entry": [{"messaging": [{"sender": {"id": sid}, "message": {"mid": "solo1", "text": "hi"}}]}]}
    client.post("/webhook/instagram", json=payload)
    u = db.one("SELECT u.* FROM users u JOIN accounts a ON a.user_id=u.id WHERE a.ext=?", (f"ig:{sid}",))
    db.x("UPDATE accounts SET last_inbound_at=? WHERE ext=?", ((datetime.now(timezone.utc) - timedelta(days=3)).isoformat(), f"ig:{sid}"))
    rid = db.add_reminder(u["id"], "solo reminder", (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0).isoformat())
    asyncio.run(send_due(db))
    assert db.one("SELECT status FROM reminders WHERE id=?", (rid,))["status"] == "undelivered"
