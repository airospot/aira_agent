"""Aira Intelligence Native Flow ↔ existing AiraCoder memory bridge.

Canonical module under ``flow/memory/``. Reuses ``memory_service`` and
``ConversationService`` — no second store, agent loop, or SQL in routes.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Mapping

from app.domain.agents import memory_service
from app.domain.services.conversations.factory import create_conversation_service
from app.domain.services.structured_memory.settings import (
    load_structured_memory_flags,
    should_inject_structured_into_prompt,
)

logger = logging.getLogger(__name__)

AGENT_PAGE_TYPE = "Agent"

_SOURCE_KIND_NOTE = (
    "active_conversation.turns is the only active dialogue for this session. "
    "long_term_memory / structured_memory are background user context only. "
    "They must not override tool observations from file_read / file_search. "
    "historical_tool_references are not the active document; re-verify with tools."
)

_CONTEXT_POLICY = {
    "active_entity_source": "active_conversation.turns_and_current_request_only",
    "document_reference_priority": (
        "current_request_explicit_path_then_latest_opened_in_session_then_clarify"
    ),
    "long_term_memory_role": (
        "authorized_user_history_and_preferences_not_automatic_entity_binding"
    ),
    "structured_memory_role": "scoped_extracted_background_not_active_entity",
    "empty_active_requires_explicit_entity_or_clarify": True,
    "cross_conversation_entity_activation": "forbidden_unless_user_refers_to_prior",
}

# Optional STM historical tool refs for follow-up turns (not active entity / not facts).
_HISTORICAL_TOOL_REFERENCES_KEY = "historical_tool_references"
_MAX_HISTORICAL_TOOL_REFERENCES = 40
_MAX_HISTORICAL_TOOL_REFERENCES_JSON_BYTES = 16 * 1024  # 16 KiB total JSON budget
_HISTORICAL_TOOL_REFERENCES_POLICY = {
    "authority": "prior_stm_decision_trace_summary_only",
    "selected_entity": False,
    "not_active_entity": True,
    "not_current_canonical_fact": True,
    "does_not_replace_tool_observations": True,
}
# Statuses that never yield historical source references.
_HISTORICAL_NO_REF_STATUSES = frozenset(
    {
        "not_found",
        "invalid_argument",
        "invalid_path",
        "not_text",
        "error",
        "source_unavailable",
    }
)


class SessionIdentityError(ValueError):
    """Explicit conversation identity rejection (no silent fallback)."""

    def __init__(self, message: str, *, code: str = "conversation_identity_rejected"):
        super().__init__(message)
        self.code = code
        self.status = "BLOCKED"


class MemoryReadError(RuntimeError):
    """Hard memory read failure (distinct from empty result)."""

    def __init__(self, message: str, *, code: str = "memory_read_failed"):
        super().__init__(message)
        self.code = code


class MemoryPersistIncompleteError(RuntimeError):
    """User row may exist but assistant write failed (do not claim full success)."""

    def __init__(
        self,
        message: str,
        *,
        user_memory_id: int | None = None,
        code: str = "memory_persist_incomplete",
    ):
        super().__init__(message)
        self.code = code
        self.user_memory_id = user_memory_id


def resolve_session_id(
    *,
    requested_session_id: str | None,
    new_conversation: bool,
    customer_id: int,
    user_id: int,
    flask_session: Mapping[str, Any] | None = None,
) -> str:
    """Resolve Agent conversation session_id with explicit reject semantics.

    - ``new_conversation`` → always mint a new server UUID (clears flask key).
    - Explicit ``requested_session_id`` must be owned by (customer, user, Agent)
      or raise ``SessionIdentityError`` (no silent browser-session fallback).
    - No request id → resume owned flask ``agent_session_id`` if still owned by
      this tenant; otherwise mint new (tenant switch safe).
    - ``app_id`` is not a column on ``conversation_memory``; ``session_id`` is
      the conversation key within customer_id+user_id+page_type scope.
    """
    if not customer_id or not user_id:
        raise ValueError("customer_id and user_id are required for Agent memory")

    if new_conversation:
        sid = str(uuid.uuid4())
        _set_flask_session_id(flask_session, sid)
        return sid

    raw = str(requested_session_id or "").strip()
    if raw:
        owner = _agent_session_owner(raw)
        if owner is not None:
            if owner == (int(customer_id), int(user_id)):
                _set_flask_session_id(flask_session, raw)
                return raw
            # Existing Agent conversation belongs to another tenant/user.
            raise SessionIdentityError(
                "requested conversation_id is not owned by this user/tenant "
                f"(page_type={AGENT_PAGE_TYPE})",
                code="conversation_identity_rejected",
            )
        # Virgin id (no Agent rows yet): allow — GET mints into the form before
        # the first persist; requiring a DB row here blocked the first question.
        _set_flask_session_id(flask_session, raw)
        return raw

    existing = ""
    if flask_session is not None:
        existing = str(flask_session.get("agent_session_id") or "").strip()
    if existing:
        owner = _agent_session_owner(existing)
        if owner is None or owner == (int(customer_id), int(user_id)):
            # Virgin flask mint or owned resume.
            return existing
        # Prior browser value from another tenant/user — do not reuse.
        logger.warning(
            "agent_memory clearing unowned flask session_id customer_id=%s user_id=%s",
            customer_id,
            user_id,
        )

    sid = str(uuid.uuid4())
    _set_flask_session_id(flask_session, sid)
    return sid


def _set_flask_session_id(flask_session: Mapping[str, Any] | None, sid: str) -> None:
    if flask_session is not None and hasattr(flask_session, "__setitem__"):
        flask_session["agent_session_id"] = sid  # type: ignore[index]


def _agent_session_owner(session_id: str) -> tuple[int, int] | None:
    """Return (customer_id, user_id) if any Agent row exists for session_id."""
    from app.adapters.db.agents.models.memory import ConversationMemory

    try:
        row = (
            ConversationMemory.query.filter_by(
                page_type=AGENT_PAGE_TYPE,
                session_id=session_id,
            )
            .limit(1)
            .first()
        )
    except Exception as exc:
        logger.exception("agent_memory ownership check failed")
        raise MemoryReadError(str(exc), code="memory_ownership_check_failed") from exc
    if row is None:
        return None
    return int(row.customer_id), int(row.user_id)


def _session_owned(session_id: str, *, customer_id: int, user_id: int) -> bool:
    owner = _agent_session_owner(session_id)
    return owner == (int(customer_id), int(user_id))


def load_flow_conversation(
    *,
    session_id: str,
    customer_id: int,
    user_id: int,
    query: str | None = None,
) -> dict[str, Any]:
    """Build typed Flow conversation payload (STM turns + LTM + structured).

    Empty memory → empty lists/None. DB/identity failure → ``MemoryReadError``.
    """
    if not customer_id or not user_id:
        raise ValueError("customer_id and user_id are required")
    if not session_id:
        raise ValueError("session_id is required")

    try:
        short_term = memory_service.get_short_term_memory(
            page_type=AGENT_PAGE_TYPE,
            session_id=session_id,
            customer_id=customer_id,
            user_id=user_id,
            strict=True,
        )
    except Exception as exc:
        raise MemoryReadError(f"short-term read failed: {exc}") from exc

    turns: list[dict[str, Any]] = []
    for msg in short_term or []:
        role = "user" if msg.message_type == "user" else "assistant"
        content = str(msg.message_content or "")
        if content:
            turns.append(
                {
                    "role": role,
                    "content": content,
                    "memory_id": msg.id,
                    "sequence_number": msg.sequence_number,
                }
            )

    historical_tool_references = _project_historical_tool_references(short_term or [])

    long_term_block, ltm_mode, ltm_entries = _load_long_term_block(
        session_id=session_id,
        customer_id=customer_id,
        user_id=user_id,
        query=query,
    )
    structured_block, structured_policy = _load_structured_block(
        session_id=session_id,
        customer_id=customer_id,
        user_id=user_id,
        query=query,
    )

    active = {
        "session_id": session_id,
        "binding": "active",
        "turns": turns,
        "turn_count": len(turns),
        "is_empty": len(turns) == 0,
    }
    out: dict[str, Any] = {
        "session_id": session_id,
        "page_type": AGENT_PAGE_TYPE,
        # Backward-compatible alias of active STM turns (same list).
        "turns": turns,
        "active_conversation": active,
        "long_term_memory": long_term_block or None,
        "long_term_memory_entries": ltm_entries or None,
        "long_term_retrieval": ltm_mode,
        "long_term_memory_policy": {
            "role": "background_only",
            "activates_entity": False,
            "same_session_excluded": True,
        },
        "structured_memory": structured_block or None,
        "structured_memory_policy": structured_policy,
        "context_policy": dict(_CONTEXT_POLICY),
        "source_kinds": {
            "active_conversation": "short_term_active_session",
            "turns": "short_term_conversation_history",
            "long_term_memory": "user_long_term_memory_background",
            "structured_memory": "structured_extracted_memory_background",
        },
        "scope": {
            "customer_id": customer_id,
            "user_id": user_id,
            "page_type": AGENT_PAGE_TYPE,
            "cross_page_merge": False,
            "app_id": None,
            "app_id_note": "conversation_memory has no app_id column; session_id is conversation key",
        },
        "authority_note": _SOURCE_KIND_NOTE,
    }
    # Omit when empty so new/empty conversations stay clean.
    if historical_tool_references:
        out[_HISTORICAL_TOOL_REFERENCES_KEY] = historical_tool_references
        out["historical_tool_references_policy"] = dict(
            _HISTORICAL_TOOL_REFERENCES_POLICY
        )
    return out


def _historical_refs_json_bytes(refs: list[dict[str, Any]]) -> int:
    return len(json.dumps(refs, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _append_historical_ref_within_budget(
    refs: list[dict[str, Any]],
    ref: dict[str, Any],
) -> bool:
    """Append ``ref`` if count and 16 KiB JSON budgets allow. Never truncates IDs."""
    if len(refs) >= _MAX_HISTORICAL_TOOL_REFERENCES:
        return False
    trial = refs + [ref]
    if _historical_refs_json_bytes(trial) > _MAX_HISTORICAL_TOOL_REFERENCES_JSON_BYTES:
        return False
    refs.append(ref)
    return True


def _project_historical_tool_references(short_term: list[Any]) -> list[dict[str, Any]]:
    """Copy structural tool identities from STM assistant decision_trace summaries.

    Classification follows observation ``status`` (found / ambiguous / candidates),
    not mere presence of ``candidates[]``. Newest assistant turns first for the
    global budget; within one tool step, candidate order is preserved. Never
    marks a reference as selected / active entity. Safe on missing/corrupt metadata.
    """
    refs: list[dict[str, Any]] = []
    assistants = [
        msg
        for msg in short_term
        if getattr(msg, "message_type", None) == "assistant"
    ]
    for msg in reversed(assistants):
        if len(refs) >= _MAX_HISTORICAL_TOOL_REFERENCES:
            break
        if _historical_refs_json_bytes(refs) >= _MAX_HISTORICAL_TOOL_REFERENCES_JSON_BYTES:
            break
        md = getattr(msg, "meta_data", None)
        if md is None:
            md = getattr(msg, "metadata", None)
        if not isinstance(md, Mapping):
            continue
        trace = md.get("decision_trace")
        if not isinstance(trace, Mapping):
            continue
        steps = trace.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if len(refs) >= _MAX_HISTORICAL_TOOL_REFERENCES:
                break
            if not isinstance(step, Mapping):
                continue
            for ref in _refs_from_decision_step(
                step,
                source_assistant_memory_id=getattr(msg, "id", None),
                source_sequence_number=getattr(msg, "sequence_number", None),
            ):
                if not _append_historical_ref_within_budget(refs, ref):
                    return refs
    return refs


def _refs_from_decision_step(
    step: Mapping[str, Any],
    *,
    source_assistant_memory_id: Any,
    source_sequence_number: Any,
) -> list[dict[str, Any]]:
    """Project file tool identities from a Decision Trace step."""
    tool = step.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        return []
    obs = step.get("observation")
    if not isinstance(obs, Mapping):
        return []
    status = step.get("tool_status")
    if status is None:
        status = obs.get("status")
    if status is None:
        return []
    status_s = str(status)
    if status_s in _HISTORICAL_NO_REF_STATUSES:
        return []

    base: dict[str, Any] = {
        "source_assistant_memory_id": source_assistant_memory_id,
        "source_sequence_number": source_sequence_number,
        "tool": tool,
        "tool_status": status_s,
        "selected": False,
        "authority": "historical_stm_tool_reference",
    }
    step_no = step.get("step")
    if isinstance(step_no, int) and not isinstance(step_no, bool):
        base["step"] = step_no

    if tool in {"file_search", "file_name_search"} and status_s == "ok":
        kind = (
            "file_name_search_candidate"
            if tool == "file_name_search"
            else "file_search_candidate"
        )
        return _file_candidate_refs(base, obs.get("candidates"), observation_kind=kind)
    if tool == "file_read" and status_s == "ok":
        path = obs.get("path")
        if not isinstance(path, str) or not path.strip():
            return []
        ref = dict(base)
        ref["observation_kind"] = "file_read"
        ref["path"] = path.strip()
        if (
            _historical_refs_json_bytes([ref])
            > _MAX_HISTORICAL_TOOL_REFERENCES_JSON_BYTES
        ):
            return []
        return [ref]
    if tool == "show_image" and status_s == "ok":
        path = obs.get("path")
        if not isinstance(path, str) or not path.strip():
            return []
        ref = dict(base)
        ref["observation_kind"] = "show_image"
        ref["path"] = path.strip()
        display_url = obs.get("display_url")
        if isinstance(display_url, str) and display_url.strip():
            ref["display_url"] = display_url.strip()
        if (
            _historical_refs_json_bytes([ref])
            > _MAX_HISTORICAL_TOOL_REFERENCES_JSON_BYTES
        ):
            return []
        return [ref]
    return []


def _file_candidate_refs(
    base: Mapping[str, Any],
    candidates: Any,
    *,
    observation_kind: str,
) -> list[dict[str, Any]]:
    if not isinstance(candidates, list):
        return []
    out: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        ref = dict(base)
        ref["observation_kind"] = observation_kind
        ref["path"] = path.strip()
        line = item.get("line")
        if isinstance(line, int) and not isinstance(line, bool) and line > 0:
            ref["line"] = line
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            ref["name"] = name.strip()
        if (
            _historical_refs_json_bytes([ref])
            > _MAX_HISTORICAL_TOOL_REFERENCES_JSON_BYTES
        ):
            continue
        out.append(ref)
    return out



def _load_long_term_block(
    *,
    session_id: str,
    customer_id: int,
    user_id: int,
    query: str | None,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Return (text_block, mode, typed_entries).

    Entries from *other* sessions only. Text is labeled BACKGROUND — never an
    automatic active entity binding for the current conversation.
    """
    try:
        enabled = memory_service.get_long_term_enabled(
            customer_id=customer_id, user_id=user_id
        )
    except Exception as exc:
        raise MemoryReadError(f"long-term flag read failed: {exc}") from exc
    if not enabled:
        return "", "disabled", []

    header = (
        "=== Long-term Memory (BACKGROUND ONLY — not active conversation) ===\n"
        "These rows come from OTHER Agent sessions for this user. "
        "Do NOT treat their topics as the active subject "
        "of THIS conversation unless the user explicitly refers to that past talk. "
        "If THIS conversation has no topic yet and the user did not name one, prefer CLARIFY."
    )
    entries: list[dict[str, Any]] = []
    parts: list[str] = []
    mode = "empty"

    if query and str(query).strip():
        try:
            semantic = memory_service.get_long_term_memory_semantic(
                query=str(query),
                page_type=AGENT_PAGE_TYPE,
                exclude_session_id=session_id,
                limit=5,
                customer_id=customer_id,
                user_id=user_id,
                strict=True,
            )
        except Exception as exc:
            raise MemoryReadError(f"long-term semantic read failed: {exc}") from exc
        if semantic:
            mode = "semantic"
            parts.append(header)
            parts.append("(retrieval=semantic)")
            for result in semantic:
                msg = result["memory"]
                if msg.session_id == session_id:
                    continue
                similarity = result["similarity"]
                role = "User" if msg.message_type == "user" else "Assistant"
                date_str = (
                    msg.created_at.strftime("%Y-%m-%d") if msg.created_at else "Unknown"
                )
                excerpt = str(msg.message_content or "")[:200]
                entries.append(
                    {
                        "source_kind": "long_term_memory",
                        "role": role.lower(),
                        "origin_session_id": msg.session_id,
                        "date": date_str,
                        "similarity": similarity,
                        "excerpt": excerpt,
                        "activates_entity": False,
                    }
                )
                parts.append(
                    f"[BACKGROUND] [{date_str}] [{role}] (Similarity: {similarity:.1%}) "
                    f"origin_session={msg.session_id}: {excerpt}"
                )
            if entries:
                return "\n".join(parts), mode, entries

    try:
        long_term = memory_service.get_long_term_memory(
            page_type=AGENT_PAGE_TYPE,
            session_id=None,
            days_back=30,
            limit=5,
            customer_id=customer_id,
            user_id=user_id,
            strict=True,
        )
    except Exception as exc:
        raise MemoryReadError(f"long-term date read failed: {exc}") from exc
    other = [m for m in (long_term or []) if m.session_id != session_id]
    if not other:
        return "", "empty", []
    mode = "date_fallback"
    parts = [header, "(retrieval=date_fallback)"]
    for msg in other[:5]:
        role = "User" if msg.message_type == "user" else "Assistant"
        date_str = msg.created_at.strftime("%Y-%m-%d") if msg.created_at else "Unknown"
        excerpt = str(msg.message_content or "")[:200]
        entries.append(
            {
                "source_kind": "long_term_memory",
                "role": role.lower(),
                "origin_session_id": msg.session_id,
                "date": date_str,
                "similarity": None,
                "excerpt": excerpt,
                "activates_entity": False,
            }
        )
        parts.append(
            f"[BACKGROUND] [{date_str}] [{role}] origin_session={msg.session_id}: {excerpt}"
        )
    return "\n".join(parts), mode, entries


