"""Turns one inbound message (WhatsApp or Instagram) into Mindy's reply.
One brain, many channels: a reply always goes back on the channel the message came from,
and reminders go out on whichever channel can still reach the person (see `deliver`)."""
import asyncio
import logging
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, available_timezones

from . import brain
from .config import settings
from .db import DB
from .instagram import ig
from .whatsapp import wa

log = logging.getLogger("mindy.handlers")
CLIENTS = {"wa": wa, "ig": ig}

# Best-guess timezone from the phone number's country code. Users can change it: "timezone Europe/Paris".
CC_TZ = {"44": "Europe/London", "353": "Europe/Dublin", "33": "Europe/Paris", "49": "Europe/Berlin", "34": "Europe/Madrid",
         "39": "Europe/Rome", "31": "Europe/Amsterdam", "91": "Asia/Kolkata", "971": "Asia/Dubai", "65": "Asia/Singapore",
         "61": "Australia/Sydney", "1": "America/New_York", "55": "America/Sao_Paulo", "52": "America/Mexico_City", "27": "Africa/Johannesburg",
         "234": "Africa/Lagos", "254": "Africa/Nairobi", "81": "Asia/Tokyo", "82": "Asia/Seoul", "62": "Asia/Jakarta"}


def tz_for(ext: str) -> str:
    if ext.startswith("ig:"):
        return settings.default_tz
    for n in (3, 2, 1):
        if ext[:n] in CC_TZ:
            return CC_TZ[ext[:n]]
    return settings.default_tz


WELCOME = {
    "wa": ("Hi{name}! I'm *Mindy* 🧠\n\nSend me anything and I'll remember it: links, reels, photos, notes, voice notes.\n\n"
           "Try:\n• _remind me to call mum tomorrow at 6pm_\n• _add milk, eggs to shopping list_\n• _Sofia's birthday is 12 March_\n"
           "• _what was that pasta place?_\n\nI've set your timezone to *{tz}*. Reply _timezone Europe/Paris_ to change it."),
    "ig": ("Hi{name}! I'm Mindy 🧠 Share any reel or post with me and I'll turn it into something useful: recipes, places, plans.\n\n"
           "You can also type things like “remind me to call mum tomorrow 6pm” or “what was that pasta place?”.\n\n"
           "Instagram only lets me reply for 24 hours after your last message, so reminders reach you on WhatsApp or the Mindy app. Send LINK to connect them."),
}
HELP = ("Here's what I can do:\n• *Save*: forward or send anything\n• *Find*: ask a question, e.g. _where's my passport photo?_\n"
        "• *Remind*: _remind me to pay rent on the 1st every month_\n• *Lists*: _add bread to shopping list_, _show shopping list_\n"
        "• *Occasions*: _Leo's birthday is 3 June_\n• *Photos*: send a ticket or invitation and I'll set the reminder\n"
        "• *Link*: send _link_ to join up WhatsApp, Instagram and the app\n• _export my data_ or _delete my data_ at any time")
CHANNEL_NAME = {"wa": "WhatsApp", "ig": "Instagram"}


def fmt_local(dt_utc_iso: str, tz: str) -> str:
    d = datetime.fromisoformat(dt_utc_iso).astimezone(ZoneInfo(tz))
    return f"{d:%a} {d.day} {d:%b}, {d:%H:%M}"


# the conversation in progress: (client, the sender's id on that channel)
_CONV: ContextVar[tuple] = ContextVar("conv", default=(wa, ""))


