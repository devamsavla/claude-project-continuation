"""Instagram messaging client (Instagram API with Instagram Login).
Docs: https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api
Rules that shape Mindy on Instagram:
- Mindy can only reply within 24 hours of the person's last message, so reminders go out on WhatsApp or the app.
- Text is limited to 1,000 bytes and there are no message templates.
- One-to-one only: Instagram group chats are not supported by the API.
Without IG_TOKEN it runs in dry-run mode: messages go to `outbox`."""
import logging
import re

import httpx

from .config import settings

log = logging.getLogger("mindy.instagram")


def _plain(text: str) -> str:
    """WhatsApp-style *bold* and _italic_ show as raw symbols on Instagram, so strip them."""
    text = re.sub(r"\*(\S[^*\n]*?)\*", r"\1", text)
    return re.sub(r"(?<![\w/])_(\S[^_\n]*?)_(?![\w/])", r"\1", text)


def _fit(text: str, limit: int = 1000) -> str:
    b = text.encode("utf-8")
    return text if len(b) <= limit else b[:limit - 3].decode("utf-8", "ignore") + "…"


class Instagram:
    channel = "ig"

    def __init__(self):
        self.outbox: list[dict] = []
        self.base = f"https://graph.instagram.com/{settings.graph_version}"

    async def _post(self, payload: dict) -> dict:
        if not settings.instagram_live:
            self.outbox.append(payload)
            log.info("DRY-RUN instagram %s", payload)
            return {"dry_run": True}
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{self.base}/{settings.ig_user_id or 'me'}/messages", json=payload,
                             headers={"Authorization": f"Bearer {settings.ig_token}"})
            if r.status_code >= 400:
                log.error("Instagram error %s: %s", r.status_code, r.text)
            return r.json()

    @staticmethod
    def _id(to: str) -> str:
        return to[3:] if to.startswith("ig:") else to

    async def text(self, to: str, body: str, reply_to: str | None = None, preview_url: bool = True):
        return await self._post({"recipient": {"id": self._id(to)}, "message": {"text": _fit(_plain(body))}})

    async def buttons(self, to: str, body: str, buttons: list[tuple[str, str]], header: str | None = None):
        """Instagram quick replies stand in for WhatsApp reply buttons."""
        if not buttons:
            return await self.text(to, body)
        qr = [{"content_type": "text", "title": t[:20], "payload": i} for i, t in buttons[:13]]
        return await self._post({"recipient": {"id": self._id(to)}, "message": {"text": _fit(_plain(body)), "quick_replies": qr}})

    async def list_menu(self, to, body, button, rows, section="Options"):
        lines = "\n".join(f"• {t}: {d}" for _, t, d in rows[:10])
        return await self.text(to, f"{body}\n{lines}")

    async def template(self, to, name, params, lang=None):
        log.info("Instagram has no templates; outside the 24-hour window this message can't be sent (%s)", name)
        return {"skipped": "outside_window"}

    async def react(self, to: str, message_id: str, emoji: str):
        return {"skipped": "reactions"}

    async def read_and_typing(self, message_id: str):
        return {"skipped": "typing"}

    async def location(self, to, lat, lng, name="", address=""):
        return await self.text(to, f"📍 https://www.google.com/maps/search/?api=1&query={lat},{lng}")

    async def link_button(self, to, body, label, url):
        return await self.text(to, f"{body}\n{label}: {url}")

    async def audio(self, to, link):
        return {"ok": False}

    async def image(self, to, link, caption=""):
        return await self.text(to, f"{caption}\n{link}".strip())

    async def document(self, to, link, filename, caption=""):
        return await self.text(to, f"{caption or filename}\n{link}".strip())

    async def download_media(self, url: str):
        """Instagram webhooks carry a CDN URL instead of a media id."""
        if not url or not url.startswith("http"):
            return None, None
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
                r = await c.get(url)
                return r.content, r.headers.get("content-type", "image/jpeg").split(";")[0]
        except httpx.HTTPError:
            return None, None


ig = Instagram()


def normalise(event: dict) -> dict | None:
    """Turns one Instagram `messaging` event into the same shape the WhatsApp handler uses."""
    m = event.get("message")
    sender = (event.get("sender") or {}).get("id")
    if not m or not sender or m.get("is_echo") or m.get("is_deleted"):
        return None
    base = {"from": f"ig:{sender}", "id": m.get("mid"), "channel": "ig"}
    if m.get("quick_reply"):
        return {**base, "type": "interactive", "interactive": {"button_reply": {"id": m["quick_reply"].get("payload", "")}}}
    text = m.get("text") or ""
    for a in m.get("attachments") or []:
        t, p = a.get("type"), a.get("payload") or {}
        if t in ("ig_reel", "reel", "ig_post", "share", "story_mention"):
            title = p.get("title") or ""
            url = p.get("url") or ""
            kind = "Reel" if t in ("ig_reel", "reel") else "Story mention" if t == "story_mention" else "Post"
            body = f"{text} {kind}: {title} {url}".strip()
            return {**base, "type": "text", "text": {"body": body}, "share": kind.lower()}
        if t == "image":
            return {**base, "type": "image", "image": {"url": p.get("url"), "caption": text}}
        if t in ("video", "audio", "file"):
            return {**base, "type": "document" if t == "file" else t, ("document" if t == "file" else t): {"url": p.get("url"), "caption": text}}
    if text:
        return {**base, "type": "text", "text": {"body": text}}
    return None
