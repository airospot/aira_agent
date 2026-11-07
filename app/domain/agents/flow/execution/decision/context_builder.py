"""Bounded model-decision context builder (A03).

UTF-8 JSON byte budgets; never mid-codepoint cuts. Mandatory fields are never
silently truncated — overflow → context_budget_exceeded before LLM call.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from app.domain.agents.flow.execution.decision.agent_system_prompt import (
    AGENT_SYSTEM_PROMPT,
)
from app.domain.agents.flow.execution.decision.json_payload import (
    measure_decision_context_bytes,
)
from app.domain.agents.flow.execution.decision.observation_projection import (
    project_observations_for_model,
)
from app.domain.agents.flow.execution.decision.validate_model_decision import (
    decision_schema,
)
from app.domain.agents.flow.execution.run_policy import RunBudget

_TERMINAL_ONLY_SYSTEM_SUFFIX = """

This turn is terminal-only. The decision_schema permits only ANSWER, CLARIFY, or STOP_INCOMPLETE. CALL_TOOL is not permitted. Use only the observations already provided; do not invent missing technical fields. Partial catalog evidence (presence, group, selectability, source identity, missing description) is enough for a limited ANSWER when present.
"""


class ContextBuildError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _system_prompt(*, terminal_only: bool) -> str:
    if terminal_only:
        return AGENT_SYSTEM_PROMPT + _TERMINAL_ONLY_SYSTEM_SUFFIX
    return AGENT_SYSTEM_PROMPT


def _conversation_for_model(conversation: Any) -> Any:
    """Single canonical history copy for the model (no duplicate turns alias)."""
    if not isinstance(conversation, Mapping):
        return conversation
    src = dict(conversation)
    # Prefer active_conversation.turns; drop top-level turns duplicate for model.
    active = src.get("active_conversation")
    if isinstance(active, Mapping):
        active_copy = dict(active)
        turns = active_copy.get("turns")
        if isinstance(turns, list):
            active_copy["turns"] = list(turns)
        src["active_conversation"] = active_copy
        src.pop("turns", None)
        return src
    # Legacy list / bare turns only.
    if "turns" in src and isinstance(src.get("turns"), list):
        return {"turns": list(src["turns"])}
    return src


def _drop_optional_background(conversation: Any) -> Any:
    if not isinstance(conversation, Mapping):
        return conversation
    out = dict(conversation)
    for key in (
        "long_term_memory",
        "long_term_memory_entries",
        "long_term_retrieval",
        "long_term_memory_policy",
        "structured_memory",
        "structured_memory_policy",
        "historical_tool_references",
        "historical_tool_references_policy",
    ):
        out.pop(key, None)
    return out


def _trim_oldest_turns(conversation: Any) -> tuple[Any, bool]:
    """Remove oldest turn pair when possible; keep the latest user/assistant pair."""
    if not isinstance(conversation, Mapping):
        return conversation, False
    out = dict(conversation)
    active = out.get("active_conversation")
    if isinstance(active, Mapping) and isinstance(active.get("turns"), list):
        turns = list(active["turns"])
        if len(turns) <= 2:
            return out, False
        # Drop oldest single message; prefer dropping a full pair when roles allow.
        if len(turns) >= 4:
            turns = turns[2:]
        else:
            turns = turns[1:]
        active_copy = dict(active)
        active_copy["turns"] = turns
        active_copy["turn_count"] = len(turns)
        active_copy["is_empty"] = len(turns) == 0
        out["active_conversation"] = active_copy
        return out, True
    turns = out.get("turns")
    if isinstance(turns, list) and len(turns) > 2:
        if len(turns) >= 4:
            out["turns"] = turns[2:]
        else:
            out["turns"] = turns[1:]
        return out, True
    return out, False


def build_model_decision_context(
    request_text: str,
    conversation: Any,
    observations: Any,
    *,
    budget: RunBudget,
    permitted_tools: Any = None,
    decision_constraints: Any = None,
) -> dict[str, Any]:
    """Return {system_prompt, user_payload, meta} within budget or raise."""
    terminal_only = bool(
        isinstance(decision_constraints, Mapping)
        and decision_constraints.get("terminal_only")
    )
    schema = decision_schema(terminal_only=terminal_only)
    system_prompt = _system_prompt(terminal_only=terminal_only)

    projected, obs_meta = project_observations_for_model(
        observations,
        max_observation_bytes=budget.policy.max_observation_bytes,
    )
    budget.last_observation_bytes = obs_meta.get("serialized_bytes")
    budget.observation_truncated = bool(obs_meta.get("truncated"))
    if obs_meta.get("overflow"):
        budget.mark_observation_exceeded()
        raise ContextBuildError(
            "observation_budget_exceeded",
            "observation projection exceeds budget",
        )

    conv = _conversation_for_model(deepcopy(conversation) if conversation is not None else {})
    truncated_history = False

    def _payload(conv_view: Any) -> dict[str, Any]:
        user_payload: dict[str, Any] = {
            "request_text": request_text,
            "conversation": conv_view,
            "observations": projected,
            "decision_schema": schema,
            "decision_mode": "terminal_only" if terminal_only else "normal",
        }
        if not terminal_only and permitted_tools is not None:
            user_payload["permitted_tools"] = permitted_tools
        return user_payload

    def _fits(user_payload: dict[str, Any]) -> tuple[bool, int]:
        total = measure_decision_context_bytes(system_prompt, user_payload)
        return total <= budget.policy.max_context_bytes, total

    # Mandatory core without optional background / with tools+schema+request.
    mandatory = _payload(_drop_optional_background(conv) if isinstance(conv, Mapping) else conv)
    # Strip history turns entirely for mandatory check of fixed fields.
    if isinstance(mandatory.get("conversation"), Mapping):
        bare = dict(mandatory["conversation"])
        if isinstance(bare.get("active_conversation"), Mapping):
            ac = dict(bare["active_conversation"])
            ac["turns"] = []
            ac["turn_count"] = 0
            ac["is_empty"] = True
            bare["active_conversation"] = ac
        bare.pop("turns", None)
        mandatory["conversation"] = bare
    ok_m, size_m = _fits(mandatory)
    if not ok_m:
        budget.last_context_bytes = size_m
        budget.mark_context_exceeded()
        raise ContextBuildError(
            "context_budget_exceeded",
            "mandatory decision context exceeds AGENT_MAX_CONTEXT_BYTES",
        )

    # Shrink optional parts until fit.
    working = conv
    payload = _payload(working)
    ok, size = _fits(payload)
    if not ok:
        working = _drop_optional_background(working)
        truncated_history = True
        payload = _payload(working)
        ok, size = _fits(payload)

    while not ok:
        working, changed = _trim_oldest_turns(working)
        if not changed:
            break
        truncated_history = True
        payload = _payload(working)
        ok, size = _fits(payload)

    if not ok:
        # Keep empty history + projected observations; if still over, fail.
        if isinstance(working, Mapping):
            working = _drop_optional_background(working)
            if isinstance(working.get("active_conversation"), Mapping):
                ac = dict(working["active_conversation"])
                ac["turns"] = []
                ac["turn_count"] = 0
                ac["is_empty"] = True
                working = dict(working)
                working["active_conversation"] = ac
            working.pop("turns", None)
            truncated_history = True
            payload = _payload(working)
            ok, size = _fits(payload)

    if not ok:
        budget.last_context_bytes = size
        budget.mark_context_exceeded()
        raise ContextBuildError(
            "context_budget_exceeded",
            "decision context exceeds AGENT_MAX_CONTEXT_BYTES after trimming",
        )

    budget.last_context_bytes = size
    budget.context_truncated = truncated_history or bool(obs_meta.get("truncated"))
    return {
        "system_prompt": system_prompt,
        "user_payload": payload,
        "meta": {
            "context_bytes": size,
            "context_truncated": budget.context_truncated,
            "observation_meta": obs_meta,
            "terminal_only": terminal_only,
        },
    }
