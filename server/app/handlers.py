"""Turns one inbound message (WhatsApp or Instagram) into Mindy's reply.
One brain, many channels: a reply always goes back on the channel the message came from,
and reminders go out on whichever channel can still reach the person (see `deliver`)."""
import asyncio
import logging
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, available_timezones

import re

from . import brain, care, hooks, llm, more, places, skills
from .config import settings
from .db import DB
from .instagram import ig
from .telegram import tg
from .whatsapp import wa

log = logging.getLogger("mindy.handlers")
CLIENTS = {"wa": wa, "ig": ig, "tg": tg}

# Best-guess timezone from the phone number's country code. Users can change it: "timezone Europe/Paris".
CC_TZ = {"44": "Europe/London", "353": "Europe/Dublin", "33": "Europe/Paris", "49": "Europe/Berlin", "34": "Europe/Madrid",
         "39": "Europe/Rome", "31": "Europe/Amsterdam", "91": "Asia/Kolkata", "971": "Asia/Dubai", "65": "Asia/Singapore",
         "61": "Australia/Sydney", "1": "America/New_York", "55": "America/Sao_Paulo", "52": "America/Mexico_City", "27": "Africa/Johannesburg",
         "234": "Africa/Lagos", "254": "Africa/Nairobi", "81": "Asia/Tokyo", "82": "Asia/Seoul", "62": "Asia/Jakarta"}


def tz_for(ext: str) -> str:
    if ext.startswith(("ig:", "tg:")):
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
CHANNEL_NAME = {"wa": "WhatsApp", "ig": "Instagram", "tg": "Telegram", "sms": "SMS"}
WELCOME["sms"] = more.SMS_WELCOME
WELCOME["tg"] = ("Hi{name}! I'm Mindy 🧠 your tech friend.\n\nSend me anything to remember, forward posts from channels, ask me anything, "
                 "send a video with “mp3” or “compress”, forward a suspicious message to check it, or type “Ramesh owes me 500”.\n\n"
                 "Reminders here are free and arrive any time. Your timezone is {tz} (reply “timezone Asia/Kolkata” to change).")
HELP += ("\n• *Tech friend*: _book an uber to Phoenix Mall_, _pay ₹500 to name@upi_, send a screenshot and ask _where do I tap?_"
         "\n• *Scam check*: forward any message or link\n• *Khata*: _Ramesh owes me 500_, _show khata_, _remind Ramesh_"
         "\n• *Files*: send a video with _mp3_ or _compress_\n• *Family*: _family 123456_ to link with family")


def fmt_local(dt_utc_iso: str, tz: str) -> str:
    d = datetime.fromisoformat(dt_utc_iso).astimezone(ZoneInfo(tz))
    return f"{d:%a} {d.day} {d:%b}, {d:%H:%M}"


# the conversation in progress: (client, the sender's id on that channel)
_CONV: ContextVar[tuple] = ContextVar("conv", default=(wa, ""))
_USER: ContextVar[dict | None] = ContextVar("user", default=None)
_VOICE: ContextVar[bool] = ContextVar("voice", default=False)
CMD_RX = re.compile(r"^(remind|add |check|scam|show|my |what|where|how|help|khata|link|login|timezone|language|call yourself|split|gift|wishlist|staff|customer|bill )", re.I)


