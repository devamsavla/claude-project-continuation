"""Mindy's understanding layer.
- With ANTHROPIC_API_KEY: Claude routes every message (fast model) and answers questions (smart model).
- Without a key: a rules parser handles the core intents, so the bot still works in dev and tests.
Mindy is deliberately task-specific (memory, reminders, lists, occasions), in line with
WhatsApp's Business Solution terms, which since 15 January 2026 bar general-purpose AI assistants."""
import base64
import json
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil import parser as dparser

from .config import settings

log = logging.getLogger("mindy.brain")
URL_RE = re.compile(r"https?://\S+")
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december"

SYSTEM = """You are Mindy, the memory assistant inside whatsonyourmind, used on WhatsApp.
You only help with: saving things people send (notes, links, photos, documents), finding them later,
reminders, lists, birthdays and occasions, and plans in group chats. Politely decline anything else
in one sentence and say what you can do. Write short, warm, plain British English. No markdown headers.
Use *bold* sparingly (WhatsApp formatting). Never invent saved items: only use what is in CONTEXT."""

ROUTE_TOOL = {
    "name": "route",
    "description": "Classify the user's WhatsApp message and extract fields.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["save", "ask", "remind", "list_add", "list_show", "occasion", "upcoming", "help", "export", "delete_all", "out_of_scope"]},
            "text": {"type": "string", "description": "Cleaned content to save, the reminder text, or the question."},
            "collection": {"type": "string", "description": "Short folder name for saves, e.g. 'Food spots', 'Gift ideas', 'Work'."},
            "tags": {"type": "array", "items": {"type": "string"}},
            "due_local": {"type": "string", "description": "For reminders: ISO 8601 local datetime in the user's timezone, e.g. 2026-11-14T17:30"},
            "repeat": {"type": "string", "enum": ["none", "daily", "weekly", "monthly", "yearly"]},
            "list_name": {"type": "string"},
            "list_entries": {"type": "array", "items": {"type": "string"}},
            "person": {"type": "string"},
            "occasion_kind": {"type": "string", "description": "birthday, anniversary, etc."},
            "month": {"type": "integer"}, "day": {"type": "integer"},
        },
        "required": ["intent"],
    },
}


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=settings.anthropic_key)


# ---------------------------------------------------------------- time parsing
def parse_when(text: str, tz: str, now: datetime | None = None) -> datetime | None:
    """Turns 'tomorrow at 9', 'in 2 hours', 'fri 6pm', 'on 14 nov at 17:30' into an aware datetime."""
    z = ZoneInfo(tz)
    now = (now or datetime.now(z)).astimezone(z)
    t = text.lower()
    m = re.search(r"\bin (\d+|an?|half an?) ?(min|minute|minutes|mins|hour|hours|hr|hrs|day|days|week|weeks)\b", t)
    if m:
        n = {"a": 1, "an": 1, "half an": 0.5, "half a": 0.5}.get(m.group(1), None)
        n = float(m.group(1)) if n is None else n
        unit = m.group(2)
        delta = timedelta(minutes=n) if unit.startswith("m") else timedelta(hours=n) if unit.startswith("h") else timedelta(days=n) if unit.startswith("d") else timedelta(weeks=n)
        return now + delta
    # time of day
    hh, mm = None, 0
    tm = re.search(r"\b(?:at )?(\d{1,2})(?:[:.](\d{2}))? ?(am|pm)\b", t) or re.search(r"\bat (\d{1,2})(?:[:.](\d{2}))?\b", t) or re.search(r"\b(\d{1,2})[:.](\d{2})\b", t)
    if tm:
        hh, mm = int(tm.group(1)), int(tm.group(2) or 0)
        ap = tm.group(3) if tm.lastindex and tm.lastindex >= 3 else None
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
    for word, h in (("morning", 9), ("noon", 12), ("lunchtime", 12), ("afternoon", 15), ("evening", 18), ("tonight", 20)):
        if hh is None and word in t:
            hh = h
    day = None
    if "tomorrow" in t:
        day = (now + timedelta(days=1)).date()
    elif "today" in t or "tonight" in t:
        day = now.date()
    else:
        wd = re.search(r"\b(?:on |next |this )?(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", t)
        dm = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)? ({MONTHS})\b|\b({MONTHS}) (\d{{1,2}})(?:st|nd|rd|th)?\b", t)
        if dm:
            try:
                d = dparser.parse(dm.group(0), default=now.replace(tzinfo=None), dayfirst=True).date()
                if d < now.date():
                    d = d.replace(year=d.year + 1)
                day = d
            except (ValueError, OverflowError):
                day = None
        elif wd:
            target = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(wd.group(1))
            ahead = (target - now.weekday()) % 7 or 7
            day = (now + timedelta(days=ahead)).date()
    if day is None and hh is None:
        return None
    if day is None:
        day = now.date()
        cand = datetime(day.year, day.month, day.day, hh, mm, tzinfo=z)
        return cand if cand > now else cand + timedelta(days=1)
    return datetime(day.year, day.month, day.day, 9 if hh is None else hh, mm, tzinfo=z)


