"""Aira Intelligence Assistant HTTP — Knowledge Agent Flow ownership.

GET /assistant renders conversation (no agent).
POST /assistant/propose runs agent once (idempotent), persists, then 303 → GET.
Memory policy/SQL lives in ``flow/memory`` + AiraCoder memory_service.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.adapters.db.agents.models.base import db
from app.adapters.db.agents.repositories import submission_repository as submissions
from app.core.security import require_tenant, role_required
from app.domain.agents.flow.memory import (
    AGENT_PAGE_TYPE,
    MemoryPersistIncompleteError,
    MemoryReadError,
    SessionIdentityError,
    list_agent_conversations,
    load_flow_conversation,
    load_turn_trace,
    load_ui_transcript,
    persist_turn,
    resolve_session_id,
)
from app.domain.agents.flow.execution.run_knowledge_agent import (
    run_knowledge_agent,
)
from app.interfaces.web.agent_routes.submission_store import (
    clear_last_ui,
    mint_submission_id,
    pop_last_ui_for_session,
    remember_submission,
)
from app.interfaces.web.agent_routes.timeline_present import (
    present_flow_timeline,
    sanitize_flow_event,
)

AGENT_HISTORY_PAGE = 15
AGENT_HISTORY_MAX = 50


def _history_window(offset: int, limit: int) -> tuple[int, int]:
    """Clamp a scroll page so the sidebar never exceeds AGENT_HISTORY_MAX."""
    try:
        offset_n = max(0, int(offset))
    except (TypeError, ValueError):
        offset_n = 0
    try:
        limit_n = int(limit)
    except (TypeError, ValueError):
        limit_n = AGENT_HISTORY_PAGE
    offset_n = min(offset_n, AGENT_HISTORY_MAX)
    if offset_n >= AGENT_HISTORY_MAX:
        return offset_n, 0
    limit_n = max(1, min(limit_n, AGENT_HISTORY_PAGE))
    limit_n = min(limit_n, AGENT_HISTORY_MAX - offset_n)
    return offset_n, limit_n


agent_bp = Blueprint(
    "agent",
    __name__,
    template_folder="../templates",
)


_CANONICAL_DECIMAL_ID = re.compile(r"^[1-9][0-9]*$")


def _strict_tenant_id(value: Any) -> int | None:
    """Accept positive int or lossless canonical decimal string only.

    ``@require_tenant`` sets ``g.user_id`` / ``g.customer_id`` from
    ``require_tenant_context()`` only when both values are ``int``. Boolean is
    rejected here because ``isinstance(True, int)`` is true in Python. Floats
    and lossy coercions (e.g. 1010.9 → 1010) are never accepted.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not _CANONICAL_DECIMAL_ID.fullmatch(text):
            return None
        return int(text)
    return None


def _tenant_ids() -> tuple[int | None, int | None]:
    return (
        _strict_tenant_id(getattr(g, "customer_id", None)),
        _strict_tenant_id(getattr(g, "user_id", None)),
    )


def _redirect_assistant(
    *,
    session_id: str | None = None,
    new: bool = False,
    turn_id: int | str | None = None,
    submission_id: str | None = None,
):
    """303 See Other — browser refresh becomes GET, not form resubmit."""
    if new:
        return redirect(url_for("agent.assistant", new=1), code=303)
    kwargs: dict = {}
    if session_id:
        kwargs["session_id"] = session_id
    if turn_id is not None and str(turn_id).strip():
        kwargs["turn_id"] = turn_id
    if submission_id and str(submission_id).strip():
        kwargs["submission_id"] = str(submission_id).strip()
    if kwargs:
        return redirect(url_for("agent.assistant", **kwargs), code=303)
    return redirect(url_for("agent.assistant"), code=303)


def _parse_submission_result(raw: object) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}
    return dict(raw) if isinstance(raw, dict) else {}


