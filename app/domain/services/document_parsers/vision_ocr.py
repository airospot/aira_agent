"""Qwen / OpenAI-compatible vision OCR for embedded document images."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any, Mapping

_DEFAULT_TIMEOUT_SECONDS = 300
_OCR_PROMPT = (
    "Extract all visible text and tables from this image as Markdown only. "
    "Preserve table structure with Markdown pipe tables when possible. "
    "Do not describe the image; output the extracted content only."
)


def extract_markdown(
    image_bytes: bytes,
    mime: str,
    *,
    config: Mapping[str, Any] | None = None,
) -> str:
    """OCR one image via KNOWLEDGE_FLOW_LLM_* chat completions (vision)."""
    cfg = dict(config or {})
    base_url = _first_nonempty(
        cfg.get("KNOWLEDGE_FLOW_LLM_BASE_URL"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_BASE_URL"),
    ).rstrip("/")
    model = _first_nonempty(
        cfg.get("KNOWLEDGE_FLOW_LLM_MODEL"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_MODEL"),
    )
    api_key = _first_nonempty(
        cfg.get("KNOWLEDGE_FLOW_LLM_API_KEY"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_API_KEY"),
        cfg.get("OPENAI_API_KEY"),
        os.environ.get("OPENAI_API_KEY"),
        "ollama",
    )
    timeout_seconds = _timeout_seconds(
        cfg.get("KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS"),
    )
    if not base_url or not model:
        return "*(OCR failed: llm_not_configured)*"
    if not image_bytes:
        return "*(OCR failed: empty_image)*"

    safe_mime = mime if mime.startswith("image/") else "image/png"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{safe_mime};base64,{b64}"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0,
        "stream": False,
    }
    url = f"{base_url}/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.reason or str(exc.code)
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        return f"*(OCR failed: HTTP {exc.code}: {detail})*"
    except Exception as exc:  # noqa: BLE001
        return f"*(OCR failed: {type(exc).__name__})*"

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return "*(OCR failed: invalid_response)*"
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, Mapping) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        text = "\n".join(p for p in parts if p).strip()
    else:
        text = str(content or "").strip()
    return text or "*(OCR failed: empty_text)*"


def fill_image_placeholders(
    text: str,
    images: tuple | list,
    *,
    config: Mapping[str, Any] | None = None,
) -> str:
    """Replace ``{{IMAGE:N}}`` placeholders with OCR markdown sections."""
    out = text
    for image in images:
        token = f"{{{{IMAGE:{image.index}}}}}"
        ocr = extract_markdown(image.data, image.mime, config=config)
        section = f"## Embedded image {image.index}\n\n{ocr}".strip()
        out = out.replace(token, section)
    return out


def _first_nonempty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _timeout_seconds(*values: Any) -> int:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        try:
            seconds = int(text)
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return seconds
    return _DEFAULT_TIMEOUT_SECONDS
