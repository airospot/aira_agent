"""Attach verified show_image display_url into ANSWER text (no model Markdown required)."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

_CORPUS_PREFIX = "/agent/corpus/"
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _verified_display_urls(observations: Sequence[Any]) -> list[str]:
    """Successful current-turn show_image URLs only (status=ok + corpus display_url)."""
    out: list[str] = []
    seen: set[str] = set()
    for obs in observations or ():
        if not isinstance(obs, Mapping):
            continue
        if str(obs.get("status") or "") != "ok":
            continue
        raw = obs.get("display_url")
        if not isinstance(raw, str):
            continue
        url = raw.strip()
        if not url.startswith(_CORPUS_PREFIX):
            continue
        rest = url[len(_CORPUS_PREFIX) :]
        if ".." in url or "//" in rest or not rest:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _answer_has_image_for_url(answer: str, url: str) -> bool:
    for match in _MD_IMAGE.finditer(answer or ""):
        if match.group(2).strip() == url:
            return True
    return False


def enrich_answer_with_show_images(
    answer: str | None,
    observations: Sequence[Any] | None,
) -> str:
    """Ensure successful show_image URLs render as Markdown images in the answer.

    - Uses only current-turn observations with status=ok and display_url.
    - Does not invent URLs from free-text paths or prior turns.
    - Skips URLs already present as ``![...](url)``.
    - Replaces a bare matching URL in the answer; otherwise appends an image line.
    """
    text = str(answer or "")
    urls = _verified_display_urls(observations or ())
    if not urls:
        return text

    for url in urls:
        if _answer_has_image_for_url(text, url):
            continue

        placeholders: list[str] = []

        def _protect(match: re.Match[str]) -> str:
            placeholders.append(match.group(0))
            return f"\0IMG{len(placeholders) - 1}\0"

        working = _MD_IMAGE.sub(_protect, text)
        if url in working:
            working = working.replace(url, f"![görsel]({url})", 1)
        else:
            sep = "" if not working else ("\n\n" if not working.endswith("\n") else "\n")
            working = f"{working}{sep}![görsel]({url})"

        for index, block in enumerate(placeholders):
            working = working.replace(f"\0IMG{index}\0", block)
        text = working

    return text
