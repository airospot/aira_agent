"""Strict tenant id extraction for agent routes."""

from __future__ import annotations

import re
from typing import Any

from flask import g

_CANONICAL_DECIMAL_ID = re.compile(r"^[1-9][0-9]*$")


def strict_tenant_id(value: Any) -> int | None:
    """Accept positive int or lossless canonical decimal string only.

    ``@require_tenant`` sets ``g.user_id`` / ``g.customer_id`` from
    ``require_tenant_context()`` only when both values are ``int``. Boolean is
    rejected here because ``isinstance(True, int)`` is true in Python. Floats
    and lossy coercions (e.g. 1010.9 → 1010) are never accepted.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not _CANONICAL_DECIMAL_ID.fullmatch(text):
            return None
        return int(text)
    return None


def tenant_ids() -> tuple[int | None, int | None]:
    return (
        strict_tenant_id(getattr(g, "customer_id", None)),
        strict_tenant_id(getattr(g, "user_id", None)),
    )


# Private aliases kept for call-site parity with former routes.py helpers.
_strict_tenant_id = strict_tenant_id
_tenant_ids = tenant_ids
