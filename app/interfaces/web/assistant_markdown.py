"""Assistant transcript Markdown → HTML (escape-first, limited subset).

Renders agent reply / turn prose for the chat UI: headings, lists, fenced
code, pipe tables (``table-scroll``), bold/inline code, and sanitized
corpus/http links and images. Not a general-purpose Markdown engine.
"""

from __future__ import annotations

import html
import re

_SAFE_LANG = re.compile(r"^[a-z0-9_+#-]+$", re.I)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_TABLE_SEP_CELL = re.compile(r"^:?-{3,}:?$")


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


def _split_table_row(line: str) -> list[str] | None:
    """Return cells for a pipe row, or None if not a table row."""
    raw = line.strip()
    if "|" not in raw:
        return None
    # Require a pipe-framed row (leading and/or trailing pipes OK).
    if not (raw.startswith("|") or raw.endswith("|")):
        return None
    parts = raw.split("|")
    if raw.startswith("|"):
        parts = parts[1:]
    if raw.endswith("|"):
        parts = parts[:-1]
    if len(parts) < 2:
        return None
    return [p.strip() for p in parts]


def _is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(_TABLE_SEP_CELL.match(c.replace(" ", "")) for c in cells)


def _try_parse_table(lines: list[str], start: int) -> tuple[str, int] | None:
    """Parse a GFM-like pipe table starting at ``start``. Return (html, next_i)."""
    if start >= len(lines):
        return None
    header = _split_table_row(lines[start])
    if header is None or start + 1 >= len(lines):
        return None
    sep = _split_table_row(lines[start + 1])
    if sep is None or not _is_separator_row(sep):
        return None
    # Ambiguous / invalid: separator column count must match header.
    if len(sep) != len(header):
        return None

    body_rows: list[list[str]] = []
    i = start + 2
    while i < len(lines):
        row = _split_table_row(lines[i])
        if row is None:
            break
        if _is_separator_row(row):
            # Extra separator mid-table → leave as plain text from here.
            break
        # Pad/truncate to header width for stable HTML.
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
        elif len(row) > len(header):
            row = row[: len(header)]
        body_rows.append(row)
        i += 1

    thead = "<thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in header) + "</tr></thead>"
    tbody_cells = []
    for row in body_rows:
        tbody_cells.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
    tbody = "<tbody>" + "".join(tbody_cells) + "</tbody>" if tbody_cells else "<tbody></tbody>"
    html_table = f'<div class="table-scroll"><table>{thead}{tbody}</table></div>'
    return html_table, i


def render_assistant_markdown(text: str) -> str:
    """Escape first, then apply the assistant Markdown subset (incl. pipe tables)."""
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
        table = _try_parse_table(lines, i)
        if table is not None:
            html_table, next_i = table
            blocks.append(html_table)
            i = next_i
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
