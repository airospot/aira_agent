"""Optional cooperative execution control for native/future tool handlers (A03).

Native sync tools cannot be forcibly killed. Callers pass a deadline/slice;
handlers check cooperatively between file/line iterations. OS-blocked read/stat
is not claimed to be preempted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


class ToolDeadlineExceeded(RuntimeError):
    """Cooperative tool deadline fired before/during iteration."""

    def __init__(self, message: str = "tool_deadline_exceeded") -> None:
        super().__init__(message)
        self.code = "tool_deadline_exceeded"


@dataclass(frozen=True)
class ExecutionControl:
    """Deadline / remaining slice for one tool invocation."""

    deadline_monotonic: float | None = None
    remaining_seconds: float | None = None
    tool_timeout_seconds: float | None = None
    clock: Callable[[], float] | None = None
    check_every_n: int = 32

    def expired(self) -> bool:
        if self.deadline_monotonic is None or self.clock is None:
            return False
        return float(self.clock()) >= float(self.deadline_monotonic)

    def checkpoint(self) -> None:
        if self.expired():
            raise ToolDeadlineExceeded()


def execution_control_from_mapping(raw: Mapping[str, Any] | None) -> ExecutionControl | None:
    if not isinstance(raw, Mapping) or not raw:
        return None
    return ExecutionControl(
        deadline_monotonic=(
            float(raw["deadline_monotonic"])
            if raw.get("deadline_monotonic") is not None
            else None
        ),
        remaining_seconds=(
            float(raw["remaining_seconds"])
            if raw.get("remaining_seconds") is not None
            else None
        ),
        tool_timeout_seconds=(
            float(raw["tool_timeout_seconds"])
            if raw.get("tool_timeout_seconds") is not None
            else None
        ),
        clock=raw.get("clock") if callable(raw.get("clock")) else None,
        check_every_n=int(raw.get("check_every_n") or 32),
    )
