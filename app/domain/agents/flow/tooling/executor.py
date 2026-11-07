"""ToolExecutor — permission, validate-in, handler, validate-out (A01/A03)."""

from __future__ import annotations

import inspect
from copy import deepcopy
from typing import Any, Collection, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from app.domain.agents.flow.tooling.errors import (
    ToolNotPermittedError,
    ToolNotRegisteredError,
    ToolResultValidationError,
    ToolValidationError,
)
from app.domain.agents.flow.tooling.registry import ToolRegistry
from app.domain.agents.flow.tooling.spec import ToolResult


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        permitted_names: Collection[str],
    ) -> None:
        self._registry = registry
        # Explicit allowlist — registration alone never grants permission.
        self._permitted = frozenset(str(n).strip() for n in permitted_names if str(n).strip())

    @property
    def permitted_names(self) -> frozenset[str]:
        return self._permitted

    def execute(
        self,
        name: str,
        arguments: Any,
        *,
        config: Mapping[str, Any] | None = None,
        execution_control: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool_name = str(name or "").strip()
        if not tool_name:
            raise ToolNotRegisteredError("unknown tool: ")
        if tool_name not in self._permitted:
            # Distinguish unknown vs registered-but-denied when possible.
            if self._registry.get(tool_name) is None:
                raise ToolNotRegisteredError(f"unknown tool: {tool_name}")
            raise ToolNotPermittedError(f"tool_not_permitted: {tool_name}")

        try:
            spec = self._registry.require(tool_name)
        except ToolNotRegisteredError:
            raise

        args_copy = deepcopy(arguments) if arguments is not None else None
        try:
            Draft202012Validator(spec.input_schema).validate(args_copy)
        except ValidationError as exc:
            raise ToolValidationError(
                f"invalid arguments for {tool_name}: {exc.message}"
            ) from exc

        raw = self._invoke_handler(
            spec.handler,
            args_copy,
            config=config,
            execution_control=execution_control,
        )
        if not isinstance(raw, Mapping):
            raise ToolResultValidationError(
                f"tool {tool_name} returned non-object result"
            )
        # Return a shallow dict copy of the payload; do not wrap into a new
        # envelope that would drop content/candidates/path/display_url/…
        result_dict = dict(raw)
        try:
            Draft202012Validator(spec.output_schema).validate(result_dict)
        except ValidationError as exc:
            raise ToolResultValidationError(
                f"invalid result for {tool_name}: {exc.message}"
            ) from exc
        return result_dict

    def execute_as_result(
        self,
        name: str,
        arguments: Any,
        *,
        config: Mapping[str, Any] | None = None,
        execution_control: Mapping[str, Any] | None = None,
    ) -> ToolResult:
        return ToolResult(
            data=self.execute(
                name,
                arguments,
                config=config,
                execution_control=execution_control,
            )
        )

    @staticmethod
    def _invoke_handler(
        handler: Any,
        args_copy: Any,
        *,
        config: Mapping[str, Any] | None,
        execution_control: Mapping[str, Any] | None,
    ) -> Any:
        """Call handler; pass execution_control only when accepted (compat)."""
        try:
            params = inspect.signature(handler).parameters
        except (TypeError, ValueError):
            params = {}
        kwargs: dict[str, Any] = {"config": config}
        if execution_control is not None and (
            "execution_control" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
        ):
            kwargs["execution_control"] = execution_control
        try:
            return handler(args_copy, **kwargs)
        except TypeError:
            # Legacy handlers that only accept (arguments, *, config=).
            return handler(args_copy, config=config)
