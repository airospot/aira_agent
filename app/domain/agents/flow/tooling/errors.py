"""Typed errors for tool registry / executor (A01)."""

from __future__ import annotations


class ToolRegistrationError(ValueError):
    """Duplicate or invalid registration."""


class ToolNotRegisteredError(LookupError):
    """Tool name is not in the registry."""


class ToolNotPermittedError(PermissionError):
    """Tool is registered but not in the caller's allowlist."""


class ToolValidationError(ValueError):
    """Input arguments failed schema validation (handler not called)."""


class ToolResultValidationError(ValueError):
    """Handler returned a payload that failed the output schema."""