class Mindy:
    def __init__(self, db: DB):
        self.db = db

    # -- reply helpers: always answer on the channel the message came from
    async def say(self, text: str, **kw):
        client, to = _CONV.get()
        return await client.text(to, text, **kw)

    async def ask(self, text: str, buttons):
        client, to = _CONV.get()
        return await client.buttons(to, text, buttons)

    async def react(self, mid: str, emoji: str):
        client, to = _CONV.get()
        return await client.react(to, mid, emoji)

    async def handle(self, msg: dict, contact_name: str | None = None):
        ext, mid, mtype = msg.get("from"), msg.get("id"), msg.get("type")
        channel = msg.get("channel") or ("ig" if str(ext).startswith("ig:") else "wa")
        if not ext or self.db.seen(mid):
            return
        client = CLIENTS[channel]
        _CONV.set((client, ext))
        user = self.db.user(ext, contact_name, tz_for(ext), channel)
        self.db.touch_inbound(user["id"], ext)
        await client.read_and_typing(mid)
        body = self._text_of(msg)
        self.db.log(user["id"], "in", body or mtype, mid)
        if user.get("_new"):
            first = f", {contact_name.split()[0]}" if contact_name else ""
            await self.ask(WELCOME[channel].format(name=first, tz=user["tz"]), [("help", "What can you do?"), ("upcoming", "My reminders")])
            if not body or body.lower() in ("hi", "hello", "hey", "start"):
                return
        try:
            if mtype == "interactive":
                await self.on_button(user, msg)
            elif mtype in ("image", "document", "audio", "video", "sticker"):
                await self.on_media(user, msg)
            elif mtype == "location":
                loc = msg["location"]
                self.db.save_item(user["id"], "place", f"{loc.get('name') or 'Pinned place'} {loc.get('address') or ''} ({loc['latitude']},{loc['longitude']})", collection="Places")
                await self.say("📍 Saved to *Places*.")
            elif mtype == "text":
                await self.on_text(user, body, mid, msg.get("share"))
            else:
                await self.say("I can't open that type of message yet, but text, links, photos and documents all work.")
        except Exception:
            log.exception("handler failed")
            await self.say("Sorry, something went wrong on my side. Try that again in a moment?")

    @staticmethod
    def _text_of(msg: dict) -> str:
        t = msg.get("type")
        if t == "text":
            return msg["text"]["body"]
        if t == "interactive":
            i = msg["interactive"]
            return (i.get("button_reply") or i.get("list_reply") or {}).get("id", "")
        if t in ("image", "document", "video"):
            return msg[t].get("caption", "")
        return ""

    # ------------------------------------------------------------ text
    async def on_text(self, user: dict, text: str, mid: str, share: str | None = None):
        tz = user["tz"]
        low = text.strip().lower()
        if low.startswith("timezone "):
            want = text.split(" ", 1)[1].strip()
            match = next((z for z in available_timezones() if z.lower() == want.lower()), None)
            if not match:
                return await self.say("I don't know that timezone. Try something like _Europe/London_ or _America/New_York_.")
            self.db.x("UPDATE users SET tz=? WHERE id=?", (match, user["id"]))
            return await self.say(f"Done. Your timezone is now *{match}*.")
        if low == "link" or low.startswith("link "):
            return await self.on_link(user, low)
        if low in ("login", "log in", "sign in", "signin", "app", "code"):
            from .auth import new_code
            code = new_code(self.db, user["id"])
            return await self.say(f"Your Mindy app code is *{code}* (valid 10 minutes).\nOpen {settings.app_url} and type it in. "
                                  "Everything you've sent me is already there.")
        if share:  # a reel or post shared from Instagram: always save it
            coll = "Reels" if share == "reel" else "Instagram"
            r = await asyncio.to_thread(brain.route, f"save this: {text}", tz) if settings.ai_live else {}
            coll = r.get("collection") or coll
            url = (brain.URL_RE.search(text) or [None])[0] if brain.URL_RE.search(text) else None
            self.db.save_item(user["id"], share, text, url=url, collection=coll, tags=r.get("tags"))
            return await self.say(f"Saved to *{coll}* 🧠 Ask me for it any time, or say “make it a plan”.")
        r = await asyncio.to_thread(brain.route, text, tz)
        intent = r.get("intent")
        if intent == "help":
            return await self.say(HELP)
        if intent == "save":
            url = (brain.URL_RE.search(text) or [None])[0] if brain.URL_RE.search(text) else None
            kind = "reel" if url and "instagram.com" in url else "link" if url else "note"
            coll = r.get("collection") or "Notes"
            self.db.save_item(user["id"], kind, r.get("text") or text, url=url, collection=coll, tags=r.get("tags"))
            await self.react(mid, "🧠")
            return await self.say(f"Saved to *{coll}*.", reply_to=mid, preview_url=False)
        if intent == "ask":
            items = self.db.search(user["id"], r.get("text") or text)
            reply = await asyncio.to_thread(brain.answer, text, items)
            return await self.say(reply)
        if intent == "remind":
            due = r.get("due")
            if not due:
                return await self.say("When should I remind you? For example _tomorrow at 9_ or _Friday 6pm_.")
            due_utc = due.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            rep = r.get("repeat") if r.get("repeat") not in (None, "none") else None
            rid = self.db.add_reminder(user["id"], r.get("text") or text, due_utc, rep)
            extra = f", repeating {rep}" if rep else ""
            note = ""
            chans = {a["channel"] for a in self.db.accounts(user["id"])}
            if chans == {"ig"} and (due - datetime.now(due.tzinfo)) > timedelta(hours=23):
                note = "\n\nHeads up: Instagram only lets me message you for 24 hours. Send LINK and connect WhatsApp so this reaches you."
            return await self.ask(f"⏰ I'll remind you *{fmt_local(due_utc, tz)}*{extra}:\n{r.get('text') or text}{note}",
                                  [(f"cancel:{rid}", "Cancel it"), ("upcoming", "All reminders")])
        if intent == "list_add":
            name, items = self.db.list_add(user["id"], r.get("list_name") or "Shopping", r.get("list_entries") or [])
            return await self.say(f"🛒 *{name}* list ({len(items)}):\n" + "\n".join(f"• {i['text']}" for i in items))
        if intent == "list_show":
            name, items = self.db.list_show(user["id"], r.get("list_name") or "Shopping")
            if not name:
                return await self.say("You don't have that list yet. Try _add milk to shopping list_.")
            return await self.say(f"*{name}* ({len(items)}):\n" + ("\n".join(f"• {i['text']}" for i in items) or "Empty!"))
        if intent == "occasion":
            if not (r.get("month") and r.get("day")):
                return await self.say("What's the date? For example _Sofia's birthday is 12 March_.")
            self.db.add_occasion(user["id"], r.get("person"), r.get("occasion_kind") or "birthday", r["month"], r["day"])
            return await self.say(f"🎉 Got it: *{r.get('person')}*, {r.get('occasion_kind') or 'birthday'} on {r['day']}/{r['month']}. "
                                  "I'll nudge you the day before with a message idea.")
        if intent == "upcoming":
            return await self.send_upcoming(user)
        if intent == "export":
            data = self.db.export_user(user["id"])
            return await self.say(f"Your data: {len(data['items'])} saved items, {len(data['reminders'])} reminders, "
                                  f"{len(data['occasions'])} occasions. A full download link is coming in the web dashboard.")
        if intent == "delete_all":
            return await self.ask("This permanently deletes everything I've saved for you. Are you sure?", [("delete_yes", "Yes, delete all"), ("delete_no", "Keep my data")])
        return await self.say("That's outside what I do. I'm best at remembering things, reminders, lists and birthdays. Type *help* to see how.")

    async def on_link(self, user: dict, low: str):
        """Same person on WhatsApp, Instagram and the app: one code joins them up."""
        parts = low.split()
        mine = {a["channel"] for a in self.db.accounts(user["id"])}
        if len(parts) == 1:
            code = self.db.link_code(user["id"])
            other = "Instagram" if "wa" in mine else "WhatsApp"
            return await self.say(f"Your link code is *{code}*. Send _link {code}_ to Mindy on {other} (or type it in the Mindy app) within 15 minutes.")
        target = self.db.use_link_code(parts[1])
        if not target:
            return await self.say("That code didn't work or has expired. Send _link_ on your other app to get a new one.")
        if target == user["id"]:
            return await self.say("That's this account's own code. Send it from your other app instead.")
        self.db.merge(user["id"], target)
        chans = " + ".join(CHANNEL_NAME.get(a["channel"], a["channel"]) for a in self.db.accounts(target))
        return await self.say(f"Linked ✅ {chans} now share one Mindy. Your saves, lists and reminders are all in one place.")

    async def send_upcoming(self, user):
        rs = self.db.upcoming(user["id"])
        if not rs:
            return await self.say("No reminders coming up. Try _remind me to stretch at 4pm_.")
        lines = [f"• {fmt_local(r['due_at'], user['tz'])}: {r['text']}" for r in rs]
        return await self.say("⏰ *Coming up*\n" + "\n".join(lines))

    # ------------------------------------------------------------ buttons
    async def on_button(self, user, msg):
        bid = self._text_of(msg)
        if bid == "help":
            return await self.say(HELP)
        if bid == "upcoming":
            return await self.send_upcoming(user)
        if bid.startswith("cancel:"):
            self.db.x("UPDATE reminders SET status='cancelled' WHERE id=? AND user_id=?", (int(bid[7:]), user["id"]))
            return await self.say("Cancelled.")
        if bid.startswith("done:"):
            self.db.x("UPDATE reminders SET status='done' WHERE id=? AND user_id=?", (int(bid[5:]), user["id"]))
            return await self.react(msg["id"], "✅")
        if bid.startswith("snooze:"):
            r = self.db.one("SELECT * FROM reminders WHERE id=? AND user_id=?", (int(bid[7:]), user["id"]))
            if r:
                due = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0).isoformat()
                self.db.add_reminder(user["id"], r["text"], due)
                return await self.say("Snoozed for an hour. 😴")
        if bid.startswith("draft:"):
            o = self.db.one("SELECT * FROM occasions WHERE id=? AND user_id=?", (int(bid[6:]), user["id"]))
            if o:
                draft = await asyncio.to_thread(brain.draft_wish, o["person"], o["kind"])
                return await self.say(f"Here's one you can copy:\n\n{draft}")
        if bid == "delete_yes":
            self.db.delete_user(user["id"])
            return await self.say("Done. Everything is deleted. Say hi any time to start fresh.")
        if bid == "delete_no":
            return await self.say("Nothing deleted. 👍")

    # ------------------------------------------------------------ media
    async def on_media(self, user, msg):
        t = msg["type"]
        m = msg[t]
        caption = m.get("caption", "") or ""
        tz = user["tz"]
        client, _ = _CONV.get()
        ref = m.get("id") or m.get("url")
        if t == "image":
            data, mime = await client.download_media(ref)
            info = await asyncio.to_thread(brain.read_image, data, mime or m.get("mime_type", "image/jpeg"), caption, tz)
            self.db.save_item(user["id"], "photo", f"{info.get('summary')} {caption}".strip(), media_id=ref, collection=info.get("collection") or "Photos")
            lines = [f"📸 Saved to *{info.get('collection') or 'Photos'}*: {info.get('summary')}"]
            for ev in info.get("events", [])[:3]:
                try:
                    due = datetime.fromisoformat(ev["due_local"]).replace(tzinfo=ZoneInfo(tz))
                except (KeyError, ValueError):
                    continue
                if due < datetime.now(ZoneInfo(tz)):
                    continue
                due_utc = due.astimezone(timezone.utc).replace(microsecond=0).isoformat()
                self.db.add_reminder(user["id"], ev.get("text", "From your photo"), due_utc)
                lines.append(f"⏰ Reminder set for *{fmt_local(due_utc, tz)}*: {ev.get('text')}")
            return await self.say("\n".join(lines))
        if t == "document":
            self.db.save_item(user["id"], "doc", f"{m.get('filename', 'Document')} {caption}".strip(), media_id=ref, collection="Documents")
            return await self.say(f"📄 Saved *{m.get('filename', 'your document')}* to *Documents*. Ask me for it any time.")
        if t == "audio":
            self.db.save_item(user["id"], "voice", f"Voice note {datetime.now(ZoneInfo(tz)):%d %b %H:%M}", media_id=ref, collection="Voice notes")
            return await self.say("🎙️ Voice note saved. (Transcription switches on with the speech-to-text key in .env.)")
        self.db.save_item(user["id"], t, caption or t, media_id=ref, collection="Media")
        return await self.say("Saved. 👍")


