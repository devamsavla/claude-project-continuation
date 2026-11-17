import asyncio
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app, db
from app.whatsapp import wa
from app.handlers import send_due

client = TestClient(app)
USER = "447700900123"


def send(text, mid):
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": USER, "profile": {"name": "Maya Patel"}}],
        "messages": [{"from": USER, "id": mid, "type": "text", "text": {"body": text}}]}}]}]}
    wa.outbox.clear()
    r = client.post("/webhook", json=payload)
    assert r.status_code == 200
    return [m for m in wa.outbox if m.get("type") in ("text", "interactive")]


def body(m):
    return m["text"]["body"] if m["type"] == "text" else m["interactive"]["body"]["text"]


def test_verify():
    r = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "dev-verify-token", "hub.challenge": "42"})
    assert r.text == "42"
    assert client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"}).status_code == 403


def test_full_flow():
    out = send("hi", "m1")
    assert "Mindy" in body(out[0]) and "Europe/London" in body(out[0])
    assert send("hi", "m1") == []  # duplicate webhook ignored
    out = send("https://www.instagram.com/reel/xyz the pasta place in Soho", "m2")
    assert "Place saved" in body(out[-1]) and "do:" in str(out[-1])  # understood as a place, with one-tap actions
    out = send("where was that pasta place?", "m3")
    assert "pasta" in body(out[-1]).lower()
    out = send("remind me to call mum tomorrow at 6pm", "m4")
    assert "call mum" in body(out[-1]) and "18:00" in body(out[-1])
    out = send("add milk, eggs to shopping list", "m5")
    assert "milk" in body(out[-1]) and "eggs" in body(out[-1])
    out = send("Sofia's birthday is 12 March", "m6")
    assert "Sofia" in body(out[-1])
    out = send("upcoming", "m7")
    assert "call mum" in body(out[-1])


def test_reminder_delivery_and_template_fallback():
    u = db.one("SELECT * FROM users WHERE wa_id=?", (USER,))
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0).isoformat()
    db.add_reminder(u["id"], "drink water", past)
    wa.outbox.clear()
    asyncio.run(send_due(db))
    assert any(m["type"] == "interactive" and "drink water" in m["interactive"]["body"]["text"] for m in wa.outbox)
    # outside the 24h window -> template
    db.x("UPDATE accounts SET last_inbound_at=? WHERE user_id=?", ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(), u["id"]))
    db.add_reminder(u["id"], "pay rent", past)
    wa.outbox.clear()
    asyncio.run(send_due(db))
    assert wa.outbox[0]["type"] == "template"


def test_waitlist():
    r = client.post("/api/waitlist", json={"email": "test@example.com", "interest": "app"})
    assert r.json()["ok"] and r.json()["position"] >= 1
    assert client.post("/api/waitlist", json={"email": "bad"}).status_code == 422


def test_weekly_and_admin():
    from app.handlers import weekly_summary
    wa.outbox.clear()
    assert asyncio.run(weekly_summary(db)) >= 1
    assert wa.outbox
    assert client.get("/admin", params={"key": "wrong"}).status_code == 403
    r = client.get("/admin", params={"key": "change-me"})
    assert r.status_code == 200 and "test@example.com" in r.text
