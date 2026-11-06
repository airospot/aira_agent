"""Shared types for document parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


IMAGE_PLACEHOLDER_TMPL = "{{{{IMAGE:{index}}}}}"
MAX_EMBEDDED_IMAGES = 8
MAX_EMBEDDED_IMAGE_BYTES = 2_000_000


@dataclass(frozen=True)
class EmbeddedImage:
    index: int
    mime: str
    data: bytes


@dataclass(frozen=True)
class ParseResult:
    text: str
    source_type: str
    meta: Mapping[str, Any] = field(default_factory=dict)
    images: tuple[EmbeddedImage, ...] = ()


class DocumentParser(Protocol):
    """One parser per office/binary document type."""

    source_type: str
    suffixes: frozenset[str]

    def can_parse(self, suffix: str) -> bool:
        ...

    def parse(self, data: bytes, *, filename: str) -> ParseResult:
        ...


def image_placeholder(index: int) -> str:
    return IMAGE_PLACEHOLDER_TMPL.format(index=index)
