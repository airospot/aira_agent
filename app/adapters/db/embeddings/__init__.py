"""Embedding adapters for conversation memory."""

from app.adapters.db.embeddings.ollama_embed import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EMBEDDING_PROFILE,
    EMBEDDING_PROVIDER,
    EmbeddingDimensionError,
    embed_document,
    embed_query,
    embedding_config_from_env,
    profile_metadata,
)

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "EMBEDDING_MODEL",
    "EMBEDDING_PROFILE",
    "EMBEDDING_PROVIDER",
    "EmbeddingDimensionError",
    "embed_document",
    "embed_query",
    "embedding_config_from_env",
    "profile_metadata",
]
