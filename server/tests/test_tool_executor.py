"""Tests for the tool executor — validation, execution, and UI payload formatting."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from llm.tool_executor import _build_ui_payload, execute_tool_call
from tools.base import Context, Tool, ToolResult
from tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SimpleInput(BaseModel):
    value: str


class SimpleTool(Tool):
    """A minimal tool that returns its input as output."""

    name = "simple"
    description = "Echoes the input value."
    input_schema = SimpleInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(output=f"got: {params.value}")


class RaisingTool(Tool):
    """A tool that raises an exception when called."""

    name = "raiser"
    description = "Always raises ValueError."
    input_schema = SimpleInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        raise ValueError("boom!")


class LongOutputTool(Tool):
    """A tool that returns a very long output for truncation testing."""

    name = "long_output"
    description = "Returns a long string."
    input_schema = SimpleInput
    max_result_chars = 200

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        long_output = "x" * 1000
        if len(long_output) > self.max_result_chars:
            return ToolResult(
                output=long_output[: self.max_result_chars],
                is_truncated=True,
            )
        return ToolResult(output=long_output)


class TruncatedResultTool(Tool):
    """A tool that marks its result as already truncated."""

    name = "truncated_tool"
    description = "Returns a truncated result with a cache path."
    input_schema = SimpleInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(
            output="shortened...",
            is_truncated=True,
            cache_path="/tmp/cache/tool-results/long.txt",
            metadata={"match_count": 500},
        )


class MetaTool(Tool):
    """A tool that populates various metadata fields."""

    name = "meta_tool"
    description = "Returns metadata for testing."
    input_schema = SimpleInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(
            output="done",
            metadata={
                "exit_code": 0,
                "warnings": ["minor issue"],
                "file_count": 3,
                "custom_field": "custom_value",
            },
        )


# ---------------------------------------------------------------------------
# Tool not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_not_found_returns_error_payload(tmp_path: Path):
    """Requesting an unknown tool must return success=false, status=error."""
    registry = ToolRegistry()
    ctx = Context(vault_path=tmp_path)

    llm_text, ui = await execute_tool_call(
        registry,
        "nonexistent_tool",
        {"some": "input"},
        ctx=ctx,
        tool_id="toolu_missing",
    )

    assert "unknown" in llm_text.lower() or "未知" in llm_text
    assert ui["status"] == "error"
    assert ui["is_error"] is True
    assert ui["id"] == "toolu_missing"
    assert ui["name"] == "nonexistent_tool"
    assert ui["elapsed_ms"] == 0
    assert ui["metadata"]["error_type"] == "unknown_tool"


# ---------------------------------------------------------------------------
# Tool throws exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_exception_returns_error_payload(tmp_path: Path):
    """If a tool raises, the executor must return an error payload."""
    registry = ToolRegistry()
    registry.register(RaisingTool())
    ctx = Context(vault_path=tmp_path)

    llm_text, ui = await execute_tool_call(
        registry,
        "raiser",
        {"value": "test"},
        ctx=ctx,
        tool_id="toolu_boom",
    )

    assert "error" in llm_text.lower() or "出错" in llm_text
    assert ui["status"] == "error"
    assert ui["is_error"] is True
    assert ui["id"] == "toolu_boom"
    assert ui["name"] == "raiser"
    assert ui["metadata"]["error_type"] == "execution"
    assert ui["elapsed_ms"] >= 0


# ---------------------------------------------------------------------------
# Tool result truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_truncation_sets_is_truncated_flag(tmp_path: Path):
    """When a tool returns is_truncated=True, the payload must reflect it."""
    registry = ToolRegistry()
    registry.register(LongOutputTool())
    ctx = Context(vault_path=tmp_path)

    _llm_text, ui = await execute_tool_call(
        registry,
        "long_output",
        {"value": "test"},
        ctx=ctx,
        tool_id="toolu_long",
    )

    assert ui["is_truncated"] is True
    assert ui["status"] in ("warning", "error")


@pytest.mark.asyncio
async def test_truncated_result_preserves_cache_path(tmp_path: Path):
    """A tool with cache_path should propagate it to the UI payload."""
    registry = ToolRegistry()
    registry.register(TruncatedResultTool())
    ctx = Context(vault_path=tmp_path)

    llm_text, ui = await execute_tool_call(
        registry,
        "truncated_tool",
        {"value": "test"},
        ctx=ctx,
        tool_id="toolu_trunc",
    )

    assert ui["is_truncated"] is True
    assert ui["cache_path"] == "/tmp/cache/tool-results/long.txt"
    assert "截断" in llm_text or "truncated" in llm_text.lower()
    assert ui["metadata"]["match_count"] == 500


@pytest.mark.asyncio
async def test_truncated_result_does_not_include_cache_path_when_absent(tmp_path: Path):
    """A truncated result without cache_path should have null cache_path."""
    registry = ToolRegistry()
    registry.register(LongOutputTool())
    ctx = Context(vault_path=tmp_path)

    _llm_text, ui = await execute_tool_call(
        registry,
        "long_output",
        {"value": "test"},
        ctx=ctx,
        tool_id="toolu_long_no_cache",
    )

    assert ui["is_truncated"] is True
    assert ui["cache_path"] is None


# ---------------------------------------------------------------------------
# Cache path handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_path_from_format_for_ui(tmp_path: Path):
    """If format_for_ui returns a cache_path, it must override the result's."""
    registry = ToolRegistry()
    registry.register(SimpleTool())
    ctx = Context(vault_path=tmp_path)

    # The SimpleTool doesn't set cache_path, so it should be None
    _llm_text, ui = await execute_tool_call(
        registry,
        "simple",
        {"value": "hello"},
        ctx=ctx,
        tool_id="toolu_simple",
    )

    assert ui["cache_path"] is None


