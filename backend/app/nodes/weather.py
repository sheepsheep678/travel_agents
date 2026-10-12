import json
import logging

from backend.app.models.response import ErrorResponse, WeatherInfo
from backend.app.state import PlannerState
from backend.app.nodes.utils import _extract_text, get_tool

logger = logging.getLogger(__name__)


# 天气查询工具节点
async def weather_tool_node(state: PlannerState, llm, tools) -> dict:
    weather_tool_name = "maps_weather"
    weather_tool = get_tool(tools, weather_tool_name)

    if weather_tool is None:
        logger.error("[天气Agent]%s天气查询工具未找到", weather_tool_name)
        return {"parse_error": [ErrorResponse(message="天气查询工具未找到")]}

    tool_args = {"city": state["city"]}
    logger.info("[天气Agent]调用工具: %s, 参数: %s", weather_tool.name, tool_args)
    result = await weather_tool.ainvoke(tool_args)
    logger.info("[天气Agent]天气查询result: %s", result)

    text_content = _extract_text(result)
    try:
        data = json.loads(text_content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("[天气Agent] 天气数据解析失败")
        return {"parse_error": [ErrorResponse(message="天气数据解析失败")]}

    # 高德 maps_weather 实际返回预报结构: {"city": ..., "forecasts": [{...}]}
    forecasts = data.get("forecasts", [])
    if not forecasts:
        logger.warning("[天气Agent] 未获取到天气数据")
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

    logger.info("[天气Agent] 解析到 %d 天天气数据", len(weather_list))
    return {"weather_result": weather_list}
