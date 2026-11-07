"""A04: document-review ANSWER requires file_read content evidence."""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.agents.flow.execution.run_agent_loop import run_agent_loop
from app.domain.agents.flow.execution.run_policy import RunBudget
from app.domain.agents.skills.completion import (
    content_answer_allowed,
    is_successful_content_file_read,
    is_zero_hit_name_search,
)
from app.domain.agents.skills.snapshot import SkillSnapshot
from tests.a03_policy_helpers import recommended_run_policy


def _review_skill() -> SkillSnapshot:
    return SkillSnapshot(
        skill_id="document-review",
        version="1.0.0",
        description="d",
        instructions="read then review",
        allowed_tools=frozenset(
            {"file_name_search", "file_read", "file_search", "show_image"}
        ),
        required_tools=frozenset({"file_name_search", "file_read"}),
        resources=(),
        content_digest="abc",
        content_answer_requires_file_read=True,
    )


def test_meta_json_and_empty_content_not_evidence() -> None:
    assert not is_successful_content_file_read(
        {
            "tool": "file_read",
            "status": "ok",
            "path": "extracted_data/x/meta.json",
            "content": '{"source_filename":"x.docx"}',
        }
    )
    assert not is_successful_content_file_read(
        {"tool": "file_read", "status": "ok", "path": "a.md", "content": "  "}
    )
    assert is_successful_content_file_read(
        {
            "tool": "file_read",
            "status": "ok",
            "path": "extracted_data/x/content.md",
            "content": "Somut metin ALTAR-99",
        }
    )


def test_search_hits_without_read_disallow_answer() -> None:
    hits = [
        {
            "tool": "file_name_search",
            "status": "ok",
            "matched_total": 1,
            "candidates": [{"path": "x.md", "name": "06_negative_missing_fact.docx"}],
        }
    ]
    ok, code = content_answer_allowed(hits)
    assert not ok
    assert code == "skill_evidence_missing"


def test_zero_hit_allows_honest_answer() -> None:
    miss = [
        {
            "tool": "file_name_search",
            "status": "ok",
            "matched_total": 0,
            "candidates": [],
        }
    ]
    assert is_zero_hit_name_search(miss[0])
    assert content_answer_allowed(miss)[0]


def test_loop_rejects_search_only_review_answer() -> None:
    script: list[dict[str, Any]] = [
        {
            "action": "CALL_TOOL",
            "tool": "file_name_search",
            "arguments": {"query": "06_negative_missing_fact"},
        },
        {
            "action": "ANSWER",
            "answer": "Dosya eksik teslimat tarihi içeriyor (uydurma).",
        },
    ]

    def decide(_r, _c, _o, decision_constraints=None):
        return script.pop(0)

    def validate(decision, terminal_only=False):
        return decision["action"]

    def execute(decision):
        return {
            "status": "ok",
            "matched_total": 1,
            "candidates": [
                {
                    "path": "extracted_data/06_negative_missing_fact/content.md",
                    "name": "06_negative_missing_fact.docx",
                }
            ],
            "query": "06_negative_missing_fact",
        }

    budget = RunBudget.start(recommended_run_policy(AGENT_MAX_STEPS=2))
    out = run_agent_loop(
        "incele",
        {},
        decide,
        validate,
        execute,
        budget=budget,
        skill_snapshot=_review_skill(),
    )
    assert out["status"] == "STOP_INCOMPLETE"
    assert out["decision"].get("code") == "skill_evidence_missing"
    assert "file_read" in out["decision"]["reason"].lower() or "içerik" in out[
        "decision"
    ]["reason"].lower()


def test_loop_accepts_answer_after_file_read() -> None:
    script: list[dict[str, Any]] = [
        {
            "action": "CALL_TOOL",
            "tool": "file_name_search",
            "arguments": {"query": "06_negative"},
        },
        {
            "action": "CALL_TOOL",
            "tool": "file_read",
            "arguments": {"path": "extracted_data/06_negative/content.md"},
        },
        {
            "action": "ANSWER",
            "answer": "Belgede somut kod ALTAR-99 geçiyor; teslimat tarihi yok.",
        },
    ]

    def decide(_r, _c, _o, decision_constraints=None):
        return script.pop(0)

    def validate(decision, terminal_only=False):
        return decision["action"]

    def execute(decision):
        tool = decision["tool"]
        if tool == "file_name_search":
            return {
                "status": "ok",
                "matched_total": 1,
                "candidates": [
                    {"path": "extracted_data/06_negative/content.md", "name": "06.docx"}
                ],
            }
        return {
            "status": "ok",
            "path": "extracted_data/06_negative/content.md",
            "content": "Kod: ALTAR-99. Teslimat tarihi belirtilmemiş.",
            "source_filename": "06_negative_missing_fact.docx",
        }

    budget = RunBudget.start(recommended_run_policy(AGENT_MAX_STEPS=4))
    out = run_agent_loop(
        "incele",
        {},
        decide,
        validate,
        execute,
        budget=budget,
        skill_snapshot=_review_skill(),
    )
    assert out["status"] == "ANSWER"
    assert "ALTAR-99" in out["decision"]["answer"]


def test_loop_correction_then_read_within_budget() -> None:
    """Search-only ANSWER gets feedback; later read+ANSWER accepted."""
    calls = {"n": 0}

    def decide(_r, _c, observations, decision_constraints=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "action": "CALL_TOOL",
                "tool": "file_name_search",
                "arguments": {"query": "x"},
            }
        if calls["n"] == 2:
            return {"action": "ANSWER", "answer": "uydurma içerik analizi"}
        if calls["n"] == 3:
            assert any(
                isinstance(o, dict) and o.get("status") == "skill_requirement"
                for o in observations
            )
            return {
                "action": "CALL_TOOL",
                "tool": "file_read",
                "arguments": {"path": "a.md"},
            }
        return {"action": "ANSWER", "answer": "Okunan: GERCEK-42"}

    def validate(decision, terminal_only=False):
        return decision["action"]

    def execute(decision):
        if decision["tool"] == "file_name_search":
            return {
                "status": "ok",
                "matched_total": 1,
                "candidates": [{"path": "a.md", "name": "a.md"}],
            }
        return {"status": "ok", "path": "a.md", "content": "GERCEK-42 satırı"}

    budget = RunBudget.start(recommended_run_policy(AGENT_MAX_STEPS=5))
    out = run_agent_loop(
        "incele",
        {},
        decide,
        validate,
        execute,
        budget=budget,
        skill_snapshot=_review_skill(),
    )
    assert out["status"] == "ANSWER"
    assert "GERCEK-42" in out["decision"]["answer"]


def test_standard_mode_unaffected_by_gate() -> None:
    def decide(_r, _c, _o, decision_constraints=None):
        return {"action": "ANSWER", "answer": "standart kısa cevap"}

    def validate(decision, terminal_only=False):
        return decision["action"]

    out = run_agent_loop(
        "merhaba",
        {},
        decide,
        validate,
        None,
        budget=RunBudget.start(recommended_run_policy(AGENT_MAX_STEPS=2)),
        skill_snapshot=None,
    )
    assert out["status"] == "ANSWER"
