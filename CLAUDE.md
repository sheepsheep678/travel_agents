# 旅迹智绘（Travel-agents）Rules

基于 LangGraph 多智能体工作流的 AI 旅行规划系统：FastAPI 后端（`backend/app`）+ Vue 3/Vite 前端（`frontend`）。高德地图 MCP 提供真实 POI/天气数据，本地 Chroma 知识库存放 11 座城市的攻略语料。

品牌名是「旅迹智绘」，但前端内部的 `sketchbook` / `sb-*` 命名是刻意保留的，不要为统一品牌而批量改名。

## Tech Stack

- Backend: Python / FastAPI / LangGraph / LangChain
- RAG: Chroma 本地持久化（余弦距离，按 `city` metadata 过滤）+ HyDE
- Data Source: 高德地图 MCP（SSE 连接，4 个工具）
- Frontend: Vue 3 + TypeScript + Vite + Vue Router（`frontend/`）
- State: `src/store.ts` 轻量 `reactive` store（**不是 Pinia**）
- Export: 高德 JS API 2.0 / PDF / PNG

## Commands

除注明外，均在仓库根目录执行（Python 代码使用绝对导入 `backend.app.*`，CWD 必须是仓库根目录）。

- 启动后端（默认 8000 端口）：`python -m backend.app.api.main`
- 启动前端（5173 端口，需先 `npm install`）：`cd frontend && npm run dev`
- 类型检查 + 生产构建：`cd frontend && npm run build`
- 重建 RAG 向量库（执行后必须重启后端）：`python -m backend.app.api.rag_file_uploader`
- 不经 HTTP，直接跑整张图调试（内置青岛 3 天示例）：`python -m backend.app.services.travel_plan_agent`
- 验证高德 MCP 工具能否加载：`python -m backend.app.nodes.tools.amap_mcp_servers`
- 需要热重载时（入口本身不支持 `--reload`）：`uvicorn backend.app.api.main:app --reload`

本仓库没有自动化测试和 lint 脚本，不要假设存在 `pytest` / `npm test` 命令。

## Architecture

### 请求与生命周期

`backend/app/api/main.py` 是唯一入口：lifespan 先 `validate_config()` fail-fast，再 `init_amap_mcp_async()` 连接高德 MCP；`get_travel_plan_agent()`（`services/travel_plan_agent.py`）返回进程级单例，LangGraph 图在首次调用时才编译。

三个 API：`GET /api/health`（含 `mcp_ready`）、`POST /api/trip/plan`（一次性）、`POST /api/trip/plan/stream`（SSE）。请求体是 `models/request.py` 的 `TripRequest`，经 `initial_state()` 转成图状态。

### 图结构与门控语义

图定义在 `services/travel_plan_agent.py`，状态在 `state.py`：

```
START ─┬─ attraction_tool_node → attraction_enrich_node → hotel_tool_node → hotel_enrich_node ─┐
       ├─ weather_tool_node ─────────────────────────────────────────────────────────────────────┤→ plan_gate_node
       └─ rag_info_node ──(RAG 景点未覆盖)→ attraction_tool_node                                   │
                        └─(已覆盖)───────────────────────────────────────────────────────────────┘
plan_gate_node ──数据齐备──→ plan_node → evaluation_node ──通过/达上限──→ END
                    └─未齐备──→ END            └───────未通过────────────→ plan_node（最多 2 轮）
```

- `plan_gate_node` 是纯门控：`is_plan_ready()`（`nodes/gate.py`）要求景点、酒店、天气、RAG 均非空，且 `hotel_round >= search_round`。未齐备时路由到 END——这**只结束当前 superstep**，剩余并行分支完成后 LangGraph 会再次触发门控，不是真正终止。
- `rag_attraction_node_router` 判断 RAG 提取出的景点名是否都被工具搜索覆盖，缺失则跳回 `attraction_tool_node` 补搜。
- 评估不通过时，`evaluation_node` 把计划归档到 `history_plan`、写入 `eval_feedback`；`plan_node` 检测到二者后进入修订模式。轮次上限 `MAX_EVAL_ROUNDS` 定义在 `constants.py`。

### 状态与 reducer

`state.py` 的 `PlannerState` 是唯一状态契约：