# ---------------------------------------------------------------- outbound (scheduled) messages
def _in_window(last: str | None, now: datetime, hours: float = 23.8) -> bool:
    return bool(last) and (now - datetime.fromisoformat(last)) < timedelta(hours=hours)


async def deliver(db: DB, user_id: int, body: str, buttons, template: str, params, now: datetime | None = None,
                  title: str = "Mindy", url: str = "/") -> str | None:
    """Sends a Mindy-initiated message on every channel the person wants and that can still reach them.
    The app: a live in-app card if it's open, plus a phone notification (Web Push) if they turned those on.
    Chat apps: WhatsApp first (approved templates work outside 24 hours), else Instagram inside its 24-hour window.
    `notify` on the user picks: 'both' (default), 'app' or 'whatsapp'. Returns the channels used, or None."""
    now = now or datetime.now(timezone.utc)
    pref = (db.one("SELECT notify FROM users WHERE id=?", (user_id,)) or {}).get("notify") or "both"
    used = []
    if pref in ("both", "app"):
        from .realtime import hub, send_push
        plain = body.replace("*", "")
        if hub.online(user_id):
            await hub.send(user_id, {"type": "notify", "title": title, "body": plain.split("\n", 1)[-1], "url": url})
            used.append("app")
        if await asyncio.to_thread(send_push, db, user_id, title, plain.split("\n", 1)[-1], url):
            used.append("push")
    if pref in ("both", "whatsapp") or not used:
        accs = db.accounts(user_id)
        wa_acc = next((a for a in accs if a["channel"] == "wa"), None)
        ig_acc = next((a for a in accs if a["channel"] == "ig"), None)
        if wa_acc:
            if _in_window(wa_acc["last_inbound_at"], now):
                await wa.buttons(wa_acc["ext"], body, buttons)
            else:
                await wa.template(wa_acc["ext"], template, params)
            used.append("wa")
        elif ig_acc and _in_window(ig_acc["last_inbound_at"], now):
            await ig.buttons(ig_acc["ext"], body, buttons)
            used.append("ig")
    return "+".join(used) or None


