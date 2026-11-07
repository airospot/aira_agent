"""file_read tool executor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from app.shared.corpus_path_sandbox import (
    MAX_READ_BYTES,
    is_probably_text,
    resolve_corpus_root,
    resolve_under_corpus,
)
from app.shared.document_source_identity import resolve_document_source

_DIR = Path(__file__).resolve().parent
_ARGUMENTS_SCHEMA = json.loads((_DIR / "tool.json").read_text(encoding="utf-8"))["arguments"]
_RESULT_SCHEMA = json.loads((_DIR / "result.json").read_text(encoding="utf-8"))
_ARGUMENTS_VALIDATOR = Draft202012Validator(_ARGUMENTS_SCHEMA)
_RESULT_VALIDATOR = Draft202012Validator(_RESULT_SCHEMA)


def execute_file_read(
    arguments: Any,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _ARGUMENTS_VALIDATOR.validate(arguments)
    result = _read(str(arguments["path"]), config=config)
    _RESULT_VALIDATOR.validate(result)
    return result


def _read(path_arg: str, *, config: Mapping[str, Any] | None) -> dict[str, Any]:
    root = resolve_corpus_root(config)
    target = resolve_under_corpus(root, path_arg)
    if target is None:
        return _result("invalid_path", path=path_arg, error="path_outside_corpus")
    if not target.exists() or not target.is_file():
        return _result("not_found", path=path_arg, error="file_not_found")
    if not is_probably_text(target):
        return _result("not_text", path=path_arg, error="binary_or_unsupported")
    try:
        data = target.read_bytes()
    except OSError as exc:
        return _result("error", path=path_arg, error=type(exc).__name__)
    truncated = len(data) > MAX_READ_BYTES
    chunk = data[:MAX_READ_BYTES]
    try:
        content = chunk.decode("utf-8")
    except UnicodeDecodeError:
        content = chunk.decode("utf-8", errors="replace")
    rel = target.relative_to(root).as_posix()
    identity = resolve_document_source(root, rel)
    return _result(
        "ok",
        path=rel,
        content=content,
        truncated=truncated,
        byte_size=len(data),
        identity=identity.as_tool_fields(),
    )


def _result(
    status: str,
    *,
    path: str | None = None,
    content: str | None = None,
    truncated: bool = False,
    byte_size: int | None = None,
    error: str | None = None,
    identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fields = {
        "source_filename": None,
        "display_name": None,
        "source_known": False,
        "source_ambiguous": False,
    }
    if identity:
        fields.update(dict(identity))
    return {
        "status": status,
        "path": path,
        "content": content,
        "truncated": truncated,
        "byte_size": byte_size,
        "error": error,
        **fields,
    }
