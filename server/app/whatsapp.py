"""WhatsApp Cloud API client.
Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
Without WA_TOKEN it runs in dry-run mode: messages go to `outbox` (used by tests and local dev)."""
import hashlib
import hmac
import logging
import re

import httpx

from . import validate
from .config import settings

log = logging.getLogger("mindy.whatsapp")


def verify_signature(raw_body: bytes, header: str | None, secret: str | None = None) -> bool:
    """Meta signs every webhook POST with X-Hub-Signature-256 = sha256=HMAC(app_secret, body)."""
    secret = settings.wa_app_secret if secret is None else secret
    if not secret:
        if settings.production:
            log.error("Webhook rejected: app secret is not set (WA_APP_SECRET / IG_APP_SECRET). Set it to accept Meta's messages.")
            return False
        return True  # local dev: no secret configured
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


class WhatsApp:
    channel = "wa"

    def __init__(self):
        self.outbox: list[dict] = []
        self.problems: list = []
        self.base = f"https://graph.facebook.com/{settings.graph_version}"

    @property
    def _headers(self):
        return {"Authorization": f"Bearer {settings.wa_token}"}

    async def _post(self, payload: dict) -> dict:
        payload = {"messaging_product": "whatsapp", **payload}
        problems = validate.whatsapp(payload)
        if problems:
            log.error("WhatsApp payload breaks Meta's limits %s: %s", problems, str(payload)[:300])
            self.problems.append((problems, payload))
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
        body = (body or "").strip() or "👍"
        if len(body) > 4096:  # split long replies instead of cutting them off
            cut = body.rfind("\n", 0, 4000)
            cut = cut if cut > 1000 else 4000
            await self.text(to, body[:cut], reply_to, preview_url)
            return await self.text(to, body[cut:], None, preview_url)
        p = {"to": to, "type": "text", "text": {"body": body, "preview_url": preview_url}}
        if reply_to:
            p["context"] = {"message_id": reply_to}
        return await self._post(p)

    async def buttons(self, to: str, body: str, buttons: list[tuple[str, str]], header: str | None = None):
        """Up to 3 reply buttons, titles max 20 characters."""
        if not buttons:
            return await self.text(to, body)
        body = (body or "").strip() or "Choose one:"
        if len(body) > 1024:  # buttons allow 1024 characters: send the long part as text, keep the question with the buttons
            cut = body.rfind("\n", 0, len(body) - 1)
            head, body = (body[:cut], body[cut + 1:]) if 0 < cut and len(body) - cut <= 1024 else (body, "Choose one:")
            await self.text(to, head)
        seen, btns = set(), []
        for i, t in buttons:
            t = (t or "").strip()[:20] or "OK"
            while t in seen:  # titles must be unique
                t = (t[:18] + " " + str(len(seen)))[:20]
            seen.add(t)
            btns.append({"type": "reply", "reply": {"id": i[:256], "title": t}})
            if len(btns) == 3:
                break
        inter = {"type": "button", "body": {"text": body},
                 "action": {"buttons": btns}}
        if header:
            inter["header"] = {"type": "text", "text": header[:60]}
        return await self._post({"to": to, "type": "interactive", "interactive": inter})

    async def list_menu(self, to: str, body: str, button: str, rows: list[tuple[str, str, str]], section="Options"):
        """Up to 10 rows: (id, title<=24, description<=72)."""
        body = (body or "").strip() or "Choose one:"
        inter = {"type": "list", "body": {"text": body[:4096]},
                 "action": {"button": button[:20], "sections": [{"title": section[:24], "rows": [
                     {"id": i, "title": t[:24], "description": d[:72]} for i, t, d in rows[:10]]}]}}
        return await self._post({"to": to, "type": "interactive", "interactive": inter})

    async def template(self, to: str, name: str, params: list[str], lang: str | None = None):
        """Business-initiated messages outside the 24-hour window must use an approved template."""
        # Meta rejects template parameters with newlines, tabs or 5+ spaces in a row (error 132018), or empty ones.
        clean = [re.sub(r" {4,}", "   ", re.sub(r"[\r\n\t]+", " · ", str(p or ""))).strip(" ·")[:1000] or "-" for p in params]
        comp = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in clean]}] if params else []
        return await self._post({"to": to, "type": "template",
                                 "template": {"name": name, "language": {"code": lang or settings.template_lang}, "components": comp}})

    async def login_code(self, to: str, code: str, name: str | None = None, lang: str | None = None):
        """Sign-in code as an Authentication template (body + copy-code button both carry the code)."""
        comp = [{"type": "body", "parameters": [{"type": "text", "text": code}]},
                {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": code}]}]
        return await self._post({"to": to, "type": "template",
                                 "template": {"name": name or settings.login_template, "language": {"code": lang or settings.template_lang}, "components": comp}})

    async def location(self, to: str, lat: float, lng: float, name: str = "", address: str = ""):
        return await self._post({"to": to, "type": "location", "location": {"latitude": lat, "longitude": lng, "name": name[:100], "address": address[:200]}})

    async def link_button(self, to: str, body: str, label: str, url: str):
        body = (body or "").strip() or "Tap below:"
        if not re.match(r"^https?://", url or ""):
            return await self.text(to, f"{body}\n{label}: {url}")
        if len(body) > 1024:
            await self.text(to, body)
            body = "👇"
        """One tappable button that opens a link (Uber, Maps, UPI via /go)."""
        return await self._post({"to": to, "type": "interactive", "interactive": {"type": "cta_url", "body": {"text": body[:1024]},
                                 "action": {"name": "cta_url", "parameters": {"display_text": label[:20], "url": url}}}})

    async def audio(self, to: str, link: str):
        return await self._post({"to": to, "type": "audio", "audio": {"link": link}})

    async def flow(self, to: str, flow_id: str, body: str, cta: str, screen: str):
        """A WhatsApp Flow: a real form inside the chat (published once in WhatsApp Manager, see flows/)."""
        return await self._post({"to": to, "type": "interactive", "interactive": {"type": "flow", "body": {"text": body[:1024]},
            "action": {"name": "flow", "parameters": {"flow_message_version": "3", "flow_id": flow_id, "flow_cta": cta[:20],
                                                       "flow_action": "navigate", "flow_action_payload": {"screen": screen}}}}})

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
            if not url or int(meta.get("file_size") or 0) > MAX_MEDIA:
                return None, None
            r = await c.get(url, headers=self._headers)
            return (r.content, mime) if len(r.content) <= MAX_MEDIA else (None, None)


MAX_MEDIA = 25 * 1024 * 1024  # 25 MB: bigger files are ignored rather than filling the server

wa = WhatsApp()
