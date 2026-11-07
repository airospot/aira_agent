"""AgentRunService — propose run orchestration without Flask/HTTP."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Mapping, Protocol

from app.domain.agents.flow.memory import (
    MemoryPersistIncompleteError,
    MemoryReadError,
    SessionIdentityError,
)
from app.domain.agents.run.contracts import ExecutionContext, RunOutcome, RunRequest

logger = logging.getLogger(__name__)


def _parse_submission_result(raw: object) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}
    return dict(raw) if isinstance(raw, dict) else {}


def _identity_timeline(events: list) -> list:
    return list(events or [])


def _identity_event(payload_event: Any) -> dict:
    return dict(payload_event) if isinstance(payload_event, Mapping) else {}


class MemoryPort(Protocol):
    last_agent_session_id: str | None

    def resolve_session_id(
        self,
        *,
        requested_session_id: str | None,
        new_conversation: bool,
        customer_id: int,
        user_id: int,
        agent_session_id_hint: str | None = None,
    ) -> str: ...

    def load_flow_conversation(
        self,
        *,
        session_id: str,
        customer_id: int,
        user_id: int,
        query: str,
    ) -> Any: ...

    def list_agent_conversations(
        self, *, customer_id: int, user_id: int, limit: int = 10
    ) -> list: ...

    def persist_turn(self, **kwargs: Any) -> dict[str, Any]: ...


class SubmissionPort(Protocol):
    def get_submission(
        self, *, customer_id: int, user_id: int, submission_id: str
    ) -> dict[str, Any] | None: ...

    def hash_for_reservation(
        self,
        *,
        request_text: str,
        new_conversation: bool,
        explicit_session_id: str | None,
    ) -> str: ...

    def try_begin_processing(
        self,
        *,
        customer_id: int,
        user_id: int,
        submission_id: str,
        session_id: str | None,
        request_hash: str,
    ) -> bool: ...

    def commit(self) -> None: ...

    def hash_matches_stored(
        self,
        *,
        stored_hash: str | None,
        request_text: str,
        new_conversation: bool,
        canonical_session_id: str | None,
    ) -> bool: ...

    def is_processing_timed_out(
        self, row: Mapping[str, Any], *, timeout_seconds: int
    ) -> bool: ...

    def mark_failed(
        self, *, customer_id: int, user_id: int, submission_id: str, error: str
    ) -> None: ...

    def mark_completed(
        self,
        *,
        customer_id: int,
        user_id: int,
        submission_id: str,
        result_payload: Mapping[str, Any],
    ) -> None: ...


Runner = Callable[..., dict[str, Any]]


def pack_decision_trace(result: dict) -> dict | None:
    decision_trace = result.get("decision_trace")
    if not isinstance(decision_trace, list):
        return None
    return {
        "final_status": result.get("decision_trace_final_status"),
        "final_action": result.get("decision_trace_final_action"),
        "steps": decision_trace,
    }


class AgentRunService:
    def __init__(
        self,
        *,
        memory: MemoryPort,
        submissions: SubmissionPort,
        runner: Runner,
        present_timeline: Callable[[list], Any] | None = None,
        sanitize_event: Callable[[Any], dict] | None = None,
    ) -> None:
        self._memory = memory
        self._submissions = submissions
        self._runner = runner
        self._present_timeline = present_timeline or _identity_timeline
        self._sanitize_event = sanitize_event or _identity_event

    def run(self, ctx: ExecutionContext, req: RunRequest) -> RunOutcome:
        customer_id = ctx.customer_id
        user_id = ctx.user_id
        submission_id = str(req.submission_id or "").strip()
        request_text = str(req.request_text or "").strip()
        new_conversation = bool(req.new_conversation)
        explicit_session_id = str(req.explicit_session_id or "").strip() or None
        hint = str(req.agent_session_id_hint or "").strip() or None

        prior_submission = self._submissions.get_submission(
            customer_id=customer_id,
            user_id=user_id,
            submission_id=submission_id,
        )
        prior_session_id = None
        if prior_submission is not None:
            prior_session_id = (
                str(prior_submission.get("session_id") or "").strip() or None
            )

        if (
            prior_session_id
            and explicit_session_id
            and explicit_session_id != prior_session_id
        ):
            return RunOutcome(
                kind="session_mismatch",
                submission_id=submission_id,
                http_status=400,
                error="submission_session_mismatch",
                message=(
                    "Bu submission başka bir konuşmaya bağlı. "
                    "Aynı submission_id ile farklı session_id kullanılamaz."
                ),
            )

        try:
            if prior_session_id:
                session_id = self._memory.resolve_session_id(
                    requested_session_id=prior_session_id,
                    new_conversation=False,
                    customer_id=customer_id,
                    user_id=user_id,
                    agent_session_id_hint=hint,
                )
            else:
                session_id = self._memory.resolve_session_id(
                    requested_session_id=explicit_session_id,
                    new_conversation=new_conversation,
                    customer_id=customer_id,
                    user_id=user_id,
                    agent_session_id_hint=hint,
                )
            conversation = self._memory.load_flow_conversation(
                session_id=session_id,
                customer_id=customer_id,
                user_id=user_id,
                query=request_text,
            )
            past = self._memory.list_agent_conversations(
                customer_id=customer_id, user_id=user_id, limit=10
            )
        except SessionIdentityError as exc:
            fresh = self._memory.resolve_session_id(
                requested_session_id=None,
                new_conversation=True,
                customer_id=customer_id,
                user_id=user_id,
                agent_session_id_hint=None,
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
            return self._outcome(
                "identity_rejected",
                submission_id=submission_id,
                session_id=fresh,
                payload=payload,
            )
        except MemoryReadError:
            logger.exception("agent_memory_pre_flow_failed")
            payload = {
                "session_id": None,
                "submission_id": submission_id,
                "agent_notice": (
                    "Konuşma belleği okunamadı; istek güvenli şekilde durduruldu."
                ),
                "memory_error": "Memory read failure (no cross-tenant fallback).",
                "replayed": False,
            }
            return self._outcome(
                "memory_read_error",
                submission_id=submission_id,
                payload=payload,
            )
        except Exception:
            logger.exception("agent_memory_pre_flow_failed")
            payload = {
                "session_id": None,
                "submission_id": submission_id,
                "agent_notice": (
                    "Konuşma belleği okunamadı; istek güvenli şekilde durduruldu."
                ),
                "memory_error": "Memory read failure (no cross-tenant fallback).",
                "replayed": False,
            }
            return self._outcome(
                "memory_read_error",
                submission_id=submission_id,
                payload=payload,
            )

        if not request_text:
            payload = {
                "session_id": session_id,
                "submission_id": submission_id,
                "agent_notice": "Boş soru gönderilmedi.",
                "replayed": False,
            }
            return self._outcome(
                "empty_question",
                submission_id=submission_id,
                session_id=session_id,
                payload=payload,
            )

        request_hash = self._submissions.hash_for_reservation(
            request_text=request_text,
            new_conversation=new_conversation,
            explicit_session_id=explicit_session_id,
        )
        owned = self._submissions.try_begin_processing(
            customer_id=customer_id,
            user_id=user_id,
            submission_id=submission_id,
            session_id=session_id,
            request_hash=request_hash,
        )
        # Commit reservation before any LLM work so concurrent retries see the row.
        self._submissions.commit()

        if not owned:
            return self._handle_non_owner(
                ctx=ctx,
                req=req,
                session_id=session_id,
                explicit_session_id=explicit_session_id,
                new_conversation=new_conversation,
                request_text=request_text,
                hint=hint,
            )

        return self._run_owned(
            ctx=ctx,
            req=req,
            session_id=session_id,
            conversation=conversation,
            past=past,
            request_text=request_text,
        )

    def _handle_non_owner(
        self,
        *,
        ctx: ExecutionContext,
        req: RunRequest,
        session_id: str,
        explicit_session_id: str | None,
        new_conversation: bool,
        request_text: str,
        hint: str | None,
    ) -> RunOutcome:
        submission_id = req.submission_id
        customer_id = ctx.customer_id
        user_id = ctx.user_id
        existing = self._submissions.get_submission(
            customer_id=customer_id,
            user_id=user_id,
            submission_id=submission_id,
        )
        if existing is None:
            payload = {
                "session_id": session_id,
                "submission_id": submission_id,
                "agent_notice": (
                    "Gönderim rezervasyonu okunamadı; lütfen yeni soru gönderin."
                ),
                "replayed": False,
            }
            return self._outcome(
                "reservation_lost",
                submission_id=submission_id,
                session_id=session_id,
                payload=payload,
            )

        canonical_session_id = str(existing.get("session_id") or "").strip() or None
        if (
            explicit_session_id
            and canonical_session_id
            and explicit_session_id != canonical_session_id
        ):
            return RunOutcome(
                kind="session_mismatch",
                submission_id=submission_id,
                http_status=400,
                error="submission_session_mismatch",
                message=(
                    "Bu submission başka bir konuşmaya bağlı. "
                    "Aynı submission_id ile farklı session_id kullanılamaz."
                ),
            )

        if not self._submissions.hash_matches_stored(
            stored_hash=existing.get("request_hash"),
            request_text=request_text,
            new_conversation=new_conversation,
            canonical_session_id=canonical_session_id,
        ):
            return RunOutcome(
                kind="scope_mismatch",
                submission_id=submission_id,
                http_status=400,
                error="submission_scope_mismatch",
                message=(
                    "Aynı submission_id farklı soru/konuşma ile yeniden "
                    "kullanılamaz. Yeni gönderim kimliği kullanın."
                ),
            )

        if canonical_session_id and canonical_session_id != session_id:
            try:
                session_id = self._memory.resolve_session_id(
                    requested_session_id=canonical_session_id,
                    new_conversation=False,
                    customer_id=customer_id,
                    user_id=user_id,
                    agent_session_id_hint=hint,
                )
            except (SessionIdentityError, MemoryReadError, Exception):
                session_id = canonical_session_id

        status_existing = str(existing.get("status") or "")
        if status_existing == "completed":
            prior = dict(_parse_submission_result(existing.get("result_json")))
            prior["replayed"] = True
            logger.info(
                "agent_propose_idempotent_hit submission_id=%s session_id=%s",
                submission_id,
                prior.get("session_id") or existing.get("session_id"),
            )
            return self._outcome(
                "replayed",
                submission_id=submission_id,
                session_id=prior.get("session_id") or existing.get("session_id"),
                turn_id=prior.get("assistant_memory_id"),
                payload=prior,
            )

        if status_existing == "processing" and not self._submissions.is_processing_timed_out(
            existing, timeout_seconds=ctx.submission_timeout_seconds
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
            return self._outcome(
                "processing",
                submission_id=submission_id,
                session_id=session_id,
                payload=payload,
            )

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
        return self._outcome(
            "failed_prior",
            submission_id=submission_id,
            session_id=session_id,
            payload=payload,
        )

    def _run_owned(
        self,
        *,
        ctx: ExecutionContext,
        req: RunRequest,
        session_id: str,
        conversation: Any,
        past: list,
        request_text: str,
    ) -> RunOutcome:
        submission_id = req.submission_id
        customer_id = ctx.customer_id
        user_id = ctx.user_id
        memory_error = None
        flow_events: list[dict] = []

        def on_event(payload_event: Any) -> None:
            flow_events.append(self._sanitize_event(payload_event))

        try:
            result = self._runner(
                request_text,
                conversation=conversation,
                config=dict(ctx.runner_config),
                on_event=on_event,
                permitted_tool_names=ctx.permitted_tool_names,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("agent_flow_crashed")
            self._submissions.mark_failed(
                customer_id=customer_id,
                user_id=user_id,
                submission_id=submission_id,
                error=type(exc).__name__,
            )
            self._submissions.commit()
            payload = {
                "session_id": session_id,
                "submission_id": submission_id,
                "agent_notice": f"Agent error: {type(exc).__name__}",
                "replayed": False,
            }
            return self._outcome(
                "agent_error",
                submission_id=submission_id,
                session_id=session_id,
                payload=payload,
            )

        agent_reply = None
        agent_notice = None
        status = result.get("status")
        decision = (
            result.get("decision") if isinstance(result.get("decision"), dict) else {}
        )
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
            logger.warning(
                "agent_flow_error status=%s stage=%s error_class=%s error=%s",
                status,
                result.get("stage"),
                result.get("error_class"),
                result.get("error"),
            )
        else:
            logger.warning(
                "agent_flow_error status=%s stage=%s error_class=%s error=%s",
                status,
                result.get("stage"),
                result.get("error_class"),
                result.get("error"),
            )
            detail = result.get("error") or result.get("error_class") or status
            agent_notice = f"Agent error: {detail}"

        assistant_text = agent_reply or agent_notice
        flow_timeline = self._present_timeline(flow_events)
        decision_trace = pack_decision_trace(result if isinstance(result, dict) else {})
        persist_result: dict = {}
        try:
            persist_result = self._memory.persist_turn(
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
            past = self._memory.list_agent_conversations(
                customer_id=customer_id, user_id=user_id, limit=10
            )
        except MemoryPersistIncompleteError as exc:
            logger.exception("agent_memory_persist_incomplete")
            memory_error = (
                "Kullanıcı mesajı kaydedilmiş olabilir ancak asistan yanıtı yazılamadı "
                f"(user_memory_id={exc.user_memory_id})."
            )
        except Exception:
            logger.exception("agent_memory_persist_failed")
            memory_error = "Yanıt üretildi ancak bellek yazılamadı."

        payload = {
            "session_id": session_id,
            "submission_id": submission_id,
            "assistant_memory_id": persist_result.get("assistant_memory_id"),
            "user_memory_id": persist_result.get("user_memory_id"),
            "memory_error": memory_error,
            "flow_status": status,
            "assistant_text": assistant_text,
            "agent_reply": agent_reply,
            "agent_notice": agent_notice
            or (assistant_text if status not in {"ANSWER", "CLARIFY"} else None),
            "replayed": False,
            "past_count": len(past),
        }
        self._submissions.mark_completed(
            customer_id=customer_id,
            user_id=user_id,
            submission_id=submission_id,
            result_payload=payload,
        )
        self._submissions.commit()
        return self._outcome(
            "completed",
            submission_id=submission_id,
            session_id=session_id,
            turn_id=persist_result.get("assistant_memory_id"),
            payload=payload,
        )

    def _outcome(
        self,
        kind: str,
        *,
        submission_id: str,
        session_id: str | None = None,
        turn_id: Any = None,
        payload: Mapping[str, Any] | None = None,
    ) -> RunOutcome:
        return RunOutcome(
            kind=kind,
            submission_id=submission_id,
            session_id=session_id,
            turn_id=turn_id,
            payload=dict(payload or {}),
            agent_session_id=getattr(self._memory, "last_agent_session_id", None)
            or session_id,
        )
