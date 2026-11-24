"""行程模块的请求 / 响应模型（与前端 types/index.ts 一一对应）。"""

from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator


# ============ 请求模型 ============


class TripRequest(BaseModel):
    """旅行规划请求。"""

    city: str = Field(..., description="目的地城市", examples=["北京"])
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD", examples=["2025-06-01"])
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD", examples=["2025-06-03"])
    travel_days: int = Field(..., description="旅行天数", ge=1, le=30, examples=[3])
    transportation: str = Field(..., description="交通方式", examples=["公共交通"])
    accommodation: str = Field(..., description="住宿偏好", examples=["经济型酒店"])
    preferences: List[str] = Field(default_factory=list, description="旅行偏好标签")
    free_text_input: Optional[str] = Field(default="", description="额外要求")
    user_id: Optional[str] = Field(
        default="",
        description="浏览器匿名用户 ID，用于召回该用户上传的知识库内容",
    )
    session_id: Optional[str] = Field(
        default="",
        description="会话 ID，存在时用于校验归属并作为 Agent checkpoint 的 thread_id",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "city": "北京",
                "start_date": "2025-06-01",
                "end_date": "2025-06-03",
                "travel_days": 3,
                "transportation": "公共交通",
                "accommodation": "经济型酒店",
                "preferences": ["历史文化", "美食"],
                "free_text_input": "希望多安排一些博物馆",
                "user_id": "browser-user-id",
                "session_id": "chat-session-id",
            }
        }
    }


class POISearchRequest(BaseModel):
    """POI 搜索请求（保留给后续地图接口扩展）。"""

    keywords: str = Field(..., description="搜索关键词", examples=["故宫"])
    city: str = Field(..., description="城市", examples=["北京"])
    citylimit: bool = Field(default=True, description="是否限制在城市范围内")


class RouteRequest(BaseModel):
    """路线规划请求（保留给后续地图接口扩展）。"""

    origin_address: str = Field(..., description="起点地址")
    destination_address: str = Field(..., description="终点地址")
    origin_city: Optional[str] = Field(default=None, description="起点城市")
    destination_city: Optional[str] = Field(default=None, description="终点城市")
    route_type: str = Field(default="walking", description="路线类型: walking/driving/transit")


# ============ 响应模型 ============


class Location(BaseModel):
    """地理位置。"""

    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")


class Attraction(BaseModel):
    """景点信息。"""

    name: str = Field(..., description="景点名称")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    visit_duration: int = Field(..., description="建议游览时间(分钟)")
    description: str = Field(..., description="景点描述")
    category: Optional[str] = Field(default="景点", description="景点类别")
    rating: Optional[float] = Field(default=None, description="评分")
    photos: Optional[List[str]] = Field(default_factory=list, description="景点图片 URL 列表")
    poi_id: Optional[str] = Field(default="", description="POI ID")
    image_url: Optional[str] = Field(default=None, description="图片 URL")
    ticket_price: int = Field(default=0, description="门票价格(元)")


class Meal(BaseModel):
    """餐饮信息。"""

    type: str = Field(..., description="餐饮类型: breakfast/lunch/dinner/snack")
    name: str = Field(..., description="餐饮名称")
    address: Optional[str] = Field(default=None, description="地址")
    location: Optional[Location] = Field(default=None, description="经纬度坐标")
    description: Optional[str] = Field(default=None, description="描述")
    estimated_cost: int = Field(default=0, description="预估费用(元)")


class Hotel(BaseModel):
    """酒店信息。"""

    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="酒店地址")
    location: Optional[Location] = Field(default=None, description="酒店位置")
    price_range: str = Field(default="", description="价格范围")
    rating: str = Field(default="", description="评分")
    distance: str = Field(default="", description="距离景点距离")
    type: str = Field(default="", description="酒店类型")
    estimated_cost: int = Field(default=0, description="预估费用(元/晚)")


class DayPlan(BaseModel):
    """单日行程。"""

    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_index: int = Field(..., description="第几天(从0开始)")
    description: str = Field(..., description="当日行程描述")
    transportation: str = Field(..., description="交通方式")
    accommodation: str = Field(..., description="住宿")
    hotel: Optional[Hotel] = Field(default=None, description="推荐酒店")
    attractions: List[Attraction] = Field(default_factory=list, description="景点列表")
    meals: List[Meal] = Field(default_factory=list, description="餐饮列表")


