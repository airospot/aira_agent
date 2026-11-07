"""Explicit A03 RunPolicy fixtures — not production code defaults."""

from __future__ import annotations

from typing import Any

from app.domain.agents.flow.execution.run_policy import (
    RECOMMENDED_RUN_POLICY,
    RunPolicy,
    parse_run_policy,
)


def recommended_policy_config(**overrides: Any) -> dict[str, Any]:
    """Copy documented recommended env values for unit tests."""
    cfg = dict(RECOMMENDED_RUN_POLICY)
    cfg.update(overrides)
    return cfg


def recommended_run_policy(**overrides: Any) -> RunPolicy:
    return parse_run_policy(recommended_policy_config(**overrides))


def corpus_config(corpus_dir: str, **overrides: Any) -> dict[str, Any]:
    cfg = recommended_policy_config(**overrides)
    cfg["AGENT_CORPUS_DIR"] = corpus_dir
    return cfg
