import json
import logging
import re

from backend.app.models.response import ErrorResponse, Hotel, Location
from backend.app.state import PlannerState
from backend.app.constants import (
    IO_CONCURRENCY, POI_TOP_K, HOTEL_SEARCH_RADIUS, HOTEL_TYPECODE_PREFIX,
)
from backend.app.nodes.utils import _extract_text, get_tool, haversine_km, fetch_details

logger = logging.getLogger(__name__)


def map_hotel_details(hotel_details, anchor_locs) -> list:
    """确定性解析酒店原始数据，直接映射为酒店模型"""
    hotels = []
    for d in hotel_details:
        location = None
        loc_str = d.get("location", "")
        if isinstance(loc_str, str) and "," in loc_str:
            try:
                lng, lat = loc_str.split(",")
                location = Location(longitude=float(lng), latitude=float(lat))
            except ValueError:
                location = None

        type_str = d.get("type", "")
        hotel_type = type_str.split(";")[-1] if isinstance(type_str, str) and type_str else ""

        rating = d.get("rating", "")
        rating = str(rating) if rating not in ([], "", None) else ""

        cost = d.get("cost")
        if isinstance(cost, list) and cost:
            cost = cost[0]
        price_range = ""
        estimated_cost = 0
        if isinstance(cost, str) and cost.strip():
            price_range = cost.strip()
            m = re.search(r"\d+", price_range)
            if m:
                estimated_cost = int(m.group())

        distance = ""
        if location is not None and anchor_locs:
            nearest = min(
                ((haversine_km(location.longitude, location.latitude,
                                loc.longitude, loc.latitude), name)
                 for name, loc in anchor_locs),
                default=None
            )
            if nearest:
                km, name = nearest
                distance = f"距{name}约{km:.1f}km"

        hotels.append(Hotel(
            name=d.get("name", ""),
            address=d.get("address", "") if isinstance(d.get("address"), str) else "",
            location=location,
            price_range=price_range,
            rating=rating,
            distance=distance,
            type=hotel_type,
            estimated_cost=estimated_cost,
        ))
    return hotels


# 酒店节点1：以景点坐标周边搜索酒店，过滤去重并保存前k个
async def hotel_tool_node(state: PlannerState, llm, tools) -> dict:
    attractions = state.get("attractions_result", [])
    if not attractions:
        logger.warning("[酒店Agent] 无可用景点，无法选取酒店位置")
        return {"parse_error": [ErrorResponse(message="无可用景点，无法选取酒店位置")]}

    attraction_names = [a.name for a in attractions]

    around_tool_name = "maps_around_search"
    detail_tool_name = "maps_search_detail"
    around_tool = get_tool(tools, around_tool_name)
    detail_tool = get_tool(tools, detail_tool_name)

    if around_tool is None:
        return {"parse_error": [ErrorResponse(message="周边搜索工具未找到")]}
    if detail_tool is None:
        return {"parse_error": [ErrorResponse(message="酒店详情工具未找到")]}

    anchors = attraction_names
    if not anchors:
        return {}

    # 根据锚点景点名匹配坐标
    anchor_locations = []
    for attraction in state.get("attractions_result", []):
        if attraction.name in anchors and attraction.location is not None:
            anchor_locations.append(
                (attraction.name, f"{attraction.location.longitude},{attraction.location.latitude}")
            )
    if not anchor_locations:
        logger.warning("[酒店Agent] 无法获取锚点景点坐标")
        return {}

    # 逐个锚点周边搜索酒店，按id去重
    hotel_pois = {}
    for anchor_name, loc in anchor_locations:
        tool_args = {"keywords": "酒店", "location": loc, "radius": HOTEL_SEARCH_RADIUS}
        logger.info("[酒店Agent]调用工具: %s, 锚点: %s, 参数: %s", around_tool.name, anchor_name, tool_args)
        search_result = await around_tool.ainvoke(tool_args)

        text_content = _extract_text(search_result)
        try:
            search_data = json.loads(text_content)
            poi_list = search_data.get("pois", [])
        except (json.JSONDecodeError, TypeError):
            logger.warning("[酒店Agent] %s 周边搜索结果解析失败", anchor_name)
            continue

        for p in poi_list[:POI_TOP_K]:
            poi_id = p.get("id")
            # typecode以10开头为住宿服务大类
            if poi_id and poi_id not in hotel_pois and str(p.get("typecode", "")).startswith(HOTEL_TYPECODE_PREFIX):
                hotel_pois[poi_id] = p

    logger.info("[酒店Agent] 共收集到 %d 个酒店", len(hotel_pois))
    if not hotel_pois:
        logger.warning("[酒店Agent] 锚点周边未找到酒店")
        return {}

    hotel_ids = list(hotel_pois.keys())
    logger.info("[酒店Agent] 获取 %d 个酒店详情中...", len(hotel_ids))

    hotel_texts = await fetch_details(
        hotel_ids, detail_tool,
        concurrency=IO_CONCURRENCY, retries=1,
        retry_delay=0, logger=logger,
    )

    hotel_details = []
    for text in hotel_texts:
        try:
            hotel_details.append(json.loads(text))
        except json.JSONDecodeError:
            return {"parse_error": [ErrorResponse(message="酒店详情数据解析失败")]}

    logger.info("[酒店Agent] 解析到 %d 条酒店详情", len(hotel_details))
    if not hotel_details:
        logger.warning("[酒店Agent] 酒店详情数据解析失败")
        return {"parse_error": [ErrorResponse(message="酒店详情数据解析失败")]}

    # 保存原始数据供enrich节点使用
    return {
        "hotel_anchors": anchors,
        "hotels_raw": json.dumps(hotel_details, ensure_ascii=False)
    }


# 酒店节点2：确定性解析酒店原始数据，直接映射为酒店模型
def hotel_enrich_node(state: PlannerState, llm=None, tools=None) -> dict:
    raw_data = state.get("hotels_raw", "")
    if not raw_data:
        return {"hotel_result": [], "hotel_round": state.get("hotel_round", 0) + 1}

    try:
        hotel_details = json.loads(raw_data)
    except json.JSONDecodeError:
        logger.warning("[酒店Agent] hotels_raw 解析失败")
        return {"parse_error": [ErrorResponse(message="酒店原始数据解析失败")], "hotel_round": state.get("hotel_round", 0) + 1}

    # 锚点景点坐标，用于计算距离描述
    anchors = state.get("hotel_anchors", [])
    anchor_locs = [
        (a.name, a.location)
        for a in state.get("attractions_result", [])
        if a.name in anchors and a.location is not None
    ]

    hotels = map_hotel_details(hotel_details, anchor_locs)

    logger.info("[酒店Agent] 完成，共映射 %d 个酒店", len(hotels))
    return {"hotel_result": hotels,
            "hotel_round": state.get("hotel_round", 0) + 1,
            }
