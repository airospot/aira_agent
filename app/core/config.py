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
        # Tenant originals + corpus live under this root (not shared data/corpus).
        "TENANT_DATA_ROOT": os.environ.get("TENANT_DATA_ROOT", "data/tenants"),
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
        # Must come from environment / overlay — no hardcoded secret.
        "SECRET_KEY": os.environ.get("SECRET_KEY"),
        "LOGIN_UI_URL": os.environ.get("LOGIN_UI_URL"),
        "AGENT_SUBMISSION_TIMEOUT_SECONDS": os.environ.get(
            "AGENT_SUBMISSION_TIMEOUT_SECONDS", str(15 * 60)
        ),
        # A03 run budgets — values must come from .env; no code-side numeric defaults.
        "AGENT_MAX_STEPS": os.environ.get("AGENT_MAX_STEPS"),
        "AGENT_RUN_TIMEOUT_SECONDS": os.environ.get("AGENT_RUN_TIMEOUT_SECONDS"),
        "AGENT_TOOL_TIMEOUT_SECONDS": os.environ.get("AGENT_TOOL_TIMEOUT_SECONDS"),
        "AGENT_MAX_OBSERVATION_BYTES": os.environ.get("AGENT_MAX_OBSERVATION_BYTES"),
        "AGENT_MAX_CONTEXT_BYTES": os.environ.get("AGENT_MAX_CONTEXT_BYTES"),
        "AGENT_MAX_TOOL_RETRIES": os.environ.get("AGENT_MAX_TOOL_RETRIES"),
    }
