"""A00: propose idempotency paths + persist-failure keeps reply (no real LLM)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse, urlunparse

import pytest

psycopg2 = pytest.importorskip("psycopg2")


def _resolve_test_url() -> str | None:
    explicit = (os.environ.get("A00_TEST_DATABASE_URL") or "").strip()
    if explicit:
        return explicit
    base = (os.environ.get("DATABASE_URL") or "").strip()
    if not base:
        try:
            from dotenv import load_dotenv

            load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
        except Exception:  # noqa: BLE001
            pass
        base = (os.environ.get("DATABASE_URL") or "").strip()
    if not base:
        return None
    return base.rsplit("/", 1)[0] + "/NATIVE_FLOW_A00_TEST"


def _can_connect(url: str) -> bool:
    try:
        from migrations._db import normalize_psycopg2_dsn

        conn = psycopg2.connect(normalize_psycopg2_dsn(url))
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch):
    url = _resolve_test_url()
    if not url or not _can_connect(url):
        pytest.skip("Gerçek PostgreSQL test DB erişilemedi (propose idempotency).")

    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SECRET_KEY", "a00-propose-idempotency-secret-key")
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "11")
    monkeypatch.setenv("AUTH_BYPASS_CUSTOMER_ID", "22")
    monkeypatch.setenv("AGENT_SUBMISSION_TIMEOUT_SECONDS", "900")

    from migrations.create_agent_submissions_table import create_agent_submissions_table
    from migrations.create_conversation_memory_table import (
        create_conversation_memory_table,
    )
    from migrations.add_embedding_to_conversation_memory import add_embedding_column

    create_agent_submissions_table()
    try:
        create_conversation_memory_table()
    except Exception:  # noqa: BLE001
        # table may already exist from prior runs
        pass
    try:
        add_embedding_column()
    except Exception:  # noqa: BLE001
        pass

    from tests.conftest import load_app_py

    application = load_app_py().create_app()
    application.config["TESTING"] = True
    client = application.test_client()
    return application, client, url


def _agent_answer(text: str = "Yanıt A00") -> dict:
    return {"status": "ANSWER", "decision": {"answer": text}, "stage": "decision"}


def test_completed_replay_same_hash_no_second_llm(app_client) -> None:
    application, client, _url = app_client
    sub_id = "a00-idem-completed-1"
    with application.app_context():
        from app.adapters.db.agents.models.base import db
        from sqlalchemy import text

        db.session.execute(
            text("DELETE FROM agent_submissions WHERE submission_id = :s"),
            {"s": sub_id},
        )
        db.session.commit()

    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        return _agent_answer("ilk cevap")

    with (
        patch(
            "app.domain.agents.run.adapters.run_knowledge_agent",
            side_effect=fake_run,
        ),
        patch(
            "app.domain.agents.run.adapters.persist_turn",
            return_value={
                "complete": True,
                "assistant_memory_id": "am-1",
                "user_memory_id": "um-1",
            },
        ),
        patch(
            "app.domain.agents.run.adapters.load_flow_conversation",
            return_value=[],
        ),
        patch(
            "app.domain.agents.run.adapters.list_agent_conversations",
            return_value=[],
        ),
        patch(
            "app.domain.agents.run.adapters.resolve_session_id",
            return_value="sess-a00-1",
        ),
    ):
        r1 = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "Merhaba",
                "submission_id": sub_id,
                "session_id": "sess-a00-1",
            },
            follow_redirects=False,
        )
        assert r1.status_code in {302, 303}
        assert calls["n"] == 1

        r2 = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "Merhaba",
                "submission_id": sub_id,
                "session_id": "sess-a00-1",
            },
            follow_redirects=False,
        )
        assert r2.status_code in {302, 303}
        assert calls["n"] == 1  # no second LLM


def test_same_id_different_content_rejected(app_client) -> None:
    application, client, _url = app_client
    sub_id = "a00-idem-mismatch-1"
    with application.app_context():
        from app.adapters.db.agents.models.base import db
        from sqlalchemy import text

        db.session.execute(
            text("DELETE FROM agent_submissions WHERE submission_id = :s"),
            {"s": sub_id},
        )
        db.session.commit()

    with (
        patch(
            "app.domain.agents.run.adapters.run_knowledge_agent",
            return_value=_agent_answer(),
        ),
        patch(
            "app.domain.agents.run.adapters.persist_turn",
            return_value={
                "complete": True,
                "assistant_memory_id": "am-2",
                "user_memory_id": "um-2",
            },
        ),
        patch(
            "app.domain.agents.run.adapters.load_flow_conversation",
            return_value=[],
        ),
        patch(
            "app.domain.agents.run.adapters.list_agent_conversations",
            return_value=[],
        ),
        patch(
            "app.domain.agents.run.adapters.resolve_session_id",
            return_value="sess-a00-2",
        ),
    ):
        client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "soru bir",
                "submission_id": sub_id,
                "session_id": "sess-a00-2",
            },
        )
        r = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "soru iki farkli",
                "submission_id": sub_id,
                "session_id": "sess-a00-2",
            },
        )
        assert r.status_code == 400
        body = r.get_json()
        assert body["error"] == "submission_scope_mismatch"


def test_new_conversation_flag_changes_hash_scope(app_client) -> None:
    application, client, _url = app_client
    sub_id = "a00-idem-newconv-1"
    with application.app_context():
        from app.adapters.db.agents.models.base import db
        from sqlalchemy import text

        db.session.execute(
            text("DELETE FROM agent_submissions WHERE submission_id = :s"),
            {"s": sub_id},
        )
        db.session.commit()

    with (
        patch(
            "app.domain.agents.run.adapters.run_knowledge_agent",
            return_value=_agent_answer(),
        ),
        patch(
            "app.domain.agents.run.adapters.persist_turn",
            return_value={
                "complete": True,
                "assistant_memory_id": "am-3",
                "user_memory_id": "um-3",
            },
        ),
        patch(
            "app.domain.agents.run.adapters.load_flow_conversation",
            return_value=[],
        ),
        patch(
            "app.domain.agents.run.adapters.list_agent_conversations",
            return_value=[],
        ),
        patch(
            "app.domain.agents.run.adapters.resolve_session_id",
            return_value="sess-new",
        ),
    ):
        client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "aynı metin",
                "submission_id": sub_id,
                "session_id": "sess-old",
                "new_conversation": "0",
            },
        )
        r = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "aynı metin",
                "submission_id": sub_id,
                "session_id": "sess-new",
                "new_conversation": "1",
            },
        )
        assert r.status_code == 400


def test_persist_failure_keeps_assistant_text_on_submission(app_client) -> None:
    application, client, _url = app_client
    sub_id = "a00-persist-fail-1"
    with application.app_context():
        from app.adapters.db.agents.models.base import db
        from sqlalchemy import text

        db.session.execute(
            text("DELETE FROM agent_submissions WHERE submission_id = :s"),
            {"s": sub_id},
        )
        db.session.commit()

    with (
        patch(
            "app.domain.agents.run.adapters.run_knowledge_agent",
            return_value=_agent_answer("Kaybolmamalı cevap"),
        ),
        patch(
            "app.domain.agents.run.adapters.persist_turn",
            side_effect=RuntimeError("db down"),
        ),
        patch(
            "app.domain.agents.run.adapters.load_flow_conversation",
            return_value=[],
        ),
        patch(
            "app.domain.agents.run.adapters.list_agent_conversations",
            return_value=[],
        ),
        patch(
            "app.domain.agents.run.adapters.resolve_session_id",
            return_value="sess-persist",
        ),
    ):
        r = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "persist test",
                "submission_id": sub_id,
                "session_id": "sess-persist",
            },
            follow_redirects=False,
        )
        assert r.status_code in {302, 303}

    with application.app_context():
        from app.adapters.db.agents.repositories import submission_repository as submissions

        row = submissions.get_submission(
            customer_id=22, user_id=11, submission_id=sub_id
        )
        assert row is not None
        assert row["status"] == "completed"
        payload = row["result_json"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert payload.get("assistant_text") == "Kaybolmamalı cevap"
        assert payload.get("agent_reply") == "Kaybolmamalı cevap"
        assert payload.get("memory_error")


def test_cross_tenant_same_submission_id_independent(app_client) -> None:
    """Different customer/user can reuse the same submission_id string."""
    application, client, url = app_client
    sub_id = "a00-cross-tenant-1"

    from migrations._db import normalize_psycopg2_dsn

    conn = psycopg2.connect(normalize_psycopg2_dsn(url))
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM agent_submissions WHERE submission_id = %s", (sub_id,))
        conn.commit()
    finally:
        conn.close()

    with application.app_context():
        from app.adapters.db.agents.models.base import db
        from app.adapters.db.agents.repositories import submission_repository as submissions

        assert (
            submissions.try_begin_processing(
                customer_id=22,
                user_id=11,
                submission_id=sub_id,
                session_id="s1",
                request_hash="h1" * 32,
            )
            is True
        )
        db.session.commit()
        assert (
            submissions.try_begin_processing(
                customer_id=33,
                user_id=11,
                submission_id=sub_id,
                session_id="s2",
                request_hash="h2" * 32,
            )
            is True
        )
        db.session.commit()
