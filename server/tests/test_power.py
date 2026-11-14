"""The 'tech friend' layer: saves that become real, family care, do-it links, khata, scam shield, file tools, Telegram."""
import asyncio
import subprocess
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import care, hooks, skills
from app.handlers import care_check, send_due
from app.main import app, db, mindy
from app.telegram import tg
from app.whatsapp import wa

client = TestClient(app)


def wa_send(ext, text, mid, name="Asha"):
    wa.outbox.clear()
    asyncio.run(mindy.handle({"from": ext, "id": mid, "type": "text", "text": {"body": text}}, name))
    return wa.outbox


def wa_button(ext, bid, mid):
    wa.outbox.clear()
    asyncio.run(mindy.handle({"from": ext, "id": mid, "type": "interactive", "interactive": {"button_reply": {"id": bid}}}, None))
    return wa.outbox


def text_of(m):
    if m["type"] == "text":
        return m["text"]["body"]
    if m["type"] == "interactive":
        return m["interactive"]["body"]["text"]
    return str(m)


def signin(phone, name):
    code = client.post("/api/auth/start", json={"phone": phone}).json()["dev_code"]
    tok = client.post("/api/auth/verify", json={"phone": phone, "code": code}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    client.patch("/api/me", json={"name": name}, headers=h)
    return h, client.get("/api/me", headers=h).json()


def test_reels_become_real_plans():
    ext = "919811100001"
    out = wa_send(ext, "https://www.instagram.com/reel/r1 air fryer paneer tikka recipe", "p1")
    m = out[-1]
    assert m["type"] == "interactive" and "Recipe saved" in text_of(m)
    ids = [b["reply"]["id"] for b in m["interactive"]["action"]["buttons"]]
    assert ids[0].endswith(":shop")
    out = wa_button(ext, ids[0], "p2")  # add ingredients + cook reminder
    assert "Shopping" in text_of(out[-1]) and "Sunday" in text_of(out[-1])
    uid = db.one("SELECT user_id FROM accounts WHERE ext=?", (ext,))["user_id"]
    assert db.one("SELECT COUNT(*) n FROM reminders WHERE user_id=? AND text LIKE 'Cook%'", (uid,))["n"] == 1
    out = wa_send(ext, "10 min abs workout https://www.instagram.com/reel/r2", "p3")
    iid = int(out[-1]["interactive"]["action"]["buttons"][0]["reply"]["id"].split(":")[1])
    out = wa_button(ext, f"do:{iid}:train", "p4")
    assert "every week" in text_of(out[-1])
    out = wa_button(ext, f"do:{iid}:done", "p5")
    assert "1 saves turned real" in text_of(out[-1]) and "streak" in text_of(out[-1])


def test_friend_matches_and_score():
    ha, a = signin("+91 98111 00002", "Kavya")
    hb, b = signin("+91 98111 00003", "Rohan")
    inv = client.get("/api/invite", headers=ha).json()["code"]
    client.post("/api/friends/accept", json={"code": inv}, headers=hb)
    client.post("/api/items", json={"text": "best vada pav in Dadar, go early https://www.instagram.com/reel/x1"}, headers=ha)
    client.post("/api/items", json={"text": "Dadar vada pav spot everyone talks about https://www.instagram.com/reel/x2"}, headers=hb)
    ms = client.get("/api/matches", headers=ha).json()
    assert ms and ms[0]["friend"]["name"] == "Rohan"
    item = ms[0]["item"]
    r = client.post(f"/api/items/{item['id']}/do", json={"action": "go", "people": [b["id"]], "when": "saturday 1pm"}, headers=ha).json()
    assert "Plan made" in r["reply"]
    assert any("vada pav" in p["title"].lower() for p in client.get("/api/plans", headers=hb).json())
    home = client.get("/api/home", headers=ha).json()
    assert "score" in home and "matches" in home
    client.patch("/api/me", json={"share_matches": False}, headers=hb)
    assert client.get("/api/matches", headers=ha).json() == []


def test_family_care_loop():
    hs, son = signin("+44 7700 900111", "Dev")
    mum_ext = "919822200001"
    wa_send(mum_ext, "hi", "c0", "Meena")
    code = client.post("/api/family/code", headers=hs).json()["code"]
    out = wa_send(mum_ext, f"family {code}", "c1", "Meena")
    assert "linked" in text_of(out[-1])
    fam = client.get("/api/family", headers=hs).json()
    mum = next(m for m in fam["members"] if m["name"] == "Meena")
    assert client.post("/api/care", json={"member": 99999, "text": "x", "when": "9am"}, headers=hs).status_code == 403
    rem = client.post("/api/care", json={"member": mum["id"], "text": "BP tablet", "when": "every day 9am"}, headers=hs).json()
    assert rem["kind"] == "care" and rem["repeat"] == "daily"
    # it's 9am: Mum gets it with an "I took it" button
    db.x("UPDATE reminders SET due_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(seconds=5)).replace(microsecond=0).isoformat(), rem["id"]))
    wa.outbox.clear()
    asyncio.run(send_due(db))
    msg = next(m for m in wa.outbox if "BP tablet" in str(m))
    assert "From Dev" in str(msg) and "took:" in str(msg)
    assert db.one("SELECT COUNT(*) n FROM reminders WHERE user_id=? AND kind='care' AND status='pending'", (mum["id"],))["n"] == 1  # tomorrow's
    # she doesn't tap it: after the alert window, Dev is told
    db.x("UPDATE care_log SET sent_at=? WHERE user_id=?", ((datetime.now(timezone.utc) - timedelta(hours=2)).replace(microsecond=0).isoformat(), mum["id"]))
    wa.outbox.clear()
    asyncio.run(care_check(db))
    assert any("Meena" in str(m) and ("hasn't confirmed" in str(m) or "mindy_care_alert" in str(m)) for m in wa.outbox)
    today = client.get("/api/family", headers=hs).json()["today"]
    assert next(t for t in today if t["member"]["name"] == "Meena")["doses"][0]["state"] == "missed"
    # she replies "took" on WhatsApp: it counts
    out = wa_send(mum_ext, "took", "c2", "Meena")
    assert "Noted" in text_of(out[-1])
    assert db.one("SELECT took_at FROM care_log WHERE user_id=?", (mum["id"],))["took_at"]


def test_do_it_links_and_khata():
    ext = "919833300001"
    out = wa_send(ext, "book an uber to Phoenix Mall, Lower Parel", "k1")
    m = out[-1]
    assert m["interactive"]["type"] == "cta_url" and "m.uber.com" in m["interactive"]["action"]["parameters"]["url"]
    wa_send(ext, "my upi is asha@okaxis", "k2")
    out = wa_send(ext, "Ramesh owes me 500", "k3")
    assert "Ramesh owes you ₹500" in text_of(out[-1])
    wa_send(ext, "got 200 from Ramesh", "k4")
    out = wa_send(ext, "khata", "k5")
    assert "Ramesh owes you ₹300" in text_of(out[-1])
    out = wa_send(ext, "remind Ramesh", "k6")
    url = out[-1]["interactive"]["action"]["parameters"]["url"]
    assert url.startswith("https://wa.me/?text=") and "300" in url and "go%3Fto%3Dupi" in url
    r = client.get("/go", params={"to": "upi://pay?pa=asha@okaxis&am=300"})
    assert r.status_code == 200 and "Pay with UPI" in r.text
    assert client.get("/go", params={"to": "https://evil.example"}).status_code == 400


def test_scam_shield_and_reports():
    ext = "919844400001"
    msg = "Dear customer your SBI account will be blocked today. Update KYC now: http://sbi-kyc-update.top/login"
    out = wa_send(ext, msg, "s1")  # forwarded link: warned straight away, not saved quietly
    assert "SCAM" in text_of(out[-1])
    out = wa_send(ext, "report", "s2")
    assert "Reported" in text_of(out[-1])
    out = wa_send(ext, "is this a scam? Hi mum this is my new number, send 5000 urgently", "s3")
    assert "SCAM" in text_of(out[-1]) or "careful" in text_of(out[-1]).lower()
    h, _ = signin("+91 98444 00002", "Tara")
    r = client.post("/api/check", json={"text": "check this https://sbi-kyc-update.top/x"}, headers=h).json()
    assert r["verdict"] == "scam" and any("reported" in x for x in r["reasons"])
    assert skills.link_check(db, "https://www.onlinesbi.sbi")["verdict"] == "ok"


def test_file_tools_and_screenshot_circle(tmp_path):
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
                    "-f", "lavfi", "-i", "sine=duration=1", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(clip)], check=True)
    out = skills.convert(clip.read_bytes(), "video/mp4", "mp3")
    assert out and out[1] == "mp3" and out[0][:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3") or out[0][:2] == b"\xff\xfb"
    out = skills.convert(clip.read_bytes(), "video/mp4", "compress")
    assert out and out[1] == "mp4"
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (600, 1200), "white").save(buf, "PNG")
    marked = skills.circle(buf.getvalue(), 0.5, 0.3, 0.08)
    im = Image.open(io.BytesIO(marked))
    assert im.size == (600, 1200) and im.getpixel((300, 360 - 48 - 3))[1] > 150  # green ring drawn


