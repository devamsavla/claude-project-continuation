"""Small pieces shared by the API, WhatsApp handlers and the hooks."""
from datetime import timezone

from .db import DB, now_iso
from .realtime import fire, hub


def new_plan(db: DB, me: dict, title: str, when, people: list[int], chat_id: int | None = None) -> int:
    allowed = {r["b"] for r in db.q("SELECT b FROM friends WHERE a=? UNION SELECT b FROM family WHERE a=?", (me["id"], me["id"]))}
    if chat_id:  # everyone in the chat can be invited
        allowed |= {r["user_id"] for r in db.q("SELECT user_id FROM chat_members WHERE chat_id=?", (chat_id,))}
    people = [p for p in people if p in allowed]
    pid = db.x("INSERT INTO plans(title,when_at,created_by,chat_id,created_at) VALUES(?,?,?,?,?)",
               (title, when.astimezone(timezone.utc).replace(microsecond=0).isoformat() if when else None, me["id"], chat_id, now_iso()))
    db.x("INSERT INTO plan_people(plan_id,user_id,rsvp) VALUES(?,?,'going')", (pid, me["id"]))
    for u in people:
        db.x("INSERT OR IGNORE INTO plan_people(plan_id,user_id) VALUES(?,?)", (pid, u))
    if people:
        fire(hub.send_many(people, {"type": "plan.invite", "plan": pid, "title": title, "from": me.get("name") or "A friend"}))
    return pid
