"""A02: AgentRunService with fake adapters (no Flask / no real LLM)."""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.agents.run.contracts import ExecutionContext, RunRequest
from app.domain.agents.run.service import AgentRunService


class FakeMemory:
    def __init__(self) -> None:
        self.last_agent_session_id: str | None = None
        self.persist_calls: list[dict] = []
        self._sid = "sess-1"

    def resolve_session_id(
        self,
        *,
        requested_session_id: str | None,
        new_conversation: bool,
        customer_id: int,
        user_id: int,
        agent_session_id_hint: str | None = None,
    ) -> str:
        if new_conversation:
            self._sid = "sess-new"
        elif requested_session_id:
            self._sid = requested_session_id
        self.last_agent_session_id = self._sid
        return self._sid

    def load_flow_conversation(self, **kwargs: Any) -> list:
        return []

    def list_agent_conversations(self, **kwargs: Any) -> list:
        return []

    def persist_turn(self, **kwargs: Any) -> dict[str, Any]:
        self.persist_calls.append(kwargs)
        return {
            "complete": True,
            "assistant_memory_id": "am-1",
            "user_memory_id": "um-1",
        }


class FakeSubmissions:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.commits = 0
        self.begin_order: list[str] = []

    def get_submission(self, *, customer_id, user_id, submission_id):
        return self.rows.get(f"{customer_id}:{user_id}:{submission_id}")

    def hash_for_reservation(self, **kwargs):
        return "hash-1"

    def try_begin_processing(
        self, *, customer_id, user_id, submission_id, session_id, request_hash
    ):
        key = f"{customer_id}:{user_id}:{submission_id}"
        if key in self.rows:
            return False
        self.rows[key] = {
            "customer_id": customer_id,
            "user_id": user_id,
            "submission_id": submission_id,
            "session_id": session_id,
            "request_hash": request_hash,
            "status": "processing",
        }
        self.begin_order.append("begin")
        return True

    def commit(self):
        self.commits += 1
        self.begin_order.append("commit")

    def hash_matches_stored(self, **kwargs):
        return True

    def is_processing_timed_out(self, row, *, timeout_seconds):
        return False

    def mark_failed(self, **kwargs):
        key = f"{kwargs['customer_id']}:{kwargs['user_id']}:{kwargs['submission_id']}"
        self.rows[key]["status"] = "failed"
        self.rows[key]["error"] = kwargs.get("error")

    def mark_completed(self, **kwargs):
        key = f"{kwargs['customer_id']}:{kwargs['user_id']}:{kwargs['submission_id']}"
        self.rows[key]["status"] = "completed"
        self.rows[key]["result_json"] = dict(kwargs["result_payload"])


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        customer_id=1,
        user_id=2,
        corpus_root="/tmp/corpus",
        permitted_tool_names=frozenset({"file_read"}),
        submission_timeout_seconds=900,
        runner_config={"KNOWLEDGE_FLOW_LLM_MODEL": "test"},
    )


def test_commit_before_runner_and_completed_answer():
    memory = FakeMemory()
    subs = FakeSubmissions()
    calls: list[str] = []

    def runner(text, **kwargs):
        calls.append("runner")
        assert "commit" in subs.begin_order
        assert subs.begin_order.index("commit") < len(subs.begin_order)
        # commit happened before runner body
        assert subs.begin_order == ["begin", "commit"]
        return {
            "status": "ANSWER",
            "decision": {"action": "ANSWER", "answer": "merhaba"},
            "decision_trace": [],
        }

    svc = AgentRunService(memory=memory, submissions=subs, runner=runner)
    out = svc.run(
        _ctx(),
        RunRequest(request_text="selam", submission_id="sub-1"),
    )
    assert out.kind == "completed"
    assert out.payload.get("agent_reply") == "merhaba"
    assert calls == ["runner"]
    assert len(memory.persist_calls) == 1
    assert subs.commits >= 2  # reserve + complete


