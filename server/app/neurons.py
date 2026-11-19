"""Your mind, as a map. Mindy's abilities are 48 neurons on 8 branches. Every neuron is dark (never tried), sparked (tried)
or wired (used 3+ times). One tap on a dark neuron tries it right away, with the person's own data and no typing;
neurons that would message someone else show a preview instead, so nothing reaches anyone without the person meaning it.

The same map drives the app's home screen, the WhatsApp menu, the Brain Score and the daily "spark"."""
import random
import re
from datetime import date, datetime, timezone

from .db import DB, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS neurons(user_id INTEGER, node TEXT, uses INTEGER DEFAULT 0, first_at TEXT, last_at TEXT, PRIMARY KEY(user_id, node));
"""

BRANCHES = [
    ("people", "People", "🤝", "Your Mindy talks to theirs"),
    ("memory", "Memory", "🧠", "Never lose a thing again"),
    ("time", "Time", "⏰", "The right nudge at the right moment"),
    ("money", "Money", "💸", "Who owes what, where it went"),
    ("family", "Family", "💚", "Look after the people you love"),
    ("safety", "Safety", "🛡️", "Scams stop at the door"),
    ("papers", "Papers", "🗂️", "Life admin, handled"),
    ("create", "Create", "🎨", "Make things in seconds"),
]

# id, branch, emoji, name, one line, detector (regex on what the person wrote), try: ("cmd", text) or ("demo", [(who, text), ...])
N = [
    ("ask_money", "people", "💸", "Get money back", "Mindy asks their Mindy, politely", r"^ask \w+.* for (₹|rs|£|\$)?\d",
     ("demo", [("you", "ask {friend} for 500 for dinner"), ("their", "💸 {me}'s Mindy here. A gentle nudge: ₹500 for dinner. [✅ Paid] [⏰ Tomorrow]"), ("mindy", "{friend} says it's paid ✅")])),
    ("group_ask", "people", "🗳️", "Ask everyone", "One question, everyone's Mindy, one answer", r"^ask (everyone|everybody|all|\w+, )",
     ("demo", [("you", "ask everyone which night works: fri, sat or sun"), ("mindy", "🎉 Saturday works for everyone!")])),
    ("remind_them", "people", "📌", "Remind them for you", "Lands on their phone; you hear when it's done", r"^remind (?!me\b)\w+ to ",
     ("demo", [("you", "remind {friend} to bring the charger at 6pm"), ("their", "⏰ Reminder from {me}: bring the charger [✅ Done]"), ("mindy", "{friend} did it ✅")])),
    ("tell_all", "people", "📣", "Tell everyone", "Running late? One line, everyone knows", r"^tell (everyone|everybody|all)\b",
     ("demo", [("you", "tell everyone I'm running 10 min late"), ("mindy", "💬 Told 4 people.")])),
    ("check_on", "people", "💚", "Is Mum okay?", "Her Mindy asks her; she taps once", r"^(check on|is \w+ (ok|okay|fine|safe|home))",
     ("demo", [("you", "is Mum ok?"), ("their", "💚 Your son wants to know you're OK [💚 All good] [📞 Call me]"), ("mindy", "Mum tapped “All good” at 10:02 💚")])),
    ("link", "people", "🔗", "Link your people", "Send one link; your Mindys can talk", r"^(my link|invite|join \w+)", ("cmd", "my link")),

    ("save", "memory", "📌", "Save anything", "Notes, links, numbers: just send them", r"^(note|idea|save|remember that)\b", ("cmd", "note: the first thing I saved in my mind 🧠")),
    ("find", "memory", "🔎", "Find it in plain words", "Ask like you'd ask a friend", r"^(what did i|find|where('s| is) my|show me)", ("cmd", "what did I save?")),
    ("kept", "memory", "📍", "Where did I keep it?", "Passport, spare keys, warranty card", r"^(i )?(kept|put|left|placed) ", ("cmd", "kept my spare keys in the kitchen drawer")),
    ("lists", "memory", "🛒", "Shared lists", "Shopping, packing, to-dos", r"^add .+ to .*list|list:", ("cmd", "add milk, eggs to shopping list")),
    ("tldr", "memory", "📃", "TL;DR anything", "Long forwards become three lines", r"^.{600,}",
     ("demo", [("you", "(forwards a 40-line school notice)"), ("mindy", "📌 TL;DR\n• Sports day Friday 9am\n• Wear house colours\n• Bring water bottle")])),
    ("clip", "memory", "📋", "Clipboard that remembers", "Double-tap your iPhone; it's saved", r"^(clipboard|what did i copy)", ("cmd", "clipboard setup")),

    ("remind", "time", "⏰", "Reminders that land", "Say it however you like, any language", r"^remind me\b|yaad dila", ("cmd", "remind me in 1 hour to drink water")),
    ("habit", "time", "🔥", "Habits and streaks", "Reply 'done' and keep the streak", r"^(habit|new habit)\b|^done$", ("cmd", "habit: drink 8 glasses of water")),
    ("brief", "time", "☀️", "Morning brief", "Your day in one message at wake-up", r"^(morning brief|brief)\b",
     ("demo", [("mindy", "☀️ Good morning!\n⏰ 10:00 Dentist\n🎂 Riya's birthday in 3 days\n🔥 Walk: 6-day streak")])),
    ("trip", "time", "✈️", "Trips plan themselves", "A ticket becomes a checklist", r"\b(fly|flying|flight|trip|train) .*\bto [A-Z]",
     ("demo", [("you", "flying to Dubai on 20 Dec"), ("mindy", "✈️ Dubai, Sat 20 Dec. Trip list made: passport ✓, charger, travel card… Check-in reminder set.")])),
    ("capsule", "time", "💌", "Letter to future you", "Opens in a year. Not even Mindy peeks", r"^(time capsule|future me|note to future me)", ("cmd", "time capsule: dear future me, I hope you're proud of this year")),
    ("goal", "time", "🎯", "A goal with check-ins", "One tap every Sunday", r"^(goal|my goal)\b", ("cmd", "brain score")),

    ("khata", "money", "📒", "Who owes what", "Say it; Mindy keeps the book", r"\bowes? (me )?\d|^(paid|lent) \w+ \d|udhaar|diye",
     ("demo", [("you", "Ramesh owes me 500"), ("mindy", "📒 Noted. Ramesh owes you ₹500. Say 'remind Ramesh' to nudge.")])),
    ("split", "money", "🧮", "Split anything", "Everyone's share, with pay links", r"^split ", ("cmd", "split 1200 between 3")),
    ("subs", "money", "📺", "Subscription radar", "Pinged before it renews", r"^(\w+ \d+ on the|my subscriptions|subscription)",
     ("demo", [("you", "Netflix 649 on the 5th"), ("mindy", "📺 Tracking Netflix. I'll ping you 2 days before it renews.")])),
    ("spend", "money", "📊", "Where it went", "Send a statement; get the truth", r"^(my )?(spend|spending)|statement",
     ("demo", [("you", "(sends bank statement)"), ("mindy", "💸 October: ₹38,200 out\n• Food delivery ₹8,400 (+30%)\n• Shopping ₹6,100")])),
    ("gift", "money", "🎁", "Group gifts", "Everyone chips in; Mindy tracks who paid", r"^(group gift|gift pool|gift ideas|wishlist|shagun)",
     ("demo", [("you", "group gift for Riya 3000 with Amit, Neha and Sam"), ("mindy", "🎁 ₹750 each. Neha ✅ Amit ✅ Sam ⏳")])),
    ("tax", "money", "🧾", "Tax season, sorted", "Checklist, estimate, deadline", r"^(itr|tax|self assessment|my income is)", ("cmd", "itr")),

    ("care", "family", "💊", "Medicine reminders", "They tap 'took it'; you know", r"^(care|medicine)",
     ("demo", [("their", "💊 9:00 · BP tablet [✅ Took it]"), ("mindy", "Mum took her 9:00 dose ✅")])),
    ("okday", "family", "🙋", "Daily “I'm OK”", "One tap from them, peace for you", r"^(daily ok|i'?m ok)", ("demo", [("their", "☀️ Are you OK today? [💚 I'm OK]"), ("mindy", "Dad tapped I'm OK at 10:04 💚")])),
    ("tree", "family", "🌳", "Family tree", "Birthdays and gift ideas hang off it", r"^(family tree|tree)\b", ("cmd", "menu:family")),
    ("codeword", "family", "🔐", "Family code word", "AI can copy a voice, not a secret", r"code ?word", ("demo", [("you", "code word mango"), ("mindy", "🔐 Set for 4 family members. Tell them in person.")])),
    ("translate", "family", "🌍", "Speaks their language", "Nani's Gujarati, your English", r"^(language|reply in|speak)\b", ("cmd", "menu:lang")),
    ("birthday", "family", "🎂", "Never miss a birthday", "Gift idea 3 days before", r"birthday", ("demo", [("mindy", "🎁 Riya's birthday is in 3 days. Her wishlist: sketchbook, Lego.")])),

    ("scam", "safety", "🛡️", "Scam check", "Forward anything odd", r"^(scam|is (this|it) (a )?(scam|safe|legit|real)|check this)", ("cmd", "is this safe? Dear customer your KYC expires today, click http://sbi-kyc-update.xyz")),
    ("number", "safety", "📞", "Who's calling?", "Community reports, no contact upload", r"^(check|who is) (number )?\+?\d", ("cmd", "check number 9876500000")),
    ("checkme", "safety", "🫶", "Check on me", "Walking home late? Mindy watches", r"^check on me", ("demo", [("you", "check on me in 30 min"), ("mindy", "🫶 Are you OK? Reply safe."), ("mindy", "(no reply in 10 min → family gets your last location)")])),
    ("loan", "safety", "🚨", "Loan app alarm", "Predatory loans called out", r"\bloan\b", ("cmd", "your instant loan is pre-approved, pay processing fee 499")),
    ("really", "safety", "🔍", "Is it really them?", "The real person answers", r"^is (this|it) really", ("demo", [("you", "someone's calling as my son asking for money"), ("mindy", "🚨 He says it's NOT him. Hang up.")])),
    ("lostphone", "safety", "📵", "Lost phone? Do this", "Block SIM, UPI, banks, in order", r"(lost|stolen).{0,15}phone", ("cmd", "checklist lost phone")),

    ("docs", "papers", "🗂️", "Expiry radar", "Passport, insurance, MOT, PUC", r"expir|valid till|renewal", ("demo", [("you", "passport expires 12 March 2029"), ("mindy", "🗂️ Saved. Reminders 60, 14 and 1 day before.")])),
    ("schemes", "papers", "🏛️", "What you're owed", "Schemes and benefits you qualify for", r"^(schemes?|yojana|benefits)", ("cmd", "schemes")),
    ("checklist", "papers", "✅", "Life checklists", "Moving, new job, new baby…", r"^checklist", ("cmd", "checklist moving house")),
    ("staff", "papers", "🧹", "Staff and salaries", "Advances and days off, done", r"^staff\b", ("demo", [("you", "staff Sunita 12000 · Sunita absent · staff pay"), ("mindy", "🧹 Sunita: ₹11,600 this month")])),
    ("biz", "papers", "🏪", "Customer reminders", "Appointments with pay links", r"^(customer|bill|invoice) ", ("demo", [("you", "customer Priya 98200 11122 appointment friday 5pm"), ("mindy", "🏪 Saved. Tap to send Priya her reminder.")])),
    ("menu", "papers", "☰", "Tap-only menu", "Never type again", r"^menu$", ("cmd", "menu")),

    ("carousel", "create", "🎠", "Instagram carousels", "One line in, designed slides out", r"carousel|slides", ("cmd", "carousel: 3 small habits that changed my year; sleep before 11; walk after dinner; phone out of the bedroom")),
    ("caption", "create", "✍️", "Captions", "For any post, in seconds", r"^caption", ("cmd", "caption for a sunset photo from my balcony")),
    ("reply", "create", "💬", "Help me reply", "To a crush, a boss, a landlord", r"^help me (reply|respond|write)", ("cmd", "help me reply")),
    ("wardrobe", "create", "👗", "What should I wear?", "Picks from your own clothes", r"wear|wardrobe|outfit", ("cmd", "what should I wear today?")),
    ("tryon", "create", "🪞", "Try it on", "You, in that jacket from a screenshot", r"try ?on", ("demo", [("you", "(your photo) + (jacket screenshot) “try on”"), ("mindy", "👀 Here's you in it.")])),
    ("persona", "create", "🐶", "Make Mindy yours", "Name, colour, personality", r"^(call yourself|be (sweet|cheeky|calm)|your colou?r)", ("cmd", "be cheeky")),
]
NODES = {n[0]: {"id": n[0], "branch": n[1], "emoji": n[2], "name": n[3], "why": n[4], "rx": re.compile(n[5], re.I), "try": n[6]} for n in N}
assert len(NODES) == 48, len(NODES)


def init(db: DB):
    with db.lock:
        db.conn.executescript(SCHEMA)
        db.conn.commit()


def detect(text: str) -> list[str]:
    t = (text or "").strip()
    return [k for k, n in NODES.items() if n["rx"].search(t)][:3] if t else []


def fire(db: DB, uid: int, nodes: list[str]) -> list[str]:
    """Counts a use; returns neurons that just changed state (dark->sparked, sparked->wired), for a small celebration."""
    changed = []
    for k in nodes:
        if k not in NODES:
            continue
        row = db.one("SELECT uses FROM neurons WHERE user_id=? AND node=?", (uid, k))
        uses = (row["uses"] if row else 0) + 1
        db.x("INSERT INTO neurons(user_id,node,uses,first_at,last_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,node) DO UPDATE SET uses=?, last_at=?",
             (uid, k, uses, now_iso(), now_iso(), uses, now_iso()))
        if uses in (1, 3):
            changed.append(k)
    return changed


def state(uses: int) -> str:
    return "wired" if uses >= 3 else "sparked" if uses >= 1 else "dark"


def rarity(db: DB) -> dict:
    total = db.one("SELECT COUNT(*) n FROM users")["n"]
    if total < 30:
        return {}
    return {r["node"]: round(100 * r["n"] / total) for r in db.q("SELECT node, COUNT(*) n FROM neurons WHERE uses>=3 GROUP BY node")}


def mind_map(db: DB, user: dict) -> dict:
    uses = {r["node"]: r["uses"] for r in db.q("SELECT node, uses FROM neurons WHERE user_id=?", (user["id"],))}
    rare = rarity(db)
    branches = []
    for bid, name, emoji, line in BRANCHES:
        nodes = []
        for k, n in NODES.items():
            if n["branch"] != bid:
                continue
            u = uses.get(k, 0)
            nodes.append({"id": k, "emoji": n["emoji"], "name": n["name"], "why": n["why"], "state": state(u), "uses": u,
                          "kind": n["try"][0], "rare": rare.get(k)})
        lit = sum(1 for x in nodes if x["state"] != "dark")
        branches.append({"id": bid, "name": name, "emoji": emoji, "line": line, "nodes": nodes, "lit": lit, "wired": sum(1 for x in nodes if x["state"] == "wired")})
    lit = sum(b["lit"] for b in branches)
    wired = sum(b["wired"] for b in branches)
    return {"branches": branches, "lit": lit, "wired": wired, "total": len(NODES), "spark": spark(db, user, uses)}


def spark(db: DB, user: dict, uses: dict | None = None) -> dict | None:
    """One dark neuron worth trying today: from the branch you've lit most (momentum), stable for the day."""
    uses = uses if uses is not None else {r["node"]: r["uses"] for r in db.q("SELECT node, uses FROM neurons WHERE user_id=?", (user["id"],))}
    dark = [k for k in NODES if not uses.get(k)]
    if not dark:
        return None
    score = {b[0]: sum(1 for k, n in NODES.items() if n["branch"] == b[0] and uses.get(k)) for b in BRANCHES}
    rnd = random.Random(f"{user['id']}-{date.today().isoformat()}")
    rnd.shuffle(dark)
    dark.sort(key=lambda k: -score[NODES[k]["branch"]])
    k = dark[0]
    n = NODES[k]
    left = sum(1 for x in NODES.values() if x["branch"] == n["branch"]) - score[n["branch"]]
    return {"id": k, "emoji": n["emoji"], "name": n["name"], "why": n["why"], "branch": n["branch"], "left_in_branch": left}


