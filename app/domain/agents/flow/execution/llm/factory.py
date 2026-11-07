"""Knowledge Flow LLM factory.

Görev:
    Config sözlüğünden `FlowLlmClient` örneği üretir.

Input:
    config — uygulama config mapping.
    Namespace: KNOWLEDGE_FLOW_LLM_*.
    Yerel Ollama: CONTEXT_TOKENS / MAX_OUTPUT_TOKENS / THINK zorunlu (kod fallback yok).

Output:
    FlowLlmClient.

Sorumluluk sınırı:
    Yalnız config → client. Transport client içinde.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from .client import FlowLlmClient, FlowLlmClientError, is_ollama_endpoint

# Cloud OpenAI defaults only (not used for Ollama-required numeric settings).
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
    timeout_seconds = _timeout_seconds(
        cfg.get("KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS"),
    )

    ollama = is_ollama_endpoint(base_url)
    context_tokens = _optional_positive_int(
        "KNOWLEDGE_FLOW_LLM_CONTEXT_TOKENS",
        cfg.get("KNOWLEDGE_FLOW_LLM_CONTEXT_TOKENS"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_CONTEXT_TOKENS"),
        required=ollama,
    )
    max_output_tokens = _optional_positive_int(
        "KNOWLEDGE_FLOW_LLM_MAX_OUTPUT_TOKENS",
        cfg.get("KNOWLEDGE_FLOW_LLM_MAX_OUTPUT_TOKENS"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_MAX_OUTPUT_TOKENS"),
        required=ollama,
    )
    think = _optional_bool(
        "KNOWLEDGE_FLOW_LLM_THINK",
        cfg.get("KNOWLEDGE_FLOW_LLM_THINK"),
        os.environ.get("KNOWLEDGE_FLOW_LLM_THINK"),
        required=ollama,
    )

    return FlowLlmClient(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        context_tokens=context_tokens,
        max_output_tokens=max_output_tokens,
        think=think,
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


def _optional_positive_int(
    name: str,
    *values: Any,
    required: bool,
) -> int | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text == "":
            continue
        try:
            number = int(text)
        except (TypeError, ValueError) as exc:
            raise FlowLlmClientError(
                f"invalid {name}={value!r}",
                "provider_unavailable",
            ) from exc
        if number <= 0:
            raise FlowLlmClientError(
                f"{name} must be positive, got {number}",
                "provider_unavailable",
            )
        return number
    if required:
        raise FlowLlmClientError(
            f"{name} required",
            "provider_unavailable",
        )
    return None


def _optional_bool(
    name: str,
    *values: Any,
    required: bool,
) -> bool | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text == "":
            continue
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise FlowLlmClientError(
            f"invalid {name}={value!r} (expected true/false)",
            "provider_unavailable",
        )
    if required:
        raise FlowLlmClientError(
            f"{name} required",
            "provider_unavailable",
        )
    return None
