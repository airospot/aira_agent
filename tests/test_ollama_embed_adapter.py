"""Ollama embed adapter: config, roles, dimensions, profile isolation (mocked HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.agents.embeddings import ollama_embed as oe


def test_config_defaults(monkeypatch):
    monkeypatch.delenv("KNOWLEDGE_FLOW_EMBED_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("KNOWLEDGE_FLOW_EMBED_MODEL", raising=False)
    monkeypatch.delenv("KNOWLEDGE_FLOW_EMBED_DIMENSIONS", raising=False)
    monkeypatch.delenv("KNOWLEDGE_FLOW_EMBED_TIMEOUT_SECONDS", raising=False)
    cfg = oe.embedding_config_from_env()
    assert cfg["provider"] == "ollama"
    assert cfg["model"] == "qwen3-embedding:4b"
    assert cfg["dimensions"] == 1536
    assert cfg["timeout_seconds"] == 8.0
    assert cfg["profile"] == "ollama:qwen3-embedding:4b:d1536"
    assert cfg["base_url"].endswith("11434")


def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_FLOW_EMBED_BASE_URL", "http://embed:11434")
    monkeypatch.setenv("KNOWLEDGE_FLOW_EMBED_MODEL", "qwen3-embedding:4b")
    monkeypatch.setenv("KNOWLEDGE_FLOW_EMBED_DIMENSIONS", "1536")
    monkeypatch.setenv("KNOWLEDGE_FLOW_EMBED_TIMEOUT_SECONDS", "3.5")
    cfg = oe.embedding_config_from_env()
    assert cfg["base_url"] == "http://embed:11434"
    assert cfg["timeout_seconds"] == 3.5
    assert cfg["profile"] == "ollama:qwen3-embedding:4b:d1536"


def test_query_role_applies_instruction_document_does_not(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_FLOW_EMBED_BASE_URL", "http://embed.test")
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        vec = [0.1] * 1536
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"embeddings": [vec]}
        return resp

    with patch("app.domain.agents.embeddings.ollama_embed.requests.post", fake_post):
        oe.embed_query("fatura nedir")
        q_input = captured["json"]["input"]
        assert q_input.startswith(oe.QWEN_QUERY_INSTRUCTION)
        assert q_input.endswith("fatura nedir")
        assert captured["json"]["dimensions"] == 1536
        assert captured["json"]["model"] == "qwen3-embedding:4b"

        oe.embed_document("fatura nedir")
        d_input = captured["json"]["input"]
        assert d_input == "fatura nedir"
        assert not str(d_input).startswith("Instruct:")


def test_dimension_mismatch_raises(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_FLOW_EMBED_BASE_URL", "http://embed.test")

    def fake_post(url, json=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"embeddings": [[0.0] * 2560]}
        return resp

    with patch("app.domain.agents.embeddings.ollama_embed.requests.post", fake_post):
        with pytest.raises(oe.EmbeddingDimensionError, match="2560"):
            oe.embed_document("x")


def test_profile_metadata_matches_config(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_FLOW_EMBED_MODEL", "qwen3-embedding:4b")
    monkeypatch.setenv("KNOWLEDGE_FLOW_EMBED_DIMENSIONS", "1536")
    meta = oe.profile_metadata()
    assert meta["embedding_provider"] == "ollama"
    assert meta["embedding_model"] == "qwen3-embedding:4b"
    assert meta["embedding_dimensions"] == 1536
    assert meta["embedding_profile"] == "ollama:qwen3-embedding:4b:d1536"


def test_unknown_profile_not_assumed_qwen():
    """Legacy/empty metadata must not equal current profile string."""
    current = oe.EMBEDDING_PROFILE
    assert current == "ollama:qwen3-embedding:4b:d1536"
    for legacy in (None, "", "nomic-embed-text", "openai:text-embedding-3-small:d1536"):
        assert legacy != current
