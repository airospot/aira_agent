"""Model-view projections for the four native tool observations (A03).

Raw ToolExecutor validation stays on full results. This module only builds the
payload sent to the model. Identity fields are preserved; content is budgeted.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Mapping

_IDENTITY_KEYS = (
    "status",
    "path",
    "error",
    "source_filename",
    "display_name",
    "source_known",
    "source_ambiguous",
    "alternate_source_filenames",
    "display_url",
    "mime",
    "byte_size",
    "truncated",
    "query",
    "matched_total",
    "returned_count",
    "name",
)


def _json_bytes(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    )


def _copy_identity(raw: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _IDENTITY_KEYS:
        if key in raw:
            out[key] = deepcopy(raw[key])
    return out


def _shrink_content(text: str, *, max_chars: int) -> tuple[str, bool]:
    if max_chars < 1:
        return "", True
    if len(text) <= max_chars:
        return text, False
    # Avoid mid-codepoint: operate on unicode chars, not bytes.
    return text[: max_chars - 1] + "…", True


def _project_one(raw: Any, *, soft_limit: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {"status": "error", "error": "invalid_observation", "model_view_truncated": True}
    base = _copy_identity(raw)
    base["model_view_truncated"] = False
    base["raw_serialized_bytes"] = _json_bytes(raw)

    # file_read-like
    if "content" in raw:
        content = raw.get("content")
        if isinstance(content, str):
            # Leave room for identity envelope.
            room = max(64, soft_limit - _json_bytes(base) - 64)
            # soft_limit is for whole observation; convert approx bytes→chars.
            max_chars = max(32, room)
            clipped, trunc = _shrink_content(content, max_chars=max_chars)
            base["content"] = clipped
            if trunc:
                base["model_view_truncated"] = True
                base["truncated"] = True
        return base

    # search-like candidates
    if "candidates" in raw:
        cands = raw.get("candidates")
        if not isinstance(cands, list):
            base["candidates"] = []
            return base
        kept: list[Any] = []
        for item in cands:
            if not isinstance(item, Mapping):
                continue
            entry = _copy_identity(item)
            snippet = item.get("snippet")
            if isinstance(snippet, str):
                entry["snippet"], sn_trunc = _shrink_content(snippet, max_chars=240)
                if sn_trunc:
                    base["model_view_truncated"] = True
            if "line" in item:
                entry["line"] = item.get("line")
            if "name" in item:
                entry["name"] = item.get("name")
            kept.append(entry)
            trial = dict(base)
            trial["candidates"] = kept
            if _json_bytes(trial) > soft_limit and len(kept) > 1:
                kept.pop()
                base["model_view_truncated"] = True
                break
        base["candidates"] = kept
        base["returned_count"] = len(kept)
        return base

    return base


def project_observations_for_model(
    observations: Any,
    *,
    max_observation_bytes: int,
) -> tuple[list[Any], dict[str, Any]]:
    """Project a list of raw observations into a budgeted model view."""
    if observations is None:
        return [], {
            "serialized_bytes": 2,
            "truncated": False,
            "overflow": False,
            "raw_bytes": 2,
            "model_view_bytes": 2,
        }
    if not isinstance(observations, list):
        observations = [observations]

    raw_bytes = _json_bytes(observations)
    if not observations:
        return [], {
            "serialized_bytes": 2,
            "truncated": False,
            "overflow": False,
            "raw_bytes": raw_bytes,
            "model_view_bytes": 2,
        }

    per = max(256, max_observation_bytes // max(1, len(observations)))
    projected: list[Any] = []
    truncated = False
    for raw in observations:
        one = _project_one(raw, soft_limit=per)
        if one.get("model_view_truncated"):
            truncated = True
        projected.append(one)

    # Fit entire list under max_observation_bytes by dropping oldest first.
    while projected and _json_bytes(projected) > max_observation_bytes:
        if len(projected) == 1:
            # Shrink the sole observation content further.
            only = projected[0]
            if isinstance(only, dict) and isinstance(only.get("content"), str):
                content = only["content"]
                if len(content) <= 8:
                    break
                only = dict(only)
                only["content"], _ = _shrink_content(content, max_chars=max(8, len(content) // 2))
                only["model_view_truncated"] = True
                only["truncated"] = True
                projected = [only]
                truncated = True
                continue
            if isinstance(only, dict) and isinstance(only.get("candidates"), list):
                cands = list(only["candidates"])
                if not cands:
                    break
                cands = cands[:-1]
                only = dict(only)
                only["candidates"] = cands
                only["returned_count"] = len(cands)
                only["model_view_truncated"] = True
                projected = [only]
                truncated = True
                continue
            break
        projected = projected[1:]
        truncated = True

    size = _json_bytes(projected)
    overflow = size > max_observation_bytes
    # Minimum safe envelope: status + identity keys only.
    if overflow and projected:
        safe: list[Any] = []
        for raw in observations[-1:]:
            if isinstance(raw, Mapping):
                envelope = _copy_identity(raw)
                envelope["model_view_truncated"] = True
                envelope["content"] = None
                envelope["candidates"] = []
                envelope["note"] = "observation_truncated_to_identity_only"
                safe.append(envelope)
        if safe and _json_bytes(safe) <= max_observation_bytes:
            projected = safe
            size = _json_bytes(projected)
            truncated = True
            overflow = False
        else:
            overflow = True

    return projected, {
        "serialized_bytes": size,
        "truncated": truncated,
        "overflow": overflow,
        "raw_bytes": raw_bytes,
        "model_view_bytes": size,
    }
