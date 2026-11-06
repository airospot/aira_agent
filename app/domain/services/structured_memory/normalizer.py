"""Text normalization for dedupe keys (v1)."""

from __future__ import annotations

import re
import unicodedata


def normalize_memory_text(text: str) -> str:
    """Lowercase, strip, collapse whitespace, Unicode NFKC (§3a-friendly)."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t
