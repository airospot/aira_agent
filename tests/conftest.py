"""Shared pytest fixtures for A00 baseline checks."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_app_py() -> ModuleType:
    """Load repo-root ``app.py`` (not the ``app/`` package).

    Does not let ``load_dotenv(..., override=True)`` clobber the process env
    already set by pytest monkeypatch / A00_TEST_DATABASE_URL.
    """
    path = REPO_ROOT / "app.py"
    name = "native_knowledge_flow_app_py"
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "create_app", None):
        return existing

    import dotenv as dotenv_mod

    original = dotenv_mod.load_dotenv

    def _load_dotenv_no_override(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["override"] = False
        return original(*args, **kwargs)

    dotenv_mod.load_dotenv = _load_dotenv_no_override  # type: ignore[assignment]
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        dotenv_mod.load_dotenv = original  # type: ignore[assignment]


@pytest.fixture
def tmp_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    return root


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def test_database_url() -> str | None:
    """Optional real PostgreSQL URL for migration/race tests."""
    url = (os.environ.get("A00_TEST_DATABASE_URL") or "").strip()
    if url:
        return url
    # Fallback convention used in local A00 setup
    base = (os.environ.get("DATABASE_URL") or "").strip()
    if not base:
        return None
    # Prefer dedicated DB if present
    candidate = base.rsplit("/", 1)[0] + "/NATIVE_FLOW_A00_TEST"
    return candidate
