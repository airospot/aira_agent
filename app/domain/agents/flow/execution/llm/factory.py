"""Knowledge Flow LLM factory.

Görev:
    Config sözlüğünden `FlowLlmClient` örneği üretir.
    Eski `create_ai_sql_client` ve AI SQL servislerine bağımlı değildir.

Input:
    config — uygulama config mapping (Flask config veya düz dict).
    Namespace: KNOWLEDGE_FLOW_LLM_*.
    API key için OPENAI_API_KEY yedek olarak kullanılabilir.

Output:
    FlowLlmClient (base_url, model, api_key, timeout_seconds).

Kullanım örneği:
    client = create_flow_llm_client(current_app.config)
    decision = client.complete_json(system_prompt, user_payload)

Sorumluluk sınırı:
    Yalnız config → client. Model routing, intent, tool, memory, event,
    retry/fallback, HTTP transport ve Flask request/session yok.
    AI_SQL_* runtime fallback yok.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from .client import FlowLlmClient, FlowLlmClientError

# Native Flow varsayılanları (AI_SQL_* okunmaz).
_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-6-luna"
_DEFAULT_TIMEOUT_SECONDS = 75


def create_flow_llm_client(config: Mapping[str, Any] | None) -> FlowLlmClient:
    """KNOWLEDGE_FLOW_LLM_* config → FlowLlmClient."""
    cfg = dict(config or {})
    base_url = _first_nonempty(
        cfg.get("KNOWLEDGE_FLOW_LLM_BASE_URL"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_BASE_URL"),
        _DEFAULT_BASE_URL,
    )
    model = _first_nonempty(
        cfg.get("KNOWLEDGE_FLOW_LLM_MODEL"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_MODEL"),
        _DEFAULT_MODEL,
    )
    api_key = _first_nonempty(
        cfg.get("KNOWLEDGE_FLOW_LLM_API_KEY"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_API_KEY"),
        cfg.get("OPENAI_API_KEY"),
        os.environ.get("OPENAI_API_KEY"),
        "",
    )
    # Öncelik: config → env; hiçbiri yoksa default 75. Geçersiz açık değer sessizce atılmaz.
    timeout_seconds = _timeout_seconds(
        cfg.get("KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS"),
    )
    return FlowLlmClient(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


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
        if text == "":
            continue
        try:
            seconds = int(text)
        except (TypeError, ValueError) as exc:
            raise FlowLlmClientError(
                f"invalid KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS={value!r}",
                "provider_unavailable",
            ) from exc
        if seconds <= 0:
            raise FlowLlmClientError(
                f"KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS must be positive, got {seconds}",
                "provider_unavailable",
            )
        return seconds
    return _DEFAULT_TIMEOUT_SECONDS
