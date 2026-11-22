"""应用配置聚合根。

设计约定：
- 唯一实例：``from backend.app.core.config import settings``。
- 按模块分组：``settings.llm`` / ``settings.database`` / ``settings.rag`` ...
  每组是一个独立的 ``BaseSettings``，直接读取仓库根目录的 ``.env``。
- 字段使用 ``validation_alias`` 保留历史环境变量名（如 ``OPENAI_API_KEY``），
  因此重构不会破坏已有 ``.env`` / 部署环境。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/app -> backend -> 仓库根目录
_APP_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _APP_DIR.parent.parent
_ENV_FILE = _REPO_ROOT / ".env"
_DATA_DIR = _APP_DIR / "data"

# 兼容脚本里直接 os.getenv 的旧写法；pydantic-settings 自身也会读取 .env
load_dotenv(_ENV_FILE)
_legacy_env = _REPO_ROOT / "langgraph" / ".env"
if _legacy_env.exists():
    load_dotenv(_legacy_env, override=False)

logger = logging.getLogger(__name__)


class _SettingsGroup(BaseSettings):
    """所有配置分组的基类：共用 .env 路径与宽松的额外字段策略。"""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class Settings:
    """配置聚合根，使用方式：``settings = Settings()``。"""

    class App(_SettingsGroup):
        name: str = Field(default="旅迹智绘", validation_alias="APP_NAME")
        version: str = Field(default="1.0.0", validation_alias="APP_VERSION")
        debug: bool = Field(default=False, validation_alias="DEBUG")

    class Server(_SettingsGroup):
        host: str = Field(default="0.0.0.0", validation_alias="HOST")
        port: int = Field(default=8000, validation_alias="PORT")
        cors_origins: str = Field(
            default=(
                "http://localhost:5173,http://localhost:3000,"
                "http://127.0.0.1:5173,http://127.0.0.1:3000"
            ),
            validation_alias="CORS_ORIGINS",
        )

        @property
        def cors_origins_list(self) -> List[str]:
            raw = (self.cors_origins or "").strip()
            if not raw:
                raw = (
                    "http://localhost:5173,http://localhost:3000,"
                    "http://127.0.0.1:5173,http://127.0.0.1:3000"
                )
            return [origin.strip() for origin in raw.split(",") if origin.strip()]

    class Database(_SettingsGroup):
        """PostgreSQL 连接配置。

        连接信息全部由环境变量提供，并带默认值；URL 由 ``build_url`` 自动拼接，
        避免在 .env 里维护带协议/驱动前缀的完整 URL。
        """

        host: str = Field(
            default="127.0.0.1",
            validation_alias=AliasChoices("POSTGRES_HOST", "DB_HOST"),
        )
        port: int = Field(
            default=5432,
            validation_alias=AliasChoices("POSTGRES_PORT", "DB_PORT"),
        )
        user: str = Field(
            default="postgres",
            validation_alias=AliasChoices("POSTGRES_USER", "DB_USER"),
        )
        password: str = Field(
            default="postgres",
            validation_alias=AliasChoices("POSTGRES_PASSWORD", "DB_PASSWORD"),
        )
        name: str = Field(
            default="travel_agents",
            validation_alias=AliasChoices(
                "POSTGRES_DB", "POSTGRES_DATABASE", "DB_NAME"
            ),
        )
        echo: bool = Field(default=False, validation_alias="DATABASE_ECHO")
        pool_size: int = Field(default=10, validation_alias="DATABASE_POOL_SIZE")
        max_overflow: int = Field(default=20, validation_alias="DATABASE_MAX_OVERFLOW")

        def build_url(self, driver: str) -> str:
            """自动拼接 URL；用户名/密码做 URL 编码，避免 @ : / 等字符破坏 URL。"""
            username = quote(self.user or "", safe="")
            password = quote(self.password or "", safe="")
            auth = f"{username}:{password}" if password else username
            return f"{driver}://{auth}@{self.host}:{self.port}/{self.name}"

        @computed_field
        @property
        def url(self) -> str:
            """增删改查元数据：SQLAlchemy + asyncpg。"""
            return self.build_url("postgresql+asyncpg")

        @computed_field
        @property
        def checkpoint_url(self) -> str:
            """LangGraph checkpointer：psycopg 连接串。"""
            return self.build_url("postgresql")

    class Amap(_SettingsGroup):
        api_key: str = Field(default="", validation_alias="AMAP_API_KEY")

    class LLM(_SettingsGroup):
        api_key: str = Field(
            default="",
            validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
        )
        base_url: str = Field(
            default="https://dashscope.aliyuncs.com/compatible-mode/v1",
            validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"),
        )
        model_id: str = Field(
            default="qwen3.8-max",
            validation_alias=AliasChoices("OPENAI_MODEL_ID", "LLM_MODEL_ID"),
        )
        embedding_model_name: str = Field(
            default="text-embedding-v4",
            validation_alias="EMBEDDING_MODEL_NAME",
        )

        # 调用参数：快模型用于 RAG / 评估 / 景点描述，主模型用于规划
        timeout: float = Field(default=90.0, validation_alias="OPENAI_TIMEOUT")
        plan_timeout: float = Field(default=180.0, validation_alias="OPENAI_PLAN_TIMEOUT")
        max_retries: int = Field(default=1, validation_alias="OPENAI_MAX_RETRIES")
        max_tokens: Optional[int] = Field(default=None, validation_alias="OPENAI_MAX_TOKENS")
        fast_model_id: str = Field(default="qwen3.8-flash", validation_alias="OPENAI_FAST_MODEL_ID")
        fast_max_tokens: Optional[int] = Field(default=4096, validation_alias="OPENAI_FAST_MAX_TOKENS")
        fast_temperature: float = Field(default=0.1, validation_alias="OPENAI_FAST_TEMPERATURE")
        fast_extra_body: str = Field(default="", validation_alias="OPENAI_FAST_EXTRA_BODY")
        plan_extra_body: str = Field(default="", validation_alias="OPENAI_PLAN_EXTRA_BODY")
        disable_thinking: bool = Field(default=True, validation_alias="OPENAI_DISABLE_THINKING")
        plan_disable_thinking: bool = Field(
            default=True, validation_alias="OPENAI_PLAN_DISABLE_THINKING"
        )

    class Rag(_SettingsGroup):
        use_hyde: bool = Field(default=True, validation_alias="RAG_USE_HYDE")
        name_fuzzy_match: bool = Field(default=True, validation_alias="RAG_NAME_FUZZY_MATCH")
        # Milvus 入库账本：文件内容 MD5 去重
        md5_milvus_path: str = Field(
            default=str(_DATA_DIR / "md5_milvus.text"),
            validation_alias="MD5_MILVUS_PATH",
        )
        corpus_dir: str = Field(
            default=str(_DATA_DIR / "corpus"), validation_alias="CORPUS_DIR"
        )

    class Milvus(_SettingsGroup):
        """Milvus 向量库与混合检索配置。

        集合 schema 创建后不可变：修改字段/维度/度量需显式删除集合后重建
        （``python -m backend.app.scripts.init_milvus --recreate``）。
        """

        uri: str = Field(
            default="http://127.0.0.1:19530", validation_alias="MILVUS_URI"
        )
        token: str = Field(default="", validation_alias="MILVUS_TOKEN")
        db_name: str = Field(default="default", validation_alias="MILVUS_DB_NAME")
        collection: str = Field(
            default="knowledge_chunks", validation_alias="MILVUS_COLLECTION"
        )
        dense_dim: int = Field(default=1024, validation_alias="MILVUS_DENSE_DIM")
        dense_metric: str = Field(
            default="COSINE", validation_alias="MILVUS_DENSE_METRIC"
        )
        sparse_metric: str = Field(
            default="BM25", validation_alias="MILVUS_SPARSE_METRIC"
        )
        analyzer_tokenizer: str = Field(
            default="jieba", validation_alias="MILVUS_ANALYZER_TOKENIZER"
        )
        # 多路召回条数 + 精排后保留条数
        dense_candidates: int = Field(
            default=20, validation_alias="MILVUS_DENSE_CANDIDATES"
        )
        sparse_candidates: int = Field(
            default=20, validation_alias="MILVUS_SPARSE_CANDIDATES"
        )
        final_top_k: int = Field(default=6, validation_alias="MILVUS_FINAL_TOP_K")
        # Cross-Encoder 精排（DashScope gte-rerank，失败时回退 RRF 融合）
        rerank_enabled: bool = Field(
            default=True, validation_alias="MILVUS_RERANK_ENABLED"
        )
        rerank_model: str = Field(
            default="gte-rerank-v2", validation_alias="MILVUS_RERANK_MODEL"
        )
        rerank_top_n: int = Field(default=6, validation_alias="MILVUS_RERANK_TOP_N")
        rerank_max_candidates: int = Field(
            default=40, validation_alias="MILVUS_RERANK_MAX_CANDIDATES"
        )
        connect_timeout: float = Field(
            default=5.0, validation_alias="MILVUS_CONNECT_TIMEOUT"
        )

    class Planner(_SettingsGroup):
        max_llm_retries: int = Field(default=1, validation_alias="PLAN_MAX_LLM_RETRIES")
        eval_skip_llm_on_hard_issues: bool = Field(
            default=True, validation_alias="EVAL_SKIP_LLM_ON_HARD_ISSUES"
        )
        hotel_anchor_concurrency: int = Field(
            default=3, validation_alias="HOTEL_ANCHOR_CONCURRENCY"
        )

    class Knowledge(_SettingsGroup):
        max_file_mb: int = Field(default=10, validation_alias="KNOWLEDGE_MAX_FILE_MB")
        max_text_chars: int = Field(default=20000, validation_alias="KNOWLEDGE_MAX_TEXT_CHARS")
        max_pdf_pages: int = Field(default=50, validation_alias="KNOWLEDGE_MAX_PDF_PAGES")
        admin_token: str = Field(default="", validation_alias="KNOWLEDGE_ADMIN_TOKEN")
        vlm_model: str = Field(default="", validation_alias="KNOWLEDGE_VLM_MODEL")
        # 父子块切分：父块入 PostgreSQL，子块入 Milvus
        parent_chunk_size: int = Field(
            default=2500, validation_alias="KNOWLEDGE_PARENT_CHUNK_SIZE"
        )
        parent_chunk_overlap: int = Field(
            default=100, validation_alias="KNOWLEDGE_PARENT_CHUNK_OVERLAP"
        )
        child_chunk_size: int = Field(
            default=400, validation_alias="KNOWLEDGE_CHILD_CHUNK_SIZE"
        )
        child_chunk_overlap: int = Field(
            default=50, validation_alias="KNOWLEDGE_CHILD_CHUNK_OVERLAP"
        )
        # 大模型 Markdown 排版优化（只整理格式，不增删事实）
        markdown_normalize: bool = Field(
            default=True, validation_alias="KNOWLEDGE_MARKDOWN_NORMALIZE"
        )
        markdown_normalize_max_chars: int = Field(
            default=12000, validation_alias="KNOWLEDGE_MARKDOWN_MAX_CHARS"
        )
        # MinerU 云端 Precision API（mineru-open-sdk，文件会上传到 mineru.net）
        mineru_enabled: bool = Field(
            default=False, validation_alias="MINERU_ENABLED"
        )
        # mineru.net 的 API Token（https://mineru.net/apiManage/token）
        mineru_token: str = Field(default="", validation_alias="MINERU_TOKEN")
        # 是否开启 OCR；对应 client.extract(..., ocr=True)
        mineru_ocr: bool = Field(default=True, validation_alias="MINERU_OCR")
        # 云端解析模型：vlm / pipeline / html（留空由 SDK 按文件类型推断）
        mineru_model: str = Field(default="vlm", validation_alias="MINERU_MODEL")
        # 文档语言，例如 ch / en
        mineru_language: str = Field(default="ch", validation_alias="MINERU_LANGUAGE")
        # 可选页码范围，例如 1-20；留空解析全部页
        mineru_pages: str = Field(default="", validation_alias="MINERU_PAGES")
        # 云端任务轮询超时（秒）
        mineru_timeout: int = Field(default=300, validation_alias="MINERU_TIMEOUT")
        mineru_fallback: bool = Field(
            default=True, validation_alias="MINERU_FALLBACK"
        )

    class Logging(_SettingsGroup):
        level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
        json_logs: bool = Field(default=False, validation_alias="LOG_JSON")
        colors: bool = Field(default=True, validation_alias="LOG_COLORS")

    class Chat(_SettingsGroup):
        max_tool_rounds: int = Field(default=3, validation_alias="CHAT_MAX_TOOL_ROUNDS")
        tool_timeout: float = Field(default=60.0, validation_alias="CHAT_TOOL_TIMEOUT")
        response_timeout: float = Field(default=180.0, validation_alias="CHAT_RESPONSE_TIMEOUT")
        max_history_messages: int = Field(
            default=20, validation_alias="CHAT_MAX_HISTORY_MESSAGES"
        )
        max_tool_result_chars: int = Field(
            default=6000, validation_alias="CHAT_MAX_TOOL_RESULT_CHARS"
        )
        # 对话 Agent 是否挂载知识库混合检索工具
        rag_tool_enabled: bool = Field(
            default=True, validation_alias="CHAT_RAG_TOOL_ENABLED"
        )

    class Mcp(_SettingsGroup):
        init_timeout: float = Field(default=60.0, validation_alias="MCP_INIT_TIMEOUT")
        local_timezone: str = Field(default="Asia/Shanghai", validation_alias="LOCAL_TIMEZONE")
        time_enabled: bool = Field(default=True, validation_alias="MCP_TIME_ENABLED")
        rail_enabled: bool = Field(default=True, validation_alias="MCP_12306_ENABLED")
        # 默认使用当前解释器运行 python -m mcp_server_time
        time_command: str = Field(default="", validation_alias="MCP_TIME_COMMAND")
        # 默认自动探测 npx；Windows 上通常是 npx.cmd
        rail_command: str = Field(default="", validation_alias="MCP_12306_COMMAND")
        rail_args: str = Field(default="-y 12306-mcp", validation_alias="MCP_12306_ARGS")

    def __init__(self) -> None:
        self.app = self.App()
        self.server = self.Server()
        self.database = self.Database()
        self.amap = self.Amap()
        self.llm = self.LLM()
        self.rag = self.Rag()
        self.milvus = self.Milvus()
        self.planner = self.Planner()
        self.knowledge = self.Knowledge()
        self.chat = self.Chat()
        self.logging = self.Logging()
        self.mcp = self.Mcp()


settings = Settings()


def get_settings() -> Settings:
    return settings


def validate_config() -> bool:
    """启动校验：缺 AMAP_API_KEY 时 fail-fast。"""
    errors: list[str] = []
    warnings: list[str] = []

    if not settings.amap.api_key:
        errors.append("AMAP_API_KEY 未配置")
    if not settings.llm.api_key:
        warnings.append("OPENAI_API_KEY / LLM_API_KEY 未配置，LLM 功能可能无法使用")
    if settings.database.user == "postgres" and settings.database.password == "postgres":
        warnings.append(
            "PostgreSQL 仍是默认 postgres/postgres，请通过 POSTGRES_USER / "
            "POSTGRES_PASSWORD 配置真实账号"
        )

    if errors:
        raise ValueError("配置错误:\n" + "\n".join(f"  - {e}" for e in errors))
    for warning in warnings:
        logger.warning("配置警告: %s", warning)
    return True


def print_config() -> None:
    """打印当前配置（隐藏敏感信息），用于本地排查。"""
    print(f"应用名称: {settings.app.name}")
    print(f"版本: {settings.app.version}")
    print(f"服务器: {settings.server.host}:{settings.server.port}")
    print(
        f"数据库: {settings.database.host}:{settings.database.port}/"
        f"{settings.database.name} (user={settings.database.user})"
    )
    print(f"高德地图API Key: {'已配置' if settings.amap.api_key else '未配置'}")
    print(f"LLM API Key: {'已配置' if settings.llm.api_key else '未配置'}")
    print(f"LLM Base URL: {settings.llm.base_url}")
    print(f"LLM Model: {settings.llm.model_id}")
    print(
        f"RAG 向量库: Milvus "
        f"{settings.milvus.uri}/{settings.milvus.collection}"
    )
    print(f"日志级别: {settings.logging.level}")


if __name__ == "__main__":
    print_config()
