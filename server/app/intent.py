"""Semantic understanding: people don't type commands, they type life.

When no rule matched, the cheap model reads the message, picks which Mindy skill it means and pulls out the details
(names, amounts, dates), and we rewrite it as the plain command that skill already understands. Rules stay the source of
truth, so the AI can only ever route to things Mindy really does. Anything it isn't sure about falls through untouched."""
import json
import logging
import re

from . import llm

log = logging.getLogger("mindy.intent")

# skill -> (what it means, slots, how to write the command)
SKILLS = {
    "ask_money": ("someone owes the user money and the user wants it asked for / chased", ["person", "amount", "for"],
                  lambda s: f"ask {s['person']} for {s['amount']}" + (f" for {s['for']}" if s.get("for") else "")),
    "ask_person": ("the user wants a question put to one specific person", ["person", "question"], lambda s: f"ask {s['person']} {_q(s['question'])}"),
    "ask_group": ("the user wants several people / everyone / the group asked something, e.g. which day works", ["question", "options"],
                  lambda s: f"ask everyone {_q(s['question'])}" + (": " + ", ".join(s["options"]) if s.get("options") else "")),
    "check_on": ("the user wants to know if a family member / friend is OK", ["person"], lambda s: f"check on {s['person']}"),
    "decline": ("the user wants someone told they can't make it to something", ["person", "event"],
                lambda s: f"tell {s['person']} I can't make it" + (f" to {s['event']}" if s.get("event") else "")),
    "tell": ("the user wants a message passed to a person or everyone", ["person", "message"], lambda s: f"tell {s['person']} {s['message']}"),
    "remind_other": ("the user wants SOMEONE ELSE reminded to do something", ["person", "task", "when"],
                     lambda s: f"remind {s['person']} to {s['task']}" + (f" {s['when']}" if s.get("when") else "")),
    "split": ("the user wants a bill split between people", ["amount", "people"], lambda s: f"split {s['amount']} between {', '.join(s['people'])}"),
    "group_gift": ("the user wants friends to chip in for a gift", ["for", "amount", "people"],
                   lambda s: f"group gift for {s['for']} {s['amount']} with {', '.join(s['people'])}"),
    "gift_ideas": ("the user wants gift ideas for someone", ["person", "budget"],
                   lambda s: f"gift ideas for {s['person']}" + (f" under {s['budget']}" if s.get("budget") else "")),
    "carousel": ("the user wants an Instagram carousel / slides / post designed", ["topic"], lambda s: f"carousel: {s['topic']}"),
    "caption": ("the user wants an Instagram caption written", ["topic"], lambda s: f"caption for {s['topic']}"),
    "spending": ("the user wants to see their spending", [], lambda s: "my spending"),
    "documents": ("the user mentions a document's expiry date", ["document", "date"], lambda s: f"{s['document']} expires {s['date']}"),
    "kept_item": ("the user says where they put a thing", ["thing", "place"], lambda s: f"kept {s['thing']} in {s['place']}"),
    "find_item": ("the user asks where they put a thing", ["thing"], lambda s: f"where is my {s['thing']}"),
    "check_on_me": ("the user wants Mindy to check they got home safe", ["minutes"], lambda s: f"check on me in {s.get('minutes') or 30} min"),
    "scam_check": ("the user asks if a number, call or message is a scam", ["number"], lambda s: f"check number {s['number']}" if s.get("number") else "scam"),
    "schemes": ("the user asks which government schemes or benefits they can get", ["situation"], lambda s: f"schemes {s.get('situation') or ''}".strip()),
    "lost_phone": ("the user lost their phone", [], lambda s: "checklist lost phone"),
    "checklist": ("the user is going through a life event: moving house, new job, new baby, wedding, first car, exam, travel abroad, new business",
                  ["event"], lambda s: f"checklist {s['event']}"),
    "language": ("the user wants Mindy to reply in a language", ["language"], lambda s: f"language {s['language']}"),
    "rename": ("the user wants to give Mindy a new name", ["name"], lambda s: f"call yourself {s['name']}"),
    "brain": ("the user asks about their brain score or what Mindy knows about them", [], lambda s: "brain score"),
    "menu": ("the user asks what Mindy can do / wants the menu", [], lambda s: "menu"),
}


def _q(q: str) -> str:
    q = q.strip().rstrip("?")
    return q if re.match(r"^(if|whether|which|what|when|where|who|how|are|is|can|could|do|does|will|would)\b", q, re.I) else "if " + q


PROMPT = """You route WhatsApp messages to a personal assistant's skills. Message:
<<<{text}>>>

Skills:
{skills}

If the message clearly asks for one of these, return {{"skill": name, "slots": {{...}}, "sure": 0-1}}.
Slots: copy names, amounts (digits only), dates and times exactly as written; "person" may be "everyone"; lists as JSON arrays.
If it is a plain reminder for the user themself, a note to save, a question, small talk, or anything else, return {{"skill": "none"}}.
The message may be in any language or mixed (Hinglish etc); slots stay in the message's language except names and numbers."""


def understand(text: str, who: str | None = None) -> str | None:
    """Returns a canonical command for more.handle, or None."""
    t = text.strip()
    if not llm.live() or len(t) < 8 or len(t) > 500 or re.match(r"^(https?://|www\.)", t):
        return None
    skills = "\n".join(f"- {k}: {v[0]}. slots: {', '.join(v[1]) or 'none'}" for k, v in SKILLS.items())
    out = llm.chat_json(PROMPT.format(text=t, skills=skills), who=who, max_tokens=220)
    return to_command(out)


def to_command(out: dict | None) -> str | None:
    if not out or out.get("skill") in (None, "none") or out.get("skill") not in SKILLS:
        return None
    try:
        if float(out.get("sure", 1)) < 0.6:
            return None
    except (TypeError, ValueError):
        pass
    name = out["skill"]
    slots = {k: v for k, v in (out.get("slots") or {}).items() if v not in (None, "", [])}
    need = [s for s in SKILLS[name][1] if s not in ("for", "when", "options", "budget", "minutes", "situation", "number", "event")]
    if any(s not in slots for s in need):
        return None
    for k, v in list(slots.items()):
        if isinstance(v, str):
            slots[k] = re.sub(r"[\r\n]+", " ", v).strip()[:160]
        elif isinstance(v, list):
            slots[k] = [str(x).strip()[:30] for x in v if str(x).strip()][:10]
        else:
            slots[k] = str(v)
    if "amount" in slots:
        slots["amount"] = re.sub(r"[^\d.]", "", str(slots["amount"])) or ""
        if not slots["amount"]:
            return None
    try:
        cmd = SKILLS[name][2](slots)
    except (KeyError, TypeError):
        return None
    log.info("understood %s -> %s", name, json.dumps(cmd)[:120])
    return cmd
