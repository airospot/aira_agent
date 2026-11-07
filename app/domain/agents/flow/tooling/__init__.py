"""Shared tool registry / executor (A01)."""

from app.domain.agents.flow.tooling.errors import (
    ToolNotPermittedError,
    ToolNotRegisteredError,
    ToolRegistrationError,
    ToolResultValidationError,
    ToolValidationError,
)
from app.domain.agents.flow.tooling.executor import ToolExecutor
from app.domain.agents.flow.tooling.native_bootstrap import build_native_tool_registry
from app.domain.agents.flow.tooling.registry import ToolRegistry
from app.domain.agents.flow.tooling.spec import ToolResult, ToolSpec

__all__ = [
    "ToolExecutor",
    "ToolNotPermittedError",
    "ToolNotRegisteredError",
    "ToolRegistrationError",
    "ToolRegistry",
    "ToolResult",
    "ToolResultValidationError",
    "ToolSpec",
    "ToolValidationError",
    "build_native_tool_registry",
]