def _load_structured_block(
    *,
    session_id: str,
    customer_id: int,
    user_id: int,
    query: str | None,
) -> tuple[str, dict[str, Any]]:
    flags = load_structured_memory_flags(int(customer_id), int(user_id))
    policy = {
        "enabled": flags.enabled,
        "shadow_mode": flags.shadow_mode,
        "injected": False,
    }
    if not should_inject_structured_into_prompt(flags):
        # Shadow/disabled: never present as verified user knowledge.
        return "", policy
    try:
        from app.domain.services.structured_memory import retrieval as sm_retrieval
        from app.domain.services.structured_memory.lifecycle import (
            expire_due_extracted_memories,
        )

        try:
            expire_due_extracted_memories(int(customer_id), int(user_id))
        except Exception as ex:
            logger.warning("structured_memory expiry skipped: %s", ex)
        block = sm_retrieval.build_structured_context_block(
            customer_id=int(customer_id),
            user_id=int(user_id),
            session_id=session_id,
            query=query,
            metadata={"source": "agent_native_flow"},
            flags=flags,
        )
        policy["injected"] = bool(block)
        return (block or ""), policy
    except Exception as exc:
        raise MemoryReadError(f"structured memory read failed: {exc}") from exc


_TRACE_META_KEYS = frozenset(
    {"flow_timeline", "decision_trace", "flow_events_sanitized"}
)


