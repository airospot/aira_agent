"""Per-type document parsers for office uploads."""

from app.domain.services.document_parsers.base import (
    EmbeddedImage,
    DocumentParser,
    ParseResult,
)
from app.domain.services.document_parsers.registry import OFFICE_SUFFIXES, get_parser

__all__ = [
    "DocumentParser",
    "EmbeddedImage",
    "OFFICE_SUFFIXES",
    "ParseResult",
    "get_parser",
]
