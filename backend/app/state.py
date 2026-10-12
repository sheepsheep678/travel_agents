from typing import TypedDict, List, Optional, Annotated, Any

from backend.app.models.response import Attraction, WeatherInfo, Hotel, ErrorResponse, TripPlan


def _add_list(existing: Optional[List[Any]], new: Optional[List[Any]]) -> List[Any]:
    existing = existing or []
    new = new or []
    return existing + new


def _add_set(existing: Optional[set], new: Optional[set]) -> set:
    return (existing or set()) | set(new or [])


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
    attraction_names: Annotated[set[str], _add_set]
    attractions_raw: str
    attractions_result: Annotated[List[Attraction], _add_list]
    search_round: int
    weather_result: Annotated[List[WeatherInfo], _add_list]
    hotel_anchors: List[str]
    hotels_raw: str
    hotel_result: Annotated[List[Hotel], _add_list]
    hotel_round: int
    final_plan: Optional[TripPlan]
    history_plan: Annotated[List[TripPlan], _add_list]
    eval_round: int
    eval_feedback: str
    eval_passed: bool
    parse_error: Annotated[list[ErrorResponse], _add_list]
    rag_result: str
    rag_attraction_names: Annotated[set[str], _add_set]


def initial_state() -> dict:
    """构建 PlannerState 的初始字典（各节点填充/消费前先置默认值）"""
    return {
        "city": "",
        "start_date": "",
        "end_date": "",
        "travel_days": 1,
        "transportation": "",
        "accommodation": "",
        "preferences": [],
        "free_text_input": "",
        "attraction_names": set(),
        "attractions_raw": "",
        "attractions_result": [],
        "search_round": 0,
        "weather_result": [],
        "hotel_anchors": [],
        "hotels_raw": "",
        "hotel_result": [],
        "hotel_round": 0,
        "final_plan": None,
        "history_plan": [],
        "eval_round": 0,
        "eval_feedback": "",
        "eval_passed": False,
        "parse_error": [],
        "rag_result": "",
        "rag_attraction_names": set(),
    }
