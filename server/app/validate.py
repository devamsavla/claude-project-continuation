"""Checks every outgoing WhatsApp payload against Meta's documented limits (Cloud API, Nov 2026):
text 4096; interactive body 1024 (list 4096); header/footer 60; reply buttons max 3, title <=20, id <=256, titles unique;
list button <=20, <=10 rows total, section title <=24, row title <=24, row id <=200, row description <=72;
cta_url display_text <=20 and an http(s) url; captions 1024; template parameters non-empty, no newlines/tabs, no more than
4 consecutive spaces. Returns a list of problems (empty = valid). Used in tests on every simulated reply."""
import re


def _len(s):
    return len(s or "")


def whatsapp(p: dict) -> list[str]:
    errs = []
    t = p.get("type")
    if p.get("status") == "read":
        return errs
    if not p.get("to"):
        errs.append("missing to")
    if t == "text":
        b = p["text"].get("body", "")
        if not b.strip():
            errs.append("empty text body")
        if _len(b) > 4096:
            errs.append("text > 4096")
    elif t == "interactive":
        i = p["interactive"]
        it = i.get("type")
        body = (i.get("body") or {}).get("text", "")
        if it != "flow" and not body.strip():
            errs.append(f"{it}: empty body")
        if _len(body) > (4096 if it == "list" else 1024):
            errs.append(f"{it}: body too long ({len(body)})")
        if i.get("header", {}).get("type") == "text" and _len(i["header"].get("text")) > 60:
            errs.append("header > 60")
        if _len((i.get("footer") or {}).get("text")) > 60:
            errs.append("footer > 60")
        a = i.get("action", {})
        if it == "button":
            bs = a.get("buttons", [])
            if not 1 <= len(bs) <= 3:
                errs.append(f"button count {len(bs)}")
            titles = [b["reply"]["title"] for b in bs]
            if len(set(titles)) != len(titles):
                errs.append(f"duplicate button titles {titles}")
            for b in bs:
                if not b["reply"]["title"].strip() or _len(b["reply"]["title"]) > 20:
                    errs.append(f"button title {b['reply']['title']!r}")
                if not b["reply"]["id"] or _len(b["reply"]["id"]) > 256:
                    errs.append("button id")
            if len({b["reply"]["id"] for b in bs}) != len(bs):
                errs.append("duplicate button ids")
        elif it == "list":
            if not a.get("button") or _len(a.get("button")) > 20:
                errs.append("list button text")
            rows = [r for s in a.get("sections", []) for r in s.get("rows", [])]
            if not 1 <= len(rows) <= 10:
                errs.append(f"list rows {len(rows)}")
            for s in a.get("sections", []):
                if not s.get("title") or _len(s.get("title")) > 24:
                    errs.append("section title")
            for r in rows:
                if not r["title"].strip() or _len(r["title"]) > 24 or _len(r.get("description")) > 72 or not r["id"] or _len(r["id"]) > 200:
                    errs.append(f"list row {r}")
            if len({r["id"] for r in rows}) != len(rows):
                errs.append("duplicate row ids")
        elif it == "cta_url":
            prm = a.get("parameters", {})
            if not prm.get("display_text") or _len(prm["display_text"]) > 20:
                errs.append(f"cta label {prm.get('display_text')!r}")
            if not re.match(r"^https?://\S+$", prm.get("url", "")):
                errs.append(f"cta url {prm.get('url')!r}")
        elif it == "flow":
            if _len(a.get("parameters", {}).get("flow_cta")) > 20:
                errs.append("flow cta")
    elif t in ("image", "document", "audio"):
        m = p[t]
        if not re.match(r"^https?://\S+$", m.get("link", "")):
            errs.append(f"{t} link")
        if _len(m.get("caption")) > 1024:
            errs.append("caption > 1024")
    elif t == "template":
        for c in p["template"].get("components", []):
            for prm in c.get("parameters", []):
                tx = prm.get("text", "")
                if not tx.strip():
                    errs.append("empty template parameter")
                if re.search(r"[\n\t]", tx) or "     " in tx:
                    errs.append(f"template parameter has newline/tab/5+ spaces: {tx[:40]!r}")
    elif t == "location":
        pass
    elif t == "reaction":
        pass
    else:
        errs.append(f"unknown type {t}")
    return errs
