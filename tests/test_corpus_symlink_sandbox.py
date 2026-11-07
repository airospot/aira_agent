"""A00: corpus path sandbox rejects symlink escape."""

from __future__ import annotations

from pathlib import Path

from app.shared.corpus_path_sandbox import (
    is_resolved_under_corpus,
    resolve_under_corpus,
)


def test_plain_file_inside_corpus_allowed(tmp_corpus: Path) -> None:
    target = tmp_corpus / "notes.md"
    target.write_text("ok", encoding="utf-8")
    assert is_resolved_under_corpus(tmp_corpus, target) is True
    assert resolve_under_corpus(tmp_corpus, "notes.md") == target.resolve()


def test_symlink_escape_rejected(tmp_corpus: Path, tmp_path: Path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("leak", encoding="utf-8")
    link = tmp_corpus / "escape.md"
    link.symlink_to(outside)
    assert is_resolved_under_corpus(tmp_corpus, link) is False
    assert resolve_under_corpus(tmp_corpus, "escape.md") is None


def test_broken_symlink_rejected(tmp_corpus: Path) -> None:
    link = tmp_corpus / "broken.md"
    link.symlink_to(tmp_corpus / "missing-target.md")
    assert is_resolved_under_corpus(tmp_corpus, link) is False
    assert resolve_under_corpus(tmp_corpus, "broken.md") is None


def test_dotdot_relative_rejected(tmp_corpus: Path) -> None:
    assert resolve_under_corpus(tmp_corpus, "../outside.md") is None
    assert resolve_under_corpus(tmp_corpus, "a/../../outside.md") is None
