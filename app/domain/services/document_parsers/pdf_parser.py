"""PDF document parser (pypdf) — page text + embedded images."""

from __future__ import annotations

import hashlib
from io import BytesIO

from pypdf import PdfReader

from app.domain.services.document_parsers.base import (
    MAX_EMBEDDED_IMAGE_BYTES,
    MAX_EMBEDDED_IMAGES,
    EmbeddedImage,
    ParseResult,
    image_placeholder,
)

_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}


class PdfParser:
    source_type = "pdf"
    suffixes = frozenset({".pdf"})

    def can_parse(self, suffix: str) -> bool:
        return str(suffix or "").lower() in self.suffixes

    def parse(self, data: bytes, *, filename: str) -> ParseResult:
        del filename
        reader = PdfReader(BytesIO(data))
        blocks: list[str] = []
        images: list[EmbeddedImage] = []
        skipped_images = 0
        seen_digests: set[str] = set()

        for page_no, page in enumerate(reader.pages, start=1):
            page_parts: list[str] = []
            extracted = (page.extract_text() or "").strip()
            if extracted:
                page_parts.append(extracted)
            try:
                page_images = list(page.images)
            except Exception:  # noqa: BLE001
                page_images = []
            for image_file in page_images:
                skipped_images += _try_add_pdf_image(
                    image_file,
                    parts=page_parts,
                    images=images,
                    seen_digests=seen_digests,
                )
            if page_parts:
                body = "\n\n".join(page_parts)
                blocks.append(f"## Page {page_no}\n\n{body}")

        text = "\n\n".join(blocks).strip()
        return ParseResult(
            text=text,
            source_type=self.source_type,
            meta={
                "page_count": len(reader.pages),
                "skipped_images": skipped_images,
            },
            images=tuple(images),
        )


def _try_add_pdf_image(
    image_file,
    *,
    parts: list[str],
    images: list[EmbeddedImage],
    seen_digests: set[str],
) -> int:
    if len(images) >= MAX_EMBEDDED_IMAGES:
        return 1
    try:
        blob = image_file.data
    except Exception:  # noqa: BLE001
        return 1
    if not isinstance(blob, (bytes, bytearray)) or not blob:
        return 1
    if len(blob) > MAX_EMBEDDED_IMAGE_BYTES:
        return 1
    digest = hashlib.sha256(bytes(blob)).hexdigest()
    if digest in seen_digests:
        return 0
    seen_digests.add(digest)
    name = str(getattr(image_file, "name", "") or "")
    ext = ""
    if "." in name:
        ext = "." + name.rsplit(".", 1)[-1].lower()
    mime = _MIME_BY_EXT.get(ext, "image/png")
    # Prefer declared image format when present
    image_format = str(getattr(image_file, "image_format", "") or "").lower()
    if image_format in {"jpeg", "jpg"}:
        mime = "image/jpeg"
    elif image_format == "png":
        mime = "image/png"
    elif image_format == "gif":
        mime = "image/gif"
    index = len(images) + 1
    images.append(EmbeddedImage(index=index, mime=mime, data=bytes(blob)))
    parts.append(image_placeholder(index))
    return 0
