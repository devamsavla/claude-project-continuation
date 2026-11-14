"""Mindy's understanding layer. Rules first (free, instant), then the cheapest model (see llm.py) only when the
rules can't tell. Mindy is deliberately task-specific on WhatsApp (memory, reminders, lists, occasions, plans,
family care), in line with WhatsApp's Business Solution terms, which since 15 January 2026 bar general-purpose
AI assistants. Study help and homework hints live in the app only."""
import json
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil import parser as dparser

from . import llm
from .config import settings

log = logging.getLogger("mindy.brain")
URL_RE = re.compile(r"https?://\S+")
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december"

SYSTEM = """You are Mindy, the memory assistant inside whatsonyourmind.
You only help with: saving things people send (notes, links, reels, photos), finding them later, turning saves into
plans, reminders, lists, birthdays, family medicine reminders (never medical advice) and plans with friends.
Politely decline anything else in one sentence. Write short, warm, plain English. Use *bold* sparingly.
Never invent saved items: only use what is in CONTEXT."""

KINDS = ["recipe", "place", "workout", "study", "product", "travel", "event", "idea", "fun", "other"]
KIND_COLLECTION = {"recipe": "Recipes", "place": "Places", "workout": "Fitness", "study": "Study", "product": "Wishlist",
                   "travel": "Travel", "event": "Events", "idea": "Ideas", "fun": "Fun", "other": "Notes"}
KIND_WORDS = {
    "recipe": r"recipe|cook|bake|ingredients|paneer|chicken|pasta|biryani|curry|dessert|cake|air ?fryer|dal|roti|noodles|salad|breakfast|vegan|snack|chai|coffee recipe|how to make",
    "place": r"\bplace\b|\bspot\b|caf[eé]|restaurant|\bbar\b|brunch|street food|dhaba|bakery|rooftop|hidden gem|best .* in |must visit|food spot|eatery|pub|vada pav|chaat",
    "workout": r"workout|gym|abs|yoga|stretch|run(ning)?|pilates|exercise|reps|cardio|hiit|push ?ups?|squats?|mobility|fitness",
    "study": r"study|exam|notes|lecture|learn|tutorial|course|formula|physics|chemistry|maths?|biology|coding|python|interview|dsa|upsc|jee|neet|gate|explained",
    "product": r"buy|deal|sale|amazon|flipkart|myntra|price|discount|outfit|shoes|sneakers|skincare|gadget|review|unboxing|link in bio",
    "travel": r"trip|travel|itinerary|goa|manali|ladakh|kerala|bali|beach|trek|hostel|visa|flight|places to visit|road trip|weekend getaway",
    "event": r"concert|gig|tickets?|festival|match|screening|standup|stand-up|workshop|meetup|launch",
    "idea": r"idea|startup|business|side hustle|tip|hack|productivity|habit|book",
}


def classify_rules(text: str) -> dict:
    low = text.lower()
    scores = {k: len(re.findall(p, low)) for k, p in KIND_WORDS.items()}
    if re.search(r"\b(?:in|at) [A-Z][a-z]+", text) and scores["place"]:
        scores["place"] += 1
    kind = max(scores, key=scores.get) if max(scores.values()) else "other"
    title = re.sub(r"https?://\S+", "", text).strip(" -:|·") or text
    title = re.split(r"[.!?\n]|#", title)[0].strip()[:70] or "Saved post"
    place = None
    m = re.search(r"\b(?:at|in) ([A-Z][\w'&]+(?: [A-Z][\w'&]+){0,3})", re.sub(r"https?://\S+", "", text))
    if m and kind in ("place", "travel", "event"):
        place = m.group(1)
    return {"kind": kind, "title": title[0].upper() + title[1:] if title else title, "place": place,
            "collection": KIND_COLLECTION[kind], "tags": []}


def classify_save(text: str, who: str | None = None) -> dict:
    """What kind of thing is this save, so Mindy can turn it into something real (cook it, go there, revise it)."""
    rules = classify_rules(text)
    if not llm.live() or len(text) < 12:
        return rules
    out = llm.chat_json(
        f"Classify this saved post. Fields: kind (one of {', '.join(KINDS)}), title (max 8 words, what it is), "
        "place (a named venue or city if any, else null), tags (max 3 short words).\nPOST: " + text[:1500],
        SYSTEM, who=who, max_tokens=150)
    if not out or out.get("kind") not in KINDS:
        return rules
    return {"kind": out["kind"], "title": (out.get("title") or rules["title"])[:70], "place": out.get("place") or rules["place"],
            "collection": KIND_COLLECTION[out["kind"]], "tags": [str(t)[:20] for t in (out.get("tags") or [])][:3]}


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


# ---------------------------------------------------------------- router: rules first, AI only when unsure
CONFIDENT = {"help", "upcoming", "export", "delete_all", "list_add", "list_show", "occasion"}


