"""A00: migration connect prefers process env over .env (override=False)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from migrations._db import connect, normalize_psycopg2_dsn


def test_normalize_sqlalchemy_style_url() -> None:
    assert (
        normalize_psycopg2_dsn("postgresql+psycopg2://u:p@h:5432/db")
        == "postgresql://u:p@h:5432/db"
    )
    assert normalize_psycopg2_dsn("postgres://u:p@h/db") == "postgresql://u:p@h/db"
    assert normalize_psycopg2_dsn("postgresql://u:p@h/db") == "postgresql://u:p@h/db"


def test_connect_uses_process_database_url_not_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql://dotenv_user:dotenv_pass@dotenv-host:5432/dotenv_db\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://proc_user:proc_pass@proc-host:5432/proc_db",
    )
    captured: dict[str, str] = {}

    def fake_connect(dsn: str):
        captured["dsn"] = dsn
        return MagicMock()

    with (
        patch("migrations._db._REPO_ROOT", tmp_path),
        patch("migrations._db.psycopg2.connect", side_effect=fake_connect),
    ):
        connect()

    assert "proc-host" in captured["dsn"]
    assert "proc_db" in captured["dsn"]
    assert "dotenv-host" not in captured["dsn"]


def test_connect_falls_back_to_postgres_env_when_database_url_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=\n", encoding="utf-8")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "pg-host")
    monkeypatch.setenv("POSTGRES_DB", "pg-db")
    monkeypatch.setenv("POSTGRES_USER", "pg-user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "pg-pass")
    monkeypatch.setenv("POSTGRES_PORT", "5433")

    captured: dict[str, object] = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    with (
        patch("migrations._db._REPO_ROOT", tmp_path),
        patch("migrations._db.psycopg2.connect", side_effect=fake_connect),
    ):
        connect()

    assert captured["host"] == "pg-host"
    assert captured["database"] == "pg-db"
    assert captured["port"] == 5433
