"""Serve sandbox corpus images under /agent/corpus/<path> (tenant-scoped)."""

from __future__ import annotations

import mimetypes

from flask import current_app, send_file

from app.core.security import require_tenant, role_required
from app.interfaces.web.agent_routes.blueprint import agent_bp
from app.interfaces.web.agent_routes.http_cache import apply_sensitive_file_headers
from app.interfaces.web.agent_routes.tenant import tenant_ids
from app.shared.corpus_path_sandbox import resolve_under_corpus
from app.shared.tenant_storage import TenantStorageError, resolve_tenant_storage

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
_MAX_IMAGE_BYTES = 5_000_000


@agent_bp.get("/corpus/<path:relpath>")
@require_tenant
@role_required(["Admin", "Super Admin"])
def corpus_media(relpath: str):
    """Return a corpus image if path stays inside the verified tenant corpus."""
    customer_id, _user_id = tenant_ids()
    if not customer_id:
        return ("Forbidden", 403)
    try:
        storage = resolve_tenant_storage(customer_id, current_app.config)
    except TenantStorageError:
        return ("Forbidden", 403)

    root = storage.corpus_root
    target = resolve_under_corpus(root, relpath)
    if target is None or not target.is_file():
        return ("Not found", 404)
    if target.suffix.lower() not in _IMAGE_SUFFIXES:
        return ("Unsupported media type", 415)
    try:
        size = target.stat().st_size
    except OSError:
        return ("Not found", 404)
    if size > _MAX_IMAGE_BYTES:
        return ("Payload too large", 413)
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
        }.get(target.suffix.lower())
    if not mime or not mime.startswith("image/"):
        return ("Unsupported media type", 415)
    response = send_file(target, mimetype=mime, conditional=True, max_age=0)
    return apply_sensitive_file_headers(response)
