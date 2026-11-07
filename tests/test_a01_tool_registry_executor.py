"""A01: ToolRegistry / ToolExecutor contracts (no real LLM)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.domain.agents.flow.tooling import (
    ToolExecutor,
    ToolNotPermittedError,
    ToolNotRegisteredError,
    ToolRegistrationError,
    ToolRegistry,
    ToolResultValidationError,
    ToolSpec,
    ToolValidationError,
    build_native_tool_registry,
)
from app.domain.agents.flow.tooling.native_bootstrap import NATIVE_TOOL_NAMES


def _echo_schemas() -> tuple[dict, dict]:
    args = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["text"],
        "properties": {"text": {"type": "string", "minLength": 1}},
    }
    result = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "echo", "error"],
        "properties": {
            "status": {"type": "string", "enum": ["ok"]},
            "echo": {"type": "string"},
            "error": {"type": ["string", "null"]},
        },
    }
    return args, result


def _make_echo_spec(handler=None) -> ToolSpec:
    args, result = _echo_schemas()

    def _handler(arguments, *, config=None):
        return {"status": "ok", "echo": arguments["text"], "error": None}

    return ToolSpec(
        name="test_echo",
        version="v1",
        description="test-only echo",
        input_schema=args,
        output_schema=result,
        handler=handler or _handler,
        catalog_document={
            "name": "test_echo",
            "description": "test-only echo",
            "arguments": args,
        },
        side_effect_class="read",
    )


def test_duplicate_registration_rejected() -> None:
    reg = ToolRegistry()
    reg.register(_make_echo_spec())
    with pytest.raises(ToolRegistrationError, match="duplicate"):
        reg.register(_make_echo_spec())


def test_unknown_and_registered_but_not_permitted() -> None:
    reg = build_native_tool_registry()
    reg.register(_make_echo_spec())
    ex = ToolExecutor(reg, permitted_names={"file_read"})
    with pytest.raises(ToolNotRegisteredError):
        ex.execute("no_such_tool", {"path": "x"})
    with pytest.raises(ToolNotPermittedError):
        ex.execute("test_echo", {"text": "hi"})
    # Registered in catalog but still denied:
    assert "test_echo" in reg.names()
    assert "test_echo" not in ex.permitted_names


def test_invalid_arguments_do_not_call_handler() -> None:
    handler = MagicMock(return_value={"status": "ok", "echo": "x", "error": None})
    reg = ToolRegistry()
    reg.register(_make_echo_spec(handler=handler))
    ex = ToolExecutor(reg, permitted_names={"test_echo"})
    with pytest.raises(ToolValidationError):
        ex.execute("test_echo", {"text": ""})
    handler.assert_not_called()


def test_invalid_result_raises_validation_error() -> None:
    def bad_handler(arguments, *, config=None):
        return {"status": "ok", "echo": 123, "error": None}  # echo must be string

    reg = ToolRegistry()
    reg.register(_make_echo_spec(handler=bad_handler))
    ex = ToolExecutor(reg, permitted_names={"test_echo"})
    with pytest.raises(ToolResultValidationError):
        ex.execute("test_echo", {"text": "hi"})


def test_catalog_mutation_does_not_affect_later_runs() -> None:
    reg = build_native_tool_registry()
    catalog = reg.catalog(names=["file_read"])
    catalog[0]["arguments"]["properties"]["path"]["minLength"] = 9999
    catalog[0]["name"] = "mutated"
    # Original registry still serves file_read with real schema.
    assert reg.require("file_read").name == "file_read"
    assert reg.require("file_read").input_schema["properties"]["path"]["minLength"] == 1


def test_get_require_schema_copies_do_not_affect_validation_or_catalog() -> None:
    reg = build_native_tool_registry()
    viewed = reg.require("file_read")
    handler_ref = viewed.handler
    viewed.input_schema["properties"]["path"]["minLength"] = 9999
    viewed.output_schema["required"] = ["status"]
    viewed.catalog_document["description"] = "mutated-public-view"
    viewed.extra_metadata["x"] = "y"

    again = reg.require("file_read")
    assert again.handler is handler_ref
    assert again.input_schema["properties"]["path"]["minLength"] == 1
    assert "path" in again.output_schema.get("required", [])
    assert again.catalog_document["description"] != "mutated-public-view"
    assert "x" not in again.extra_metadata

    catalog = reg.catalog(names=["file_read"])
    assert catalog[0]["description"] != "mutated-public-view"
    assert catalog[0]["arguments"]["properties"]["path"]["minLength"] == 1

    # Executor validation still accepts a normal short path.
    corpus_ok = {"AGENT_CORPUS_DIR": "."}
    ex = ToolExecutor(reg, permitted_names={"file_read"})
    # missing file is fine — must not fail on minLength 9999 from mutated view
    result = ex.execute("file_read", {"path": "nope.md"}, config=corpus_ok)
    assert result["status"] in {"not_found", "invalid_path", "ok", "not_text", "error"}


def test_native_bootstrap_registers_exactly_four() -> None:
    reg = build_native_tool_registry()
    assert set(reg.names()) == set(NATIVE_TOOL_NAMES)
    assert "test_echo" not in reg.names()


def test_four_native_tools_via_executor(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    guide = corpus / "uat-guide.md"
    guide.write_text(
        "# UAT\nPara birimi TRY\nKalem A 100.00\n",
        encoding="utf-8",
    )
    images = corpus / "images"
    images.mkdir()
    png = images / "tiny.png"
    # Minimal valid-ish PNG header bytes (enough for show_image suffix/size checks)
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    config = {"AGENT_CORPUS_DIR": str(corpus)}
    reg = build_native_tool_registry()
    ex = ToolExecutor(reg, permitted_names=NATIVE_TOOL_NAMES)

    named = ex.execute(
        "file_name_search", {"query": "uat-guide", "limit": 10}, config=config
    )
    assert named["status"] == "ok"
    assert any(c.get("path") == "uat-guide.md" for c in named["candidates"])

    found = ex.execute(
        "file_search", {"query": "TRY", "limit": 10}, config=config
    )
    assert found["status"] == "ok"
    assert found["matched_total"] >= 1
    assert found["candidates"][0]["path"] == "uat-guide.md"

    read = ex.execute("file_read", {"path": "uat-guide.md"}, config=config)
    assert read["status"] == "ok"
    assert "TRY" in (read.get("content") or "")
    assert read.get("path") == "uat-guide.md"

    shown = ex.execute("show_image", {"path": "images/tiny.png"}, config=config)
    assert shown["status"] == "ok"
    assert shown.get("display_url")
    assert "images/tiny.png" in (shown.get("display_url") or "")
    assert shown.get("path") == "images/tiny.png"


def test_symlink_escape_rejected_via_executor(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("leak", encoding="utf-8")
    (corpus / "escape.md").symlink_to(outside)
    config = {"AGENT_CORPUS_DIR": str(corpus)}
    ex = ToolExecutor(build_native_tool_registry(), permitted_names=NATIVE_TOOL_NAMES)

    read = ex.execute("file_read", {"path": "escape.md"}, config=config)
    assert read["status"] in {"invalid_path", "not_found"}
    assert read.get("content") in (None, "")

    search = ex.execute(
        "file_search", {"query": "leak", "limit": 10}, config=config
    )
    assert search["status"] == "ok"
    assert search["matched_total"] == 0
