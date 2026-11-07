"""A03 review: Ollama native transport, env LLM settings, serializer parity."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from app.domain.agents.flow.execution.decision.json_payload import (
    dumps_compact,
    measure_decision_context_bytes,
)
from app.domain.agents.flow.execution.llm.client import (
    FlowLlmClient,
    FlowLlmClientError,
    is_ollama_endpoint,
    ollama_native_root,
)
from app.domain.agents.flow.execution.llm.factory import create_flow_llm_client
from app.domain.agents.flow.execution.run_agent_loop import run_agent_loop
from tests.a03_policy_helpers import recommended_run_policy


def test_ollama_root_strips_v1() -> None:
    assert ollama_native_root("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434"
    assert is_ollama_endpoint("http://127.0.0.1:11434/v1")
    assert not is_ollama_endpoint("https://api.openai.com/v1")


_OLLAMA_ENV_KEYS = (
    "OLLAMA_BASE_URL",
    "KNOWLEDGE_FLOW_LLM_BASE_URL",
    "KNOWLEDGE_FLOW_LLM_MODEL",
    "KNOWLEDGE_FLOW_LLM_API_KEY",
    "KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS",
    "KNOWLEDGE_FLOW_LLM_CONTEXT_TOKENS",
    "KNOWLEDGE_FLOW_LLM_MAX_OUTPUT_TOKENS",
    "KNOWLEDGE_FLOW_LLM_THINK",
    "OPENAI_API_KEY",
)


@pytest.fixture
def clean_llm_env(monkeypatch: pytest.MonkeyPatch):
    for key in _OLLAMA_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_factory_requires_ollama_settings_no_numeric_fallback(clean_llm_env) -> None:
    with pytest.raises(FlowLlmClientError, match="CONTEXT_TOKENS"):
        create_flow_llm_client(
            {
                "KNOWLEDGE_FLOW_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
                "KNOWLEDGE_FLOW_LLM_MODEL": "qwen3.5:9b",
                "KNOWLEDGE_FLOW_LLM_API_KEY": "ollama",
                "KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS": "30",
            }
        )
    with pytest.raises(FlowLlmClientError, match="THINK"):
        create_flow_llm_client(
            {
                "KNOWLEDGE_FLOW_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
                "KNOWLEDGE_FLOW_LLM_MODEL": "qwen3.5:9b",
                "KNOWLEDGE_FLOW_LLM_API_KEY": "ollama",
                "KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS": "30",
                "KNOWLEDGE_FLOW_LLM_CONTEXT_TOKENS": "65536",
                "KNOWLEDGE_FLOW_LLM_MAX_OUTPUT_TOKENS": "2048",
            }
        )
    with pytest.raises(FlowLlmClientError, match="true/false"):
        create_flow_llm_client(
            {
                "KNOWLEDGE_FLOW_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
                "KNOWLEDGE_FLOW_LLM_MODEL": "qwen3.5:9b",
                "KNOWLEDGE_FLOW_LLM_API_KEY": "ollama",
                "KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS": "30",
                "KNOWLEDGE_FLOW_LLM_CONTEXT_TOKENS": "65536",
                "KNOWLEDGE_FLOW_LLM_MAX_OUTPUT_TOKENS": "2048",
                "KNOWLEDGE_FLOW_LLM_THINK": "maybe",
            }
        )
    # bool("false") would be True — parser must treat string false as False.
    client = create_flow_llm_client(
        {
            "KNOWLEDGE_FLOW_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
            "KNOWLEDGE_FLOW_LLM_MODEL": "qwen3.5:9b",
            "KNOWLEDGE_FLOW_LLM_API_KEY": "ollama",
            "KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS": "30",
            "KNOWLEDGE_FLOW_LLM_CONTEXT_TOKENS": "65536",
            "KNOWLEDGE_FLOW_LLM_MAX_OUTPUT_TOKENS": "2048",
            "KNOWLEDGE_FLOW_LLM_THINK": "false",
        }
    )
    assert client.think is False
    assert client.context_tokens == 65536
    assert client.max_output_tokens == 2048


def test_factory_cloud_does_not_require_ollama_keys(clean_llm_env) -> None:
    client = create_flow_llm_client(
        {
            "KNOWLEDGE_FLOW_LLM_BASE_URL": "https://api.openai.com/v1",
            "KNOWLEDGE_FLOW_LLM_MODEL": "gpt-6-luna",
            "KNOWLEDGE_FLOW_LLM_API_KEY": "sk-test",
            "KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS": "75",
        }
    )
    assert not client.uses_ollama_native()
    assert client.context_tokens is None
    assert client.think is None


def test_factory_derives_llm_url_from_ollama_base(clean_llm_env) -> None:
    client = create_flow_llm_client(
        {
            "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
            "KNOWLEDGE_FLOW_LLM_MODEL": "qwen3.5:9b",
            "KNOWLEDGE_FLOW_LLM_API_KEY": "ollama",
            "KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS": "30",
            "KNOWLEDGE_FLOW_LLM_CONTEXT_TOKENS": "65536",
            "KNOWLEDGE_FLOW_LLM_MAX_OUTPUT_TOKENS": "2048",
            "KNOWLEDGE_FLOW_LLM_THINK": "false",
        }
    )
    assert client.base_url == "http://127.0.0.1:11434/v1"
    assert client.uses_ollama_native()


def test_ollama_native_request_contract() -> None:
    captured: dict[str, Any] = {}

    def fake_post(endpoint, body, *, timeout_seconds, auth_bearer=False):
        captured["endpoint"] = endpoint
        captured["body"] = body
        captured["auth_bearer"] = auth_bearer
        return (
            {
                "message": {
                    "role": "assistant",
                    "content": '{"action":"ANSWER","answer":"ok"}',
                    "thinking": '{"action":"ANSWER","answer":"from-thinking"}',
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 10,
                "eval_count": 5,
            },
            None,
        )

    client = FlowLlmClient(
        base_url="http://127.0.0.1:11434/v1",
        model="qwen3.5:9b",
        api_key="ollama",
        timeout_seconds=30,
        context_tokens=65536,
        max_output_tokens=2048,
        think=False,
    )
    with patch.object(client, "_post_json", side_effect=fake_post):
        decision = client.complete_json("sys", {"request_text": "hi"})
    assert decision == {"action": "ANSWER", "answer": "ok"}
    assert captured["endpoint"] == "http://127.0.0.1:11434/api/chat"
    assert captured["auth_bearer"] is False
    assert captured["body"]["think"] is False
    assert captured["body"]["stream"] is False
    assert captured["body"]["options"]["num_ctx"] == 65536
    assert captured["body"]["options"]["num_predict"] == 2048
    assert "/v1/" not in captured["endpoint"]
    assert "options" not in json.dumps(captured["body"]) or "num_ctx" in captured["body"]["options"]
    assert client.last_meta["transport"] == "ollama_api_chat"
    assert client.last_meta["num_ctx"] == 65536


def test_openai_request_contract_keeps_chat_completions() -> None:
    captured: dict[str, Any] = {}

    def fake_post(endpoint, body, *, timeout_seconds, auth_bearer=False):
        captured["endpoint"] = endpoint
        captured["body"] = body
        captured["auth_bearer"] = auth_bearer
        return (
            {
                "id": "chatcmpl-1",
                "choices": [
                    {
                        "message": {
                            "content": '{"action":"ANSWER","answer":"cloud"}',
                            "reasoning": '{"action":"ANSWER","answer":"ignore"}',
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
            "req-1",
        )

    client = FlowLlmClient(
        base_url="https://api.openai.com/v1",
        model="gpt-6-luna",
        api_key="sk-test",
        timeout_seconds=75,
        max_output_tokens=2048,
    )
    with patch.object(client, "_post_json", side_effect=fake_post):
        decision = client.complete_json("sys", {"request_text": "hi"})
    assert decision["answer"] == "cloud"
    assert captured["endpoint"].endswith("/chat/completions")
    assert captured["auth_bearer"] is True
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["max_tokens"] == 2048
    assert "think" not in captured["body"]
    assert "options" not in captured["body"]


def test_thinking_not_parsed_as_decision_empty_content_length() -> None:
    client = FlowLlmClient(
        base_url="http://127.0.0.1:11434/v1",
        model="qwen3.5:9b",
        api_key="ollama",
        timeout_seconds=30,
        context_tokens=65536,
        max_output_tokens=16,
        think=False,
    )

    def empty_length(_endpoint, _body, *, timeout_seconds, auth_bearer=False):
        return (
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "thinking": '{"action":"ANSWER","answer":"from-thinking"}',
                },
                "done": True,
                "done_reason": "length",
            },
            None,
        )

    with patch.object(client, "_post_json", side_effect=empty_length):
        with pytest.raises(FlowLlmClientError) as excinfo:
            client.complete_json("sys", {"x": 1})
    assert excinfo.value.error_class == "output_limit"


def test_empty_content_stop_is_malformed_not_thinking() -> None:
    client = FlowLlmClient(
        base_url="http://127.0.0.1:11434/v1",
        model="qwen3.5:9b",
        api_key="ollama",
        timeout_seconds=30,
        context_tokens=8192,
        max_output_tokens=128,
        think=False,
    )

    def empty_stop(_endpoint, _body, *, timeout_seconds, auth_bearer=False):
        return (
            {
                "message": {
                    "content": "   ",
                    "thinking": '{"action":"ANSWER","answer":"nope"}',
                },
                "done_reason": "stop",
            },
            None,
        )

    with patch.object(client, "_post_json", side_effect=empty_stop):
        with pytest.raises(FlowLlmClientError) as excinfo:
            client.complete_json("sys", {"x": 1})
    assert excinfo.value.error_class == "malformed_model_response"


def test_builder_and_client_same_serializer_bytes() -> None:
    payload = {"a": 1, "nested": {"b": "ü"}, "list": [1, 2]}
    system = "hello"
    compact = dumps_compact(payload)
    spaced = json.dumps(payload, ensure_ascii=False)
    assert len(compact.encode("utf-8")) < len(spaced.encode("utf-8"))
    measured = measure_decision_context_bytes(system, payload)
    assert measured == len(system.encode("utf-8")) + len(compact.encode("utf-8"))

    client = FlowLlmClient(
        base_url="https://api.openai.com/v1",
        model="gpt-6-luna",
        api_key="sk-test",
        timeout_seconds=75,
        max_output_tokens=64,
    )
    captured: dict[str, Any] = {}

    def fake_post(endpoint, body, *, timeout_seconds, auth_bearer=False):
        captured["user"] = body["messages"][1]["content"]
        return (
            {
                "choices": [
                    {
                        "message": {"content": '{"action":"ANSWER","answer":"x"}'},
                        "finish_reason": "stop",
                    }
                ]
            },
            None,
        )

    with patch.object(client, "_post_json", side_effect=fake_post):
        client.complete_json(system, payload, max_context_bytes=measured)
    assert captured["user"] == compact
    with pytest.raises(FlowLlmClientError) as excinfo:
        client.complete_json(system, payload, max_context_bytes=measured - 1)
    assert excinfo.value.error_class == "context_budget_exceeded"


def test_loop_maps_output_limit_to_stop_incomplete() -> None:
    def decide(*_a, **_k):
        raise FlowLlmClientError("hit limit", "output_limit")

    from app.domain.agents.flow.execution.run_policy import RunBudget

    out = run_agent_loop(
        "q",
        {},
        decide,
        lambda d, **k: d.get("action"),
        lambda d: {},
        budget=RunBudget.start(recommended_run_policy()),
    )
    assert out["status"] == "STOP_INCOMPLETE"
    assert out["decision"]["action"] == "STOP_INCOMPLETE"
    assert "çıktı limiti" in out["decision"]["reason"]