def _display_from_submission_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Map server-side submission result to GET render fields (no cookie)."""
    flow_status = payload.get("flow_status")
    agent_reply = payload.get("agent_reply")
    assistant_text = payload.get("assistant_text")
    agent_notice = payload.get("agent_notice")
    if not agent_reply and flow_status == "ANSWER" and assistant_text:
        agent_reply = assistant_text
    if not agent_notice and flow_status not in {"ANSWER", "CLARIFY"} and assistant_text:
        agent_notice = assistant_text
    return {
        "agent_reply": agent_reply,
        "agent_notice": agent_notice,
        "memory_error": payload.get("memory_error"),
        "assistant_memory_id": payload.get("assistant_memory_id"),
        "session_id": payload.get("session_id"),
        "flow_status": flow_status,
    }


def _turns_include_assistant_text(turns: list, text: str | None) -> bool:
    needle = str(text or "").strip()
    if not needle:
        return False
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        if str(turn.get("role") or "").lower() != "assistant":
            continue
        if str(turn.get("content") or "").strip() == needle:
            return True
    return False


def _overlay_submission_reply(turns: list, *, agent_reply: str | None) -> list:
    """If persist failed, transcript may lack the answer — append for display."""
    reply = str(agent_reply or "").strip()
    if not reply or _turns_include_assistant_text(turns, reply):
        return turns
    out = list(turns)
    out.append({"role": "assistant", "content": reply, "from_submission": True})
    return out


def _render_assistant(
    *,
    request_text: str = "",
    agent_reply=None,
    agent_notice=None,
    flow_events=None,
    flow_timeline=None,
    decision_trace=None,
    session_id: str | None = None,
    conversation_turns=None,
    past_conversations=None,
    memory_error: str | None = None,
    submission_id: str | None = None,
    selected_turn_id=None,
):
    return render_template(
        "assistant.html",
        request_text=request_text,
        agent_reply=agent_reply,
        agent_notice=agent_notice,
        flow_events=flow_events,
        flow_timeline=flow_timeline,
        decision_trace=decision_trace,
        session_id=session_id,
        conversation_turns=conversation_turns or [],
        past_conversations=past_conversations or [],
        history_page_size=AGENT_HISTORY_PAGE,
        history_max=AGENT_HISTORY_MAX,
        history_has_more=len(past_conversations or []) >= AGENT_HISTORY_PAGE,
        memory_error=memory_error,
        submission_id=submission_id or mint_submission_id(),
        selected_turn_id=selected_turn_id,
        page_type=AGENT_PAGE_TYPE,
    )


def _pack_decision_trace(result: dict) -> dict | None:
    decision_trace = result.get("decision_trace")
    if not isinstance(decision_trace, list):
        return None
    return {
        "final_status": result.get("decision_trace_final_status"),
        "final_action": result.get("decision_trace_final_action"),
        "steps": decision_trace,
    }


@agent_bp.get("/")
@require_tenant
@role_required(["Admin", "Super Admin"])
def home():
    """Native landing page — status + links into the agent workspace."""
    return render_template(
        "home.html",
        ollama_model=current_app.config.get("KNOWLEDGE_FLOW_LLM_MODEL")
        or "qwen3.5:9b",
    )


@agent_bp.get("/assistant")
@require_tenant
@role_required(["Admin", "Super Admin"])
def assistant():
    """Load conversation transcript + turn-bound Flow trace. Never runs the agent."""
    customer_id, user_id = _tenant_ids()
    memory_error = None
    session_id = None
    turns: list = []
    past: list = []
    flow_timeline = None
    decision_trace = None
    selected_turn_id = None
    agent_reply = None
    agent_notice = None
    new_conversation = (request.args.get("new") or "").strip() in {"1", "true", "yes"}
    requested_turn = (request.args.get("turn_id") or "").strip() or None
    requested_submission = (request.args.get("submission_id") or "").strip() or None

    if new_conversation:
        clear_last_ui(session)

    # Full answers come from tenant-scoped agent_submissions, never the cookie.
    submission_display: dict[str, Any] = {}
    if customer_id and user_id and requested_submission:
        row = submissions.get_submission(
            customer_id=customer_id,
            user_id=user_id,
            submission_id=requested_submission,
        )
        if row:
            status_row = str(row.get("status") or "")
            if status_row == "completed":
                submission_display = _display_from_submission_payload(
                    _parse_submission_result(row.get("result_json"))
                )
            elif status_row == "processing":
                submission_display = {
                    "session_id": row.get("session_id"),
                    "agent_notice": (
                        "Bu gönderim hâlâ işleniyor. Lütfen bekleyin; "
                        "otomatik yeniden çalıştırma yapılmaz."
                    ),
                }
            elif status_row == "failed":
                submission_display = {
                    "session_id": row.get("session_id"),
                    "agent_notice": (
                        "Önceki gönderim zaman aşımına uğradı veya başarısız oldu. "
                        "Yeniden denemek için yeni bir soru gönderin (yeni submission_id)."
                    ),
                    "memory_error": row.get("error"),
                }

    if customer_id and user_id:
        try:
            # Prefer session bound to the completed submission when present.
            requested_session = request.args.get("session_id") or submission_display.get(
                "session_id"
            )
            session_id = resolve_session_id(
                requested_session_id=requested_session,
                new_conversation=new_conversation,
                customer_id=customer_id,
                user_id=user_id,
                flask_session=session,
            )
            turns = load_ui_transcript(
                session_id=session_id, customer_id=customer_id, user_id=user_id
            )
            past = list_agent_conversations(
                customer_id=customer_id,
                user_id=user_id,
                limit=AGENT_HISTORY_PAGE,
                offset=0,
            )
            last_ui = pop_last_ui_for_session(session, session_id) or {}
            if submission_display.get("memory_error"):
                memory_error = submission_display.get("memory_error")
            elif last_ui.get("memory_error") and not memory_error:
                memory_error = last_ui.get("memory_error")
            agent_reply = submission_display.get("agent_reply")
            agent_notice = submission_display.get("agent_notice")
            if not agent_notice and last_ui.get("agent_notice"):
                agent_notice = last_ui.get("agent_notice")
            turns = _overlay_submission_reply(turns, agent_reply=agent_reply)
            turn_ref = (
                requested_turn
                or submission_display.get("assistant_memory_id")
                or last_ui.get("assistant_memory_id")
            )
            overlay = load_turn_trace(
                session_id=session_id,
                customer_id=customer_id,
                user_id=user_id,
                turn_id=turn_ref,
            )
            if overlay and overlay.get("has_trace"):
                flow_timeline = overlay.get("flow_timeline")
                decision_trace = overlay.get("decision_trace")
                selected_turn_id = overlay.get("turn_id")
        except SessionIdentityError as exc:
            memory_error = f"Konuşma kimliği reddedildi ({exc.code})."
            session_id = None
            agent_reply = submission_display.get("agent_reply")
            agent_notice = submission_display.get("agent_notice")
            if submission_display.get("memory_error"):
                memory_error = submission_display.get("memory_error")
        except MemoryReadError:
            current_app.logger.exception("agent_memory_load_failed")
            memory_error = "Konuşma belleği okunamadı. Başka oturuma düşülmedi."
            agent_reply = submission_display.get("agent_reply")
            agent_notice = submission_display.get("agent_notice")
            if submission_display.get("memory_error"):
                memory_error = submission_display.get("memory_error")
        except Exception:
            current_app.logger.exception("agent_memory_load_failed")
            memory_error = "Konuşma belleği okunamadı. Başka oturuma düşülmedi."
            agent_reply = submission_display.get("agent_reply")
            agent_notice = submission_display.get("agent_notice")
    else:
        last_ui = pop_last_ui_for_session(session, None) or {}
        if last_ui.get("memory_error") and not memory_error:
            memory_error = last_ui.get("memory_error")

    return _render_assistant(
        request_text="",
        agent_reply=agent_reply,
        agent_notice=agent_notice,
        session_id=session_id,
        conversation_turns=turns,
        past_conversations=past,
        memory_error=memory_error,
        flow_timeline=flow_timeline,
        decision_trace=decision_trace,
        selected_turn_id=selected_turn_id,
        submission_id=mint_submission_id(),
    )


@agent_bp.get("/assistant/conversations")
@require_tenant
@role_required(["Admin", "Super Admin"])
def assistant_conversations():
    """Next sidebar page. Total cap is AGENT_HISTORY_MAX; caller scrolls to load."""
    customer_id, user_id = _tenant_ids()
    offset, limit = _history_window(
        request.args.get("offset") or 0,
        request.args.get("limit") or AGENT_HISTORY_PAGE,
    )
    if not customer_id or not user_id or limit == 0:
        return jsonify({"items": [], "next_offset": offset, "has_more": False})
    rows = list_agent_conversations(
        customer_id=customer_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    items = [
        {
            "session_id": row.get("session_id"),
            "title": row.get("title") or "",
            "last_message_at": row.get("last_message_at") or "",
            "href": url_for("agent.assistant", session_id=row.get("session_id")),
        }
        for row in rows
        if row.get("session_id")
    ]
    next_offset = offset + len(items)
    has_more = len(items) == limit and next_offset < AGENT_HISTORY_MAX
    return jsonify({"items": items, "next_offset": next_offset, "has_more": has_more})


@agent_bp.post("/assistant/propose")
@require_tenant
@role_required(["Admin", "Super Admin"])
def assistant_propose():
    """Run agent at most once per scoped submission; persist; 303 → GET."""
    request_text = (request.form.get("request_text") or "").strip()
    submission_id = (request.form.get("submission_id") or "").strip() or mint_submission_id()
    customer_id, user_id = _tenant_ids()

    if not customer_id or not user_id:
        payload = {
            "session_id": None,
            "agent_notice": "Yetkili kullanıcı/tenant bağlamı çözülemedi.",
            "memory_error": "Kimlik eksik; bellek kullanılmadı.",
            "replayed": False,
        }
        remember_submission(session, submission_id=submission_id, payload=payload)
        return _redirect_assistant()

    memory_error = None
    past: list = []
    new_conversation = (request.form.get("new_conversation") or "").strip() in {
        "1",
        "true",
        "yes",
    }
    # Same submission retry must not remint session (new_conversation / empty start).
    prior_submission = submissions.get_submission(
        customer_id=customer_id,
        user_id=user_id,
        submission_id=submission_id,
    )
    prior_session_id = None
    if prior_submission is not None:
        prior_session_id = str(prior_submission.get("session_id") or "").strip() or None

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
                requested_session_id=request.form.get("session_id"),
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
        return _redirect_assistant(session_id=fresh, submission_id=submission_id)
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
        return _redirect_assistant(submission_id=submission_id)
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
        return _redirect_assistant(submission_id=submission_id)

    if not request_text:
        payload = {
            "session_id": session_id,
            "submission_id": submission_id,
            "agent_notice": "Boş soru gönderilmedi.",
            "replayed": False,
        }
        remember_submission(session, submission_id=submission_id, payload=payload)
        return _redirect_assistant(
            session_id=session_id, submission_id=submission_id
        )

    # Hash uses the reserved session when replaying so new_conversation remints
    # and empty-session retries stay stable against the real resolver.
    hash_session_id = prior_session_id or session_id
    request_hash = submissions.hash_request(
        request_text=request_text,
        session_id=hash_session_id,
        new_conversation=new_conversation,
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
            return _redirect_assistant(
                session_id=session_id, submission_id=submission_id
            )

        if str(existing.get("request_hash") or "") != request_hash:
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

        status_existing = str(existing.get("status") or "")
        if status_existing == "completed":
            prior = _parse_submission_result(existing.get("result_json"))
            prior["replayed"] = True
            current_app.logger.info(
                "agent_propose_idempotent_hit submission_id=%s session_id=%s",
                submission_id,
                prior.get("session_id") or existing.get("session_id"),
            )
            remember_submission(session, submission_id=submission_id, payload=prior)
            return _redirect_assistant(
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
            return _redirect_assistant(
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
        return _redirect_assistant(
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
        return _redirect_assistant(
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
    decision_trace = _pack_decision_trace(result if isinstance(result, dict) else {})
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
    return _redirect_assistant(
        session_id=session_id,
        turn_id=persist_result.get("assistant_memory_id"),
        submission_id=submission_id,
    )
