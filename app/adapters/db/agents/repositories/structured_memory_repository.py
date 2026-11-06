"""
Structured memory persistence — CRUD shell only (Phase 1).

No extraction, filtering, or prompt logic. Callers own ``db.session.commit()``.

**DB deployment blocked until migration practice is clarified** (e.g. no
``alembic/`` at repo root in prior survey): these models map to tables that must
be created via your chosen DDL/migration path before writes succeed in prod.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_

from app.adapters.db.agents.models.base import db
from app.adapters.db.agents.models.structured_memory_tables import (
    ExtractedMemory,
    MemoryEventLog,
)

_CODE_AGENT_PAGES = frozenset({"airacoder", "chat", "agent_tools", "aira"})


class StructuredMemoryRepository:
    """Thin data-access wrapper around ``ExtractedMemory`` and ``MemoryEventLog``."""

    def insert_extracted_memory(self, **kwargs: Any) -> ExtractedMemory:
        row = ExtractedMemory(**kwargs)
        db.session.add(row)
        db.session.flush()
        return row

    def insert_event(self, **kwargs: Any) -> MemoryEventLog:
        row = MemoryEventLog(**kwargs)
        db.session.add(row)
        db.session.flush()
        return row

    def get_extracted_by_id(
        self, memory_id: int, *, customer_id: int, user_id: int
    ) -> Optional[ExtractedMemory]:
        return (
            ExtractedMemory.query.filter_by(
                id=memory_id, customer_id=customer_id, user_id=user_id
            ).first()
        )

    def list_events_for_extracted(
        self,
        extracted_memory_id: int,
        *,
        customer_id: int,
        user_id: int,
        limit: int = 100,
    ) -> List[MemoryEventLog]:
        return (
            MemoryEventLog.query.filter_by(
                extracted_memory_id=extracted_memory_id,
                customer_id=customer_id,
                user_id=user_id,
            )
            .order_by(MemoryEventLog.created_at.desc())
            .limit(limit)
            .all()
        )

    def list_extracted_for_user(
        self,
        *,
        customer_id: int,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[ExtractedMemory]:
        q = ExtractedMemory.query.filter_by(customer_id=customer_id, user_id=user_id)
        if status is not None:
            q = q.filter_by(status=status)
        return q.order_by(ExtractedMemory.created_at.desc()).limit(limit).all()

    def update_extracted_fields(
        self,
        memory_id: int,
        *,
        customer_id: int,
        user_id: int,
        fields: Dict[str, Any],
    ) -> Optional[ExtractedMemory]:
        row = self.get_extracted_by_id(memory_id, customer_id=customer_id, user_id=user_id)
        if row is None:
            return None
        for k, v in fields.items():
            if hasattr(row, k):
                setattr(row, k, v)
        db.session.flush()
        return row

    def list_active_for_retrieval(
        self,
        *,
        customer_id: int,
        user_id: int,
        prefetch: int = 200,
    ) -> List[ExtractedMemory]:
        """Active rows only; caller filters expires_at, scope, lexical match."""
        return (
            ExtractedMemory.query.filter_by(
                customer_id=customer_id, user_id=user_id, status="active"
            )
            .order_by(
                ExtractedMemory.importance.desc(),
                ExtractedMemory.created_at.desc(),
            )
            .limit(prefetch)
            .all()
        )

    def list_for_knowledge_recall(
        self,
        *,
        customer_id: int,
        user_id: int,
        offset: int = 0,
        limit: int = 8,
    ) -> Dict[str, Any]:
        """Knowledge read. Code Agent still uses list_active_for_retrieval.

        Tenant, user, active, expiry, supersession, global-user scope and page
        origin are applied before offset and limit. Session and project rows stay
        out: this version cannot prove project-level user authorization.
        ``matched`` is the filtered count, not a prefiltered sample.
        """
        now = datetime.now(timezone.utc)
        replaced = (
            db.session.query(ExtractedMemory.supersedes_id)
            .filter(
                ExtractedMemory.customer_id == customer_id,
                ExtractedMemory.user_id == user_id,
                ExtractedMemory.status == "active",
                ExtractedMemory.supersedes_id.isnot(None),
            )
        )
        page_type = ExtractedMemory.provenance_json.op("->>")("page_type")
        filtered = (
            ExtractedMemory.query.filter_by(
                customer_id=customer_id,
                user_id=user_id,
                status="active",
            )
            .filter(or_(ExtractedMemory.expires_at.is_(None), ExtractedMemory.expires_at > now))
            .filter(~ExtractedMemory.id.in_(replaced))
            .filter(
                or_(
                    ExtractedMemory.scope_type.is_(None),
                    ExtractedMemory.scope_type == "",
                    ExtractedMemory.scope_type == "global_user",
                )
            )
            .filter(or_(page_type.is_(None), func.lower(page_type).notin_(tuple(_CODE_AGENT_PAGES))))
        )
        matched = filtered.count()
        start = max(0, int(offset))
        size = max(1, min(int(limit), 8))
        rows = (
            filtered.order_by(
                ExtractedMemory.importance.desc(),
                ExtractedMemory.created_at.desc(),
                ExtractedMemory.id.desc(),
            )
            .offset(start)
            .limit(size)
            .all()
        )
        return {
            "rows": rows,
            "matched": int(matched),
            "returned": len(rows),
            "offset": start,
            "continuation_available": start + len(rows) < int(matched),
            "limited": False,
        }
