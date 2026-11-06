"""DOCX document parser (python-docx) — paragraphs, tables, embedded images."""

from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.domain.services.document_parsers.base import (
    MAX_EMBEDDED_IMAGE_BYTES,
    MAX_EMBEDDED_IMAGES,
    EmbeddedImage,
    ParseResult,
    image_placeholder,
)

_A_BLIP = qn("a:blip")
_R_EMBED = qn("r:embed")
# VML namespace is not in python-docx nsmap defaults.
_V_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"
_R_ID_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


class DocxParser:
    source_type = "docx"
    suffixes = frozenset({".docx"})

    def can_parse(self, suffix: str) -> bool:
        return str(suffix or "").lower() in self.suffixes

    def parse(self, data: bytes, *, filename: str) -> ParseResult:
        del filename
        document = Document(BytesIO(data))
        blocks: list[str] = []
        images: list[EmbeddedImage] = []
        skipped_images = 0
        paragraph_count = 0
        table_count = 0

        for kind, item in _iter_body_blocks(document):
            if kind == "paragraph":
                text = item.text.strip()
                if text:
                    blocks.append(text)
                    paragraph_count += 1
                skipped_images += _append_element_images(
                    document,
                    item._element,
                    blocks=blocks,
                    images=images,
                )
            else:
                md = _table_to_markdown(item)
                if md:
                    blocks.append(md)
                    table_count += 1
                skipped_images += _append_element_images(
                    document,
                    item._tbl,
                    blocks=blocks,
                    images=images,
                )

        text = "\n\n".join(blocks).strip()
        return ParseResult(
            text=text,
            source_type=self.source_type,
            meta={
                "paragraph_count": paragraph_count,
                "table_count": table_count,
                "skipped_images": skipped_images,
            },
            images=tuple(images),
        )


def _iter_body_blocks(document: Document):
    """Yield (kind, block) preserving Word body order (paragraph / table)."""
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield "paragraph", Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield "table", Table(child, document)


def _append_element_images(
    document: Document,
    element,
    *,
    blocks: list[str],
    images: list[EmbeddedImage],
) -> int:
    """Extract blip images under element; return count of skipped images."""
    skipped = 0
    seen_rids: set[str] = set()
    for blip in element.iter(_A_BLIP):
        rid = blip.get(_R_EMBED)
        if not rid or rid in seen_rids:
            continue
        seen_rids.add(rid)
        skipped += _try_add_image(
            document, rid, blocks=blocks, images=images
        )
    for imagedata in element.iter(_V_IMAGEDATA):
        rid = imagedata.get(_R_EMBED) or imagedata.get(_R_ID_ATTR)
        if not rid or rid in seen_rids:
            continue
        seen_rids.add(rid)
        skipped += _try_add_image(
            document, rid, blocks=blocks, images=images
        )
    return skipped


def _try_add_image(
    document: Document,
    rid: str,
    *,
    blocks: list[str],
    images: list[EmbeddedImage],
) -> int:
    if len(images) >= MAX_EMBEDDED_IMAGES:
        return 1
    try:
        part = document.part.related_parts[rid]
    except KeyError:
        return 1
    blob = getattr(part, "blob", None)
    if not isinstance(blob, (bytes, bytearray)) or not blob:
        return 1
    if len(blob) > MAX_EMBEDDED_IMAGE_BYTES:
        return 1
    mime = str(getattr(part, "content_type", "") or "application/octet-stream")
    if not mime.startswith("image/"):
        return 1
    index = len(images) + 1
    images.append(EmbeddedImage(index=index, mime=mime, data=bytes(blob)))
    blocks.append(image_placeholder(index))
    return 0


def _cell_text(cell) -> str:
    parts = [p.text.strip() for p in cell.paragraphs if p.text and p.text.strip()]
    return " ".join(parts).replace("|", "\\|").replace("\n", " ")


def _table_to_markdown(table: Table) -> str:
    rows: list[list[str]] = []
    for row in table.rows:
        rows.append([_cell_text(cell) for cell in row.cells])
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    normalized = [r + [""] * (width - len(r)) for r in rows]
    header = normalized[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
