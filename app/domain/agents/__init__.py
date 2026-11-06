"""Memory service export used by Native Flow.

Source ``app/domain/agents/__init__.py`` eager-imports legacy agents
(code analyzer, tool router, intent classifier). Native Flow's
memory bridge only executes ``from app.domain.agents import memory_service``.
"""
from . import memory_service

__all__ = ["memory_service"]
