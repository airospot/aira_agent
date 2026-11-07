"""Upload into tenant storage: keep originals; publish derived corpus atomically."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, jsonify, request

from app.core.security import require_tenant, role_required
from app.domain.services.document_parsers import OFFICE_SUFFIXES, get_parser
from app.domain.services.document_parsers.vision_ocr import fill_image_placeholders
from app.interfaces.web.agent_routes.blueprint import agent_bp
from app.interfaces.web.agent_routes.tenant import tenant_ids
from app.shared.corpus_path_sandbox import TEXT_SUFFIXES
from app.shared.tenant_storage import TenantStorage, TenantStorageError, resolve_tenant_storage

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_TEXT_UPLOAD_BYTES = 2_000_000
_MAX_OFFICE_UPLOAD_BYTES = 10_000_000
_ALLOWED_SUFFIXES = TEXT_SUFFIXES | OFFICE_SUFFIXES
_EXTRACTED_DIRNAME = "extracted_data"
_MANIFEST_NAME = "manifest.json"


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


def _download_url(upload_id: str) -> str:
    return f"/agent/documents/{upload_id}/original"


def _write_manifest(upload_dir: Path, payload: dict) -> None:
    path = upload_dir / _MANIFEST_NAME
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_manifest(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _find_cached_extraction(storage: TenantStorage, source_sha256: str) -> dict | None:
    """Same-tenant only: ready extraction with matching source hash."""
    extracted_root = storage.corpus_root / _EXTRACTED_DIRNAME
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
        try:
            rel = content_path.relative_to(storage.corpus_root).as_posix()
        except ValueError:
            continue
        images = meta.get("images") if isinstance(meta.get("images"), list) else []
        return {
            "path": rel,
            "byte_size": content_path.stat().st_size,
            "image_count": int(meta.get("image_count") or 0),
            "source_filename": str(meta.get("source_filename") or ""),
            "images": images,
        }
    return None


def _store_original(
    storage: TenantStorage,
    *,
    upload_id: str,
    source_filename: str,
    stored_name: str,
    data: bytes,
) -> tuple[Path, Path, str]:
    upload_dir = storage.upload_dir(upload_id)
    upload_dir.mkdir(parents=True, exist_ok=False)
    original = storage.original_path(upload_id, stored_name)
    original.write_bytes(data)
    digest = _sha256_hex(data)
    if _sha256_hex(original.read_bytes()) != digest:
        raise RuntimeError("original_integrity_failed")
    return upload_dir, original, digest


@agent_bp.post("/documents/upload")
@require_tenant
@role_required(["Admin", "Super Admin"])
def document_upload():
    """Accept upload into tenant uploads/; publish derived files under tenant corpus/."""
    customer_id, _user_id = tenant_ids()
    if not customer_id:
        return jsonify({"ok": False, "error": "tenant_required"}), 403

    try:
        storage = resolve_tenant_storage(customer_id, current_app.config)
    except TenantStorageError as exc:
        return jsonify({"ok": False, "error": str(exc) or "tenant_required"}), 403

    uploaded = request.files.get("file") or request.files.get("document")
    if uploaded is None or not str(uploaded.filename or "").strip():
        return jsonify({"ok": False, "error": "file_required"}), 400

    source_filename = Path(uploaded.filename).name
    parsed_name = _safe_filename(source_filename)
    if parsed_name is None:
        allowed = ", ".join(sorted(_ALLOWED_SUFFIXES))
        return jsonify({"ok": False, "error": "unsupported_type", "allowed": allowed}), 400

    stem, suffix = parsed_name
    stored_name = f"{stem}{suffix}"
    is_office = suffix in OFFICE_SUFFIXES
    max_bytes = _MAX_OFFICE_UPLOAD_BYTES if is_office else _MAX_TEXT_UPLOAD_BYTES
    data = uploaded.read(max_bytes + 1)
    if len(data) > max_bytes:
        return jsonify({"ok": False, "error": "file_too_large", "max_bytes": max_bytes}), 400

    if not is_office and b"\x00" in data[:512]:
        return jsonify({"ok": False, "error": "binary_rejected"}), 400

    upload_id = uuid.uuid4().hex
    try:
        upload_dir, original_path, source_sha = _store_original(
            storage,
            upload_id=upload_id,
            source_filename=source_filename,
            stored_name=stored_name,
            data=data,
        )
    except (OSError, TenantStorageError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": "store_failed", "detail": type(exc).__name__}), 500

    created_at = datetime.now(timezone.utc).isoformat()
    base_manifest = {
        "upload_id": upload_id,
        "customer_id": storage.customer_id,
        "source_filename": source_filename,
        "stored_filename": stored_name,
        "original_sha256": source_sha,
        "byte_size": len(data),
        "status": "uploaded",
        "error_code": None,
        "corpus_relative_path": None,
        "created_at": created_at,
        "cached": False,
    }
    _write_manifest(upload_dir, base_manifest)

    if is_office:
        cached = _find_cached_extraction(storage, source_sha)
        if cached is not None:
            # Original already stored; reuse same-tenant derived path only.
            base_manifest.update(
                {
                    "status": "ready",
                    "corpus_relative_path": cached["path"],
                    "cached": True,
                    "image_count": cached["image_count"],
                    "images": cached.get("images") or [],
                }
            )
            _write_manifest(upload_dir, base_manifest)
            assert _sha256_hex(original_path.read_bytes()) == source_sha
            return jsonify(
                {
                    "ok": True,
                    "upload_id": upload_id,
                    "download_url": _download_url(upload_id),
                    "path": cached["path"],
                    "source_filename": source_filename,
                    "display_name": source_filename,
                    "suggest_prompt": f"{source_filename} dosyasını oku ve özetle",
                    "original_sha256": source_sha,
                    "status": "ready",
                    "parsed": True,
                    "cached": True,
                    "image_count": cached["image_count"],
                    "images": cached.get("images") or [],
                    "byte_size": cached["byte_size"],
                    "message": f"{source_filename} yüklendi (önceki çıkarımdan).",
                }
            )

        base_manifest["status"] = "processing"
        _write_manifest(upload_dir, base_manifest)

        parser = get_parser(suffix)
        if parser is None:
            base_manifest["status"] = "failed"
            base_manifest["error_code"] = "unsupported_type"
            _write_manifest(upload_dir, base_manifest)
            return jsonify(
                {
                    "ok": False,
                    "error": "unsupported_type",
                    "upload_id": upload_id,
                    "download_url": _download_url(upload_id),
                    "status": "failed",
                    "original_preserved": True,
                    "original_sha256": source_sha,
                }
            ), 400

        staging = upload_dir / "staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        staging_out = staging / stem

        try:
            result = parser.parse(data, filename=source_filename)
            staging_out.mkdir(parents=True, exist_ok=False)
            saved_images = _save_embedded_images(staging_out, result.images)
            filled = fill_image_placeholders(
                result.text,
                result.images,
                config=current_app.config,
            )
            filled = _annotate_image_files(filled, saved_images)
            if not filled.strip():
                raise ValueError("empty_text")
            body = _render_parsed_markdown(
                source_filename=source_filename,
                source_type=result.source_type,
                text=filled,
            )
            payload = body.encode("utf-8")
            (staging_out / "content.md").write_bytes(payload)
            model = str(
                current_app.config.get("KNOWLEDGE_FLOW_LLM_MODEL") or "qwen3.5:9b"
            )
            meta = {
                "source_filename": source_filename,
                "source_type": result.source_type,
                "source_sha256": source_sha,
                "upload_id": upload_id,
                "image_count": len(result.images),
                "skipped_images": int((result.meta or {}).get("skipped_images") or 0),
                "ocr_model": model if result.images else None,
                "created_at": created_at,
                "parser_meta": dict(result.meta or {}),
                "images": saved_images,
            }
            (staging_out / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            extracted_root = storage.corpus_root / _EXTRACTED_DIRNAME
            extracted_root.mkdir(parents=True, exist_ok=True)
            final_dir = _unique_extracted_dir(extracted_root, stem)
            staging_out.rename(final_dir)
            shutil.rmtree(staging, ignore_errors=True)

            content_path = final_dir / "content.md"
            rel = content_path.relative_to(storage.corpus_root).as_posix()
            base_manifest.update(
                {
                    "status": "ready",
                    "error_code": None,
                    "corpus_relative_path": rel,
                    "cached": False,
                    "image_count": len(result.images),
                    "images": saved_images,
                }
            )
            _write_manifest(upload_dir, base_manifest)
            assert _sha256_hex(original_path.read_bytes()) == source_sha
            return jsonify(
                {
                    "ok": True,
                    "upload_id": upload_id,
                    "download_url": _download_url(upload_id),
                    "path": rel,
                    "source_filename": source_filename,
                    "display_name": source_filename,
                    "suggest_prompt": f"{source_filename} dosyasını oku ve özetle",
                    "original_sha256": source_sha,
                    "status": "ready",
                    "parsed": True,
                    "cached": False,
                    "image_count": len(result.images),
                    "images": saved_images,
                    "byte_size": len(payload),
                    "message": f"{source_filename} yüklendi.",
                }
            )
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(staging, ignore_errors=True)
            err = "empty_text" if str(exc) == "empty_text" else "parse_failed"
            detail = type(exc).__name__ if err == "parse_failed" else None
            base_manifest["status"] = "failed"
            base_manifest["error_code"] = err
            _write_manifest(upload_dir, base_manifest)
            assert _sha256_hex(original_path.read_bytes()) == source_sha
            body = {
                "ok": False,
                "error": err,
                "upload_id": upload_id,
                "download_url": _download_url(upload_id),
                "status": "failed",
                "original_preserved": True,
                "original_sha256": source_sha,
            }
            if detail:
                body["detail"] = detail
            return jsonify(body), 400

    # Plain text → staging then atomic publish into tenant corpus root.
    staging = upload_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    staging_file = staging / stored_name
    staging_file.write_bytes(data)
    final = _unique_dest(storage.corpus_root, stem, suffix)
    staging_file.replace(final)
    shutil.rmtree(staging, ignore_errors=True)
    rel = final.relative_to(storage.corpus_root).as_posix()
    base_manifest.update(
        {
            "status": "ready",
            "corpus_relative_path": rel,
            "cached": False,
        }
    )
    _write_manifest(upload_dir, base_manifest)
    assert _sha256_hex(original_path.read_bytes()) == source_sha
    return jsonify(
        {
            "ok": True,
            "upload_id": upload_id,
            "download_url": _download_url(upload_id),
            "path": rel,
            "source_filename": source_filename,
            "display_name": source_filename,
            "suggest_prompt": f"{source_filename} dosyasını oku ve özetle",
            "original_sha256": source_sha,
            "status": "ready",
            "parsed": False,
            "cached": False,
            "byte_size": len(data),
            "message": f"{source_filename} yüklendi.",
        }
    )
