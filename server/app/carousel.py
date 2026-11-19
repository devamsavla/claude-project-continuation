"""Instagram carousel maker: one sentence in, 5-7 designed 1080x1350 slides out, plus a caption and hashtags.

The AI writes the slides; without AI, Mindy splits the person's own text into slides. Rendering is plain Pillow,
so it costs nothing per carousel."""
import colorsys
import io
import os
import re
import textwrap

from PIL import Image, ImageDraw, ImageFont

from . import llm

W, H = 1080, 1350
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
THEMES = [  # (background, ink, accent)
    ((7, 9, 10), (244, 241, 234), None),
    ((244, 239, 227), (10, 10, 10), None),
    (None, (6, 53, 44), None),
]


def _font(size, bold=True):
    for name in (("Poppins-Bold.ttf",) if bold else ("Poppins-Medium.ttf",)) + ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",):
        try:
            return ImageFont.truetype(name if name.startswith("/") else os.path.join(FONT_DIR, name), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _accent(hue):
    r, g, b = colorsys.hls_to_rgb(((hue if hue is not None else 150) % 360) / 360, 0.5, 0.65)
    return int(r * 255), int(g * 255), int(b * 255)


def _soft(hue):
    r, g, b = colorsys.hls_to_rgb(((hue if hue is not None else 150) % 360) / 360, 0.86, 0.75)
    return int(r * 255), int(g * 255), int(b * 255)


def write(topic: str, who: str | None = None, brand: str | None = None) -> dict:
    """Slides as [{title, body}], a caption and hashtags."""
    out = llm.chat_json(
        "Write an Instagram carousel about: " + topic[:600] + (f"\nBrand: {brand}" if brand else "") +
        "\nReturn {\"slides\":[{\"title\":str,\"body\":str}], \"caption\":str, \"hashtags\":[str]}. "
        "5 to 7 slides. Slide 1 is a scroll-stopping hook (title under 8 words, body under 12). Middle slides: one idea each, "
        "title under 7 words, body under 28 words, concrete and useful. Last slide: a clear call to action. "
        "Caption under 60 words, warm, no clickbait. 5 to 8 relevant hashtags without spaces. Same language as the topic.",
        who=who, max_tokens=900) if llm.live() else None
    if out and isinstance(out.get("slides"), list) and len(out["slides"]) >= 2:
        slides = [{"title": str(s.get("title", ""))[:80], "body": str(s.get("body", ""))[:220]} for s in out["slides"][:8]]
        tags = [("#" + re.sub(r"\W", "", str(t).lstrip("#")))[:30] for t in (out.get("hashtags") or [])][:8]
        return {"slides": slides, "caption": str(out.get("caption", ""))[:600], "hashtags": [t for t in tags if len(t) > 1]}
    parts = [p.strip() for p in re.split(r"\n+|;|\s\|\s", topic) if p.strip()]
    if len(parts) < 2:
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|,\s+", topic) if p.strip()]
    slides = [{"title": parts[0][:80], "body": ""}] + [{"title": p[:80], "body": ""} for p in parts[1:7]]
    if len(slides) < 2:
        slides.append({"title": "Save this for later", "body": ""})
    return {"slides": slides, "caption": parts[0][:200], "hashtags": []}


def _wrap(draw, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render(slides: list[dict], hue: int | None = None, handle: str = "") -> list[bytes]:
    acc, soft = _accent(hue), _soft(hue)
    n = len(slides)
    pngs = []
    for i, s in enumerate(slides):
        first, last = i == 0, i == n - 1
        if first:
            bg, ink, hi = (7, 9, 10), (244, 241, 234), acc
        elif last:
            bg, ink, hi = acc, (6, 20, 14), (6, 20, 14)
        else:
            bg, ink, hi = ((244, 239, 227), (12, 12, 12), acc) if i % 2 else (soft, (6, 40, 32), (6, 40, 32))
        img = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(img)
        pad = 96
        if first:
            d.ellipse([W - 420, -160, W + 180, 440], fill=tuple(int(c * 0.35 + b * 0.65) for c, b in zip(acc, bg)))
        title_size = 104 if first else 78
        tf = _font(title_size)
        lines = _wrap(d, s["title"], tf, W - 2 * pad)
        while len(lines) > (5 if first else 4) and title_size > 52:
            title_size -= 8
            tf = _font(title_size)
            lines = _wrap(d, s["title"], tf, W - 2 * pad)
        bf = _font(44, bold=False)
        body = _wrap(d, s.get("body") or "", bf, W - 2 * pad)[:8]
        block = len(lines) * int(title_size * 1.12) + (40 + len(body) * 62 if body else 0)
        y = (H - block) // 2 if not first else H - block - 230
        if not first and not last:
            d.text((pad, pad), f"{i:02d}", font=_font(40), fill=hi)
        for ln in lines:
            d.text((pad, y), ln, font=tf, fill=ink)
            y += int(title_size * 1.12)
        if body:
            y += 40
            for ln in body:
                d.text((pad, y), ln, font=bf, fill=ink)
                y += 62
        foot = _font(32, bold=False)
        if handle:
            d.text((pad, H - pad - 20), handle[:40], font=foot, fill=ink)
        mark = f"{i + 1} / {n}" if not last else "Save + share"
        d.text((W - pad - d.textlength(mark, font=foot), H - pad - 20), mark, font=foot, fill=ink)
        if first:
            sf = _font(40)
            d.text((pad, H - pad - 90), "Swipe", font=sf, fill=hi)
            x = pad + d.textlength("Swipe", font=sf) + 18
            ym = H - pad - 90 + 30
            d.line([(x, ym), (x + 46, ym)], fill=hi, width=6)
            d.polygon([(x + 46, ym - 14), (x + 66, ym), (x + 46, ym + 14)], fill=hi)
        out = io.BytesIO()
        img.save(out, "PNG", optimize=True)
        pngs.append(out.getvalue())
    return pngs


def caption(topic: str, who: str | None = None) -> str:
    out = llm.chat("Write an Instagram caption (under 60 words, warm, specific, one emoji at most) and then 6 relevant hashtags on a new line, for: "
                   + topic[:600] + "\nSame language as the request. Output only the caption and hashtags.", who=who, max_tokens=200) if llm.live() else None
    return out or "✍️ My caption writer switches on once my AI is connected. Meanwhile: lead with the benefit, one line of proof, then a clear ask."
