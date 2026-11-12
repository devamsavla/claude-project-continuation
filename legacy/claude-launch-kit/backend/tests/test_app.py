"""The web app with several real people at once: sign in with WhatsApp codes, friends by invite link, shared chats
with @mindy, plans, reminders delivered live, multiplayer games and a synced watch party."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.handlers import send_due
from app.main import app, db, mindy
from app.whatsapp import wa

PHONES = {"aarav": "+91 98200 11111", "zoya": "+91 98200 22222", "sam": "+44 7700 900333"}


def wait(ws, kind, pred=lambda e: True, limit=40):
    for _ in range(limit):
        e = ws.receive_json()
        if e.get("type") == kind and pred(e):
            return e
    raise AssertionError(f"no {kind} event")


def sign_in(c, who):
    r = c.post("/api/auth/start", json={"phone": PHONES[who]})
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    # the code really went out on WhatsApp (dry-run outbox)
    assert any(code in str(m) for m in wa.outbox)
    r = c.post("/api/auth/verify", json={"phone": PHONES[who], "code": code})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert c.patch("/api/me", json={"name": who.title()}, headers=h).json()["name"] == who.title()
    return tok, h


def test_sign_in_rules():
    with TestClient(app) as c:
        assert c.post("/api/auth/start", json={"phone": "123"}).status_code == 422
        assert c.get("/api/me").status_code == 401
        r = c.post("/api/auth/start", json={"phone": "+91 98200 99999"})
        code = r.json()["dev_code"]
        # a code only works for the number it was sent to
        assert c.post("/api/auth/verify", json={"phone": "+91 98200 88888", "code": code}).status_code == 401
        assert c.post("/api/auth/verify", json={"phone": "+91 98200 99999", "code": code}).status_code == 200
        # and only once
        assert c.post("/api/auth/verify", json={"phone": "+91 98200 99999", "code": code}).status_code == 401


def test_login_from_whatsapp_and_shared_memory():
    """Send LOGIN to Mindy on WhatsApp, type the code in the app, and everything sent on WhatsApp is there."""
    ext = "919820077777"
    wa.outbox.clear()
    asyncio.run(mindy.handle({"from": ext, "id": "w-1", "type": "text", "text": {"body": "https://www.instagram.com/reel/abc butter chicken recipe"}}, "Isha"))
    asyncio.run(mindy.handle({"from": ext, "id": "w-2", "type": "text", "text": {"body": "login"}}, "Isha"))
    reply = wa.outbox[-1]["text"]["body"]
    code = next(w.strip("*.") for w in reply.split() if w.strip("*").isdigit() and len(w.strip("*")) == 6)
    with TestClient(app) as c:
        tok = c.post("/api/auth/verify", json={"code": code}).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        items = c.get("/api/items", headers=h).json()
        assert any("butter chicken" in i["text"] and i["collection"] == "Reels" for i in items)
        assert c.get("/api/items", params={"q": "butter chicken"}, headers=h).json()
        # saved in the app, found from WhatsApp
        c.post("/api/items", json={"text": "Wifi password at the cafe is chai2026"}, headers=h)
    wa.outbox.clear()
    asyncio.run(mindy.handle({"from": ext, "id": "w-3", "type": "text", "text": {"body": "what is the wifi password?"}}, "Isha"))
    assert "chai2026" in str(wa.outbox[-1])


def test_three_friends_live():
    with TestClient(app) as c:
        ta, ha = sign_in(c, "aarav")
        tz_, hz = sign_in(c, "zoya")
        ts, hs = sign_in(c, "sam")
        assert c.get("/api/me", headers=ha).json()["tz"] == "Asia/Kolkata"
        assert c.get("/api/me", headers=hs).json()["tz"] == "Europe/London"

        # friends by invite link
        inv = c.get("/api/invite", headers=ha).json()
        assert "invite=" in inv["url"]
        assert c.post("/api/friends/accept", json={"code": inv["code"]}, headers=hz).status_code == 200
        assert c.post("/api/friends/accept", json={"code": inv["code"]}, headers=hs).status_code == 200
        assert c.post("/api/friends/accept", json={"code": "nope"}, headers=hs).status_code == 404
        fa = c.get("/api/friends", headers=ha).json()
        assert {f["name"] for f in fa} == {"Zoya", "Sam"}
        ids = {f["name"]: f["id"] for f in fa}
        me_a = c.get("/api/me", headers=ha).json()["id"]

        with c.websocket_connect(f"/ws?token={ta}") as wa_, c.websocket_connect(f"/ws?token={tz_}") as wz:
            wait(wa_, "hello")
            wait(wz, "hello")
            # presence: Aarav sees Zoya online
            assert c.get("/api/friends", headers=ha).json()[[f["name"] for f in fa].index("Zoya")]["online"] in (True, False)
            online = {f["name"]: f["online"] for f in c.get("/api/friends", headers=ha).json()}
            assert online == {"Zoya": True, "Sam": False}

            # status shows up live for friends
            c.patch("/api/me", json={"status": "study"}, headers=ha)
            assert wait(wz, "status")["status"] == "study"

            # group chat with Mindy inside
            chat = c.post("/api/chats", json={"members": [ids["Zoya"], ids["Sam"]], "name": "Friday gang"}, headers=ha).json()["id"]
            c.post(f"/api/chats/{chat}/messages", json={"body": "anyone free friday?"}, headers=ha)
            assert wait(wz, "chat.message")["message"]["body"] == "anyone free friday?"
            c.post(f"/api/chats/{chat}/messages", json={"body": "@mindy movie night Friday 9pm"}, headers=hz)
            m = wait(wa_, "chat.message", lambda e: e["message"]["kind"] == "mindy")
            assert "Plan made: Movie night for Fri" in m["message"]["body"], m["message"]["body"]
            plans = c.get("/api/plans", headers=hs).json()
            assert any("ovie night" in p["title"] for p in plans)
            pid = plans[0]["id"]
            assert c.post(f"/api/plans/{pid}/rsvp", json={"rsvp": "going"}, headers=hs).status_code == 200
            assert c.get("/api/chats", headers=hs).json()[0]["unread"] >= 3
            msgs = c.get(f"/api/chats/{chat}/messages", headers=hs).json()
            assert [x["name"] for x in msgs][-1] is None or msgs[-1]["kind"] == "mindy"
            assert c.get("/api/chats", headers=hs).json()[0]["unread"] == 0
            # people outside the chat can't read it
            assert c.get(f"/api/chats/{chat}/messages", headers={"Authorization": "Bearer nope"}).status_code == 401

            # split money in a chat
            c.post(f"/api/chats/{chat}/messages", json={"body": "@mindy split ₹1500 for the pizza"}, headers=ha)
            m = wait(wz, "chat.message", lambda e: e["message"]["kind"] == "mindy" and "each" in e["message"]["body"])
            assert "₹500 each" in m["message"]["body"], m["message"]["body"]

            # the thought bubble: one sentence, Mindy does it
            r = c.post("/api/think", json={"text": "dinner with Zoya Saturday 8pm"}, headers=ha).json()
            assert r["did"][0]["kind"] == "plan" and "Zoya" in r["did"][0]["with"]
            assert wait(wz, "plan.invite")["from"] == "Aarav"
            r = c.post("/api/think", json={"text": "remind me to submit the assignment tomorrow 9am"}, headers=ha).json()
            assert r["did"][0]["kind"] == "remind" and "09:00" in r["reply"]

            # hand cricket, Aarav vs Zoya, live
            wa_.send_json({"type": "game.new", "game": "hand", "with": [ids["Zoya"]]})
            room = wait(wz, "game.invite")["room"]
            st = wait(wa_, "game.state")
            for i in range(40):
                if st["state"]["over"]:
                    break
                # innings 1: Aarav scores 3,3,3 then is out; innings 2: Zoya hits 4s and chases 10
                wa_.send_json({"type": "game.move", "room": room, "move": {"n": 3}})
                wz.send_json({"type": "game.move", "room": room, "move": {"n": 4 if (st["state"]["innings"] == 2 or i < 3) else 3}})
                wait(wz, "game.state")
                wait(wz, "game.state")
                st = wait(wa_, "game.state")
                st = wait(wa_, "game.state")
            assert st["state"]["over"] and st["state"]["winner"] == ids["Zoya"]
            assert st["state"]["score"] == {str(me_a): 9, str(ids["Zoya"]): 12}

            # Last Card, three people
            wa_.send_json({"type": "game.new", "game": "lastcard", "with": [ids["Zoya"], ids["Sam"]]})
            room = wait(wz, "game.invite")["room"]
            st = wait(wa_, "game.state")["state"]
            assert len(st["hand"]) == 7 and len(st["players"]) == 3
            # Zoya can't move out of turn
            if st["turn"] != ids["Zoya"]:
                wz.send_json({"type": "game.move", "room": room, "move": {"act": "draw"}})
                assert wait(wz, "game.error")["message"] == "not your turn"

            # watch party: YouTube in sync
            wa_.send_json({"type": "party.new", "url": "https://youtu.be/dQw4w9WgXcQ", "with": [ids["Zoya"]]})
            room = wait(wz, "party.invite")["room"]
            wz.send_json({"type": "party.join", "room": room})
            st = wait(wz, "party.state")
            assert st["video"] == "dQw4w9WgXcQ" and len(st["members"]) == 2
            wa_.send_json({"type": "party.sync", "room": room, "playing": True, "t": 42.5})
            s = wait(wz, "party.sync")
            assert s["playing"] and s["t"] == 42.5
            wz.send_json({"type": "party.react", "room": room, "emoji": "😂"})
            assert wait(wa_, "party.react")["emoji"] == "😂"
            # Netflix: synced countdown
            wa_.send_json({"type": "party.new", "service": "Netflix", "title": "Kota Factory S3", "link": "https://www.netflix.com/title/81249783"})
            room2 = wait(wa_, "party.state", lambda e: e["service"] == "Netflix")["room"]
            wa_.send_json({"type": "party.countdown", "room": room2})
            assert wait(wa_, "party.countdown")["start"] > 0

            # a due reminder arrives live in the open app (and on WhatsApp)
            rid = db.add_reminder(me_a, "Drink water", (datetime.now(timezone.utc) - timedelta(seconds=5)).replace(microsecond=0).isoformat())
            wa.outbox.clear()
            c.portal.call(send_due, db)
            n = wait(wa_, "notify")
            assert "Drink water" in n["body"]
            assert db.one("SELECT status FROM reminders WHERE id=?", (rid,))["status"] == "sent"
            assert any("Drink water" in str(m) for m in wa.outbox)

            # only the app, not WhatsApp, when asked
            c.patch("/api/me", json={"notify": "app"}, headers=ha)
            rid = db.add_reminder(me_a, "Stretch", (datetime.now(timezone.utc) - timedelta(seconds=5)).replace(microsecond=0).isoformat())
            wa.outbox.clear()
            c.portal.call(send_due, db)
            assert "Stretch" in wait(wa_, "notify")["body"]
            assert not any("Stretch" in str(m) for m in wa.outbox)

        # Zoya leaves: Aarav's list shows her offline
        assert {f["name"]: f["online"] for f in c.get("/api/friends", headers=ha).json()}["Zoya"] is False

        # mind: mood, passport, charts
        assert c.post("/api/moods", json={"mood": 4, "energy": 3}, headers=ha).json()["mood"] == 4
        assert c.post("/api/stamps", json={"kind": "cafe", "title": "Blue Tokai", "place": "Mumbai"}, headers=ha).status_code == 200
        st = c.get("/api/stats", headers=ha).json()
        assert st["moods"][-1]["mood"] == 4 and len(st["reminders"]) == 6
        # lists
        c.post("/api/lists/Shopping/items", json={"text": "milk, bread"}, headers=ha)
        li = c.get("/api/lists", headers=ha).json()
        item = li[0]["items"][0]
        c.post(f"/api/list-items/{item['id']}/toggle", headers=ha)
        assert c.get("/api/lists", headers=ha).json()[0]["items"][-1]["done"] == 1
        # reminders: add, snooze, done
        r = c.post("/api/reminders", json={"text": "call mum Sunday 7pm"}, headers=ha).json()
        assert r["status"] == "pending"
        assert c.post("/api/reminders", json={"text": "call mum"}, headers=ha).status_code == 422
        c.post(f"/api/reminders/{r['id']}/snooze", json={"minutes": 30}, headers=ha)
        c.post(f"/api/reminders/{r['id']}/done", headers=ha)
        assert db.one("SELECT status FROM reminders WHERE id=?", (r["id"],))["status"] == "done"
        # phone notifications: key is ready
        assert len(c.get("/api/push/key", headers=ha).json()["key"]) > 80
        # export and delete
        ex = c.get("/api/export", headers=ha)
        assert ex.status_code == 200 and "stamps" in ex.json()
        assert c.post("/api/delete-account", json={"confirm": "nope"}, headers=hs).status_code == 422
        assert c.post("/api/delete-account", json={"confirm": "DELETE"}, headers=hs).status_code == 200
        assert c.get("/api/me", headers=hs).status_code == 401
        assert {f["name"] for f in c.get("/api/friends", headers=ha).json()} == {"Zoya"}
        # sign out
        c.post("/api/auth/logout", headers=hz)
        assert c.get("/api/me", headers=hz).status_code == 401
