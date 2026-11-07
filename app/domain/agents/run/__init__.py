"""Agent run application service (A02)."""

from app.domain.agents.run.contracts import ExecutionContext, RunOutcome, RunRequest
from app.domain.agents.run.service import AgentRunService

__all__ = [
    "AgentRunService",
    "ExecutionContext",
    "RunOutcome",
    "RunRequest",
]


def create_agent_run_service(**overrides):
    from app.domain.agents.run.factory import create_agent_run_service as _create

    return _create(**overrides)


def build_execution_context(**kwargs):
    from app.domain.agents.run.factory import build_execution_context as _build

    return _build(**kwargs)
