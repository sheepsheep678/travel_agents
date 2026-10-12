"""集中管理各节点的 prompt 模板（大模板用函数承载，便于插值 state 字段）"""

import json

from backend.app.constants import MAX_DAILY_MINUTES


# ============ 景点 enrich 节点 ============

ATTRACTION_ENRICH_SYSTEM = "你是景点信息整合专家，擅长将高德地图POI原始数据严格、准确地转换为结构化景点模型，绝不编造或篡改原始数据。"


def build_enrich_prompt(city: str, preferences: list, raw_data: str) -> str:
    return f"""你是高德地图POI数据整合专家。以下是通过高德地图POI详情接口获取的景点详情列表(JSON格式)，请将每条数据严格转换为结构化的景点模型。

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

城市: {city}
用户偏好: {preferences}

POI详情数据:
{raw_data}"""


# ============ RAG 检索节点 ============

RAG_HYDE_SYSTEM = "根据用户问题，先写一段可能的答案性段落，用于向量检索的查询文档（不要分析过程）。"


def build_rag_query(state) -> str:
    """HyDE风格检索查询：疑问句 + 全量state约束 + 语料词汇对齐"""
    city = state.get("city", "") or "目的地"
    travel_days = state.get("travel_days") or 1
    start_date = state.get("start_date", "")
    end_date = state.get("end_date", "")
    transportation = state.get("transportation", "")
    accommodation = state.get("accommodation", "")
    prefs = state.get("preferences", []) or []
    free_text = state.get("free_text_input", "")

    # 主问句：城市 + 天数，直接命中攻略类语料的语义模式
    query = f"{city}有哪些适合{travel_days}天行程的旅游攻略？"

    # 约束从句：以陈述形式注入全部行程参数，模拟文档信息密度
    conditions = []
    if start_date and end_date:
        conditions.append(f"游客计划于{start_date}至{end_date}期间出行")
    if transportation:
        conditions.append(f"采用{transportation}方式抵达")
    if accommodation:
        conditions.append(f"住宿选择{accommodation}")
    if prefs:
        conditions.append(f"重点关注{'、'.join(prefs)}相关的玩法")
    if conditions:
        query += "假设" + "，".join(conditions) + "，"

    # 分主题追问：词汇与攻略语料对齐，覆盖规划所需全部维度
    query += (
        f"那么{city}有哪些必玩景点和特色玩法？"
        f"当地有什么值得品尝的美食推荐？"
        f"每日游览路线如何安排最顺路？"
    )
    if free_text:
        query += f"如果游客特别希望{free_text}，行程上有什么针对性建议？"
    query += "出行又有哪些注意事项？"

    return query


def build_rag_hyde_user(query: str) -> str:
    return f"问题：{query}\n请直接写一段中等长度、客观、包含关键术语的段落。"


def build_rag_extract_system(city: str) -> str:
    return f"请根据本地知识库搜索到的结果，提取涉及到的{city}的景点名称，并用逗号分隔。如果结果为空，返回'未检索到相关内容。'。"


def build_rag_extract_user(context: str) -> str:
    return f"结果：{context}\n请提取结果中包含的景点信息，根据欢迎程度排序，格式例如：景点1，景点2，景点3。"


# ============ 规划节点 ============

PLAN_SYSTEM = "你是资深旅行规划师，擅长制定路线合理、数据严谨的旅行计划，绝不编造景点、酒店或坐标。"

PLAN_RETRY_MESSAGES = [
    "你是资深旅行规划师，擅长制定路线合理、数据严谨的旅行计划，绝不编造景点、酒店或坐标。注意：days 与 day_routes 必须非空且与旅行天数一致；每天 attraction_names 必须从候选景点中至少挑选1个，禁止返回空列表。",
    "上次输出不合法：每天 attraction_names 必须非空、逐字取自候选景点名称（候选不足时能选几个选几个，不能为空）；day_routes 与天数一致。请重新生成完整计划。",
]


