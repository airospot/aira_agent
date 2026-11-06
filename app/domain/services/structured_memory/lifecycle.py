"""TTL / expiry for structured memory (Phase 4 v1 — inline on read path when enabled)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from app.adapters.db.agents.models.base import db
from app.adapters.db.agents.repositories.structured_memory_repository import (
    StructuredMemoryRepository,
)

logger = logging.getLogger(__name__)


def _normalize_expiry(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def expire_due_extracted_memories(customer_id: int, user_id: int) -> int:
    """
    Mark ``active`` rows with ``expires_at`` in the past as ``expired`` and append
    ``EXPIRED`` events. Commits once if any row changed.

    Intended callers: ``get_conversation_context`` (when structured feature is on)
    or a future scheduler; see ``docs/migrations/README.md`` for DDL prerequisites.
    """
    from app.adapters.db.agents.models.structured_memory_tables import ExtractedMemory

    now = datetime.now(timezone.utc)
    repo = StructuredMemoryRepository()
    rows = (
        ExtractedMemory.query.filter_by(
            customer_id=customer_id, user_id=user_id, status="active"
        )
        .filter(ExtractedMemory.expires_at.isnot(None))
        .all()
    )
    due: list = []
    for r in rows:
        ea = _normalize_expiry(r.expires_at)
        if ea <= now:
            due.append(r)
    if not due:
        return 0
    for r in due:
        repo.update_extracted_fields(
            r.id,
            customer_id=customer_id,
            user_id=user_id,
            fields={"status": "expired"},
        )
        repo.insert_event(
            customer_id=customer_id,
            user_id=user_id,
            event_type="EXPIRED",
            extracted_memory_id=r.id,
            conversation_memory_id=None,
            payload={"expires_at": r.expires_at.isoformat() if r.expires_at else None},
            session_id=getattr(r, "session_id", None),
            project_id=getattr(r, "project_id", None),
        )
    db.session.commit()
    logger.info(
        "structured_memory expired count=%s customer_id=%s user_id=%s",
        len(due),
        customer_id,
        user_id,
    )
    return len(due)
