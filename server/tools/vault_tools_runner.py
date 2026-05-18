"""Vault Tools Runner — MCP stdio subprocess that hosts user-defined vault tools.

This module runs as an isolated subprocess. It:
1. Scans <vault>/.crabby/tools/ for Python files
2. Loads each file's register(registry) entry point
3. Exposes the discovered tools via MCP stdio protocol
4. Handles tool-call requests from the Crabby backend
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any

# ISOLATION: Replace the runner's own directory in sys.path[0] with a safe
# site-packages path.  Deleting sys.path[0] alone is insufficient because
# Python also searches the current working directory independently.
# By overwriting sys.path[0] we prevent the current directory from shadowing
# stdlib modules (e.g. a user file named json.py).
import site
if sys.path:
    try:
        _sp = site.getsitepackages()
        sys.path[0] = _sp[0] if _sp else ""
    except IndexError:
        sys.path[0] = ""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from tools.vault_tools_registry import Context, ToolRegistry, ToolResult

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("vault-tools-runner")


def _load_vault_tools(tools_dir: Path) -> list[Tool]:
    """Discover and load vault tools from the given directory.

    Each Python file at the top level of tools_dir is treated as a tool module.
    It must expose a ``register(registry: ToolRegistry)`` function.
    """
    registry = ToolRegistry()
    loaded: list[Tool] = []

    if not tools_dir.is_dir():
        logger.warning("Vault tools directory does not exist: %s", tools_dir)
        return loaded

    for entry in sorted(tools_dir.iterdir()):
        if entry.is_dir():
            continue
        if entry.suffix != ".py":
            continue
        if entry.name.startswith("_"):
            continue

        module_name = entry.stem
        try:
            spec = importlib.util.spec_from_file_location(module_name, entry)
            if spec is None or spec.loader is None:
                logger.warning("Could not load spec for %s", entry.name)
                continue

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            if not hasattr(module, "register"):
                logger.warning(
                    "Module %s does not expose register(registry) — skipping",
                    module_name,
                )
                continue

            module.register(registry)
            logger.info("Loaded vault tool module: %s", module_name)

        except Exception:
            logger.exception("Failed to load vault tool %s — skipping", entry.name)
            continue

    for name, tool in registry.snapshot():
        loaded.append(tool)

    logger.info("Vault tools runner: discovered %d tools in %s", len(loaded), tools_dir)
    return loaded


async def _run_mcp_server(tools: list[Any]) -> None:
    """Start the MCP stdio server with the given tools."""
    tool_by_name: dict[str, Any] = {t.name: t for t in tools}

    server = Server("vault-tools")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=t.name,
                description=t.description or None,
                inputSchema=t.input_schema.model_json_schema(),
            )
            for t in tools
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        tool = tool_by_name.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")

        vault_path = os.environ.get("VAULT_PATH", "")
        runtime_data_path = os.environ.get("CRABBY_DATA_DIR", "")

        ctx = Context(
            vault_path=vault_path,
            permission_level="normal",
            session_id=None,
            conversation_id=None,
            runtime_data_path=Path(runtime_data_path) if runtime_data_path else None,
        )

        try:
            params = tool.input_schema(**arguments)
        except Exception as exc:
            raise ValueError(f"Invalid arguments for {name}: {exc}") from exc

        result: ToolResult = await tool.call(params, ctx)

        return [TextContent(type="text", text=result.output)]

    # Run until stdin is closed
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    vault_path = os.environ.get("VAULT_PATH", "")
    if not vault_path:
        logger.error("VAULT_PATH environment variable is not set — aborting")
        sys.exit(1)

    tools_dir = Path(vault_path) / ".crabby" / "tools"
    tools = _load_vault_tools(tools_dir)

    try:
        asyncio.run(_run_mcp_server(tools))
    except KeyboardInterrupt:
        logger.info("Vault tools runner shutting down")
    except Exception:
        logger.exception("Vault tools runner crashed")
        sys.exit(1)


if __name__ == "__main__":
    main()
