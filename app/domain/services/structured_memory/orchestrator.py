"""
Structured memory extraction orchestrator.

Runs **after** transcript commit. Uses a fresh DB transaction for structured rows;
failures roll back **only** structured writes.

``shadow_mode`` is only for read-path (prompt injection); extraction runs when
``memory_structured_enabled`` is on regardless of shadow.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.adapters.db.agents.models.base import db
from app.adapters.db.agents.repositories.structured_memory_repository import (
    StructuredMemoryRepository,
)
from app.domain.services.structured_memory.constants import MEMORY_EVENT_TYPES_V1
from app.domain.services.structured_memory.merge import find_active_duplicate
from app.domain.services.structured_memory.normalizer import normalize_memory_text
from app.domain.services.structured_memory.rules import evaluate_rules
from app.domain.services.structured_memory.scope import (
    audit_session_and_project_ids,
    derive_scope_v1,
)
from app.domain.services.structured_memory.sensitive_filter import evaluate_sensitive_content
from app.domain.services.structured_memory.settings import load_structured_memory_flags

logger = logging.getLogger(__name__)


def _commit_structured() -> None:
    db.session.commit()


def _emit_event(
    repo: StructuredMemoryRepository,
    *,
    customer_id: int,
    user_id: int,
    event_type: str,
    conversation_memory_id: Optional[int],
    extracted_memory_id: Optional[int],
    payload: Optional[Dict[str, Any]],
    transcript_session_id: Optional[str] = None,
    transcript_project_id: Optional[int] = None,
) -> None:
    if event_type not in MEMORY_EVENT_TYPES_V1:
        raise ValueError(f"invalid event_type: {event_type}")
    repo.insert_event(
        customer_id=customer_id,
        user_id=user_id,
        event_type=event_type,
        extracted_memory_id=extracted_memory_id,
        conversation_memory_id=conversation_memory_id,
        payload=payload or {},
        session_id=transcript_session_id,
        project_id=transcript_project_id,
    )
    _commit_structured()


def process_structured_memory_candidate(
    *,
    conversation_memory_id: int,
    message_type: str,
    message_content: str,
    customer_id: int,
    user_id: int,
    page_type: str,
    session_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    repo: Optional[StructuredMemoryRepository] = None,
    flag_overrides: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Shadow extraction entrypoint. Safe to call from ``save_message`` post-commit.

    ``flag_overrides`` is for unit tests only (maps config keys to values).
    ``repo`` injects a fake repository for tests.
    """
    try:
        _process_structured_memory_candidate_impl(
            conversation_memory_id=conversation_memory_id,
            message_type=message_type,
            message_content=message_content,
            customer_id=customer_id,
            user_id=user_id,
            page_type=page_type,
            session_id=session_id,
            metadata=metadata,
            repo=repo or StructuredMemoryRepository(),
            flag_overrides=flag_overrides,
        )
    except Exception:
        logger.exception(
            "structured_memory pipeline failed customer_id=%s user_id=%s conv_msg_id=%s "
            "(transcript already committed; structured txn rolled back)",
            customer_id,
            user_id,
            conversation_memory_id,
        )
        try:
            db.session.rollback()
        except Exception:
            logger.exception("structured_memory rollback failed")


