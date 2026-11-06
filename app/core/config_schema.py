"""Minimal memory config schema for Native Knowledge Flow.

Only keys touched by ``memory_service`` / structured-memory helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class ConfigCategory(Enum):
    SYSTEM = "system"


class ConfigType(Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"


@dataclass
class ConfigValidation:
    required: bool = False
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    allowed_values: Optional[List[str]] = None


@dataclass
class ConfigSetting:
    key: str
    name: str
    description: str
    category: ConfigCategory
    type: ConfigType
    validation: ConfigValidation = field(default_factory=ConfigValidation)
    sensitive: bool = False
    restart_required: bool = False
    ui_group: Optional[str] = None
    ui_order: int = 0
    default: Any = None


class ConfigurationSchema:
    """Memory-only setting definitions + defaults."""

    def __init__(self) -> None:
        self.settings = self._initialize_settings()

    def _initialize_settings(self) -> Dict[str, ConfigSetting]:
        rows = [
            ConfigSetting(
                key="memory_short_term_count",
                name="Short-term Memory Count",
                description="Recent messages kept in short-term memory",
                category=ConfigCategory.SYSTEM,
                type=ConfigType.INTEGER,
                validation=ConfigValidation(required=True, min_value=5, max_value=50),
                default=10,
                ui_group="Memory Configuration",
                ui_order=1,
            ),
            ConfigSetting(
                key="memory_long_term_enabled",
                name="Long-term Memory Enabled",
                description="Enable long-term memory storage",
                category=ConfigCategory.SYSTEM,
                type=ConfigType.BOOLEAN,
                validation=ConfigValidation(required=True),
                default=True,
                ui_group="Memory Configuration",
                ui_order=2,
            ),
            ConfigSetting(
                key="memory_auto_context_enabled",
                name="Auto Context Enabled",
                description="Automatically add memory context to queries",
                category=ConfigCategory.SYSTEM,
                type=ConfigType.BOOLEAN,
                validation=ConfigValidation(required=True),
                default=True,
                ui_group="Memory Configuration",
                ui_order=3,
            ),
            ConfigSetting(
                key="memory_structured_enabled",
                name="Structured Memory Enabled",
                description="Master switch for structured memory",
                category=ConfigCategory.SYSTEM,
                type=ConfigType.BOOLEAN,
                validation=ConfigValidation(required=True),
                default=False,
                ui_group="Memory Configuration",
                ui_order=4,
            ),
            ConfigSetting(
                key="memory_structured_shadow_mode",
                name="Structured Memory Shadow Mode",
                description="Log/extract without injecting into prompts",
                category=ConfigCategory.SYSTEM,
                type=ConfigType.BOOLEAN,
                validation=ConfigValidation(required=True),
                default=True,
                ui_group="Memory Configuration",
                ui_order=5,
            ),
            ConfigSetting(
                key="memory_structured_max_context",
                name="Structured Memory Max Context Rows",
                description="Max structured rows injected into context",
                category=ConfigCategory.SYSTEM,
                type=ConfigType.INTEGER,
                validation=ConfigValidation(required=True, min_value=1, max_value=500),
                default=20,
                ui_group="Memory Configuration",
                ui_order=6,
            ),
            ConfigSetting(
                key="memory_structured_min_confidence",
                name="Structured Memory Min Confidence",
                description="Minimum confidence for structured candidates",
                category=ConfigCategory.SYSTEM,
                type=ConfigType.FLOAT,
                validation=ConfigValidation(required=True, min_value=0.0, max_value=1.0),
                default=0.5,
                ui_group="Memory Configuration",
                ui_order=7,
            ),
            ConfigSetting(
                key="memory_structured_embedding_enabled",
                name="Structured Memory Embedding Enabled",
                description="Embed structured memory_text",
                category=ConfigCategory.SYSTEM,
                type=ConfigType.BOOLEAN,
                validation=ConfigValidation(required=True),
                default=False,
                ui_group="Memory Configuration",
                ui_order=8,
            ),
            ConfigSetting(
                key="memory_sensitive_filter_enabled",
                name="Memory Sensitive Filter Enabled",
                description="Sensitive-content filter before persist",
                category=ConfigCategory.SYSTEM,
                type=ConfigType.BOOLEAN,
                validation=ConfigValidation(required=True),
                default=False,
                ui_group="Memory Configuration",
                ui_order=9,
            ),
            ConfigSetting(
                key="ollama_url",
                name="Ollama URL",
                description="Local embedding / LLM base URL",
                category=ConfigCategory.SYSTEM,
                type=ConfigType.STRING,
                validation=ConfigValidation(required=False),
                default="http://localhost:11434",
                ui_group="Memory Configuration",
                ui_order=10,
            ),
        ]
        return {row.key: row for row in rows}

    def get_settings_by_category(self, category: ConfigCategory) -> List[ConfigSetting]:
        return [s for s in self.settings.values() if s.category == category]

    def defaults(self) -> Dict[str, Any]:
        return {key: setting.default for key, setting in self.settings.items()}


CONFIG_SCHEMA = ConfigurationSchema()
