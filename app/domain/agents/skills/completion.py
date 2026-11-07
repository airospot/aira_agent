"""Narrow skill completion gates (execution-enforced; not prompt-only)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

_EVIDENCE_MISSING_CODE = "skill_evidence_missing"
_EVIDENCE_MISSING_REASON = (
    "Belge incelemesi için hedef dosyanın içeriği file_read ile okunmadan "
    "içerik raporu verilemez."
)
_FEEDBACK_MESSAGE = (
    "Skill completion: content review ANSWER rejected. "
    "Call file_read on the candidate content path and use that observation; "
    "name/size/directory/meta.json alone are not document content. "
    "If the file was not found, ANSWER/CLARIFY honestly without inventing "
    "content and without asking the user for extracted_data/ or content.md paths."
)


def evidence_missing_code() -> str:
    return _EVIDENCE_MISSING_CODE


def evidence_missing_reason() -> str:
    return _EVIDENCE_MISSING_REASON


def correction_feedback_observation() -> dict[str, Any]:
    return {
        "status": "skill_requirement",
        "error": _EVIDENCE_MISSING_CODE,
        "tool": None,
        "path": None,
        "content": None,
        "message": _FEEDBACK_MESSAGE,
        "source_filename": None,
        "display_name": None,
        "source_known": False,
        "source_ambiguous": False,
    }


def _path_is_meta_json(path: Any) -> bool:
    text = str(path or "").strip().replace("\\", "/")
    if not text:
        return False
    name = text.rsplit("/", 1)[-1].lower()
    return name == "meta.json"


def is_successful_content_file_read(observation: Any) -> bool:
    """True when observation is a successful file_read with document body text."""
    if not isinstance(observation, Mapping):
        return False
    tool = str(observation.get("tool") or "").strip()
    # Shape fallback when tool tag missing: content key present (file_read schema).
    if tool and tool != "file_read":
        return False
    if not tool and "content" not in observation:
        return False
    if str(observation.get("status") or "") != "ok":
        return False
    if _path_is_meta_json(observation.get("path")):
        return False
    content = observation.get("content")
    if not isinstance(content, str) or not content.strip():
        return False
    return True


def is_zero_hit_name_search(observation: Any) -> bool:
    if not isinstance(observation, Mapping):
        return False
    tool = str(observation.get("tool") or "").strip()
    if tool and tool not in {"file_name_search", "file_search"}:
        return False
    if "candidates" not in observation and "matched_total" not in observation:
        return False
    if str(observation.get("status") or "") != "ok":
        return False
    matched = observation.get("matched_total")
    candidates = observation.get("candidates")
    if isinstance(matched, int) and matched == 0:
        return True
    if isinstance(candidates, list) and len(candidates) == 0:
        if matched is None or matched == 0:
            return True
    return False


def has_search_hits_without_content_read(observations: Sequence[Any]) -> bool:
    saw_hits = False
    for obs in observations:
        if is_successful_content_file_read(obs):
            return False
        if not isinstance(obs, Mapping):
            continue
        tool = str(obs.get("tool") or "").strip()
        if tool and tool not in {"file_name_search", "file_search"}:
            continue
        if "candidates" not in obs and "matched_total" not in obs:
            continue
        if str(obs.get("status") or "") != "ok":
            continue
        matched = obs.get("matched_total")
        candidates = obs.get("candidates")
        if isinstance(matched, int) and matched > 0:
            saw_hits = True
        elif isinstance(candidates, list) and len(candidates) > 0:
            saw_hits = True
    return saw_hits


def content_answer_allowed(observations: Sequence[Any]) -> tuple[bool, str | None]:
    """Whether ANSWER is allowed under content_answer_requires_file_read.

    Allowed when:
    - successful file_read with non-empty content (not meta.json), or
    - honest not-found: zero-hit search and no content read required for inventing.
    Disallowed when search returned candidates but no content file_read yet,
    or ANSWER with no relevant observations.
    """
    obs_list = list(observations or [])
    if any(is_successful_content_file_read(obs) for obs in obs_list):
        return True, None
    if any(is_zero_hit_name_search(obs) for obs in obs_list):
        return True, None
    if has_search_hits_without_content_read(obs_list):
        return False, _EVIDENCE_MISSING_CODE
    return False, _EVIDENCE_MISSING_CODE
