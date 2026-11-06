import asyncio
import json
import logging
import re
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.app.models.response import Attraction, ErrorResponse, Location
from backend.app.state import PlannerState
from backend.app.constants import (
    IO_CONCURRENCY, DETAIL_FETCH_RETRIES, DETAIL_RETRY_DELAY, POI_TOP_K,
    ATTRACTION_DESC_TIMEOUT,
)
from backend.app.prompts import ATTRACTION_DESCRIPTION_SYSTEM, build_attraction_description_prompt
from backend.app.nodes.utils import _extract_text, get_tool, fetch_details, find_uncovered_names
from backend.app.services.config import settings

logger = logging.getLogger(__name__)


# 非景点过滤：保留 08 体育休闲 / 11 风景名胜 / 14 科教文化 三个大类
_NON_ATTRACTION_TYPECODE_PREFIXES = (
    "01", "02", "03", "04", "05", "06", "07", "09",
    "10", "12", "13", "15", "16", "17", "18", "19", "20",
)

# 只匹配 type 的最后一级，避免「科教文化服务;学校;大学」被中间的「学校」误杀
_NON_ATTRACTION_TYPE_WORDS = frozenset({
    "商场", "购物中心", "百货商场", "超市", "便利店",
    "写字楼", "商务楼", "住宅区", "小区", "公寓",
    "停车场", "停车库", "银行", "自动提款机",
    "学校", "中学", "小学", "幼儿园",
    "医院", "诊所", "药店", "餐厅", "饭店", "咖啡馆",
    "火车站", "汽车站", "地铁站", "公交站", "机场", "加油站",
    "政府机关", "公司", "工厂", "仓库",
})

# 名称中带这些词时一律判为非景点（优先于下面的名称救回，避免「XX公园停车场」被救回）
_NON_ATTRACTION_NAME_WORDS = frozenset({
    "停车场", "停车库", "银行", "自动提款机", "加油站",
    "地铁站", "公交站", "火车站", "汽车站", "机场",
    "医院", "诊所", "药店", "购物中心", "商场", "超市", "便利店",
    "写字楼", "公司", "工厂", "仓库",
})

# typecode/type 判为非景点时的名称救回标记（多字强语义，避免单字误救）
_ATTRACTION_NAME_MARKERS = (
    "景区", "风景区", "旅游区", "游览区", "名胜", "公园", "广场",
    "博物馆", "纪念馆", "展览馆", "美术馆", "科技馆", "海洋馆", "水族馆",
    "动物园", "植物园", "寺", "庙", "教堂", "道观", "故居", "旧址", "遗址",
    "古镇", "古城", "古村", "栈桥", "码头", "浴场", "海滩", "沙滩",
    "步行街", "商业街", "老街",
)

# 游览时长推断：按顺序匹配，第一条命中即返回（具体类别必须排在泛类别之前）
_VISIT_DURATION_RULES = (
    (("博物馆", "纪念馆", "展览馆", "美术馆", "科技馆", "海洋馆",
      "水族馆", "陈列馆"), 120),
    (("主题乐园", "游乐园", "乐园", "动物园", "植物园",
      "海洋公园", "欢乐谷"), 180),
    (("古镇", "古城", "古村", "历史文化街区", "历史街区"), 180),
    (("风景名胜区", "风景名胜", "风景区", "景区",
      "国家森林公园", "森林公园", "湿地公园"), 180),
    (("公园", "广场", "湿地"), 90),
    (("海滩", "海水浴场", "浴场", "海滨", "沙滩"), 90),
    (("寺", "庙", "教堂", "道观", "塔", "阁", "楼", "祠"), 60),
    (("街", "路", "巷", "栈桥", "码头", "桥"), 60),
    (("岛", "山", "峰", "岭"), 120),
)
_DEFAULT_VISIT_DURATION = 90


def is_non_attraction_poi(poi: dict) -> bool:
    """按 typecode 大类 + type 末级词表判断是否非景点；名称含强景点标记时保留"""
    if not isinstance(poi, dict):
        return True
    name = str(poi.get("name") or "").strip()
    typecode = str(poi.get("typecode") or "")
    type_str = str(poi.get("type") or "")
    segments = [s.strip() for s in type_str.split(";") if s.strip()]
    last_type = segments[-1] if segments else ""

    # 住宿类硬排除，不做名称救回（避免「XX温泉度假酒店」被当成景点）
    if typecode.startswith("10"):
        return True

    by_code = any(typecode.startswith(p) for p in _NON_ATTRACTION_TYPECODE_PREFIXES)
    by_type = bool(last_type) and any(w in last_type for w in _NON_ATTRACTION_TYPE_WORDS)
    if not (by_code or by_type):
        return False
    # 名称本身带强非景点词时不做救回（如「XX公园停车场」「XX大学附属医院」）
    if any(w in name for w in _NON_ATTRACTION_NAME_WORDS):
        return True
    return not any(marker in name for marker in _ATTRACTION_NAME_MARKERS)


