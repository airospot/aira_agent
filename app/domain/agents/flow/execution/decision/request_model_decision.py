"""Request one model decision via the existing LLM adapter."""

from __future__ import annotations

from typing import Any, Mapping

from app.domain.agents.flow.execution.decision.context_builder import (
    ContextBuildError,
    build_model_decision_context,
)
from app.domain.agents.flow.execution.run_policy import RunBudget


def _is_terminal_only(decision_constraints: Any) -> bool:
    if not isinstance(decision_constraints, Mapping):
        return False
    return bool(decision_constraints.get("terminal_only"))


def request_model_decision(
    request_text: str,
    conversation: Any,
    observations: Any,
    client: Any,
    permitted_tools: Any = None,
    decision_constraints: Any = None,
    *,
    budget: RunBudget | None = None,
) -> dict[str, Any]:
    """Ask the model for one decision using the live JSON decision schema.

    When ``budget`` is provided, builds a bounded context first. Overflow raises
    ``ContextBuildError`` without calling the LLM.
    Per-call HTTP timeout uses remaining run budget when available.

    urllib timeout is not a guaranteed total wall-clock kill in every OS/Python
    edge case; remaining budget is still checked after the call returns.
    """
    if budget is None:
        # Legacy path (isolated fixtures): unbounded payload.
        from app.domain.agents.flow.execution.decision.agent_system_prompt import (
            AGENT_SYSTEM_PROMPT,
        )
        from app.domain.agents.flow.execution.decision.validate_model_decision import (
            decision_schema,
        )

        terminal_only = _is_terminal_only(decision_constraints)
        schema = decision_schema(terminal_only=terminal_only)
        user_payload: dict[str, Any] = {
            "request_text": request_text,
            "conversation": conversation,
            "observations": observations,
            "decision_schema": schema,
            "decision_mode": "terminal_only" if terminal_only else "normal",
        }
        if not terminal_only and permitted_tools is not None:
            user_payload["permitted_tools"] = permitted_tools
        system_prompt = AGENT_SYSTEM_PROMPT
        if terminal_only:
            from app.domain.agents.flow.execution.decision.context_builder import (
                _TERMINAL_ONLY_SYSTEM_SUFFIX,
            )

            system_prompt = AGENT_SYSTEM_PROMPT + _TERMINAL_ONLY_SYSTEM_SUFFIX
        return client.complete_json(system_prompt, user_payload)

    if budget.deadline_exceeded():
        budget.mark_deadline()
        raise ContextBuildError("run_deadline_exceeded", "deadline before LLM call")

    built = build_model_decision_context(
        request_text,
        conversation,
        observations,
        budget=budget,
        permitted_tools=permitted_tools,
        decision_constraints=decision_constraints,
    )
    configured = getattr(client, "timeout_seconds", 75)
    http_timeout = budget.llm_http_timeout_seconds(configured)
    if http_timeout <= 0:
        budget.mark_deadline()
        raise ContextBuildError("run_deadline_exceeded", "no time left for LLM call")

    decision = client.complete_json(
        built["system_prompt"],
        built["user_payload"],
        timeout_seconds=http_timeout,
        max_context_bytes=budget.policy.max_context_bytes,
    )
    if budget.deadline_exceeded():
        budget.mark_deadline()
        raise ContextBuildError(
            "run_deadline_exceeded",
            "deadline exceeded after LLM returned",
        )
    return decision
