"""Knowledge Flow native LLM istemcisi.

Görev:
    Karar JSON'u ister. Yerel Ollama için /api/chat + native num_ctx/num_predict/think;
    cloud OpenAI-uyumlu için /v1/chat/completions.

Input:
    Constructor: base_url, model, api_key, timeout_seconds,
    context_tokens / max_output_tokens / think (Ollama zorunlu; factory verir).
    complete_json(system_prompt, user_payload): sistem metni + kullanıcı JSON yükü.

Output:
    Modelin assistant content içindeki JSON nesnesi (dict).
    Reasoning/thinking içeriği karar olarak parse edilmez.

Sorumluluk sınırı:
    Yalnız LLM HTTP çağrısı. Intent, tool, memory, Flask yok.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.domain.agents.flow.execution.decision.json_payload import (
    dumps_compact,
    measure_decision_context_bytes,
)
from app.shared.runtime_utils import redact_secrets


class FlowLlmClientError(RuntimeError):
    """LLM taşıma / yanıt hatası."""

    def __init__(self, message: str, error_class: str = "provider_failure"):
        super().__init__(message)
        self.error_class = error_class


def is_ollama_endpoint(base_url: str) -> bool:
    host = str(base_url or "").lower()
    return any(
        token in host
        for token in (
            "127.0.0.1",
            "localhost",
            "0.0.0.0",
            ":11434",
            "ollama",
        )
    )


def ollama_native_root(base_url: str) -> str:
    """http://host:11434/v1 → http://host:11434"""
    raw = str(base_url or "").strip().rstrip("/")
    parts = urlsplit(raw)
    path = parts.path or ""
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    elif path == "/v1":
        path = ""
    return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", "")).rstrip("/")


