"""Shared corpus path sandbox for file_read / file_search."""

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
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def is_probably_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    try:
        sample = path.read_bytes()[:512]
    except OSError:
        return False
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False
