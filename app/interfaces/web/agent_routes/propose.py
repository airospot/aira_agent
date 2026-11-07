"""POST /assistant/propose — HTTP adapter over AgentRunService."""

from __future__ import annotations

from flask import current_app, jsonify, request, session

from app.core.security import require_tenant, role_required
from app.domain.agents.run.contracts import RunRequest
from app.domain.agents.run.factory import (
    build_execution_context,
    create_agent_run_service,
    skill_id_for_form,
)
from app.domain.agents.skills.catalog import STANDARD_SKILL_ID
from app.domain.agents.skills.errors import SkillError
from app.interfaces.web.agent_routes.assistant import redirect_assistant
from app.interfaces.web.agent_routes.blueprint import agent_bp
from app.interfaces.web.agent_routes.submission_store import (
    mint_submission_id,
    remember_submission,
)
from app.interfaces.web.agent_routes.tenant import tenant_ids

# HTTP mapping lives in the route — service outcomes stay transport-free.
_HTTP_ERROR_BY_KIND = frozenset(
    {
        "session_mismatch",
        "scope_mismatch",
        "invalid_submission_id",
        "skill_error",
    }
)


@agent_bp.post("/assistant/propose")
@require_tenant
@role_required(["Admin", "Super Admin"])
def assistant_propose():
    """Run agent at most once per scoped submission; persist; 303 → GET."""
    request_text = (request.form.get("request_text") or "").strip()
    raw_submission = request.form.get("submission_id")
    # Empty → mint; non-empty (incl. padded) → service normalizes/validates once.
    if raw_submission is None or str(raw_submission).strip() == "":
        submission_id = mint_submission_id()
    else:
        submission_id = str(raw_submission)
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
    # Version/content/tools must not come from the client.
    _ = request.form.get("skill_version")
    _ = request.form.get("skill_digest")
    _ = request.form.get("skill_tools")
    _ = request.form.get("allowed_tools")

    new_conversation = (request.form.get("new_conversation") or "").strip() in {
        "1",
        "true",
        "yes",
    }
    explicit_session_id = str(request.form.get("session_id") or "").strip() or None
    agent_session_hint = str(session.get("agent_session_id") or "").strip() or None

    try:
        skill_id = skill_id_for_form(request.form.get("skill_id"))
        ctx = build_execution_context(
            customer_id=customer_id,
            user_id=user_id,
            config=current_app.config,
            skill_id=skill_id,
        )
    except SkillError as exc:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": exc.code,
                    "message": exc.message,
                }
            ),
            400,
        )

    req = RunRequest(
        request_text=request_text,
        submission_id=submission_id,
        explicit_session_id=explicit_session_id,
        new_conversation=new_conversation,
        agent_session_id_hint=agent_session_hint,
        skill_id=skill_id,
    )
    service = create_agent_run_service()
    outcome = service.run(ctx, req)

    if outcome.agent_session_id:
        session["agent_session_id"] = outcome.agent_session_id

    if outcome.kind in _HTTP_ERROR_BY_KIND:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": outcome.error or outcome.kind,
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

    redirect_skill = skill_id if skill_id != STANDARD_SKILL_ID else None
    return redirect_assistant(
        session_id=outcome.session_id,
        turn_id=outcome.turn_id,
        submission_id=outcome.submission_id,
        skill_id=redirect_skill,
    )
