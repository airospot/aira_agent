"""Authorized download of tenant-scoped original upload bytes."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from flask import current_app, send_file

from app.core.security import require_tenant, role_required
from app.interfaces.web.agent_routes.blueprint import agent_bp
from app.interfaces.web.agent_routes.http_cache import apply_sensitive_file_headers
from app.interfaces.web.agent_routes.tenant import tenant_ids
from app.shared.tenant_storage import TenantStorageError, resolve_tenant_storage

_UPLOAD_ID_RE_LEN = 64  # uuid4.hex is 32; allow up to 64 alnum


def _load_manifest(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


@agent_bp.get("/documents/<upload_id>/original")
@require_tenant
@role_required(["Admin", "Super Admin"])
def document_original_download(upload_id: str):
    """Stream original bytes via manifest — never trust client filesystem paths."""
    customer_id, _user_id = tenant_ids()
    if not customer_id:
        return ("Forbidden", 403)

    uid = str(upload_id or "").strip()
    if (
        not uid
        or len(uid) > _UPLOAD_ID_RE_LEN
        or any(ch for ch in uid if not (ch.isalnum() or ch in "-_"))
    ):
        return ("Not found", 404)

    try:
        storage = resolve_tenant_storage(customer_id, current_app.config)
        manifest_path = storage.manifest_path(uid)
    except TenantStorageError:
        return ("Not found", 404)

    if not manifest_path.is_file():
        return ("Not found", 404)

    manifest = _load_manifest(manifest_path)
    if not manifest:
        return ("Not found", 404)
    if int(manifest.get("customer_id") or 0) != storage.customer_id:
        return ("Not found", 404)

    stored = str(manifest.get("stored_filename") or "").strip()
    source_name = str(manifest.get("source_filename") or stored or "download")
    try:
        target = storage.original_path(uid, stored)
    except TenantStorageError:
        return ("Not found", 404)
    if not target.is_file():
        return ("Not found", 404)

    mime, _ = mimetypes.guess_type(source_name)
    if not mime:
        mime = "application/octet-stream"
    # Force download + nosniff so HTML/text uploads never render as pages.
    response = send_file(
        target,
        mimetype=mime,
        as_attachment=True,
        download_name=Path(source_name).name,
        conditional=True,
        max_age=0,
    )
    return apply_sensitive_file_headers(response)
