"""Resolve a document parser by file suffix."""

from __future__ import annotations

from app.domain.services.document_parsers.base import DocumentParser
from app.domain.services.document_parsers.docx_parser import DocxParser
from app.domain.services.document_parsers.pdf_parser import PdfParser
from app.domain.services.document_parsers.pptx_parser import PptxParser

_PARSERS: tuple[DocumentParser, ...] = (
    PdfParser(),
    DocxParser(),
    PptxParser(),
)

OFFICE_SUFFIXES = frozenset(
    suffix for parser in _PARSERS for suffix in parser.suffixes
)


def get_parser(suffix: str) -> DocumentParser | None:
    needle = str(suffix or "").lower()
    if not needle:
        return None
    for parser in _PARSERS:
        if parser.can_parse(needle):
            return parser
    return None
