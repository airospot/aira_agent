"""Bootstrap AgentRunService with production adapters (SQLAlchemy/app context OK here)."""

from __future__ import annotations

from typing import Any, Mapping

from app.domain.agents.flow.tooling.native_bootstrap import NATIVE_TOOL_NAMES
from app.domain.agents.run.adapters import (
    BridgeMemoryAdapter,
    SqlAlchemySubmissionAdapter,
    default_runner,
)
from app.domain.agents.run.contracts import ExecutionContext
from app.domain.agents.run.service import AgentRunService
from app.shared.corpus_path_sandbox import resolve_corpus_root


def create_agent_run_service(**overrides: Any) -> AgentRunService:
    # Lazy import: agent_routes package imports propose which imports this factory.
    from app.interfaces.web.agent_routes.timeline_present import (
        present_flow_timeline,
        sanitize_flow_event,
    )

    memory = overrides.pop("memory", None) or BridgeMemoryAdapter()
    submissions = overrides.pop("submissions", None) or SqlAlchemySubmissionAdapter()
    runner = overrides.pop("runner", None) or default_runner
    present_timeline = overrides.pop("present_timeline", None) or present_flow_timeline
    sanitize_event = overrides.pop("sanitize_event", None) or sanitize_flow_event
    if overrides:
        raise TypeError(f"unexpected overrides: {sorted(overrides)}")
    return AgentRunService(
        memory=memory,
        submissions=submissions,
        runner=runner,
        present_timeline=present_timeline,
        sanitize_event=sanitize_event,
    )


def build_execution_context(
    *,
    customer_id: int,
    user_id: int,
    config: Mapping[str, Any],
) -> ExecutionContext:
    timeout = int(
        config.get("AGENT_SUBMISSION_TIMEOUT_SECONDS")
        or 15 * 60
    )
    root = resolve_corpus_root(config)
    return ExecutionContext(
        customer_id=customer_id,
        user_id=user_id,
        corpus_root=str(root),
        permitted_tool_names=frozenset(NATIVE_TOOL_NAMES),
        submission_timeout_seconds=timeout,
        runner_config=config,
    )
