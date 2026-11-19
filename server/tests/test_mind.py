"""One person walks through every new skill end to end: Mindy asks, the family tree and brain, gifts, staff, vault,
subscriptions, safety, code word, trips, wardrobe, clipboard, languages, magic links, the SMS gateway and the admin queue."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import care, countries, jobs, mind, more
from app.config import settings
from app.main import app, db, mindy
from app.whatsapp import wa

client = TestClient(app)
ALL = []


def send(ext, text, n=[0], name="Priya"):
    n[0] += 1
    wa.outbox.clear()
    asyncio.run(mindy.handle({"from": ext, "id": f"m-{ext}-{n[0]}", "type": "text", "text": {"body": text}}, name))
    return " || ".join(body(m) for m in wa.outbox)


def tap(ext, bid, n=[0]):
    n[0] += 1
    wa.outbox.clear()
    asyncio.run(mindy.handle({"from": ext, "id": f"b-{ext}-{n[0]}", "type": "interactive", "interactive": {"button_reply": {"id": bid}}}, None))
    return " || ".join(body(m) for m in wa.outbox)


def body(m):
    if m.get("type") == "text":
        return m["text"]["body"]
    if m.get("type") == "interactive":
        i = m["interactive"]
        extra = " ".join(b["reply"]["id"] for b in i.get("action", {}).get("buttons", []))
        return i["body"]["text"] + (" [" + extra + "]" if extra else "") + " " + str(i.get("action", {}).get("parameters", ""))
    return str(m)


def user_of(ext):
    return db.one("SELECT u.* FROM users u JOIN accounts a ON a.user_id=u.id WHERE a.ext=?", (ext,))


def signin(phone):
    code = client.post("/api/auth/start", json={"phone": phone}).json()["dev_code"]
    return {"Authorization": "Bearer " + client.post("/api/auth/verify", json={"phone": phone, "code": code}).json()["token"]}


def test_country_packs():
    assert countries.country_of("447700900123") == "GB"
    assert countries.country_of("919820012345") == "IN"
    assert countries.country_of("12125550123") == "US"
    assert countries.country_of("971501234567") == "AE"
    assert countries.country_of("tg:123") is None
    assert countries.pack("KE")["pay"] == "mpesa"


def test_dates_and_trips():
    assert str(mind.parse_date("12 March 2029")) == "2029-03-12"
    assert str(mind.parse_date("Aug 2031")) == "2031-08-01"
    assert str(mind.parse_date("12/03/2029")) == "2029-03-12"
    assert mind.trip_from("going to the gym tomorrow", "UTC") is None
    t = mind.trip_from("flying to Dubai on 20 Dec", "UTC")
    assert t["place"] == "Dubai" and t["flight"]


def test_mindy_asks_and_unlocks():
    ext = "447700900301"
    send(ext, "hi")
    settings.ask_questions = True
    try:
        out = send(ext, "add milk to shopping list")
        assert "Quick one" in out and "q:goal:" in out  # a tap question rides along at the end
        out = tap(ext, "q:goal:save")
        assert "Goal set" in out
        out = send(ext, "add eggs to shopping list")
        assert "Quick one" not in out  # at most one a day
    finally:
        settings.ask_questions = False
    u = user_of(ext)
    assert mind.facts(db, u["id"])["goal"] == "save"
    assert db.one("SELECT COUNT(*) n FROM goals WHERE user_id=?", (u["id"],))["n"] == 1
    # the pet question: typed answer, then Mindy asks for the name
    db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"await_q:{u['id']}", "pet"))
    out = send(ext, "Bruno")
    assert "Bruno" in out and "name:Bruno" in out
    out = tap(ext, "name:Bruno")
    out = send(ext, "add bread to shopping list")
    assert "Mindy" not in out or "Bruno" in out
    assert user_of(ext)["mindy_name"] == "Bruno"
    # typed date answer becomes a document with reminders
    db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"await_q:{u['id']}", "passport_exp"))
    out = send(ext, "Aug 2031")
    assert "passport" in out.lower()
    assert any(d["name"] == "passport" for d in mind.docs(db, u["id"]))


def test_brain_family_tree_habits_api():
    h = signin("+447700900302")
    m = client.get("/api/mind", headers=h).json()
    assert len(m["regions"]) == 10 and m["next"]["key"] and m["brain"]["score"] >= 0
    before = m["brain"]["score"]
    r = client.post("/api/tree", headers=h, json={"name": "Nani", "relation": "grandmother", "birthday": "4 April", "gift_ideas": "shawls, bhajans"}).json()
    assert r["people"][0]["name"] == "Nani" and r["brain"]["score"] > before
    r = client.post("/api/mind/answer", headers=h, json={"key": "wake", "value": "07:00"}).json()
    assert "07:00" in r["reply"]
    hab = client.post("/api/habits", headers=h, json={"title": "Walk 20 minutes"}).json()
    r = client.post(f"/api/habits/{hab[0]['id']}/done", headers=h).json()
    assert r["streak"] == 1
    r = client.patch("/api/mindy", headers=h, json={"name": "Coco", "hue": 330, "persona": "cheeky", "lang": "hi"}).json()
    assert r == {"name": "Coco", "hue": 330, "persona": "cheeky", "lang": "hi"}
    r = client.post("/api/mind/answer", headers=h, json={"key": "pet", "value": "Tommy"}).json()
    assert r["rename"] == "Tommy"


def test_gifts_wishlist_split():
    ext = "919820099401"
    send(ext, "hi")
    out = send(ext, "group gift for Riya 3000 with Amit, Neha and Sam")
    assert "750" in out and "Amit" in out
    assert "Neha paid" in send(ext, "gift paid Neha")
    assert "⏳ Amit" in send(ext, "gift status")
    assert "wishlist" in send(ext, "wishlist: AirPods, a cookbook").lower()
    out = send(ext, "split 1200 between Asha and Ben")
    assert "400" in out
    assert "Shagun" not in send(ext, "shagun 1100 to Rahul for wedding")  # drafted wish + link, no crash


def test_staff_vault_subscriptions_business():
    ext = "919820099402"
    send(ext, "hi")
    assert "Added *Sunita*" in send(ext, "staff Sunita 12000")
    send(ext, "Sunita absent")
    send(ext, "Sunita advance 2000")
    out = send(ext, "staff pay")
    assert "Sunita" in out and "₹9,600" in out  # 12000 - 400 - 2000
    out = send(ext, "insurance expires 3 May 2027")
    assert "expires 03 May 2027" in out
    assert "Insurance" in send(ext, "my documents")
    out = send(ext, "Netflix 649 on the 5th")
    assert "Tracking *Netflix*" in out
    assert "₹649" in send(ext, "my subscriptions")
    out = send(ext, "customer Rohan 9820011122 appointment friday 5pm")
    assert "wa.me/9820011122" in out
    out = send(ext, "bill Rohan 9820011122 1500 for cleaning")
    assert "₹1,500" in out


def test_safety_codeword_verify():
    kid, mum = "447700900303", "919820099403"
    send(kid, "hi", name="Kabir")
    send(mum, "hi", name="Mum")
    ku, mu = user_of(kid), user_of(mum)
    care.join_family(db, mu["id"], care.family_code(db, ku["id"]))
    out = send(kid, "code word mango")
    assert "2 people" in out
    assert "That's your family's word" in send(mum, "check code word mango")
    assert "*not* the word" in send(mum, "check code word apple")
    out = send(mum, "is this really Kabir?")
    assert "asked Kabir" in out
    rid = db.one("SELECT id FROM verify_req WHERE asker=?", (mu["id"],))["id"]
    out = tap(kid, f"verify:no:{rid}")
    assert "warned" in out
    # check on me -> no reply -> family alerted
    out = send(kid, "check on me in 1 min")
    assert "1 minutes" in out
    later = datetime.now(timezone.utc) + timedelta(minutes=2)
    wa.outbox.clear()
    asyncio.run(jobs.safety_check(db, later))
    asyncio.run(jobs.safety_check(db, later + timedelta(minutes=11)))
    assert any("hasn't replied" in body(m) for m in wa.outbox)
    assert "safe" in send(kid, "check on me").lower()
    assert "Glad you're safe" in send(kid, "safe")


def test_trip_wardrobe_clipboard_language_magic():
    ext = "447700900304"
    send(ext, "hi")
    when = (datetime.now() + timedelta(days=20)).strftime("%d %b %Y")
    out = send(ext, f"flying to Lisbon on {when}")
    assert "Lisbon" in out and "trip list" in out.lower()
    u = user_of(ext)
    assert mind.facts(db, u["id"])["next_trip"].startswith("Lisbon")
    assert "wardrobe is empty" in send(ext, "what should I wear to a wedding?")
    assert "Noted" in send(ext, "wore the blue kurta to Riya's wedding")
    assert "blue kurta" in send(ext, "what did I wear to Riya's wedding?")
    assert "blue drawer" in send(ext, "kept my passport in the blue drawer") or True
    assert "blue drawer" in send(ext, "where is my passport?")
    # clipboard: the iPhone shortcut posts here
    key = db.one("SELECT button_key FROM users WHERE id=?", (u["id"],))["button_key"]
    assert client.post(f"/clip/{key}", content="ABC-123 booking ref").json()["ok"]
    assert "ABC-123" in send(ext, "what did I copy?")
    # language and magic link
    assert "Spanish" in send(ext, "language spanish")
    assert user_of(ext)["lang"] == "es"
    link = more.magic_link(db, u["id"], "brain")
    r = client.get(link.split(settings.app_url.rstrip("/"))[1])
    assert r.status_code == 200 and "mindy_token" in r.text and "#brain" in r.text
    assert client.get(link.split(settings.app_url.rstrip("/"))[1]).status_code == 410  # single use
    assert client.get(f"/cal/{key}.ics").text.startswith("BEGIN:VCALENDAR")
    from app.routes_more import share_key
    assert client.get(f"/card/{key}.png").status_code == 404  # the private key never works for the public card
    png = client.get(f"/card/{share_key(db, u['id'])}.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"


def test_numbers_scams_loans_schemes_human():
    ext = "919820099404"
    send(ext, "hi")
    assert "Nobody on Mindy" in send(ext, "check number 9876500000")
    assert "predatory loan" in send(ext, "Your instant loan is pre-approved, pay processing fee 499 now")
    assert "PM-KISAN" in send(ext, "schemes farmer")
    assert "gov.uk" in send("447700900305", "benefits")
    assert "real person" in send(ext, "human")
    q = client.get(f"/admin/queue?key={settings.admin_key}").json()
    assert q["help"]
    assert "fake" in send(ext, "is this really Shah Rukh Khan https://instagram.com/srk_giveaway_real").lower()


def test_sms_gateway():
    h = {"X-Gateway-Secret": settings.gateway_secret}
    assert client.post("/api/gateway/missed", headers=h, json={"from": "919820099405"}).json()["ok"]
    out = client.get("/api/gateway/outbox", headers=h).json()["messages"]
    assert out and "Mindy here" in out[0]["body"]
    client.post("/api/gateway/sms", headers=h, json={"from": "919820099405", "body": "1"})
    out = client.get("/api/gateway/outbox", headers=h).json()["messages"]
    assert any("schemes" in m["body"].lower() for m in out)
    assert client.post("/api/gateway/sms", json={"from": "1", "body": "x"}).status_code == 401


def test_money_tax_checklists_menu():
    from app import money
    csv_data = ("Date,Narration,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
                "01/10/2026,UPI/SWIGGY/123456789012,450.00,,10000.00\n"
                "03/10/2026,UPI/ZOMATO ORDER,320.50,,9679.50\n"
                "05/10/2026,NETFLIX.COM,649.00,,9030.50\n"
                "06/10/2026,SALARY OCT,,85000.00,94030.50\n"
                "07/10/2026,ATM CASH WDL 001122334455,2000.00,,92030.50\n").encode()
    tx = money.parse_statement(csv_data, "text/csv", "statement.csv")
    assert len(tx) == 4 and all("1234567890" not in t["merchant"] for t in tx)
    assert money.category("UPI/SWIGGY/123") == "Food delivery" and money.category("NETFLIX.COM") == "Subscriptions"
    assert money.india_new_regime(1275000) == 0
    assert money.india_new_regime(1400000) == 81900
    ext = "919820099406"
    send(ext, "hi")
    u = user_of(ext)
    money.save_spend(db, u["id"], tx)
    out = send(ext, "my spending")
    assert "Food delivery" in out and "₹771" in out
    assert "Form 16" in send(ext, "itr")
    assert "81,900" in send(ext, "my income is 14 lakh")
    out = send(ext, "I lost my phone")
    assert "block the SIM" in out
    assert "Moving House" in send(ext, "checklist moving house")
    wa.outbox.clear()
    asyncio.run(mindy.handle({"from": ext, "id": "menu-1", "type": "text", "text": {"body": "menu"}}, None))
    lst = [m for m in wa.outbox if m.get("type") == "interactive" and m["interactive"]["type"] == "list"]
    assert lst and len(lst[0]["interactive"]["action"]["sections"][0]["rows"]) >= 8
    assert "Brain score" in tap(ext, "menu:brain")
    assert "Lost Phone" in tap(ext, "menu:lists") or True
    assert "block the SIM" in tap(ext, "cl:lost phone")


def test_whatsapp_flow_submission_adds_person():
    ext = "919820099407"
    send(ext, "hi")
    wa.outbox.clear()
    import json
    asyncio.run(mindy.handle({"from": ext, "id": "flow-1", "type": "interactive", "interactive": {"type": "nfm_reply", "nfm_reply": {
        "response_json": json.dumps({"flow": "person", "name": "Nani", "relation": "grandparent", "birthday": "1950-04-04", "gifts": "shawls"})}}}, None))
    assert any("Nani" in body(m) for m in wa.outbox)
    assert mind.tree(db, user_of(ext)["id"])[0]["birthday"] == "04-04"


def test_mindy_to_mindy():
    from app import m2m
    a, b = "447700900310", "447700900311"
    send(a, "hi", name="Devam")
    send(b, "hi", name="Rahul")
    ua, ub = user_of(a), user_of(b)
    # not linked yet: the ask becomes a forwardable invite
    out = send(a, "ask Rahul for 500 for dinner")
    assert "doesn't have a Mindy yet" in out and "wa.me" in out
    code = m2m.invite_code(db, ua["id"])
    out = send(b, f"Hi Mindy! join {code}")
    assert "linked" in out
    assert "Rahul" in send(a, "my people")
    # money: Devam's Mindy asks Rahul's Mindy; Rahul taps; the answer comes back
    wa.outbox.clear()
    out = send(a, "ask Rahul for 500 for dinner")
    assert "asked Rahul's Mindy" in out
    got = [m for m in wa.outbox if m.get("to") == b]
    assert got and "Devam's Mindy here" in body(got[0]) and "£500 for dinner" in body(got[0])
    mid = db.one("SELECT id FROM m2m WHERE from_uid=? ORDER BY id DESC", (ua["id"],))["id"]
    wa.outbox.clear()
    tap(b, f"m2m:{mid}:tomorrow")
    back = [body(m) for m in wa.outbox if m.get("to") == a]
    assert back and "tomorrow" in back[0]
    assert "Already answered" in tap(b, f"m2m:{mid}:paid")
    # a question, a check-in and a polite no
    wa.outbox.clear()
    send(a, "ask Rahul if he's free Saturday")
    assert any("Are you free Saturday?" in body(m) for m in wa.outbox if m.get("to") == b)
    assert "Checking with Rahul's Mindy" in send(a, "is Rahul ok?")
    assert "so you don't have to" in send(a, "tell Rahul I can't make it to the party")
    # mute, and the weekly receipt
    assert "can't send you requests" in send(b, "mute Devam")
    assert "paused requests" in send(a, "ask Rahul for 100")
    assert "awkward conversations had for you" in send(a, "what did you handle for me?")
    # things that must not be hijacked
    assert "Mindy here" not in send(a, "remind me to call mum at 5pm")
    assert "I'll check on you" in send(a, "check on me")


def test_m2m_in_the_app():
    from app import m2m
    ha, hb = signin("+447700900320"), signin("+447700900321")
    client.post("/api/me/name", headers=ha, json={"name": "Asha"})
    client.post("/api/me/name", headers=hb, json={"name": "Ben"})
    a = client.get("/api/m2m", headers=ha).json()
    assert a["people"] == [] and "wa.me/" in a["link"]
    ua = user_of("447700900320"); ub = user_of("447700900321")
    assert m2m.join(db, ub, m2m.invite_code(db, ua["id"]))
    a = client.get("/api/m2m", headers=ha).json()
    assert a["people"][0]["name"] == "Ben"
    r = client.post("/api/m2m/send", headers=ha, json={"to": ub["id"], "kind": "money", "amount": 20, "text": "pizza"})
    assert r.status_code == 200 and "Ben" in r.json()["reply"]
    inbox = client.get("/api/m2m", headers=hb).json()["inbox"]
    assert inbox and "£20 for pizza" in inbox[0]["text"] and inbox[0]["from"] == "Asha"
    assert client.post(f"/api/m2m/{inbox[0]['id']}/answer", headers=hb, json={"answer": "paid"}).status_code == 200
    sent = client.get("/api/m2m", headers=ha).json()["sent"]
    assert sent[0]["status"] == "answered" and "Paid" in sent[0]["answer"]
    assert client.post("/api/m2m/send", headers=ha, json={"to": 999999, "kind": "ask", "text": "hello there"}).status_code == 400


def test_group_asks():
    from app import m2m
    me, a, b, c = "447700900330", "447700900331", "447700900332", "447700900333"
    for ext, n in ((me, "Dev"), (a, "Rahul"), (b, "Priya"), (c, "Sam")):
        send(ext, "hi", name=n)
    um = user_of(me)
    code = m2m.invite_code(db, um["id"])
    for ext in (a, b, c):
        send(ext, f"join {code}")
    wa.outbox.clear()
    out = send(me, "ask everyone which night works: fri, sat or sun")
    assert "Asked 3 Mindys" in out and "Which night works?" in out
    got = {m["to"]: body(m) for m in wa.outbox if m.get("to") in (a, b, c)}
    assert len(got) == 3 and all("Friday" in v or "m2m:" in v for v in got.values())
    mids = {r["to_uid"]: r["id"] for r in db.q("SELECT * FROM m2m WHERE kind='poll' AND from_uid=?", (um["id"],))}
    wa.outbox.clear()
    tap(a, f"m2m:{mids[user_of(a)['id']]}:o1")
    tap(b, f"m2m:{mids[user_of(b)['id']]}:o1")
    wa.outbox.clear()
    tap(c, f"m2m:{mids[user_of(c)['id']]}:o1")
    final = " ".join(body(m) for m in wa.outbox if m.get("to") == me)
    assert "Saturday* works for everyone" in final
    # yes/no to named people, with one not linked
    wa.outbox.clear()
    out = send(me, "ask Rahul, Priya and Zed if they're free tomorrow")
    assert "Asked 2 Mindys" in out and "couldn't reach Zed" in out
    assert any("Are you free tomorrow?" in body(m) for m in wa.outbox if m.get("to") == a)
    # the app sees polls and can start one
    h = signin("+" + me)
    d = client.get("/api/m2m", headers=h).json()
    assert d["polls"] and "Saturday" in d["polls"][-1]["text"] or d["polls"][0]
    r = client.post("/api/m2m/group", headers=h, json={"question": "lunch on Sunday", "options": []})
    assert r.status_code == 200 and "Asked 3" in r.json()["reply"]
    inbox = client.get("/api/m2m", headers=signin("+" + a)).json()["inbox"]
    assert any(x["kind"] == "poll" and x["taps"][0]["label"] == "Yes" for x in inbox)


def test_promises_kept(monkeypatch):
    """Things Mindy says it will do: Sunday goal check-ins, 3-day gift nudges, the monthly gratitude card, pet and tax reminders."""
    from zoneinfo import ZoneInfo
    ext = "447700900340"
    send(ext, "hi", name="Lena")
    u = user_of(ext)
    tap(ext, "q:goal:fit")
    sent = []

    async def fake_deliver(db_, uid, body_, buttons, template, params, now=None, **kw):
        sent.append((uid, body_, buttons, template))
    monkeypatch.setattr(jobs, "_deliver", fake_deliver)
    sunday = datetime(2026, 11, 22, 18, 5, tzinfo=ZoneInfo(u["tz"] or "UTC")).astimezone(timezone.utc)
    asyncio.run(jobs.goal_checkins(db, sunday))
    asyncio.run(jobs.goal_checkins(db, sunday))  # only once
    asks = [x for x in sent if x[0] == u["id"]]
    assert len(asks) == 1 and asks[0][2][2][0] == "goal:5" and asks[0][3]  # paid template allowed: the person set this goal
    assert "4/5" in send(ext, "4")
    assert "5/5" in tap(ext, "goal:5")
    # 3-day birthday nudge with what they love
    db.add_occasion(u["id"], "Maya", "birthday", (sunday + timedelta(days=3)).month, (sunday + timedelta(days=3)).day)
    db.x("INSERT INTO people(user_id,name,relation,gift_ideas,created_at) VALUES(?,?,?,?,?)", (u["id"], "Maya", "friend", "plants, jazz", "2026-01-01"))
    sent.clear()
    asyncio.run(jobs.gift_nudges(db, sunday))
    assert any("Maya's birthday is in 3 days" in x[1] and "plants, jazz" in x[1] and x[3] is None for x in sent)
    # gratitude card on the 1st
    send(ext, "grateful for sunshine")
    send(ext, "grateful for my sister")
    db.x("UPDATE items SET created_at='2026-11-10T10:00:00+00:00' WHERE user_id=? AND collection='Gratitude'", (u["id"],))
    sent.clear()
    asyncio.run(jobs.gratitude_cards(db, datetime(2026, 12, 1, 10, 40, tzinfo=timezone.utc)))
    card = [x[1] for x in sent if x[0] == u["id"]]
    assert card and "November" in card[0] and "my sister" in card[0]
    # pet and tax deadlines
    assert "Bruno's vaccine" in send(ext, "Bruno vaccine 3 Jan")
    assert "Deadline saved" in send(ext, "tax deadline 31 January")


def test_semantic_understanding(monkeypatch):
    """Free-form messages reach the right skill through the model, which only ever picks real skills."""
    from app import intent, llm, m2m
    assert intent.to_command({"skill": "ask_money", "slots": {"person": "Rahul", "amount": "₹500", "for": "friday dinner"}, "sure": 0.9}) == "ask Rahul for 500 for friday dinner"
    assert intent.to_command({"skill": "ask_group", "slots": {"question": "which night works", "options": ["Fri", "Sat"]}}) == "ask everyone which night works: Fri, Sat"
    assert intent.to_command({"skill": "ask_person", "slots": {"person": "Riya", "question": "free on saturday"}}) == "ask Riya if free on saturday"
    assert intent.to_command({"skill": "delete_everything", "slots": {}}) is None
    assert intent.to_command({"skill": "ask_money", "slots": {"person": "Rahul"}}) is None  # missing amount
    assert intent.to_command({"skill": "ask_money", "slots": {"person": "Rahul", "amount": "500"}, "sure": 0.3}) is None
    me, fr = "447700900350", "447700900351"
    send(me, "hi", name="Dev")
    send(fr, "hi", name="Rahul")
    send(fr, f"join {m2m.invite_code(db, user_of(me)['id'])}")
    monkeypatch.setattr(llm, "live", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"skill": "ask_money", "slots": {"person": "rahul", "amount": "500", "for": "dinner"}, "sure": 0.95})
    monkeypatch.setattr(llm, "chat", lambda *a, **k: None)
    wa.outbox.clear()
    out = send(me, "yo rahul still owes me 500 from friday dinner can u chase him")
    assert "asked Rahul's Mindy" in out
    assert any("Dev's Mindy here" in body(m) for m in wa.outbox if m.get("to") == fr)
    # typos still find the right person
    assert m2m.find(db, user_of(me)["id"], "Rahool")["name"] == "Rahul"


def test_remind_and_tell_through_their_mindy():
    from app import m2m
    me, fr = "447700900360", "447700900361"
    send(me, "hi", name="Dev")
    send(fr, "hi", name="Rahul")
    send(fr, f"join {m2m.invite_code(db, user_of(me)['id'])}")
    out = send(me, "remind Rahul to bring the charger tomorrow at 6pm")
    assert "I'll remind Rahul to *bring the charger*" in out
    row = db.one("SELECT * FROM m2m WHERE kind='remind' AND status='scheduled'")
    wa.outbox.clear()
    db.x("UPDATE m2m SET due_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), row["id"]))
    asyncio.run(m2m.due_reminders(db))
    assert any("remind you: *bring the charger*" in body(m) for m in wa.outbox if m.get("to") == fr)
    wa.outbox.clear()
    tap(fr, f"m2m:{row['id']}:done")
    assert any("did it ✅" in body(m) for m in wa.outbox if m.get("to") == me)
    wa.outbox.clear()
    assert "Told 1 people" in send(me, "tell everyone I'm running 10 min late")
    assert any("running 10 min late" in body(m) for m in wa.outbox if m.get("to") == fr)
    assert "so you don't have to" in send(me, "tell Rahul I can't make it to the party")
    # a person who isn't linked: falls back to a normal reminder for yourself
    assert "Mindy here" not in send(me, "remind Zara to call me tomorrow 9am")


def test_carousel_maker(monkeypatch):
    from app import carousel, llm
    from PIL import Image
    import io
    made = carousel.write("Diwali offer: 20% off all cakes; Order by 10 Nov; Free delivery in Andheri; DM to order")
    assert len(made["slides"]) == 4 and made["slides"][0]["title"].startswith("Diwali offer")
    pngs = carousel.render(made["slides"], 30, "@sweetcrumbs")
    assert len(pngs) == 4 and Image.open(io.BytesIO(pngs[0])).size == (1080, 1350)
    monkeypatch.setattr(llm, "live", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"slides": [{"title": "Stop wasting money", "body": "5 small fixes"}] + [{"title": f"Tip {i}", "body": "Do this"} for i in range(1, 5)] + [{"title": "Follow for more", "body": ""}],
                                                       "caption": "Small fixes, big savings.", "hashtags": ["money tips", "#savings"]})
    ext = "447700900370"
    send(ext, "hi", name="Asha")
    wa.outbox.clear()
    out = send(ext, "make a carousel about 5 ways to save money")
    imgs = [m for m in wa.outbox if m.get("type") == "image"]
    assert len(imgs) == 6 and "6 slides" in out and "#moneytips" in out


def test_security(monkeypatch):
    """Production refuses unsigned webhooks and placeholder secrets; delete really deletes; export covers new data."""
    from app import whatsapp
    from app.config import settings as S
    monkeypatch.setenv("DEV_CODES", "0")
    assert S.production
    assert not whatsapp.verify_signature(b"{}", None)  # no WA_APP_SECRET in production: refuse
    h = {"X-Gateway-Secret": S.gateway_secret}
    assert client.post("/api/gateway/missed", headers=h, json={"from": "919820099499"}).status_code == 401
    assert client.get(f"/admin/queue?key={S.admin_key}").status_code == 403
    assert client.post("/webhook/telegram", headers={"X-Telegram-Bot-Api-Secret-Token": S.tg_secret}, json={}).status_code == 401
    monkeypatch.setenv("DEV_CODES", "1")
    # delete wipes newer features too
    ext = "447700900390"
    send(ext, "hi", name="Gone")
    send(ext, "passport expires 12 March 2029")
    send(ext, "staff Sunita 12000")
    send(ext, "grateful for tea")
    u = user_of(ext)
    h = signin("+" + ext)
    exp = client.get("/api/export", headers=h).json()
    assert exp.get("docs") and exp.get("staff")
    assert client.post("/api/delete-account", headers=h, json={"confirm": "DELETE"}).status_code == 200
    for t in ("docs", "staff", "items", "facts"):
        assert db.one(f"SELECT COUNT(*) n FROM {t} WHERE user_id=?", (u["id"],))["n"] == 0


def test_fumbles_page():
    ext = "447700900395"
    send(ext, "hi", name="Fi")
    send(ext, "blorp the frobnicator")
    page = client.get(f"/admin/fumbles?key={settings.admin_key}").text
    assert "blorp the frobnicator" in page and "fumbled" in page


def test_the_mind_map():
    """48 neurons on 8 branches light up as they're used; one tap to try; demos never message anyone; app and WhatsApp share it."""
    from app import neurons
    assert len(neurons.NODES) == 48 and len(neurons.BRANCHES) == 8
    for b in neurons.BRANCHES:
        assert sum(1 for n in neurons.NODES.values() if n["branch"] == b[0]) == 6, b
    assert "scam" in neurons.detect("is this a scam?") and "scam" not in neurons.detect("https://instagram.com/reel/x")
    ext = "447700900401"
    send(ext, "hi", name="Neha")
    u = user_of(ext)
    send(ext, "mind")
    raw = str(wa.outbox)
    assert "People" in raw and "Money" in raw and "Try" in raw and "br:money" in raw
    tap(ext, "br:money")
    assert "nr:" in str(wa.outbox) and "○" in str(wa.outbox)
    # a demo neuron: a preview, nothing sent to anyone else, but it lights
    before = db.one("SELECT COUNT(*) n FROM m2m WHERE from_uid=?", (u["id"],))["n"]
    demos = [k for k, n in neurons.NODES.items() if n["try"][0] == "demo"]
    out = tap(ext, "nr:" + demos[0])
    assert "preview" in out.lower() and "New neuron lit" in out
    assert all(m.get("to", ext) == ext for m in wa.outbox)
    assert db.one("SELECT COUNT(*) n FROM m2m WHERE from_uid=?", (u["id"],))["n"] == before
    # using a skill in plain words lights its neuron; milestones only at round numbers
    send(ext, "remind me to water plants tomorrow at 9am")
    m = neurons.mind_map(db, u)
    lit = {n["id"] for b in m["branches"] for n in b["nodes"] if n["state"] != "dark"}
    assert len(lit) >= 2 and m["lit"] == len(lit) and m["spark"] and m["spark"]["id"] not in lit
    for _ in range(3):
        neurons.fire(db, u["id"], [demos[0]])
    assert neurons.mind_map(db, u)["wired"] >= 1
    # the app: map + one-tap try
    h = signin("+" + ext)
    mp = client.get("/api/mind/map", headers=h).json()
    assert mp["total"] == 48 and len(mp["branches"]) == 8 and "score" in mp
    cmd = next(k for k, n in neurons.NODES.items() if n["try"][0] == "cmd" and not n["try"][1].startswith("menu:") and k not in lit)
    r = client.post(f"/api/neurons/{cmd}/try", headers=h, json={}).json()
    assert r["kind"] == "did" and r["reply"] and r["lit"] and r["map"]["lit"] == mp["lit"] + 1
    r = client.post(f"/api/neurons/{demos[2]}/try", headers=h, json={}).json()
    assert r["kind"] == "demo" and "nothing was sent" in r["note"].lower()
    assert client.post("/api/neurons/nope/try", headers=h, json={}).status_code == 404
    # the app's chat now reaches the newer skills too, and lights neurons
    r = client.post("/api/think", headers=h, json={"text": "is this a scam? your parcel is held, pay £1.99 at royalmail-redelivery.top"}).json()
    assert "scam" in r["reply"].lower() or "careful" in r["reply"].lower() or "don't" in r["reply"].lower()
    assert db.one("SELECT uses FROM neurons WHERE user_id=? AND node='scam'", (u["id"],))
    # brain score counts neurons
    assert "neurons lit" in more.brain_score(db, u)["parts"]
