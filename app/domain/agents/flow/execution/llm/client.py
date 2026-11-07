"""Knowledge Flow native LLM istemcisi.

Görev:
    OpenAI-uyumlu Chat Completions üzerinden tek bir JSON karar nesnesi ister.
    GPT-4.1 için kullanılan mevcut istek/yanıt sözleşmesini korur.

Input:
    Constructor: base_url, model, api_key, timeout_seconds (config/factory dışarıdan verir).
    complete_json(system_prompt, user_payload): sistem metni + kullanıcı JSON yükü.

Output:
    Modelin choices[0].message.content içindeki JSON nesnesi (dict).
    Semantik değiştirme yok.

Kullanım örneği:
    client = FlowLlmClient(
        base_url="https://api.openai.com/v1",
        model="gpt-6-luna-3-preview",
        api_key=...,
        timeout_seconds=75,
    )
    decision = client.complete_json(system_prompt, user_payload)

Sorumluluk sınırı:
    Yalnız LLM HTTP çağrısı. Intent, tool seçimi, prompt üretimi, schema
    doğrulama, Gateway, memory, Flow event ve Flask route yok.
    Config: yalnız KNOWLEDGE_FLOW_LLM_* (factory üzerinden).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app.shared.runtime_utils import redact_secrets


class FlowLlmClientError(RuntimeError):
    """LLM taşıma / yanıt hatası."""

    def __init__(self, message: str, error_class: str = "provider_failure"):
        super().__init__(message)
        self.error_class = error_class


class FlowLlmClient:
    """OpenAI-compatible JSON chat client for Knowledge Agent Flow."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: int = 75,
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.model = str(model or "").strip()
        self.api_key = str(api_key or "")
        self.timeout_seconds = int(timeout_seconds)
        self.last_meta: dict[str, Any] = {}
        if not self.base_url:
            raise FlowLlmClientError("base_url required", "provider_unavailable")
        if not self.model:
            raise FlowLlmClientError("model required (expected gpt-6-luna-3-preview)", "model_unavailable")
        if self.model.lower() in {"fake", "mock", "scripted", "stub"}:
            raise FlowLlmClientError(
                f"Unsupported model={self.model!r}.",
                "model_unavailable",
            )
        if not self.api_key:
            raise FlowLlmClientError("api_key required", "authentication_failed")

    def _is_local_openai_compatible(self) -> bool:
        host = self.base_url.lower()
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

    def complete_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        *,
        timeout_seconds: float | int | None = None,
    ) -> dict[str, Any]:
        """Request one JSON decision.

        ``timeout_seconds`` is per-call and does not mutate ``self.timeout_seconds``.
        urllib's timeout is a socket idle/connect bound — not a hard total wall-clock
        guarantee on every platform. Callers should still check run deadlines after return.
        """
        safe_user = redact_secrets(user_payload)
        user_json = json.dumps(safe_user, ensure_ascii=False)
        local = self._is_local_openai_compatible()
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_json},
            ],
        }
        # Local Ollama often rejects or ignores response_format; keep it for cloud APIs.
        if not local:
            body["response_format"] = {"type": "json_object"}
        else:
            # Qwen3.5 reasoning models can hang or leave content empty unless think is off.
            body["think"] = False
            body["max_tokens"] = 2048
            # Server default OLLAMA_CONTEXT_LENGTH=65536 makes local decide huge/slow.
            body["options"] = {"num_ctx": 8192}
        # gpt-6-luna rejects non-default temperature (HTTP 400 unsupported_value).
        # Older OpenAI-compatible models still accept an explicit low temperature.
        if not self.model.lower().startswith("gpt-6-luna"):
            body["temperature"] = 0.1
        call_timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(self.timeout_seconds)
        )
        payload, request_id = self._post_chat(body, timeout_seconds=call_timeout)

        usage = payload.get("usage") or {}
        self.last_meta = {
            "provider": "openai_compatible",
            "model": self.model,
            "request_id": request_id or payload.get("id"),
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "structured_output": (
                "prompt_json_only" if local else "response_format.json_object"
            ),
            "endpoint": f"{self.base_url}/chat/completions",
            "retry": "none",
        }
        try:
            message = (payload.get("choices") or [{}])[0].get("message") or {}
            content = message.get("content")
            if not str(content or "").strip():
                # Some local reasoning models put the answer in `reasoning`.
                content = message.get("reasoning") or message.get("reasoning_content")
            return self._parse_json_object(content)
        except FlowLlmClientError:
            raise
        except Exception as exc:
            raise FlowLlmClientError(
                self._sanitize(f"Malformed LLM JSON content: {exc}"),
                "malformed_model_response",
            ) from None

    def _post_chat(
        self,
        body: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        effective_timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(self.timeout_seconds)
        )
        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                raw = resp.read().decode("utf-8")
                request_id = resp.headers.get("x-request-id") or resp.headers.get(
                    "openai-request-id"
                )
                return json.loads(raw), request_id
        except urllib.error.HTTPError as exc:
            detail = self._sanitize(exc.read().decode("utf-8", errors="ignore")[:400])
            error_class = self._classify_http(exc.code, detail)
            self.last_meta = {
                "provider": "openai_compatible",
                "model": self.model,
                "error_class": error_class,
                "http_status": exc.code,
            }
            raise FlowLlmClientError(
                f"LLM HTTP {exc.code}: {detail}",
                error_class,
            ) from None
        except TimeoutError:
            self.last_meta = {
                "provider": "openai_compatible",
                "model": self.model,
                "error_class": "timeout",
                "timeout_seconds": effective_timeout,
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