def strip_when(text: str) -> str:
    t = re.sub(r"^(please )?(remind me|reminder|remember)( to| that| about)?\s*", "", text.strip(), flags=re.I)
    t = re.sub(rf"\b(tomorrow|today|tonight|this (morning|afternoon|evening)|in \d+ ?\w+|in an? \w+|at \d{{1,2}}([:.]\d{{2}})? ?(am|pm)?|\d{{1,2}}([:.]\d{{2}})? ?(am|pm)|on (mon|tue|wed|thu|fri|sat|sun)\w*|(next|this) (mon|tue|wed|thu|fri|sat|sun)\w*|(on )?\d{{1,2}}(st|nd|rd|th)? ({MONTHS})|every (day|week|month|year))\b", "", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,.-")
    t = re.sub(r"^(to|that|about)\s+", "", t, flags=re.I)
    return t or text


# ---------------------------------------------------------------- rules router (no API key)
def route_rules(text: str) -> dict:
    t = text.strip()
    low = t.lower()
    if low in ("help", "hi", "hello", "hey", "start", "menu", "/help", "/start"):
        return {"intent": "help"}
    if low in ("what's coming up", "whats coming up", "upcoming", "my reminders", "reminders"):
        return {"intent": "upcoming"}
    if low in ("export", "export my data", "/export"):
        return {"intent": "export"}
    if low in ("delete everything", "delete my data", "/delete"):
        return {"intent": "delete_all"}
    if re.match(r"^(please )?(remind me|reminder)\b", low):
        rep = next((r for r in ("daily", "weekly", "monthly", "yearly") if f"every {r[:-2] if r != 'daily' else 'day'}" in low), "none")
        return {"intent": "remind", "text": strip_when(t), "repeat": rep}
    m = re.match(r"^add (.+?) to (?:my |the )?(.+?) list$", low)
    if m:
        return {"intent": "list_add", "list_name": m.group(2), "list_entries": [e.strip() for e in re.split(r",| and ", m.group(1)) if e.strip()]}
    m = re.match(r"^(?:show|what's on|whats on|send)(?: me)? (?:my |the )?(.+?) list\??$", low)
    if m:
        return {"intent": "list_show", "list_name": m.group(1)}
    m = re.match(rf"^(.+?)'?s? (birthday|anniversary) (?:is )?(?:on )?(.+)$", low)
    if m:
        try:
            d = dparser.parse(m.group(3), dayfirst=True, fuzzy=True)
            return {"intent": "occasion", "person": m.group(1).strip().title(), "occasion_kind": m.group(2), "month": d.month, "day": d.day}
        except (ValueError, OverflowError):
            pass
    if t.endswith("?") or re.match(r"^(what|where|when|which|who|find|show me|did i|have i)\b", low):
        return {"intent": "ask", "text": t}
    coll = "Links" if URL_RE.search(t) else "Notes"
    if "instagram.com/reel" in low or "instagram.com/p/" in low:
        coll = "Reels"
    return {"intent": "save", "text": t, "collection": coll, "tags": []}


# ---------------------------------------------------------------- AI router
def route(text: str, tz: str, now: datetime | None = None) -> dict:
    if not settings.ai_live:
        r = route_rules(text)
        if r["intent"] == "remind":
            when = parse_when(text, tz, now)
            r["due"] = when
        return r
    z = ZoneInfo(tz)
    now = (now or datetime.now(z)).astimezone(z)
    try:
        msg = _client().messages.create(
            model=settings.model_fast, max_tokens=500, system=SYSTEM,
            tools=[ROUTE_TOOL], tool_choice={"type": "tool", "name": "route"},
            messages=[{"role": "user", "content": f"User timezone: {tz}. Local now: {now:%A %Y-%m-%d %H:%M}.\nMessage: {text}"}])
        r = next(b.input for b in msg.content if b.type == "tool_use")
    except Exception as e:  # network or quota trouble: fall back, never drop a message
        log.exception("route failed, using rules: %s", e)
        r = route_rules(text)
    if r.get("intent") == "remind":
        due = None
        if r.get("due_local"):
            try:
                due = datetime.fromisoformat(r["due_local"]).replace(tzinfo=z)
            except ValueError:
                due = None
        r["due"] = due or parse_when(text, tz, now)
    return r


def answer(question: str, items: list[dict]) -> str:
    if not items:
        return "I couldn't find anything saved about that yet. Forward it to me next time and I'll keep it."
    if not settings.ai_live:
        lines = [f"• {i['text'][:140]}" + (f" ({i['collection']})" if i.get("collection") else "") for i in items[:5]]
        return "Here's what I found:\n" + "\n".join(lines)
    ctx = "\n".join(f"[{i['id']}] {i['created_at'][:10]} | {i['collection']} | {i['text']} {i.get('url') or ''}" for i in items)
    msg = _client().messages.create(model=settings.model_smart, max_tokens=400, system=SYSTEM,
                                    messages=[{"role": "user", "content": f"CONTEXT (the user's saved items):\n{ctx}\n\nQUESTION: {question}\n\nAnswer in 1 to 3 short lines."}])
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def read_image(data: bytes, mime: str, caption: str, tz: str) -> dict:
    """Reminders from photos: tickets, invitations, letters, receipts."""
    if not settings.ai_live or not data:
        return {"summary": caption or "Photo", "collection": "Photos", "events": []}
    now = datetime.now(ZoneInfo(tz))
    prompt = (f"User timezone {tz}, local now {now:%A %Y-%m-%d %H:%M}. Caption: {caption or '(none)'}\n"
              "Look at this image. Return JSON only: {\"summary\": one line describing it, \"collection\": short folder name, "
              "\"events\": [{\"text\": what to remind, \"due_local\": ISO local datetime}]}. Include events only for real dates in the image "
              "(tickets, invitations, appointments, bills, expiry dates). For an event, remind 2 hours before its start.")
    msg = _client().messages.create(model=settings.model_smart, max_tokens=600, system=SYSTEM, messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": mime if mime in ("image/jpeg", "image/png", "image/webp", "image/gif") else "image/jpeg", "data": base64.b64encode(data).decode()}},
        {"type": "text", "text": prompt}]}])
    raw = "".join(b.text for b in msg.content if b.type == "text")
    try:
        return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError:
        return {"summary": caption or "Photo", "collection": "Photos", "events": []}


def draft_wish(person: str, kind: str) -> str:
    if not settings.ai_live:
        return f"Happy {kind}, {person}! 🎉 Hope today is as brilliant as you are. Let's celebrate properly soon."
    msg = _client().messages.create(model=settings.model_fast, max_tokens=200, system=SYSTEM, messages=[{"role": "user", "content":
          f"Draft a warm, short WhatsApp {kind} message to {person}. Two sentences, one emoji, no hashtags. Output only the message."}])
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def recipe_from(text: str) -> dict:
    """Turns a saved food reel's caption or note into a recipe card."""
    msg = _client().messages.create(model=settings.model_fast, max_tokens=700, system=SYSTEM, messages=[{"role": "user", "content":
          "From this saved food post, write a recipe card. Return JSON only: {\"title\": str, \"time\": str, \"ingredients\": [str], \"steps\": [str]}. "
          "If the post doesn't say, make a sensible home version and keep it short.\n\nPOST: " + text}])
    raw = "".join(b.text for b in msg.content if b.type == "text")
    try:
        return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError:
        return {"title": "Recipe", "time": "", "ingredients": [], "steps": [raw.strip()]}
