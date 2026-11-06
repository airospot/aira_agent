"""Aira Intelligence Flow memory adaptation (canonical location).

Reuses AiraCoder ``memory_service`` / ConversationService — no second store.
"""

from .bridge import (
    AGENT_PAGE_TYPE,
    MemoryPersistIncompleteError,
    MemoryReadError,
    SessionIdentityError,
    list_agent_conversations,
    load_flow_conversation,
    load_turn_trace,
    load_ui_transcript,
    persist_turn,
    resolve_session_id,
)

__all__ = [
    "AGENT_PAGE_TYPE",
    "MemoryPersistIncompleteError",
    "MemoryReadError",
    "SessionIdentityError",
    "list_agent_conversations",
    "load_flow_conversation",
    "load_turn_trace",
    "load_ui_transcript",
    "persist_turn",
    "resolve_session_id",
]
