"""PPTX document parser (python-pptx) — text frames, tables, pictures."""

from __future__ import annotations

from io import BytesIO

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.domain.services.document_parsers.base import (
    MAX_EMBEDDED_IMAGE_BYTES,
    MAX_EMBEDDED_IMAGES,
    EmbeddedImage,
    ParseResult,
    image_placeholder,
)


class PptxParser:
    source_type = "pptx"
    suffixes = frozenset({".pptx"})

    def can_parse(self, suffix: str) -> bool:
        return str(suffix or "").lower() in self.suffixes

    def parse(self, data: bytes, *, filename: str) -> ParseResult:
        del filename
        presentation = Presentation(BytesIO(data))
        slides_out: list[str] = []
        images: list[EmbeddedImage] = []
        skipped_images = 0
        table_count = 0
        for index, slide in enumerate(presentation.slides, start=1):
            parts: list[str] = []
            for shape in slide.shapes:
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE or getattr(
                    shape, "shape_type", None
                ) == MSO_SHAPE_TYPE.PICTURE:
                    skipped_images += _try_add_picture(
                        shape, parts=parts, images=images
                    )
                    continue
                if shape.shape_type == MSO_SHAPE_TYPE.TABLE or getattr(
                    shape, "has_table", False
                ):
                    md = _table_to_markdown(shape.table)
                    if md:
                        parts.append(md)
                        table_count += 1
                    continue
                if not getattr(shape, "has_text_frame", False):
                    continue
                for paragraph in shape.text_frame.paragraphs:
                    line = "".join(run.text for run in paragraph.runs).strip()
                    if line:
                        parts.append(line)
            if parts:
                body = "\n\n".join(parts)
                slides_out.append(f"## Slide {index}\n\n{body}")
        text = "\n\n".join(slides_out).strip()
        return ParseResult(
            text=text,
            source_type=self.source_type,
            meta={
                "slide_count": len(presentation.slides),
                "table_count": table_count,
                "skipped_images": skipped_images,
            },
            images=tuple(images),
        )


def _try_add_picture(shape, *, parts: list[str], images: list[EmbeddedImage]) -> int:
    if len(images) >= MAX_EMBEDDED_IMAGES:
        return 1
    try:
        image = shape.image
        blob = image.blob
        mime = str(image.content_type or "application/octet-stream")
    except Exception:  # noqa: BLE001
        return 1
    if not isinstance(blob, (bytes, bytearray)) or not blob:
        return 1
    if len(blob) > MAX_EMBEDDED_IMAGE_BYTES:
        return 1
    if not mime.startswith("image/"):
        return 1
    index = len(images) + 1
    images.append(EmbeddedImage(index=index, mime=mime, data=bytes(blob)))
    parts.append(image_placeholder(index))
    return 0


def _cell_text(cell) -> str:
    parts: list[str] = []
    for paragraph in cell.text_frame.paragraphs:
        line = "".join(run.text for run in paragraph.runs).strip()
        if line:
            parts.append(line)
    return " ".join(parts).replace("|", "\\|").replace("\n", " ")


def _table_to_markdown(table) -> str:
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
