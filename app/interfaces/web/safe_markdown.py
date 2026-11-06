"""Minimal safe markdown render for assistant transcripts."""

from __future__ import annotations

import html
import re

_SAFE_LANG = re.compile(r"^[a-z0-9_+#-]+$", re.I)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _safe_href(href: str) -> str:
    h = (href or "").strip()
    # Models sometimes rewrite /agent/corpus/... into https://agent/corpus/...
    for bad_prefix in ("https://agent/corpus/", "http://agent/corpus/"):
        if h.startswith(bad_prefix):
            h = "/agent/corpus/" + h[len(bad_prefix) :]
            break
    if h.startswith("/agent/corpus/"):
        # Block traversal / absolute escapes inside corpus URLs.
        rest = h[len("/agent/corpus/") :]
        if ".." in h or "//" in rest:
            return ""
        return h
    if h.startswith(("http://", "https://", "#")):
        return h
    if h.startswith("/") and not h.startswith("//"):
        return h
    return ""


def _inline(text: str) -> str:
    def image(m: re.Match[str]) -> str:
        alt = m.group(1)
        href = _safe_href(m.group(2))
        if not href:
            return alt
        return (
            f'<img src="{html.escape(href, quote=True)}" '
            f'alt="{html.escape(alt, quote=True)}" '
            f'class="agent-inline-image" loading="lazy" />'
        )

    def link(m: re.Match[str]) -> str:
        label = m.group(1)
        href = _safe_href(m.group(2))
        if not href:
            return label
        external = href.startswith("http://") or href.startswith("https://")
        attrs = ' target="_blank" rel="noopener noreferrer"' if external else ""
        return f'<a href="{html.escape(href, quote=True)}"{attrs}>{label}</a>'

    text = _IMAGE.sub(image, text)
    text = _LINK.sub(link, text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _INLINE_CODE.sub(r"<code>\1</code>", text)
    return text


def render_safe_markdown(text: str) -> str:
    """Escape first, then apply a limited Markdown subset."""
    raw = text or ""
    escaped = html.escape(raw, quote=False)
    escaped = re.sub(r"(?i)javascript:", "", escaped)
    lines = escaped.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^```([A-Za-z0-9_+#-]*)\s*$", line)
        if fence:
            lang = fence.group(1).lower()
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            klass = f' class="language-{lang}"' if _SAFE_LANG.match(lang) else ""
            blocks.append(f"<pre><code{klass}>{chr(10).join(body)}</code></pre>")
            continue
        if re.match(r"^###\s+", line):
            blocks.append(f"<h3>{_inline(line[4:].strip())}</h3>")
        elif re.match(r"^##\s+", line):
            blocks.append(f"<h2>{_inline(line[3:].strip())}</h2>")
        elif re.match(r"^#\s+", line):
            blocks.append(f"<h2>{_inline(line[2:].strip())}</h2>")
        elif re.match(r"^-\s+", line):
            items = []
            while i < len(lines) and re.match(r"^-\s+", lines[i]):
                items.append(f"<li>{_inline(lines[i][2:].strip())}</li>")
                i += 1
            blocks.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif line.strip() == "":
            blocks.append("")
        else:
            blocks.append(f"<p>{_inline(line)}</p>")
        i += 1
    return "\n".join(blocks)