def build_plan_prompt(state, date_list, attractions_brief, hotels_brief,
                      weather_brief, overlap_names, revision_block) -> str:
    travel_days = state.get("travel_days") or 1
    return f"""你是资深旅行规划师。请根据以下数据为游客制定一份完整的{state['city']}旅行计划。

基本信息:
- 城市: {state['city']}
- 行程日期: {date_list} (共{travel_days}天)
- 大交通方式: {state.get('transportation', '')}
- 住宿偏好: {state.get('accommodation', '')}
- 用户偏好: {state.get('preferences', [])}
- 额外需求: {state.get('free_text_input', '') or '无'}
- 双源重合景点(候选数据与知识库均推荐，选点时最高优先级): {sorted(overlap_names) if overlap_names else '无'}


候选景点数据(精简信息，景点坐标/地址/描述/图片/评分等详情已保存在系统中，无需输出，直接用名称引用):
{json.dumps(attractions_brief, ensure_ascii=False)}

候选酒店数据(精简信息，酒店坐标/地址等详情已保存在系统中，无需输出，直接用名称引用):
{json.dumps(hotels_brief, ensure_ascii=False)}

天气数据:
{json.dumps(weather_brief, ensure_ascii=False)}

本地知识库推荐攻略:
{state['rag_result']}

{revision_block}

错误信息：
{json.dumps([e.model_dump() for e in state.get("parse_error", [])], ensure_ascii=False)}


规划要求(必须严格遵守):
1. days 必须恰好包含{travel_days}天，day_index 依次为0到{travel_days - 1}；每天日期由系统按 start_date 自动推算，无需输出 date 字段
2. 从候选景点中挑选合适的分配到每一天，地理位置相近的景点安排在同一天(可参考景点类别)；每天的景点按游览路线的合理顺序排列
3. attraction_names 必须逐字使用候选景点中的 name 字段，禁止编造、改名或补充详情；景点坐标/地址/描述/图片等详情由系统按名称自动补全
4. 每天所有景点 visit_duration 之和不宜超过{MAX_DAILY_MINUTES}分钟
5. hotel_name 必须逐字使用候选酒店中的 name 字段，从候选酒店中选择1家最合适的填入每天；酒店坐标/地址等详情由系统按名称自动补全
6. 每天安排三餐 meals，餐厅可合理推荐并估算费用
7. 天气由系统按日期自动匹配，无需输出 weather_info
8. budget: 汇总门票(ticket_price之和)、酒店(estimated_cost×住宿晚数)、餐饮、交通的估算总额
9. description: 概括当日行程亮点与节奏，字数不要太少，确保信息丰富
10. overall_suggestions: 结合天气与偏好给出总体出行建议
11.本地知识库推荐攻略是精心查找的必玩攻略，大部分都是城市的特色，但是可以根据用户偏好自行取舍
12.不要安排过多的相似特征的景点，用户会审美疲劳；尽量多样化，确保行程丰富有趣
13.如处于修订模式，必须优先解决评估反馈中指出的全部问题


day_routes 要求(共{travel_days}条，与每天一一对应):
1. start_name: 当日路线起点名称。第1天取所选酒店的名称；之后每天取前一天最后一个景点的名称
2. end_name: 当日路线终点名称，取当日最后一个景点的名称
3. 名称必须从候选景点/酒店数据/本地知识库地点中原样取值，禁止编造或改写
"""


# ============ 评估节点 ============

EVAL_SYSTEM = "你是严格的旅行计划评审专家，只依据给定数据判断合理性，不编造问题也不放过硬伤。"


def build_eval_prompt(state, travel_days, plan_brief, hard_issues) -> str:
    return f"""请评估以下{state['city']}旅行计划的合理性，给出是否通过的结论与具体意见。

基本信息: 共{travel_days}天({state['start_date']}~{state['end_date']})，大交通: {state.get('transportation', '')}，
住宿偏好: {state.get('accommodation', '')}，用户偏好: {state.get('preferences', [])}，
额外需求: {state.get('free_text_input', '') or '无'}

天气数据:
{json.dumps([w.model_dump() for w in state.get("weather_result", [])], ensure_ascii=False)}

待评估计划:
{json.dumps(plan_brief, ensure_ascii=False)}

系统已检出的硬性问题(无需重复检查):
{json.dumps(hard_issues, ensure_ascii=False)}

评估维度:
1. 同一天景点地理上是否顺路，类别是否过度雷同(审美疲劳)
2. 节奏是否合理(单日景点数量、描述与景点是否匹配)
3. 天气适配(雨天是否仍安排大量户外景点)
4. 三餐安排与预算是否符合逻辑
5. 整体是否响应用户偏好与额外需求
注意: 景点/酒店/路线详情已保存在系统中，只评估计划编排本身，不要臆测不存在的数据。"""
