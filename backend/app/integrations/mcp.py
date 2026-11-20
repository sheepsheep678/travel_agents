"""多 MCP 服务管理：高德地图、时间、12306。

- 高德地图：SSE，用于行程规划（景点 / 酒店 / 天气）。
- 时间：官方 mcp-server-time（stdio，``python -m mcp_server_time``）。
- 12306：社区 12306-mcp（stdio，``npx -y 12306-mcp``），用于对话助手的车次查询。

各服务独立初始化：某个服务失败只记入 ``errors``，不影响其他服务与后端启动。
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import sys
from typing import Any, Iterable, Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from backend.app.core.config import settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

AMAP = "amap"
TIME = "time"
RAIL = "rail"


class McpRegistry:
    def __init__(self) -> None:
        self.client: Optional[MultiServerMCPClient] = None
        self.tools: dict[str, list[BaseTool]] = {}
        self.errors: dict[str, str] = {}
        self.connections: dict[str, dict[str, Any]] = {}

    async def init(self) -> None:
        self.connections = _build_connections()
        if not self.connections:
            logger.warning("没有可用的 MCP 服务配置，跳过初始化")
            return

        self.client = MultiServerMCPClient(self.connections)
        await asyncio.gather(
            *(self._load_one(name) for name in self.connections),
            return_exceptions=False,
        )

    async def _load_one(self, name: str) -> None:
        assert self.client is not None
        try:
            tools = await asyncio.wait_for(
                self.client.get_tools(server_name=name),
                timeout=settings.mcp.init_timeout,
            )
            self.tools[name] = tools
            self.errors.pop(name, None)
            logger.info("MCP 服务已加载", server=name, tool_count=len(tools))
            for tool in tools:
                logger.debug("MCP 工具", server=name, tool=tool.name)
        except Exception as exc:
            self.errors[name] = f"{type(exc).__name__}: {exc}"
            logger.exception("MCP 服务初始化失败", server=name)

    def get_tools(self, *servers: str) -> list[BaseTool]:
        names: Iterable[str] = servers or self.tools.keys()
        tools: list[BaseTool] = []
        for name in names:
            tools.extend(self.tools.get(name, []))
        return tools

    def get_tool(self, name: str) -> Optional[BaseTool]:
        for tools in self.tools.values():
            for tool in tools:
                if tool.name == name:
                    return tool
        return None

    @property
    def ready(self) -> dict[str, bool]:
        return {name: bool(self.tools.get(name)) for name in self.connections}

    def close(self) -> None:
        # MultiServerMCPClient 没有 aclose/close；每个工具调用会创建独立 session，
        # 这里只清空引用，进程退出时由 anyio 释放。
        self.client = None
        self.tools.clear()
        self.errors.clear()
        self.connections.clear()


def _build_connections() -> dict[str, dict[str, Any]]:
    connections: dict[str, dict[str, Any]] = {}

    if settings.amap.api_key:
        connections[AMAP] = {
            "transport": "sse",
            "url": f"https://mcp.amap.com/sse?key={settings.amap.api_key}",
        }

    if settings.mcp.time_enabled:
        connections[TIME] = {
            "transport": "stdio",
            "command": settings.mcp.time_command.strip() or sys.executable,
            "args": [
                "-m",
                "mcp_server_time",
                "--local-timezone",
                settings.mcp.local_timezone,
            ],
        }

    if settings.mcp.rail_enabled:
        command, args = _rail_command()
        connections[RAIL] = {
            "transport": "stdio",
            "command": command,
            "args": args,
        }

    return connections


def _rail_command() -> tuple[str, list[str]]:
    """构造 12306 MCP 的启动命令（Windows 需要经 cmd.exe 执行 npx.cmd）。"""
    configured = settings.mcp.rail_command.strip()
    args = shlex.split(settings.mcp.rail_args) or ["-y", "12306-mcp"]
    if os.name == "nt":
        npx = configured or shutil.which("npx.cmd") or shutil.which("npx") or "npx"
        return os.environ.get("COMSPEC", "cmd.exe"), ["/c", npx, *args]
    npx = configured or shutil.which("npx") or "npx"
    return npx, args


_registry = McpRegistry()


def get_mcp_registry() -> McpRegistry:
    return _registry


async def init_mcp_async() -> None:
    """供 FastAPI lifespan 调用。"""
    await _registry.init()


async def close_mcp() -> None:
    _registry.close()
    logger.info("MCP 服务引用已清空")


def get_mcp_tools(*servers: str) -> list[BaseTool]:
    return _registry.get_tools(*servers)


def get_mcp_tool(name: str) -> Optional[BaseTool]:
    return _registry.get_tool(name)


def get_mcp_status() -> dict[str, Any]:
    return {"ready": _registry.ready, "errors": dict(_registry.errors)}


def ensure_initialized_sync() -> None:
    """脚本场景的同步初始化；在运行中的事件循环里请改用 init_mcp_async。"""
    if _registry.connections:
        return
    asyncio.run(_registry.init())


if __name__ == "__main__":
    from backend.app.core.logging import setup_logging

    setup_logging()
    asyncio.run(_registry.init())
    print(f"服务状态: {_registry.ready}")
    for server, tools in _registry.tools.items():
        print(f"[{server}] {len(tools)} 个工具")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")
    if _registry.errors:
        print(f"错误: {_registry.errors}")
