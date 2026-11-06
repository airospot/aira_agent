"""show_image tool executor — validate corpus image and return display URL."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from jsonschema import Draft202012Validator

from app.domain.agents.flow.tools._corpus import (
    resolve_corpus_root,
    resolve_under_corpus,
)

_DIR = Path(__file__).resolve().parent
_ARGUMENTS_SCHEMA = json.loads((_DIR / "tool.json").read_text(encoding="utf-8"))["arguments"]
_RESULT_SCHEMA = json.loads((_DIR / "result.json").read_text(encoding="utf-8"))
_ARGUMENTS_VALIDATOR = Draft202012Validator(_ARGUMENTS_SCHEMA)
_RESULT_VALIDATOR = Draft202012Validator(_RESULT_SCHEMA)

_MAX_IMAGE_BYTES = 5_000_000
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
_CORPUS_URL_PREFIX = "/agent/corpus/"


def execute_show_image(
    arguments: Any,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _ARGUMENTS_VALIDATOR.validate(arguments)
    result = _show(str(arguments["path"]), config=config)
    _RESULT_VALIDATOR.validate(result)
    return result


def _show(path_arg: str, *, config: Mapping[str, Any] | None) -> dict[str, Any]:
    root = resolve_corpus_root(config)
    target = resolve_under_corpus(root, path_arg)
    if target is None:
        return _result("invalid_path", path=path_arg, error="path_outside_corpus")
    if not target.exists() or not target.is_file():
        return _result("not_found", path=path_arg, error="file_not_found")
    suffix = target.suffix.lower()
    if suffix not in _IMAGE_SUFFIXES:
        return _result("not_image", path=path_arg, error="unsupported_extension")
    try:
        byte_size = target.stat().st_size
    except OSError as exc:
        return _result("error", path=path_arg, error=type(exc).__name__)
    if byte_size > _MAX_IMAGE_BYTES:
        return _result(
            "too_large",
            path=path_arg,
            byte_size=byte_size,
            error="image_too_large",
        )
    mime, _ = mimetypes.guess_type(target.name)
    if not mime or not mime.startswith("image/"):
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }.get(suffix, "application/octet-stream")
        if not mime.startswith("image/"):
            return _result("not_image", path=path_arg, error="not_image_mime")
    rel = target.relative_to(root).as_posix()
    display_url = _CORPUS_URL_PREFIX + quote(rel, safe="/")
    return _result(
        "ok",
        path=rel,
        display_url=display_url,
        mime=mime,
        byte_size=byte_size,
    )


def _result(
    status: str,
    *,
    path: str | None = None,
    display_url: str | None = None,
    mime: str | None = None,
    byte_size: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "path": path,
        "display_url": display_url,
        "mime": mime,
        "byte_size": byte_size,
        "error": error,
    }
