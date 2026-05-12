"""MCP Client 管理器 — 连接外部 MCP Server 并管理生命周期。

启动时通过 ``stdio_client`` 以子进程方式启动 MCP Server，
保持连接直至 shutdown。支持同时连接多个 MCP Server。

典型用法::

    manager = MCPClientManager()
    session = await manager.connect(MCPServerConfig(
        name="mempalace",
        command="python",
        args=["-m", "mempalace.mcp_server"],
    ))
    # session 可用于 list_tools / call_tool
    # ...
    await manager.disconnect_all()  # shutdown 时调用
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """一个 MCP Server 的连接配置。

    Attributes:
        name   : 显示名称，如 ``"mempalace"``。
        command: 可执行文件路径，如 ``"python"``。
        args   : 命令参数列表，如 ``["-m", "mempalace.mcp_server"]``。
        env    : 额外环境变量（可选）。
    """

    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    url: str = ""
    transport: str = "stdio"


class MCPClientManager:
    """管理多个 MCP Server 连接的生命周期。

    内部使用 ``AsyncExitStack`` 来正确管理
    ``stdio_client`` 和 ``ClientSession`` 两层 async context manager。
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}

    async def connect(self, config: MCPServerConfig) -> ClientSession:
        """连接一个 MCP Server。

        启动子进程、完成 MCP 握手、返回可用的 ``ClientSession``。

        Args:
            config: MCP Server 配置。

        Returns:
            已初始化的 ``ClientSession`` 实例。

        Raises:
            RuntimeError: 连接或初始化失败。
        """
        if config.transport == "sse":
            from mcp.client.sse import sse_client
            logger.info("正在连接 MCP Server (SSE): %s (%s)", config.name, config.url)
            transport = await self._stack.enter_async_context(
                sse_client(url=config.url)
            )
        else:
            logger.info("正在连接 MCP Server (Stdio): %s (%s %s)", config.name, config.command, config.args)
            params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=config.env,
            )
            # stdio_client 是 async context manager，管理子进程生命周期
            transport = await self._stack.enter_async_context(
                stdio_client(params)
            )
            
        read_stream, write_stream = transport

        # ClientSession 是 async context manager，管理 MCP 协议会话
        session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )

        # MCP 握手
        await session.initialize()

        self._sessions[config.name] = session
        logger.info("MCP Server 已连接: %s", config.name)
        return session

    def get_session(self, name: str) -> ClientSession | None:
        """按名称获取已连接的 MCP Session。"""
        return self._sessions.get(name)

    @property
    def connected_servers(self) -> list[str]:
        """当前已连接的 MCP Server 名称列表。"""
        return list(self._sessions.keys())

    async def disconnect_all(self) -> None:
        """关闭所有 MCP 连接（shutdown 时调用）。

        按 LIFO 顺序退出所有 context manager，
        确保 session 先关闭、子进程再终止。
        """
        logger.info("正在断开所有 MCP 连接...")
        try:
            await self._stack.aclose()
        except Exception:
            logger.exception("断开 MCP 连接时出错")
        self._sessions.clear()
        logger.info("所有 MCP 连接已断开")
