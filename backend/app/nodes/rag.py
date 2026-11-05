import logging
import re

from backend.app.state import PlannerState
from backend.app.prompts import (
    build_rag_query, RAG_HYDE_SYSTEM, build_rag_hyde_user,
    build_rag_extract_system, build_rag_extract_user,
)
from backend.app.services.config import settings
from backend.app.services.rag_component import aretrieve

logger = logging.getLogger(__name__)

# 提取结果中常见但并非景点的词，避免误触发补搜
_RAG_NAME_STOPWORDS = {
    "未检索到相关内容", "景点", "旅游景点", "旅游景区", "景区", "美食",
    "攻略", "路线", "注意事项", "行程", "酒店", "住宿", "交通",
}


async def rag_info_node(state: PlannerState, llm, tools) -> dict:
    query = build_rag_query(state)

    answer = query
    if settings.rag_use_hyde:
        logger.info("[RAG Agent] LLM生成假设文档中...")
        try:
            result = await llm.ainvoke([
                {"role": "system", "content": RAG_HYDE_SYSTEM},
                {"role": "user", "content": build_rag_hyde_user(query)},
            ])
            hyde_answer = result.content if hasattr(result, "content") else str(result)
            if hyde_answer.strip():
                answer = hyde_answer
                logger.info("[RAG Agent] 假设文档: %s", answer)
            else:
                logger.warning("[RAG Agent] 假设文档为空，回退问句检索")
        except Exception as e:
            logger.warning("[RAG Agent] HyDE 生成失败，回退问句检索: %s", e)

    docs = await aretrieve(answer, city=state.get("city"))
    if not docs:
        logger.info("[RAG Agent] 未检索到相关内容，跳过景点名提取")
        return {"rag_result": "未检索到相关内容。", "rag_attraction_names": set()}

    context = "\n\n".join(
        f"[来源:{d.metadata.get('source', '旅迹智绘')}]\n{d.page_content}"
        for d in docs
    )
    try:
        rag_attraction_result = await llm.ainvoke([
            {"role": "system", "content": build_rag_extract_system(state.get("city"))},
            {"role": "user", "content": build_rag_extract_user(context)},
        ])
        rag_names_raw = rag_attraction_result.content if hasattr(rag_attraction_result, "content") else ""
    except Exception as e:
        # 提取失败只影响补搜，不应中断整次规划
        logger.warning("[RAG Agent] 景点名提取失败，跳过补搜: %s", e)
        return {"rag_result": context, "rag_attraction_names": set()}
    stopwords = _RAG_NAME_STOPWORDS | {state.get("city", "")}
    rag_names = {
        n.strip()
        for n in re.split(r"[,，、;；\s]+", rag_names_raw)
        if n.strip() and len(n.strip()) >= 2 and n.strip() not in stopwords
    }
    logger.info("[RAG Agent] 知识库景点名称: %s", rag_names)
    return {"rag_result": context if context else "未检索到相关内容。",
            "rag_attraction_names": rag_names}
