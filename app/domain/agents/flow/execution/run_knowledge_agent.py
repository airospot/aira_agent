"""Knowledge Agent Flow runner — registry/executor-backed native file tools."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Mapping

from app.domain.agents.flow.execution.decision.request_model_decision import (
    request_model_decision,
)
from app.domain.agents.flow.execution.decision.validate_model_decision import (
    validate_model_decision,
)
from app.domain.agents.flow.execution.events import (
    build_flow_event,
    emit_flow_event,
)
from app.domain.agents.flow.execution.llm.factory import (
    create_flow_llm_client,
)
from app.domain.agents.flow.execution.answer_show_image import (
    enrich_answer_with_show_images,
)
from app.domain.agents.flow.execution.run_agent_loop import (
    run_agent_loop,
)
from app.domain.agents.flow.execution.run_policy import (
    RunBudget,
    RunPolicy,
    parse_run_policy,
)
from app.domain.agents.flow.tooling import (
    ToolExecutor,
    ToolNotPermittedError,
    ToolNotRegisteredError,
    ToolRegistry,
    build_native_tool_registry,
)
from app.domain.agents.flow.tooling.native_bootstrap import NATIVE_TOOL_NAMES

_FILE_READ_ARG_KEYS = ("path",)
_FILE_SEARCH_ARG_KEYS = ("query", "glob", "limit")
_FILE_NAME_SEARCH_ARG_KEYS = ("query", "glob", "limit")
_SHOW_IMAGE_ARG_KEYS = ("path",)


def run_knowledge_agent(
    request_text: str,
    *,
    conversation: Any,
    config: Mapping[str, Any] | None,
    dataset_dir: str | Path | None = None,  # unused; kept for call-site compat
    on_event: Callable[[Mapping[str, Any]], Any] | None = None,
    caller_context: Mapping[str, Any] | None = None,
    tool_registry: ToolRegistry | None = None,
    permitted_tool_names: set[str] | frozenset[str] | None = None,
    run_policy: RunPolicy | None = None,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Run one agent turn with corpus file tools via shared registry/executor."""
    del dataset_dir, caller_context  # legacy kwargs ignored
    policy = run_policy or parse_run_policy(config)
    budget = RunBudget.start(policy, clock=clock)
    client = create_flow_llm_client(config)

    registry = tool_registry or build_native_tool_registry()
    if permitted_tool_names is None:
        permitted = frozenset(NATIVE_TOOL_NAMES)
    else:
        permitted = frozenset(str(n).strip() for n in permitted_tool_names if str(n).strip())
    executor = ToolExecutor(registry, permitted_names=permitted)

    permitted_tools = registry.catalog(names=permitted)
    tool_names = {
        "file_read": "file_read",
        "file_search": "file_search",
        "file_name_search": "file_name_search",
        "show_image": "show_image",
    }
    for entry in permitted_tools:
        name = entry.get("name")
        if isinstance(name, str) and name in tool_names:
            tool_names[name] = name

    flow_started_at = time.perf_counter()
    step = 0
    seen_observations = 0
    last_tool: str | None = None
    decision_trace: list[dict[str, Any]] = []

    def _emit(
        event: str,
        *,
        action: str | None = None,
        tool: str | None = None,
        status: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        emit_flow_event(
            on_event,
            build_flow_event(
                event,
                flow_started_at=flow_started_at,
                step=step if step > 0 else None,
                action=action,
                tool=tool,
                status=status,
                duration_ms=duration_ms,
            ),
        )

    def _tool_meta_lookup(tool: str) -> dict[str, Any] | None:
        spec = registry.get(tool)
        if spec is None:
            return None
        return {
            "side_effect_class": spec.side_effect_class,
            "retry_policy": spec.retry_policy,
            "cache_policy": spec.cache_policy,
            "timeout_seconds": spec.timeout_seconds,
            "extra_metadata": dict(spec.extra_metadata or {}),
            "repeatable": bool((spec.extra_metadata or {}).get("repeatable")),
        }

    def _decide(request_text, conversation, observations, decision_constraints=None):
        nonlocal step, seen_observations
        step += 1
        obs_count = len(observations) if observations is not None else 0
        if obs_count > seen_observations:
            _emit("observation_consumed", tool=last_tool, status="ok")
            seen_observations = obs_count
        terminal_only = bool(
            isinstance(decision_constraints, Mapping)
            and decision_constraints.get("terminal_only")
        )
        _emit("decide_started")
        started = time.perf_counter()
        try:
            decision = request_model_decision(
                request_text,
                conversation,
                observations,
                client,
                permitted_tools=permitted_tools,
                decision_constraints=decision_constraints,
                budget=budget,
            )
        except Exception as exc:  # noqa: BLE001
            _emit("error", status=type(exc).__name__, duration_ms=_duration_ms(started))
            raise
        decide_ms = _duration_ms(started)
        _emit("decide_finished", duration_ms=decide_ms)
        usage = _client_usage(client)
        if usage:
            budget.usage_by_step.append({"step": step, **usage})
        decision_trace.append(
            _trace_decision_record(
                step=step,
                decision=decision if isinstance(decision, Mapping) else None,
                decide_duration_ms=decide_ms,
                observations_available=obs_count,
                tool_names=tool_names,
                decision_mode="terminal_only" if terminal_only else "normal",
                usage=usage,
                context_bytes=budget.last_context_bytes,
                observation_bytes=budget.last_observation_bytes,
                context_truncated=budget.context_truncated,
                observation_truncated=budget.observation_truncated,
            )
        )
        return decision

    def _validate(decision, terminal_only=False):
        started = time.perf_counter()
        try:
            action = validate_model_decision(
                decision,
                terminal_only=bool(terminal_only),
            )
        except Exception as exc:  # noqa: BLE001
            _emit("error", status=type(exc).__name__, duration_ms=_duration_ms(started))
            raise
        _emit("validate_finished", action=str(action), duration_ms=_duration_ms(started))
        return action

    def _execute_tool(decision):
        nonlocal last_tool
        tool = decision.get("tool")
        if not isinstance(tool, str) or not tool:
            _emit("error", status="tool_not_permitted")
            raise ValueError("tool_not_permitted")
        _emit("tool_started", action="CALL_TOOL", tool=tool)
        started = time.perf_counter()
        slice_s = budget.tool_slice_seconds()
        if slice_s <= 0:
            budget.mark_deadline()
            _emit(
                "tool_finished",
                action="CALL_TOOL",
                tool=tool,
                status="tool_deadline_exceeded",
                duration_ms=_duration_ms(started),
            )
            return {
                "status": "error",
                "error": "tool_deadline_exceeded",
                "path": None,
                "source_filename": None,
                "display_name": None,
                "source_known": False,
                "source_ambiguous": False,
            }
        control = {
            "deadline_monotonic": budget.now() + slice_s,
            "remaining_seconds": slice_s,
            "tool_timeout_seconds": budget.policy.tool_timeout_seconds,
            "clock": budget.clock,
        }
        try:
            observation = executor.execute(
                tool,
                decision.get("arguments"),
                config=config,
                execution_control=control,
            )
        except (ToolNotPermittedError, ToolNotRegisteredError):
            _emit("error", status="tool_not_permitted")
            raise ValueError("tool_not_permitted")
        except Exception as exc:  # noqa: BLE001
            _emit(
                "error",
                action="CALL_TOOL",
                tool=tool,
                status=type(exc).__name__,
                duration_ms=_duration_ms(started),
            )
            raise
        last_tool = tool
        tool_ms = _duration_ms(started)
        obs_status = None
        if isinstance(observation, Mapping) and observation.get("status") is not None:
            obs_status = str(observation.get("status"))
        _emit(
            "tool_finished",
            action="CALL_TOOL",
            tool=tool,
            status=obs_status,
            duration_ms=tool_ms,
        )
        if decision_trace:
            decision_trace[-1]["tool_duration_ms"] = tool_ms
            decision_trace[-1]["tool_status"] = obs_status
            decision_trace[-1]["observation"] = _summarize_observation(
                observation,
                tool=tool,
                tool_names=tool_names,
            )
        return observation

    result = run_agent_loop(
        request_text,
        conversation,
        _decide,
        _validate,
        execute_tool=_execute_tool,
        budget=budget,
        tool_meta_lookup=_tool_meta_lookup,
    )
    status = result.get("status")
    action = None
    decision = result.get("decision")
    if isinstance(decision, dict) and decision.get("action") is not None:
        action = str(decision.get("action"))
    if (
        str(status) == "ANSWER"
        and isinstance(decision, dict)
        and isinstance(decision.get("answer"), str)
    ):
        decision = dict(decision)
        decision["answer"] = enrich_answer_with_show_images(
            decision.get("answer"),
            result.get("observations"),
        )
        result = dict(result)
        result["decision"] = decision
    _emit(
        "flow_completed",
        action=action,
        status=str(status) if status is not None else None,
        duration_ms=_duration_ms(flow_started_at),
    )
    out = dict(result)
    out["decision_trace"] = decision_trace
    out["decision_trace_final_status"] = str(status) if status is not None else None
    out["decision_trace_final_action"] = action
    out["run_budget"] = budget.as_trace_metadata()
    return out


def _client_usage(client: Any) -> dict[str, Any] | None:
    meta = getattr(client, "last_meta", None)
    if not isinstance(meta, Mapping) or not meta:
        return None
    out: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens", "model", "request_id"):
        if key in meta:
            out[key] = meta.get(key)
    return out or None


def _trace_decision_record(
    *,
    step: int,
    decision: Mapping[str, Any] | None,
    decide_duration_ms: int,
    observations_available: int,
    tool_names: Mapping[str, str],
    decision_mode: str,
    usage: Mapping[str, Any] | None = None,
    context_bytes: int | None = None,
    observation_bytes: int | None = None,
    context_truncated: bool = False,
    observation_truncated: bool = False,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "step": step,
        "decision_mode": decision_mode,
        "decide_duration_ms": decide_duration_ms,
        "observations_available": observations_available,
        "action": None,
        "tool": None,
        "arguments": None,
        "context_bytes": context_bytes,
        "observation_bytes": observation_bytes,
        "context_truncated": context_truncated,
        "observation_truncated": observation_truncated,
    }
    if usage:
        record["usage"] = dict(usage)
    if not isinstance(decision, Mapping):
        return record
    action = decision.get("action")
    record["action"] = str(action) if action is not None else None
    tool = decision.get("tool")
    if isinstance(tool, str) and tool:
        record["tool"] = tool_names.get(tool, tool)
    args = decision.get("arguments")
    if isinstance(args, Mapping):
        record["arguments"] = _summarize_arguments(tool if isinstance(tool, str) else None, args)
    return record


def _summarize_arguments(tool: str | None, args: Mapping[str, Any]) -> dict[str, Any]:
    if tool == "file_read":
        keys = _FILE_READ_ARG_KEYS
    elif tool == "file_search":
        keys = _FILE_SEARCH_ARG_KEYS
    elif tool == "file_name_search":
        keys = _FILE_NAME_SEARCH_ARG_KEYS
    elif tool == "show_image":
        keys = _SHOW_IMAGE_ARG_KEYS
    else:
        keys = tuple(str(k) for k in list(args.keys())[:8])
    out: dict[str, Any] = {}
    for key in keys:
        if key in args:
            val = args.get(key)
            if isinstance(val, str) and len(val) > 200:
                out[key] = val[:200] + "…"
            else:
                out[key] = val
    return out


def _summarize_observation(
    observation: Any,
    *,
    tool: str,
    tool_names: Mapping[str, str],
) -> dict[str, Any]:
    summary: dict[str, Any] = {"tool": tool_names.get(tool, tool)}
    if not isinstance(observation, Mapping):
        summary["status"] = "invalid_observation"
        return summary
    status = observation.get("status")
    summary["status"] = str(status) if status is not None else None
    if tool == tool_names.get("file_read"):
        for key in (
            "path",
            "truncated",
            "byte_size",
            "error",
            "source_filename",
            "display_name",
            "source_known",
            "source_ambiguous",
        ):
            if key in observation:
                summary[key] = observation[key]
        content = observation.get("content")
        if isinstance(content, str):
            summary["content_chars"] = len(content)
        return summary
    if tool == tool_names.get("show_image"):
        for key in (
            "path",
            "display_url",
            "mime",
            "byte_size",
            "error",
            "source_filename",
            "display_name",
            "source_known",
            "source_ambiguous",
        ):
            if key in observation:
                summary[key] = observation[key]
        return summary
    if tool in {
        tool_names.get("file_search"),
        tool_names.get("file_name_search"),
    }:
        for key in ("query", "matched_total", "returned_count", "truncated", "error"):
            if key in observation:
                summary[key] = observation[key]
        candidates_out: list[dict[str, Any]] = []
        raw = observation.get("candidates")
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, Mapping):
                    continue
                entry: dict[str, Any] = {"path": item.get("path")}
                if "line" in item:
                    entry["line"] = item.get("line")
                if "name" in item:
                    entry["name"] = item.get("name")
                for key in (
                    "source_filename",
                    "display_name",
                    "source_known",
                    "source_ambiguous",
                ):
                    if key in item:
                        entry[key] = item.get(key)
                candidates_out.append(entry)
        summary["candidates"] = candidates_out
        return summary
    # Unknown tool: keep status only (no raw dump).
    return summary


def _duration_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
