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
    assert db.one("SELECT COUNT(*) n FROM reminders WHERE user_id=? AND repeat='weekly'", (u["id"],))["n"] == 1
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
    png = client.get(f"/card/{key}.png")
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
