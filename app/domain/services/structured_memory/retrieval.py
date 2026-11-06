"""Structured memory read path for LLM context (Phase 3 v1: scope + lexical, no embeddings)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.adapters.db.agents.repositories.structured_memory_repository import (
    StructuredMemoryRepository,
)
from app.domain.services.structured_memory.settings import (
    StructuredMemoryRuntimeFlags,
    should_inject_structured_into_prompt,
)

if TYPE_CHECKING:
    from app.adapters.db.agents.models.structured_memory_tables import ExtractedMemory


def _tokenize_query(query: Optional[str]) -> List[str]:
    if not query or not str(query).strip():
        return []
    return [t.lower() for t in re.findall(r"[\w\u00c0-\u024f]{2,}", str(query).lower())]


def _row_matches_scope(
    row: "ExtractedMemory",
    *,
    session_id: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> bool:
    st = (row.scope_type or "global_user").strip()
    sv = row.scope_value
    if st == "global_user":
        return True
    if st == "session":
        if not session_id:
            return False
        return str(session_id) == (str(sv) if sv is not None else "")
    if st == "project":
        md = metadata or {}
        pid = md.get("project_id")
        if pid is None or pid == "":
            return False
        return str(pid) == (str(sv) if sv is not None else "")
    return False


def _row_matches_lexical(row: "ExtractedMemory", tokens: List[str]) -> bool:
    if not tokens:
        return True
    blob = f"{row.memory_category} {row.memory_text}".lower()
    return any(t in blob for t in tokens)


def build_structured_context_block(
    *,
    customer_id: int,
    user_id: int,
    session_id: Optional[str],
    query: Optional[str],
    metadata: Optional[Dict[str, Any]],
    flags: StructuredMemoryRuntimeFlags,
) -> str:
    """
    Returns formatted block or empty string. Caller must ensure
    ``should_inject_structured_into_prompt(flags)`` is True.
    """
    if not should_inject_structured_into_prompt(flags):
        return ""

    from app.core.config_manager import get_config_manager_for_customer

    cm = get_config_manager_for_customer(customer_id=customer_id, user_id=user_id)
    raw_max = cm.get_config("memory_structured_max_context", default=20)
    try:
        max_rows = int(raw_max) if raw_max is not None else 20
    except (TypeError, ValueError):
        max_rows = 20
    max_rows = max(1, min(max_rows, 500))

    repo = StructuredMemoryRepository()
    rows = repo.list_active_for_retrieval(
        customer_id=customer_id, user_id=user_id, prefetch=max(200, max_rows * 10)
    )
    tokens = _tokenize_query(query)
    min_conf = float(flags.min_confidence)

    picked: List = []
    for r in rows:
        if r.confidence is not None and r.confidence < min_conf:
            continue
        if not _row_matches_scope(r, session_id=session_id, metadata=metadata):
            continue
        if not _row_matches_lexical(r, tokens):
            continue
        picked.append(r)
        if len(picked) >= max_rows:
            break

    if not picked:
        return ""

    lines = ["=== Structured memory (extracted) ==="]
    for r in picked:
        scope = f"{r.scope_type or 'global_user'}"
        if r.scope_value:
            scope += f":{r.scope_value}"
        conf = f"{r.confidence:.2f}" if r.confidence is not None else "n/a"
        lines.append(f"[{r.memory_category}] scope={scope} confidence={conf}> {r.memory_text}")
    lines.append("")
    return "\n".join(lines)