async def send_due(db: DB, now: datetime | None = None):
    """Runs every 30 seconds: delivers due reminders on the best available channel."""
    now = now or datetime.now(timezone.utc)
    for r in db.due_reminders(now.replace(microsecond=0).isoformat()):
        used = await deliver(db, r["user_id"], f"⏰ *Reminder*\n{r['text']}", [(f"done:{r['id']}", "Done"), (f"snooze:{r['id']}", "Snooze 1 hour")],
                             settings.reminder_template, [r["text"]], now, title="⏰ Reminder", url="/#mind")
        db.x("UPDATE reminders SET status=? WHERE id=?", ("sent" if used else "undelivered", r["id"]))
        if r.get("repeat"):
            due = datetime.fromisoformat(r["due_at"]).astimezone(ZoneInfo(r["tz"]))
            step = {"daily": timedelta(days=1), "weekly": timedelta(weeks=1)}.get(r["repeat"])
            if step:
                nxt = due + step
            elif r["repeat"] == "monthly":
                y, mo = due.year + (due.month == 12), due.month % 12 + 1
                nxt = due.replace(year=y, month=mo, day=min(due.day, 28 if mo == 2 else 30 if mo in (4, 6, 9, 11) else 31))
            else:
                nxt = due.replace(year=due.year + 1)
            db.add_reminder(r["user_id"], r["text"], nxt.astimezone(timezone.utc).isoformat(), r["repeat"])