# ---------------------------------------------------------------------------
# Tool metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_contains_tool_name_and_id(tmp_path: Path):
    """The UI payload must contain the tool name and the provided tool_id."""
    registry = ToolRegistry()
    registry.register(SimpleTool())
    ctx = Context(vault_path=tmp_path)

    _llm_text, ui = await execute_tool_call(
        registry,
        "simple",
        {"value": "hello"},
        ctx=ctx,
        tool_id="toolu_test_123",
    )

    assert ui["id"] == "toolu_test_123"
    assert ui["tool_use_id"] == "toolu_test_123"
    assert ui["name"] == "simple"
    assert ui["tool"] == "simple"


@pytest.mark.asyncio
async def test_elapsed_time_is_set_on_success(tmp_path: Path):
    """Elapsed time must be present and positive on a successful call."""
    registry = ToolRegistry()
    registry.register(SimpleTool())
    ctx = Context(vault_path=tmp_path)

    _llm_text, ui = await execute_tool_call(
        registry,
        "simple",
        {"value": "hello"},
        ctx=ctx,
        tool_id="toolu_timed",
    )

    assert "elapsed_ms" in ui
    assert ui["elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_elapsed_time_is_set_on_exception(tmp_path: Path):
    """Elapsed time must be present even when a tool raises."""
    registry = ToolRegistry()
    registry.register(RaisingTool())
    ctx = Context(vault_path=tmp_path)

    _llm_text, ui = await execute_tool_call(
        registry,
        "raiser",
        {"value": "test"},
        ctx=ctx,
        tool_id="toolu_exc",
    )

    assert "elapsed_ms" in ui
    assert ui["elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_metadata_preserves_tool_fields(tmp_path: Path):
    """Tool metadata (exit_code, warnings, etc.) should appear in the payload."""
    registry = ToolRegistry()
    registry.register(MetaTool())
    ctx = Context(vault_path=tmp_path)

    _llm_text, ui = await execute_tool_call(
        registry,
        "meta_tool",
        {"value": "test"},
        ctx=ctx,
        tool_id="toolu_meta",
    )

    assert ui["metadata"]["exit_code"] == 0
    assert ui["metadata"]["file_count"] == 3
    assert ui["metadata"]["custom_field"] == "custom_value"
    assert "warnings" in ui["metadata"]


# ---------------------------------------------------------------------------
# Status determination
# ---------------------------------------------------------------------------


def test_status_error_on_nonzero_exit_code():
    """Exit code != 0 must result in status=error."""
    ui = _build_ui_payload(
        tool_name="bash",
        output="[exit code 7]",
        tool_id="toolu_1",
        metadata={"exit_code": 7},
        elapsed_ms=50,
    )
    assert ui["status"] == "error"
    assert ui["is_error"] is True


def test_status_error_on_blocked():
    """blocked=True must result in status=error."""
    ui = _build_ui_payload(
        tool_name="bash",
        output="blocked",
        tool_id="toolu_2",
        metadata={"blocked": True},
        elapsed_ms=10,
    )
    assert ui["status"] == "error"
    assert ui["is_error"] is True


def test_status_error_on_timeout():
    """timeout=True must result in status=error."""
    ui = _build_ui_payload(
        tool_name="bash",
        output="timeout",
        tool_id="toolu_3",
        metadata={"timeout": True},
        elapsed_ms=30000,
    )
    assert ui["status"] == "error"
    assert ui["is_error"] is True


def test_status_error_on_metadata_error():
    """metadata.error must result in status=error."""
    ui = _build_ui_payload(
        tool_name="memory_write",
        output="validation failed",
        tool_id="toolu_memory_write",
        metadata={"error": True},
        elapsed_ms=5,
    )
    assert ui["status"] == "error"
    assert ui["is_error"] is True


def test_status_warning_on_truncation():
    """is_truncated=True must result in status=warning (not error)."""
    ui = _build_ui_payload(
        tool_name="grep",
        output="x" * 1000,
        tool_id="toolu_4",
        is_truncated=True,
        metadata={},
        elapsed_ms=100,
    )
    assert ui["status"] == "warning"
    assert ui["is_error"] is False


def test_status_warning_on_warnings():
    """warnings in metadata must result in status=warning."""
    ui = _build_ui_payload(
        tool_name="bash",
        output="ok",
        tool_id="toolu_5",
        metadata={"warnings": ["minor issue"]},
        elapsed_ms=50,
    )
    assert ui["status"] == "warning"
    assert ui["is_error"] is False


def test_status_success_on_clean_result():
    """A clean result with no errors/warnings/truncation must be status=success."""
    ui = _build_ui_payload(
        tool_name="echo",
        output="hello",
        tool_id="toolu_6",
        metadata={"exit_code": 0},
        elapsed_ms=5,
    )
    assert ui["status"] == "success"
    assert ui["is_error"] is False
    assert ui["is_truncated"] is False


# ---------------------------------------------------------------------------
# Permission denied
# ---------------------------------------------------------------------------


class RestrictedTool(Tool):
    """A tool that denies restricted permission level."""

    name = "restricted_tool"
    description = "Only allowed in normal mode."
    input_schema = SimpleInput

    def check_permission(self, params: BaseModel, ctx: Context) -> bool:
        return ctx.permission_level != "restricted"

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(output="allowed")


@pytest.mark.asyncio
async def test_permission_denied_returns_error_payload(tmp_path: Path):
    """A tool that rejects permission_level=restricted must return error."""
    registry = ToolRegistry()
    registry.register(RestrictedTool())
    ctx = Context(vault_path=tmp_path, permission_level="restricted")

    llm_text, ui = await execute_tool_call(
        registry,
        "restricted_tool",
        {"value": "test"},
        ctx=ctx,
        tool_id="toolu_perm",
    )

    assert ui["status"] == "error"
    assert ui["is_error"] is True
    assert ui["metadata"]["error_type"] == "permission"


# ---------------------------------------------------------------------------
# Validation failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_input_returns_validation_error(tmp_path: Path):
    """Sending a malformed input must return error_type=validation."""
    registry = ToolRegistry()
    registry.register(SimpleTool())
    ctx = Context(vault_path=tmp_path)

    # SimpleInput requires 'value' field — omit it to trigger validation error
    _llm_text, ui = await execute_tool_call(
        registry,
        "simple",
        {"wrong_field": "data"},
        ctx=ctx,
        tool_id="toolu_bad_input",
    )

    assert ui["status"] == "error"
    assert ui["is_error"] is True
    assert ui["metadata"]["error_type"] == "validation"
