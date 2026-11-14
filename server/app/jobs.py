"""Scheduled jobs for the newer skills. Mindy-initiated messages go through `deliver`; anything that is just nice to have
(brief, on this day, cheeky nudges) passes template=None, so it only uses free channels (app, push, Telegram, an open WhatsApp window)."""
import logging
import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import care, mind, more, places
from .config import settings
from .db import DB, now_iso

log = logging.getLogger("mindy.jobs")


async def _deliver(*a, **k):
    from .handlers import deliver
    return await deliver(*a, **k)


async def safety_check(db: DB, now: datetime | None = None):
    """'Check on me': ask at the due time; if still no reply 10 minutes later, alert family with the last saved location."""
    now = now or datetime.now(timezone.utc)
    for s in db.q("SELECT * FROM safety WHERE kind='check' AND cleared_at IS NULL AND alerted_at IS NULL AND due_at<=?", (now.isoformat(),)):
        due = datetime.fromisoformat(s["due_at"])
        asked = db.one("SELECT v FROM kv WHERE k=?", (f"checked:{s['id']}",))
        if not asked:
            await _deliver(db, s["user_id"], "🫶 *Are you OK?* Reply *safe* now. If I don't hear back in 10 minutes, I'll tell your family.",
                           [("safe", "I'm safe")], settings.reminder_template, ["Are you OK? Reply safe."], now, title="🫶 Are you OK?")
            db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"checked:{s['id']}", now.isoformat()))
            continue
        if now - due < timedelta(minutes=10):
            continue
        u = db.one("SELECT name FROM users WHERE id=?", (s["user_id"],)) or {}
        p = places.latest(db, s["user_id"])
        where = f"\nLast saved location: https://maps.google.com/?q={p['lat']},{p['lng']}" if p else ""
        for f in care.family_of(db, s["user_id"]):
            await _deliver(db, f["id"], f"⚠️ *{u.get('name') or 'Your family member'} asked me to check on them and hasn't replied.* Please call them now.{where}",
                           [], settings.care_alert_template, [u.get("name") or "Your family member", "a safety check"], now, title="⚠️ Safety check")
        db.x("UPDATE safety SET alerted_at=? WHERE id=?", (now.isoformat(), s["id"]))


async def ok_daily(db: DB, now: datetime | None = None):
    """'I'm OK' daily: ask at 10:00 local, tell family at 13:00 local if there was no tap. Runs every 15 minutes."""
    now = now or datetime.now(timezone.utc)
    for u in db.q("SELECT id, name, tz FROM users WHERE ok_daily=1"):
        local = now.astimezone(ZoneInfo(u["tz"] or "UTC"))
        day = local.date().isoformat()
        start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
        ok = db.one("SELECT 1 FROM safety WHERE user_id=? AND kind='ok' AND created_at>=?", (u["id"], start))
        if local.hour == 10 and local.minute < 15 and not db.one("SELECT 1 FROM kv WHERE k=?", (f"okask:{u['id']}:{day}",)):
            db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"okask:{u['id']}:{day}", "1"))
            if not ok:
                await _deliver(db, u["id"], "☀️ Good morning! *Are you OK today?*", [("okday", "💚 I'm OK")], settings.reminder_template, ["Are you OK today?"], now)
        if local.hour == 13 and local.minute < 15 and not ok and not db.one("SELECT 1 FROM kv WHERE k=?", (f"okalert:{u['id']}:{day}",)):
            db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"okalert:{u['id']}:{day}", "1"))
            for f in care.family_of(db, u["id"]):
                await _deliver(db, f["id"], f"💛 {u['name'] or 'Your family member'} hasn't tapped *I'm OK* today. Maybe give them a call?",
                               [], settings.care_alert_template, [u["name"] or "Your family member", "today's I'm OK"], now)


