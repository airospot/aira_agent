"""
Sensitive-content gate (v1).

**Frozen behavior:** if blocked, caller must write ``REJECTED_SENSITIVE`` only
(no ``extracted_memory`` row, no silent drop).
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# High-signal patterns only; tune in later phases.
_PATTERNS = (
    (re.compile(r"\bsk-[a-zA-Z0-9]{10,}\b", re.I), "openai_sk"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws_access_key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "pem_private_key"),
    (re.compile(r"\bpassword\s*[:=]\s*\S+", re.I), "password_literal"),
    (re.compile(r"\bbearer\s+[a-z0-9._\-]{20,}\b", re.I), "bearer_token"),
)


def evaluate_sensitive_content(text: str) -> Tuple[bool, Optional[str]]:
    """
    Returns:
        (blocked, reason_code) — if blocked, reason_code is a short machine id.
    """
    if not text:
        return False, None
    for rx, code in _PATTERNS:
        if rx.search(text):
            return True, code
    return False, None
