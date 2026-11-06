"""Minimal ConfigurationManager for Native Knowledge Flow memory.

No GraphRAG / monitoring / agent-tool repositories. Values come from
``config_schema`` defaults + environment overrides.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import psycopg2

from .config_schema import CONFIG_SCHEMA, ConfigCategory

logger = logging.getLogger(__name__)

_ENV_OVERRIDES = {
    "memory_short_term_count": "MEMORY_SHORT_TERM_COUNT",
    "memory_long_term_enabled": "MEMORY_LONG_TERM_ENABLED",
    "memory_auto_context_enabled": "MEMORY_AUTO_CONTEXT_ENABLED",
    "memory_structured_enabled": "MEMORY_STRUCTURED_ENABLED",
    "memory_structured_shadow_mode": "MEMORY_STRUCTURED_SHADOW_MODE",
    "memory_structured_max_context": "MEMORY_STRUCTURED_MAX_CONTEXT",
    "memory_structured_min_confidence": "MEMORY_STRUCTURED_MIN_CONFIDENCE",
    "memory_structured_embedding_enabled": "MEMORY_STRUCTURED_EMBEDDING_ENABLED",
    "memory_sensitive_filter_enabled": "MEMORY_SENSITIVE_FILTER_ENABLED",
    "ollama_url": "OLLAMA_URL",
}


def _parse_bool(raw: str) -> Optional[bool]:
    s = raw.strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return None


def _coerce(key: str, raw: str) -> Any:
    setting = CONFIG_SCHEMA.settings.get(key)
    kind = setting.type.value if setting is not None else "string"
    if kind == "boolean":
        parsed = _parse_bool(raw)
        return raw if parsed is None else parsed
    if kind == "integer":
        try:
            return int(raw.strip())
        except ValueError:
            return raw
    if kind == "float":
        try:
            return float(raw.strip())
        except ValueError:
            return raw
    return raw.strip()


def _psycopg2_dsn(url: str) -> str:
    """Accept SQLAlchemy-style URLs for raw psycopg2.connect."""
    text = (url or "").strip()
    if text.startswith("postgresql+psycopg2://"):
        text = "postgresql://" + text[len("postgresql+psycopg2://") :]
    if text.startswith("postgres://"):
        text = "postgresql://" + text[len("postgres://") :]
    return text


def _default_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        (
            f"postgresql://{os.environ.get('POSTGRES_USER', 'postgres')}:"
            f"{os.environ.get('POSTGRES_PASSWORD', 'postgres')}@"
            f"{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:"
            f"{os.environ.get('POSTGRES_PORT', '5432')}/"
            f"{os.environ.get('POSTGRES_DB', 'NATIVE_FLOW')}"
        ),
    )


def _build_memory_config() -> dict[str, Any]:
    values = CONFIG_SCHEMA.defaults()
    for key, env_name in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_name)
        if raw is None or not str(raw).strip():
            continue
        values[key] = _coerce(key, str(raw))
    # Prefer explicit LLM base when it points at local Ollama.
    llm_base = (os.environ.get("KNOWLEDGE_FLOW_LLM_BASE_URL") or "").strip()
    if llm_base and ("11434" in llm_base or "ollama" in llm_base.lower()):
        parsed = urlparse(llm_base)
        if parsed.scheme and parsed.netloc:
            values["ollama_url"] = urlunparse(
                (parsed.scheme, parsed.netloc, "", "", "", "")
            ).rstrip("/")
    return values


class ConfigurationManager:
    """Memory-scoped config + Postgres connection helper."""

    def __init__(self, connection_string: str, customer_id: int, user_id: int):
        if customer_id is None:
            raise ValueError("customer_id is required and cannot be None")
        if user_id is None:
            raise ValueError("user_id is required and cannot be None")
        self.connection_string = _psycopg2_dsn(connection_string)
        self.customer_id = int(customer_id)
        self.user_id = int(user_id)
        self.schema = CONFIG_SCHEMA
        self._lock = threading.Lock()
        self._current_config = _build_memory_config()

    def _get_connection(self):
        return psycopg2.connect(self.connection_string)

    def get_config(
        self,
        key: Optional[str] = None,
        category: Optional[ConfigCategory] = None,
        default: Any = None,
    ) -> Any:
        with self._lock:
            if key:
                return self._current_config.get(key, default)
            if category:
                settings = self.schema.get_settings_by_category(category)
                return {
                    setting.key: self._current_config.get(setting.key)
                    for setting in settings
                }
            return self._current_config.copy()

    def get_all_config(self):
        return self.get_config()

    def _get_openai_api_key(self) -> Optional[str]:
        for name in (
            "KNOWLEDGE_FLOW_LLM_API_KEY",
            "OPENAI_API_KEY",
        ):
            value = (os.environ.get(name) or "").strip()
            if value and value.lower() != "ollama":
                return value
        return None


class _LazyConfigManager:
    """Module-level proxy used by older ``from ... import config_manager`` paths."""

    def __getattr__(self, name: str):
        return getattr(get_config_manager_for_customer(), name)


config_manager = _LazyConfigManager()


def get_config_manager_for_customer(
    customer_id: int = None, user_id: int = None
) -> ConfigurationManager:
    if customer_id is None or user_id is None:
        try:
            from app.core.context import (
                get_customer_id_from_request,
                get_user_id_from_request,
            )

            jwt_customer_id = get_customer_id_from_request()
            jwt_user_id = get_user_id_from_request()
            if jwt_customer_id and customer_id is None:
                customer_id = jwt_customer_id
            if jwt_user_id and user_id is None:
                user_id = jwt_user_id
        except Exception:
            pass

    if customer_id is None or user_id is None:
        try:
            from flask import has_request_context, session

            if has_request_context():
                if customer_id is None:
                    customer_id = session.get("customer_id")
                if user_id is None:
                    user_id = session.get("user_id")
        except Exception:
            pass

    if customer_id is None:
        customer_id = int(os.environ.get("AUTH_BYPASS_CUSTOMER_ID") or 1)
        logger.debug("config_manager fallback customer_id=%s", customer_id)
    if user_id is None:
        user_id = int(os.environ.get("AUTH_BYPASS_USER_ID") or 1)
        logger.debug("config_manager fallback user_id=%s", user_id)

    return ConfigurationManager(
        connection_string=_default_database_url(),
        customer_id=int(customer_id),
        user_id=int(user_id),
    )


def get_current_config_manager() -> ConfigurationManager:
    return get_config_manager_for_customer()