def test_completed_replay_skips_runner():
    memory = FakeMemory()
    subs = FakeSubmissions()
    key = "1:2:sub-r"
    subs.rows[key] = {
        "session_id": "sess-1",
        "request_hash": "hash-1",
        "status": "completed",
        "result_json": {
            "session_id": "sess-1",
            "assistant_memory_id": "am-x",
            "agent_reply": "eski",
            "flow_status": "ANSWER",
        },
    }
    ran = {"n": 0}

    def runner(*_a, **_k):
        ran["n"] += 1
        raise AssertionError("must not run")

    svc = AgentRunService(memory=memory, submissions=subs, runner=runner)
    out = svc.run(_ctx(), RunRequest(request_text="selam", submission_id="sub-r"))
    assert out.kind == "replayed"
    assert out.payload.get("replayed") is True
    assert out.payload.get("agent_reply") == "eski"
    assert ran["n"] == 0
    assert memory.persist_calls == []


def test_processing_does_not_rerun():
    memory = FakeMemory()
    subs = FakeSubmissions()
    subs.rows["1:2:sub-p"] = {
        "session_id": "sess-1",
        "request_hash": "hash-1",
        "status": "processing",
    }

    def runner(*_a, **_k):
        raise AssertionError("must not run")

    svc = AgentRunService(memory=memory, submissions=subs, runner=runner)
    out = svc.run(_ctx(), RunRequest(request_text="selam", submission_id="sub-p"))
    assert out.kind == "processing"
    assert out.payload.get("replayed") is True


def test_scope_mismatch_different_content():
    memory = FakeMemory()
    subs = FakeSubmissions()
    subs.rows["1:2:sub-s"] = {
        "session_id": "sess-1",
        "request_hash": "other-hash",
        "status": "processing",
    }
    subs.hash_matches_stored = lambda **k: False  # type: ignore[method-assign]

    svc = AgentRunService(
        memory=memory, submissions=subs, runner=lambda *a, **k: {}
    )
    out = svc.run(_ctx(), RunRequest(request_text="farklı", submission_id="sub-s"))
    assert out.kind == "scope_mismatch"
    assert out.error == "submission_scope_mismatch"


def test_session_mismatch():
    memory = FakeMemory()
    subs = FakeSubmissions()
    subs.rows["1:2:sub-m"] = {
        "session_id": "canonical",
        "request_hash": "hash-1",
        "status": "completed",
        "result_json": {},
    }
    svc = AgentRunService(
        memory=memory, submissions=subs, runner=lambda *a, **k: {}
    )
    out = svc.run(
        _ctx(),
        RunRequest(
            request_text="x",
            submission_id="sub-m",
            explicit_session_id="other",
        ),
    )
    assert out.kind == "session_mismatch"
    assert out.error == "submission_session_mismatch"


