"""WhatsApp Cloud API client.
Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
Without WA_TOKEN it runs in dry-run mode: messages go to `outbox` (used by tests and local dev)."""
import hashlib
import hmac
import logging

import httpx

from .config import settings

log = logging.getLogger("mindy.whatsapp")


def verify_signature(raw_body: bytes, header: str | None, secret: str | None = None) -> bool:
    """Meta signs every webhook POST with X-Hub-Signature-256 = sha256=HMAC(app_secret, body)."""
    secret = settings.wa_app_secret if secret is None else secret
    if not secret:
        return True  # dev mode: no secret configured
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


class WhatsApp:
    channel = "wa"

    def __init__(self):
        self.outbox: list[dict] = []
        self.base = f"https://graph.facebook.com/{settings.graph_version}"

    @property
    def _headers(self):
        return {"Authorization": f"Bearer {settings.wa_token}"}

    async def _post(self, payload: dict) -> dict:
        payload = {"messaging_product": "whatsapp", **payload}
        if not settings.whatsapp_live:
            self.outbox.append(payload)
            log.info("DRY-RUN send %s", payload)
            return {"dry_run": True}
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{self.base}/{settings.wa_phone_number_id}/messages", json=payload, headers=self._headers)
            if r.status_code >= 400:
                log.error("WhatsApp error %s: %s", r.status_code, r.text)
            return r.json()

    # ---- sending ----
    async def text(self, to: str, body: str, reply_to: str | None = None, preview_url: bool = True):
        p = {"to": to, "type": "text", "text": {"body": body[:4096], "preview_url": preview_url}}
        if reply_to:
            p["context"] = {"message_id": reply_to}
        return await self._post(p)

    async def buttons(self, to: str, body: str, buttons: list[tuple[str, str]], header: str | None = None):
        """Up to 3 reply buttons, titles max 20 characters."""
        inter = {"type": "button", "body": {"text": body[:1024]},
                 "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t[:20]}} for i, t in buttons[:3]]}}
        if header:
            inter["header"] = {"type": "text", "text": header[:60]}
        return await self._post({"to": to, "type": "interactive", "interactive": inter})

    async def list_menu(self, to: str, body: str, button: str, rows: list[tuple[str, str, str]], section="Options"):
        """Up to 10 rows: (id, title<=24, description<=72)."""
        inter = {"type": "list", "body": {"text": body[:1024]},
                 "action": {"button": button[:20], "sections": [{"title": section[:24], "rows": [
                     {"id": i, "title": t[:24], "description": d[:72]} for i, t, d in rows[:10]]}]}}
        return await self._post({"to": to, "type": "interactive", "interactive": inter})

    async def template(self, to: str, name: str, params: list[str], lang: str | None = None):
        """Business-initiated messages outside the 24-hour window must use an approved template."""
        comp = [{"type": "body", "parameters": [{"type": "text", "text": p[:1000]} for p in params]}] if params else []
        return await self._post({"to": to, "type": "template",
                                 "template": {"name": name, "language": {"code": lang or settings.template_lang}, "components": comp}})

    async def login_code(self, to: str, code: str, name: str | None = None, lang: str | None = None):
        """Sign-in code as an Authentication template (body + copy-code button both carry the code)."""
        comp = [{"type": "body", "parameters": [{"type": "text", "text": code}]},
                {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": code}]}]
        return await self._post({"to": to, "type": "template",
                                 "template": {"name": name or settings.login_template, "language": {"code": lang or settings.template_lang}, "components": comp}})

    async def image(self, to: str, link: str, caption: str = ""):
        return await self._post({"to": to, "type": "image", "image": {"link": link, "caption": caption[:1024]}})

    async def document(self, to: str, link: str, filename: str, caption: str = ""):
        return await self._post({"to": to, "type": "document", "document": {"link": link, "filename": filename, "caption": caption[:1024]}})

    async def react(self, to: str, message_id: str, emoji: str):
        return await self._post({"to": to, "type": "reaction", "reaction": {"message_id": message_id, "emoji": emoji}})

    async def read_and_typing(self, message_id: str):
        """Marks the message read (blue ticks) and shows the typing indicator while Mindy thinks."""
        return await self._post({"status": "read", "message_id": message_id, "typing_indicator": {"type": "text"}})

    # ---- media ----
    async def download_media(self, media_id: str) -> tuple[bytes, str] | tuple[None, None]:
        if not settings.whatsapp_live:
            return None, None
        async with httpx.AsyncClient(timeout=30) as c:
            meta = (await c.get(f"{self.base}/{media_id}", headers=self._headers)).json()
            url, mime = meta.get("url"), meta.get("mime_type", "application/octet-stream")
            if not url:
                return None, None
            r = await c.get(url, headers=self._headers)
            return r.content, mime


wa = WhatsApp()
