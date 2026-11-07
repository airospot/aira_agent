"""file_name_search tool executor — match by technical path or original name."""

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
    is_resolved_under_corpus,
    resolve_corpus_root,
)
from app.shared.document_source_identity import (
    iter_source_name_matches,
    resolve_document_source,
)

_DIR = Path(__file__).resolve().parent
_ARGUMENTS_SCHEMA = json.loads((_DIR / "tool.json").read_text(encoding="utf-8"))["arguments"]
_RESULT_SCHEMA = json.loads((_DIR / "result.json").read_text(encoding="utf-8"))
_ARGUMENTS_VALIDATOR = Draft202012Validator(_ARGUMENTS_SCHEMA)
_RESULT_VALIDATOR = Draft202012Validator(_RESULT_SCHEMA)
_DEFAULT_LIMIT = 20


def execute_file_name_search(
    arguments: Any,
    *,
    config: Mapping[str, Any] | None = None,
    execution_control: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _ARGUMENTS_VALIDATOR.validate(arguments)
    result = _search_names(arguments, config=config, execution_control=execution_control)
    _RESULT_VALIDATOR.validate(result)
    return result


def _search_names(
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
    paths: list[Path] = []
    try:
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

    matches = iter_source_name_matches(root, query=query, paths=paths)
    hits: list[dict[str, Any]] = []
    for match_idx, match in enumerate(matches):
        if control is not None and match_idx % max(1, control.check_every_n) == 0:
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
        target = root / match.path
        if not is_resolved_under_corpus(root, target) or not target.is_file():
            continue
        try:
            size = target.stat().st_size
        except OSError:
            size = 0
        identity = resolve_document_source(root, match.path)
        source_filename = match.source_filename or identity.source_filename
        display_name = (
            match.source_filename
            if match.source_filename
            else identity.display_name
        )
        entry: dict[str, Any] = {
            "path": match.path,
            "name": Path(match.path).name,
            "byte_size": int(size),
            "source_filename": source_filename,
            "display_name": display_name,
            "source_known": bool(source_filename) or identity.source_known,
            "source_ambiguous": identity.source_ambiguous,
        }
        if identity.alternate_source_filenames:
            entry["alternate_source_filenames"] = list(
                identity.alternate_source_filenames
            )
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
