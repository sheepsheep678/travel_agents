import asyncio
import json
import math
import re
from datetime import timedelta, datetime
from typing import TypedDict, List, Optional, Annotated, Any, Sequence
from langchain_core.messages import BaseMessage
from langgraph.constants import START, END
from langgraph.graph import add_messages, StateGraph
from pydantic import BaseModel, Field

from backend.app.models.response import Attraction, WeatherInfo, Hotel, \
    ErrorResponse, TripPlan, DayPlan, Budget, POIInfo, RouteInfo, Meal, Location
from backend.app.nodes.llm import get_llm
from backend.app.nodes.tools.amap_mcp_servers import get_amap_mcp_client, get_amap_mcp_tools

travel_plan_agent = None


def _add_list(existing: Optional[List[Any]], new: Optional[List[Any]]) -> List[Any]:
    existing = existing or []
    new = new or []
    return existing + new


# 图的状态
class PlannerState(TypedDict):
    city: str
    start_date: str
    end_date: str
    travel_days: int
    transportation: str
    accommodation: str
    preferences: List[str]
    free_text_input: str
    attractions_raw: str
    attractions_result: Annotated[List[Attraction], _add_list]
    meal_result: Annotated[List[Meal], _add_list]
    weather_result: Annotated[List[WeatherInfo], _add_list]
    hotel_anchors: List[str]
    hotels_raw: str
    hotel_result: Annotated[List[Hotel], _add_list]
    route_result: Optional[RouteInfo]
    day_route_locations: List[str]
    final_plan: Optional[TripPlan]
    parse_error: Annotated[list[ErrorResponse], _add_list]
    messages: Annotated[Sequence[BaseMessage], add_messages]

