"""Mindy on Telegram. Telegram is the open channel: messages are free, there's no 24-hour window and no paid
templates, and bots may chat about anything. So on Telegram Mindy also answers open questions (cheap model),
and reminders sent here cost nothing.
Without TELEGRAM_BOT_TOKEN it runs in dry-run mode: messages go to `outbox`.
Setup: create a bot with @BotFather, then call setWebhook with url=https://api.../webhook/telegram and
secret_token=TELEGRAM_WEBHOOK_SECRET (see README)."""
import logging

import httpx

from .config import settings

log = logging.getLogger("mindy.telegram")


def _plain(text: str) -> str:
    return text.replace("*", "").replace("_", "")


class Telegram:
    channel = "tg"

    def __init__(self):
        self.outbox: list[dict] = []

    @property
    def base(self):
        return f"https://api.telegram.org/bot{settings.tg_token}"

    @staticmethod
    def _chat(to: str) -> str:
        return to.removeprefix("tg:")

    async def _call(self, method: str, payload: dict) -> dict:
        if not settings.telegram_live:
            self.outbox.append({"method": method, **payload})
            log.info("DRY-RUN telegram %s %s", method, payload)
            return {"dry_run": True}
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{self.base}/{method}", json=payload)
            if r.status_code >= 400:
                log.error("Telegram error %s: %s", r.status_code, r.text)
            return r.json()

    async def text(self, to, body, reply_to=None, preview_url=True):
        p = {"chat_id": self._chat(to), "text": _plain(body)[:4096], "link_preview_options": {"is_disabled": not preview_url}}
        return await self._call("sendMessage", p)

    async def buttons(self, to, body, buttons, header=None):
        if not buttons:
            return await self.text(to, body)
        kb = [[{"text": t, "callback_data": i[:64]}] for i, t in buttons[:8]]
        return await self._call("sendMessage", {"chat_id": self._chat(to), "text": _plain(body)[:4096], "reply_markup": {"inline_keyboard": kb}})

    async def link_button(self, to, body, label, url):
        if not url.startswith("https://"):
            return await self.text(to, f"{body}\n{url}")
        return await self._call("sendMessage", {"chat_id": self._chat(to), "text": _plain(body),
                                                "reply_markup": {"inline_keyboard": [[{"text": label, "url": url}]]}})

    async def location(self, to, lat, lng, name="", address=""):
        return await self._call("sendLocation", {"chat_id": self._chat(to), "latitude": lat, "longitude": lng})

    async def list_menu(self, to, body, button, rows, section="Options"):
        return await self.buttons(to, body, [(i, t) for i, t, _ in rows])

    async def react(self, to, message_id, emoji):
        mid = str(message_id).rsplit(":", 1)[-1]
        if not mid.isdigit():
            return None
        return await self._call("setMessageReaction", {"chat_id": self._chat(to), "message_id": int(mid), "reaction": [{"type": "emoji", "emoji": "👍" if emoji not in ("👍", "❤", "🔥", "🎉") else emoji}]})

    async def read_and_typing(self, message_id):
        return None  # sendChatAction needs the chat id; typing is sent in handle() via typing()

    async def typing(self, to):
        return await self._call("sendChatAction", {"chat_id": self._chat(to), "action": "typing"})

    async def audio(self, to, link):
        return await self._call("sendAudio", {"chat_id": self._chat(to), "audio": link})

    async def image(self, to, link, caption=""):
        return await self._call("sendPhoto", {"chat_id": self._chat(to), "photo": link, "caption": _plain(caption)[:1024]})

    async def document(self, to, link, filename, caption=""):
        return await self._call("sendDocument", {"chat_id": self._chat(to), "document": link, "caption": _plain(caption)[:1024]})

    async def template(self, to, name, params, lang=None):
        return await self.text(to, " ".join(params))  # Telegram has no templates or window

    async def download_media(self, file_id: str):
        if not settings.telegram_live:
            return None, None
        async with httpx.AsyncClient(timeout=60) as c:
            meta = (await c.get(f"{self.base}/getFile", params={"file_id": file_id})).json()
            path = (meta.get("result") or {}).get("file_path")
            if not path:
                return None, None
            r = await c.get(f"https://api.telegram.org/file/bot{settings.tg_token}/{path}")
            ext = path.rsplit(".", 1)[-1].lower()
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "mp4": "video/mp4", "oga": "audio/ogg", "ogg": "audio/ogg",
                    "mp3": "audio/mpeg", "m4a": "audio/mp4", "pdf": "application/pdf", "webp": "image/webp"}.get(ext, "application/octet-stream")
            return r.content, mime


tg = Telegram()


def normalise(update: dict) -> tuple[dict | None, str | None]:
    """Turns a Telegram update into the same message shape the WhatsApp handler uses."""
    if "callback_query" in update:
        q = update["callback_query"]
        chat = q["message"]["chat"]["id"]
        name = (q.get("from") or {}).get("first_name")
        return ({"from": f"tg:{chat}", "id": f"tg:cb:{q['id']}", "type": "interactive", "channel": "tg", "cb": q["id"],
                 "interactive": {"button_reply": {"id": q.get("data", "")}}}, name)
    m = update.get("message") or update.get("edited_message") or update.get("channel_post")
    if not m or m.get("chat", {}).get("type") not in ("private", None):
        return None, None
    chat, name = m["chat"]["id"], (m.get("from") or {}).get("first_name")
    base = {"from": f"tg:{chat}", "id": f"tg:{chat}:{m['message_id']}", "channel": "tg"}
    fwd = m.get("forward_origin") or m.get("forward_from_chat")
    caption = m.get("caption", "")
    if "text" in m:
        text = m["text"]
        if text.startswith("/start"):
            text = text.split(" ", 1)[1] if " " in text else "hi"
        share = None
        if fwd:  # a post forwarded from a channel or chat: save it like a shared reel
            src = (fwd.get("chat") or fwd).get("title") or (fwd.get("sender_user") or {}).get("first_name") or "Telegram"
            text, share = f"{text}\n(from {src} on Telegram)", "telegram"
        return {**base, "type": "text", "text": {"body": text}, "share": share}, name
    if "photo" in m:
        return {**base, "type": "image", "image": {"id": m["photo"][-1]["file_id"], "caption": caption, "mime_type": "image/jpeg"}}, name
    for kind, key in (("video", "video"), ("audio", "audio"), ("audio", "voice"), ("document", "document"), ("video", "video_note")):
        if key in m:
            f = m[key]
            return {**base, "type": kind, kind: {"id": f["file_id"], "caption": caption, "mime_type": f.get("mime_type", ""), "filename": f.get("file_name", key)}}, name
    if "location" in m:
        loc = m["location"]
        return {**base, "type": "location", "location": {"latitude": loc["latitude"], "longitude": loc["longitude"]}}, name
    return {**base, "type": "unsupported"}, name