def route(text: str, tz: str, now: datetime | None = None, who: str | None = None) -> dict:
    z = ZoneInfo(tz)
    now = (now or datetime.now(z)).astimezone(z)
    r = route_rules(text)
    if r["intent"] == "remind":
        r["due"] = parse_when(text, tz, now)
        if r["due"] or not llm.live():
            return r
    if r["intent"] in CONFIDENT or not llm.live():
        return r
    if r["intent"] == "save" and not re.search(r"\b(remind|tomorrow|tonight|every|birthday|list|at \d|\d ?(am|pm))\b", text.lower()):
        return r  # a plain save: classify_save handles it, no routing call needed
    out = llm.chat_json(
        f"User timezone: {tz}. Local now: {now:%A %Y-%m-%d %H:%M}.\nMessage: {text[:1500]}\n"
        "Classify. Fields: intent (save, ask, remind, list_add, list_show, occasion, upcoming, help, out_of_scope), text "
        "(cleaned content, reminder text or question), due_local (ISO local datetime for reminders), repeat (none, daily, weekly, "
        "monthly, yearly), list_name, list_entries (array), person, occasion_kind, month, day.", SYSTEM, who=who, max_tokens=250)
    if not out or not out.get("intent"):
        return r
    if out["intent"] == "remind":
        due = None
        if out.get("due_local"):
            try:
                due = datetime.fromisoformat(str(out["due_local"])[:19]).replace(tzinfo=z)
            except ValueError:
                due = None
        out["due"] = due or parse_when(text, tz, now)
    for k in ("collection", "tags"):
        out.setdefault(k, r.get(k))
    return out


def answer(question: str, items: list[dict], who: str | None = None) -> str:
    if not items:
        return "I couldn't find anything saved about that yet. Forward it to me next time and I'll keep it."
    lines = [f"• {i['text'][:140]}" + (f" ({i['collection']})" if i.get("collection") else "") for i in items[:5]]
    ctx = "\n".join(f"[{i['id']}] {i['created_at'][:10]} | {i['collection']} | {i['text'][:400]} {i.get('url') or ''}" for i in items)
    out = llm.chat(f"CONTEXT (the user's saved items):\n{ctx}\n\nQUESTION: {question}\n\nAnswer in 1 to 3 short lines.", SYSTEM, who=who)
    return (out or "").strip() or "Here's what I found:\n" + "\n".join(lines)


def read_image(data: bytes, mime: str, caption: str, tz: str, who: str | None = None) -> dict:
    """Reminders from photos: tickets, invitations, letters, bills, medicine boxes (name and dose only)."""
    fallback = {"summary": caption or "Photo", "collection": "Photos", "events": []}
    if not data:
        return fallback
    now = datetime.now(ZoneInfo(tz))
    out = llm.chat_json(
        f"User timezone {tz}, local now {now:%A %Y-%m-%d %H:%M}. Caption: {caption or '(none)'}\n"
        "Look at this image. Fields: summary (one line), collection (short folder name), events (array of {text, due_local}). "
        "Include events only for real dates in the image (tickets, invitations, appointments, bills, expiry dates); remind 2 hours "
        "before an event starts. If it is a medicine box, summary = medicine name and strength as printed, no advice.",
        SYSTEM, image=data, mime=mime if mime in ("image/jpeg", "image/png", "image/webp") else "image/jpeg", who=who, max_tokens=400)
    return out if out and "summary" in out else fallback


def draft_wish(person: str, kind: str, who: str | None = None) -> str:
    out = llm.chat(f"Draft a warm, short WhatsApp {kind} message to {person}. Two sentences, one emoji, no hashtags. Output only the message.",
                   SYSTEM, who=who, max_tokens=120)
    return (out or "").strip() or f"Happy {kind}, {person}! 🎉 Hope today is as brilliant as you are. Let's celebrate properly soon."


def recipe_from(text: str, who: str | None = None) -> dict:
    """A saved food reel's caption becomes a recipe card with a shopping list."""
    out = llm.chat_json("From this saved food post, write a recipe card. Fields: title, time, ingredients (array of short "
                        "shopping-list items), steps (array). If the post doesn't say, make a sensible home version.\n\nPOST: " + text[:2000],
                        SYSTEM, who=who, max_tokens=600)
    if out and out.get("ingredients"):
        return out
    return {"title": classify_rules(text)["title"], "time": "", "ingredients": [], "steps": []}


def quiz_from(text: str, who: str | None = None) -> dict:
    """Study saves become a 5-question quiz (app only)."""
    out = llm.chat_json("Make a 5-question multiple-choice quiz to revise this. Fields: title, questions (array of {q, options "
                        "(4 strings), answer (index 0-3), why (one line)}).\n\nMATERIAL: " + text[:3000], "", who=who, max_tokens=900)
    return out if out and out.get("questions") else {"title": "Quiz", "questions": []}


def homework_hint(text: str, image: bytes | None = None, mime: str = "image/jpeg", who: str | None = None) -> str | None:
    """App only. Explains the method step by step and checks understanding; doesn't just hand over the final answer."""
    return llm.chat("A student asks for homework help. Explain the method in short numbered steps a 14-year-old can follow, "
                    "give a similar worked example, then ask them to try the final step themselves. Don't state the final answer "
                    "to their exact question.\n\nQUESTION: " + (text or "(see photo)"),
                    "You are Mindy, a patient study buddy. Be encouraging and brief.", image=image, mime=mime, who=who, max_tokens=700)
