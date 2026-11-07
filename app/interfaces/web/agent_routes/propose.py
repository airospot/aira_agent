"""POST /assistant/propose — HTTP adapter over AgentRunService."""

from __future__ import annotations

from flask import current_app, jsonify, request, session

from app.core.security import require_tenant, role_required
from app.domain.agents.run.contracts import RunRequest
from app.domain.agents.run.factory import (
    build_execution_context,
    create_agent_run_service,
)
from app.interfaces.web.agent_routes.assistant import redirect_assistant
from app.interfaces.web.agent_routes.blueprint import agent_bp
from app.interfaces.web.agent_routes.submission_store import (
    mint_submission_id,
    remember_submission,
)
from app.interfaces.web.agent_routes.tenant import tenant_ids


@agent_bp.post("/assistant/propose")
@require_tenant
@role_required(["Admin", "Super Admin"])
def assistant_propose():
    """Run agent at most once per scoped submission; persist; 303 → GET."""
    request_text = (request.form.get("request_text") or "").strip()
    submission_id = (
        (request.form.get("submission_id") or "").strip() or mint_submission_id()
    )
    customer_id, user_id = tenant_ids()

    if not customer_id or not user_id:
        payload = {
            "session_id": None,
            "agent_notice": "Yetkili kullanıcı/tenant bağlamı çözülemedi.",
            "memory_error": "Kimlik eksik; bellek kullanılmadı.",
            "replayed": False,
        }
        remember_submission(session, submission_id=submission_id, payload=payload)
        return redirect_assistant()

    # Form may carry spoofed ids — ignored; only server tenant_ids() are used.
    _ = request.form.get("customer_id")
    _ = request.form.get("user_id")
    _ = request.form.get("permitted_tools")

    new_conversation = (request.form.get("new_conversation") or "").strip() in {
        "1",
        "true",
        "yes",
    }
    explicit_session_id = str(request.form.get("session_id") or "").strip() or None
    agent_session_hint = str(session.get("agent_session_id") or "").strip() or None

    ctx = build_execution_context(
        customer_id=customer_id,
        user_id=user_id,
        config=current_app.config,
    )
    req = RunRequest(
        request_text=request_text,
        submission_id=submission_id,
        explicit_session_id=explicit_session_id,
        new_conversation=new_conversation,
        agent_session_id_hint=agent_session_hint,
    )
    service = create_agent_run_service()
    outcome = service.run(ctx, req)

    if outcome.agent_session_id:
        session["agent_session_id"] = outcome.agent_session_id

    if outcome.http_status == 400:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": outcome.error,
                    "message": outcome.message,
                }
            ),
            400,
        )

    if outcome.payload:
        remember_submission(
            session,
            submission_id=outcome.submission_id,
            payload=dict(outcome.payload),
        )

    return redirect_assistant(
        session_id=outcome.session_id,
        turn_id=outcome.turn_id,
        submission_id=outcome.submission_id,
    )