class WeatherInfo(BaseModel):
    """天气信息。"""

    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_weather: str = Field(default="", description="白天天气")
    night_weather: str = Field(default="", description="夜间天气")
    day_temp: Union[int, str] = Field(default=0, description="白天温度")
    night_temp: Union[int, str] = Field(default=0, description="夜间温度")
    wind_direction: str = Field(default="", description="风向")
    wind_power: str = Field(default="", description="风力")

    @field_validator("day_temp", "night_temp", mode="before")
    @classmethod
    def parse_temperature(cls, v):
        """解析温度，移除 °C / ℃ 等单位。"""
        if isinstance(v, str):
            v = v.replace("°C", "").replace("℃", "").replace("°", "").strip()
            try:
                return int(v)
            except ValueError:
                return 0
        return v


class Budget(BaseModel):
    """预算信息。"""

    total_attractions: int = Field(default=0, description="景点门票总费用")
    total_hotels: int = Field(default=0, description="酒店总费用")
    total_meals: int = Field(default=0, description="餐饮总费用")
    total_transportation: int = Field(default=0, description="交通总费用")
    total: int = Field(default=0, description="总费用")


class TripPlan(BaseModel):
    """旅行计划。"""

    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: List[DayPlan] = Field(..., description="每日行程")
    weather_info: List[WeatherInfo] = Field(default_factory=list, description="天气信息")
    overall_suggestions: str = Field(..., description="总体建议")
    budget: Optional[Budget] = Field(default=None, description="预算信息")


class TripPlanResponse(BaseModel):
    """旅行计划响应。"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[TripPlan] = Field(default=None, description="旅行计划数据")


class TrainSeatPrice(BaseModel):
    """12306 车次的坐席余票与票价。"""

    seat_name: str = Field(default="", description="坐席名称，如：二等座")
    short: str = Field(default="", description="坐席简称")
    num: Optional[Union[int, str]] = Field(default=None, description="余票数量或状态：有 / 无 / 数字")
    price: Optional[float] = Field(default=None, description="票价（元）")
    discount: Optional[int] = Field(default=None, description="折扣")


class TrainTicket(BaseModel):
    """一张 12306 车次票面。"""

    train_no: str = Field(default="", description="内部车次编号")
    train_code: str = Field(default="", description="展示车次，如：G1064")
    start_date: str = Field(default="", description="出发日期 YYYY-MM-DD")
    arrive_date: str = Field(default="", description="到达日期 YYYY-MM-DD")
    start_time: str = Field(default="", description="出发时间 HH:MM")
    arrive_time: str = Field(default="", description="到达时间 HH:MM")
    duration: str = Field(default="", description="历时 HH:MM")
    from_station: str = Field(default="", description="出发站")
    to_station: str = Field(default="", description="到达站")
    from_station_telecode: str = Field(default="", description="出发站电报码")
    to_station_telecode: str = Field(default="", description="到达站电报码")
    prices: List[TrainSeatPrice] = Field(default_factory=list, description="坐席票价与余票")
    flags: List[str] = Field(default_factory=list, description="复兴号 / 智能动车等标签")


class TrainSearchResponse(BaseModel):
    """12306 车次查询响应。"""

    success: bool = Field(default=True, description="是否成功")
    message: str = Field(default="", description="消息")
    from_city: str = Field(default="", description="出发城市")
    to_city: str = Field(default="", description="到达城市")
    date: str = Field(default="", description="查询日期")
    tickets: List[TrainTicket] = Field(default_factory=list, description="车次列表")


class POIInfo(BaseModel):
    """POI 信息。"""

    id: str = Field(..., description="POI ID")
    name: str = Field(..., description="名称")
    type: str = Field(..., description="类型")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    tel: Optional[str] = Field(default=None, description="电话")


class POISearchResponse(BaseModel):
    """POI 搜索响应。"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[POIInfo] = Field(default_factory=list, description="POI 列表")


class RouteInfo(BaseModel):
    """路线信息。"""

    distance: float = Field(..., description="距离(米)")
    duration: int = Field(..., description="时间(秒)")
    route_type: str = Field(..., description="路线类型")
    description: str = Field(..., description="路线描述")


class RouteResponse(BaseModel):
    """路线规划响应。"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[RouteInfo] = Field(default=None, description="路线信息")


class WeatherResponse(BaseModel):
    """天气查询响应。"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[WeatherInfo] = Field(default_factory=list, description="天气信息")


class ErrorResponse(BaseModel):
    """节点内部错误记录。"""

    success: bool = Field(default=False, description="是否成功")
    message: str = Field(..., description="错误消息")
    error_code: Optional[str] = Field(default=None, description="错误代码")
