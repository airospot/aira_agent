"""GET / and GET /assistant — render conversation; never runs the agent."""

from __future__ import annotations

from typing import Any

from flask import current_app, redirect, render_template, request, session, url_for

from app.adapters.db.agents.repositories import submission_repository as submissions
from app.core.security import require_tenant, role_required
from app.domain.agents.flow.memory import (
    AGENT_PAGE_TYPE,
    MemoryReadError,
    SessionIdentityError,
    list_agent_conversations,
    load_turn_trace,
    load_ui_transcript,
    resolve_session_id,
)
from app.interfaces.web.agent_routes.blueprint import agent_bp
from app.interfaces.web.agent_routes.conversations import (
    AGENT_HISTORY_MAX,
    AGENT_HISTORY_PAGE,
)
from app.interfaces.web.agent_routes.submission_display import (
    overlay_submission_reply,
    submission_display_if_session_matches,
)
from app.interfaces.web.agent_routes.submission_store import (
    clear_last_ui,
    mint_submission_id,
    pop_last_ui_for_session,
)
from app.interfaces.web.agent_routes.tenant import tenant_ids


def redirect_assistant(
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


def render_assistant(
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
    customer_id, user_id = tenant_ids()
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
    # new=1 must not carry a previous submission answer into a fresh conversation.
    requested_submission = None
    if not new_conversation:
        requested_submission = (request.args.get("submission_id") or "").strip() or None

    if new_conversation:
        clear_last_ui(session)

    submission_row = None
    if customer_id and user_id and requested_submission:
        submission_row = submissions.get_submission(
            customer_id=customer_id,
            user_id=user_id,
            submission_id=requested_submission,
        )

    if customer_id and user_id:
        # 1) Ownership / resolve — failure here must not show a recovery answer.
        try:
            requested_session = request.args.get("session_id")
            if not requested_session and submission_row is not None:
                requested_session = (
                    str(submission_row.get("session_id") or "").strip() or None
                )
            session_id = resolve_session_id(
                requested_session_id=requested_session,
                new_conversation=new_conversation,
                customer_id=customer_id,
                user_id=user_id,
                flask_session=session,
            )
        except SessionIdentityError as exc:
            memory_error = f"Konuşma kimliği reddedildi ({exc.code})."
            session_id = None
        except MemoryReadError:
            current_app.logger.exception("agent_session_resolve_failed")
            memory_error = "Konuşma belleği okunamadı. Başka oturuma düşülmedi."
            session_id = None
        except Exception:
            current_app.logger.exception("agent_session_resolve_failed")
            memory_error = "Konuşma belleği okunamadı. Başka oturuma düşülmedi."
            session_id = None

        # 2) After successful resolve + session match, prepare server recovery
        #    answer before transcript/list reads (those may fail independently).
        submission_display: dict[str, Any] = {}
        if session_id:
            submission_display = submission_display_if_session_matches(
                submission_row, selected_session_id=session_id
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

            def _note_memory_read_failure() -> None:
                nonlocal memory_error
                read_err = "Konuşma belleği okunamadı. Başka oturuma düşülmedi."
                if memory_error and read_err not in str(memory_error):
                    memory_error = f"{memory_error} | {read_err}"
                else:
                    memory_error = memory_error or read_err

            try:
                turns = load_ui_transcript(
                    session_id=session_id, customer_id=customer_id, user_id=user_id
                )
            except MemoryReadError:
                current_app.logger.exception("agent_transcript_load_failed")
                _note_memory_read_failure()
                turns = []
            except Exception:
                current_app.logger.exception("agent_transcript_load_failed")
                _note_memory_read_failure()
                turns = []

            try:
                past = list_agent_conversations(
                    customer_id=customer_id,
                    user_id=user_id,
                    limit=AGENT_HISTORY_PAGE,
                    offset=0,
                )
            except MemoryReadError:
                current_app.logger.exception("agent_conversation_list_failed")
                _note_memory_read_failure()
                past = []
            except Exception:
                current_app.logger.exception("agent_conversation_list_failed")
                _note_memory_read_failure()
                past = []

            turns = overlay_submission_reply(turns, agent_reply=agent_reply)
            turn_ref = (
                requested_turn
                or submission_display.get("assistant_memory_id")
                or last_ui.get("assistant_memory_id")
            )
            try:
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
            except Exception:
                current_app.logger.exception("agent_turn_trace_load_failed")
    else:
        last_ui = pop_last_ui_for_session(session, None) or {}
        if last_ui.get("memory_error") and not memory_error:
            memory_error = last_ui.get("memory_error")

    return render_assistant(
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
