"""Knowledge Agent Flow runner — file tools + show_image."""

from __future__ import annotations

import json
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
from app.domain.agents.flow.execution.run_agent_loop import (
    run_agent_loop,
)
from app.domain.agents.flow.tools import file_name_search as file_name_search_execute
from app.domain.agents.flow.tools import file_read as file_read_execute
from app.domain.agents.flow.tools import file_search as file_search_execute
from app.domain.agents.flow.tools import show_image as show_image_execute

_FILE_READ_TOOL_JSON = Path(file_read_execute.__file__).resolve().parent / "tool.json"
_FILE_SEARCH_TOOL_JSON = Path(file_search_execute.__file__).resolve().parent / "tool.json"
_FILE_NAME_SEARCH_TOOL_JSON = (
    Path(file_name_search_execute.__file__).resolve().parent / "tool.json"
)
_SHOW_IMAGE_TOOL_JSON = Path(show_image_execute.__file__).resolve().parent / "tool.json"

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
) -> dict[str, Any]:
    """Run one agent turn with corpus file tools only."""
    del dataset_dir, caller_context  # legacy kwargs ignored
    client = create_flow_llm_client(config)
    file_read_tool = json.loads(_FILE_READ_TOOL_JSON.read_text(encoding="utf-8"))
    file_search_tool = json.loads(_FILE_SEARCH_TOOL_JSON.read_text(encoding="utf-8"))
    file_name_search_tool = json.loads(
        _FILE_NAME_SEARCH_TOOL_JSON.read_text(encoding="utf-8")
    )
    show_image_tool = json.loads(_SHOW_IMAGE_TOOL_JSON.read_text(encoding="utf-8"))
    permitted_tools = [
        file_name_search_tool,
        file_search_tool,
        file_read_tool,
        show_image_tool,
    ]
    file_read_name = file_read_tool["name"]
    file_search_name = file_search_tool["name"]
    file_name_search_name = file_name_search_tool["name"]
    show_image_name = show_image_tool["name"]
    permitted_tool_names = {
        file_read_name,
        file_search_name,
        file_name_search_name,
        show_image_name,
    }
    tool_names = {
        "file_read": file_read_name,
        "file_search": file_search_name,
        "file_name_search": file_name_search_name,
        "show_image": show_image_name,
    }

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
            )
        except Exception as exc:  # noqa: BLE001
            _emit("error", status=type(exc).__name__, duration_ms=_duration_ms(started))
            raise
        decide_ms = _duration_ms(started)
        _emit("decide_finished", duration_ms=decide_ms)
        decision_trace.append(
            _trace_decision_record(
                step=step,
                decision=decision if isinstance(decision, Mapping) else None,
                decide_duration_ms=decide_ms,
                observations_available=obs_count,
                tool_names=tool_names,
                decision_mode="terminal_only" if terminal_only else "normal",
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
        if tool not in permitted_tool_names:
            _emit("error", status="tool_not_permitted")
            raise ValueError("tool_not_permitted")
        _emit("tool_started", action="CALL_TOOL", tool=tool)
        started = time.perf_counter()
        try:
            if tool == file_read_name:
                observation = file_read_execute.execute_file_read(
                    decision.get("arguments"),
                    config=config,
                )
            elif tool == file_search_name:
                observation = file_search_execute.execute_file_search(
                    decision.get("arguments"),
                    config=config,
                )
            elif tool == file_name_search_name:
                observation = file_name_search_execute.execute_file_name_search(
                    decision.get("arguments"),
                    config=config,
                )
            elif tool == show_image_name:
                observation = show_image_execute.execute_show_image(
                    decision.get("arguments"),
                    config=config,
                )
            else:
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
                tool=tool if isinstance(tool, str) else None,
                tool_names=tool_names,
            )
        return observation

    result = run_agent_loop(
        request_text,
        conversation,
        _decide,
        _validate,
        execute_tool=_execute_tool,
        max_steps=8,
    )
    status = result.get("status")
    action = None
    decision = result.get("decision")
    if isinstance(decision, dict) and decision.get("action") is not None:
        action = str(decision.get("action"))
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
    return out


def _trace_decision_record(
    *,
    step: int,
    decision: Mapping[str, Any] | None,
    decide_duration_ms: int,
    observations_available: int,
    tool_names: Mapping[str, str],
    decision_mode: str = "normal",
) -> dict[str, Any]:
    action = None
    tool = None
    arguments = None
    if decision is not None:
        if decision.get("action") is not None:
            action = str(decision.get("action"))
        if decision.get("tool") is not None:
            tool = str(decision.get("tool"))
        if action == "CALL_TOOL":
            arguments = _safe_tool_arguments(
                decision.get("arguments"),
                tool=tool,
                tool_names=tool_names,
            )
    return {
        "step": step,
        "action": action,
        "tool": tool,
        "arguments": arguments,
        "decide_duration_ms": decide_duration_ms,
        "observations_available": observations_available,
        "decision_mode": decision_mode,
    }


def _safe_tool_arguments(
    arguments: Any,
    *,
    tool: str | None,
    tool_names: Mapping[str, str],
) -> dict[str, Any] | None:
    if not isinstance(arguments, Mapping):
        return None
    if tool == tool_names.get("file_read"):
        keys = _FILE_READ_ARG_KEYS
    elif tool == tool_names.get("file_search"):
        keys = _FILE_SEARCH_ARG_KEYS
    elif tool == tool_names.get("file_name_search"):
        keys = _FILE_NAME_SEARCH_ARG_KEYS
    elif tool == tool_names.get("show_image"):
        keys = _SHOW_IMAGE_ARG_KEYS
    else:
        return None
    return {key: arguments[key] for key in keys if key in arguments}


def _summarize_observation(
    observation: Any,
    *,
    tool: str | None,
    tool_names: Mapping[str, str],
) -> dict[str, Any]:
    if not isinstance(observation, Mapping):
        return {"status": None}
    status = observation.get("status")
    summary: dict[str, Any] = {
        "status": str(status) if status is not None else None,
    }
    if tool == tool_names.get("file_read"):
        for key in ("path", "truncated", "byte_size", "error"):
            if key in observation:
                summary[key] = observation[key]
        content = observation.get("content")
        if isinstance(content, str):
            summary["content_chars"] = len(content)
        return summary
    if tool == tool_names.get("show_image"):
        for key in ("path", "display_url", "mime", "byte_size", "error"):
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
                candidates_out.append(entry)
        summary["candidates"] = candidates_out
        return summary
    return summary


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))