class FlowLlmClient:
    """JSON chat client: Ollama native or OpenAI-compatible cloud."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: int,
        context_tokens: int | None = None,
        max_output_tokens: int | None = None,
        think: bool | None = None,
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.model = str(model or "").strip()
        self.api_key = str(api_key or "")
        self.timeout_seconds = int(timeout_seconds)
        self.context_tokens = context_tokens
        self.max_output_tokens = max_output_tokens
        self.think = think
        self.last_meta: dict[str, Any] = {}
        if not self.base_url:
            raise FlowLlmClientError("base_url required", "provider_unavailable")
        if not self.model:
            raise FlowLlmClientError("model required", "model_unavailable")
        if self.model.lower() in {"fake", "mock", "scripted", "stub"}:
            raise FlowLlmClientError(
                f"Unsupported model={self.model!r}.",
                "model_unavailable",
            )
        if not self.api_key:
            raise FlowLlmClientError("api_key required", "authentication_failed")
        if self.uses_ollama_native():
            if self.context_tokens is None:
                raise FlowLlmClientError(
                    "KNOWLEDGE_FLOW_LLM_CONTEXT_TOKENS required for Ollama",
                    "provider_unavailable",
                )
            if self.max_output_tokens is None:
                raise FlowLlmClientError(
                    "KNOWLEDGE_FLOW_LLM_MAX_OUTPUT_TOKENS required for Ollama",
                    "provider_unavailable",
                )
            if self.think is None:
                raise FlowLlmClientError(
                    "KNOWLEDGE_FLOW_LLM_THINK required for Ollama",
                    "provider_unavailable",
                )

    def uses_ollama_native(self) -> bool:
        return is_ollama_endpoint(self.base_url)

    def complete_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        *,
        timeout_seconds: float | int | None = None,
        max_context_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Request one JSON decision.

        ``timeout_seconds`` is per-call and does not mutate ``self.timeout_seconds``.
        After redaction, sent system+user bytes are checked against ``max_context_bytes``
        when provided (same compact serializer as the context builder).
        """
        safe_user = redact_secrets(user_payload)
        user_json = dumps_compact(safe_user)
        sent_bytes = measure_decision_context_bytes(system_prompt, safe_user)
        if max_context_bytes is not None and sent_bytes > int(max_context_bytes):
            raise FlowLlmClientError(
                "decision context exceeds AGENT_MAX_CONTEXT_BYTES after redaction",
                "context_budget_exceeded",
            )

        call_timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(self.timeout_seconds)
        )

        if self.uses_ollama_native():
            return self._complete_json_ollama(
                system_prompt,
                user_json,
                timeout_seconds=call_timeout,
                sent_bytes=sent_bytes,
                decision_schema=safe_user.get("decision_schema"),
            )
        return self._complete_json_openai(
            system_prompt,
            user_json,
            timeout_seconds=call_timeout,
            sent_bytes=sent_bytes,
        )

    def _complete_json_ollama(
        self,
        system_prompt: str,
        user_json: str,
        *,
        timeout_seconds: float,
        sent_bytes: int,
        decision_schema: Any = None,
    ) -> dict[str, Any]:
        root = ollama_native_root(self.base_url)
        endpoint = f"{root}/api/chat"
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "think": bool(self.think),
            "format": decision_schema if isinstance(decision_schema, dict) else "json",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_json},
            ],
            "options": {
                "num_ctx": int(self.context_tokens),
                "num_predict": int(self.max_output_tokens),
            },
        }
        if not self.model.lower().startswith("gpt-6-luna"):
            body["options"]["temperature"] = 0.1

        payload, request_id = self._post_json(endpoint, body, timeout_seconds=timeout_seconds)
        message = payload.get("message") or {}
        content = message.get("content")
        done_reason = payload.get("done_reason")
        self.last_meta = {
            "provider": "ollama_native",
            "transport": "ollama_api_chat",
            "model": self.model,
            "request_id": request_id or payload.get("created_at"),
            "input_tokens": payload.get("prompt_eval_count"),
            "output_tokens": payload.get("eval_count"),
            "total_tokens": None,
            "structured_output": "json_schema" if isinstance(decision_schema, dict) else "json_object",
            "endpoint": endpoint,
            "retry": "none",
            "num_ctx": int(self.context_tokens),
            "num_predict": int(self.max_output_tokens),
            "think": bool(self.think),
            "done_reason": done_reason,
            "sent_context_bytes": sent_bytes,
        }
        return self._decision_from_content(
            content,
            finish_or_done_reason=done_reason,
        )

    def _complete_json_openai(
        self,
        system_prompt: str,
        user_json: str,
        *,
        timeout_seconds: float,
        sent_bytes: int,
    ) -> dict[str, Any]:
        endpoint = f"{self.base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_json},
            ],
            "response_format": {"type": "json_object"},
        }
        if self.max_output_tokens is not None:
            body["max_tokens"] = int(self.max_output_tokens)
        if not self.model.lower().startswith("gpt-6-luna"):
            body["temperature"] = 0.1

        payload, request_id = self._post_json(
            endpoint,
            body,
            timeout_seconds=timeout_seconds,
            auth_bearer=True,
        )
        usage = payload.get("usage") or {}
        choice0 = (payload.get("choices") or [{}])[0] or {}
        message = choice0.get("message") or {}
        content = message.get("content")
        finish_reason = choice0.get("finish_reason")
        self.last_meta = {
            "provider": "openai_compatible",
            "transport": "openai_chat_completions",
            "model": self.model,
            "request_id": request_id or payload.get("id"),
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "structured_output": "response_format.json_object",
            "endpoint": endpoint,
            "retry": "none",
            "finish_reason": finish_reason,
            "sent_context_bytes": sent_bytes,
            "max_tokens": self.max_output_tokens,
        }
        # Never treat reasoning* as decision JSON.
        return self._decision_from_content(
            content,
            finish_or_done_reason=finish_reason,
        )

    def _decision_from_content(
        self,
        content: Any,
        *,
        finish_or_done_reason: Any,
    ) -> dict[str, Any]:
        text = str(content or "").strip()
        reason = str(finish_or_done_reason or "").strip().lower()
        if not text:
            if reason == "length":
                self.last_meta = {
                    **self.last_meta,
                    "error_class": "output_limit",
                    "finish_or_done_reason": finish_or_done_reason,
                }
                raise FlowLlmClientError(
                    "Model output hit token limit before a decision JSON was produced",
                    "output_limit",
                )
            self.last_meta = {
                **self.last_meta,
                "error_class": "malformed_model_response",
                "finish_or_done_reason": finish_or_done_reason,
            }
            raise FlowLlmClientError(
                "Malformed LLM JSON content: empty message content",
                "malformed_model_response",
            )
        try:
            return self._parse_json_object(text)
        except FlowLlmClientError:
            if reason == "length":
                self.last_meta = {
                    **self.last_meta,
                    "error_class": "output_limit",
                    "finish_or_done_reason": finish_or_done_reason,
                }
                raise FlowLlmClientError(
                    "Model output hit token limit with incomplete decision JSON",
                    "output_limit",
                ) from None
            raise

    def _post_json(
        self,
        endpoint: str,
        body: dict[str, Any],
        *,
        timeout_seconds: float,
        auth_bearer: bool = False,
    ) -> tuple[dict[str, Any], str | None]:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if auth_bearer:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=float(timeout_seconds)) as resp:
                raw = resp.read().decode("utf-8")
                request_id = resp.headers.get("x-request-id") or resp.headers.get(
                    "openai-request-id"
                )
                return json.loads(raw), request_id
        except urllib.error.HTTPError as exc:
            detail = self._sanitize(exc.read().decode("utf-8", errors="ignore")[:400])
            error_class = self._classify_http(exc.code, detail)
            self.last_meta = {
                "provider": "ollama_native" if self.uses_ollama_native() else "openai_compatible",
                "model": self.model,
                "error_class": error_class,
                "http_status": exc.code,
                "endpoint": endpoint,
            }
            raise FlowLlmClientError(
                f"LLM HTTP {exc.code}: {detail}",
                error_class,
            ) from None
        except TimeoutError:
            self.last_meta = {
                "provider": "ollama_native" if self.uses_ollama_native() else "openai_compatible",
                "model": self.model,
                "error_class": "timeout",
                "timeout_seconds": float(timeout_seconds),
                "endpoint": endpoint,
            }
            raise FlowLlmClientError("LLM request timed out", "timeout") from None
        except Exception as exc:
            msg = self._sanitize(str(exc))
            error_class = "timeout" if "timed out" in msg.lower() else "provider_failure"
            raise FlowLlmClientError(f"LLM request failed: {msg}", error_class) from None

    def _parse_json_object(self, content: Any) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            raise FlowLlmClientError(
                "Malformed LLM JSON content: empty message",
                "malformed_model_response",
            )
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            parsed = None
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        raise FlowLlmClientError(
            self._sanitize("Malformed LLM JSON content: expected JSON object"),
            "malformed_model_response",
        )

    def _sanitize(self, text: str) -> str:
        out = str(text or "")
        if self.api_key:
            out = out.replace(self.api_key, "***")
        out = out.replace("Bearer ", "Bearer ***")
        return out

    @staticmethod
    def _classify_http(code: int, detail: str) -> str:
        if code in {401, 403}:
            return "authentication_failed"
        if code == 429:
            return "rate_limited"
        if code == 404 or ("model" in detail.lower() and "not found" in detail.lower()):
            return "model_unavailable"
        if code >= 500:
            return "provider_failure"
        return "provider_failure"
