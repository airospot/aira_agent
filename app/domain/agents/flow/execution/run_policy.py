"""Immutable RunPolicy + mutable run-scoped budget (A03).

Effective values come from server config / .env — no silent numeric defaults here.
Clock is monotonic and injectable for tests.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

POLICY_ENV_KEYS: tuple[str, ...] = (
    "AGENT_MAX_STEPS",
    "AGENT_RUN_TIMEOUT_SECONDS",
    "AGENT_TOOL_TIMEOUT_SECONDS",
    "AGENT_MAX_OBSERVATION_BYTES",
    "AGENT_MAX_CONTEXT_BYTES",
    "AGENT_MAX_TOOL_RETRIES",
)

# Documented recommended profile (tests/docs); not applied as code fallbacks.
RECOMMENDED_RUN_POLICY: dict[str, int] = {
    "AGENT_MAX_STEPS": 8,
    "AGENT_RUN_TIMEOUT_SECONDS": 180,
    "AGENT_TOOL_TIMEOUT_SECONDS": 15,
    "AGENT_MAX_OBSERVATION_BYTES": 65536,
    "AGENT_MAX_CONTEXT_BYTES": 131072,
    "AGENT_MAX_TOOL_RETRIES": 1,
}

_STOP_DEADLINE = "run_deadline_exceeded"
_STOP_CONTEXT = "context_budget_exceeded"
_STOP_OBSERVATION = "observation_budget_exceeded"
_STOP_STEPS = "step_budget_exceeded"

_REASON_DEADLINE = "Çalışma süresi doldu; tamamlanamadı."
_REASON_CONTEXT = "Bağlam bütçesi aşıldı; zorunlu içerik sığmıyor."
_REASON_OBSERVATION = "Gözlem bütçesi aşıldı; güvenli özet sığmıyor."
_REASON_STEPS = "Adım bütçesi doldu; mevcut gözlemlerle tamamlanamadı."


class RunPolicyError(ValueError):
    """Invalid or missing run budget configuration."""


@dataclass(frozen=True)
class RunPolicy:
    """Server-verified run limits (form/model cannot override)."""

    max_steps: int
    run_timeout_seconds: float
    tool_timeout_seconds: float
    max_observation_bytes: int
    max_context_bytes: int
    max_tool_retries: int

    def as_trace_dict(self) -> dict[str, Any]:
        return {
            "max_steps": self.max_steps,
            "run_timeout_seconds": self.run_timeout_seconds,
            "tool_timeout_seconds": self.tool_timeout_seconds,
            "max_observation_bytes": self.max_observation_bytes,
            "max_context_bytes": self.max_context_bytes,
            "max_tool_retries": self.max_tool_retries,
        }


def _parse_int(raw: Any, *, key: str, min_value: int = 0) -> int:
    if isinstance(raw, bool) or raw is None:
        raise RunPolicyError(f"{key} must be an integer >= {min_value}")
    if isinstance(raw, int):
        value = raw
    else:
        text = str(raw).strip()
        if not text:
            raise RunPolicyError(f"{key} is required")
        try:
            value = int(text)
        except ValueError as exc:
            raise RunPolicyError(f"{key} must be an integer, got {raw!r}") from exc
    if value < min_value:
        raise RunPolicyError(f"{key} must be >= {min_value}, got {value}")
    return value


def _parse_positive_finite_float(raw: Any, *, key: str) -> float:
    if isinstance(raw, bool) or raw is None:
        raise RunPolicyError(f"{key} must be a finite number > 0")
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = str(raw).strip()
        if not text:
            raise RunPolicyError(f"{key} is required")
        try:
            value = float(text)
        except ValueError as exc:
            raise RunPolicyError(f"{key} must be a finite number, got {raw!r}") from exc
    if not math.isfinite(value) or value <= 0:
        raise RunPolicyError(f"{key} must be a finite number > 0, got {raw!r}")
    return value


def parse_run_policy(config: Mapping[str, Any] | None) -> RunPolicy:
    """Validate policy from config mapping. Missing/invalid → RunPolicyError."""
    cfg = config or {}
    missing = [
        key
        for key in POLICY_ENV_KEYS
        if key not in cfg or cfg.get(key) is None or str(cfg.get(key)).strip() == ""
    ]
    if missing:
        raise RunPolicyError(
            "missing run policy config keys: " + ", ".join(missing)
        )
    return RunPolicy(
        max_steps=_parse_int(cfg["AGENT_MAX_STEPS"], key="AGENT_MAX_STEPS", min_value=1),
        run_timeout_seconds=_parse_positive_finite_float(
            cfg["AGENT_RUN_TIMEOUT_SECONDS"], key="AGENT_RUN_TIMEOUT_SECONDS"
        ),
        tool_timeout_seconds=_parse_positive_finite_float(
            cfg["AGENT_TOOL_TIMEOUT_SECONDS"], key="AGENT_TOOL_TIMEOUT_SECONDS"
        ),
        max_observation_bytes=_parse_int(
            cfg["AGENT_MAX_OBSERVATION_BYTES"],
            key="AGENT_MAX_OBSERVATION_BYTES",
            min_value=1,
        ),
        max_context_bytes=_parse_int(
            cfg["AGENT_MAX_CONTEXT_BYTES"],
            key="AGENT_MAX_CONTEXT_BYTES",
            min_value=1,
        ),
        max_tool_retries=_parse_int(
            cfg["AGENT_MAX_TOOL_RETRIES"],
            key="AGENT_MAX_TOOL_RETRIES",
            min_value=0,
        ),
    )


def run_policy_config_overlay(policy: RunPolicy) -> dict[str, Any]:
    """Serialize policy into runner_config keys (single verified snapshot)."""
    return {
        "AGENT_MAX_STEPS": policy.max_steps,
        "AGENT_RUN_TIMEOUT_SECONDS": policy.run_timeout_seconds,
        "AGENT_TOOL_TIMEOUT_SECONDS": policy.tool_timeout_seconds,
        "AGENT_MAX_OBSERVATION_BYTES": policy.max_observation_bytes,
        "AGENT_MAX_CONTEXT_BYTES": policy.max_context_bytes,
        "AGENT_MAX_TOOL_RETRIES": policy.max_tool_retries,
    }


@dataclass
class RunBudget:
    """Mutable per-run counters and deadline (not shared across requests)."""

    policy: RunPolicy
    clock: Callable[[], float] = field(default=time.monotonic)
    started_at: float = field(default_factory=time.monotonic)
    stop_code: str | None = None
    stop_reason: str | None = None
    tool_retry_counts: dict[str, int] = field(default_factory=dict)
    total_tool_retries: int = 0
    last_context_bytes: int | None = None
    last_observation_bytes: int | None = None
    context_truncated: bool = False
    observation_truncated: bool = False
    usage_by_step: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        policy: RunPolicy,
        *,
        clock: Callable[[], float] | None = None,
    ) -> RunBudget:
        clk = clock or time.monotonic
        return cls(policy=policy, clock=clk, started_at=clk())

    def now(self) -> float:
        return float(self.clock())

    def elapsed_seconds(self) -> float:
        return max(0.0, self.now() - self.started_at)

    def remaining_seconds(self) -> float:
        return self.policy.run_timeout_seconds - self.elapsed_seconds()

    def deadline_exceeded(self) -> bool:
        return self.remaining_seconds() <= 0

    def llm_http_timeout_seconds(self, configured_http_timeout: float | int) -> float:
        """Min of remaining run budget and configured HTTP timeout (>0)."""
        configured = float(configured_http_timeout)
        if not math.isfinite(configured) or configured <= 0:
            raise RunPolicyError(
                f"configured HTTP timeout must be finite > 0, got {configured_http_timeout!r}"
            )
        remaining = self.remaining_seconds()
        if remaining <= 0:
            return 0.0
        return min(remaining, configured)

    def tool_slice_seconds(self) -> float:
        remaining = self.remaining_seconds()
        if remaining <= 0:
            return 0.0
        return min(remaining, float(self.policy.tool_timeout_seconds))

    def mark_deadline(self) -> None:
        if self.stop_code is None:
            self.stop_code = _STOP_DEADLINE
            self.stop_reason = _REASON_DEADLINE

    def mark_context_exceeded(self) -> None:
        if self.stop_code is None:
            self.stop_code = _STOP_CONTEXT
            self.stop_reason = _REASON_CONTEXT

    def mark_observation_exceeded(self) -> None:
        if self.stop_code is None:
            self.stop_code = _STOP_OBSERVATION
            self.stop_reason = _REASON_OBSERVATION

    def mark_steps_exceeded(self) -> None:
        if self.stop_code is None:
            self.stop_code = _STOP_STEPS
            self.stop_reason = _REASON_STEPS

    def record_retry(self, fingerprint: str) -> int:
        n = int(self.tool_retry_counts.get(fingerprint, 0)) + 1
        self.tool_retry_counts[fingerprint] = n
        self.total_tool_retries += 1
        return n

    def retries_used(self, fingerprint: str) -> int:
        return int(self.tool_retry_counts.get(fingerprint, 0))

    def as_trace_metadata(self) -> dict[str, Any]:
        return {
            "run_policy": self.policy.as_trace_dict(),
            "stop_code": self.stop_code,
            "elapsed_seconds": round(self.elapsed_seconds(), 3),
            "remaining_seconds": round(max(0.0, self.remaining_seconds()), 3),
            "total_tool_retries": self.total_tool_retries,
            "last_context_bytes": self.last_context_bytes,
            "last_observation_bytes": self.last_observation_bytes,
            "context_truncated": self.context_truncated,
            "observation_truncated": self.observation_truncated,
            "usage_by_step": list(self.usage_by_step),
            "usage_totals": _sum_usage(self.usage_by_step),
        }


def _sum_usage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "known": False,
    }
    inp = out = tot = 0
    saw = False
    for row in rows:
        for key, acc_name in (
            ("input_tokens", "inp"),
            ("output_tokens", "out"),
            ("total_tokens", "tot"),
        ):
            val = row.get(key)
            if isinstance(val, int) and not isinstance(val, bool):
                saw = True
                if acc_name == "inp":
                    inp += val
                elif acc_name == "out":
                    out += val
                else:
                    tot += val
    if not saw:
        return totals
    totals["known"] = True
    totals["input_tokens"] = inp
    totals["output_tokens"] = out
    totals["total_tokens"] = tot if tot else (inp + out)
    return totals


def stop_incomplete_payload(
    *,
    code: str,
    reason: str,
    observations: list[Any],
) -> dict[str, Any]:
    return {
        "status": "STOP_INCOMPLETE",
        "decision": {
            "action": "STOP_INCOMPLETE",
            "reason": reason,
            "code": code,
        },
        "observations": observations,
        "budget_stop_code": code,
    }
