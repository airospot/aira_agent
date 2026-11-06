"""Upload a document into the agent corpus (data/corpus)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, jsonify, request

from app.core.security import require_tenant, role_required
from app.domain.agents.flow.tools._corpus import TEXT_SUFFIXES, resolve_corpus_root
from app.domain.services.document_parsers import OFFICE_SUFFIXES, get_parser
from app.domain.services.document_parsers.vision_ocr import fill_image_placeholders
from app.interfaces.web.agent_routes.routes import agent_bp

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_TEXT_UPLOAD_BYTES = 2_000_000
_MAX_OFFICE_UPLOAD_BYTES = 10_000_000
_ALLOWED_SUFFIXES = TEXT_SUFFIXES | OFFICE_SUFFIXES
_EXTRACTED_DIRNAME = "extracted_data"


def _safe_stem(name: str) -> str | None:
    raw = Path(str(name or "")).name.strip()
    if not raw or raw in {".", ".."}:
        return None
    stem = Path(raw).stem
    cleaned = _SAFE_NAME.sub("_", stem).strip("._-") or "upload"
    return cleaned[:80]


def _safe_filename(name: str) -> tuple[str, str] | None:
    """Return (safe_stem, suffix) when the upload type is allowed."""
    raw = Path(str(name or "")).name.strip()
    if not raw or raw in {".", ".."}:
        return None
    suffix = Path(raw).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        return None
    stem = _safe_stem(raw)
    if stem is None:
        return None
    return stem, suffix


def _unique_dest(root: Path, stem: str, suffix: str) -> Path:
    dest = root / f"{stem}{suffix}"
    if not dest.exists():
        return dest
    n = 2
    while True:
        candidate = root / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def _unique_extracted_dir(extracted_root: Path, stem: str) -> Path:
    dest = extracted_root / stem
    if not dest.exists():
        return dest
    n = 2
    while True:
        candidate = extracted_root / f"{stem}_{n}"
        if not candidate.exists():
            return candidate
        n += 1


def _render_parsed_markdown(*, source_filename: str, source_type: str, text: str) -> str:
    header = f"<!-- source: {source_filename} type: {source_type} -->\n\n"
    return header + text.strip() + "\n"


_MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


def _ext_for_mime(mime: str) -> str:
    return _MIME_TO_EXT.get(str(mime or "").lower(), ".bin")


def _save_embedded_images(out_dir: Path, images) -> list[dict]:
    """Write ``images/img_NNN.ext`` under the per-document folder; return meta rows."""
    if not images:
        return []
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict] = []
    for image in images:
        ext = _ext_for_mime(image.mime)
        name = f"img_{image.index:03d}{ext}"
        path = images_dir / name
        path.write_bytes(image.data)
        rel = f"images/{name}"
        saved.append(
            {
                "index": image.index,
                "path": rel,
                "mime": image.mime,
                "byte_size": len(image.data),
            }
        )
    return saved


def _annotate_image_files(text: str, saved_images: list[dict]) -> str:
    """Insert relative image file refs next to OCR section headings."""
    out = text
    for item in saved_images:
        heading = f"## Embedded image {item['index']}"
        needle = heading + "\n\n"
        replacement = (
            f"{heading}\n\n"
            f"<!-- image_file: {item['path']} -->\n"
            f"![]({item['path']})\n\n"
        )
        if needle in out:
            out = out.replace(needle, replacement, 1)
        elif heading in out:
            out = out.replace(heading, replacement.rstrip(), 1)
    return out


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _find_cached_extraction(extracted_root: Path, source_sha256: str) -> dict | None:
    if not extracted_root.is_dir():
        return None
    for meta_path in extracted_root.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        if str(meta.get("source_sha256") or "") != source_sha256:
            continue
        content_path = meta_path.parent / "content.md"
        if not content_path.is_file():
            continue
        rel = content_path.relative_to(extracted_root.parent).as_posix()
        images = meta.get("images") if isinstance(meta.get("images"), list) else []
        return {
            "path": rel,
            "byte_size": content_path.stat().st_size,
            "image_count": int(meta.get("image_count") or 0),
            "source_filename": str(meta.get("source_filename") or ""),
            "images": images,
        }
    return None


@agent_bp.post("/documents/upload")
@require_tenant
@role_required(["Admin", "Super Admin"])
def document_upload():
    """Save an uploaded document under AGENT_CORPUS_DIR (office → extracted_data)."""
    uploaded = request.files.get("file") or request.files.get("document")
    if uploaded is None or not str(uploaded.filename or "").strip():
        return jsonify({"ok": False, "error": "file_required"}), 400

    source_filename = Path(uploaded.filename).name
    parsed_name = _safe_filename(source_filename)
    if parsed_name is None:
        allowed = ", ".join(sorted(_ALLOWED_SUFFIXES))
        return jsonify({"ok": False, "error": "unsupported_type", "allowed": allowed}), 400

    stem, suffix = parsed_name
    is_office = suffix in OFFICE_SUFFIXES
    max_bytes = _MAX_OFFICE_UPLOAD_BYTES if is_office else _MAX_TEXT_UPLOAD_BYTES
    data = uploaded.read(max_bytes + 1)
    if len(data) > max_bytes:
        return jsonify({"ok": False, "error": "file_too_large", "max_bytes": max_bytes}), 400

    root = resolve_corpus_root(current_app.config)
    root.mkdir(parents=True, exist_ok=True)

    if is_office:
        source_sha = _sha256_hex(data)
        extracted_root = root / _EXTRACTED_DIRNAME
        extracted_root.mkdir(parents=True, exist_ok=True)
        cached = _find_cached_extraction(extracted_root, source_sha)
        if cached is not None:
            return jsonify(
                {
                    "ok": True,
                    "path": cached["path"],
                    "source_filename": source_filename,
                    "parsed": True,
                    "cached": True,
                    "image_count": cached["image_count"],
                    "images": cached.get("images") or [],
                    "byte_size": cached["byte_size"],
                    "message": (
                        f"{source_filename} cache'ten alındı: {cached['path']}"
                    ),
                }
            )

        parser = get_parser(suffix)
        if parser is None:
            return jsonify({"ok": False, "error": "unsupported_type"}), 400
        try:
            result = parser.parse(data, filename=source_filename)
        except Exception as exc:  # noqa: BLE001
            return jsonify(
                {
                    "ok": False,
                    "error": "parse_failed",
                    "detail": type(exc).__name__,
                }
            ), 400

        out_dir = _unique_extracted_dir(extracted_root, stem)
        out_dir.mkdir(parents=True, exist_ok=False)
        saved_images = _save_embedded_images(out_dir, result.images)

        filled = fill_image_placeholders(
            result.text,
            result.images,
            config=current_app.config,
        )
        filled = _annotate_image_files(filled, saved_images)
        if not filled.strip() and not result.images:
            return jsonify({"ok": False, "error": "empty_text"}), 400
        if not filled.strip():
            return jsonify({"ok": False, "error": "empty_text"}), 400

        body = _render_parsed_markdown(
            source_filename=source_filename,
            source_type=result.source_type,
            text=filled,
        )
        payload = body.encode("utf-8")
        content_path = out_dir / "content.md"
        content_path.write_bytes(payload)

        model = str(
            current_app.config.get("KNOWLEDGE_FLOW_LLM_MODEL")
            or "qwen3.5:9b"
        )
        meta = {
            "source_filename": source_filename,
            "source_type": result.source_type,
            "source_sha256": source_sha,
            "image_count": len(result.images),
            "skipped_images": int((result.meta or {}).get("skipped_images") or 0),
            "ocr_model": model if result.images else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "parser_meta": dict(result.meta or {}),
            "images": saved_images,
        }
        (out_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rel = content_path.relative_to(root).as_posix()
        return jsonify(
            {
                "ok": True,
                "path": rel,
                "source_filename": source_filename,
                "parsed": True,
                "cached": False,
                "image_count": len(result.images),
                "images": saved_images,
                "byte_size": len(payload),
                "message": (
                    f"{source_filename} parse edilip {rel} olarak corpus'a yüklendi"
                ),
            }
        )

    if b"\x00" in data[:512]:
        return jsonify({"ok": False, "error": "binary_rejected"}), 400

    dest = _unique_dest(root, stem, suffix)
    dest.write_bytes(data)
    rel = dest.name
    return jsonify(
        {
            "ok": True,
            "path": rel,
            "source_filename": source_filename,
            "parsed": False,
            "cached": False,
            "byte_size": len(data),
            "message": f"{rel} corpus'a yüklendi",
        }
    )
