"""Per-tenant document/corpus roots from server-verified customer_id."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_TENANT_DATA_ROOT = Path("data/tenants")


class TenantStorageError(ValueError):
    """Missing/invalid tenant or path escape — fail closed (no shared corpus fallback)."""


def _positive_customer_id(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise TenantStorageError("customer_id_required")
    if isinstance(value, int):
        if value <= 0:
            raise TenantStorageError("customer_id_invalid")
        return value
    raise TenantStorageError("customer_id_invalid")


def resolve_tenant_data_root(config: Mapping[str, Any] | None = None) -> Path:
    raw = None
    if config is not None:
        raw = config.get("TENANT_DATA_ROOT")
    root = Path(str(raw or DEFAULT_TENANT_DATA_ROOT)).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    else:
        root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ensure_under(root: Path, candidate: Path) -> Path:
    try:
        resolved_root = root.resolve()
        resolved = candidate.resolve()
        resolved.relative_to(resolved_root)
    except (ValueError, OSError, RuntimeError) as exc:
        raise TenantStorageError("tenant_path_escape") from exc
    return resolved


@dataclass(frozen=True)
class TenantStorage:
    """Request-scoped paths; never mutate global Flask config from these."""

    customer_id: int
    data_root: Path
    tenant_root: Path
    uploads_root: Path
    corpus_root: Path

    def upload_dir(self, upload_id: str) -> Path:
        uid = str(upload_id or "").strip()
        if not uid or uid in {".", ".."} or "/" in uid or "\\" in uid:
            raise TenantStorageError("upload_id_invalid")
        path = self.uploads_root / uid
        return _ensure_under(self.uploads_root, path)

    def manifest_path(self, upload_id: str) -> Path:
        return self.upload_dir(upload_id) / "manifest.json"

    def original_path(self, upload_id: str, stored_filename: str) -> Path:
        name = Path(str(stored_filename or "")).name
        if not name or name in {".", ".."}:
            raise TenantStorageError("stored_filename_invalid")
        path = self.upload_dir(upload_id) / name
        return _ensure_under(self.upload_dir(upload_id), path)


def resolve_tenant_storage(
    customer_id: Any,
    config: Mapping[str, Any] | None = None,
) -> TenantStorage:
    """Build tenant roots under TENANT_DATA_ROOT; no shared-corpus fallback."""
    cid = _positive_customer_id(customer_id)
    data_root = resolve_tenant_data_root(config)
    # Integer segment only — blocks ../ and foreign path injection via id.
    tenant_root = _ensure_under(data_root, data_root / str(cid))
    uploads_root = tenant_root / "uploads"
    corpus_root = tenant_root / "corpus"
    uploads_root.mkdir(parents=True, exist_ok=True)
    corpus_root.mkdir(parents=True, exist_ok=True)
    _ensure_under(data_root, uploads_root)
    _ensure_under(data_root, corpus_root)
    return TenantStorage(
        customer_id=cid,
        data_root=data_root,
        tenant_root=tenant_root,
        uploads_root=uploads_root,
        corpus_root=corpus_root,
    )
