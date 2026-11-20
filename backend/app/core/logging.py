"""structlog 日志配置。

只在进程入口（``backend.app.main``）调用一次 :func:`setup_logging`。
其他模块用 :func:`get_logger` 获取 structlog logger；历史代码里的
``logging.getLogger`` 也会经由 ProcessorFormatter 输出同样的彩色/结构化格式。
"""

from __future__ import annotations

import logging
import sys

import structlog

from backend.app.core.config import settings


def setup_logging(
    level: str | None = None,
    *,
    json_logs: bool | None = None,
    colors: bool | None = None,
) -> None:
    cfg = settings.logging
    level_name = (level or cfg.level or "INFO").upper()
    use_json = cfg.json_logs if json_logs is None else json_logs
    use_colors = cfg.colors if colors is None else colors

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if use_json
        else structlog.dev.ConsoleRenderer(colors=use_colors)
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level_name)

    # 让 uvicorn 的日志走我们配置的根 handler，避免默认格式与重复输出
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # 第三方库默认偏吵，压到 WARNING
    for name in (
        "httpx",
        "httpcore",
        "chromadb",
        "urllib3",
        "asyncio",
        "mcp",
        "mcp.client",
        "langchain",
        "langgraph",
        "sqlalchemy.engine",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取 structlog logger；``get_logger(__name__)`` 即可。"""
    return structlog.get_logger(name)
