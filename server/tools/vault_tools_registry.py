"""Standalone Tool registry for vault-tools runner subprocess.

This module is intentionally self-contained. It does not import any
Crabby main-process code so that it can run safely in an isolated
subprocess with no access to backend internals.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolResult(BaseModel):
    """Standardized tool result returned to the caller."""
    output: str
    metadata: dict[str, Any] = {}
    is_truncated: bool = False
    cache_path: str | None = None


class Tool:
    """Minimal Tool ABC compatible with the Crabby Tool interface.

    Subclasses must set:
        name        : str
        description : str
        input_schema: type[BaseModel]
        is_read_only: bool = True

    And implement:
        async def call(self, params: BaseModel, ctx: "Context") -> ToolResult
    """

    name: str
    description: str
    input_schema: type[BaseModel]
    is_read_only: bool = True

    async def call(self, params: BaseModel, ctx: "Context") -> ToolResult:
        raise NotImplementedError

    def to_mcp_schema(self) -> dict[str, Any]:
        """Return the MCP tool schema for list_tools."""
        schema = self.input_schema.model_json_schema()
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": schema,
        }


class Context(BaseModel):
    """Runtime context injected into every tool call."""
    vault_path: str
    permission_level: str = "normal"
    session_id: str | None = None
    conversation_id: str | None = None
    runtime_data_path: Path | None = None  # consistent with tools/base.py Context


class ToolRegistry:
    """Lightweight tool registry for the runner subprocess."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name!r}")
        self._tools[tool.name] = tool
        logger.debug("Registered vault tool: %s", tool.name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def snapshot(self) -> list[tuple[str, Tool]]:
        return [(name, tool) for name, tool in self._tools.items()]
