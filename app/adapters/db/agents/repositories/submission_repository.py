"""Server-side agent propose idempotency store."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import text

from app.adapters.db.agents.models.base import db

DEFAULT_PROCESSING_TIMEOUT_SECONDS = 15 * 60


def hash_request(
    *,
    request_text: str,
    session_id: str | None,
    new_conversation: bool,
) -> str:
    payload = {
        "request_text": str(request_text or "").strip(),
        "session_id": str(session_id or "").strip() or None,
        "new_conversation": bool(new_conversation),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_for_reservation(
    *,
    request_text: str,
    new_conversation: bool,
    explicit_session_id: str | None,
) -> str:
    """Hash used when creating a reservation.

    New-conversation and empty-session starts omit session_id so concurrent
    first lookups that each mint a different UUID still share one hash.
    Explicit conversation continues include the client-provided session_id.
    """
    explicit = str(explicit_session_id or "").strip() or None
    if new_conversation or not explicit:
        return hash_request(
            request_text=request_text,
            session_id=None,
            new_conversation=new_conversation,
        )
    return hash_request(
        request_text=request_text,
        session_id=explicit,
        new_conversation=new_conversation,
    )


def hash_matches_stored(
    *,
    stored_hash: str | None,
    request_text: str,
    new_conversation: bool,
    canonical_session_id: str | None,
) -> bool:
    """True if request matches the reserved hash (unscoped or canonical-scoped)."""
    stored = str(stored_hash or "").strip()
    if not stored:
        return False
    unscoped = hash_request(
        request_text=request_text,
        session_id=None,
        new_conversation=new_conversation,
    )
    if stored == unscoped:
        return True
    canonical = str(canonical_session_id or "").strip() or None
    if canonical:
        scoped = hash_request(
            request_text=request_text,
            session_id=canonical,
            new_conversation=new_conversation,
        )
        if stored == scoped:
            return True
    return False


def _row_to_dict(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


def get_submission(
    *,
    customer_id: int,
    user_id: int,
    submission_id: str,
) -> dict[str, Any] | None:
    result = db.session.execute(
        text(
            """
            SELECT customer_id, user_id, submission_id, session_id, request_hash,
                   status, result_json, error, created_at, updated_at, completed_at
            FROM agent_submissions
            WHERE customer_id = :customer_id
              AND user_id = :user_id
              AND submission_id = :submission_id
            """
        ),
        {
            "customer_id": int(customer_id),
            "user_id": int(user_id),
            "submission_id": str(submission_id),
        },
    ).fetchone()
    return _row_to_dict(result)


def try_begin_processing(
    *,
    customer_id: int,
    user_id: int,
    submission_id: str,
    session_id: str | None,
    request_hash: str,
) -> bool:
    """Insert processing row. Returns True if this caller owns the run.

    Caller MUST commit immediately after a True result (before LLM).
    """
    result = db.session.execute(
        text(
            """
            INSERT INTO agent_submissions (
                customer_id, user_id, submission_id, session_id,
                request_hash, status, created_at, updated_at
            ) VALUES (
                :customer_id, :user_id, :submission_id, :session_id,
                :request_hash, 'processing', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (customer_id, user_id, submission_id) DO NOTHING
            """
        ),
        {
            "customer_id": int(customer_id),
            "user_id": int(user_id),
            "submission_id": str(submission_id),
            "session_id": session_id,
            "request_hash": request_hash,
        },
    )
    return bool(result.rowcount)


def mark_completed(
    *,
    customer_id: int,
    user_id: int,
    submission_id: str,
    result_payload: Mapping[str, Any],
) -> None:
    db.session.execute(
        text(
            """
            UPDATE agent_submissions
            SET status = 'completed',
                result_json = CAST(:result_json AS jsonb),
                error = NULL,
                updated_at = CURRENT_TIMESTAMP,
                completed_at = CURRENT_TIMESTAMP
            WHERE customer_id = :customer_id
              AND user_id = :user_id
              AND submission_id = :submission_id
            """
        ),
        {
            "customer_id": int(customer_id),
            "user_id": int(user_id),
            "submission_id": str(submission_id),
            "result_json": json.dumps(dict(result_payload), ensure_ascii=False),
        },
    )


def mark_failed(
    *,
    customer_id: int,
    user_id: int,
    submission_id: str,
    error: str,
) -> None:
    db.session.execute(
        text(
            """
            UPDATE agent_submissions
            SET status = 'failed',
                error = :error,
                updated_at = CURRENT_TIMESTAMP,
                completed_at = CURRENT_TIMESTAMP
            WHERE customer_id = :customer_id
              AND user_id = :user_id
              AND submission_id = :submission_id
            """
        ),
        {
            "customer_id": int(customer_id),
            "user_id": int(user_id),
            "submission_id": str(submission_id),
            "error": str(error or "")[:2000],
        },
    )


def is_processing_timed_out(
    row: Mapping[str, Any],
    *,
    timeout_seconds: int = DEFAULT_PROCESSING_TIMEOUT_SECONDS,
) -> bool:
    created = row.get("created_at")
    if created is None:
        return True
    if getattr(created, "tzinfo", None) is None:
        created = created.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return now - created > timedelta(seconds=max(1, int(timeout_seconds)))
