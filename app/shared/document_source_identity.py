"""Resolve user-facing source filenames for tenant corpus paths.

Technical corpus-relative paths stay the tool execution key. Original upload
names come from sandboxed meta.json / upload manifests — never invented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from app.shared.corpus_path_sandbox import is_resolved_under_corpus

_EXTRACTED = "extracted_data"
_UNKNOWN_DISPLAY = "orijinal adı bilinmiyor"
_AMBIGUOUS_DISPLAY = "orijinal adı belirsiz"


@dataclass(frozen=True)
class DocumentSourceIdentity:
    """Verified source naming for one corpus-relative path."""

    path: str
    source_filename: str | None
    display_name: str
    source_known: bool
    source_ambiguous: bool
    alternate_source_filenames: tuple[str, ...] = ()

    def as_tool_fields(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "source_filename": self.source_filename,
            "display_name": self.display_name,
            "source_known": self.source_known,
            "source_ambiguous": self.source_ambiguous,
        }
        if self.alternate_source_filenames:
            out["alternate_source_filenames"] = list(self.alternate_source_filenames)
        return out


def _posix_rel(root: Path, path: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def _read_json_file(root: Path, path: Path) -> dict[str, Any] | None:
    if not is_resolved_under_corpus(root, path):
        return None
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _tenant_layout(corpus_root: Path) -> tuple[Path, Path] | None:
    """Return (tenant_root, uploads_root) when corpus_root is …/<id>/corpus."""
    try:
        corpus_r = corpus_root.resolve()
    except (OSError, RuntimeError):
        return None
    tenant_root = corpus_r.parent
    if (tenant_root / "corpus").resolve() != corpus_r:
        return None
    uploads = tenant_root / "uploads"
    return tenant_root, uploads


def _extracted_doc_dir(corpus_root: Path, relative: str) -> Path | None:
    parts = Path(str(relative or "").replace("\\", "/")).parts
    if len(parts) < 2 or parts[0] != _EXTRACTED:
        return None
    doc_dir = corpus_root / parts[0] / parts[1]
    if not is_resolved_under_corpus(corpus_root, doc_dir):
        return None
    return doc_dir


def _names_from_meta(corpus_root: Path, relative: str) -> set[str]:
    doc_dir = _extracted_doc_dir(corpus_root, relative)
    if doc_dir is None:
        return set()
    meta = _read_json_file(corpus_root, doc_dir / "meta.json")
    if not meta:
        return set()
    name = str(meta.get("source_filename") or "").strip()
    if not name or name in {".", ".."}:
        return set()
    return {Path(name).name}


def _iter_manifests(uploads_root: Path) -> Iterator[dict[str, Any]]:
    try:
        if not uploads_root.is_dir():
            return
    except OSError:
        return
    try:
        children = sorted(uploads_root.iterdir())
    except OSError:
        return
    for child in children:
        if not child.is_dir():
            continue
        if not is_resolved_under_corpus(uploads_root, child):
            continue
        manifest_path = child / "manifest.json"
        meta = _read_json_file(uploads_root, manifest_path)
        if meta:
            yield meta


def _same_document_path(a: str, b: str) -> bool:
    if a == b:
        return True
    pa, pb = Path(a).parts, Path(b).parts
    return (
        len(pa) >= 2
        and len(pb) >= 2
        and pa[0] == _EXTRACTED
        and pb[0] == _EXTRACTED
        and pa[1] == pb[1]
    )


def _names_from_manifests(corpus_root: Path, relative: str) -> set[str]:
    layout = _tenant_layout(corpus_root)
    if layout is None:
        return set()
    _tenant, uploads = layout
    rel = str(relative or "").replace("\\", "/").lstrip("/")
    names: set[str] = set()
    for manifest in _iter_manifests(uploads):
        corpus_rel = str(manifest.get("corpus_relative_path") or "").replace("\\", "/").lstrip("/")
        if not corpus_rel or not _same_document_path(corpus_rel, rel):
            continue
        name = str(manifest.get("source_filename") or "").strip()
        if name and name not in {".", ".."}:
            names.add(Path(name).name)
    return names


def resolve_document_source(
    corpus_root: Path,
    relative_path: str,
) -> DocumentSourceIdentity:
    """Resolve display/source names for a corpus-relative path (sandbox-safe)."""
    rel = str(relative_path or "").replace("\\", "/").lstrip("/")
    names = _names_from_meta(corpus_root, rel) | _names_from_manifests(corpus_root, rel)
    ordered = tuple(sorted(names))
    if len(ordered) == 1:
        name = ordered[0]
        return DocumentSourceIdentity(
            path=rel,
            source_filename=name,
            display_name=name,
            source_known=True,
            source_ambiguous=False,
        )
    if len(ordered) > 1:
        return DocumentSourceIdentity(
            path=rel,
            source_filename=None,
            display_name=_AMBIGUOUS_DISPLAY,
            source_known=False,
            source_ambiguous=True,
            alternate_source_filenames=ordered,
        )
    return DocumentSourceIdentity(
        path=rel,
        source_filename=None,
        display_name=_UNKNOWN_DISPLAY,
        source_known=False,
        source_ambiguous=False,
    )


@dataclass(frozen=True)
class SourceNameMatch:
    """One name-search hit: executable corpus path + verified original name."""

    path: str
    source_filename: str | None
    display_name: str
    match_via: str  # path|basename|source_filename


def iter_source_name_matches(
    corpus_root: Path,
    *,
    query: str,
    paths: list[Path],
) -> list[SourceNameMatch]:
    """Match query against technical path/basename and verified original names."""
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    hits: list[SourceNameMatch] = []
    seen: set[tuple[str, str | None]] = set()

    def _add(path_rel: str, source_filename: str | None, display_name: str, via: str) -> None:
        key = (path_rel, source_filename)
        if key in seen:
            return
        # Ensure target exists under corpus.
        target = corpus_root / path_rel
        if not is_resolved_under_corpus(corpus_root, target):
            return
        if not target.is_file():
            # Prefer content.md when match was on a doc folder name via meta only.
            return
        seen.add(key)
        hits.append(
            SourceNameMatch(
                path=path_rel,
                source_filename=source_filename,
                display_name=display_name,
                match_via=via,
            )
        )

    for path in paths:
        if not is_resolved_under_corpus(corpus_root, path):
            continue
        rel = _posix_rel(corpus_root, path)
        if not rel:
            continue
        identity = resolve_document_source(corpus_root, rel)
        matched = False
        if needle in rel.lower():
            _add(rel, identity.source_filename, identity.display_name, "path")
            matched = True
        if needle in path.name.lower():
            _add(rel, identity.source_filename, identity.display_name, "basename")
            matched = True
        for alt in identity.alternate_source_filenames or (
            (identity.source_filename,) if identity.source_filename else ()
        ):
            if alt and needle in alt.lower():
                _add(rel, alt, alt, "source_filename")
                matched = True
        if not matched and identity.source_filename and needle in identity.source_filename.lower():
            _add(rel, identity.source_filename, identity.display_name, "source_filename")

    # Manifest-only names (e.g. cache reuse with a second original name).
    layout = _tenant_layout(corpus_root)
    if layout is not None:
        _tenant, uploads = layout
        for manifest in _iter_manifests(uploads):
            src = str(manifest.get("source_filename") or "").strip()
            corpus_rel = str(manifest.get("corpus_relative_path") or "").replace("\\", "/").lstrip("/")
            if not src or not corpus_rel:
                continue
            if needle not in src.lower() and needle not in Path(src).name.lower():
                continue
            target = corpus_root / corpus_rel
            if not is_resolved_under_corpus(corpus_root, target) or not target.is_file():
                continue
            _add(corpus_rel, Path(src).name, Path(src).name, "source_filename")

    return hits
