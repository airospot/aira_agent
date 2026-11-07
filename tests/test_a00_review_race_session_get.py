"""A00 review #2: concurrent empty/new race, session mismatch, GET isolation."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

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
        pytest.skip("Gerçek PostgreSQL test DB erişilemedi (A00 review #2).")

    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SECRET_KEY", "a00-review2-secret-key-long-enough")
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "11")
    monkeypatch.setenv("AUTH_BYPASS_CUSTOMER_ID", "22")
    monkeypatch.setenv("AGENT_SUBMISSION_TIMEOUT_SECONDS", "900")

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


def _agent_answer(text: str) -> dict:
    return {"status": "ANSWER", "decision": {"answer": text}, "stage": "decision"}


def _location_qs(resp) -> dict:
    loc = resp.headers.get("Location") or ""
    return parse_qs(urlparse(loc).query)


def test_concurrent_empty_new_submission_single_reservation(app_client) -> None:
    """Both first lookups miss; only one agent run; loser is processing/replay."""
    application, _client, _url = app_client
    sub_id = f"a00-rev2-race-{uuid4().hex[:8]}"
    _purge(application, sub_id)
    calls = {"n": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    results: list = []

    def fake_run(*_a, **_k):
        with lock:
            calls["n"] += 1
        time.sleep(0.35)
        return _agent_answer("race-canonical-answer")

    def worker(new_conversation: str) -> None:
        # Separate test clients ⇒ separate flask sessions (both miss prior).
        c = application.test_client()
        with (
            patch(
                "app.interfaces.web.agent_routes.propose.run_knowledge_agent",
                side_effect=fake_run,
            ),
            patch(
                "app.interfaces.web.agent_routes.propose.persist_turn",
                return_value={
                    "complete": True,
                    "assistant_memory_id": "am-race",
                    "user_memory_id": "um-race",
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
        ):
            barrier.wait(timeout=10)
            resp = c.post(
                "/agent/assistant/propose",
                data={
                    "request_text": "eşzamanlı soru",
                    "submission_id": sub_id,
                    "new_conversation": new_conversation,
                },
                follow_redirects=False,
            )
            results.append(resp)

    t1 = threading.Thread(target=worker, args=("1",))
    t2 = threading.Thread(target=worker, args=("1",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert len(results) == 2
    assert all(r.status_code in {302, 303} for r in results)
    assert calls["n"] == 1

    sessions = {
        (_location_qs(r).get("session_id") or [None])[0] for r in results
    }
    assert len(sessions) == 1
    assert None not in sessions

    with application.app_context():
        from app.adapters.db.agents.repositories import submission_repository as submissions

        row = submissions.get_submission(
            customer_id=22, user_id=11, submission_id=sub_id
        )
        assert row is not None
        assert row["status"] in {"processing", "completed"}
        assert row["session_id"] == next(iter(sessions))


def test_replay_rejects_different_session_allows_canonical(app_client) -> None:
    application, client, _url = app_client
    sub_id = f"a00-rev2-sess-{uuid4().hex[:8]}"
    _purge(application, sub_id)
    calls = {"n": 0}

    def fake_run(*_a, **_k):
        calls["n"] += 1
        return _agent_answer("canonical replay ok")

    with (
        patch(
            "app.interfaces.web.agent_routes.propose.run_knowledge_agent",
            side_effect=fake_run,
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.persist_turn",
            return_value={
                "complete": True,
                "assistant_memory_id": "am-s",
                "user_memory_id": "um-s",
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
            data={"request_text": "boş session ilk", "submission_id": sub_id},
            follow_redirects=False,
        )
        assert r1.status_code in {302, 303}
        canonical = _location_qs(r1).get("session_id", [None])[0]
        assert canonical
        assert calls["n"] == 1

        foreign = str(uuid4())
        bad = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "boş session ilk",
                "submission_id": sub_id,
                "session_id": foreign,
            },
        )
        assert bad.status_code == 400
        assert bad.get_json()["error"] == "submission_session_mismatch"
        assert calls["n"] == 1

        good = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "boş session ilk",
                "submission_id": sub_id,
                "session_id": canonical,
            },
            follow_redirects=False,
        )
        assert good.status_code in {302, 303}
        assert calls["n"] == 1
        assert _location_qs(good).get("session_id", [None])[0] == canonical


def test_get_submission_recovery_requires_matching_session(app_client) -> None:
    application, client, _url = app_client
    sub_id = f"a00-rev2-get-{uuid4().hex[:8]}"
    answer_a = "ANSWER_FROM_SESSION_A_UNIQUE"
    _purge(application, sub_id)

    with (
        patch(
            "app.interfaces.web.agent_routes.propose.run_knowledge_agent",
            return_value=_agent_answer(answer_a),
        ),
        patch(
            "app.interfaces.web.agent_routes.propose.persist_turn",
            side_effect=RuntimeError("skip memory"),
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
            data={"request_text": "konuşma A", "submission_id": sub_id},
            follow_redirects=False,
        )
        session_a = _location_qs(r1).get("session_id", [None])[0]
        assert session_a

        ok = client.get(
            f"/agent/assistant?session_id={session_a}&submission_id={sub_id}"
        )
        assert answer_a in ok.get_data(as_text=True)

        session_b = str(uuid4())
        cross = client.get(
            f"/agent/assistant?session_id={session_b}&submission_id={sub_id}"
        )
        assert answer_a not in cross.get_data(as_text=True)

        fresh = client.get(f"/agent/assistant?new=1&submission_id={sub_id}")
        assert answer_a not in fresh.get_data(as_text=True)
