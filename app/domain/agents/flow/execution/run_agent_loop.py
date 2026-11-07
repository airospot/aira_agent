"""Minimal Knowledge Agent execution loop.

Orchestrates decide → validate → optional execute_tool.
No prompt, provider, JSON parsing, tool selection, or semantic logic.
A03: run budget / deadline / limited retries via optional RunBudget + tool policy.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from jsonschema.exceptions import ValidationError

from app.domain.agents.flow.execution.llm.client import FlowLlmClientError
from app.domain.agents.flow.execution.run_policy import (
    RunBudget,
    stop_incomplete_payload,
)
from app.domain.agents.skills.completion import (
    content_answer_allowed,
    correction_feedback_observation,
    evidence_missing_code,
    evidence_missing_reason,
)
from app.domain.agents.skills.snapshot import SkillSnapshot

_LLM_OUTPUT_LIMIT_REASON = (
    "Model çıktı limiti doldu; geçerli bir karar JSON'u üretilmedi."
)
_LLM_MALFORMED_REASON = (
    "Model yanıtı geçerli karar JSON'u içermiyor."
)
_LLM_CONTEXT_REASON = (
    "Gönderilecek bağlam bayt limiti aşıldı."
)


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

# ToolSpec.retry_policy values accepted in A03.
_SUPPORTED_RETRY_POLICIES = frozenset({None, "none", "transient"})


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


def _stop_incomplete(reason: str, observations: list[Any], *, code: str | None = None) -> dict[str, Any]:
    if code:
        return stop_incomplete_payload(code=code, reason=reason, observations=observations)
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
    return str(value)


def _canonicalize_arguments(args: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _canonicalize_json(args[key])
        for key in sorted(args.keys(), key=lambda item: str(item))
    }


def _tool_request_fingerprint(decision: Any) -> str | None:
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


def _tool_meta(lookup: Callable[[str], Mapping[str, Any] | None] | None, tool: str) -> Mapping[str, Any]:
    if lookup is None:
        return {}
    meta = lookup(tool)
    return meta if isinstance(meta, Mapping) else {}


def _validate_retry_policy(policy: Any) -> str | None:
    if policy is None:
        return None
    text = str(policy).strip().lower()
    if text not in {"none", "transient"}:
        raise ValueError(f"unsupported retry_policy: {policy!r}")
    return text


def _may_retry_error(
    *,
    budget: RunBudget | None,
    fingerprint: str | None,
    tool_meta: Mapping[str, Any],
) -> bool:
    side = str(tool_meta.get("side_effect_class") or "read").strip().lower()
    if side == "write":
        return False
    policy = _validate_retry_policy(tool_meta.get("retry_policy"))
    if policy == "none":
        return False
    # Default / transient: allow up to max_tool_retries additional attempts.
    if budget is None or fingerprint is None:
        return True
    if budget.deadline_exceeded():
        return False
    used = budget.retries_used(fingerprint)
    return used < budget.policy.max_tool_retries


def _is_repeatable_success(tool_meta: Mapping[str, Any]) -> bool:
    extra = tool_meta.get("extra_metadata")
    if isinstance(extra, Mapping) and bool(extra.get("repeatable")):
        return True
    return bool(tool_meta.get("repeatable"))


def _tag_observation(observation: Any, tool_name: str) -> Any:
    if not isinstance(observation, dict) or not tool_name:
        return observation
    if observation.get("tool"):
        return observation
    tagged = dict(observation)
    tagged["tool"] = tool_name
    return tagged


def run_agent_loop(
    request_text: str,
    conversation: Any,
    decide: Callable[..., Any],
    validate: Callable[..., Any],
    execute_tool: Callable[..., Any] | None = None,
    max_steps: int | None = None,
    *,
    budget: RunBudget | None = None,
    tool_meta_lookup: Callable[[str], Mapping[str, Any] | None] | None = None,
    skill_snapshot: SkillSnapshot | None = None,
) -> dict[str, Any]:
    observations: list[Any] = []
    prior_tool_results: dict[str, dict[str, Any]] = {}
    awaiting_terminal_only = False
    require_read = bool(
        skill_snapshot is not None
        and skill_snapshot.requires_file_read_for_content_answer()
    )

    if budget is not None:
        steps = budget.policy.max_steps
    elif max_steps is not None:
        steps = int(max_steps)
    else:
        raise ValueError("max_steps or budget.policy.max_steps is required")

    for step in range(1, steps + 1):
        if budget is not None and budget.deadline_exceeded():
            budget.mark_deadline()
            return _stop_incomplete(
                budget.stop_reason or _STEP_BUDGET_REASON,
                observations,
                code=budget.stop_code,
            )

        terminal_only = awaiting_terminal_only or step >= steps
        try:
            decision = _call_decide(
                decide,
                request_text,
                conversation,
                observations,
                terminal_only=terminal_only,
            )
        except Exception as exc:  # noqa: BLE001
            # Context/deadline coded stops surface as STOP_INCOMPLETE when tagged.
            code = getattr(exc, "code", None)
            if isinstance(code, str) and code in {
                "context_budget_exceeded",
                "observation_budget_exceeded",
                "run_deadline_exceeded",
            }:
                if budget is not None:
                    if code == "run_deadline_exceeded":
                        budget.mark_deadline()
                    elif code == "context_budget_exceeded":
                        budget.mark_context_exceeded()
                    else:
                        budget.mark_observation_exceeded()
                    return _stop_incomplete(
                        budget.stop_reason or str(exc),
                        observations,
                        code=budget.stop_code or code,
                    )
                return _stop_incomplete(str(exc), observations, code=code)
            if isinstance(exc, FlowLlmClientError):
                llm_code = str(exc.error_class or "")
                if llm_code == "output_limit":
                    return _stop_incomplete(
                        _LLM_OUTPUT_LIMIT_REASON,
                        observations,
                        code="output_limit",
                    )
                if llm_code == "malformed_model_response":
                    return _stop_incomplete(
                        _LLM_MALFORMED_REASON,
                        observations,
                        code="malformed_model_response",
                    )
                if llm_code == "context_budget_exceeded":
                    if budget is not None:
                        budget.mark_context_exceeded()
                    return _stop_incomplete(
                        _LLM_CONTEXT_REASON,
                        observations,
                        code="context_budget_exceeded",
                    )
            return _failure("decide", exc)

        if budget is not None and budget.deadline_exceeded():
            budget.mark_deadline()
            return _stop_incomplete(
                budget.stop_reason or _STEP_BUDGET_REASON,
                observations,
                code=budget.stop_code,
            )

        try:
            action = _call_validate(
                validate,
                decision,
                terminal_only=terminal_only,
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, ValidationError):
                return _stop_incomplete(
                    "Modelin karar biçimi doğrulanamadı; inceleme tamamlanamadı. Yeni bir gönderimle tekrar deneyebilirsiniz.",
                    observations,
                    code="invalid_model_decision",
                )
            if terminal_only:
                # Model emitted a non-terminal action under terminal-only schema.
                return _stop_incomplete(
                    _TERMINAL_ONLY_VIOLATION_REASON,
                    observations,
                )
            return _failure("validate", exc)

        if action in _TERMINAL:
            if (
                action == "ANSWER"
                and require_read
                and not content_answer_allowed(observations)[0]
            ):
                # Do not accept content-report ANSWER without file_read evidence.
                already_nudged = any(
                    isinstance(obs, dict)
                    and obs.get("status") == "skill_requirement"
                    and obs.get("error") == evidence_missing_code()
                    for obs in observations
                )
                if terminal_only or step >= steps or already_nudged:
                    return _stop_incomplete(
                        evidence_missing_reason(),
                        observations,
                        code=evidence_missing_code(),
                    )
                # One limited correction feedback, then continue within budget.
                observations.append(correction_feedback_observation())
                awaiting_terminal_only = False
                continue
            out = {
                "status": action,
                "decision": decision,
                "observations": observations,
            }
            return out

        if action == "CALL_TOOL":
            if terminal_only:
                return _stop_incomplete(
                    _TERMINAL_ONLY_VIOLATION_REASON,
                    observations,
                )

            if budget is not None and budget.deadline_exceeded():
                budget.mark_deadline()
                return _stop_incomplete(
                    budget.stop_reason or _STEP_BUDGET_REASON,
                    observations,
                    code=budget.stop_code,
                )

            request_fp = _tool_request_fingerprint(decision)
            tool_name = ""
            if isinstance(decision, dict):
                tool_name = str(decision.get("tool") or "")
            meta = _tool_meta(tool_meta_lookup, tool_name)
            # Reject unsupported retry_policy early (no silent accept).
            _validate_retry_policy(meta.get("retry_policy"))

            prior = prior_tool_results.get(request_fp) if request_fp else None
            if prior is not None:
                status = prior.get("status")
                if status == "ok" or (
                    isinstance(status, str)
                    and status not in _RETRYABLE_OBSERVATION_STATUSES
                ):
                    if not _is_repeatable_success(meta):
                        awaiting_terminal_only = True
                        continue
                elif _is_retryable_prior(prior):
                    if not _may_retry_error(
                        budget=budget, fingerprint=request_fp, tool_meta=meta
                    ):
                        awaiting_terminal_only = True
                        continue
                    if budget is not None and request_fp is not None:
                        budget.record_retry(request_fp)

            if execute_tool is None:
                return _error("execute_tool", "execute_tool_missing")
            try:
                observation = execute_tool(decision)
            except Exception as exc:  # noqa: BLE001
                return _failure("execute_tool", exc)

            observation = _tag_observation(observation, tool_name)
            if budget is not None and budget.deadline_exceeded():
                # Late result is not treated as normal success for continuation.
                budget.mark_deadline()
                if isinstance(observation, dict):
                    late = dict(observation)
                    late["late_after_deadline"] = True
                    observations.append(late)
                else:
                    observations.append(observation)
                return _stop_incomplete(
                    budget.stop_reason or _STEP_BUDGET_REASON,
                    observations,
                    code=budget.stop_code,
                )

            observations.append(observation)
            if request_fp is not None:
                prior_tool_results[request_fp] = {
                    "observation_fingerprint": _observation_fingerprint(observation),
                    "status": _observation_status(observation),
                }
            continue

        return _error("validate", "unknown_action")

    if budget is not None:
        budget.mark_steps_exceeded()
        return _stop_incomplete(
            budget.stop_reason or _STEP_BUDGET_REASON,
            observations,
            code=budget.stop_code,
        )
    return _stop_incomplete(_STEP_BUDGET_REASON, observations)
