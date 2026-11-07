"""A00: GET recovery survives transcript/list MemoryReadError (no LLM rerun)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

from app.domain.agents.flow.memory import MemoryReadError

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
        pytest.skip("Gerçek PostgreSQL test DB erişilemedi (GET recovery).")

    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SECRET_KEY", "a00-get-recovery-memory-read-secret")
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "11")
    monkeypatch.setenv("AUTH_BYPASS_CUSTOMER_ID", "22")

    from migrations.add_embedding_to_conversation_memory import add_embedding_column
    from migrations.create_agent_submissions_table import create_agent_submissions_table
    from migrations.create_conversation_memory_table import (
        create_conversation_memory_table,
    )

    create_agent_submissions_table()
    try:
        create_conversation_memory_table()
    except Exception:  # noqa: BLE001
        pass
    try:
        add_embedding_column()
    except Exception:  # noqa: BLE001
        pass

    from tests.conftest import load_app_py

    application = load_app_py().create_app()
    application.config["TESTING"] = True
    return application, application.test_client(), url


def _purge(application, sub_id: str) -> None:
    with application.app_context():
        from app.adapters.db.agents.models.base import db
        from sqlalchemy import text

        db.session.execute(
            text("DELETE FROM agent_submissions WHERE submission_id = :s"),
            {"s": sub_id},
        )
        db.session.commit()


def _seed_completed_submission(application, client, *, sub_id: str, answer: str) -> str:
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        return {"status": "ANSWER", "decision": {"answer": answer}, "stage": "decision"}

    with (
        patch(
            "app.interfaces.web.agent_routes.propose.run_knowledge_agent",
            side_effect=fake_run,
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.persist_turn",
            side_effect=RuntimeError("persist skipped"),
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.load_flow_conversation",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.list_agent_conversations",
            return_value=[],
        ),
    ):
        resp = client.post(
            "/agent/assistant/propose",
            data={"request_text": "recovery seed", "submission_id": sub_id},
            follow_redirects=False,
        )
    assert resp.status_code in {302, 303}
    assert calls["n"] == 1
    session_id = parse_qs(urlparse(resp.headers["Location"]).query).get(
        "session_id", [None]
    )[0]
    assert session_id
    return session_id


def test_get_recovery_survives_transcript_memory_read_error(app_client) -> None:
    application, client, _url = app_client
    sub_id = f"a00-get-tx-{uuid4().hex[:8]}"
    answer = "RECOVERY_TRANSCRIPT_FAIL_" + uuid4().hex[:6]
    _purge(application, sub_id)
    session_id = _seed_completed_submission(
        application, client, sub_id=sub_id, answer=answer
    )

    with (
        patch(
            "app.interfaces.web.agent_routes.assistant.load_ui_transcript",
            side_effect=MemoryReadError("transcript down"),
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.list_agent_conversations",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.load_turn_trace",
            return_value=None,
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.run_knowledge_agent",
            side_effect=AssertionError("LLM must not run on GET"),
        ),
    ):
        get1 = client.get(
            f"/agent/assistant?session_id={session_id}&submission_id={sub_id}"
        )
        body1 = get1.get_data(as_text=True)
        assert get1.status_code == 200
        assert answer in body1
        assert "Konuşma belleği okunamadı" in body1

        # Refresh
        get2 = client.get(
            f"/agent/assistant?session_id={session_id}&submission_id={sub_id}"
        )
        assert answer in get2.get_data(as_text=True)

        # new=1 still isolates
        fresh = client.get(f"/agent/assistant?new=1&submission_id={sub_id}")
        assert answer not in fresh.get_data(as_text=True)

        with client.session_transaction() as sess:
            blob = repr(sess.get("agent_last_ui") or {})
            assert answer not in blob


def test_get_recovery_survives_conversation_list_memory_read_error(app_client) -> None:
    application, client, _url = app_client
    sub_id = f"a00-get-list-{uuid4().hex[:8]}"
    answer = "RECOVERY_LIST_FAIL_" + uuid4().hex[:6]
    _purge(application, sub_id)
    session_id = _seed_completed_submission(
        application, client, sub_id=sub_id, answer=answer
    )

    with (
        patch(
            "app.interfaces.web.agent_routes.assistant.load_ui_transcript",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.list_agent_conversations",
            side_effect=MemoryReadError("sidebar down"),
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.load_turn_trace",
            return_value=None,
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.run_knowledge_agent",
            side_effect=AssertionError("LLM must not run on GET"),
        ),
    ):
        get1 = client.get(
            f"/agent/assistant?session_id={session_id}&submission_id={sub_id}"
        )
        body1 = get1.get_data(as_text=True)
        assert get1.status_code == 200
        assert answer in body1
        assert "Konuşma belleği okunamadı" in body1

        get2 = client.get(
            f"/agent/assistant?session_id={session_id}&submission_id={sub_id}"
        )
        assert answer in get2.get_data(as_text=True)

        mismatch = client.get(
            f"/agent/assistant?session_id={uuid4()}&submission_id={sub_id}"
        )
        assert answer not in mismatch.get_data(as_text=True)
