"""The brain behind the Android helper: given what's on the person's screen right now (a compact list of the
buttons and boxes Android's accessibility service can see) and what they want ("Phoenix Mall jaana hai"),
work out the ONE next thing to tap, in simple words, in their language.

Cheap by design: the screen goes as text (no screenshot), and only the visible, meaningful elements.
Safe by design: PIN, OTP, password and card fields are never targeted and never auto-tapped, and payment
confirmation buttons are marked user_only so the app can point at them but never press them."""
import re

from . import llm, skills

SENSITIVE = re.compile(r"\b(upi pin|enter pin|mpin|m-pin|otp|one.?time|cvv|password|passcode|pin code|atm pin)\b", re.I)
USER_ONLY = re.compile(r"\b(pay|send money|confirm payment|proceed to pay|transfer|place order|buy now|confirm booking|book now|request \w+)\b", re.I)
APPS = [(r"\b(uber|cab|taxi|ola|rapido|ride|auto)\b", "ride"), (r"\b(directions?|route|navigate|rasta|kaise jaun|map)\b", "maps"),
        (r"\byoutube\b|\b(video|gaana|song|bhajan)\b.*\b(dekh|play|chala)", "youtube"), (r"\bwhatsapp\b|\bvideo call\b|\bcall\b", "whatsapp")]
SYSTEM = ("You guide an older or non-technical person through a phone app, one step at a time, like a patient grandchild. "
          "Use very simple words. Never ask them to type a PIN, OTP or password for you; tell them to type it themselves. "
          "Never give medical or financial advice. Reply with JSON only.")


def _line(n: dict) -> str:
    bits = [n.get("t"), n.get("d"), ("hint: " + n["h"]) if n.get("h") else None, n.get("id")]
    flags = "".join(f for f, k in (("C", "k"), ("E", "e"), ("S", "s"), ("P", "p")) if n.get(k))
    return f"[{n['i']}] " + " | ".join(b for b in bits if b)[:120] + (f" ({flags})" if flags else "")


def _hi(lang: str) -> bool:
    return (lang or "").lower().startswith("hi")


def first_step(goal: str, pkg: str, lang: str) -> dict | None:
    """Opening the right app at the right screen is the biggest shortcut: do it before any tapping."""
    low = goal.lower()
    for pat, kind in APPS:
        if not re.search(pat, low):
            continue
        if kind == "ride":
            m = re.search(r"\b(?:to|for)\s+(.+)", goal, re.I) or re.search(r"(.+?)\s+(?:jaana|jana|jaanaa|tak|ko|pe|par)\b", goal, re.I)
            place = m.group(1) if m else goal
            place = re.sub(r"\b(book|get|an?|uber|cab|taxi|ola|rapido|ride|auto|please|mujhe|hai|se|me|mein|karni|karo|chahiye)\b", "", place, flags=re.I)
            place = re.sub(r"\s{2,}", " ", place).strip(" .?,")
            if not place and "uber" not in (pkg or ""):
                return {"action": "open", "url": "https://m.uber.com/ul/?action=setPickup&pickup=my_location",
                        "say": "Uber खोल रहा हूँ। 'Where to' दबाकर जगह बोलिए।" if _hi(lang) else "Opening Uber. Tap 'Where to?' and type the place."}
            d = skills.do_it(f"book an uber to {place}") if place else None
            if d and "uber" not in (pkg or ""):
                return {"action": "open", "url": d["links"][0][1], "say": f"मैं Uber खोल रहा हूँ, {place} पहले से भरा है।" if _hi(lang) else f"Opening Uber with {place} already filled in."}
        if kind == "maps" and "maps" not in (pkg or ""):
            m = re.search(r"\b(?:to|for|tak)\b\s+(.+)", goal, re.I)
            if m:
                d = skills.do_it("directions to " + m.group(1))
                return {"action": "open", "url": d["links"][0][1], "say": "रास्ता खोल रहा हूँ। Start दबाइए।" if _hi(lang) else "Opening the route. Then press Start."}
        if kind == "youtube" and "youtube" not in (pkg or ""):
            q = re.sub(r"\b(youtube|play|chala|dekhna|dekh|video|on|pe|par)\b", "", goal, flags=re.I).strip()
            return {"action": "open", "url": "https://www.youtube.com/results?search_query=" + re.sub(r"\s+", "+", q),
                    "say": "YouTube खोल रहा हूँ।" if _hi(lang) else "Opening YouTube."}
        if kind == "whatsapp" and "whatsapp" not in (pkg or ""):
            return {"action": "open", "url": "https://wa.me/", "say": "WhatsApp खोल रहा हूँ।" if _hi(lang) else "Opening WhatsApp."}
    return None