async def capsules(db: DB, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    for c in db.q("SELECT * FROM capsules WHERE opened=0 AND open_at<=?", (now.isoformat(),)):
        await _deliver(db, c["user_id"], f"💌 *A letter from you, {datetime.fromisoformat(c['created_at']):%d %b %Y}:*\n\n{c['text']}",
                       [], settings.reminder_template, ["A letter from your past self"], now, title="💌 Time capsule")
        db.x("UPDATE capsules SET opened=1 WHERE id=?", (c["id"],))


async def morning_brief(db: DB, now: datetime | None = None):
    """At each person's wake time: today's reminders, birthdays (with a gift nudge 3 days before), docs expiring, one question.
    Free channels only. Runs every 5 minutes."""
    now = now or datetime.now(timezone.utc)
    for u in db.q("SELECT * FROM users WHERE brief_at IS NOT NULL"):
        local = now.astimezone(ZoneInfo(u["tz"] or "UTC"))
        hh, mm = (int(x) for x in u["brief_at"].split(":"))
        if not (local.hour == hh and mm <= local.minute < mm + 5):
            continue
        k = f"brief:{u['id']}:{local.date()}"
        if db.one("SELECT 1 FROM kv WHERE k=?", (k,)):
            continue
        db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (k, "1"))
        lines = []
        end = (local.replace(hour=23, minute=59)).astimezone(timezone.utc).isoformat()
        for r in db.q("SELECT text, due_at FROM reminders WHERE user_id=? AND status='pending' AND due_at<=? ORDER BY due_at LIMIT 5", (u["id"], end)):
            lines.append(f"⏰ {datetime.fromisoformat(r['due_at']).astimezone(ZoneInfo(u['tz'])):%H:%M} {r['text']}")
        soon = local.date() + timedelta(days=3)
        for o in db.q("SELECT person FROM occasions WHERE user_id=? AND month=? AND day=?", (u["id"], soon.month, soon.day)):
            lines.append(f"🎁 {o['person']}'s birthday is in 3 days. Say _gift ideas for {o['person']}_.")
        for o in db.q("SELECT person FROM occasions WHERE user_id=? AND month=? AND day=?", (u["id"], local.month, local.day)):
            lines.append(f"🎂 It's {o['person']}'s birthday today!")
        for h in db.q("SELECT id, title FROM habits WHERE user_id=? AND archived=0 LIMIT 2", (u["id"],)):
            s = mind.streak(db, h["id"], local.date())
            if s:
                lines.append(f"🔥 {h['title']}: {s}-day streak. Keep it alive.")
        hello = random.choice(["Good morning ☀️", "Rise and shine 🌞", "Morning! ☕"]) if (u.get("persona") or "sweet") != "cheeky" else \
            random.choice(["Morning, superstar. Don't make me chase you today 😏", "Up already? I'm impressed 👀"])
        body = f"*{hello}*\n" + ("\n".join(lines) if lines else "Nothing on today. A good day to do one of your saved things?")
        await _deliver(db, u["id"], body, [], None, [], now, title="☀️ Your morning", url="/#now")


NUDGES = ["Thinking of me? No? 🙄 Fine. So… {saved}?", "You've gone quiet. Should I be worried, or are you busy being amazing? 👀",
          "Remember {saved}? I do. Shall we make it happen this week?", "I've been holding on to {saved} for you. Just saying. 😌"]


async def cheeky_nudges(db: DB, now: datetime | None = None):
    """For people who chose the cheeky Mindy: once in a while, a teasing nudge about something they saved. Free channels only."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=4)).isoformat()
    for u in db.q("SELECT id FROM users WHERE persona='cheeky'"):
        last = db.one("SELECT MAX(created_at) t FROM messages WHERE user_id=? AND direction='in'", (u["id"],))
        if not last or not last["t"] or last["t"] > cutoff or db.one("SELECT 1 FROM kv WHERE k=?", (f"nudge:{u['id']}:{now.date().isocalendar()[1]}",)):
            continue
        it = db.one("SELECT title, text FROM items WHERE user_id=? AND done_at IS NULL AND rkind IN ('place','travel','recipe','workout','event') ORDER BY RANDOM() LIMIT 1", (u["id"],))
        if not it:
            continue
        db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"nudge:{u['id']}:{now.date().isocalendar()[1]}", "1"))
        await _deliver(db, u["id"], random.choice(NUDGES).format(saved=(it.get("title") or it["text"])[:60]), [], None, [], now, title="Mindy 👀")


async def on_this_day(db: DB, now: datetime | None = None):
    """Once a week: something they saved a year ago. Free channels only."""
    now = now or datetime.now(timezone.utc)
    ago = (now - timedelta(days=365)).date().isoformat()
    for it in db.q("SELECT user_id, text, collection FROM items WHERE substr(created_at,1,10)=? AND collection NOT IN ('Clipboard','Email') GROUP BY user_id", (ago,)):
        await _deliver(db, it["user_id"], f"🕰️ *On this day last year* you saved:\n{it['text'][:300]}", [], None, [], now, title="🕰️ On this day")


def add_jobs(scheduler, db: DB):
    scheduler.add_job(safety_check, "interval", seconds=60, args=[db], id="safety", max_instances=1, coalesce=True)
    scheduler.add_job(ok_daily, "interval", minutes=15, args=[db], id="okdaily", max_instances=1, coalesce=True)
    scheduler.add_job(capsules, "interval", hours=1, args=[db], id="capsules", max_instances=1, coalesce=True)
    scheduler.add_job(morning_brief, "interval", minutes=5, args=[db], id="brief", max_instances=1, coalesce=True)
    scheduler.add_job(cheeky_nudges, "cron", hour=17, minute=10, args=[db], id="nudges")
    scheduler.add_job(on_this_day, "cron", day_of_week="sat", hour=10, minute=20, args=[db], id="onthisday")
