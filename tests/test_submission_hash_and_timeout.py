"""A00: request hash and processing timeout helpers (no LLM, no DB)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.adapters.db.agents.repositories import submission_repository as submissions


def test_hash_includes_text_session_and_new_conversation_flag() -> None:
    a = submissions.hash_request(
        request_text="merhaba", session_id="s1", new_conversation=False
    )
    b = submissions.hash_request(
        request_text="merhaba", session_id="s1", new_conversation=True
    )
    c = submissions.hash_request(
        request_text="farkli", session_id="s1", new_conversation=False
    )
    d = submissions.hash_request(
        request_text="merhaba", session_id=None, new_conversation=False
    )
    assert a != b
    assert a != c
    assert a != d
    assert len(a) == 64


def test_empty_session_hashes_as_none() -> None:
    blank = submissions.hash_request(
        request_text="x", session_id="  ", new_conversation=False
    )
    none = submissions.hash_request(
        request_text="x", session_id=None, new_conversation=False
    )
    assert blank == none


def test_hash_for_reservation_unscopes_new_and_empty() -> None:
    unscoped_new = submissions.hash_for_reservation(
        request_text="q", new_conversation=True, explicit_session_id=None
    )
    unscoped_empty = submissions.hash_for_reservation(
        request_text="q", new_conversation=False, explicit_session_id=None
    )
    scoped = submissions.hash_for_reservation(
        request_text="q", new_conversation=False, explicit_session_id="sess-1"
    )
    assert unscoped_new != unscoped_empty
    assert unscoped_empty != scoped
    assert submissions.hash_matches_stored(
        stored_hash=unscoped_empty,
        request_text="q",
        new_conversation=False,
        canonical_session_id="sess-minted-later",
    )
    assert not submissions.hash_matches_stored(
        stored_hash=unscoped_empty,
        request_text="q-other",
        new_conversation=False,
        canonical_session_id="sess-minted-later",
    )


def test_processing_timeout_detection() -> None:
    fresh = {"created_at": datetime.now(timezone.utc)}
    stale = {
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=20),
    }
    assert submissions.is_processing_timed_out(fresh, timeout_seconds=900) is False
    assert submissions.is_processing_timed_out(stale, timeout_seconds=900) is True