def test_identity_rejected():
    from app.domain.agents.flow.memory import SessionIdentityError

    memory = FakeMemory()

    def boom(**kwargs):
        raise SessionIdentityError("nope", code="conversation_identity_rejected")

    memory.resolve_session_id = boom  # type: ignore[method-assign]
    # second resolve for fresh session
    calls = {"n": 0}

    def resolve2(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SessionIdentityError("nope", code="conversation_identity_rejected")
        memory.last_agent_session_id = "fresh"
        return "fresh"

    memory.resolve_session_id = resolve2  # type: ignore[method-assign]
    subs = FakeSubmissions()
    svc = AgentRunService(
        memory=memory, submissions=subs, runner=lambda *a, **k: {}
    )
    out = svc.run(
        _ctx(),
        RunRequest(
            request_text="x",
            submission_id="sub-i",
            explicit_session_id="stolen",
        ),
    )
    assert out.kind == "identity_rejected"
    assert out.session_id == "fresh"


def test_memory_read_error():
    from app.domain.agents.flow.memory import MemoryReadError

    memory = FakeMemory()

    def resolve_ok(**kwargs):
        memory.last_agent_session_id = "s1"
        return "s1"

    memory.resolve_session_id = resolve_ok  # type: ignore[method-assign]

    def load_fail(**kwargs):
        raise MemoryReadError("down")

    memory.load_flow_conversation = load_fail  # type: ignore[method-assign]
    svc = AgentRunService(
        memory=memory, submissions=FakeSubmissions(), runner=lambda *a, **k: {}
    )
    out = svc.run(_ctx(), RunRequest(request_text="x", submission_id="sub-mr"))
    assert out.kind == "memory_read_error"


def test_persist_failure_keeps_submission_answer():
    memory = FakeMemory()

    def persist_fail(**kwargs):
        raise RuntimeError("db down")

    memory.persist_turn = persist_fail  # type: ignore[method-assign]
    subs = FakeSubmissions()

    def runner(text, **kwargs):
        return {
            "status": "ANSWER",
            "decision": {"action": "ANSWER", "answer": "korunan"},
        }

    svc = AgentRunService(memory=memory, submissions=subs, runner=runner)
    out = svc.run(_ctx(), RunRequest(request_text="q", submission_id="sub-pf"))
    assert out.kind == "completed"
    assert out.payload.get("agent_reply") == "korunan"
    assert out.payload.get("memory_error")
    key = "1:2:sub-pf"
    assert subs.rows[key]["status"] == "completed"
    assert subs.rows[key]["result_json"]["agent_reply"] == "korunan"


def test_execution_context_rejects_bool_ids():
    with pytest.raises(ValueError):
        ExecutionContext(
            customer_id=True,  # type: ignore[arg-type]
            user_id=1,
            corpus_root="/tmp",
            permitted_tool_names=frozenset(),
            submission_timeout_seconds=10,
        )


def test_runner_config_is_independent_snapshot_and_uses_verified_corpus():
    src = {"AGENT_CORPUS_DIR": "/liar/path", "OTHER": "keep"}
    ctx = ExecutionContext(
        customer_id=1,
        user_id=2,
        corpus_root="/verified/corpus",
        permitted_tool_names=frozenset({"file_read"}),
        submission_timeout_seconds=60,
        runner_config=src,
    )
    src["AGENT_CORPUS_DIR"] = "/mutated"
    src["OTHER"] = "changed"
    assert ctx.runner_config["AGENT_CORPUS_DIR"] == "/verified/corpus"
    assert ctx.runner_config["OTHER"] == "keep"
    assert src["AGENT_CORPUS_DIR"] == "/mutated"


def test_conflicting_config_corpus_overridden_for_runner():
    seen: dict = {}

    def runner(_text, **kwargs):
        seen["config"] = dict(kwargs.get("config") or {})
        return {
            "status": "ANSWER",
            "decision": {"action": "ANSWER", "answer": "ok"},
        }

    ctx = ExecutionContext(
        customer_id=1,
        user_id=2,
        corpus_root="/verified/root",
        permitted_tool_names=frozenset({"file_read"}),
        submission_timeout_seconds=60,
        runner_config={"AGENT_CORPUS_DIR": "/wrong"},
    )
    svc = AgentRunService(
        memory=FakeMemory(), submissions=FakeSubmissions(), runner=runner
    )
    out = svc.run(ctx, RunRequest(request_text="q", submission_id="sub-cfg"))
    assert out.kind == "completed"
    assert seen["config"]["AGENT_CORPUS_DIR"] == "/verified/root"


def test_invalid_submission_id_rejects_without_reservation():
    subs = FakeSubmissions()
    svc = AgentRunService(
        memory=FakeMemory(), submissions=subs, runner=lambda *a, **k: {}
    )
    out = svc.run(_ctx(), RunRequest(request_text="q", submission_id="   "))
    assert out.kind == "invalid_submission_id"
    assert subs.rows == {}
    assert subs.commits == 0

    out2 = svc.run(
        _ctx(), RunRequest(request_text="q", submission_id="bad id with spaces")
    )
    assert out2.kind == "invalid_submission_id"
    assert subs.rows == {}


def test_padded_submission_id_completes_and_replays_normalized():
    memory = FakeMemory()
    subs = FakeSubmissions()
    ran = {"n": 0}

    def runner(text, **kwargs):
        ran["n"] += 1
        return {
            "status": "ANSWER",
            "decision": {"action": "ANSWER", "answer": f"cevap-{text}"},
        }

    svc = AgentRunService(memory=memory, submissions=subs, runner=runner)
    first = svc.run(
        _ctx(),
        RunRequest(request_text="soru", submission_id="  pad-sub-1  "),
    )
    assert first.kind == "completed"
    assert first.submission_id == "pad-sub-1"
    assert "1:2:pad-sub-1" in subs.rows
    assert "  pad-sub-1  " not in str(subs.rows.keys())
    assert ran["n"] == 1

    second = svc.run(
        _ctx(),
        RunRequest(request_text="soru", submission_id="\tpad-sub-1\n"),
    )
    assert second.kind == "replayed"
    assert second.submission_id == "pad-sub-1"
    assert ran["n"] == 1
