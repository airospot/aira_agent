"""Bootstrap AgentRunService with production adapters (SQLAlchemy/app context OK here)."""

from __future__ import annotations

from typing import Any, Mapping

from app.domain.agents.flow.execution.run_policy import parse_run_policy
from app.domain.agents.flow.tooling.native_bootstrap import NATIVE_TOOL_NAMES
from app.domain.agents.run.adapters import (
    BridgeMemoryAdapter,
    SqlAlchemySubmissionAdapter,
    default_runner,
)
from app.domain.agents.run.contracts import ExecutionContext
from app.domain.agents.run.service import AgentRunService
from app.domain.agents.skills.catalog import STANDARD_SKILL_ID, normalize_skill_id
from app.domain.agents.skills.errors import SkillError
from app.domain.agents.skills.loader import bind_skill_tools, load_skill_snapshot
from app.shared.tenant_storage import resolve_tenant_storage


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
    skill_id: str | None = None,
) -> ExecutionContext:
    timeout = int(
        config.get("AGENT_SUBMISSION_TIMEOUT_SECONDS")
        or 15 * 60
    )
    # Per-request tenant corpus — no shared AGENT_CORPUS_DIR fallback.
    storage = resolve_tenant_storage(customer_id, config)
    root = storage.corpus_root
    # Single validation point for run budgets (form/model cannot override).
    policy = parse_run_policy(config)

    server_tools = frozenset(NATIVE_TOOL_NAMES)
    normalized = normalize_skill_id(skill_id)
    snapshot = load_skill_snapshot(normalized, config=config)
    try:
        effective = bind_skill_tools(
            snapshot,
            server_permitted=server_tools,
            registry_names=server_tools,
        )
    except SkillError:
        raise

    return ExecutionContext(
        customer_id=customer_id,
        user_id=user_id,
        corpus_root=str(root),
        permitted_tool_names=effective,
        submission_timeout_seconds=timeout,
        runner_config=config,
        run_policy=policy,
        skill_snapshot=snapshot,
    )


def skill_id_for_form(raw: object) -> str:
    """Normalize form/GET skill id; raises SkillError on unknown."""
    return normalize_skill_id(raw) if raw is not None and str(raw).strip() else STANDARD_SKILL_ID
