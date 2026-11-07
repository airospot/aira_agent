"""Sidebar conversation history pagination for the assistant UI."""

from __future__ import annotations

from flask import jsonify, request, url_for

from app.core.security import require_tenant, role_required
from app.domain.agents.flow.memory import list_agent_conversations
from app.interfaces.web.agent_routes.blueprint import agent_bp
from app.interfaces.web.agent_routes.tenant import tenant_ids

AGENT_HISTORY_PAGE = 15
AGENT_HISTORY_MAX = 50


def history_window(offset: int, limit: int) -> tuple[int, int]:
    """Clamp a scroll page so the sidebar never exceeds AGENT_HISTORY_MAX."""
    try:
        offset_n = max(0, int(offset))
    except (TypeError, ValueError):
        offset_n = 0
    try:
        limit_n = int(limit)
    except (TypeError, ValueError):
        limit_n = AGENT_HISTORY_PAGE
    offset_n = min(offset_n, AGENT_HISTORY_MAX)
    if offset_n >= AGENT_HISTORY_MAX:
        return offset_n, 0
    limit_n = max(1, min(limit_n, AGENT_HISTORY_PAGE))
    limit_n = min(limit_n, AGENT_HISTORY_MAX - offset_n)
    return offset_n, limit_n


@agent_bp.get("/assistant/conversations")
@require_tenant
@role_required(["Admin", "Super Admin"])
def assistant_conversations():
    """Next sidebar page. Total cap is AGENT_HISTORY_MAX; caller scrolls to load."""
    customer_id, user_id = tenant_ids()
    offset, limit = history_window(
        request.args.get("offset") or 0,
        request.args.get("limit") or AGENT_HISTORY_PAGE,
    )
    if not customer_id or not user_id or limit == 0:
        return jsonify({"items": [], "next_offset": offset, "has_more": False})
    rows = list_agent_conversations(
        customer_id=customer_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    items = [
        {
            "session_id": row.get("session_id"),
            "title": row.get("title") or "",
            "last_message_at": row.get("last_message_at") or "",
            "href": url_for("agent.assistant", session_id=row.get("session_id")),
        }
        for row in rows
        if row.get("session_id")
    ]
    next_offset = offset + len(items)
    has_more = len(items) == limit and next_offset < AGENT_HISTORY_MAX
    return jsonify({"items": items, "next_offset": next_offset, "has_more": has_more})
