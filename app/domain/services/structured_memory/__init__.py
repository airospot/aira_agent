"""
Structured memory — extraction (Phase 2 shadow) + frozen contracts.

**Path freeze:** ``app/domain/services/structured_memory/`` only — never
``app/domain/memory_extraction/``.

**DB deployment:** DDL external; writes fail until tables exist.

See package docstrings in ``constants.py``, ``orchestrator.py``, and
``sensitive_filter.py`` for frozen policies.
"""

from app.domain.services.structured_memory.constants import MEMORY_EVENT_TYPES_V1
from app.domain.services.structured_memory.orchestrator import (
    process_structured_memory_candidate,
)

__all__ = ["MEMORY_EVENT_TYPES_V1", "process_structured_memory_candidate"]
