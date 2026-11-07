"""file_search tool executor — content-only corpus text search."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from app.domain.agents.flow.tooling.execution_control import (
    ToolDeadlineExceeded,
    execution_control_from_mapping,
)
from app.shared.corpus_path_sandbox import (
    is_probably_text,
    is_resolved_under_corpus,
    read_limited_bytes,
    resolve_corpus_root,
)
from app.shared.document_source_identity import resolve_document_source

_DIR = Path(__file__).resolve().parent
_ARGUMENTS_SCHEMA = json.loads((_DIR / "tool.json").read_text(encoding="utf-8"))["arguments"]
_RESULT_SCHEMA = json.loads((_DIR / "result.json").read_text(encoding="utf-8"))
_ARGUMENTS_VALIDATOR = Draft202012Validator(_ARGUMENTS_SCHEMA)
_RESULT_VALIDATOR = Draft202012Validator(_RESULT_SCHEMA)
_DEFAULT_LIMIT = 20
_MAX_FILE_BYTES = 2_000_000


def execute_file_search(
    arguments: Any,
    *,
    config: Mapping[str, Any] | None = None,
    execution_control: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _ARGUMENTS_VALIDATOR.validate(arguments)
    result = _search(arguments, config=config, execution_control=execution_control)
    _RESULT_VALIDATOR.validate(result)
    return result


def _search(
    arguments: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None,
    execution_control: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    control = execution_control_from_mapping(execution_control)
    query = str(arguments.get("query") or "").strip()
    if not query:
        return {
            "status": "invalid_argument",
            "query": query,
            "matched_total": 0,
            "returned_count": 0,
            "truncated": False,
            "candidates": [],
            "error": "empty_query",
        }
    limit = int(arguments.get("limit") or _DEFAULT_LIMIT)
    limit = max(1, min(limit, 50))
    pattern = str(arguments.get("glob") or "**/*").strip() or "**/*"
    root = resolve_corpus_root(config)
    needle = query.lower()
    hits: list[dict[str, Any]] = []
    identity_cache: dict[str, Mapping[str, Any]] = {}
    paths: list[Path] = []
    try:
        # Cooperative collect — avoid claiming unlimited glob is free.
        for idx, path in enumerate(root.glob(pattern)):
            if control is not None and idx % max(1, control.check_every_n) == 0:
                control.checkpoint()
            if path.is_file():
                paths.append(path)
        paths.sort()
    except ToolDeadlineExceeded:
        return {
            "status": "error",
            "query": query,
            "matched_total": 0,
            "returned_count": 0,
            "truncated": False,
            "candidates": [],
            "error": "tool_deadline_exceeded",
        }
    except ValueError:
        return {
            "status": "invalid_argument",
            "query": query,
            "matched_total": 0,
            "returned_count": 0,
            "truncated": False,
            "candidates": [],
            "error": "invalid_glob",
        }

    for file_idx, path in enumerate(paths):
        if control is not None and file_idx % max(1, control.check_every_n) == 0:
            try:
                control.checkpoint()
            except ToolDeadlineExceeded:
                return {
                    "status": "error",
                    "query": query,
                    "matched_total": len(hits),
                    "returned_count": len(hits),
                    "truncated": True,
                    "candidates": hits,
                    "error": "tool_deadline_exceeded",
                }
        if not is_resolved_under_corpus(root, path):
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        if not is_probably_text(path):
            continue
        try:
            data, _trunc = read_limited_bytes(path, max_bytes=_MAX_FILE_BYTES)
            text = data.decode("utf-8", errors="replace")
        except OSError:
            continue
        if rel not in identity_cache:
            identity_cache[rel] = resolve_document_source(root, rel).as_tool_fields()
        identity = identity_cache[rel]
        for idx, line in enumerate(text.splitlines(), start=1):
            if control is not None and idx % 200 == 0:
                try:
                    control.checkpoint()
                except ToolDeadlineExceeded:
                    return {
                        "status": "error",
                        "query": query,
                        "matched_total": len(hits),
                        "returned_count": len(hits),
                        "truncated": True,
                        "candidates": hits,
                        "error": "tool_deadline_exceeded",
                    }
            if needle not in line.lower():
                continue
            entry: dict[str, Any] = {
                "path": rel,
                "line": idx,
                "snippet": line.strip()[:240],
                "source_filename": identity.get("source_filename"),
                "display_name": identity.get("display_name") or "orijinal adı bilinmiyor",
                "source_known": bool(identity.get("source_known")),
                "source_ambiguous": bool(identity.get("source_ambiguous")),
            }
            alts = identity.get("alternate_source_filenames")
            if isinstance(alts, list) and alts:
                entry["alternate_source_filenames"] = list(alts)
            hits.append(entry)
            if len(hits) >= limit:
                return {
                    "status": "ok",
                    "query": query,
                    "matched_total": len(hits),
                    "returned_count": len(hits),
                    "truncated": True,
                    "candidates": hits,
                    "error": None,
                }

    return {
        "status": "ok",
        "query": query,
        "matched_total": len(hits),
        "returned_count": len(hits),
        "truncated": False,
        "candidates": hits,
        "error": None,
    }
