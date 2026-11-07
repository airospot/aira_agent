"""Small run contracts — ExecutionContext, RunRequest, RunOutcome."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app.domain.agents.flow.execution.run_policy import (
    RunPolicy,
    parse_run_policy,
    run_policy_config_overlay,
)
from app.domain.agents.skills.snapshot import SkillSnapshot


# Matches DB VARCHAR(64): first char + up to 63 more → max 64 total.
_SUBMISSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def _positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be a positive int")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"{field_name} must be a positive int")
        return value
    raise ValueError(f"{field_name} must be a positive int")


def normalize_submission_id(raw: Any) -> str:
    """Single validation point for submission ids (trim; reject empty/invalid)."""
    text = str(raw if raw is not None else "").strip()
    if not text:
        raise ValueError("submission_id is required")
    if any(ch.isspace() for ch in text):
        raise ValueError("submission_id is invalid")
    if not _SUBMISSION_ID_RE.fullmatch(text):
        raise ValueError("submission_id is invalid")
    return text


def _snapshot_runner_config(
    raw: Mapping[str, Any] | None, *, corpus_root: str
) -> dict[str, Any]:
    """Independent config copy; AGENT_CORPUS_DIR always matches verified corpus_root."""
    if raw is None:
        snap: dict[str, Any] = {}
    else:
        try:
            snap = dict(raw)
        except Exception:  # noqa: BLE001
            snap = {str(k): raw[k] for k in raw}  # type: ignore[index]
    snap["AGENT_CORPUS_DIR"] = corpus_root
    return snap


@dataclass(frozen=True)
class ExecutionContext:
    """Server-verified run scope (never taken from form/model tool args)."""

    customer_id: int
    user_id: int
    corpus_root: str
    permitted_tool_names: frozenset[str]
    submission_timeout_seconds: int
    runner_config: Mapping[str, Any] = field(default_factory=dict)
    run_policy: RunPolicy | None = None
    skill_snapshot: SkillSnapshot | None = None

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
        root = str(Path(root))
        object.__setattr__(self, "corpus_root", root)
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
        snap = _snapshot_runner_config(self.runner_config, corpus_root=root)
        policy = self.run_policy
        if policy is None:
            policy = parse_run_policy(snap)
        else:
            if not isinstance(policy, RunPolicy):
                raise ValueError("run_policy must be RunPolicy")
        snap.update(run_policy_config_overlay(policy))
        object.__setattr__(self, "run_policy", policy)
        object.__setattr__(self, "runner_config", snap)


@dataclass(frozen=True)
class RunRequest:
    """Client intent for one propose (session hint is a candidate only)."""

    request_text: str
    submission_id: str
    explicit_session_id: str | None = None
    new_conversation: bool = False
    agent_session_id_hint: str | None = None
    # Allowlisted skill id only; version/tools/body never from client.
    skill_id: str | None = None


@dataclass(frozen=True)
class RunOutcome:
    """HTTP-free result for the web adapter to map to 303 / 400 / cookie pointer."""

    kind: str
    submission_id: str
    session_id: str | None = None
    turn_id: int | str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    agent_session_id: str | None = None
    error: str | None = None
    message: str | None = None
