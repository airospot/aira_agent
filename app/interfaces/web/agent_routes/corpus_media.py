"""Serve sandbox corpus images under /agent/corpus/<path>."""

from __future__ import annotations

import mimetypes

from flask import current_app, send_file

from app.core.security import require_tenant, role_required
from app.domain.agents.flow.tools._corpus import resolve_corpus_root, resolve_under_corpus
from app.interfaces.web.agent_routes.routes import agent_bp

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
_MAX_IMAGE_BYTES = 5_000_000


@agent_bp.get("/corpus/<path:relpath>")
@require_tenant
@role_required(["Admin", "Super Admin"])
def corpus_media(relpath: str):
    """Return a corpus image file if path stays inside AGENT_CORPUS_DIR."""
    root = resolve_corpus_root(current_app.config)
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
    return send_file(target, mimetype=mime, conditional=True, max_age=3600)
