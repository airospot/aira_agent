"""A00: real PostgreSQL migration idempotency + concurrent reservation race.

Requires A00_TEST_DATABASE_URL or DATABASE_URL pointing at a disposable DB
(preferably NATIVE_FLOW_A00_TEST). Skips when unreachable — never pretends
mock results are real DB proof.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest

psycopg2 = pytest.importorskip("psycopg2")


def _redact(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, f"{p.hostname}:{p.port or 5432}", p.path, "", "", ""))


def _resolve_test_url() -> str | None:
    explicit = (os.environ.get("A00_TEST_DATABASE_URL") or "").strip()
    if explicit:
        return explicit
    base = (os.environ.get("DATABASE_URL") or "").strip()
    if not base:
        # Load .env without overriding process env
        try:
            from dotenv import load_dotenv

            load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
        except Exception:  # noqa: BLE001
            pass
        base = (os.environ.get("DATABASE_URL") or "").strip()
    if not base:
        return None
    # Dedicated disposable DB preferred
    return base.rsplit("/", 1)[0] + "/NATIVE_FLOW_A00_TEST"


def _can_connect(url: str) -> bool:
    try:
        from migrations._db import normalize_psycopg2_dsn

        conn = psycopg2.connect(normalize_psycopg2_dsn(url))
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def pg_url() -> str:
    url = _resolve_test_url()
    if not url or not _can_connect(url):
        pytest.skip(
            "Gerçek PostgreSQL test DB erişilemedi "
            f"(A00_TEST_DATABASE_URL / NATIVE_FLOW_A00_TEST). "
            f"Aday: {_redact(url) if url else 'yok'}"
        )
    return url


def test_agent_submissions_migration_twice(pg_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", pg_url)
    # Prevent dotenv from re-injecting production URL over the test DB
    monkeypatch.setenv("POSTGRES_HOST", "")
    monkeypatch.setenv("POSTGRES_DB", "")
    monkeypatch.setenv("POSTGRES_USER", "")
    monkeypatch.setenv("POSTGRES_PASSWORD", "")

    from migrations.create_agent_submissions_table import create_agent_submissions_table

    create_agent_submissions_table()
    create_agent_submissions_table()  # second run must be no-op / safe

    from migrations._db import normalize_psycopg2_dsn

    conn = psycopg2.connect(normalize_psycopg2_dsn(pg_url))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'agent_submissions'
            )
            """
        )
        assert cur.fetchone()[0] is True
        cur.execute(
            """
            SELECT constraint_name FROM information_schema.table_constraints
            WHERE table_name = 'agent_submissions' AND constraint_type = 'PRIMARY KEY'
            """
        )
        assert cur.fetchone() is not None
    finally:
        conn.close()


def test_concurrent_try_begin_processing_single_winner(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("SECRET_KEY", "a00-pg-race-secret-key-long-enough")
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "7")
    monkeypatch.setenv("AUTH_BYPASS_CUSTOMER_ID", "3")

    from migrations.create_agent_submissions_table import create_agent_submissions_table

    create_agent_submissions_table()

    from migrations._db import normalize_psycopg2_dsn

    conn = psycopg2.connect(normalize_psycopg2_dsn(pg_url))
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM agent_submissions WHERE submission_id = %s",
            ("a00-race-sub-1",),
        )
        conn.commit()
    finally:
        conn.close()

    from tests.conftest import load_app_py
    from app.adapters.db.agents.repositories import submission_repository as submissions

    application = load_app_py().create_app()
    results: list[bool] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        with application.app_context():
            barrier.wait()
            owned = submissions.try_begin_processing(
                customer_id=3,
                user_id=7,
                submission_id="a00-race-sub-1",
                session_id="sess-race",
                request_hash="abc" * 10 + "abcd",
            )
            from app.adapters.db.agents.models.base import db

            db.session.commit()
            results.append(owned)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert sorted(results) == [False, True]

    with application.app_context():
        row = submissions.get_submission(
            customer_id=3, user_id=7, submission_id="a00-race-sub-1"
        )
        assert row is not None
        assert row["status"] == "processing"

    # Cross-tenant same submission_id is independent
    with application.app_context():
        other = submissions.try_begin_processing(
            customer_id=99,
            user_id=7,
            submission_id="a00-race-sub-1",
            session_id="sess-other",
            request_hash="xyz" * 10 + "xyzz",
        )
        from app.adapters.db.agents.models.base import db

        db.session.commit()
        assert other is True
