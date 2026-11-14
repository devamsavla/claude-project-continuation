"""The cheapest possible AI: rules first, then one small model through any OpenAI-compatible API.

Default: Google Gemini 2.5 Flash-Lite through Google's OpenAI-compatible endpoint (has a free tier, then about
$0.10 per million input tokens). Works unchanged with OpenAI (gpt-5-nano), DeepSeek, Groq, OpenRouter, Together
or a Lovable/other gateway: set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL.

Cost guards: answers are cached by prompt, every person has a daily call budget, and any failure returns None so
callers fall back to rules. A message is never dropped because the AI is down or over budget."""
import base64
import hashlib
import json
import logging
import time

import httpx

from .config import settings

log = logging.getLogger("mindy.llm")
_cache: dict[str, tuple[float, str]] = {}
_budget: dict[str, list] = {}
STATS = {"calls": 0, "cached": 0, "failed": 0, "over_budget": 0, "tokens_in": 0, "tokens_out": 0}


def live() -> bool:
    return bool(settings.llm_key)


def _over_budget(who: str | None) -> bool:
    if not who:
        return False
    day = time.strftime("%Y-%m-%d")
    d, n = _budget.get(who, [day, 0])
    if d != day:
        d, n = day, 0
    if n >= settings.llm_daily_calls:
        return True
    _budget[who] = [d, n + 1]
    return False


def chat(prompt: str, system: str = "", *, image: bytes | None = None, mime: str = "image/jpeg",
         json_mode: bool = False, max_tokens: int = 400, who: str | None = None, cache: bool = True) -> str | None:
    """One call to the cheap model. Returns the text, or None (no key, over budget, error)."""
    if not live():
        return None
    key = hashlib.sha256(f"{system}\n{prompt}\n{json_mode}".encode()).hexdigest() if cache and image is None else None
    if key and key in _cache and time.time() - _cache[key][0] < 86400:
        STATS["cached"] += 1
        return _cache[key][1]
    if _over_budget(who):
        STATS["over_budget"] += 1
        return None
    content: list | str = prompt
    if image is not None:
        content = [{"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image).decode()}"}}]
    body = {"model": settings.llm_model, "max_tokens": max_tokens, "temperature": 0.2,
            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = httpx.post(settings.llm_base_url.rstrip("/") + "/chat/completions", json=body, timeout=25,
                       headers={"Authorization": f"Bearer {settings.llm_key}"})
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"] or ""
        u = data.get("usage") or {}
        STATS["calls"] += 1
        STATS["tokens_in"] += u.get("prompt_tokens", 0)
        STATS["tokens_out"] += u.get("completion_tokens", 0)
    except Exception as e:  # network, quota, bad key: callers fall back to rules
        STATS["failed"] += 1
        log.warning("llm call failed: %s", e)
        return None
    if key:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[key] = (time.time(), text)
    return text


def chat_json(prompt: str, system: str = "", **kw) -> dict | None:
    raw = chat(prompt + "\nReply with JSON only.", system, json_mode=True, **kw)
    if not raw:
        return None
    try:
        return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError:
        return None