def test_telegram_channel():
    upd = {"update_id": 1, "message": {"message_id": 7, "chat": {"id": 5551, "type": "private"}, "from": {"first_name": "Neel"}, "text": "/start"}}
    assert client.post("/webhook/telegram", json=upd).status_code == 401
    tg.outbox.clear()
    r = client.post("/webhook/telegram", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": "dev-telegram-secret"})
    assert r.status_code == 200
    assert any("tech friend" in str(m) for m in tg.outbox)
    tg.outbox.clear()
    fwd = {"update_id": 2, "message": {"message_id": 8, "chat": {"id": 5551, "type": "private"}, "from": {"first_name": "Neel"},
                                       "forward_origin": {"type": "channel", "chat": {"title": "Startup Notes"}}, "text": "10 cold email templates that work"}}
    client.post("/webhook/telegram", json=fwd, headers={"X-Telegram-Bot-Api-Secret-Token": "dev-telegram-secret"})
    uid = db.one("SELECT user_id FROM accounts WHERE ext='tg:5551'")["user_id"]
    assert db.one("SELECT COUNT(*) n FROM items WHERE user_id=? AND text LIKE '%Startup Notes%'", (uid,))["n"] == 1
    # reminders on Telegram are free: no WhatsApp template needed
    db.add_reminder(uid, "Stand-up call", (datetime.now(timezone.utc) - timedelta(seconds=5)).replace(microsecond=0).isoformat())
    tg.outbox.clear()
    asyncio.run(send_due(db))
    assert any("Stand-up call" in str(m) for m in tg.outbox)
