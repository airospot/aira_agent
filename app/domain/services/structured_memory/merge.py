"""v1 merge: same category + scope + normalized memory_text → one active row."""

from __future__ import annotations

from typing import Optional

from app.adapters.db.agents.models.structured_memory_tables import ExtractedMemory
from app.adapters.db.agents.repositories.structured_memory_repository import (
    StructuredMemoryRepository,
)
from app.domain.services.structured_memory.normalizer import normalize_memory_text


def find_active_duplicate(
    repo: StructuredMemoryRepository,
    *,
    customer_id: int,
    user_id: int,
    memory_category: str,
    scope_type: Optional[str],
    scope_value: Optional[str],
    normalized_text: str,
) -> Optional[ExtractedMemory]:
    rows = repo.list_extracted_for_user(
        customer_id=customer_id,
        user_id=user_id,
        status="active",
        limit=80,
    )
    for row in rows:
        if row.memory_category != memory_category:
            continue
        if (row.scope_type or None) != (scope_type or None):
            continue
        if (row.scope_value or None) != (scope_value or None):
            continue
        if normalize_memory_text(row.memory_text) == normalized_text:
            return row
    return None