def _process_structured_memory_candidate_impl(
    *,
    conversation_memory_id: int,
    message_type: str,
    message_content: str,
    customer_id: int,
    user_id: int,
    page_type: str,
    session_id: str,
    metadata: Optional[Dict[str, Any]],
    repo: StructuredMemoryRepository,
    flag_overrides: Optional[Dict[str, Any]],
) -> None:
    flags = load_structured_memory_flags(
        customer_id, user_id, overrides=flag_overrides
    )
    audit_sid, audit_pid = audit_session_and_project_ids(session_id, metadata)

    if not flags.enabled:
        logger.debug(
            "structured_memory skip disabled customer_id=%s user_id=%s conv_msg_id=%s",
            customer_id,
            user_id,
            conversation_memory_id,
        )
        return

    if message_type != "user":
        _emit_event(
            repo,
            customer_id=customer_id,
            user_id=user_id,
            event_type="SKIPPED_NON_USER",
            conversation_memory_id=conversation_memory_id,
            extracted_memory_id=None,
            payload={"message_type": message_type},
            transcript_session_id=audit_sid,
            transcript_project_id=audit_pid,
        )
        logger.info(
            "structured_memory event=SKIPPED_NON_USER customer_id=%s user_id=%s conv_msg_id=%s",
            customer_id,
            user_id,
            conversation_memory_id,
        )
        return

    if flags.sensitive_filter_enabled:
        blocked, reason = evaluate_sensitive_content(message_content)
        if blocked:
            _emit_event(
                repo,
                customer_id=customer_id,
                user_id=user_id,
                event_type="REJECTED_SENSITIVE",
                conversation_memory_id=conversation_memory_id,
                extracted_memory_id=None,
                payload={"reason": reason or "sensitive"},
                transcript_session_id=audit_sid,
                transcript_project_id=audit_pid,
            )
            logger.info(
                "structured_memory event=REJECTED_SENSITIVE customer_id=%s user_id=%s "
                "conv_msg_id=%s reason=%s",
                customer_id,
                user_id,
                conversation_memory_id,
                reason,
            )
            return

    hit = evaluate_rules(message_content)
    if hit is None:
        logger.debug(
            "structured_memory no_rule_match customer_id=%s user_id=%s conv_msg_id=%s",
            customer_id,
            user_id,
            conversation_memory_id,
        )
        return

    if hit.confidence < flags.min_confidence:
        _emit_event(
            repo,
            customer_id=customer_id,
            user_id=user_id,
            event_type="REJECTED_LOW_CONFIDENCE",
            conversation_memory_id=conversation_memory_id,
            extracted_memory_id=None,
            payload={
                "confidence": hit.confidence,
                "min_confidence": flags.min_confidence,
                "rule_id": hit.rule_id,
            },
            transcript_session_id=audit_sid,
            transcript_project_id=audit_pid,
        )
        logger.info(
            "structured_memory event=REJECTED_LOW_CONFIDENCE customer_id=%s user_id=%s "
            "conv_msg_id=%s rule_id=%s confidence=%s",
            customer_id,
            user_id,
            conversation_memory_id,
            hit.rule_id,
            hit.confidence,
        )
        return

    scope_type, scope_value = derive_scope_v1(page_type, session_id, metadata)
    norm = normalize_memory_text(hit.memory_text)
    dup = find_active_duplicate(
        repo,
        customer_id=customer_id,
        user_id=user_id,
        memory_category=hit.memory_category,
        scope_type=scope_type,
        scope_value=scope_value,
        normalized_text=norm,
    )

    if dup is not None:
        prov = dup.provenance_json or {}
        hist = list(prov.get("merge_history", []))
        hist.append(
            {
                "rule_id": hit.rule_id,
                "source_conversation_memory_id": conversation_memory_id,
                "merged_snippet": hit.memory_text,
            }
        )
        prov["merge_history"] = hist
        repo.update_extracted_fields(
            dup.id,
            customer_id=customer_id,
            user_id=user_id,
            fields={
                "memory_text": hit.memory_text,
                "confidence": max(dup.confidence or 0.0, hit.confidence),
                "provenance_json": prov,
                "session_id": audit_sid,
                "project_id": audit_pid,
            },
        )
        _emit_event(
            repo,
            customer_id=customer_id,
            user_id=user_id,
            event_type="MERGED",
            conversation_memory_id=conversation_memory_id,
            extracted_memory_id=dup.id,
            payload={"rule_id": hit.rule_id, "merged_into_id": dup.id},
            transcript_session_id=audit_sid,
            transcript_project_id=audit_pid,
        )
        logger.info(
            "structured_memory event=MERGED customer_id=%s user_id=%s conv_msg_id=%s extracted_id=%s",
            customer_id,
            user_id,
            conversation_memory_id,
            dup.id,
        )
        return

    row = repo.insert_extracted_memory(
        customer_id=customer_id,
        user_id=user_id,
        memory_category=hit.memory_category,
        memory_text=hit.memory_text,
        scope_type=scope_type,
        scope_value=scope_value,
        session_id=audit_sid,
        project_id=audit_pid,
        status="active",
        confidence=hit.confidence,
        importance=0,
        provenance_json={
            "rule_id": hit.rule_id,
            "source_conversation_memory_id": conversation_memory_id,
        },
        source_conversation_memory_id=conversation_memory_id,
        supersedes_id=None,
        expires_at=None,
    )
    _emit_event(
        repo,
        customer_id=customer_id,
        user_id=user_id,
        event_type="CREATED",
        conversation_memory_id=conversation_memory_id,
        extracted_memory_id=row.id,
        payload={"rule_id": hit.rule_id},
        transcript_session_id=audit_sid,
        transcript_project_id=audit_pid,
    )
    logger.info(
        "structured_memory event=CREATED customer_id=%s user_id=%s conv_msg_id=%s extracted_id=%s",
        customer_id,
        user_id,
        conversation_memory_id,
        row.id,
    )
