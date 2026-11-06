"""Derive v1 scope from conversation context (inputs only; no business rules)."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def audit_session_and_project_ids(
    session_id: str,
    metadata: Optional[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[int]]:
    """
    Denormalized transcript session + project for reporting, graph, and audit.

    Independent of ``derive_scope_v1`` (scope grain); always captures the chat
    ``session_id`` when non-empty and parses ``metadata[\"project_id\"]`` when set.
    """
    sid = (session_id or "").strip() or None
    pid: Optional[int] = None
    md = metadata or {}
    raw = md.get("project_id")
    if raw is not None and raw != "":
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            pid = None
    return sid, pid


def derive_scope_v1(
    page_type: str,
    session_id: str,
    metadata: Optional[Dict[str, Any]],
) -> Tuple[str, Optional[str]]:
    md = metadata or {}
    pid = md.get("project_id")
    if pid not in (None, ""):
        return "project", str(pid)
    if session_id:
        return "session", str(session_id)
    # page_type reserved for future domain scope; v1 uses global_user when no session signal
    _ = page_type  # explicit unused for future rules
    return "global_user", None