def _parse_location(value) -> Optional[Location]:
    if isinstance(value, dict):
        lng, lat = value.get("longitude"), value.get("latitude")
    elif isinstance(value, str) and "," in value:
        lng, lat = value.split(",", 1)
    else:
        return None
    try:
        lng_f, lat_f = float(str(lng).strip()), float(str(lat).strip())
    except (TypeError, ValueError):
        return None
    if not (-180 <= lng_f <= 180 and -90 <= lat_f <= 90):
        return None
    if abs(lng_f) < 1e-6 and abs(lat_f) < 1e-6:
        return None
    return Location(longitude=lng_f, latitude=lat_f)


def _parse_rating(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    if not m:
        return None
    rating = float(m.group())
    return rating if rating > 0 else None


def _parse_photos(value) -> List[str]:
    if isinstance(value, str):
        raw_urls = value.split(",")
    elif isinstance(value, list):
        raw_urls = [str(v) for v in value]
    else:
        return []
    photos, seen = [], set()
    for url in raw_urls:
        url = url.strip()
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            photos.append(url)
    return photos[:10]


def _parse_ticket_price(value) -> int:
    """只提取原始数据中的显式数字；缺失/免费一律为 0，绝不按知名度猜测"""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("price") or value.get("cost") or ""
    if not isinstance(value, str):
        return 0
    m = re.search(r"\d+(?:\.\d+)?", value.strip())
    return int(float(m.group())) if m else 0


def _infer_visit_duration(name: str, type_str: str, category: str) -> int:
    haystack = "；".join(x for x in (name, category, type_str) if x)
    for keywords, minutes in _VISIT_DURATION_RULES:
        if any(k in haystack for k in keywords):
            return max(30, min(240, minutes))
    return _DEFAULT_VISIT_DURATION


def _fallback_description(name: str, category: str, raw: dict, city: str) -> str:
    """确定性简介模板，保证 description 非空；只用原始字段，不补未提供的信息"""
    cat = category or "景点"
    parts = [f"{name}是{city}的{cat}" if city else f"{name}是一处{cat}"]
    alias = raw.get("alias")
    if isinstance(alias, str) and alias.strip():
        parts.append(f"又称{alias.strip()}")
    area = raw.get("business_area")
    if isinstance(area, str) and area.strip():
        parts.append(f"位于{area.strip()}一带")
    opentime = raw.get("opentime2")
    if isinstance(opentime, str) and opentime.strip():
        parts.append(f"开放时间{opentime.strip()}")
    return ("，".join(parts) + "。")[:200]


def map_attraction_details(poi_details: list, city: str = "") -> List[Attraction]:
    """确定性解析景点原始数据，直接映射为景点模型（坐标/图片/门票均来自原始字段）"""
    attractions = []
    skipped = 0
    for raw in poi_details or []:
        if not isinstance(raw, dict) or is_non_attraction_poi(raw):
            skipped += 1
            continue
        name = str(raw.get("name") or "").strip()
        location = _parse_location(raw.get("location"))
        if not name or location is None:
            skipped += 1
            logger.info("[景点Agent] 跳过无名称/坐标的POI: %s", name or raw.get("id"))
            continue

        type_str = str(raw.get("type") or "")
        segments = [s.strip() for s in type_str.split(";") if s.strip()]
        category = segments[-1] if segments else "景点"
        photos = _parse_photos(raw.get("photo"))
        attractions.append(Attraction(
            name=name,
            address=raw.get("address") if isinstance(raw.get("address"), str) else "",
            location=location,
            visit_duration=_infer_visit_duration(name, type_str, category),
            description=_fallback_description(name, category, raw, city),
            category=category,
            rating=_parse_rating(raw.get("rating")),
            photos=photos,
            poi_id=str(raw.get("id") or ""),
            image_url=photos[0] if photos else None,
            ticket_price=_parse_ticket_price(raw.get("cost")),
        ))
    if skipped:
        logger.info("[景点Agent] 原始 %d 条，跳过 %d 条非景点/无效数据",
                    len(poi_details or []), skipped)
    return attractions


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
    if state.get("search_round", 0) > 0:
        # 补搜轮只搜 RAG 未覆盖的名称，避免重搜 preferences 导致整链重复
        missing = sorted(find_uncovered_names(rag_names, attr_names, settings.rag_name_fuzzy_match))
        keyword_list = missing
    else:
        keyword_list = list(state.get("preferences", []) or ["景点"])
    keyword_list = list(dict.fromkeys(keyword_list))
    if not keyword_list:
        logger.info("[景点Agent] 无待补搜景点，跳过")
        return {"attractions_raw": ""}
    search_semaphore = asyncio.Semaphore(IO_CONCURRENCY)

    async def search_one(keyword: str):
        async with search_semaphore:
            tool_args = {"keywords": keyword, "city": state["city"]}
            try:
                search_result = await search_tool.ainvoke(tool_args)
                search_data = json.loads(_extract_text(search_result))
                # 排除住宿类 POI（typecode 10xxxx）：景点名检索可能返回同名酒店
                return [(poi.get("id"), poi.get("name"), poi)
                        for poi in search_data.get("pois", [])[:POI_TOP_K]
                        if not str(poi.get("typecode", "")).startswith("10")]
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
        # 清空 raw，避免 enrich 把上一轮数据再送进 LLM
        return {"attractions_raw": "", "parse_error": [ErrorResponse(message="未搜索到景点")]}

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


class AttractionDescriptionItem(BaseModel):
    name: str = Field(..., description="景点名称，必须与输入完全一致")
    description: str = Field(..., description="40-80字中文景点简介")


class AttractionDescriptionList(BaseModel):
    descriptions: List[AttractionDescriptionItem] = Field(default_factory=list)


def _build_raw_lookup(raw_items: list) -> tuple:
    by_id, by_name = {}, {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("id") or "")
        name = str(raw.get("name") or "").strip()
        if pid:
            by_id[pid] = raw
        if name:
            by_name[name] = raw
    return by_id, by_name


def _dedup_new(items: List[Attraction], existing: List[Attraction]) -> List[Attraction]:
    """只保留真正新增的景点：补搜轮若命中同一 POI，避免列表 reducer 累积重复项"""
    existing_ids = {a.poi_id for a in existing if a.poi_id}
    existing_names = {a.name for a in existing}
    new_items, seen_ids, seen_names = [], set(), set()
    for a in items:
        if (a.poi_id and a.poi_id in existing_ids) or a.name in existing_names:
            continue
        if (a.poi_id and a.poi_id in seen_ids) or a.name in seen_names:
            continue
        if a.poi_id:
            seen_ids.add(a.poi_id)
        seen_names.add(a.name)
        new_items.append(a)
    return new_items


async def _enrich_attraction_descriptions(new_items, raw_by_id, raw_by_name, city, llm) -> None:
    """快模型只生成 description；失败/超时/空返回时保留映射阶段的模板兜底"""
    if not new_items or llm is None:
        return

    items = []
    for a in new_items:
        raw = raw_by_id.get(a.poi_id or "") or raw_by_name.get(a.name) or {}
        items.append({
            "name": a.name,
            "type": str(raw.get("type") or "")[:120],
            "alias": str(raw.get("alias") or "")[:60],
            "business_area": str(raw.get("business_area") or "")[:60],
            "opentime2": str(raw.get("opentime2") or "")[:120],
        })

    try:
        structured_llm = llm.with_structured_output(AttractionDescriptionList)
        result = await asyncio.wait_for(
            structured_llm.ainvoke([
                {"role": "system", "content": ATTRACTION_DESCRIPTION_SYSTEM},
                {"role": "user", "content": build_attraction_description_prompt(city, items)},
            ]),
            timeout=ATTRACTION_DESC_TIMEOUT,
        )
    except Exception as e:
        logger.warning("[景点Agent] 描述生成失败，保留模板兜底: %s", e)
        return

    desc_by_name = {}
    for item in getattr(result, "descriptions", None) or []:
        name = str(getattr(item, "name", "") or "").strip()
        desc = str(getattr(item, "description", "") or "").strip()
        if name and desc:
            desc_by_name.setdefault(name, desc[:300])
    if not desc_by_name:
        logger.info("[景点Agent] 描述为空，保留模板兜底")
        return

    hit = 0
    for a in new_items:
        desc = desc_by_name.get(a.name)
        if desc:
            a.description = desc
            hit += 1
    logger.info("[景点Agent] 描述生成 %d/%d，其余使用模板", hit, len(new_items))


# 查询工具景点信息 enrich 节点：确定性映射 + 快模型仅生成 description
async def attraction_enrich_node(state: PlannerState, llm, tools) -> dict:
    raw_data = state.get("attractions_raw", "")
    if not raw_data:
        return {"attractions_result": []}

    try:
        raw_items = json.loads(raw_data)
    except (json.JSONDecodeError, TypeError):
        logger.warning("[景点Agent] attractions_raw 解析失败")
        return {"attractions_result": [],
                "parse_error": [ErrorResponse(message="景点原始数据解析失败")]}
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        return {"attractions_result": []}

    city = state.get("city", "")
    raw_by_id, raw_by_name = _build_raw_lookup(raw_items)
    mapped = map_attraction_details(raw_items, city)
    new_items = _dedup_new(mapped, state.get("attractions_result", []))

    if new_items:
        await _enrich_attraction_descriptions(new_items, raw_by_id, raw_by_name, city, llm)

    logger.info("[景点Agent] 完成，新增 %d 个景点", len(new_items))
    return {"attractions_result": new_items}
