"""Application configuration from environment. No feature business logic."""

from __future__ import annotations

import os
from typing import Any


def build_app_config() -> dict[str, Any]:
    return {
        "APP_RUNTIME_MODE": os.environ.get("APP_RUNTIME_MODE", "development"),
        "AIRA_DEV_HOST": os.environ.get("AIRA_DEV_HOST", "127.0.0.1"),
        "AIRA_DEV_PORT": os.environ.get("AIRA_DEV_PORT", os.environ.get("FLASK_RUN_PORT", "5000")),
        "AGENT_CORPUS_DIR": os.environ.get("AGENT_CORPUS_DIR", "data/corpus"),
        "KNOWLEDGE_FLOW_LLM_BASE_URL": os.environ.get(
            "KNOWLEDGE_FLOW_LLM_BASE_URL", "http://127.0.0.1:11434/v1"
        ),
        "KNOWLEDGE_FLOW_LLM_MODEL": os.environ.get(
            "KNOWLEDGE_FLOW_LLM_MODEL", "qwen3.5:9b"
        ),
        "KNOWLEDGE_FLOW_LLM_API_KEY": os.environ.get("KNOWLEDGE_FLOW_LLM_API_KEY", "ollama"),
        "KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS": os.environ.get(
            "KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS", "120"
        ),
        "APP_USER_NAME": None,
        "SECRET_KEY": "dev-runtime-governance",
    }