def persist_turn(
    *,
    session_id: str,
    customer_id: int,
    user_id: int,
    user_text: str,
    flow_status: str | None,
    assistant_text: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist user then assistant; surface incomplete assistant writes.

    Flow Timeline / Decision Trace ride on assistant ``metadata`` only (canonical
    turn association). They are not written into long-term user memory semantics.
    """
    if not customer_id or not user_id:
        raise ValueError("customer_id and user_id are required")
    if not session_id:
        raise ValueError("session_id is required")

    md = dict(metadata or {})
    md.setdefault("source", "agent_native_flow")
    if flow_status:
        md["flow_status"] = flow_status

    # User row: no heavy trace blobs (keeps embedding/context clean).
    user_md = {k: v for k, v in md.items() if k not in _TRACE_META_KEYS}
    assistant_md = dict(md)

    saved_user = None
    saved_assistant = None
    user_content = str(user_text or "").strip()
    if user_content:
        saved_user = memory_service.save_message(
            page_type=AGENT_PAGE_TYPE,
            session_id=session_id,
            message_type="user",
            message_content=user_content,
            metadata=user_md,
            memory_type="short_term",
            create_embedding=True,
            customer_id=customer_id,
            user_id=user_id,
        )

    assistant_content = str(assistant_text or "").strip()
    persist_assistant = flow_status in {
        "ANSWER",
        "CLARIFY",
        "STOP_INCOMPLETE",
        "step_limit",
    }
    if persist_assistant and assistant_content:
        try:
            saved_assistant = memory_service.save_message(
                page_type=AGENT_PAGE_TYPE,
                session_id=session_id,
                message_type="assistant",
                message_content=assistant_content,
                metadata=assistant_md,
                memory_type="short_term",
                create_embedding=False,
                customer_id=customer_id,
                user_id=user_id,
            )
        except Exception as exc:
            raise MemoryPersistIncompleteError(
                f"assistant message write failed after user save: {exc}",
                user_memory_id=getattr(saved_user, "id", None),
            ) from exc

    return {
        "session_id": session_id,
        "user_memory_id": getattr(saved_user, "id", None),
        "assistant_memory_id": getattr(saved_assistant, "id", None),
        "complete": bool(
            (not user_content or saved_user)
            and (not (persist_assistant and assistant_content) or saved_assistant)
        ),
    }


def load_turn_trace(
    *,
    session_id: str,
    customer_id: int,
    user_id: int,
    turn_id: int | str | None = None,
) -> dict[str, Any] | None:
    """Load sanitized Flow Timeline / Decision Trace for one assistant turn.

    Default: latest assistant message in the session. Never crosses tenants.
    """
    from app.adapters.db.agents.models.memory import ConversationMemory

    if not session_id or not customer_id or not user_id:
        return None
    try:
        q = ConversationMemory.query.filter_by(
            customer_id=customer_id,
            user_id=user_id,
            page_type=AGENT_PAGE_TYPE,
            session_id=session_id,
            message_type="assistant",
        )
        row = None
        if turn_id is not None and str(turn_id).strip():
            try:
                tid = int(turn_id)
            except (TypeError, ValueError):
                tid = None
            if tid is not None:
                row = q.filter_by(id=tid).first()
        if row is None:
            row = q.order_by(ConversationMemory.id.desc()).first()
    except Exception as exc:
        raise MemoryReadError(f"turn trace read failed: {exc}") from exc
    if row is None:
        return None
    md = row.meta_data if isinstance(row.meta_data, dict) else {}
    timeline = md.get("flow_timeline")
    trace = md.get("decision_trace")
    if not timeline and not trace:
        return {
            "turn_id": row.id,
            "session_id": session_id,
            "flow_timeline": None,
            "decision_trace": None,
            "flow_status": md.get("flow_status"),
            "submission_id": md.get("submission_id"),
            "has_trace": False,
        }
    return {
        "turn_id": row.id,
        "session_id": session_id,
        "flow_timeline": timeline if isinstance(timeline, list) else None,
        "decision_trace": trace if isinstance(trace, dict) else None,
        "flow_status": md.get("flow_status"),
        "submission_id": md.get("submission_id"),
        "has_trace": True,
    }


def _conversation_service():
    """Build ConversationService with a psycopg2-compatible DSN."""
    conn = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("SQLALCHEMY_DATABASE_URI")
        or ""
    )
    if not conn:
        # Compose from discrete POSTGRES_* (common in container).
        host = os.environ.get("POSTGRES_HOST")
        if host:
            port = os.environ.get("POSTGRES_PORT", "5432")
            dbname = os.environ.get("POSTGRES_DB", "airacoder")
            user = os.environ.get("POSTGRES_USER", "postgres")
            password = os.environ.get("POSTGRES_PASSWORD", "postgres")
            conn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
        else:
            from app.adapters.db.agents.models.base import db

            conn = str(db.engine.url)
    conn = (
        str(conn)
        .replace("postgresql+psycopg2://", "postgresql://")
        .replace("postgresql+psycopg://", "postgresql://")
    )
    return create_conversation_service(conn)


def list_agent_conversations(
    *, customer_id: int, user_id: int, limit: int = 10, offset: int = 0
) -> list[dict[str, Any]]:
    """List Agent sessions via ConversationService (canonical list owner)."""
    try:
        return _conversation_service().list_conversations(
            customer_id=customer_id,
            user_id=user_id,
            page_type=AGENT_PAGE_TYPE,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.warning("ConversationService list failed; ORM fallback: %s", exc)
        from sqlalchemy import func

        from app.adapters.db.agents.models.base import db
        from app.adapters.db.agents.models.memory import ConversationMemory

        rows = (
            db.session.query(
                ConversationMemory.session_id,
                func.min(ConversationMemory.created_at).label("created_at"),
                func.max(ConversationMemory.created_at).label("last_message_at"),
            )
            .filter_by(
                customer_id=customer_id,
                user_id=user_id,
                page_type=AGENT_PAGE_TYPE,
            )
            .group_by(ConversationMemory.session_id)
            .order_by(
                func.max(ConversationMemory.created_at).desc(),
                ConversationMemory.session_id.asc(),
            )
            .offset(max(0, int(offset or 0)))
            .limit(max(1, min(int(limit), 100)))
            .all()
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            title_row = (
                ConversationMemory.query.filter_by(
                    customer_id=customer_id,
                    user_id=user_id,
                    page_type=AGENT_PAGE_TYPE,
                    session_id=row.session_id,
                    message_type="user",
                )
                .order_by(ConversationMemory.id.asc())
                .first()
            )
            title = (title_row.message_content if title_row else "") or row.session_id
            out.append(
                {
                    "session_id": row.session_id,
                    "title": str(title)[:120],
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "last_message_at": (
                        row.last_message_at.isoformat() if row.last_message_at else None
                    ),
                }
            )
        return out


def load_ui_transcript(
    *, session_id: str, customer_id: int, user_id: int
) -> list[dict[str, Any]]:
    """Full conversation transcript for UI (not the bounded STM model window).

    Prefer ConversationService; fall back to ORM (same ownership filters) if the
    repository DSN path is unavailable. Includes STM + LTM rows for the session.
    Each turn may include ``memory_id`` and ``has_flow_trace`` for GET restore.
    """
    rows: list[dict[str, Any]] | None = None
    try:
        rows = _conversation_service().get_conversation_messages(
            customer_id=customer_id,
            user_id=user_id,
            session_id=session_id,
            page_type=AGENT_PAGE_TYPE,
        )
    except ValueError:
        rows = None
    except Exception as exc:
        logger.warning("ConversationService transcript failed; ORM fallback: %s", exc)
        rows = None

    if rows is None:
        from app.adapters.db.agents.models.memory import ConversationMemory

        try:
            orm_rows = (
                ConversationMemory.query.filter_by(
                    customer_id=customer_id,
                    user_id=user_id,
                    page_type=AGENT_PAGE_TYPE,
                    session_id=session_id,
                )
                .order_by(ConversationMemory.id.asc())
                .all()
            )
        except Exception as exc:
            raise MemoryReadError(f"ui transcript read failed: {exc}") from exc
        rows = [
            {
                "id": r.id,
                "message_type": r.message_type,
                "message_content": r.message_content,
                "metadata": r.meta_data if isinstance(r.meta_data, dict) else {},
            }
            for r in orm_rows
        ]

    turns: list[dict[str, Any]] = []
    for row in rows or []:
        # ConversationService uses type/content; ORM fallback uses message_*.
        msg_type = row.get("message_type") or row.get("type") or ""
        role = "user" if msg_type == "user" else "assistant"
        content = str(row.get("message_content") or row.get("content") or "")
        if not content:
            continue
        md = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        mid = row.get("id") or row.get("memory_id")
        has_trace = bool(
            role == "assistant"
            and (md.get("flow_timeline") or md.get("decision_trace"))
        )
        turns.append(
            {
                "role": role,
                "content": content,
                "memory_id": mid,
                "has_flow_trace": has_trace,
            }
        )
    return turns