async def occasion_nudges(db: DB, today: datetime | None = None):
    """Daily: the day before a birthday, offer to draft a message."""
    tomorrow = (today or datetime.now(timezone.utc)) + timedelta(days=1)
    for o in db.occasions_on(tomorrow.month, tomorrow.day):
        text = f"🎂 {o['person']}'s {o['kind']} is tomorrow."
        await deliver(db, o["user_id"], text + " Want me to draft a message?", [(f"draft:{o['id']}", "Draft a message"), ("upcoming", "My reminders")],
                      settings.reminder_template, [text])


async def weekly_summary(db: DB, now: datetime | None = None):
    """Sundays: a short 'your week with Mindy' for anyone who saved something this week."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=7)).replace(microsecond=0).isoformat()
    rows = db.q("SELECT u.id, COUNT(i.id) AS saved FROM users u JOIN items i ON i.user_id=u.id WHERE i.created_at>=? GROUP BY u.id", (since,))
    for r in rows:
        upcoming = len(db.upcoming(r["id"], 50))
        await deliver(db, r["id"], f"🧠 *Your week with Mindy*\n{r['saved']} things saved, {upcoming} reminders coming up.",
                      [("upcoming", "See reminders"), ("help", "What else?")], "mindy_weekly", [str(r["saved"]), str(upcoming)], now)
    return len(rows)
