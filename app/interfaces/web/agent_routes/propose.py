"""POST /assistant/propose — idempotent agent run, persist, 303 → GET."""

from __future__ import annotations

from flask import current_app, jsonify, request, session

from app.adapters.db.agents.models.base import db
from app.adapters.db.agents.repositories import submission_repository as submissions
from app.core.security import require_tenant, role_required
from app.domain.agents.flow.execution.run_knowledge_agent import (
    run_knowledge_agent,
)
from app.domain.agents.flow.memory import (
    MemoryPersistIncompleteError,
    MemoryReadError,
    SessionIdentityError,
    list_agent_conversations,
    load_flow_conversation,
    persist_turn,
    resolve_session_id,
)
from app.interfaces.web.agent_routes.assistant import redirect_assistant
from app.interfaces.web.agent_routes.blueprint import agent_bp
from app.interfaces.web.agent_routes.submission_display import parse_submission_result
from app.interfaces.web.agent_routes.submission_store import (
    mint_submission_id,
    remember_submission,
)
from app.interfaces.web.agent_routes.tenant import tenant_ids
from app.interfaces.web.agent_routes.timeline_present import (
    present_flow_timeline,
    sanitize_flow_event,
)


def pack_decision_trace(result: dict) -> dict | None:
    decision_trace = result.get("decision_trace")
    if not isinstance(decision_trace, list):
        return None
    return {
        "final_status": result.get("decision_trace_final_status"),
        "final_action": result.get("decision_trace_final_action"),
        "steps": decision_trace,
    }