def heuristic(goal: str, nodes: list[dict], lang: str) -> dict:
    """No AI available: pick the element that best matches the goal or a common 'next' word."""
    words = {w for w in re.findall(r"[a-z]{3,}", goal.lower())}
    nxt = re.compile(r"\b(where to|search|next|continue|confirm|done|ok|allow|start|call|video|send|book|choose)\b", re.I)
    best, score = None, 0
    for n in nodes:
        if n.get("p") or not (n.get("k") or n.get("e")):
            continue
        label = f"{n.get('t') or ''} {n.get('d') or ''} {n.get('h') or ''}".lower()
        s = 2 * len(words & set(re.findall(r"[a-z]{3,}", label))) + (1 if nxt.search(label) else 0)
        if s > score:
            best, score = n, s
    if not best:
        return {"action": "stuck", "target": -1, "say": "मुझे यहाँ अगला कदम नहीं दिख रहा। परिवार को बुलाऊँ?" if _hi(lang) else "I can't see the next step here. Shall I call your family?"}
    label = best.get("t") or best.get("d") or best.get("h") or "this"
    return {"action": "type" if best.get("e") else "tap", "target": best["i"],
            "say": f"यहाँ दबाइए: {label}" if _hi(lang) else f"Tap here: {label}"}


def next_step(goal: str, pkg: str, nodes: list[dict], history: list[str], lang: str = "en", who: str | None = None) -> dict:
    nodes = nodes[:150]
    screen_text = " ".join(f"{n.get('t') or ''} {n.get('h') or ''}" for n in nodes)
    if any(n.get("p") for n in nodes) or SENSITIVE.search(screen_text):
        return {"action": "private", "target": -1, "say": "यह आपका PIN या OTP है। इसे सिर्फ़ आप भरें, मैं नहीं देख रहा। भरने के बाद आगे बढ़ें।" if _hi(lang)
                else "This is your PIN or OTP. Only you should type it; I'm not looking. Carry on when you've typed it."}
    if not history:
        f = first_step(goal, pkg, lang)
        if f:
            return f
    out = llm.chat_json(
        f"GOAL: {goal}\nAPP: {pkg}\nSTEPS SO FAR: {' / '.join(history[-6:]) or 'none'}\nLANGUAGE FOR 'say': {'Hindi (Devanagari)' if _hi(lang) else 'simple English'}\n"
        "SCREEN (index | text | description | hint | id, flags C=clickable E=editable S=scrollable):\n" + "\n".join(_line(n) for n in nodes) +
        "\n\nFields: action (tap, type, scroll, wait, done, stuck), target (index or -1), text (what to type, only for type), "
        "say (one short instruction naming the button, max 15 words). If the goal is already achieved, action=done.",
        SYSTEM, who=who, max_tokens=160)
    if not out or out.get("action") not in ("tap", "type", "scroll", "wait", "done", "stuck"):
        return heuristic(goal, nodes, lang)
    try:
        out["target"] = int(out.get("target", -1))
    except (TypeError, ValueError):
        out["target"] = -1
    tgt = next((n for n in nodes if n["i"] == out["target"]), None)
    if tgt and tgt.get("p"):
        return {"action": "private", "target": -1, "say": "Type this yourself; I'm not looking."}
    label = f"{(tgt or {}).get('t') or ''} {(tgt or {}).get('d') or ''}"
    out["user_only"] = bool(tgt and USER_ONLY.search(label))
    if out["user_only"]:
        out["say"] = (out.get("say") or "") + (" नाम और रकम जाँच लें, फिर आप खुद दबाएँ।" if _hi(lang) else " Check the name and amount, then press it yourself.")
    return out
