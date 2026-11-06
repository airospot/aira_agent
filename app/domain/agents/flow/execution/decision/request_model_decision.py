"""Request one model decision via the existing LLM adapter."""

from __future__ import annotations

from typing import Any, Mapping

from .agent_system_prompt import AGENT_SYSTEM_PROMPT
from .validate_model_decision import decision_schema

_TERMINAL_ONLY_SYSTEM_SUFFIX = """

This turn is terminal-only. The decision_schema permits only ANSWER, CLARIFY, or STOP_INCOMPLETE. CALL_TOOL is not permitted. Use only the observations already provided; do not invent missing technical fields. Partial catalog evidence (presence, group, selectability, source identity, missing description) is enough for a limited ANSWER when present.
"""


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
) -> dict[str, Any]:
    """Ask the model for one decision using the live JSON decision schema.

    When ``decision_constraints.terminal_only`` is true:
    - ``decision_schema`` excludes CALL_TOOL
    - ``permitted_tools`` is omitted (tools are not offered)
    - ``decision_mode`` is set so the constraint is visible in the user payload
    Observations are passed unchanged.
    """
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
        system_prompt = AGENT_SYSTEM_PROMPT + _TERMINAL_ONLY_SYSTEM_SUFFIX

    return client.complete_json(system_prompt, user_payload)