class Mindy:
    def __init__(self, db: DB):
        self.db = db

    # -- reply helpers: always answer on the channel the message came from
    async def _out(self, text: str) -> str:
        """Every reply passes through here: the person's own name for Mindy, their language, and a voice copy if they want one."""
        u = _USER.get()
        if not u:
            return text
        text = more.rename_out(text, u)
        if u.get("lang") and u["lang"] != "en":
            text = await asyncio.to_thread(more.translate, text, u["lang"], str(u["id"]))
        if _VOICE.get() and u.get("voice"):
            try:
                audio = await asyncio.to_thread(llm.tts, re.sub(r"[*_~]|https?://\S+", "", text)[:900], u.get("lang") or "en")
                client, to = _CONV.get()
                if audio and hasattr(client, "audio"):
                    await client.audio(to, skills.store_media(audio, "mp3"))
            except Exception:
                log.exception("voice reply failed")
        return text

    async def say(self, text: str, **kw):
        client, to = _CONV.get()
        return await client.text(to, await self._out(text), **kw)

    async def ask(self, text: str, buttons):
        client, to = _CONV.get()
        return await client.buttons(to, await self._out(text), buttons)

    async def links(self, text: str, links):
        client, to = _CONV.get()
        if not links:
            return await self.say(text)
        extra = "".join(f"\n{l}: {u}" for l, u in links[1:])
        return await client.link_button(to, await self._out(text) + extra, links[0][0], links[0][1])

    async def more_reply(self, r: dict):
        """Sends a reply from the skills module: notifications to others, an app deep link, buttons or links."""
        user = _USER.get()
        for uid, body, btns in r.get("notify") or []:
            try:
                await deliver(self.db, uid, body, btns, settings.reminder_template, [body.replace("*", "")[:900]], title="Mindy")
            except Exception:
                log.exception("notify failed")
        text, links = r["text"], list(r.get("links") or [])
        if r.get("app") and user:
            links.append((r["app"][0], more.magic_link(self.db, user["id"], r["app"][1])))
        if r.get("flow") and settings.flow_person_id and _CONV.get()[0] is wa:
            client, to = _CONV.get()
            return await client.flow(to, settings.flow_person_id, await self._out(text), "Add a person", "PERSON")
        if r.get("list"):
            client, to = _CONV.get()
            if links:
                text += "".join(f"\n{l}: {u}" for l, u in links)
            return await client.list_menu(to, await self._out(text), "Open", [tuple(x) for x in r["list"]][:10], "Mindy")
        if r.get("buttons"):
            if links:
                text += "".join(f"\n{l}: {u}" for l, u in links)
            return await self.ask(text, r["buttons"])
        if links:
            return await self.links(text, links)
        return await self.say(text)

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
        _USER.set(user)
        _VOICE.set(False)
        if channel == "sms" and mtype == "text":
            menu = self.db.one("SELECT v FROM kv WHERE k=?", (f"sms_menu:{ext}",))
            b = msg["text"]["body"].strip()
            if menu and b.isdigit() and 0 < int(b) <= len(menu["v"].split("|")):
                msg = {**msg, "type": "interactive", "interactive": {"button_reply": {"id": menu["v"].split("|")[int(b) - 1]}}}
                mtype = "interactive"
        self.db.touch_inbound(user["id"], ext)
        await client.read_and_typing(mid)
        if channel == "tg":
            await tg.typing(ext)
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
                await self.on_location(user, msg["location"])
            elif mtype == "text":
                await self.on_text(user, body, mid, msg.get("share"))
                await self.maybe_ask(user)
            else:
                await self.say("I can't open that type of message yet, but text, links, photos and documents all work.")
        except Exception:
            log.exception("handler failed")
            await self.say("Sorry, something went wrong on my side. Try that again in a moment?")

    async def maybe_ask(self, user):
        """Mindy asks: one tap question at the end of a conversation the person started (free on every channel)."""
        try:
            if not settings.ask_questions or user.get("_new") or self.db.one("SELECT 1 FROM kv WHERE k LIKE ? LIMIT 1", (f"await_%:{user['id']}",)):
                return
            last = (self.db.one("SELECT body FROM messages WHERE user_id=? AND direction='in' ORDER BY id DESC LIMIT 1", (user["id"],)) or {}).get("body") or ""
            if re.match(r"^(login|log in|link|code|app|help|timezone|export|delete|report|stop|human)\b", last.lower().strip()):
                return
            tq = more.tail_question(self.db, user)
            if tq:
                await (self.ask(tq[0], tq[1]) if tq[1] else self.say(tq[0]))
        except Exception:
            log.exception("tail question failed")

    @staticmethod
    def _text_of(msg: dict) -> str:
        t = msg.get("type")
        if t == "text":
            return msg["text"]["body"]
        if t == "interactive":
            i = msg["interactive"]
            if i.get("nfm_reply"):  # a WhatsApp Flow form was submitted
                return "flow:" + (i["nfm_reply"].get("response_json") or "{}")
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
        if low.startswith("family "):
            other = care.join_family(self.db, user["id"], low.split(" ", 1)[1])
            if not other:
                return await self.say("That family code didn't work. Codes last 7 days; ask for a new one in the Mindy app.")
            o = self.db.one("SELECT name FROM users WHERE id=?", (other,))
            return await self.say(f"👨‍👩‍👧 You're now linked with *{(o or {}).get('name') or 'your family'}* on Mindy. They can set gentle reminders for you, "
                                  "and they'll know you're OK when you tap “I took it”.")
        if low in ("took", "took it", "taken", "i took it", "done", "ok", "yes", "haan", "ho gaya", "le li"):
            row = care.took(self.db, user["id"])
            if row:
                await self.care_taken(user, row)
                return await self.say("✅ Noted. Thank you! Your family can see you're on track.")
            if low != "done":
                return await self.say("👍")
        # ---- Mindy asked something and this is the typed answer
        if CMD_RX.match(low) or brain.URL_RE.search(text):
            self.db.x("DELETE FROM kv WHERE k=?", (f"await_q:{user['id']}",))
        fa = more.free_answer(self.db, user, text)
        if fa:
            return await self.more_reply(fa)
        # ---- everyday skills (gifts, staff, vault, safety, code word, wardrobe, languages, trips...): rules first, isolated
        mr = await asyncio.to_thread(more.handle, self.db, user, text, self.button_key(user))
        if mr:
            return await self.more_reply(mr)
        # ---- places: parking, home, "where's my car"
        pa = places.ask(text)
        if pa:
            return await self.send_place(user, *pa)
        if re.match(r"^(i )?(just )?(parked|park kiya|parked here|parking)\b|^save (this|my) (parking|car|home|office)|^(this is|it's) my (home|office|hotel)", low):
            lab = places.label_of(low) or "car"
            note = re.sub(r"^(i )?(just )?(parked|park kiya|parking)( (at|in|on))?\s*", "", text, flags=re.I).strip(" .")
            if places.latest(self.db, user["id"], lab) and note and not re.match(r"^(here|now)$", note.lower()):
                places.add_note(self.db, user["id"], lab, note)
                return await self.say(f"📝 Added to your {lab} spot: *{note}*")
            self.db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"await_place:{user['id']}", lab))
            return await self.say(f"Send me your location now: tap 📎 → *Location* → *Send your current location*." + (f"\nI'll add your note: {note}" if note and lab == "car" else ""))
        if re.search(r"\b(button|buttons|shortcut|shortcuts|home screen)\b", low):
            k = self.button_key(user)
            base = settings.app_url.rstrip("/") + f"/b/{k}"
            return await self.say("📲 Your Mindy buttons. Open one, then tap *Share → Add to Home Screen* (iPhone) or *⋮ → Add to Home screen* (Android):\n"
                                  f"🚗 I parked here: {base}/park\n📍 Where's my car: {base}/car\n🏠 Take me home: {base}/home\n🆘 SOS to family: {base}/sos")
        # ---- tech friend skills (all specific tasks, fine on WhatsApp)
        if re.match(r"^(scam\??|is (this|it) (a )?(scam|fraud|real|safe)\??|check( this)?:?|fraud\??|safe\??)\b", low):
            rest = re.sub(r"^(scam\??|is (this|it) (a )?(scam|fraud|real|safe)\??|check( this)?:?|fraud\??|safe\??)\s*", "", text, flags=re.I)
            if not rest.strip():
                self.db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"await_scam:{user['id']}", "1"))
                return await self.say("🛡️ Forward me the message or link and I'll check it.")
            return await self.scam_reply(user, rest)
        if self.db.one("SELECT v FROM kv WHERE k=?", (f"await_scam:{user['id']}",)):
            self.db.x("DELETE FROM kv WHERE k=?", (f"await_scam:{user['id']}",))
            return await self.scam_reply(user, text)
        if low in ("report", "report it", "report scam", "report this"):
            last = self.db.one("SELECT v FROM kv WHERE k=?", (f"last_check:{user['id']}",))
            if not last:
                return await self.say("Forward the message first, then reply *report*.")
            skills.report_scam(self.db, user["id"], last["v"])
            for url in re.findall(r"(?:https?://|www\.)\S+", last["v"])[:5]:
                skills.report_link(self.db, user["id"], url)
            return await self.say("🙏 Reported. Everyone on Mindy who gets this will now be warned.")
        m = re.match(r"^(?:my )?upi(?: id)?(?: is)?\s+([\w.\-]{2,}@[a-z]{2,})$", low)
        if m:
            self.db.x("UPDATE users SET upi=? WHERE id=?", (m.group(1), user["id"]))
            return await self.say(f"💸 Saved. Payment reminders you send will ask people to pay *{m.group(1)}*.")
        if low in ("khata", "show khata", "my khata", "who owes me", "hisaab", "hisab", "balances", "udhaar"):
            rows = skills.khata_all(self.db, user["id"])
            if not rows:
                return await self.say("📒 Your khata is empty. Try _Ramesh owes me 500_ or _paid Sunil 300_.")
            total = sum(r["balance"] for r in rows)
            lines = "\n".join("• " + skills.balance_line(r) for r in rows[:15])
            return await self.say(f"📒 *Your khata*\n{lines}\n\nNet: {'you get' if total >= 0 else 'you pay'} *₹{abs(total):,}*. Say _remind Ramesh_ to send a payment reminder.")
        m = re.match(r"^remind ([a-z][a-z .']{0,30}?)(?: to pay| about (?:the )?money| for (?:the )?money)?\s*$", low)
        if m and not re.search(r"\b(me|us)\b", m.group(1)):
            b = skills.khata_balance(self.db, user["id"], m.group(1).strip())
            if b["entries"] and b["balance"] > 0:
                me = self.db.one("SELECT * FROM users WHERE id=?", (user["id"],))
                req = skills.pay_request(me, b["person"].title(), b["balance"])
                tip = "" if me.get("upi") else "\n\nTip: send _my upi is yourname@bank_ once and I'll add a tap-to-pay link."
                return await self.links(f"📨 Here's a friendly reminder for *{b['person'].title()}* (₹{b['balance']:,}). Tap, pick their chat, send.{tip}",
                                        [("Send on WhatsApp", req["whatsapp"])])
        k = skills.parse_khata(text)
        if k:
            b = skills.khata_add(self.db, user["id"], k, text)
            return await self.say(f"📒 Noted. {skills.balance_line(b)}.")
        d = skills.do_it(text)
        if d:
            return await self.links(d["reply"], d["links"])
        if share or re.search(r"(?:https?://|www\.)\S+", text):
            chk = skills.check_message(self.db, text, use_ai=False)
            if chk["verdict"] == "scam":
                self.db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"last_check:{user['id']}", text))
                return await self.say(chk["reply"])
        if share:  # a reel or post shared from Instagram: always save it, then offer to make it real
            um = brain.URL_RE.search(text)
            item = await asyncio.to_thread(hooks.smart_save, self.db, user["id"], text, um.group(0) if um else None, share)
            return await self.ask(hooks.save_reply(item), [(f"do:{item['id']}:{a}", l) for a, l in hooks.actions_for(item)[:3]])
        r = await asyncio.to_thread(brain.route, text, tz, None, str(user["id"]))
        intent = r.get("intent")
        if intent == "help":
            return await self.say(HELP)
        if intent == "save":
            um = brain.URL_RE.search(text)
            url = um.group(0) if um else None
            src = "reel" if url and "instagram.com" in url else "link" if url else "note"
            item = await asyncio.to_thread(hooks.smart_save, self.db, user["id"], r.get("text") or text, url, src)
            await self.react(mid, "🧠")
            if item.get("rkind") in (None, "other", "idea") and not url:
                return await self.say(f"Saved to *{item['collection']}*.", reply_to=mid, preview_url=False)
            return await self.ask(hooks.save_reply(item), [(f"do:{item['id']}:{a}", l) for a, l in hooks.actions_for(item)[:3]])
        if intent == "out_of_scope" or (intent == "ask" and not self.db.search(user["id"], r.get("text") or text) and _CONV.get()[0] is tg):
            client, _ = _CONV.get()
            if client is tg:  # Telegram allows open chat; WhatsApp does not
                ans = await asyncio.to_thread(llm.chat, text[:3000], "You are Mindy, a warm, practical tech friend. Answer briefly and clearly.", who=str(user["id"]), max_tokens=600)
                return await self.say(ans or "I'm out of thinking power for today. Try again tomorrow, or ask me to save or remind something.")
            if intent == "out_of_scope":
                return await self.say("On WhatsApp I stick to remembering, reminders, plans, family, scam checks and getting things done. "
                                      f"For anything else, ask me on Telegram: https://t.me/{settings.tg_username}")
        if intent == "ask":
            items = self.db.search(user["id"], r.get("text") or text)
            reply = await asyncio.to_thread(brain.answer, text, items, str(user["id"]))
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
        mb = await asyncio.to_thread(more.on_button, self.db, user, bid)
        if mb:
            return await self.more_reply(mb)
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
        if bid.startswith("do:"):
            _, iid, action = bid.split(":", 2)
            item = self.db.one("SELECT * FROM items WHERE id=? AND user_id=?", (int(iid), user["id"]))
            if not item:
                return await self.say("I couldn't find that save any more.")
            res = await asyncio.to_thread(hooks.do_action, self.db, user, item, action)
            return await self.say(res["reply"])
        if bid.startswith("place:"):
            _, pid, lab = bid.split(":", 2)
            if lab == "spot":
                return await self.say("📍 Saved. Ask me for it any time.")
            places.set_label(self.db, user["id"], int(pid), lab)
            return await self.say(places_saved_text(lab))
        if bid.startswith("took:"):
            row = care.took(self.db, user["id"], int(bid[5:]))
            if row:
                await self.care_taken(user, row)
                return await self.say("✅ Thank you! Noted.")
            return await self.say("👍")
        if bid.startswith("csnooze:"):
            row = self.db.one("SELECT * FROM care_log WHERE id=? AND user_id=?", (int(bid[8:]), user["id"]))
            if row:
                due = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(microsecond=0).isoformat()
                self.db.x("UPDATE care_log SET alerted_at=? WHERE id=?", (due, row["id"]))  # don't alert for this one
                self.db.add_reminder(user["id"], row["text"], due, kind="care", set_by=row["set_by"])
                return await self.say("OK, I'll remind you again in 15 minutes. 🙂")
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

    def button_key(self, user):
        import secrets as _s
        row = self.db.one("SELECT button_key FROM users WHERE id=?", (user["id"],))
        if row and row.get("button_key"):
            return row["button_key"]
        k = _s.token_urlsafe(9)
        self.db.x("UPDATE users SET button_key=? WHERE id=?", (k, user["id"]))
        return k

    async def on_location(self, user, loc):
        pending = self.db.one("SELECT v FROM kv WHERE k=?", (f"await_place:{user['id']}",))
        label = pending["v"] if pending else places.label_of(f"{loc.get('name') or ''} {loc.get('address') or ''}") if loc.get("name") else None
        self.db.x("DELETE FROM kv WHERE k=?", (f"await_place:{user['id']}",))
        pid = places.save(self.db, user["id"], float(loc["latitude"]), float(loc["longitude"]), label, name=loc.get("name") or loc.get("address") or "")
        if label:
            return await self.say(places_saved_text(label))
        return await self.ask("📍 Got it. What is this place?", [(f"place:{pid}:car", "🚗 My car"), (f"place:{pid}:home", "🏠 Home"), (f"place:{pid}:spot", "📍 Just save")])

    async def send_place(self, user, label, mode):
        p = places.latest(self.db, user["id"], label)
        if not p:
            hint = "Send me your location (📎 → Location) when you park, and I'll remember it." if label == "car" else \
                f"I don't have your {label} saved yet. Send me the location (📎 → Location) and say it's {label}."
            return await self.say(hint)
        client, to = _CONV.get()
        await client.location(to, p["lat"], p["lng"], {"car": "Your car", "home": "Home"}.get(label, label.title()), p.get("note") or "")
        if p.get("photo"):
            await client.image(to, p["photo"], "The photo you took")
        ago_txt = fmt_local(p["created_at"], user["tz"])
        lk = places.links(p, mode)
        note = f"\nYour note: *{p['note']}*" if p.get("note") else ""
        return await self.links(f"{'🚗 Your car' if label == 'car' else '📍 ' + label.title()} (saved {ago_txt}).{note}\nTap to go there. *Street View* shows the spot in 3D.", lk[:2])

    async def scam_reply(self, user, text):
        chk = await asyncio.to_thread(skills.check_message, self.db, text, str(user["id"]))
        self.db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"last_check:{user['id']}", text))
        return await self.say(chk["reply"])

    async def care_taken(self, user, row):
        from .realtime import hub
        await hub.send_many(care.carers(self.db, row), {"type": "care.taken", "user": user["id"], "name": user.get("name") or "Family",
                                                        "text": row["text"], "log": row["id"]})

    # ------------------------------------------------------------ media
    async def style_media(self, user, t, ref, caption):
        """Photos with a purpose: wardrobe items, 'this is me' for try-on, try-on itself, and receipts to split."""
        low = caption.lower()
        if t != "image" or not low:
            return None
        client, to = _CONV.get()
        if re.search(r"\b(wardrobe|closet|my clothes|almirah)\b", low):
            data, mime = await client.download_media(ref)
            desc = await asyncio.to_thread(llm.chat, "Describe this clothing item in under 8 words: colour, type, style. Then ' | ' and when to wear it (2-4 words).",
                                           image=data, mime=mime or "image/jpeg", who=str(user["id"]), max_tokens=40) if data else None
            title = (desc or re.sub(r"(?i)\b(wardrobe|closet|my clothes|almirah)\b", "", caption).strip() or "Clothing item").strip()
            url = skills.store_media(data, "jpg", keep=True) if data else None
            iid = self.db.save_item(user["id"], "photo", f"{title} {url or ''}".strip(), url=url, collection="Wardrobe")
            self.db.x("UPDATE items SET title=? WHERE id=?", (title.split("|")[0].strip()[:80], iid))
            n = self.db.one("SELECT COUNT(*) n FROM items WHERE user_id=? AND collection='Wardrobe'", (user["id"],))["n"]
            return await self.more_reply(more.R(f"👗 Added to your wardrobe: *{title.split('|')[0].strip()}* ({n} pieces). Ask _what should I wear to…?_ any time.",
                                                app=("See your wardrobe", "brain")))
        if re.match(r"^(this is me|me|my photo|for try ?on|my picture)\b", low):
            data, _ = await client.download_media(ref)
            if not data:
                return await self.say("I couldn't open that photo. Try again?")
            url = skills.store_media(data, "jpg", keep=True)
            self.db.x("UPDATE users SET photo=? WHERE id=?", (url, user["id"]))
            return await self.say("📸 Got you! Now send any clothing photo with *try on* and I'll show you wearing it. Say _delete my photo_ any time.")
        if re.search(r"\b(try ?on|how (will|would) (this|it) look|will (this|it) suit me|on me)\b", low):
            me = self.db.one("SELECT photo FROM users WHERE id=?", (user["id"],))
            if not me or not me.get("photo"):
                return await self.say("First send me one clear photo of yourself (standing, good light) with the caption *this is me*.")
            if not llm.live():
                return await self.say("👗 Try-on switches on once my image AI is connected.")
            if not await asyncio.to_thread(more.tryon_allowed, self.db, user["id"]):
                return await self.say(f"👗 That's your {settings.tryon_daily} free try-ons for today. More tomorrow, or unlimited on Mindy Plus.")
            cloth, mime = await client.download_media(ref)
            person = skills.read_media(me["photo"])
            await self.say("👗 Dressing you up… give me 15 seconds.")
            img = await asyncio.to_thread(llm.try_on, person, cloth, mime or "image/jpeg", str(user["id"])) if (person and cloth) else None
            if not img:
                return await self.say("I couldn't make that one. Try a clearer photo of the clothes on a plain background?")
            return await client.image(to, skills.store_media(img, "png"), "👀 Here's you in it. Send another to compare!")
        if re.search(r"\b(split|bill|receipt)\b", low) and re.search(r"\b(split|between|share)\b", low):
            data, mime = await client.download_media(ref)
            out = await asyncio.to_thread(llm.chat_json, "This is a receipt. Return JSON {total: number, currency: string}. Total = the final amount paid.",
                                          image=data, mime=mime or "image/jpeg", who=str(user["id"]), max_tokens=80) if data and llm.live() else None
            m = re.search(r"(?:between|with|among)\s+(.+)$", caption, re.I)
            if out and out.get("total") and m:
                r = await asyncio.to_thread(more.handle, self.db, user, f"split {out['total']} between {m.group(1)}")
                if r:
                    return await self.more_reply(r)
            return await self.say("🧮 Tell me the total and who to split with, like _split 2400 between Asha, Ben and Kim_.")
        return None

    async def on_media(self, user, msg):
        t = msg["type"]
        m = msg[t]
        caption = m.get("caption", "") or ""
        tz = user["tz"]
        client, _ = _CONV.get()
        ref = m.get("id") or m.get("url")
        tool = skills.wants_tool(caption)
        if tool and t in ("video", "audio", "image", "document"):
            data, mime = await client.download_media(ref)
            if not data:
                return await self.say("I couldn't download that file. Try sending it again?")
            if len(data) > 60_000_000:
                return await self.say("That file is too big for me (60 MB max). Try a shorter clip?")
            await self.say("⚙️ On it, give me a few seconds…")
            out = await asyncio.to_thread(skills.convert, data, mime or m.get("mime_type", ""), tool)
            if not out:
                return await self.say("I can compress videos and photos, and turn videos or voice notes into MP3. That file type didn't work.")
            blob, ext, _ = out
            url = skills.store_media(blob, ext)
            saved = f" ({len(data) // 1024} KB → {len(blob) // 1024} KB)" if tool == "compress" else ""
            if ext == "jpg":
                return await client.image(_CONV.get()[1], url, f"Here you go{saved} ✨")
            return await client.document(_CONV.get()[1], url, f"mindy.{ext}", f"Here you go{saved} ✨")
        styled = await self.style_media(user, t, ref, caption)
        if styled is not None:
            return styled
        if t == "image" and re.search(r"\b(park|parked|parking|car|bike|pillar|level|gaadi)\b", caption.lower()):
            data, mime = await client.download_media(ref)
            url = skills.store_media(data, "jpg", keep=True) if data else None
            p = places.add_note(self.db, user["id"], "car", caption, url)
            if p:
                return await self.say("📸 Added this photo to your parking spot. Ask *where's my car?* later.")
            self.db.x("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (f"await_place:{user['id']}", "car"))
            return await self.say("📸 Got the photo. Now send your location (📎 → Location) so I know where it is.")
        if t in ("image", "document") and re.search(r"\b(read|what does (this|it) say|explain|samjhao|batao|padh|kya likha|meaning|letter|bill|notice)\b", caption.lower()) and llm.live():
            data, mime = await client.download_media(ref)
            if data and (mime or "").startswith("image/"):
                txt = await asyncio.to_thread(brain.read_for_me, data, mime, caption, str(user["id"]))
                if txt:
                    self.db.save_item(user["id"], "photo", f"{caption}: {txt[:300]}", media_id=ref, collection="Documents")
                    return await self.say("📄 " + txt)
        if t == "image":
            data, mime = await client.download_media(ref)
            asks = re.search(r"\?|\b(where|how|what|help|tap|click|press|kaise|kahan|next|stuck|privacy|permission)\b", caption.lower()) or (user.get("simple") and not caption)
            if data and asks:
                help_ = await asyncio.to_thread(skills.screen_help, data, mime or "image/jpeg", caption or "What do I do next?", str(user["id"]))
                if help_ and help_.get("x") is not None and not help_.get("done"):
                    marked = await asyncio.to_thread(skills.circle, data, help_["x"], help_["y"], help_["r"])
                    url = skills.store_media(marked, "jpg")
                    return await client.image(_CONV.get()[1], url, f"👉 {help_['step']}\n\nDo that, then send me the next screenshot.")
                if help_:
                    return await self.say(f"👉 {help_['step']}")
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
        if t == "document" and (re.search(r"statement|bank|passbook|transactions", (caption + " " + m.get("filename", "")).lower())
                                or (m.get("mime_type") or "").endswith("csv")):
            data, mime = await client.download_media(ref)
            from . import money
            txns = await asyncio.to_thread(money.parse_statement, data or b"", mime or m.get("mime_type", ""), m.get("filename", ""))
            if not txns:
                return await self.say("I couldn't read transactions from that file. A CSV export from your bank app works best, or a text PDF (not a photo).")
            n = money.save_spend(self.db, user["id"], txns)
            return await self.more_reply(more.R(f"🔒 Read {len(txns)} transactions ({n} new). I kept only dates, amounts and shop names, and deleted the file.\n\n"
                                                + money.summary_text(self.db, user), app=("See the breakdown", "money")))
        if t == "document":
            self.db.save_item(user["id"], "doc", f"{m.get('filename', 'Document')} {caption}".strip(), media_id=ref, collection="Documents")
            return await self.say(f"📄 Saved *{m.get('filename', 'your document')}* to *Documents*. Ask me for it any time.")
        if t == "audio":
            data, mime = await client.download_media(ref)
            heard = None
            if data and llm.live():
                mp3 = await asyncio.to_thread(skills.convert, data, mime or "audio/ogg", "mp3")
                heard = await asyncio.to_thread(llm.transcribe, mp3[0] if mp3 else data, "mp3", str(user["id"]))
            if heard:
                if not user.get("voice"):
                    await self.say(f"🎙️ I heard: _{heard}_")
                _VOICE.set(True)
                return await self.on_text(user, heard, msg.get("id"), None)
            self.db.save_item(user["id"], "voice", f"Voice note {datetime.now(ZoneInfo(tz)):%d %b %H:%M}", media_id=ref, collection="Voice notes")
            return await self.say("🎙️ Voice note saved. (I understand voice notes once the AI key is switched on.)")
        self.db.save_item(user["id"], t, caption or t, media_id=ref, collection="Media")
        return await self.say("Saved. 👍")


# ---------------------------------------------------------------- outbound (scheduled) messages
def _in_window(last: str | None, now: datetime, hours: float = 23.8) -> bool:
    return bool(last) and (now - datetime.fromisoformat(last)) < timedelta(hours=hours)


def places_saved_text(label: str) -> str:
    return {"car": "🚗 Parking saved. When you need it, just ask *where's my car?*",
            "home": "🏠 Home saved. Say *take me home* any time.",
            "office": "🏢 Office saved. Say *take me to office* any time."}.get(label, f"📍 Saved as *{label}*. Ask for it any time.")


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
        tg_acc = next((a for a in accs if a["channel"] == "tg"), None)
        if wa_acc and _in_window(wa_acc["last_inbound_at"], now):
            await wa.buttons(wa_acc["ext"], body, buttons)  # free inside the 24-hour window
            used.append("wa")
        elif tg_acc:
            await tg.buttons(tg_acc["ext"], body, buttons)  # Telegram is always free
            used.append("tg")
        elif wa_acc and template:
            await wa.template(wa_acc["ext"], template, params)  # paid template outside the window
            used.append("wa")
        elif ig_acc and _in_window(ig_acc["last_inbound_at"], now):
            await ig.buttons(ig_acc["ext"], body, buttons)
            used.append("ig")
    return "+".join(used) or None


async def send_due(db: DB, now: datetime | None = None):
    """Runs every 30 seconds: delivers due reminders on the best available channel."""
    now = now or datetime.now(timezone.utc)
    for r in db.due_reminders(now.replace(microsecond=0).isoformat()):
        if r.get("kind") == "care":
            log_id = care.open_log(db, r)
            setter = db.one("SELECT name FROM users WHERE id=?", (r.get("set_by"),)) if r.get("set_by") and r["set_by"] != r["user_id"] else None
            by = f"\n_From {setter['name']}, with love_ 💚" if setter and setter.get("name") else ""
            used = await deliver(db, r["user_id"], f"💊 *Time for: {r['text']}*{by}\n\nTap when done, or reply *took*.",
                                 [(f"took:{log_id}", "✅ I took it"), (f"csnooze:{log_id}", "⏰ In 15 min")],
                                 settings.care_template, [r["text"]], now, title="💊 " + r["text"], url="/#care")
        else:
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
            db.add_reminder(r["user_id"], r["text"], nxt.astimezone(timezone.utc).isoformat(), r["repeat"], kind=r.get("kind") or "normal", set_by=r.get("set_by"))


async def care_check(db: DB, now: datetime | None = None):
    """Runs every minute: if a family member hasn't confirmed a dose in time, tell the people who care for them."""
    from .realtime import hub
    for row in care.overdue(db, now):
        db.x("UPDATE care_log SET alerted_at=? WHERE id=?", (datetime.now(timezone.utc).replace(microsecond=0).isoformat(), row["id"]))
        who = row.get("name") or "Your family member"
        when = fmt_local(row["due_at"], (db.one("SELECT tz FROM users WHERE id=?", (row["user_id"],)) or {}).get("tz") or "UTC")
        acc = next((a for a in db.accounts(row["user_id"]) if a["channel"] == "wa"), None)
        call = f"\nCall them: https://wa.me/{acc['ext']}" if acc else ""
        for cid in care.carers(db, row):
            await hub.send(cid, {"type": "care.missed", "user": row["user_id"], "name": who, "text": row["text"], "log": row["id"]})
            await deliver(db, cid, f"⚠️ *{who}* hasn't confirmed *{row['text']}* (due {when}).{call}", [],
                          settings.care_alert_template, [who, row["text"]], now, title=f"⚠️ {who} missed {row['text']}", url="/#care")


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
