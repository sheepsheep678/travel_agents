import asyncio
from backend.app.services.config import get_settings
from langchain_mcp_adapters.client import MultiServerMCPClient

# 全局缓存变量
_client = None
_tools = []


# 内部异步初始化函数
async def _init_async():
    global _client, _tools

    # 防止重复初始化
    if _client is not None:
        return

    api_key = get_settings().amap_api_key
    # mcp_server_config = {
    #     "amap": {
    #         "transport": "stdio",
    #         "command": "npx",
    #         "args": ["-y", "@amap/amap-maps-mcp-server"],
    #         "env": {"AMAP_MAPS_API_KEY": api_key},
    #     }
    # }

    mcp_server_config = {
        "amap": {
            "transport": "sse",
            "url": f"https://mcp.amap.com/sse?key={api_key}",
        }
    }

    print("正在启动 MCP 服务并连接...")
    _client = MultiServerMCPClient(mcp_server_config)

    try:
        # 核心耗时操作：启动进程、握手、获取工具列表
        _tools = await _client.get_tools()
        print(f"成功加载 {len(_tools)} 个工具")

        # 打印工具名确认
        for t in _tools:
            print(f" - {t.name}: {t.description}")

    except Exception as e:
        print(f"MCP工具初始化失败: {e}")
        import traceback
        traceback.print_exc()


# ==========================================
# 对外暴露的同步接口
# ==========================================

def _ensure_initialized():
    """确保初始化完成（同步阻塞）"""
    if _client is None:
        # 使用 asyncio.run 驱动异步初始化
        # 注意：这是脚本写法。在 FastAPI 中不要这样用，
        # 应改由 FastAPI lifespan 调用 init_amap_mcp_async()。
        asyncio.run(_init_async())


async def init_amap_mcp_async():
    """异步初始化 MCP 客户端（供 FastAPI lifespan 使用）"""
    await _init_async()


async def close_amap_mcp():
    """关闭 MCP 客户端（供 FastAPI lifespan shutdown 使用）

    MultiServerMCPClient 没有提供 aclose/close 方法，进程退出时会自动释放连接，
    这里只清空缓存引用，避免在关闭阶段报错。
    """
    global _client, _tools
    _client = None
    _tools = []


def get_amap_mcp_client():
    """获取 Client 对象"""
    _ensure_initialized()
    return _client


def get_amap_mcp_tools():
    """获取 Tools 列表"""
    _ensure_initialized()
    return _tools


# ==========================================
# 测试入口
# ==========================================
if __name__ == "__main__":
    # 1. 获取工具列表（第一次调用会触发初始化）
    tools_list = get_amap_mcp_tools()
    print(f"\n获取到工具数量: {len(tools_list)}")

    # 2. 再次获取（直接走缓存，不会重新连接）
    client = get_amap_mcp_client()
    print(f"Client 对象: {client}")
