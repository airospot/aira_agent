"""A04: document-review application skill loader, scope, hash, context."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.db.agents.repositories import submission_repository as submissions
from app.domain.agents.flow.execution.decision.context_builder import (
    ContextBuildError,
    build_model_decision_context,
)
from app.domain.agents.flow.execution.run_knowledge_agent import run_knowledge_agent
from app.domain.agents.flow.tooling.native_bootstrap import NATIVE_TOOL_NAMES
from app.domain.agents.run.service import pack_decision_trace
from app.domain.agents.skills.catalog import (
    DOCUMENT_REVIEW_SKILL_ID,
    STANDARD_SKILL_ID,
    normalize_skill_id,
)
from app.domain.agents.skills.errors import SkillError
from app.domain.agents.skills.loader import (
    bind_skill_tools,
    load_skill_snapshot,
    package_skills_root,
)
from tests.a03_policy_helpers import recommended_policy_config, recommended_run_policy


@pytest.fixture
def skill_cfg() -> dict:
    return recommended_policy_config()


def test_package_skills_root_is_repo_not_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    root = package_skills_root()
    assert root.name == "agent_skills"
    assert (root / "document-review" / "skill.json").is_file()


def test_normalize_unknown_skill_id() -> None:
    with pytest.raises(SkillError) as exc:
        normalize_skill_id("evil-skill")
    assert exc.value.code == "unknown_skill_id"
    assert normalize_skill_id("") == STANDARD_SKILL_ID
    assert normalize_skill_id(None) == STANDARD_SKILL_ID


def test_load_valid_document_review(skill_cfg: dict) -> None:
    snap = load_skill_snapshot(DOCUMENT_REVIEW_SKILL_ID, config=skill_cfg)
    assert snap is not None
    assert snap.skill_id == "document-review"
    assert snap.version == "1.0.0"
    assert "file_name_search" in snap.required_tools
    assert "file_read" in snap.required_tools
    assert snap.allowed_tools <= frozenset(NATIVE_TOOL_NAMES)
    assert snap.content_digest
    assert "Belge inceleme" in snap.instructions or "belge" in snap.instructions.lower()
    assert any(r.name == "checklist" for r in snap.resources)
    # Snapshot immutable-ish: public meta has no full body.
    meta = snap.public_meta()
    assert set(meta) == {"id", "version", "digest"}
    assert "prompt_block" not in meta


def test_standard_returns_none(skill_cfg: dict) -> None:
    assert load_skill_snapshot(STANDARD_SKILL_ID, config=skill_cfg) is None


def test_missing_skill_max_bytes_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_SKILL_MAX_BYTES", raising=False)
    with pytest.raises(SkillError) as exc:
        load_skill_snapshot(DOCUMENT_REVIEW_SKILL_ID, config={})
    assert exc.value.code == "skill_config_invalid"


def test_corrupt_json_rejected(tmp_path: Path, skill_cfg: dict) -> None:
    root = tmp_path / "agent_skills"
    skill = root / "document-review"
    skill.mkdir(parents=True)
    (skill / "skill.json").write_text("{not-json", encoding="utf-8")
    (skill / "SKILL.md").write_text("x", encoding="utf-8")
    with pytest.raises(SkillError) as exc:
        load_skill_snapshot("document-review", config=skill_cfg, skills_root=root)
    assert exc.value.code == "skill_invalid"


def test_extra_metadata_field_rejected(tmp_path: Path, skill_cfg: dict) -> None:
    root = tmp_path / "agent_skills"
    skill = root / "document-review"
    (skill / "resources").mkdir(parents=True)
    meta = {
        "id": "document-review",
        "version": "1.0.0",
        "description": "x",
        "allowed_tools": ["file_read", "file_name_search"],
        "required_tools": ["file_read", "file_name_search"],
        "resources": [],
        "shell_command": "rm -rf /",
    }
    (skill / "skill.json").write_text(json.dumps(meta), encoding="utf-8")
    (skill / "SKILL.md").write_text("instr", encoding="utf-8")
    with pytest.raises(SkillError) as exc:
        load_skill_snapshot("document-review", config=skill_cfg, skills_root=root)
    assert exc.value.code == "skill_invalid"


def test_traversal_and_absolute_resource_rejected(tmp_path: Path, skill_cfg: dict) -> None:
    root = tmp_path / "agent_skills"
    skill = root / "document-review"
    skill.mkdir(parents=True)
    base = {
        "id": "document-review",
        "version": "1.0.0",
        "description": "x",
        "allowed_tools": ["file_read", "file_name_search"],
        "required_tools": ["file_read", "file_name_search"],
    }
    (skill / "SKILL.md").write_text("instr", encoding="utf-8")
    for bad_path in ("../other/SKILL.md", "/etc/passwd"):
        meta = {**base, "resources": [{"name": "x", "path": bad_path}]}
        (skill / "skill.json").write_text(json.dumps(meta), encoding="utf-8")
        with pytest.raises(SkillError) as exc:
            load_skill_snapshot("document-review", config=skill_cfg, skills_root=root)
        assert exc.value.code in {"skill_path_escape", "skill_resource_missing"}


def test_symlink_resource_rejected(tmp_path: Path, skill_cfg: dict) -> None:
    root = tmp_path / "agent_skills"
    skill = root / "document-review"
    (skill / "resources").mkdir(parents=True)
    outside = tmp_path / "secret.md"
    outside.write_text("leak", encoding="utf-8")
    target = skill / "resources" / "checklist.md"
    target.symlink_to(outside)
    meta = {
        "id": "document-review",
        "version": "1.0.0",
        "description": "x",
        "allowed_tools": ["file_read", "file_name_search"],
        "required_tools": ["file_read", "file_name_search"],
        "resources": [{"name": "checklist", "path": "resources/checklist.md"}],
    }
    (skill / "skill.json").write_text(json.dumps(meta), encoding="utf-8")
    (skill / "SKILL.md").write_text("instr", encoding="utf-8")
    with pytest.raises(SkillError) as exc:
        load_skill_snapshot("document-review", config=skill_cfg, skills_root=root)
    assert exc.value.code == "skill_path_escape"


def test_size_limit(tmp_path: Path) -> None:
    root = tmp_path / "agent_skills"
    skill = root / "document-review"
    skill.mkdir(parents=True)
    meta = {
        "id": "document-review",
        "version": "1.0.0",
        "description": "x",
        "allowed_tools": ["file_read", "file_name_search"],
        "required_tools": ["file_read", "file_name_search"],
        "resources": [],
    }
    (skill / "skill.json").write_text(json.dumps(meta), encoding="utf-8")
    (skill / "SKILL.md").write_text("x" * 200, encoding="utf-8")
    with pytest.raises(SkillError) as exc:
        load_skill_snapshot(
            "document-review",
            config={"AGENT_SKILL_MAX_BYTES": 50},
            skills_root=root,
        )
    assert exc.value.code == "skill_too_large"


def test_bind_tools_intersection_and_not_ready() -> None:
    from app.domain.agents.skills.snapshot import SkillSnapshot

    snap = SkillSnapshot(
        skill_id="document-review",
        version="1.0.0",
        description="d",
        instructions="i",
        allowed_tools=frozenset({"file_read", "file_name_search", "file_search"}),
        required_tools=frozenset({"file_read", "file_name_search"}),
        resources=(),
        content_digest="abc",
    )
    effective = bind_skill_tools(
        snap,
        server_permitted=frozenset({"file_read", "file_name_search", "show_image"}),
        registry_names=frozenset(NATIVE_TOOL_NAMES),
    )
    assert effective == frozenset({"file_read", "file_name_search"})
    with pytest.raises(SkillError) as exc:
        bind_skill_tools(
            snap,
            server_permitted=frozenset({"file_search"}),
            registry_names=frozenset(NATIVE_TOOL_NAMES),
        )
    assert exc.value.code == "skill_not_ready"


def test_digest_changes_when_instructions_change(
    tmp_path: Path, skill_cfg: dict
) -> None:
    src = package_skills_root() / "document-review"
    dst = tmp_path / "agent_skills" / "document-review"
    shutil.copytree(src, dst)
    a = load_skill_snapshot("document-review", config=skill_cfg, skills_root=tmp_path / "agent_skills")
    assert a is not None
    (dst / "SKILL.md").write_text(a.instructions + "\n# mutated\n", encoding="utf-8")
    b = load_skill_snapshot("document-review", config=skill_cfg, skills_root=tmp_path / "agent_skills")
    assert b is not None
    assert a.version == b.version
    assert a.content_digest != b.content_digest


def test_hash_standard_unchanged_skill_omitted() -> None:
    base = submissions.hash_request(
        request_text="q", session_id="s1", new_conversation=False
    )
    same = submissions.hash_request(
        request_text="q",
        session_id="s1",
        new_conversation=False,
        skill_id="standard",
    )
    assert base == same
    skilled = submissions.hash_request(
        request_text="q",
        session_id="s1",
        new_conversation=False,
        skill_id="document-review",
        skill_version="1.0.0",
        skill_digest="deadbeef",
    )
    assert skilled != base
    other_digest = submissions.hash_request(
        request_text="q",
        session_id="s1",
        new_conversation=False,
        skill_id="document-review",
        skill_version="1.0.0",
        skill_digest="cafebabe",
    )
    assert other_digest != skilled


def test_context_builder_includes_skill_and_counts_bytes(skill_cfg: dict) -> None:
    snap = load_skill_snapshot(DOCUMENT_REVIEW_SKILL_ID, config=skill_cfg)
    assert snap is not None
    from app.domain.agents.flow.execution.run_policy import RunBudget

    budget = RunBudget.start(recommended_run_policy())
    built = build_model_decision_context(
        "uat-guide.md incele",
        {"active_conversation": {"turns": [], "turn_count": 0, "is_empty": True}},
        [],
        budget=budget,
        permitted_tools=[{"name": "file_read"}],
        skill_snapshot=snap,
    )
    assert "Active application skill" in built["system_prompt"]
    assert "document-review" in built["system_prompt"]
    assert snap.instructions.strip()[:40] in built["system_prompt"]
    # User document text is request_text — separate from skill layer.
    assert built["user_payload"]["request_text"] == "uat-guide.md incele"


def test_oversized_skill_fails_before_llm(skill_cfg: dict) -> None:
    snap = load_skill_snapshot(DOCUMENT_REVIEW_SKILL_ID, config=skill_cfg)
    assert snap is not None
    from app.domain.agents.flow.execution.run_policy import RunBudget, parse_run_policy
    from app.domain.agents.skills.snapshot import SkillSnapshot

    tiny = parse_run_policy(
        recommended_policy_config(AGENT_MAX_CONTEXT_BYTES=800)
    )
    budget = RunBudget.start(tiny)
    huge = SkillSnapshot(
        skill_id=snap.skill_id,
        version=snap.version,
        description=snap.description,
        instructions="X" * 5000,
        allowed_tools=snap.allowed_tools,
        required_tools=snap.required_tools,
        resources=snap.resources,
        content_digest=snap.content_digest,
    )
    client = MagicMock()
    with pytest.raises(ContextBuildError) as exc:
        from app.domain.agents.flow.execution.decision.request_model_decision import (
            request_model_decision,
        )

        request_model_decision(
            "hi",
            {},
            [],
            client,
            permitted_tools=[],
            budget=budget,
            skill_snapshot=huge,
        )
    assert exc.value.code == "context_budget_exceeded"
    client.complete_json.assert_not_called()


def test_pack_decision_trace_includes_skill_meta_only() -> None:
    packed = pack_decision_trace(
        {
            "decision_trace": [{"step": 1}],
            "decision_trace_final_status": "ANSWER",
            "decision_trace_final_action": "ANSWER",
            "skill": {
                "id": "document-review",
                "version": "1.0.0",
                "digest": "abc",
                "effective_tools": ["file_read"],
                "instructions": "SECRET FULL TEXT",
            },
        }
    )
    assert packed is not None
    assert packed["skill"]["id"] == "document-review"
    assert packed["skill"]["effective_tools"] == ["file_read"]
    assert "instructions" not in packed["skill"]
    assert "SECRET" not in json.dumps(packed)


def test_runner_catalog_matches_effective_tools(
    tmp_path: Path, skill_cfg: dict
) -> None:
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "a.md").write_text("hello", encoding="utf-8")
    snap = load_skill_snapshot(DOCUMENT_REVIEW_SKILL_ID, config=skill_cfg)
    assert snap is not None
    effective = bind_skill_tools(
        snap,
        server_permitted=frozenset(NATIVE_TOOL_NAMES),
        registry_names=frozenset(NATIVE_TOOL_NAMES),
    )

    class Client:
        timeout_seconds = 30
        last_meta = {}

        def complete_json(self, system_prompt, user_payload, **kwargs):
            tools = user_payload.get("permitted_tools") or []
            names = {t.get("name") for t in tools if isinstance(t, dict)}
            assert names == set(effective)
            assert "Active application skill" in system_prompt
            return {"action": "ANSWER", "answer": "ok"}

    with patch(
        "app.domain.agents.flow.execution.run_knowledge_agent.create_flow_llm_client",
        return_value=Client(),
    ):
        result = run_knowledge_agent(
            "özetle",
            conversation={},
            config=recommended_policy_config(AGENT_CORPUS_DIR=str(corpus)),
            permitted_tool_names=effective,
            skill_snapshot=snap,
        )
    assert result["status"] == "ANSWER"
    assert result["skill"]["id"] == "document-review"
    assert set(result["skill"]["effective_tools"]) == set(effective)
