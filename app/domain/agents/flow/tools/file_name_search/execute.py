"""file_name_search tool executor — match corpus paths by name only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from app.domain.agents.flow.tools._corpus import (
    is_probably_text,
    is_resolved_under_corpus,
    resolve_corpus_root,
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
) -> dict[str, Any]:
    _ARGUMENTS_VALIDATOR.validate(arguments)
    result = _search_names(arguments, config=config)
    _RESULT_VALIDATOR.validate(result)
    return result


def _search_names(
    arguments: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None,
) -> dict[str, Any]:
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
    try:
        paths = sorted(p for p in root.glob(pattern) if p.is_file())
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

    for path in paths:
        if not is_resolved_under_corpus(root, path):
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            continue
        if not is_probably_text(path):
            continue
        if needle not in rel.lower() and needle not in path.name.lower():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        hits.append({"path": rel, "name": path.name, "byte_size": int(size)})
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
