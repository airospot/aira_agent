"""Load structured-memory flags from ConfigurationManager (defaults = safe)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

_CONFIG_KEY_TO_ENV = {
    "memory_structured_enabled": "MEMORY_STRUCTURED_ENABLED",
    "memory_structured_shadow_mode": "MEMORY_STRUCTURED_SHADOW_MODE",
    "memory_structured_min_confidence": "MEMORY_STRUCTURED_MIN_CONFIDENCE",
    "memory_sensitive_filter_enabled": "MEMORY_SENSITIVE_FILTER_ENABLED",
}


def _env_bool(name: str) -> Optional[bool]:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None


def _env_float(name: str) -> Optional[float]:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None


@dataclass(frozen=True)
class StructuredMemoryRuntimeFlags:
    enabled: bool
    shadow_mode: bool
    min_confidence: float
    sensitive_filter_enabled: bool


def load_structured_memory_flags(
    customer_id: int,
    user_id: int,
    *,
    overrides: Optional[Dict[str, Any]] = None,
) -> StructuredMemoryRuntimeFlags:
    """
    Resolve flags. ``overrides`` supplies key->value for unit tests (bypasses DB config).

    When not using ``overrides``, these environment variables override DB config (for local / ops):
    ``MEMORY_STRUCTURED_ENABLED``, ``MEMORY_STRUCTURED_SHADOW_MODE``,
    ``MEMORY_STRUCTURED_MIN_CONFIDENCE``, ``MEMORY_SENSITIVE_FILTER_ENABLED``.
    """
    if overrides is not None:

        def _get(key: str, default: Any) -> Any:
            if key not in overrides:
                return default
            return overrides[key]

    else:
        from app.core.config_manager import get_config_manager_for_customer

        cm = get_config_manager_for_customer(customer_id=customer_id, user_id=user_id)

        def _get(key: str, default: Any) -> Any:
            env_name = _CONFIG_KEY_TO_ENV.get(key)
            if env_name:
                if key == "memory_structured_min_confidence":
                    ev = _env_float(env_name)
                else:
                    ev = _env_bool(env_name)
                if ev is not None:
                    return ev
            v = cm.get_config(key, default=default)
            return default if v is None else v

    return StructuredMemoryRuntimeFlags(
        enabled=bool(_get("memory_structured_enabled", False)),
        shadow_mode=bool(_get("memory_structured_shadow_mode", True)),
        min_confidence=float(_get("memory_structured_min_confidence", 0.5)),
        sensitive_filter_enabled=bool(_get("memory_sensitive_filter_enabled", False)),
    )


def should_inject_structured_into_prompt(flags: StructuredMemoryRuntimeFlags) -> bool:
    """True when structured rows may be prepended to LLM context (not shadow-only)."""
    return flags.enabled and not flags.shadow_mode
