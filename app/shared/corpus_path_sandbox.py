"""Agent corpus path sandbox (resolve root; keep reads inside the corpus tree)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


DEFAULT_CORPUS_DIR = Path("data/corpus")
MAX_READ_BYTES = 64_000
TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".xml",
    ".rst",
    ".ini",
    ".cfg",
    ".log",
}


def resolve_corpus_root(config: Mapping[str, Any] | None = None) -> Path:
    raw = None
    if config is not None:
        raw = config.get("AGENT_CORPUS_DIR")
    root = Path(str(raw or DEFAULT_CORPUS_DIR)).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    else:
        root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_under_corpus(root: Path, relative: str) -> Path | None:
    """Return absolute path if ``relative`` stays inside ``root``; else None."""
    rel = str(relative or "").strip().lstrip("/")
    if not rel or rel.startswith("~") or ".." in Path(rel).parts:
        return None
    candidate = root / rel
    if not is_resolved_under_corpus(root, candidate):
        return None
    return candidate.resolve()


def is_resolved_under_corpus(root: Path, path: Path) -> bool:
    """True if ``path`` resolves to a real location inside ``root``.

    Catches ValueError (outside root), OSError (broken link / IO), and
    RuntimeError (symlink loops from Path.resolve). Not TOCTOU-safe.
    """
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_root)
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def read_limited_bytes(path: Path, *, max_bytes: int) -> tuple[bytes, bool]:
    """Read at most ``max_bytes`` without loading the whole file into memory.

    Returns ``(chunk, truncated)``. Does not claim to preempt a blocked OS read.
    """
    limit = max(0, int(max_bytes))
    with path.open("rb") as fh:
        chunk = fh.read(limit + 1)
    truncated = len(chunk) > limit
    if truncated:
        chunk = chunk[:limit]
    return chunk, truncated


def is_probably_text(path: Path, *, probe_bytes: int = 512) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    try:
        sample, _ = read_limited_bytes(path, max_bytes=max(1, int(probe_bytes)))
    except OSError:
        return False
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False
