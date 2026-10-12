import asyncio
import json
import logging
from typing import List

from pydantic import BaseModel

from backend.app.models.response import Attraction, ErrorResponse
from backend.app.state import PlannerState
from backend.app.constants import (
    IO_CONCURRENCY, DETAIL_FETCH_RETRIES, DETAIL_RETRY_DELAY, POI_TOP_K,
)
from backend.app.prompts import ATTRACTION_ENRICH_SYSTEM, build_enrich_prompt
from backend.app.nodes.utils import _extract_text, get_tool, fetch_details

logger = logging.getLogger(__name__)


class AttractionList(BaseModel):
    attractions: List[Attraction]


def backfill_attraction_photos(raw_data: str, attractions: List[Attraction]) -> None:
    """确定性回填照片：LLM 可能漏填/填错图片字段，按 poi_id/name 从原始数据直接注入"""
    try:
        raw_items = json.loads(raw_data)
    except (json.JSONDecodeError, TypeError):
        raw_items = []
    photo_by_id, photo_by_name = {}, {}
    for item in raw_items:
        pid, pname = item.get("id") or "", item.get("name") or ""
        photo = item.get("photo") or ""
        urls = [u.strip() for u in str(photo).split(",") if u.strip()] if photo else []
        if urls:
            if pid:
                photo_by_id[pid] = urls
            if pname:
                photo_by_name[pname] = urls
    for a in attractions:
        urls = photo_by_id.get(a.poi_id or "") or photo_by_name.get(a.name or "")
        if urls:
            a.photos = urls
            a.image_url = a.image_url or urls[0]


# 景点查询工具节点
async def attraction_tool_node(state: PlannerState, llm, tools) -> dict:
    search_tool_name = "maps_text_search"
    detail_tool_name = "maps_search_detail"
    search_tool = get_tool(tools, search_tool_name)
    detail_tool = get_tool(tools, detail_tool_name)

    if search_tool is None:
        logger.error("[景点Agent]%s景点查询工具未找到", search_tool_name)
        return {"parse_error": [ErrorResponse(message="景点查询工具未找到")]}
    if detail_tool is None:
        logger.error("[景点Agent]%s景点详情工具未找到", detail_tool_name)
        return {"parse_error": [ErrorResponse(message="景点详情工具未找到")]}

    rag_names = state.get("rag_attraction_names") or set()
    attr_names = state.get("attraction_names") or set()
    missing = sorted(rag_names - attr_names) if state.get("search_round", 0) > 0 else []
    keyword_list = (state.get("preferences", []) + missing) or ["景点"]
    search_semaphore = asyncio.Semaphore(IO_CONCURRENCY)

    async def search_one(keyword: str):
        async with search_semaphore:
            tool_args = {"keywords": keyword, "city": state["city"]}
            try:
                search_result = await search_tool.ainvoke(tool_args)
                search_data = json.loads(_extract_text(search_result))
                return [(poi.get("id"), poi.get("name"), poi)
                        for poi in search_data.get("pois", [])[:POI_TOP_K]]
            except (json.JSONDecodeError, TypeError):
                logger.warning("[景点Agent] 关键词「%s」搜索结果解析失败", keyword)
                return []

    # 并发搜索各关键词，再统一去重合并
    search_results = await asyncio.gather(*[search_one(kw) for kw in keyword_list])

    poi_list = []
    seen_ids = set()
    new_names = set()
    for results in search_results:
        for poi_id, name, poi in results:
            if poi_id and poi_id not in seen_ids:
                seen_ids.add(poi_id)
                new_names.add(name)
                poi_list.append(poi)

    if not poi_list:
        logger.warning("[景点Agent] 未搜索到任何景点")
        return {"parse_error": [ErrorResponse(message="未搜索到景点")]}

    logger.info("[景点Agent] 景点列表: %s", poi_list)

    # 第二步：提取所有POI ID，调用详情工具
    poi_ids = [poi["id"] for poi in poi_list if poi.get("id")]
    logger.info("[景点Agent] 获取到 %d 个POI ID", len(poi_ids))

    detail_texts = await fetch_details(
        poi_ids, detail_tool,
        concurrency=IO_CONCURRENCY, retries=DETAIL_FETCH_RETRIES,
        retry_delay=DETAIL_RETRY_DELAY, logger=logger,
    )

    poi_details = []
    for text in detail_texts:
        try:
            poi_details.append(json.loads(text))
        except json.JSONDecodeError:
            continue

    logger.info("[景点Agent]解析到 %d 条POI详情", len(poi_details))
    logger.info("[景点Agent]poi_details: %s", poi_details)

    # 第三步：保存原始数据供enrich节点使用
    return {
        "attractions_raw": json.dumps(poi_details, ensure_ascii=False),
        "search_round": state.get("search_round", 0) + 1,
        "attraction_names": new_names,
    }


# 查询工具景点信息 enrich 节点
async def attraction_enrich_node(state: PlannerState, llm, tools) -> dict:
    raw_data = state.get("attractions_raw", "")
    if not raw_data:
        return {"attractions_result": []}

    enrich_prompt = build_enrich_prompt(state["city"], state.get("preferences", []), raw_data)

    logger.info("[景点Agent] LLM整合中...")
    structured_llm = llm.with_structured_output(AttractionList)
    result = await structured_llm.ainvoke([
        {"role": "system", "content": ATTRACTION_ENRICH_SYSTEM},
        {"role": "user", "content": enrich_prompt},
    ])
    logger.info("[景点Agent] 完成，共 %d 个景点", len(result.attractions))

    # 确定性回填照片：LLM 可能漏填/填错图片字段，按 poi_id/name 从原始数据直接注入，保证图片不丢
    backfill_attraction_photos(raw_data, result.attractions)

    return {"attractions_result": result.attractions}
