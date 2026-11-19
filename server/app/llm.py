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
        out = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def transcribe(audio: bytes, fmt: str = "mp3", who: str | None = None) -> str | None:
    """Voice note -> text (any language), through the same cheap model (Gemini accepts audio)."""
    if not live() or _over_budget(who):
        return None
    body = {"model": settings.llm_model, "max_tokens": 500, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Transcribe this voice note exactly, in the language spoken. Output only the words."},
        {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio).decode(), "format": fmt}}]}]}
    try:
        r = httpx.post(settings.llm_base_url.rstrip("/") + "/chat/completions", json=body, timeout=40,
                       headers={"Authorization": f"Bearer {settings.llm_key}"})
        r.raise_for_status()
        STATS["calls"] += 1
        return (r.json()["choices"][0]["message"]["content"] or "").strip() or None
    except Exception as e:
        STATS["failed"] += 1
        log.warning("transcribe failed: %s", e)
        return None


# ---------------------------------------------------------------- voice replies and try-on
TTS_LANG = {"en": "en-GB", "hi": "hi-IN", "hinglish": "hi-IN", "gu": "gu-IN", "mr": "mr-IN", "ta": "ta-IN", "te": "te-IN", "bn": "bn-IN",
            "kn": "kn-IN", "ml": "ml-IN", "pa": "pa-IN", "ur": "ur-IN", "es": "es-ES", "pt": "pt-BR", "fr": "fr-FR", "de": "de-DE",
            "ar": "ar-XA", "sw": "sw-KE", "id": "id-ID", "tl": "fil-PH", "it": "it-IT", "tr": "tr-TR", "ru": "ru-RU", "zh": "cmn-CN",
            "ja": "ja-JP", "ko": "ko-KR", "pl": "pl-PL", "nl": "nl-NL", "yo": "yo-NG", "ha": "ha-NG"}


def tts(text: str, lang: str = "en") -> bytes | None:
    """Text -> MP3. Google Cloud Text-to-Speech (generous free tier) if TTS_API_KEY is set, else espeak-ng offline, else None."""
    if not text.strip():
        return None
    key = settings.tts_key
    if key:
        try:
            r = httpx.post("https://texttospeech.googleapis.com/v1/text:synthesize", params={"key": key}, timeout=20,
                           json={"input": {"text": text[:1500]}, "voice": {"languageCode": TTS_LANG.get(lang, "en-GB")},
                                 "audioConfig": {"audioEncoding": "MP3"}})
            r.raise_for_status()
            return base64.b64decode(r.json()["audioContent"])
        except Exception as e:
            log.warning("tts failed: %s", e)
    import shutil
    import subprocess
    import tempfile
    if shutil.which("espeak-ng") and shutil.which("ffmpeg"):
        with tempfile.TemporaryDirectory() as d:
            wav, mp3 = f"{d}/o.wav", f"{d}/o.mp3"
            v = {"hinglish": "hi"}.get(lang, lang)
            if subprocess.run(["espeak-ng", "-v", v, "-s", "150", "-w", wav, text[:1500]], capture_output=True).returncode != 0:
                subprocess.run(["espeak-ng", "-w", wav, text[:1500]], capture_output=True)
            if subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-b:a", "64k", mp3], capture_output=True).returncode == 0:
                with open(mp3, "rb") as f:
                    return f.read()
    return None


def try_on(person: bytes, clothing: bytes, mime: str = "image/jpeg", who: str | None = None) -> bytes | None:
    """Virtual try-on with Gemini's image model (about $0.04 an image, so callers cap it per day)."""
    key = settings.gemini_key or (settings.llm_key if "googleapis" in settings.llm_base_url else "")
    if not key or _over_budget(who):
        return None
    parts = [{"text": "Photo 1 is a person. Photo 2 is a clothing item. Create a realistic photo of the same person (same face, body, skin tone and pose) "
                      "wearing this clothing item, in a clean, well-lit setting. Keep it tasteful and natural. Output only the image."},
             {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(person).decode()}},
             {"inline_data": {"mime_type": mime, "data": base64.b64encode(clothing).decode()}}]
    try:
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{settings.tryon_model}:generateContent",
                       params={"key": key}, json={"contents": [{"parts": parts}]}, timeout=90)
        r.raise_for_status()
        STATS["calls"] += 1
        for p in r.json()["candidates"][0]["content"]["parts"]:
            d = p.get("inline_data") or p.get("inlineData")
            if d and d.get("data"):
                return base64.b64decode(d["data"])
    except Exception as e:
        STATS["failed"] += 1
        log.warning("try-on failed: %s", e)
    return None
