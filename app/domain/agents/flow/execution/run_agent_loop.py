"""Minimal Knowledge Agent execution loop.

Orchestrates decide → validate → optional execute_tool.
No prompt, provider, JSON parsing, tool selection, or semantic logic.
"""

from __future__ import annotations

import json
from typing import Any, Callable


_TERMINAL = frozenset({"ANSWER", "CLARIFY", "STOP_INCOMPLETE"})

# Observation statuses that may recover on a later identical call (transient).
_RETRYABLE_OBSERVATION_STATUSES = frozenset(
    {
        "error",
    }
)

_TERMINAL_ONLY_VIOLATION_REASON = (
    "Mevcut gözlemlerle terminal karar beklenirken yeniden araç çağrısı yapıldı."
)
_STEP_BUDGET_REASON = (
    "Adım bütçesi doldu; mevcut gözlemlerle tamamlanamadı."
)


def _failure(stage: str, exc: BaseException) -> dict[str, Any]:
    return {
        "status": "ERROR",
        "stage": stage,
        "error_class": type(exc).__name__,
    }


def _error(stage: str, code: str) -> dict[str, Any]:
    return {
        "status": "ERROR",
        "stage": stage,
        "error": code,
    }


def _stop_incomplete(reason: str, observations: list[Any]) -> dict[str, Any]:
    return {
        "status": "STOP_INCOMPLETE",
        "decision": {
            "action": "STOP_INCOMPLETE",
            "reason": reason,
        },
        "observations": observations,
    }


def _canonicalize_json(value: Any) -> Any:
    """JSON-compatible canonical form (dict keys sorted; nested list/dict ok)."""
    if isinstance(value, dict):
        return {
            str(key): _canonicalize_json(value[key])
            for key in sorted(value.keys(), key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_canonicalize_json(item) for item in value]
    if isinstance(value, str):
        return value.strip()
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value
    # Non-JSON scalars → stable string; never raise to the Flow boundary.
    return str(value)


def _canonicalize_arguments(args: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _canonicalize_json(args[key])
        for key in sorted(args.keys(), key=lambda item: str(item))
    }


def _tool_request_fingerprint(decision: Any) -> str | None:
    """Request-scoped identity of a CALL_TOOL decision (tool + canonical args).

    Returns a hashable JSON string. Nested list/dict arguments are supported.
    Fingerprint failures return None (call proceeds untracked) — never raise.
    """
    try:
        if not isinstance(decision, dict):
            return None
        tool = decision.get("tool")
        if not isinstance(tool, str) or not tool:
            return None
        args = decision.get("arguments")
        if not isinstance(args, dict):
            args = {}
        payload = {
            "tool": tool,
            "arguments": _canonicalize_arguments(args),
        }
        return json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError):
        return None


def _observation_fingerprint(observation: Any) -> str:
    try:
        return json.dumps(
            _canonicalize_json(observation),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        )
    except (TypeError, ValueError, RecursionError):
        return repr(observation)


def _observation_status(observation: Any) -> str | None:
    if isinstance(observation, dict) and observation.get("status") is not None:
        return str(observation.get("status"))
    return None


def _is_retryable_prior(prior: dict[str, Any]) -> bool:
    status = prior.get("status")
    return isinstance(status, str) and status in _RETRYABLE_OBSERVATION_STATUSES


def _call_decide(
    decide: Callable[..., Any],
    request_text: str,
    conversation: Any,
    observations: list[Any],
    *,
    terminal_only: bool,
) -> Any:
    if terminal_only:
        return decide(
            request_text,
            conversation,
            observations,
            decision_constraints={"terminal_only": True},
        )
    try:
        return decide(
            request_text,
            conversation,
            observations,
            decision_constraints=None,
        )
    except TypeError:
        # Legacy 3-arg decide callables (isolated fixtures / older adapters).
        return decide(request_text, conversation, observations)


def _call_validate(
    validate: Callable[..., Any],
    decision: Any,
    *,
    terminal_only: bool,
) -> Any:
    if terminal_only:
        return validate(decision, terminal_only=True)
    try:
        return validate(decision, terminal_only=False)
    except TypeError:
        return validate(decision)


def run_agent_loop(
    request_text: str,
    conversation: Any,
    decide: Callable[..., Any],
    validate: Callable[..., Any],
    execute_tool: Callable[..., Any] | None = None,
    max_steps: int = 8,
) -> dict[str, Any]:
    observations: list[Any] = []
    # Request-scoped only: tool+args fingerprint → prior observation record.
    prior_tool_results: dict[str, dict[str, Any]] = {}
    # After a no-progress duplicate CALL_TOOL, next decide/validate are terminal-only.
    awaiting_terminal_only = False

    for step in range(1, max_steps + 1):
        # Finalization reserve: last decision slot is terminal-only so the model
        # must ANSWER / CLARIFY / STOP_INCOMPLETE from existing observations
        # instead of spending the budget on a CALL_TOOL that cannot execute.
        terminal_only = awaiting_terminal_only or step >= max_steps
        try:
            decision = _call_decide(
                decide,
                request_text,
                conversation,
                observations,
                terminal_only=terminal_only,
            )
        except Exception as exc:  # noqa: BLE001 — stage-bounded technical failure
            return _failure("decide", exc)

        try:
            action = _call_validate(
                validate,
                decision,
                terminal_only=terminal_only,
            )
        except Exception as exc:  # noqa: BLE001 — stage-bounded technical failure
            return _failure("validate", exc)

        if action in _TERMINAL:
            return {
                "status": action,
                "decision": decision,
                "observations": observations,
            }

        if action == "CALL_TOOL":
            if terminal_only:
                # Defense in depth: terminal schema should have rejected this
                # (duplicate-driven or finalization-reserve terminal_only).
                return _stop_incomplete(
                    _TERMINAL_ONLY_VIOLATION_REASON,
                    observations,
                )

            request_fp = _tool_request_fingerprint(decision)
            prior = prior_tool_results.get(request_fp) if request_fp else None

            if prior is not None and not _is_retryable_prior(prior):
                # Same definitive tool+args: do not re-execute; next decide is
                # terminal-only with constrained schema in the real model request.
                awaiting_terminal_only = True
                continue

            if execute_tool is None:
                return _error("execute_tool", "execute_tool_missing")
            try:
                observation = execute_tool(decision)
            except Exception as exc:  # noqa: BLE001 — stage-bounded technical failure
                return _failure("execute_tool", exc)

            observations.append(observation)
            if request_fp is not None:
                prior_tool_results[request_fp] = {
                    "observation_fingerprint": _observation_fingerprint(observation),
                    "status": _observation_status(observation),
                }
            continue

        return _error("validate", "unknown_action")

    return _stop_incomplete(_STEP_BUDGET_REASON, observations)