- `attraction_names` / `rag_attraction_names` 用集合并集 reducer；`attractions_result`、`weather_result`、`hotel_result`、`history_plan`、`parse_error` 用列表累加 reducer。这使多轮补搜和修订可以叠加，而不是覆盖。
- 节点只返回**部分状态字典**，不要返回整个 state。
- 新增字段必须同时加到 `PlannerState` 和 `initial_state()`。

### 防幻觉契约（修改 prompt/模型时必须保留）

LLM 只输出计划**框架与名称**（`plan.py` 的 `PlannerOutput` / `DayPlanBrief`），所有具体详情由系统按名称从 state 确定性回填：

- 景点对象、酒店对象、天气、日期 → `plan.py` 按名称查找并回填；未知名称跳过/置空；空景点日按描述关键词或评分兜底填充。
- 景点详情（name/address/location/category/rating/photos/poi_id/ticket_price/visit_duration）→ `attraction.map_attraction_details()` 从原始 MCP 数据确定性映射，图片由 `photo` 字段直接解析；门票价缺失时填 0，不按知名度猜测。
- 景点 description → 仅把 name/type/alias/business_area/opentime2 交给快模型生成；失败、超时或空返回时使用确定性模板兜底。
- 酒店 → `hotel.map_hotel_details()` 直接映射原始数据，并用 Haversine 计算「距 X 约 Y km」。

不要让 LLM 直接生成地址、坐标、图片等易幻觉字段。

### 评估

`nodes/evaluation.py` 先做确定性强校验（天数一致、每天有景点、游览总时长 ≤ `MAX_DAILY_MINUTES`、有酒店候选时每天必须有酒店），命中任一即一票否决；无硬性问题时才以 LLM 的 `passed` 为准。

### MCP 工具

`nodes/tools/amap_mcp_servers.py` 通过 SSE 连接高德并缓存全局工具列表。节点用 `utils.get_tool(tools, name)` 按名称查找：

- `maps_text_search`（景点搜索）
- `maps_search_detail`（POI 详情）
- `maps_around_search`（景点周边酒店）
- `maps_weather`（天气）

工具缺失时节点返回 `parse_error` 而不抛异常。MCP 结果是文本块，统一用 `utils._extract_text()` 解析；详情批量获取用 `utils.fetch_details()`（信号量限流 + 重试）。

### RAG

`nodes/rag.py` 做 HyDE：LLM 生成假设性答案文档 → Chroma 检索 → LLM 提取景点名。`services/rag_component.py` 持有 Chroma 单例并按 `city` metadata 过滤。

**入库脚本和查询侧必须共用 `get_vector_store()`**，保证集合名、距离度量、嵌入模型完全一致。集合创建后配置不可改（默认余弦距离），切换需删除 `chroma_dir` 重新入库。`chroma_dir` / `md5_path` 默认推导到 `backend/app/api/`。

⚠️ **入库后必须重启后端**：Chroma 索引按持久化目录缓存在进程内，后端运行期间用另一进程入库会导致检索缺结果，或抛 `InternalError: Error finding id`。

### SSE 进度

`TravelPlanAgent.stream_events()` 从 `graph.astream_events(version="v2")` 中**只保留 `NODE_LABELS`（`constants.py`）里登记的节点**的 chain 事件。新增图节点若不加入 `NODE_LABELS`，前端将收不到该节点的任何进度事件。

事件协议：`node_start` / `node_end` / `node_error` / `done`。`main.py` 用队列桥接事件，每 10 秒发 `: ping` 心跳，客户端断开时取消图执行。前端解析在 `frontend/src/services/api.ts`，TS 类型在 `frontend/src/types/index.ts`，与 `backend/app/models/response.py` 的 Pydantic 模型一一对应。

### 前端

- Vue 3 + Vue Router，两个路由：`/`（Home，手账翻书选城）与 `/result`（结果页）。
- 跨页计划状态是 `src/store.ts` 的轻量 `reactive` store，**不是 Pinia**（README 中的 "Pinia" 表述过时）。
- `views/Result.vue` 用 `VITE_AMAP_WEB_JS_KEY` 加载高德 JS API 2.0，并包含地图标注、PDF/PNG 导出逻辑。
- 翻书交互在 `components/sketchbook/*`，城市配置在 `data/sketchbookCities.ts`。
- 布局与动效样式在 `styles/` 下，其中 `sketchbook.css` 是翻书相关的核心样式。

