"""Bridge MCP server tools into the local Tool registry."""

from __future__ import annotations

import logging
from typing import Any

from mcp import ClientSession
from pydantic import BaseModel, create_model

from tools.base import Context, Tool, ToolResult
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def _build_pydantic_model(
    tool_name: str,
    input_schema: dict[str, Any],
) -> type[BaseModel]:
    """Build a lightweight Pydantic model from an MCP JSON schema."""
    if not input_schema or not input_schema.get("properties"):
        return create_model(f"{tool_name}_Input")

    properties: dict[str, Any] = input_schema.get("properties", {})
    required: set[str] = set(input_schema.get("required", []))

    field_definitions: dict[str, Any] = {}
    for name, prop in properties.items():
        python_type = _json_type_to_python(prop.get("type", "string"))
        if name in required:
            field_definitions[name] = (python_type, ...)
        else:
            field_definitions[name] = (python_type, prop.get("default"))

    return create_model(f"{tool_name}_Input", **field_definitions)


def _json_type_to_python(json_type: str) -> type:
    mapping: dict[str, type] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    return mapping.get(json_type, str)


class MCPToolWrapper(Tool):
    """Expose a remote MCP tool through the local Tool interface."""

    is_read_only = True

    def __init__(
        self,
        session: ClientSession,
        tool_name: str,
        tool_description: str,
        tool_input_schema: dict[str, Any],
        server_name: str,
    ) -> None:
        self.name = tool_name
        self.description = tool_description or f"MCP tool from {server_name}"
        self._session = session
        self._server_name = server_name
        self.input_schema = _build_pydantic_model(tool_name, tool_input_schema)

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        arguments = params.model_dump(exclude_none=True)
        logger.debug("Calling MCP tool %s.%s(%s)", self._server_name, self.name, arguments)

        result = await self._session.call_tool(self.name, arguments=arguments)

        output_parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text"):
                output_parts.append(block.text)
            else:
                output_parts.append(str(block))

        return ToolResult(
            output="\n".join(output_parts),
            metadata={
                "mcp_server": self._server_name,
                "tool": self.name,
            },
        )

    def to_anthropic_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema.model_json_schema(),
        }


async def register_mcp_tools(
    session: ClientSession,
    registry: ToolRegistry,
    server_name: str,
) -> int:
    """Discover tools from an MCP session and register them strictly."""
    tools_response = await session.list_tools()
    count = 0

    for tool_def in tools_response.tools:
        try:
            wrapped = MCPToolWrapper(
                session=session,
                tool_name=tool_def.name,
                tool_description=tool_def.description or "",
                tool_input_schema=(
                    tool_def.inputSchema if hasattr(tool_def, "inputSchema") else {}
                ),
                server_name=server_name,
            )
            registry.register(
                wrapped,
                source="mcp",
                metadata={
                    "server_name": server_name,
                    "tool_name": tool_def.name,
                },
            )
            count += 1
            logger.debug("Registered MCP tool %s.%s", server_name, tool_def.name)
        except Exception as exc:
            logger.exception("Failed to register MCP tool %s.%s", server_name, tool_def.name)
            raise RuntimeError(
                f"Failed to register MCP tool {server_name}.{tool_def.name}: {exc}",
            ) from exc

    logger.info(
        "MCP server %s: discovered %d tools, registered %d",
        server_name,
        len(tools_response.tools),
        count,
    )
    return count
