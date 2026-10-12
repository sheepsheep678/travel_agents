import logging
import re

from backend.app.state import PlannerState
from backend.app.prompts import (
    build_rag_query, RAG_HYDE_SYSTEM, build_rag_hyde_user,
    build_rag_extract_system, build_rag_extract_user,
)
from backend.app.services.rag_component import aretrieve

logger = logging.getLogger(__name__)


async def rag_info_node(state: PlannerState, llm, tools) -> dict:
    query = build_rag_query(state)
    logger.info("[RAG Agent] LLM生成假设文档中...")
    result = await llm.ainvoke([
        {"role": "system", "content": RAG_HYDE_SYSTEM},
        {"role": "user", "content": build_rag_hyde_user(query)},
    ])
    answer = result.content if hasattr(result, "content") else str(result)
    if not answer.strip():
        logger.warning("[RAG Agent] 假设文档为空，回退问句检索")
        answer = query
    logger.info("[RAG Agent] 假设文档: %s", answer)
    docs = await aretrieve(answer, city=state.get("city"))
    context = "\n\n".join(
        f"[来源:{d.metadata.get('source', 'sheep开发者')}]\n{d.page_content}"
        for d in docs
    )
    rag_attraction_result = await llm.ainvoke([
        {"role": "system", "content": build_rag_extract_system(state.get("city"))},
        {"role": "user", "content": build_rag_extract_user(context)},
    ])
    rag_names_raw = rag_attraction_result.content if hasattr(rag_attraction_result, "content") else ""
    rag_names = {n.strip() for n in re.split(r"[,，、;；\s]+", rag_names_raw) if n.strip()}
    logger.info("[RAG Agent] 知识库景点名称: %s", rag_names)
    return {"rag_result": context if context else "未检索到相关内容。",
            "rag_attraction_names": rag_names}
