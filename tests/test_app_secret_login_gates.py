"""A00: SECRET_KEY and LOGIN_UI_URL startup gates."""

from __future__ import annotations

import pytest

from tests.conftest import load_app_py


def _apply_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set after ``load_app_py`` so ``app.py`` dotenv(override=True) cannot refill."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:5432/testdb")
    monkeypatch.setenv("SECRET_KEY", "a00-unit-test-secret-key-not-placeholder")
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "1")
    monkeypatch.setenv("AUTH_BYPASS_CUSTOMER_ID", "1")
    monkeypatch.delenv("LOGIN_UI_URL", raising=False)


def test_secret_key_required(monkeypatch: pytest.MonkeyPatch) -> None:
    app_module = load_app_py()
    _apply_base_env(monkeypatch)
    monkeypatch.setenv("SECRET_KEY", "")

    with pytest.raises(SystemExit, match="SECRET_KEY"):
        app_module.create_app()


def test_secret_key_placeholder_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    app_module = load_app_py()
    _apply_base_env(monkeypatch)
    monkeypatch.setenv("SECRET_KEY", "changeme")

    with pytest.raises(SystemExit, match="placeholder"):
        app_module.create_app()


def test_login_ui_url_required_when_auth_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    app_module = load_app_py()
    _apply_base_env(monkeypatch)
    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.delenv("LOGIN_UI_URL", raising=False)

    with pytest.raises(SystemExit, match="LOGIN_UI_URL"):
        app_module.create_app()


def test_auth_disabled_allows_missing_login_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    app_module = load_app_py()
    _apply_base_env(monkeypatch)
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.delenv("LOGIN_UI_URL", raising=False)

    application = app_module.create_app()
    assert application.config["SECRET_KEY"]
    client = application.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
