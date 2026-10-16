# 图节点 → 前端进度文案
NODE_LABELS = {
    "attraction_tool_node": "正在搜索景点...",
    "attraction_enrich_node": "正在整合景点数据...",
    "rag_info_node": "正在检索本地知识库...",
    "weather_tool_node": "正在查询天气...",
    "hotel_tool_node": "正在搜索推荐酒店...",
    "hotel_enrich_node": "正在整合酒店数据...",
    "plan_node": "正在生成行程计划...",
    "evaluation_node": "正在评估行程合理性...",
}

# 评估节点最多打回重规划的轮次（防止反思循环死锁）
MAX_EVAL_ROUNDS = 2

# 带重试策略的节点最大重试次数
NODE_RETRY_ATTEMPTS = 3

# 并发与重试
IO_CONCURRENCY = 3
DETAIL_FETCH_RETRIES = 2
DETAIL_RETRY_DELAY = 1.0  # 秒

# 搜索 / 酒店
POI_TOP_K = 1
HOTEL_SEARCH_RADIUS = "3000"
HOTEL_TYPECODE_PREFIX = "10"

# 行程约束
MAX_DAILY_MINUTES = 480

# RAG
RAG_TOP_K = 4
