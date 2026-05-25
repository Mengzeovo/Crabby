"""Tests for vault-tools runner (MCP subprocess for user-defined vault tools)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.vault_tools_registry import Context, Tool, ToolRegistry, ToolResult
from tools import vault_tools_runner
from pydantic import BaseModel as PydanticBaseModel
from vault_tools_entrypoint import VAULT_TOOLS_RUNNER_ARG


# ---------------------------------------------------------------------------
# vault_tools_registry tests
# ---------------------------------------------------------------------------


class DummyInput:
    """Minimal model-like object for testing (non-schema call)."""
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        exclude_none = kwargs.get("exclude_none", False)
        return {
            k: v
            for k, v in self.__dict__.items()
            if not (exclude_none and v is None)
        }


class PydanticDummyInput(PydanticBaseModel):
    """Pydantic model for schema test."""
    query: str


class DummyTool(Tool):
    """A tool with a trivial async call for testing."""
    name = "dummy_tool"
    description = "A test tool that echoes its input."
    input_schema = DummyInput
    is_read_only = True

    async def call(self, params: DummyInput, ctx: Context) -> ToolResult:
        return ToolResult(output=f"echo: {params.query}")


def test_tool_registry_register_and_list() -> None:
    registry = ToolRegistry()
    tool = DummyTool()
    registry.register(tool)

    assert registry.get("dummy_tool") is tool
    assert registry.get("nonexistent") is None

    tools = registry.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "dummy_tool"


def test_tool_registry_duplicate_raises() -> None:
    registry = ToolRegistry()
    registry.register(DummyTool())
    with pytest.raises(ValueError, match="Duplicate tool name"):
        registry.register(DummyTool())


def test_tool_registry_snapshot() -> None:
    registry = ToolRegistry()
    registry.register(DummyTool())
    snapshot = registry.snapshot()

    assert len(snapshot) == 1
    assert snapshot[0][0] == "dummy_tool"
    assert snapshot[0][1].name == "dummy_tool"


def test_tool_to_mcp_schema() -> None:
    """Verify to_mcp_schema works with a real Pydantic input model."""
    class RealTool(Tool):
        name = "real_tool"
        description = "A tool with a real Pydantic schema."
        input_schema = PydanticDummyInput
        is_read_only = True

        async def call(self, params: PydanticDummyInput, ctx: Context) -> ToolResult:
            return ToolResult(output="ok")

    tool = RealTool()
    schema = tool.to_mcp_schema()
    assert schema["name"] == "real_tool"
    assert schema["description"] == "A tool with a real Pydantic schema."
    assert "inputSchema" in schema


def test_tool_result_model() -> None:
    result = ToolResult(output="hello", metadata={"count": 1}, is_truncated=False)
    assert result.output == "hello"
    assert result.metadata == {"count": 1}
    assert result.is_truncated is False
    assert result.cache_path is None


def test_context_model() -> None:
    ctx = Context(vault_path="/tmp/vault", permission_level="restricted")
    assert ctx.vault_path == "/tmp/vault"
    assert ctx.permission_level == "restricted"
    assert ctx.session_id is None
    assert ctx.conversation_id is None


# ---------------------------------------------------------------------------
# vault_tools_runner discovery tests
# ---------------------------------------------------------------------------


def test_load_vault_tools_skips_missing_directory(tmp_path: Path) -> None:
    tools = vault_tools_runner._load_vault_tools(tmp_path / "nonexistent")
    assert tools == []


def test_load_vault_tools_skips_non_python_files(tmp_path: Path) -> None:
    tools_dir = tmp_path / ".crabby" / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "readme.txt").write_text("not a tool")
    (tools_dir / "__init__.py").write_text("# empty")

    tools = vault_tools_runner._load_vault_tools(tools_dir)
    assert tools == []


def test_load_vault_tools_skips_files_without_register(tmp_path: Path) -> None:
    tools_dir = tmp_path / ".crabby" / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "no_register.py").write_text(
        "x = 1\n",
    )

    tools = vault_tools_runner._load_vault_tools(tools_dir)
    assert tools == []


def test_load_vault_tools_skips_broken_modules(tmp_path: Path) -> None:
    tools_dir = tmp_path / ".crabby" / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "broken.py").write_text("raise RuntimeError('oops')")

    tools = vault_tools_runner._load_vault_tools(tools_dir)
    assert tools == []


def test_load_vault_tools_loads_valid_modules(tmp_path: Path) -> None:
    tools_dir = tmp_path / ".crabby" / "tools"
    tools_dir.mkdir(parents=True)

    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "hello_tool.py").write_text(
        "from tools.vault_tools_registry import Tool, ToolRegistry, ToolResult, Context\n"
        "from pydantic import BaseModel\n"
        "\n"
        "class HelloInput(BaseModel):\n"
        "    name: str\n"
        "\n"
        "class HelloTool(Tool):\n"
        "    name = 'hello'\n"
        "    description = 'Say hello'\n"
        "    input_schema = HelloInput\n"
        "\n"
        "    async def call(self, params, ctx):\n"
        "        return ToolResult(output=f'Hello, {params.name}!')\n"
        "\n"
        "def register(registry):\n"
        "    registry.register(HelloTool())\n",
    )

    tools = vault_tools_runner._load_vault_tools(tools_dir)
    assert len(tools) == 1
    assert tools[0].name == "hello"


# ---------------------------------------------------------------------------
# End-to-end subprocess test: runner speaks MCP over stdio
# ---------------------------------------------------------------------------


def test_runner_subprocess_list_tools_via_stdio(tmp_path: Path) -> None:
    """Verify the runner subprocess starts and responds to MCP JSON-RPC."""
    tools_dir = tmp_path / ".crabby" / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "echo_tool.py").write_text(
        "from tools.vault_tools_registry import Tool, ToolRegistry, ToolResult, Context\n"
        "from pydantic import BaseModel\n"
        "\n"
        "class EchoInput(BaseModel):\n"
        "    message: str\n"
        "\n"
        "class EchoTool(Tool):\n"
        "    name = 'echo'\n"
        "    description = 'Echo back the message'\n"
        "    input_schema = EchoInput\n"
        "\n"
        "    async def call(self, params, ctx):\n"
        "        return ToolResult(output=f'echo: {params.message}')\n"
        "\n"
        "def register(registry):\n"
        "    registry.register(EchoTool())\n",
    )

    runner_script = Path(__file__).resolve().parents[1] / "tools" / "vault_tools_runner.py"
    env = {
        "VAULT_PATH": str(tmp_path),
        "CRABBY_DATA_DIR": str(tmp_path / "data"),
    }

    proc = subprocess.Popen(
        [sys.executable, str(runner_script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**subprocess.os.environ, **env},
        text=True,
    )

    try:
        # Send MCP initialize request
        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.0.0"},
            },
        }
        proc.stdin.write(json.dumps(initialize_request) + "\n")
        proc.stdin.flush()

        # Read initialize response
        line = proc.stdout.readline()
        assert line, "Runner produced no output"
        response = json.loads(line)
        assert response["id"] == 1
        assert response["result"]["protocolVersion"] == "2024-11-05"

        # Send initialized notification
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        proc.stdin.write(json.dumps(notification) + "\n")
        proc.stdin.flush()

        # Send tools/list request
        list_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }
        proc.stdin.write(json.dumps(list_request) + "\n")
        proc.stdin.flush()

        line = proc.stdout.readline()
        assert line, "Runner produced no output after tools/list"
        response = json.loads(line)
        assert response["id"] == 2, f"Unexpected response: {response}"
        tools = response["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "echo"
        assert tools[0]["description"] == "Echo back the message"
        assert "inputSchema" in tools[0]

    finally:
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=5)


def test_main_runner_entrypoint_dispatches_before_backend_startup(
    tmp_path: Path,
) -> None:
    """The packaged runner entry should not initialize the FastAPI backend."""
    main_script = Path(__file__).resolve().parents[1] / "main.py"
    env = {
        **subprocess.os.environ,
        "VAULT_PATH": str(tmp_path),
        "CRABBY_DATA_DIR": str(tmp_path / "data"),
    }

    result = subprocess.run(
        [sys.executable, str(main_script), VAULT_TOOLS_RUNNER_ARG],
        capture_output=True,
        text=True,
        env=env,
        input="",
        timeout=10,
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Vault tools directory does not exist" in result.stderr
    assert "on_event is deprecated" not in combined_output
    assert "Uvicorn running" not in combined_output


def test_runner_aborts_when_vault_path_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runner should exit with an error when VAULT_PATH is not set."""
    monkeypatch.delenv("VAULT_PATH", raising=False)
    runner_script = Path(__file__).resolve().parents[1] / "tools" / "vault_tools_runner.py"

    result = subprocess.run(
        [sys.executable, str(runner_script)],
        capture_output=True,
        text=True,
        env={k: v for k, v in subprocess.os.environ.items() if k != "VAULT_PATH"},
        timeout=5,
    )

    assert result.returncode != 0
    # After the path-isolation fix, the runner reaches the VAULT_PATH check.
    assert "VAULT_PATH" in result.stderr
