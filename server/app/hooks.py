"""The hook: people save dozens of reels a day and never use them. Mindy turns each save into something real.
- Every save is understood (recipe, place, workout, study, product, travel, event, idea).
- One tap makes it happen: shopping list + cook reminder, a plan with friends, a weekly workout, a revision quiz.
- Friend matches: you and a friend saved the same kind of place or dish, so Mindy suggests doing it together.
- Saved -> Done score and a streak, so using your saves becomes a habit."""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import brain
from .db import DB, now_iso

ACTIONS = {
    "recipe": [("shop", "🛒 Add to shopping"), ("cook", "🍳 Cook it Sunday"), ("go", "👯 Cook with friends")],
    "place": [("go", "👯 Go with friends"), ("remind", "📍 Go this weekend"), ("done", "✅ Been there")],
    "travel": [("go", "✈️ Plan a trip"), ("remind", "⏰ Remind me"), ("done", "✅ Been there")],
    "event": [("go", "🎟️ Go with friends"), ("remind", "⏰ Remind me"), ("done", "✅ Went")],
    "workout": [("train", "💪 Every Monday 7am"), ("remind", "⏰ Tomorrow 7am"), ("done", "✅ Did it")],
    "study": [("revise", "📚 Revise tomorrow"), ("quiz", "🧠 Quiz me"), ("done", "✅ Learnt it")],
    "product": [("price", "🏷️ Check in a week"), ("remind", "⏰ Remind me"), ("done", "✅ Bought it")],
    "idea": [("remind", "⏰ Think on Sunday"), ("done", "✅ Did it")],
    "fun": [("go", "👯 Do it with friends"), ("done", "✅ Did it")],
    "other": [("remind", "⏰ Remind me"), ("done", "✅ Did it")],
}
DEFAULT_WHEN = {"cook": "sunday 6pm", "go": "saturday 1pm", "remind": "saturday 11am", "train": "monday 7am",
                "revise": "tomorrow 7pm", "price": "in 7 days"}
STOP = set("the a an and or of in at on for to with best this that my your how what is are from top most must try new".split())


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def smart_save(db: DB, uid: int, text: str, url: str | None = None, src: str = "note", collection: str | None = None) -> dict:
    """Saves anything and works out what it is. Returns the stored item."""
    c = brain.classify_save(text, who=str(uid))
    coll = collection if collection and collection not in ("Notes", "Links", "Inbox") else c["collection"]
    iid = db.save_item(uid, src, text, url=url, collection=coll, tags=c.get("tags"))
    db.x("UPDATE items SET rkind=?, title=?, place=? WHERE id=?", (c["kind"], c["title"], c.get("place"), iid))
    return db.one("SELECT * FROM items WHERE id=?", (iid,))


def actions_for(item: dict) -> list[tuple[str, str]]:
    return ACTIONS.get(item.get("rkind") or "other", ACTIONS["other"])


def save_reply(item: dict) -> str:
    k = item.get("rkind") or "other"
    lead = {"recipe": "🍳 Recipe saved", "place": "📍 Place saved", "travel": "✈️ Trip idea saved", "event": "🎟️ Event saved",
            "workout": "💪 Workout saved", "study": "📚 Study note saved", "product": "🏷️ Wishlist saved", "idea": "💡 Idea saved"}.get(k, "🧠 Saved")
    return f"{lead}: *{item.get('title') or 'your post'}*\nDon't let it rot in your saves. Make it happen?"