def demo_text(node: str, user: dict, friend: str | None) -> str:
    n = NODES[node]
    me = (user.get("name") or "You").split(" ")[0]
    fr = friend or "Rahul"
    who = {"you": "You", "their": f"{fr}'s phone", "mindy": "Mindy"}
    lines = [f"*{who[w]}:* {t.replace('{friend}', fr).replace('{me}', me)}" for w, t in n["try"][1]]
    return f"{n['emoji']} *{n['name']}*: {n['why']}\n\n" + "\n".join(lines)


def celebrate(changed: list[str], db: DB, uid: int) -> str:
    if not changed:
        return ""
    lit = db.one("SELECT COUNT(*) n FROM neurons WHERE user_id=? AND uses>=1", (uid,))["n"]
    k = changed[0]
    n = NODES[k]
    uses = db.one("SELECT uses FROM neurons WHERE user_id=? AND node=?", (uid, k))["uses"]
    if uses >= 3:
        return f"\n\n⚡ *{n['name']}* is now wired into your mind."
    return f"\n\n✨ New neuron lit: {n['emoji']} *{n['name']}* · {lit}/{len(NODES)}"


MILESTONES = (5, 10, 20, 30, 40, 48)


def milestone(changed: list[str], db: DB, uid: int) -> str:
    """For WhatsApp: only the moments worth a message of their own (a round number lit, a whole branch, the first wired neuron).
    Every single new neuron would be noise; the map shows the rest."""
    if not changed:
        return ""
    lit = db.one("SELECT COUNT(*) n FROM neurons WHERE user_id=? AND uses>=1", (uid,))["n"]
    uses = {r["node"]: r["uses"] for r in db.q("SELECT node, uses FROM neurons WHERE user_id=?", (uid,))}
    for k in changed:
        n = NODES[k]
        if uses.get(k) == 1:
            br = next(b for b in BRANCHES if b[0] == n["branch"])
            mates = [x for x, v in NODES.items() if v["branch"] == br[0]]
            if all(uses.get(x) for x in mates):
                return f"🌿 Your whole *{br[1]}* branch is lit. {lit}/{len(NODES)} neurons now. Say *mind* to see what's still dark."
    if any(uses.get(k) == 1 for k in changed) and lit in MILESTONES:
        return (f"🧠 {lit}/{len(NODES)} neurons lit. Your mind's growing. Say *mind* to see the map."
                if lit < len(NODES) else f"🧠 All {lit} neurons lit. That's a whole mind. Rarer than you'd think.")
    wired = [k for k in changed if uses.get(k, 0) >= 3]
    if wired and sum(1 for v in uses.values() if v >= 3) == 1:
        return f"⚡ *{NODES[wired[0]]['name']}* is your first wired neuron: you use it without thinking now."
    return ""