class travel_plan_agents:
    def __init__(self):
        try:
            self.llm = get_llm()
            self.mcp_client = get_amap_mcp_client()
            self.mcp_tools = get_amap_mcp_tools()
            self.attraction_model=self.llm.bind_tools(self.mcp_tools)
            self.weather_model=self.llm.bind_tools(self.mcp_tools)
            self.hotel_model=self.llm.bind_tools(self.mcp_tools)
            self.planner_model=self.llm.bind_tools(self.mcp_tools)
            self.graph=None
        except Exception as e:
            print(f"多智能体系统初始化失败: {e}")
            import traceback
            traceback.print_exc()

    def _build_planner_graph(self):



        def _extract_text(result) -> str:
            """从MCP工具返回结果中提取文本内容"""
            text_content = ""
            if isinstance(result, list):
                for block in result:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_content += block["text"]
            elif hasattr(result, "content"):
                text_content = result.content
            return text_content



        # 景点查询工具节点
        async def attraction_tool_node(state: PlannerState):
            search_tool_name = "maps_text_search"
            detail_tool_name = "maps_search_detail"
            search_tool = next((t for t in self.mcp_tools if t.name == search_tool_name), None)
            detail_tool = next((t for t in self.mcp_tools if t.name == detail_tool_name), None)

            if search_tool is None:
                print(f"[景点Agent]{search_tool_name}景点查询工具未找到")
                return {"parse_error": [ErrorResponse(message="景点查询工具未找到")]}
            if detail_tool is None:
                print(f"[景点Agent]{detail_tool_name}景点详情工具未找到")
                return {"parse_error": [ErrorResponse(message="景点详情工具未找到")]}

            keyword_list = state.get("preferences", []) or ["景点"]
            poi_list = []
            seen_ids = set()
            for keyword in keyword_list:
                tool_args = {"keywords": keyword, "city": state["city"]}
                print(f"[景点Agent]调用工具: {search_tool.name}, 参数: {tool_args}")
                search_result = await search_tool.ainvoke(tool_args)

                text_content = _extract_text(search_result)
                try:
                    search_data = json.loads(text_content)
                except (json.JSONDecodeError, TypeError):
                    print(f"[景点Agent] 关键词「{keyword}」搜索结果解析失败")
                    continue

                for poi in search_data.get("pois", [])[:6]:
                    poi_id = poi.get("id")
                    if poi_id and poi_id not in seen_ids:
                        seen_ids.add(poi_id)
                        poi_list.append(poi)
                print(f"[景点Agent] 关键词「{keyword}」累计候选POI: {len(poi_list)} 个")

            if not poi_list:
                print("[景点Agent] 未搜索到任何景点")
                return {"parse_error": [ErrorResponse(message="未搜索到景点")]}

            print(f"[景点Agent] 景点列表: {poi_list}")

            # 第二步：提取所有POI ID，调用详情工具
            poi_ids = [poi["id"] for poi in poi_list if poi.get("id")]
            print(f"[景点Agent] 获取到 {len(poi_ids)} 个POI ID")

            # detail_texts = []
            # for poi_id in poi_ids:
            #     result = await detail_tool.ainvoke({"id": poi_id})
            #     text = _extract_text(result)
            #     if text and not text.startswith("Error"):
            #         detail_texts.append(text)

            detail_semaphore = asyncio.Semaphore(3)

            async def fetch_detail(poi_id: str):
                async with detail_semaphore:
                    for attempt in range(2):
                        result = await detail_tool.ainvoke({"id": poi_id})
                        text = _extract_text(result)
                        if text and not text.startswith("Error"):
                            return text
                        if attempt == 0:
                            await asyncio.sleep(1)
                    print(f"[景点Agent] POI {poi_id} 详情获取失败: {text[:80] if text else '空返回'}")
                    return None

            detail_texts = [
                t for t in await asyncio.gather(*[fetch_detail(pid) for pid in poi_ids])
                if t is not None
            ]



            poi_details = []
            for text in detail_texts:
                try:
                    poi_details.append(json.loads(text))
                except json.JSONDecodeError:
                    continue

            print(f"[景点Agent]解析到 {len(poi_details)} 条POI详情")
            print(f"[景点Agent]poi_details: {poi_details}")
            # for poi in poi_details:
            #     print(f"[景点Agent]  - {poi.get('name')} | {poi.get('location')} | {poi.get('address')}")

            # 第三步：保存原始数据供enrich节点使用
            return {
                "attractions_raw": json.dumps(poi_details, ensure_ascii=False)
            }

        # 景点信息 enrich 节点
        async def attraction_enrich_node(state: PlannerState):
            raw_data = state.get("attractions_raw", "")
            if not raw_data:
                return {"attractions_result": []}

            class AttractionList(BaseModel):
                attractions: List[Attraction]

            enrich_prompt = f"""你是高德地图POI数据整合专家。以下是通过高德地图POI详情接口获取的景点详情列表(JSON格式)，请将每条数据严格转换为结构化的景点模型。

原始数据字段说明:
- id: POI唯一标识
- name: 景点名称
- location: 经纬度字符串，格式为"经度,纬度"(如"114.365446,30.561506")
- address: 地址
- business_area: 所属商圈
- city: 所在城市
- type: POI类型，分号分隔的层级(如"科教文化服务;博物馆;博物馆")
- alias: 别名
- photo: 图片URL(字符串，可能是单个URL或多个逗号分隔的URL，也可能为空)
- cost: 费用信息(可能为空列表)
- opentime2: 详细开放时间描述
- rating: 评分(字符串，如"4.9"，可能为空)

字段映射规则(必须严格遵守):
1. name: 直接使用原始 name
2. address: 直接使用原始 address
3. location: 将"经度,纬度"字符串拆分为 location 对象，longitude=经度, latitude=纬度，均为数值类型
4. poi_id: 使用原始 id
5. category: 取原始 type 最后一级作为类别(如"博物馆")
6. visit_duration: 根据POI类型推断建议游览时长(分钟)，如博物馆/纪念馆120、公园90、寺庙60等
7. rating: 将字符串评分转为数值(如"4.9"→4.9)，为空时填null
8. ticket_price: 优先从 cost 字段提取(元)；cost 为空时根据景点知名度合理估计，免费景点填0
9. photos: 从 photo 字段提取图片URL组成字符串列表(逗号分隔时拆分)；photo 为空时填空列表
10. image_url: 取 photo 字段的第一个URL；无图片时填null
11. description: 用一句话概括景点特色，可结合 type、alias、business_area 等信息，并附上关键开放时间(opentime2)要点
12. 只保留真正适合旅游的景点，过滤掉商场、写字楼、住宅等非景点数据
13. 不得编造原始数据中不存在的名称、地址或经纬度
14. 如果景点名称重复或者大部分重复，可以合理删减重复项，保留一个代表项

城市: {state['city']}
用户偏好: {state.get('preferences', [])}

POI详情数据:
{raw_data}"""

            print("[景点Agent] LLM整合中...")
            structured_llm = self.llm.with_structured_output(AttractionList)
            result =await structured_llm.ainvoke([
                {"role": "system",
                 "content": "你是景点信息整合专家，擅长将高德地图POI原始数据严格、准确地转换为结构化景点模型，绝不编造或篡改原始数据。"},
                {"role": "user", "content": enrich_prompt}
            ])
            print(f"[景点Agent] 完成，共 {len(result.attractions)} 个景点")

            # 确定性回填照片：LLM 可能漏填/填错图片字段，按 poi_id/name 从原始数据直接注入，保证图片不丢
            raw_items = []
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
            for a in result.attractions:
                urls = photo_by_id.get(a.poi_id or "") or photo_by_name.get(a.name or "")
                if urls:
                    a.photos = urls
                    a.image_url = a.image_url or urls[0]

            return {"attractions_result": result.attractions}


        # 天气查询工具节点
        async def weather_tool_node(state: PlannerState):
            weather_tool_name = "maps_weather"
            weather_tool = next((t for t in self.mcp_tools if t.name == weather_tool_name), None)

            if weather_tool is None:
                print(f"[天气Agent]{weather_tool_name}天气查询工具未找到")
                return {"parse_error": [ErrorResponse(message="天气查询工具未找到")]}

            tool_args = {"city": state["city"]}
            print(f"[天气Agent]调用工具: {weather_tool.name}, 参数: {tool_args}")
            result = await weather_tool.ainvoke(tool_args)
            print("[天气Agent]天气查询result: ", result)


            text_content = _extract_text(result)
            # print("[天气Agent]天气查询text content: ", text_content)
            try:
                data = json.loads(text_content)
            except (json.JSONDecodeError, TypeError):
                print("[天气Agent] 天气数据解析失败")
                return {"parse_error": [ErrorResponse(message="天气数据解析失败")]}

            # 高德 maps_weather 实际返回预报结构: {"city": ..., "forecasts": [{...}]}
            forecasts = data.get("forecasts", [])
            if not forecasts:
                print("[天气Agent] 未获取到天气数据")
                return {"parse_error": [ErrorResponse(message="未获取到天气数据")]}

            weather_list = [
                WeatherInfo(
                    date=f.get("date", ""),
                    day_weather=f.get("dayweather", ""),
                    night_weather=f.get("nightweather", ""),
                    day_temp=f.get("daytemp", 0),
                    night_temp=f.get("nighttemp", 0),
                    wind_direction=f.get("daywind", ""),
                    wind_power=f.get("daypower", ""),
                )
                for f in forecasts
            ]

            print(f"[天气Agent] 解析到 {len(weather_list)} 天天气数据")
            return {"weather_result": weather_list}


        # 酒店节点1：以锚点景点坐标周边搜索酒店，过滤去重并保存前k个
        async def hotel_tool_node(state: PlannerState):
            attractions = state.get("attractions_result", [])
            if not attractions:
                print("[酒店Agent] 无可用景点，无法选取酒店位置")
                return {"parse_error": [ErrorResponse(message="无可用景点，无法选取酒店位置")]}

            attraction_names = [a.name for a in attractions]

            around_tool_name = "maps_around_search"
            detail_tool_name = "maps_search_detail"
            around_tool = next((t for t in self.mcp_tools if t.name == around_tool_name), None)
            detail_tool = next((t for t in self.mcp_tools if t.name == detail_tool_name), None)

            if around_tool is None:
                return {"parse_error": [ErrorResponse(message="周边搜索工具未找到")]}
            if detail_tool is None:
                return {"parse_error": [ErrorResponse(message="酒店详情工具未找到")]}

            anchors = attraction_names
            if not anchors:
                return {"parse_error": [ErrorResponse(message="锚点景点为空")]}

            # 根据锚点景点名匹配坐标
            anchor_locations = []
            for attraction in state.get("attractions_result", []):
                if attraction.name in anchors and attraction.location is not None:
                    anchor_locations.append(
                        (attraction.name, f"{attraction.location.longitude},{attraction.location.latitude}")
                    )
            if not anchor_locations:
                print("[酒店Agent] 无法获取锚点景点坐标")
                return {"parse_error": [ErrorResponse(message="无法获取锚点景点坐标")]}

            # 逐个锚点周边搜索酒店，按id去重
            hotel_pois = {}
            for anchor_name, loc in anchor_locations:
                tool_args = {"keywords": "酒店", "location": loc, "radius": "3000"}
                print(f"[酒店Agent]调用工具: {around_tool.name}, 锚点: {anchor_name}, 参数: {tool_args}")
                search_result = await around_tool.ainvoke(tool_args)
                # print(f"[酒店Agent] {anchor_name} 周边搜索结果: {search_result}")

                text_content = _extract_text(search_result)
                # print(f"[酒店Agent] {anchor_name} 周边搜索结果: {text_content}")
                try:
                    search_data = json.loads(text_content)
                    poi_list = search_data.get("pois", [])
                except (json.JSONDecodeError, TypeError):
                    print(f"[酒店Agent] {anchor_name} 周边搜索结果解析失败")
                    continue

                for p in poi_list[:1]:
                    poi_id = p.get("id")
                    # typecode以10开头为住宿服务大类
                    if poi_id and poi_id not in hotel_pois and str(p.get("typecode", "")).startswith("10"):
                        hotel_pois[poi_id] = p


            print(f"[酒店Agent] 共收集到 {len(hotel_pois)} 个酒店")
            if not hotel_pois:
                print("[酒店Agent] 锚点周边未找到酒店")
                return {"parse_error": [ErrorResponse(message="锚点周边未找到酒店")]}

            hotel_ids = list(hotel_pois.keys())
            print(f"[酒店Agent] 获取 {len(hotel_ids)} 个酒店详情中...")
            hotel_details = []
            for hotel_id in hotel_ids:
                result = await detail_tool.ainvoke({"id": hotel_id})
                text = _extract_text(result)
                if text and not text.startswith("Error"):
                    try:
                        hotel_details.append(json.loads(text))
                    except json.JSONDecodeError:
                        return {"parse_error": [ErrorResponse(message="酒店详情数据解析失败")]}

            print(f"[酒店Agent] 解析到 {len(hotel_details)} 条酒店详情")
            if not hotel_details:
                print("[酒店Agent] 酒店详情数据解析失败")
                return {"parse_error": [ErrorResponse(message="酒店详情数据解析失败")]}

            # 保存原始数据供enrich节点使用
            return {
                "hotel_anchors": anchors,
                "hotels_raw": json.dumps(hotel_details, ensure_ascii=False)
            }

        # 酒店节点2：确定性解析酒店原始数据，直接映射为酒店模型
        def hotel_enrich_node(state: PlannerState):
            raw_data = state.get("hotels_raw", "")
            if not raw_data:
                return {"hotel_result": []}

            try:
                hotel_details = json.loads(raw_data)
            except json.JSONDecodeError:
                print("[酒店Agent] hotels_raw 解析失败")
                return {"parse_error": [ErrorResponse(message="酒店原始数据解析失败")]}

            def _haversine_km(lon1, lat1, lon2, lat2):
                r = 6371.0
                phi1, phi2 = math.radians(lat1), math.radians(lat2)
                dphi = math.radians(lat2 - lat1)
                dlambda = math.radians(lon2 - lon1)
                a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
                return 2 * r * math.asin(math.sqrt(a))

            # 锚点景点坐标，用于计算距离描述
            anchors = state.get("hotel_anchors", [])
            anchor_locs = [
                (a.name, a.location)
                for a in state.get("attractions_result", [])
                if a.name in anchors and a.location is not None
            ]

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
                        ((_haversine_km(location.longitude, location.latitude,
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

            print(f"[酒店Agent] 完成，共映射 {len(hotels)} 个酒店")
            return {"hotel_result": hotels}

        # 规划节点：汇总全部数据，LLM生成完整旅行计划及每日路线起终点
        async def plan_node(state: PlannerState):
            attractions = state.get("attractions_result", [])
            hotels = state.get("hotel_result", [])
            weather_list = state.get("weather_result", [])

            if not attractions or not hotels or not weather_list:
                print("[规划Agent] 上游数据未就绪(提前触发)，跳过本次执行")
                return {}
            # 确定性推算每日日期
            travel_days = state.get("travel_days") or 1
            try:
                start_dt = datetime.strptime(state["start_date"], "%Y-%m-%d")
                date_list = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(travel_days)]
            except (ValueError, KeyError):
                date_list = [state.get("start_date", "")]

            # 只给LLM精简信息(名称/类别/时长/价格)，坐标、地址、描述、图片等详情后续从state按名称回填
            attractions_brief = [
                {"name": a.name, "category": a.category, "visit_duration": a.visit_duration,
                 "ticket_price": a.ticket_price, "rating": a.rating}
                for a in attractions if a.location is not None
            ]
            hotels_brief = [
                {"name": h.name, "type": h.type, "rating": h.rating,
                 "distance": h.distance, "estimated_cost": h.estimated_cost,
                 "price_range": h.price_range}
                for h in hotels
            ]
            weather_brief = [w.model_dump() for w in weather_list]

            class DayRoute(BaseModel):
                start_name: str = Field(..., description="当日路线起点名称(酒店名或景点名)")
                end_name: str = Field(..., description="当日路线终点名称(景点名)")

            class DayPlanBrief(BaseModel):
                day_index: int = Field(..., description="第几天(从0开始)")
                description: str = Field(..., description="当日行程描述")
                transportation: str = Field(..., description="交通方式")
                accommodation: str = Field(..., description="住宿")
                hotel_name: str = Field(..., description="当日酒店名，从候选酒店中逐字选择")
                attraction_names: List[str] = Field(..., description="当日景点名，按游览顺序，从候选景点中逐字选择")
                meals: List[Meal] = Field(default=[], description="餐饮列表")

            class PlannerOutput(BaseModel):
                days: List[DayPlanBrief]
                day_routes: List[DayRoute]
                overall_suggestions: str
                budget: Optional[Budget] = None

            plan_prompt = f"""你是资深旅行规划师。请根据以下数据为游客制定一份完整的{state['city']}旅行计划。

    基本信息:
    - 城市: {state['city']}
    - 行程日期: {date_list} (共{travel_days}天)
    - 大交通方式: {state.get('transportation', '')}
    - 住宿偏好: {state.get('accommodation', '')}
    - 用户偏好: {state.get('preferences', [])}
    - 额外需求: {state.get('free_text_input', '') or '无'}

    候选景点数据(精简信息，景点坐标/地址/描述/图片/评分等详情已保存在系统中，无需输出，直接用名称引用):
    {json.dumps(attractions_brief, ensure_ascii=False)}

    候选酒店数据(精简信息，酒店坐标/地址等详情已保存在系统中，无需输出，直接用名称引用):
    {json.dumps(hotels_brief, ensure_ascii=False)}

    天气数据:
    {json.dumps(weather_brief, ensure_ascii=False)}

    错误信息：
    {json.dumps([e.model_dump() for e in state.get("parse_error", [])], ensure_ascii=False)}


    规划要求(必须严格遵守):
    1. days 必须恰好包含{travel_days}天，day_index 依次为0到{travel_days - 1}；每天日期由系统按 start_date 自动推算，无需输出 date 字段
    2. 从候选景点中挑选合适的分配到每一天，地理位置相近的景点安排在同一天(可参考景点类别)；每天的景点按游览路线的合理顺序排列
    3. attraction_names 必须逐字使用候选景点中的 name 字段，禁止编造、改名或补充详情；景点坐标/地址/描述/图片等详情由系统按名称自动补全
    4. 每天所有景点 visit_duration 之和不宜超过480分钟
    5. hotel_name 必须逐字使用候选酒店中的 name 字段，从候选酒店中选择1家最合适的填入每天；酒店坐标/地址等详情由系统按名称自动补全
    6. 每天安排三餐 meals，餐厅可合理推荐并估算费用
    7. 天气由系统按日期自动匹配，无需输出 weather_info
    8. budget: 汇总门票(ticket_price之和)、酒店(estimated_cost×住宿晚数)、餐饮、交通的估算总额
    9. description: 概括当日行程亮点与节奏
    10. overall_suggestions: 结合天气与偏好给出总体出行建议

    day_routes 要求(共{travel_days}条，与每天一一对应):
    1. start_name: 当日路线起点名称。第1天取所选酒店的名称；之后每天取前一天最后一个景点的名称
    2. end_name: 当日路线终点名称，取当日最后一个景点的名称
    3. 名称必须从候选景点/酒店数据中原样取值，禁止编造或改写
    """

            print("[规划Agent] LLM生成旅行计划框架中...")
            structured_llm = self.llm.with_structured_output(PlannerOutput)
            result = await structured_llm.ainvoke([
                {"role": "system",
                 "content": "你是资深旅行规划师，擅长制定路线合理、数据严谨的旅行计划，绝不编造景点、酒店或坐标。"},
                {"role": "user", "content": plan_prompt}
            ])
            # LLM 偶发返回空计划(days/routes 为空)，重试一次
            if not result.days or not result.day_routes:
                print("[规划Agent] 首次返回空计划，重试一次...")
                result = await structured_llm.ainvoke([
                    {"role": "system",
                     "content": "你是资深旅行规划师，擅长制定路线合理、数据严谨的旅行计划，绝不编造景点、酒店或坐标。注意：days 与 day_routes 必须非空且与旅行天数一致，禁止返回空列表。"},
                    {"role": "user", "content": plan_prompt}
                ])

            # 确定性重建完整计划：景点/酒店/天气/日期等具体信息全部从state按名称回填，LLM只提供计划框架
            attractions_by_name = {a.name: a for a in attractions if a.location is not None}
            hotels_by_name = {h.name: h for h in hotels}

            days = []
            for b in result.days:
                day_attractions = []
                for name in b.attraction_names:
                    src = attractions_by_name.get(name)
                    if src is None:
                        print(f"[规划Agent] 景点「{name}」不在候选数据中，已跳过")
                        continue
                    day_attractions.append(src)
                hotel = hotels_by_name.get(b.hotel_name)
                if hotel is None and b.hotel_name:
                    print(f"[规划Agent] 酒店「{b.hotel_name}」不在候选数据中，已置空")
                date = date_list[b.day_index] if 0 <= b.day_index < len(date_list) else date_list[0]
                days.append(DayPlan(
                    date=date,
                    day_index=b.day_index,
                    description=b.description,
                    transportation=b.transportation,
                    accommodation=b.accommodation,
                    hotel=hotel,
                    attractions=day_attractions,
                    meals=b.meals,
                ))

            day_route_locations = [[r.start_name, r.end_name] for r in result.day_routes]
            if not days or not day_route_locations:
                print("[规划Agent] 重试后仍为空计划，放弃本次生成")
                return {"parse_error": [ErrorResponse(message="行程计划生成失败，请重试")], "final_plan": None}

            # 确定性回填天气：每天都有天气条目（预报覆盖则用预报，未覆盖则占位空卡）
            weather_by_date = {w.date: w for w in weather_list}
            final_weather = [weather_by_date.get(d, WeatherInfo(date=d)) for d in date_list]

            plan = TripPlan(
                city=state["city"],
                start_date=state["start_date"],
                end_date=state["end_date"],
                days=days,
                weather_info=final_weather,
                overall_suggestions=result.overall_suggestions,
                budget=result.budget,
            )

            print(f"[规划Agent] 完成，共 {len(plan.days)} 天行程，"
                  f"{len(day_route_locations)} 条每日路线起终点，天气 {len(final_weather)} 天")

            return {
                    "final_plan": plan,
                    "day_route_locations": day_route_locations,
                }









        work_flow=StateGraph(PlannerState)

        work_flow.add_node("attraction_tool_node", attraction_tool_node)
        work_flow.add_node("attraction_enrich_node", attraction_enrich_node)
        work_flow.add_node("weather_tool_node", weather_tool_node)
        work_flow.add_node("hotel_tool_node", hotel_tool_node)
        work_flow.add_node("hotel_enrich_node", hotel_enrich_node)
        work_flow.add_node("plan_node", plan_node)

        work_flow.add_edge(START, "attraction_tool_node")
        work_flow.add_edge(START, "weather_tool_node")
        work_flow.add_edge("attraction_tool_node", "attraction_enrich_node")
        work_flow.add_edge("attraction_enrich_node", "hotel_tool_node")
        work_flow.add_edge("hotel_tool_node", "hotel_enrich_node")
        work_flow.add_edge("hotel_enrich_node", "plan_node")
        work_flow.add_edge("weather_tool_node", "plan_node")
        work_flow.add_edge("plan_node", END)


        graph=work_flow.compile()
        self.graph=graph


    async def ainvoke(self, state: PlannerState):
        if self.graph is None:
            self._build_planner_graph()

        return await self.graph.ainvoke(state)




def get_travel_plan_agent():
    global travel_plan_agent
    if travel_plan_agent is None:
        travel_plan_agent = travel_plan_agents()
    return travel_plan_agent

if __name__ == "__main__":
    state = {
        "city": "青岛",
        "start_date": "2026-8-18",
        "end_date": "2026-8-20",
        "travel_days": 3,
        "transportation": "自驾",
        "accommodation": "酒店",
        "preferences": ["风景","啤酒","崂山"],
        "free_text_input": "希望旅行氛围浪漫、轻松、惬意，慢节奏",
        "attractions_raw": "",
        "attractions_result": [],
        "meal_result": [],
        "weather_result": [],
         "hotel_anchors": [],
        "hotels_raw": "",
        "hotel_result": [],
        "route_result": None,
        "day_route_locations": [],
        "final_plan": None,
        "parse_error": [],
        "messages": []
    }

    travel_plan_agent =get_travel_plan_agent()

    result=asyncio.run(travel_plan_agent.ainvoke(state))
    print(f"result: {result}")
    print(f"result[attractions_result]: {result['attractions_result']}")
    print(f"result[weather_result]: {result['weather_result']}")
    print(f"result[hotel_anchors]: {result['hotel_anchors']}")
    print(f"result[hotel_result]: {result['hotel_result']}")
    print(f"result[day_route_locations]: {result['day_route_locations']}")
    print(f"result[final_plan]: {result['final_plan']}")
    print(f"result[parse_error]: {result['parse_error']}")
    print(f"[plan]:")
    print(f"天气信息: {result['final_plan'].weather_info}")
    print(f"预算: {result['final_plan'].budget}")
    print(f"总体建议: {result['final_plan'].overall_suggestions}")
    for day_plan in result['final_plan'].days:
        print(f"- 第{day_plan.day_index}天")
        print(f"  - 大概行程：{day_plan.description}")
        print(f"  - 交通方式：{day_plan.transportation}")
        print(f"  - 住宿：{day_plan.accommodation}")
        print(f"  - 推荐酒店：{day_plan.hotel}")
        print(f"  - 景点：{day_plan.attractions}")
        print(f"  - 餐饮：{day_plan.meals}")