def do_action(db: DB, user: dict, item: dict, action: str, when_text: str | None = None, people: list[int] | None = None) -> dict:
    """Turns a save into a reminder, list, plan or quiz. Returns {reply, did}."""
    uid, tz = user["id"], user["tz"]
    title = item.get("title") or item["text"][:60]
    when = brain.parse_when(when_text or DEFAULT_WHEN.get(action, "saturday 11am"), tz)
    did = {"kind": action, "item": item["id"]}
    w = lambda d: f"{d.astimezone(ZoneInfo(tz)):%a} {d.astimezone(ZoneInfo(tz)).day} {d.astimezone(ZoneInfo(tz)):%b}, {d.astimezone(ZoneInfo(tz)):%H:%M}"
    if action == "done":
        db.x("UPDATE items SET done_at=? WHERE id=? AND user_id=?", (now_iso(), item["id"], uid))
        s = score(db, uid)
        return {"reply": f"✅ Done! That's {s['done_week']} saves turned real this week. 🔥 {s['streak']}-day streak.", "did": did}
    if action == "shop":
        card = brain.recipe_from(item["text"], who=str(uid))
        entries = card.get("ingredients") or [f"Ingredients for {title}"]
        name, _ = db.list_add(uid, "Shopping", entries[:20])
        rid = db.add_reminder(uid, f"Cook {title} 🍳", _iso(brain.parse_when(DEFAULT_WHEN["cook"], tz)), item_id=item["id"])
        did.update(list=name, added=entries[:20], reminder=rid)
        what = f"{len(entries[:20])} ingredients" if card.get("ingredients") else f"*{title}*"
        return {"reply": f"🛒 Added {what} to your Shopping list, and I'll remind you to cook it on Sunday at 18:00.", "did": did, "recipe": card}
    if action == "go":
        from .api_shared import new_plan  # avoid a circular import at module load
        pid = new_plan(db, user, title, when, people or [])
        did.update(plan=pid)
        return {"reply": f"👯 Plan made: *{title}* for {w(when)}." + (" Invites sent." if people else " Add friends in the app to invite them."), "did": did}
    if action == "quiz":
        quiz = brain.quiz_from(item["text"], who=str(uid))
        return {"reply": "🧠 Quiz ready in the app." if quiz.get("questions") else "Quizzes need the AI switched on.", "did": did, "quiz": quiz}
    text = {"cook": f"Cook {title} 🍳", "remind": f"{title}", "train": f"{title} 💪", "revise": f"Revise: {title} 📚",
            "price": f"Check the price: {title} 🏷️"}.get(action, title)
    rep = "weekly" if action == "train" else None
    rid = db.add_reminder(uid, text, _iso(when), rep, item_id=item["id"])
    did.update(reminder=rid, when=_iso(when), repeat=rep)
    return {"reply": f"⏰ Done: *{text}* on {w(when)}" + (", every week." if rep else "."), "did": did}


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z]{3,}", (s or "").lower()) if w not in STOP}


def matches(db: DB, uid: int, limit: int = 6) -> list[dict]:
    """Friends who saved something like your saves, for doing it together. Both people must allow matches."""
    me = db.one("SELECT share_matches FROM users WHERE id=?", (uid,))
    if not me or not me.get("share_matches"):
        return []
    since = _iso(datetime.now(timezone.utc) - timedelta(days=60))
    mine = db.q("SELECT * FROM items WHERE user_id=? AND created_at>? AND rkind IN ('place','recipe','travel','event','workout','fun') AND done_at IS NULL ORDER BY id DESC LIMIT 200", (uid, since))
    friends = db.q("SELECT u.id, u.name FROM friends f JOIN users u ON u.id=f.b WHERE f.a=? AND COALESCE(u.share_matches,1)=1", (uid,))
    out, seen = [], set()
    for f in friends:
        theirs = db.q("SELECT * FROM items WHERE user_id=? AND created_at>? AND rkind IN ('place','recipe','travel','event','workout','fun') ORDER BY id DESC LIMIT 200", (f["id"], since))
        for a in mine:
            wa = _words((a.get("title") or "") + " " + (a.get("place") or ""))
            for b in theirs:
                if b["rkind"] != a["rkind"]:
                    continue
                same_place = a.get("place") and b.get("place") and a["place"].lower() == b["place"].lower()
                shared = wa & _words((b.get("title") or "") + " " + (b.get("place") or ""))
                if same_place or len(shared) >= 2:
                    key = (f["id"], a["id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    why = f"you both saved {a['place']}" if same_place else "you both saved " + {"recipe": "this dish", "place": "spots like this", "travel": "this trip",
                                                                                                    "event": "this", "workout": "this workout"}.get(a["rkind"], "this")
                    out.append({"friend": f, "item": a, "theirs": {"title": b.get("title"), "kind": b["rkind"]}, "why": why})
                    break
            if len(out) >= limit:
                return out
    return out


def score(db: DB, uid: int) -> dict:
    """Saved vs done this week, and the streak of days you did something you'd saved or ticked a reminder."""
    week = _iso(datetime.now(timezone.utc) - timedelta(days=7))
    saved = db.one("SELECT COUNT(*) n FROM items WHERE user_id=? AND created_at>?", (uid, week))["n"]
    done = db.one("SELECT COUNT(*) n FROM items WHERE user_id=? AND done_at>?", (uid, week))["n"]
    tz = ZoneInfo((db.one("SELECT tz FROM users WHERE id=?", (uid,)) or {}).get("tz") or "UTC")
    days = set()
    for r in db.q("SELECT done_at d FROM items WHERE user_id=? AND done_at IS NOT NULL UNION ALL SELECT day d FROM moods WHERE user_id=?", (uid, uid)):
        try:
            days.add(r["d"][:10] if len(r["d"]) == 10 else datetime.fromisoformat(r["d"]).astimezone(tz).date().isoformat())
        except ValueError:
            pass
    streak, d = 0, datetime.now(tz).date()
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    while d.isoformat() in days:
        streak += 1
        d -= timedelta(days=1)
    return {"saved_week": saved, "done_week": done, "streak": streak, "rate": round(100 * done / saved) if saved else 0}
