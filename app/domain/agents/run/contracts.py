"""Small run contracts — ExecutionContext, RunRequest, RunOutcome."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


def _positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be a positive int")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"{field_name} must be a positive int")
        return value
    raise ValueError(f"{field_name} must be a positive int")


@dataclass(frozen=True)
class ExecutionContext:
    """Server-verified run scope (never taken from form/model tool args)."""

    customer_id: int
    user_id: int
    corpus_root: str
    permitted_tool_names: frozenset[str]
    submission_timeout_seconds: int
    runner_config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "customer_id", _positive_int(self.customer_id, field_name="customer_id")
        )
        object.__setattr__(
            self, "user_id", _positive_int(self.user_id, field_name="user_id")
        )
        root = str(self.corpus_root or "").strip()
        if not root:
            raise ValueError("corpus_root is required")
        object.__setattr__(self, "corpus_root", str(Path(root)))
        names = frozenset(
            str(n).strip() for n in (self.permitted_tool_names or ()) if str(n).strip()
        )
        object.__setattr__(self, "permitted_tool_names", names)
        try:
            timeout = int(self.submission_timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("submission_timeout_seconds must be int") from exc
        if timeout < 1:
            raise ValueError("submission_timeout_seconds must be >= 1")
        object.__setattr__(self, "submission_timeout_seconds", timeout)


@dataclass(frozen=True)
class RunRequest:
    """Client intent for one propose (session hint is a candidate only)."""

    request_text: str
    submission_id: str
    explicit_session_id: str | None = None
    new_conversation: bool = False
    agent_session_id_hint: str | None = None


@dataclass(frozen=True)
class RunOutcome:
    """HTTP-free result for the web adapter to map to 303 / 400 / cookie pointer."""

    kind: str
    submission_id: str
    session_id: str | None = None
    turn_id: int | str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    agent_session_id: str | None = None
    http_status: int | None = None
    error: str | None = None
    message: str | None = None
