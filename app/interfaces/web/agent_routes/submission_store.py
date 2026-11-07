"""Flask-session store for Agent POST idempotency + thin PRG pointers.

Full agent answers live in ``agent_submissions.result_json`` (server DB), not
in the signed session cookie. This store only keeps submission dedupe keys and
a thin pointer (ids / short flags) so PRG/refresh survive cookie size limits.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping
from uuid import uuid4

_SUBMISSIONS_KEY = "agent_submissions"
_LAST_UI_KEY = "agent_last_ui"
_MAX_SUBMISSIONS = 40

# Keep cookie payloads small: never put full answers / timeline blobs here.
# Short operational agent_notice may remain; long clarify/answer text is DB-only.
_FORBIDDEN_BLOB_KEYS = frozenset(
    {
        "flow_timeline",
        "decision_trace",
        "flow_events",
        "agent_reply",
        "assistant_text",
        "request_text",
    }
)

# Keys allowed in the thin cookie pointer (everything else dropped too).
_ALLOWED_THIN_KEYS = frozenset(
    {
        "session_id",
        "submission_id",
        "assistant_memory_id",
        "user_memory_id",
        "memory_error",
        "flow_status",
        "replayed",
        "past_count",
        "agent_notice",
    }
)
_MAX_COOKIE_NOTICE_CHARS = 240


def mint_submission_id() -> str:
    return str(uuid4())


def _as_mutable(flask_session: Mapping[str, Any] | None) -> MutableMapping[str, Any] | None:
    if flask_session is None or not hasattr(flask_session, "__setitem__"):
        return None
    return flask_session  # type: ignore[return-value]


def _thin_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k in _FORBIDDEN_BLOB_KEYS:
            continue
        if k not in _ALLOWED_THIN_KEYS:
            continue
        if k == "agent_notice":
            text = str(v or "")
            if len(text) > _MAX_COOKIE_NOTICE_CHARS:
                continue
            out[k] = text
            continue
        out[k] = v
    return out


def get_completed_submission(
    flask_session: Mapping[str, Any] | None, submission_id: str
) -> dict[str, Any] | None:
    sid = str(submission_id or "").strip()
    if not sid or flask_session is None:
        return None
    store = flask_session.get(_SUBMISSIONS_KEY) or {}
    if not isinstance(store, dict):
        return None
    row = store.get(sid)
    return dict(row) if isinstance(row, dict) else None


def remember_submission(
    flask_session: Mapping[str, Any] | None,
    *,
    submission_id: str,
    payload: dict[str, Any],
) -> None:
    sess = _as_mutable(flask_session)
    if sess is None:
        return
    sid = str(submission_id or "").strip()
    if not sid:
        return
    thin = _thin_payload(dict(payload))
    store = sess.get(_SUBMISSIONS_KEY)
    if not isinstance(store, dict):
        store = {}
    store = dict(store)
    store[sid] = thin
    if len(store) > _MAX_SUBMISSIONS:
        for old in list(store.keys())[: len(store) - _MAX_SUBMISSIONS]:
            store.pop(old, None)
    sess[_SUBMISSIONS_KEY] = store
    sess[_LAST_UI_KEY] = thin
    if hasattr(sess, "modified"):
        sess.modified = True  # type: ignore[attr-defined]


def pop_last_ui_for_session(
    flask_session: Mapping[str, Any] | None, session_id: str | None
) -> dict[str, Any] | None:
    """Thin last-turn pointer for this conversation (answers loaded from DB)."""
    if flask_session is None:
        return None
    row = flask_session.get(_LAST_UI_KEY)
    if not isinstance(row, dict):
        return None
    if session_id and row.get("session_id") and row.get("session_id") != session_id:
        return None
    return dict(row)


def clear_last_ui(flask_session: Mapping[str, Any] | None) -> None:
    sess = _as_mutable(flask_session)
    if sess is None:
        return
    sess.pop(_LAST_UI_KEY, None)
    if hasattr(sess, "modified"):
        sess.modified = True  # type: ignore[attr-defined]