@agent_bp.post("/assistant/propose")
@require_tenant
@role_required(["Admin", "Super Admin"])
def assistant_propose():
    """Run agent at most once per scoped submission; persist; 303 → GET."""
    request_text = (request.form.get("request_text") or "").strip()
    submission_id = (request.form.get("submission_id") or "").strip() or mint_submission_id()
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

    memory_error = None
    past: list = []
    new_conversation = (request.form.get("new_conversation") or "").strip() in {
        "1",
        "true",
        "yes",
    }
    explicit_session_id = str(request.form.get("session_id") or "").strip() or None
    # Same submission retry must not remint session (new_conversation / empty start).
    prior_submission = submissions.get_submission(
        customer_id=customer_id,
        user_id=user_id,
        submission_id=submission_id,
    )
    prior_session_id = None
    if prior_submission is not None:
        prior_session_id = str(prior_submission.get("session_id") or "").strip() or None

    # Reject explicit session that disagrees with an existing reservation.
    if (
        prior_session_id
        and explicit_session_id
        and explicit_session_id != prior_session_id
    ):
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "submission_session_mismatch",
                    "message": (
                        "Bu submission başka bir konuşmaya bağlı. "
                        "Aynı submission_id ile farklı session_id kullanılamaz."
                    ),
                }
            ),
            400,
        )

    try:
        if prior_session_id:
            session_id = resolve_session_id(
                requested_session_id=prior_session_id,
                new_conversation=False,
                customer_id=customer_id,
                user_id=user_id,
                flask_session=session,
            )
        else:
            session_id = resolve_session_id(
                requested_session_id=explicit_session_id,
                new_conversation=new_conversation,
                customer_id=customer_id,
                user_id=user_id,
                flask_session=session,
            )
        conversation = load_flow_conversation(
            session_id=session_id,
            customer_id=customer_id,
            user_id=user_id,
            query=request_text,
        )
        past = list_agent_conversations(
            customer_id=customer_id, user_id=user_id, limit=10
        )
    except SessionIdentityError as exc:
        fresh = resolve_session_id(
            requested_session_id=None,
            new_conversation=True,
            customer_id=customer_id,
            user_id=user_id,
            flask_session=session,
        )
        payload = {
            "session_id": fresh,
            "submission_id": submission_id,
            "agent_notice": (
                "Bu konuşma kimliği sizin oturumunuza ait değil. "
                "Yeni konuşma açıldı — sorunuzu tekrar gönderin."
            ),
            "memory_error": f"conversation_identity_rejected ({exc.code})",
            "replayed": False,
        }
        remember_submission(session, submission_id=submission_id, payload=payload)
        return redirect_assistant(session_id=fresh, submission_id=submission_id)
    except MemoryReadError:
        current_app.logger.exception("agent_memory_pre_flow_failed")
        payload = {
            "session_id": None,
            "submission_id": submission_id,
            "agent_notice": "Konuşma belleği okunamadı; istek güvenli şekilde durduruldu.",
            "memory_error": "Memory read failure (no cross-tenant fallback).",
            "replayed": False,
        }
        remember_submission(session, submission_id=submission_id, payload=payload)
        return redirect_assistant(submission_id=submission_id)
    except Exception:
        current_app.logger.exception("agent_memory_pre_flow_failed")
        payload = {
            "session_id": None,
            "submission_id": submission_id,
            "agent_notice": "Konuşma belleği okunamadı; istek güvenli şekilde durduruldu.",
            "memory_error": "Memory read failure (no cross-tenant fallback).",
            "replayed": False,
        }
        remember_submission(session, submission_id=submission_id, payload=payload)
        return redirect_assistant(submission_id=submission_id)

    if not request_text:
        payload = {
            "session_id": session_id,
            "submission_id": submission_id,
            "agent_notice": "Boş soru gönderilmedi.",
            "replayed": False,
        }
        remember_submission(session, submission_id=submission_id, payload=payload)
        return redirect_assistant(
            session_id=session_id, submission_id=submission_id
        )

    # Unscoped hash for new/empty starts so concurrent first lookups share one key.
    request_hash = submissions.hash_for_reservation(
        request_text=request_text,
        new_conversation=new_conversation,
        explicit_session_id=explicit_session_id,
    )
    timeout_seconds = int(
        current_app.config.get("AGENT_SUBMISSION_TIMEOUT_SECONDS")
        or submissions.DEFAULT_PROCESSING_TIMEOUT_SECONDS
    )

    owned = submissions.try_begin_processing(
        customer_id=customer_id,
        user_id=user_id,
        submission_id=submission_id,
        session_id=session_id,
        request_hash=request_hash,
    )
    # Commit reservation before any LLM work so concurrent retries see the row.
    db.session.commit()

    if not owned:
        existing = submissions.get_submission(
            customer_id=customer_id,
            user_id=user_id,
            submission_id=submission_id,
        )
        if existing is None:
            payload = {
                "session_id": session_id,
                "submission_id": submission_id,
                "agent_notice": "Gönderim rezervasyonu okunamadı; lütfen yeni soru gönderin.",
                "replayed": False,
            }
            remember_submission(session, submission_id=submission_id, payload=payload)
            return redirect_assistant(
                session_id=session_id, submission_id=submission_id
            )

        canonical_session_id = (
            str(existing.get("session_id") or "").strip() or None
        )
        if (
            explicit_session_id
            and canonical_session_id
            and explicit_session_id != canonical_session_id
        ):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "submission_session_mismatch",
                        "message": (
                            "Bu submission başka bir konuşmaya bağlı. "
                            "Aynı submission_id ile farklı session_id kullanılamaz."
                        ),
                    }
                ),
                400,
            )

        if not submissions.hash_matches_stored(
            stored_hash=existing.get("request_hash"),
            request_text=request_text,
            new_conversation=new_conversation,
            canonical_session_id=canonical_session_id,
        ):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "submission_scope_mismatch",
                        "message": (
                            "Aynı submission_id farklı soru/konuşma ile yeniden "
                            "kullanılamaz. Yeni gönderim kimliği kullanın."
                        ),
                    }
                ),
                400,
            )

        # Rebind to the winner's canonical session (race / empty / new_conversation).
        if canonical_session_id and canonical_session_id != session_id:
            try:
                session_id = resolve_session_id(
                    requested_session_id=canonical_session_id,
                    new_conversation=False,
                    customer_id=customer_id,
                    user_id=user_id,
                    flask_session=session,
                )
            except (SessionIdentityError, MemoryReadError, Exception):
                session_id = canonical_session_id

        status_existing = str(existing.get("status") or "")
        if status_existing == "completed":
            prior = parse_submission_result(existing.get("result_json"))
            prior["replayed"] = True
            current_app.logger.info(
                "agent_propose_idempotent_hit submission_id=%s session_id=%s",
                submission_id,
                prior.get("session_id") or existing.get("session_id"),
            )
            remember_submission(session, submission_id=submission_id, payload=prior)
            return redirect_assistant(
                session_id=prior.get("session_id") or existing.get("session_id"),
                turn_id=prior.get("assistant_memory_id"),
                submission_id=submission_id,
            )

        if status_existing == "processing" and not submissions.is_processing_timed_out(
            existing, timeout_seconds=timeout_seconds
        ):
            payload = {
                "session_id": session_id,
                "submission_id": submission_id,
                "agent_notice": (
                    "Bu gönderim hâlâ işleniyor. Lütfen bekleyin; "
                    "otomatik yeniden çalıştırma yapılmaz."
                ),
                "replayed": True,
            }
            remember_submission(session, submission_id=submission_id, payload=payload)
            return redirect_assistant(
                session_id=session_id, submission_id=submission_id
            )

        # timed-out processing or failed — no auto-rerun
        payload = {
            "session_id": session_id,
            "submission_id": submission_id,
            "agent_notice": (
                "Önceki gönderim zaman aşımına uğradı veya başarısız oldu. "
                "Yeniden denemek için yeni bir soru gönderin (yeni submission_id)."
            ),
            "memory_error": existing.get("error"),
            "replayed": True,
        }
        remember_submission(session, submission_id=submission_id, payload=payload)
        return redirect_assistant(
            session_id=session_id, submission_id=submission_id
        )
    flow_events: list[dict] = []

    def on_event(payload_event):
        flow_events.append(sanitize_flow_event(payload_event))

    try:
        result = run_knowledge_agent(
            request_text,
            conversation=conversation,
            config=current_app.config,
            on_event=on_event,
        )
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("agent_flow_crashed")
        submissions.mark_failed(
            customer_id=customer_id,
            user_id=user_id,
            submission_id=submission_id,
            error=type(exc).__name__,
        )
        db.session.commit()
        payload = {
            "session_id": session_id,
            "submission_id": submission_id,
            "agent_notice": f"Agent error: {type(exc).__name__}",
            "replayed": False,
        }
        remember_submission(session, submission_id=submission_id, payload=payload)
        return redirect_assistant(
            session_id=session_id, submission_id=submission_id
        )

    agent_reply = None
    agent_notice = None
    status = result.get("status")
    decision = result.get("decision") if isinstance(result.get("decision"), dict) else {}
    if status == "ANSWER":
        agent_reply = decision.get("answer")
    elif status == "CLARIFY":
        agent_notice = decision.get("question")
    elif status == "STOP_INCOMPLETE":
        agent_notice = decision.get("reason")
    elif status == "step_limit":
        agent_notice = (
            decision.get("reason")
            if isinstance(decision, dict) and decision.get("reason")
            else "Adım sınırına ulaşıldı; mevcut gözlemlerle tamamlanamadı."
        )
        current_app.logger.warning(
            "agent_flow_error status=%s stage=%s error_class=%s error=%s",
            status,
            result.get("stage"),
            result.get("error_class"),
            result.get("error"),
        )
    else:
        current_app.logger.warning(
            "agent_flow_error status=%s stage=%s error_class=%s error=%s",
            status,
            result.get("stage"),
            result.get("error_class"),
            result.get("error"),
        )
        detail = result.get("error") or result.get("error_class") or status
        agent_notice = f"Agent error: {detail}"

    assistant_text = agent_reply or agent_notice
    flow_timeline = present_flow_timeline(flow_events)
    decision_trace = pack_decision_trace(result if isinstance(result, dict) else {})
    persist_result: dict = {}
    try:
        persist_result = persist_turn(
            session_id=session_id,
            customer_id=customer_id,
            user_id=user_id,
            user_text=request_text,
            flow_status=str(status) if status is not None else None,
            assistant_text=assistant_text,
            metadata={
                "flow_status": status,
                "submission_id": submission_id,
                "flow_timeline": flow_timeline,
                "decision_trace": decision_trace,
            },
        )
        if not persist_result.get("complete"):
            memory_error = "Konuşma kısmen kaydedildi; asistan yanıtı yazılamadı."
        past = list_agent_conversations(
            customer_id=customer_id, user_id=user_id, limit=10
        )
    except MemoryPersistIncompleteError as exc:
        current_app.logger.exception("agent_memory_persist_incomplete")
        memory_error = (
            "Kullanıcı mesajı kaydedilmiş olabilir ancak asistan yanıtı yazılamadı "
            f"(user_memory_id={exc.user_memory_id})."
        )
    except Exception:
        current_app.logger.exception("agent_memory_persist_failed")
        memory_error = "Yanıt üretildi ancak bellek yazılamadı."

    # Persist reply on the submission even if conversation memory write fails,
    # so a completed reservation can replay without re-running the LLM.
    payload = {
        "session_id": session_id,
        "submission_id": submission_id,
        "assistant_memory_id": persist_result.get("assistant_memory_id"),
        "user_memory_id": persist_result.get("user_memory_id"),
        "memory_error": memory_error,
        "flow_status": status,
        "assistant_text": assistant_text,
        "agent_reply": agent_reply,
        "agent_notice": agent_notice or (
            assistant_text if status not in {"ANSWER", "CLARIFY"} else None
        ),
        "replayed": False,
        "past_count": len(past),
    }
    submissions.mark_completed(
        customer_id=customer_id,
        user_id=user_id,
        submission_id=submission_id,
        result_payload=payload,
    )
    db.session.commit()
    remember_submission(session, submission_id=submission_id, payload=payload)
    return redirect_assistant(
        session_id=session_id,
        turn_id=persist_result.get("assistant_memory_id"),
        submission_id=submission_id,
    )
