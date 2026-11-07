"""A02: web propose cannot override server tenant via form fields."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.conftest import load_app_py


@pytest.fixture
def app_client(monkeypatch):
    # Fixture owns required env — mock service path does not need a live DB.
    import os

    db = (
        os.environ.get("A00_TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql://native:native@127.0.0.1:5432/NATIVE_FLOW_A00_TEST"
    )
    monkeypatch.setenv("DATABASE_URL", db)
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "7")
    monkeypatch.setenv("AUTH_BYPASS_CUSTOMER_ID", "9")
    monkeypatch.setenv("SECRET_KEY", "a02-route-test-secret")
    mod = load_app_py()
    application = mod.create_app()
    application.config["TESTING"] = True
    application.config["AUTH_DISABLED"] = "1"
    application.config["AUTH_BYPASS_USER_ID"] = 7
    application.config["AUTH_BYPASS_CUSTOMER_ID"] = 9
    client = application.test_client()
    return application, client


def test_form_customer_user_cannot_override_execution_context(app_client):
    _app, client = app_client
    captured: dict = {}

    class FakeOutcome:
        kind = "empty_question"
        submission_id = "sub-x"
        session_id = "s1"
        turn_id = None
        payload = {
            "session_id": "s1",
            "submission_id": "sub-x",
            "agent_notice": "Boş soru gönderilmedi.",
            "replayed": False,
        }
        agent_session_id = "s1"
        error = None
        message = None

    class FakeService:
        def run(self, ctx, req):
            captured["customer_id"] = ctx.customer_id
            captured["user_id"] = ctx.user_id
            captured["permitted"] = set(ctx.permitted_tool_names)
            captured["corpus"] = ctx.runner_config.get("AGENT_CORPUS_DIR")
            return FakeOutcome()

    with patch(
        "app.interfaces.web.agent_routes.propose.create_agent_run_service",
        return_value=FakeService(),
    ):
        resp = client.post(
            "/agent/assistant/propose",
            data={
                "request_text": "",
                "submission_id": "sub-x",
                "customer_id": "1",
                "user_id": "1",
                "permitted_tools": "evil_tool",
            },
            follow_redirects=False,
        )
    assert resp.status_code in {302, 303}
    assert captured["customer_id"] == 9
    assert captured["user_id"] == 7
    assert "evil_tool" not in captured["permitted"]
    assert captured["corpus"] is not None
    assert captured["corpus"].endswith("/9/corpus") or "/9/corpus" in captured["corpus"]


def test_route_maps_outcome_kind_to_http_400(app_client):
    _app, client = app_client

    class FakeOutcome:
        kind = "scope_mismatch"
        submission_id = "sub-y"
        session_id = None
        turn_id = None
        payload = {}
        agent_session_id = None
        error = "submission_scope_mismatch"
        message = "scope"

    class FakeService:
        def run(self, ctx, req):
            return FakeOutcome()

    with patch(
        "app.interfaces.web.agent_routes.propose.create_agent_run_service",
        return_value=FakeService(),
    ):
        resp = client.post(
            "/agent/assistant/propose",
            data={"request_text": "x", "submission_id": "sub-y"},
            follow_redirects=False,
        )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "submission_scope_mismatch"