### 配置与环境变量

- 后端读仓库根目录 `.env`（pydantic-settings，`services/config.py`）：`OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL_ID` / `EMBEDDING_MODEL_NAME` / `AMAP_API_KEY` / `HOST` / `PORT` / `CORS_ORIGINS` / `LOG_LEVEL` 等。
- 前端读 `frontend/.env` 的 `VITE_AMAP_WEB_JS_KEY`。它和后端 `AMAP_API_KEY` 是两把不同的 Key（Web 端 JS API vs 服务端）。
- Vite 将 `/api` 代理到 `http://127.0.0.1:8000`（`frontend/vite.config.ts`）。
- 前端 axios/fetch 与 Vite 代理超时都设为 10 分钟：Agent 单次运行可能长达约 5 分钟。

## Must Follow

- 所有 Python 入口都在仓库根目录执行；绝对导入 `backend.app.*` 依赖此 CWD。
- 节点只返回**部分状态字典**，不要返回整个 state。
- 新增状态字段必须同时加到 `PlannerState` 和 `initial_state()`。
- 新增图节点必须加入 `constants.py` 的 `NODE_LABELS`，否则前端收不到该节点的 SSE 事件。
- 入库脚本和查询侧必须共用 `get_vector_store()`，保证集合名、距离度量、嵌入模型一致。
- 重新入库后必须重启后端（Chroma 进程内缓存）。
- 保持防幻觉契约：LLM 只输出框架与名称，详情由系统按名称确定性回填。
- 保持 Vite 代理使用 `127.0.0.1` 而非 `localhost`，否则 Node 可能解析到 IPv6 `::1` 导致连不上后端。
- 前端超时保持 10 分钟（axios/fetch 与 Vite 代理），Agent 单次运行可能长达约 5 分钟。
- 新城市的语料放在 `backend/app/api/data/<城市名>.txt`，文件名即 metadata 中的 `city`。

## Never Do

- 不要让 LLM 直接生成地址、坐标、图片等易幻觉字段。
- 不要在节点里返回整个 state。
- 不要用 `python -m backend.app.api.main` 配合 `--reload`（入口不支持），需要热重载时用 `uvicorn backend.app.api.main:app --reload`。
- 不要假设存在自动化测试或 lint 脚本（无 `pytest` / `npm test`）。
- 不要为统一品牌而批量重命名 `sketchbook` / `sb-*`。
- 不要用 Pinia 替换 `src/store.ts` 的轻量 store。
- 不要在后端运行期间用另一进程重新入库 Chroma（会缺结果或抛 `InternalError: Error finding id`）。
- 不要把 Vite 代理改成 `localhost`。
- 不要修改集合创建后的 Chroma 配置（维度/距离度量不可改，需删除 `chroma_dir` 重新入库）。
- 不要提交或顺手重新入库 `backend/app/api/chroma_db/` 的二进制文件：该目录受版本管理，重新入库会弄脏 `data_level0.bin`、`length.bin`、`chroma.sqlite3`。

## 仓库特定注意事项

- `.env`、`frontend/.env`、`node_modules`、`.venv`、`dist/` 已 gitignore；但 `backend/app/api/chroma_db/` 是提交进仓库的。
- 前端内部 `sketchbook` / `sb-*` 命名刻意保留，不要为统一品牌而批量改名。
- README 中关于 Pinia 的表述已过时，以 `src/store.ts` 的实际实现为准。

## More Rules

- 状态契约：`backend/app/state.py`
- 图结构与路由：`backend/app/services/travel_plan_agent.py`
- 节点标签与轮次上限：`backend/app/constants.py`
- 门控与就绪判断：`backend/app/nodes/gate.py`
- 防幻觉回填：`backend/app/nodes/plan.py`、`backend/app/nodes/attraction.py`、`backend/app/nodes/hotel.py`
- 评估规则：`backend/app/nodes/evaluation.py`
- RAG 入库：`backend/app/api/rag_file_uploader.py`、`backend/app/services/rag_component.py`
- 响应/事件模型：`backend/app/models/response.py`、`frontend/src/types/index.ts`、`frontend/src/services/api.ts`
