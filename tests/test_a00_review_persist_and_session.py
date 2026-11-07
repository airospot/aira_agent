"""A00 review: GET restore after persist fail; stable new/empty session replay."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

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
        pytest.skip("Gerçek PostgreSQL test DB erişilemedi (A00 review).")

    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SECRET_KEY", "a00-review-fix-secret-key-long")
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


def _agent_answer(text: str) -> dict:
    return {"status": "ANSWER", "decision": {"answer": text}, "stage": "decision"}


def _location_qs(resp) -> dict:
    loc = resp.headers.get("Location") or ""
    return parse_qs(urlparse(loc).query)


def test_persist_failure_post_redirect_get_refresh_replay_shows_answer(app_client) -> None:
    application, client, _url = app_client
    sub_id = "a00-rev-persist-get-1"
    answer = "PersistFailCevap-" + ("Z" * 200)
    _purge(application, sub_id)
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        return _agent_answer(answer)

    with (
        patch(
            "app.interfaces.web.agent_routes.propose.run_knowledge_agent",
            side_effect=fake_run,
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.persist_turn",
            side_effect=RuntimeError("db down"),
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.load_flow_conversation",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.list_agent_conversations",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.list_agent_conversations",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.load_ui_transcript",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.load_turn_trace",
            return_value=None,
        ),
    ):
        # Real session resolver (no patch): empty session start.
        r1 = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "persist görünür mü",
                "submission_id": sub_id,
            },
            follow_redirects=False,
        )
        assert r1.status_code in {302, 303}
        qs = _location_qs(r1)
        assert qs.get("submission_id", [None])[0] == sub_id
        session_id = qs.get("session_id", [None])[0]
        assert session_id

        with client.session_transaction() as sess:
            last = sess.get("agent_last_ui") or {}
            assert answer not in json.dumps(last, ensure_ascii=False)
            assert "assistant_text" not in last
            assert "agent_reply" not in last

        get1 = client.get(
            f"/agent/assistant?session_id={session_id}&submission_id={sub_id}"
        )
        assert get1.status_code == 200
        body1 = get1.get_data(as_text=True)
        assert answer in body1
        assert "bellek yazılamadı" in body1.lower() or "Yanıt üretildi" in body1

        # Refresh (plain GET) still shows answer from server submission.
        get2 = client.get(
            f"/agent/assistant?session_id={session_id}&submission_id={sub_id}"
        )
        assert answer in get2.get_data(as_text=True)
        assert calls["n"] == 1

        # Replay same submission — no second LLM; answer still on GET after redirect.
        r2 = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "persist görünür mü",
                "submission_id": sub_id,
                "session_id": session_id,
            },
            follow_redirects=False,
        )
        assert r2.status_code in {302, 303}
        assert calls["n"] == 1
        qs2 = _location_qs(r2)
        assert qs2.get("submission_id", [None])[0] == sub_id
        get3 = client.get(r2.headers["Location"])
        assert answer in get3.get_data(as_text=True)


def test_new_conversation_same_submission_replays_with_real_resolver(app_client) -> None:
    application, client, _url = app_client
    sub_id = "a00-rev-newconv-1"
    _purge(application, sub_id)
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        return _agent_answer("yeni konuşma cevabı")

    with (
        patch(
            "app.interfaces.web.agent_routes.propose.run_knowledge_agent",
            side_effect=fake_run,
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.persist_turn",
            return_value={
                "complete": True,
                "assistant_memory_id": "am-nc",
                "user_memory_id": "um-nc",
            },
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.load_flow_conversation",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.list_agent_conversations",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.list_agent_conversations",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.load_ui_transcript",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.load_turn_trace",
            return_value=None,
        ),
    ):
        r1 = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "yeni oturum sorusu",
                "submission_id": sub_id,
                "new_conversation": "1",
            },
            follow_redirects=False,
        )
        assert r1.status_code in {302, 303}
        assert calls["n"] == 1
        session_id = _location_qs(r1).get("session_id", [None])[0]
        assert session_id

        # Clear flask conversation key to force resolver pressure on retry.
        with client.session_transaction() as sess:
            sess.pop("agent_session_id", None)

        r2 = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "yeni oturum sorusu",
                "submission_id": sub_id,
                "new_conversation": "1",
            },
            follow_redirects=False,
        )
        assert r2.status_code in {302, 303}
        assert calls["n"] == 1
        assert _location_qs(r2).get("session_id", [None])[0] == session_id

        r3 = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "farklı içerik",
                "submission_id": sub_id,
                "new_conversation": "1",
            },
        )
        assert r3.status_code == 400
        assert r3.get_json()["error"] == "submission_scope_mismatch"
        assert calls["n"] == 1


def test_empty_session_same_submission_replays_with_real_resolver(app_client) -> None:
    application, client, _url = app_client
    sub_id = "a00-rev-empty-sess-1"
    _purge(application, sub_id)
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        return _agent_answer("boş session cevabı")

    with (
        patch(
            "app.interfaces.web.agent_routes.propose.run_knowledge_agent",
            side_effect=fake_run,
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.persist_turn",
            return_value={
                "complete": True,
                "assistant_memory_id": "am-es",
                "user_memory_id": "um-es",
            },
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.load_flow_conversation",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.list_agent_conversations",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.list_agent_conversations",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.load_ui_transcript",
            return_value=[],
        ),
        patch(
            "app.interfaces.web.agent_routes.assistant.load_turn_trace",
            return_value=None,
        ),
    ):
        r1 = client.post(
            "/agent/assistant/propose",
            data={"request_text": "ilk soru", "submission_id": sub_id},
            follow_redirects=False,
        )
        assert r1.status_code in {302, 303}
        session_id = _location_qs(r1).get("session_id", [None])[0]
        assert session_id
        assert calls["n"] == 1

        with client.session_transaction() as sess:
            sess.pop("agent_session_id", None)

        r2 = client.post(
            "/agent/assistant/propose",
            data={"request_text": "ilk soru", "submission_id": sub_id},
            follow_redirects=False,
        )
        assert r2.status_code in {302, 303}
        assert calls["n"] == 1
        assert _location_qs(r2).get("session_id", [None])[0] == session_id

        r3 = client.post(
            "/agent/assistant/propose",
            data={"request_text": "başka soru", "submission_id": sub_id},
        )
        assert r3.status_code == 400
        assert calls["n"] == 1
