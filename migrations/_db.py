"""Shared DB connection for migration scripts.

Importable as ``from migrations._db import connect`` when repo root is on
``sys.path``, and safe when scripts are run as ``python migrations/....py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_repo_on_path() -> None:
    root = str(_REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _load_env() -> None:
    load_dotenv(_REPO_ROOT / ".env", override=False)


def normalize_psycopg2_dsn(url: str) -> str:
    """Convert SQLAlchemy-style URLs to a psycopg2-compatible postgresql:// DSN."""
    raw = str(url or "").strip()
    if not raw:
        return raw
    if raw.startswith("postgresql+psycopg2://"):
        return "postgresql://" + raw[len("postgresql+psycopg2://") :]
    if raw.startswith("postgres://"):
        return "postgresql://" + raw[len("postgres://") :]
    return raw


def _connect_from_database_url(url: str):
    dsn = normalize_psycopg2_dsn(url)
    parsed = urlparse(dsn)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise SystemExit(
            f"DATABASE_URL scheme desteklenmiyor: {parsed.scheme!r} "
            "(beklenen postgresql://)"
        )
    # Redacted log for operators
    safe = urlunparse(
        (
            "postgresql",
            f"{parsed.hostname or '?'}:{parsed.port or 5432}",
            parsed.path or "/",
            "",
            "",
            "",
        )
    )
    print(f"  🔗 Connecting via DATABASE_URL → {safe}")
    return psycopg2.connect(dsn)


def _connect_from_postgres_env():
    host = (os.environ.get("POSTGRES_HOST") or "").strip()
    database = (os.environ.get("POSTGRES_DB") or "").strip()
    user = (os.environ.get("POSTGRES_USER") or "").strip()
    password = os.environ.get("POSTGRES_PASSWORD")
    port_raw = (os.environ.get("POSTGRES_PORT") or "5432").strip() or "5432"

    missing = [
        name
        for name, value in (
            ("POSTGRES_HOST", host),
            ("POSTGRES_DB", database),
            ("POSTGRES_USER", user),
            ("POSTGRES_PASSWORD", password if password is not None else ""),
        )
        if not str(value or "").strip() and name != "POSTGRES_PASSWORD"
    ]
    if password is None or str(password) == "":
        missing.append("POSTGRES_PASSWORD")
    if missing:
        raise SystemExit(
            "DATABASE_URL yok; POSTGRES_* eksik: " + ", ".join(missing)
        )
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise SystemExit(f"POSTGRES_PORT geçersiz: {port_raw!r}") from exc

    print(f"  🔗 Connecting via POSTGRES_* → {host}:{port}/{database}")
    return psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
    )


def connect():
    """Open a psycopg2 connection using DATABASE_URL or required POSTGRES_*."""
    _ensure_repo_on_path()
    _load_env()
    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    if database_url:
        return _connect_from_database_url(database_url)
    return _connect_from_postgres_env()
