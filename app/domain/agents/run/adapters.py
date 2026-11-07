"""Production adapters — bridge/repository behind ports (Flask/SQLAlchemy stay here)."""

from __future__ import annotations

from typing import Any, Mapping

from app.adapters.db.agents.models.base import db
from app.adapters.db.agents.repositories import submission_repository as submissions
from app.domain.agents.flow.execution.run_knowledge_agent import (
    run_knowledge_agent as _run_knowledge_agent,
)
from app.domain.agents.flow.memory import (
    list_agent_conversations as _list_agent_conversations,
    load_flow_conversation as _load_flow_conversation,
    persist_turn as _persist_turn,
    resolve_session_id as _resolve_session_id,
)

# Module-level aliases so tests can patch this module (not Flask propose).
resolve_session_id = _resolve_session_id
load_flow_conversation = _load_flow_conversation
list_agent_conversations = _list_agent_conversations
persist_turn = _persist_turn
run_knowledge_agent = _run_knowledge_agent


class BridgeMemoryAdapter:
    """Memory port over flow/memory bridge. No Flask session object required."""

    def __init__(self) -> None:
        self.last_agent_session_id: str | None = None

    def resolve_session_id(
        self,
        *,
        requested_session_id: str | None,
        new_conversation: bool,
        customer_id: int,
        user_id: int,
        agent_session_id_hint: str | None = None,
    ) -> str:
        hint: dict[str, Any] = {}
        raw_hint = str(agent_session_id_hint or "").strip()
        if raw_hint:
            hint["agent_session_id"] = raw_hint
        sid = resolve_session_id(
            requested_session_id=requested_session_id,
            new_conversation=new_conversation,
            customer_id=customer_id,
            user_id=user_id,
            flask_session=hint,
        )
        self.last_agent_session_id = (
            str(hint.get("agent_session_id") or "").strip() or sid
        )
        return sid

    def load_flow_conversation(
        self,
        *,
        session_id: str,
        customer_id: int,
        user_id: int,
        query: str,
    ) -> Any:
        return load_flow_conversation(
            session_id=session_id,
            customer_id=customer_id,
            user_id=user_id,
            query=query,
        )

    def list_agent_conversations(
        self,
        *,
        customer_id: int,
        user_id: int,
        limit: int = 10,
    ) -> list:
        return list_agent_conversations(
            customer_id=customer_id, user_id=user_id, limit=limit
        )

    def persist_turn(self, **kwargs: Any) -> dict[str, Any]:
        return persist_turn(**kwargs)


class SqlAlchemySubmissionAdapter:
    """Submission port; commit is explicit (never hold TX across the runner)."""

    def get_submission(
        self, *, customer_id: int, user_id: int, submission_id: str
    ) -> dict[str, Any] | None:
        return submissions.get_submission(
            customer_id=customer_id, user_id=user_id, submission_id=submission_id
        )

    def hash_for_reservation(
        self,
        *,
        request_text: str,
        new_conversation: bool,
        explicit_session_id: str | None,
        skill_id: str | None = None,
        skill_version: str | None = None,
        skill_digest: str | None = None,
    ) -> str:
        return submissions.hash_for_reservation(
            request_text=request_text,
            new_conversation=new_conversation,
            explicit_session_id=explicit_session_id,
            skill_id=skill_id,
            skill_version=skill_version,
            skill_digest=skill_digest,
        )

    def try_begin_processing(
        self,
        *,
        customer_id: int,
        user_id: int,
        submission_id: str,
        session_id: str | None,
        request_hash: str,
    ) -> bool:
        return submissions.try_begin_processing(
            customer_id=customer_id,
            user_id=user_id,
            submission_id=submission_id,
            session_id=session_id,
            request_hash=request_hash,
        )

    def commit(self) -> None:
        db.session.commit()

    def hash_matches_stored(
        self,
        *,
        stored_hash: str | None,
        request_text: str,
        new_conversation: bool,
        canonical_session_id: str | None,
        skill_id: str | None = None,
        skill_version: str | None = None,
        skill_digest: str | None = None,
    ) -> bool:
        return submissions.hash_matches_stored(
            stored_hash=stored_hash,
            request_text=request_text,
            new_conversation=new_conversation,
            canonical_session_id=canonical_session_id,
            skill_id=skill_id,
            skill_version=skill_version,
            skill_digest=skill_digest,
        )

    def is_processing_timed_out(
        self, row: Mapping[str, Any], *, timeout_seconds: int
    ) -> bool:
        return submissions.is_processing_timed_out(
            row, timeout_seconds=timeout_seconds
        )

    def mark_failed(
        self, *, customer_id: int, user_id: int, submission_id: str, error: str
    ) -> None:
        submissions.mark_failed(
            customer_id=customer_id,
            user_id=user_id,
            submission_id=submission_id,
            error=error,
        )

    def mark_completed(
        self,
        *,
        customer_id: int,
        user_id: int,
        submission_id: str,
        result_payload: Mapping[str, Any],
    ) -> None:
        submissions.mark_completed(
            customer_id=customer_id,
            user_id=user_id,
            submission_id=submission_id,
            result_payload=result_payload,
        )


def default_runner(
    request_text: str,
    *,
    conversation: Any,
    config: Mapping[str, Any] | None,
    on_event: Any = None,
    permitted_tool_names: frozenset[str] | None = None,
    run_policy: Any = None,
    skill_snapshot: Any = None,
) -> dict[str, Any]:
    return run_knowledge_agent(
        request_text,
        conversation=conversation,
        config=config,
        on_event=on_event,
        permitted_tool_names=permitted_tool_names,
        run_policy=run_policy,
        skill_snapshot=skill_snapshot,
    )
