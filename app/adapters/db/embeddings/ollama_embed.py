"""Small Ollama /api/embed adapter (no langchain_community dependency)."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal, Sequence

import requests

logger = logging.getLogger(__name__)

EmbeddingRole = Literal["query", "document"]

# Fixed Qwen3 Embedding query instruction (do not auto-apply to documents).
QWEN_QUERY_INSTRUCTION = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\n"
    "Query: "
)

EMBEDDING_PROVIDER = "ollama"
EMBEDDING_MODEL = "qwen3-embedding:4b"
EMBEDDING_DIMENSIONS = 1536
EMBEDDING_PROFILE = f"{EMBEDDING_PROVIDER}:{EMBEDDING_MODEL}:d{EMBEDDING_DIMENSIONS}"


class EmbeddingDimensionError(ValueError):
    """Model returned a vector length that does not match the configured column."""


def embedding_config_from_env() -> dict[str, Any]:
    base = (
        os.environ.get("KNOWLEDGE_FLOW_EMBED_BASE_URL")
        or os.environ.get("OLLAMA_BASE_URL")
        or "http://127.0.0.1:11434"
    ).rstrip("/")
    model = (
        os.environ.get("KNOWLEDGE_FLOW_EMBED_MODEL") or EMBEDDING_MODEL
    ).strip()
    try:
        dimensions = int(
            os.environ.get("KNOWLEDGE_FLOW_EMBED_DIMENSIONS")
            or EMBEDDING_DIMENSIONS
        )
    except ValueError:
        dimensions = EMBEDDING_DIMENSIONS
    try:
        timeout = float(os.environ.get("KNOWLEDGE_FLOW_EMBED_TIMEOUT_SECONDS") or "8")
    except ValueError:
        timeout = 8.0
    return {
        "provider": EMBEDDING_PROVIDER,
        "base_url": base,
        "model": model,
        "dimensions": dimensions,
        "timeout_seconds": timeout,
        "profile": f"{EMBEDDING_PROVIDER}:{model}:d{dimensions}",
    }


def _prepare_input(text: str, *, role: EmbeddingRole) -> str:
    raw = str(text or "").strip()
    if role == "query":
        return f"{QWEN_QUERY_INSTRUCTION}{raw}"
    return raw


def embed_texts(
    texts: Sequence[str],
    *,
    role: EmbeddingRole = "document",
    base_url: str | None = None,
    model: str | None = None,
    dimensions: int | None = None,
    timeout_seconds: float | None = None,
) -> list[list[float]]:
    """Call Ollama /api/embed and require exact ``dimensions`` length."""
    cfg = embedding_config_from_env()
    url = (base_url or cfg["base_url"]).rstrip("/") + "/api/embed"
    use_model = model or cfg["model"]
    use_dims = int(dimensions if dimensions is not None else cfg["dimensions"])
    timeout = float(
        timeout_seconds if timeout_seconds is not None else cfg["timeout_seconds"]
    )
    payload_input = [_prepare_input(t, role=role) for t in texts]
    body = {
        "model": use_model,
        "input": payload_input if len(payload_input) != 1 else payload_input[0],
        "dimensions": use_dims,
    }
    resp = requests.post(url, json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    vectors = data.get("embeddings")
    if not isinstance(vectors, list) or not vectors:
        raise RuntimeError("ollama embed returned no embeddings")
    out: list[list[float]] = []
    for vec in vectors:
        if not isinstance(vec, list):
            raise RuntimeError("ollama embed vector is not a list")
        if len(vec) != use_dims:
            raise EmbeddingDimensionError(
                f"expected dimensions={use_dims}, got {len(vec)} "
                f"(model={use_model}; do not pad/truncate)"
            )
        out.append([float(x) for x in vec])
    return out


def embed_query(text: str, **kwargs: Any) -> list[float]:
    return embed_texts([text], role="query", **kwargs)[0]


def embed_document(text: str, **kwargs: Any) -> list[float]:
    return embed_texts([text], role="document", **kwargs)[0]


def profile_metadata() -> dict[str, Any]:
    cfg = embedding_config_from_env()
    return {
        "embedding_provider": cfg["provider"],
        "embedding_model": cfg["model"],
        "embedding_dimensions": cfg["dimensions"],
        "embedding_profile": cfg["profile"],
    }
