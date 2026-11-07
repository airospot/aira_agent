"""Cache / sniff headers for tenant-sensitive file responses."""

from __future__ import annotations

from flask import Response


def apply_sensitive_file_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
