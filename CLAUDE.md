# 旅迹智绘（Travel-agents）Rules

基于 LangGraph 多智能体工作流的 AI 旅行规划系统：FastAPI 后端（`backend/app`）+ Vue 3/Vite 前端（`frontend`）。高德地图 MCP 提供真实 POI/天气数据，时间 MCP 与 12306 MCP 供对话助手查询实时信息，Milvus 存放知识库子块（稠密 + BM25 稀疏向量），PostgreSQL 存储用户/会话/消息/知识库元数据/父块与 LangGraph checkpointer。

品牌名是「旅迹智绘」，但前端内部的 `sketchbook` / `sb-*` 命名是刻意保留的，不要为统一品牌而批量改名。

## Tech Stack

- Backend: Python / FastAPI / LangGraph / LangChain / PostgreSQL（SQLAlchemy async + asyncpg）
- Checkpointer: `langgraph-checkpoint-postgres` + `psycopg`（AsyncPostgresSaver）
- Logging: structlog（彩色控制台 / 可选 JSON），只在 `main.py` 配置一次
- RAG: Milvus 3.x（稠密 COSINE + BM25 稀疏向量 + jieba 分析器）+ 条件过滤 + RRF 融合 + DashScope `gte-rerank` Cross-Encoder 精排；父块存 PostgreSQL
- Data Source: 高德地图 MCP（SSE）、时间 MCP（stdio）、12306 MCP（stdio，`npx -y 12306-mcp`）、Milvus（Docker Desktop，`http://127.0.0.1:19530`）
- Frontend: Vue 3 + TypeScript + Vite + Vue Router（`frontend/`）
- State: `src/store.ts` 轻量 `reactive` store（**不是 Pinia**）；会话与消息以服务端为准
- Export: 高德 JS API 2.0 / PDF / PNG

## 目录结构

```
backend/app/
  main.py                 # 唯一入口：structlog、lifespan、路由挂载、全局异常
  core/                   # config / logging / database / deps / exceptions
  integrations/           # llm / milvus / mcp（外部服务适配）
  agent/                  # LangGraph 图、state、prompts、constants、nodes/
  modules/
    health/               # GET /api/v1/health
    sessions/             # models / repository / schemas / service / router
    chat/                 # agent / history(checkpointer) / SSE service
    knowledge/            # 解析 / chunking / markdown / retrieval / PG 父块 + Milvus 子块 / ingest_cli
    trip/                 # 行程规划 models / repository / service / router / schemas
  scripts/                # init_db.py / init_milvus.py
  data/
    corpus/               # 11 座城市 txt 语料（文件名即 city）
    md5_milvus.text       # Milvus 入库去重账本（运行时生成）
```

## Commands

除注明外，均在仓库根目录执行（Python 代码使用绝对导入 `backend.app.*`，CWD 必须是仓库根目录）。

- 初始化 PostgreSQL（建库 + 建表 + checkpointer）：`python -m backend.app.scripts.init_db`
- 启动 Milvus 容器（Windows Docker Desktop）：`docker start milvus-standalone`
- 初始化 Milvus 数据库 / 集合 / BM25 函数 / 索引：`python -m backend.app.scripts.init_milvus`
- 重建 Milvus 集合（会清空向量）：`python -m backend.app.scripts.init_milvus --recreate`
- 启动后端（默认 8000 端口）：`python -m backend.app.main`
- 启动前端（5173 端口，需先 `npm install`）：`cd frontend && npm run dev`
- 类型检查 + 生产构建：`cd frontend && npm run build`
- 管理端语料入库（父子块 → PG + Milvus）：`python -m backend.app.modules.knowledge.ingest_cli`（`--force` 忽略账本，`--city 青岛` 只处理一城）
- 不经 HTTP，直接跑整张图调试（内置青岛 3 天示例）：`python -m backend.app.agent.graph`
- 验证 MCP 工具加载（高德 / 时间 / 12306）：`python -m backend.app.integrations.mcp`
- 需要热重载时：`uvicorn backend.app.main:app --reload --loop backend.app.core.runtime:proactor_loop_factory`（Windows 下必须显式指定，见“事件循环”一节）

本仓库没有自动化测试和 lint 脚本，不要假设存在 `pytest` / `npm test` 命令。

## Architecture

### 请求与生命周期

`backend/app/main.py` 是唯一入口：`setup_logging()` 只在这里调用一次；lifespan 依次执行 `validate_config()` → `init_database()`（连接 PG、`create_all`、初始化 checkpointer）→ `init_milvus()`（建集合/索引，失败不阻断，检索降级为空上下文）→ `init_mcp_async()`（高德/时间/12306 独立初始化，单服务失败不阻断启动）。关闭时依次 `close_mcp()` → `close_milvus()` → `close_database()`。

所有业务路由挂载在 `/api/v1` 下：

| 模块 | 路径 | 说明 |
| --- | --- | --- |
| health | `GET /api/v1/health` | 数据库、checkpointer、Milvus、各 MCP 服务状态 |
| sessions | `/api/v1/sessions` | 创建 / ensure / 列表 / 详情 / 删除 |
| chat | `POST /api/v1/chat/stream` | 对话 SSE（token / done / error） |
| knowledge | `/api/v1/knowledge/*` | 用户上传 / 列表 / 删除；管理端上传 |
| trip | `/api/v1/trip/plan`、`/api/v1/trip/plan/stream` | 一次性 / SSE 行程规划 |

路由只做参数与依赖注入，业务逻辑在对应模块的 `service.py`；数据库操作在 `repository.py`；`core/deps.py` 提供 `DbSession` 与各 service 的 `Depends`。业务错误抛 `core/exceptions.py` 的 `AppError` 子类，由 `core/exception_handlers.py` 统一转成 `{"success": false, "code": ..., "message": ...}`。

### 配置

`backend/app/core/config.py` 的 `settings = Settings()` 是唯一配置实例，按模块分组：`settings.app` / `server` / `database` / `amap` / `llm` / `rag` / `planner` / `knowledge` / `chat` / `logging` / `mcp`。每组是独立的 `BaseSettings`，字段用 `validation_alias` 读取仓库根目录 `.env` 的历史变量名（如 `OPENAI_API_KEY`、`AMAP_API_KEY`）。新增配置要加在对应分组，不要恢复扁平字段。

### 数据库与会话

- 业务表：`users`、`chat_sessions`、`knowledge_documents`、`trip_plans`（每次规划一条，含 thread_id / 请求 / 结果 / 状态）。
- 对话消息不落业务表：`chat_sessions` 只记录“有哪些会话”（user_id + session_id + 标题/城市），消息内容快照由 LangGraph checkpointer 按 `thread_id = session_id` 保存。
- LangGraph checkpoint 由 `AsyncPostgresSaver` 管理，表由 `setup()` 创建；不要把 checkpoint 表写进 `Base.metadata`。
- `user_id` = 浏览器匿名 ID（前端 `localStorage` 的 `lvji_client_id`），知识库归属按 `user_id` 计算。
- `session_id` = 服务端 `chat_sessions.id`；前端提交 `user_id + session_id`，后端 `SessionService.assert_session()` 校验归属。
- 每次行程规划使用独立 `thread_id = "{session_id|user_id}:{uuid}"`，避免同一线程的叠加 reducer 把多次规划状态混在一起。

### 图结构与门控语义

图定义在 `agent/graph.py`，状态在 `agent/state.py`：

```
START ─┬─ attraction_tool_node → attraction_enrich_node → hotel_tool_node → hotel_enrich_node ─┐
       ├─ weather_tool_node ─────────────────────────────────────────────────────────────────────┤→ plan_gate_node
       └─ rag_info_node ──(RAG 景点未覆盖)→ attraction_tool_node                                   │
                        └─(已覆盖)───────────────────────────────────────────────────────────────┘
plan_gate_node ──数据齐备──→ plan_node → evaluation_node ──通过/达上限──→ END
                    └─未齐备──→ END            └───────未通过────────────→ plan_node（最多 2 轮）
```

- `plan_gate_node` 是纯门控：`is_plan_ready()`（`agent/nodes/gate.py`）要求景点、酒店、天气、RAG 均非空，且 `hotel_round >= search_round`。未齐备时路由到 END——这**只结束当前 superstep**，剩余并行分支完成后 LangGraph 会再次触发门控，不是真正终止。
- `rag_attraction_node_router` 判断 RAG 提取出的景点名是否都被工具搜索覆盖，缺失则跳回 `attraction_tool_node` 补搜。
- 评估不通过时，`evaluation_node` 把计划归档到 `history_plan`、写入 `eval_feedback`；`plan_node` 检测到二者后进入修订模式。轮次上限 `MAX_EVAL_ROUNDS` 定义在 `agent/constants.py`。

### 状态与 reducer

`agent/state.py` 的 `PlannerState` 是唯一状态契约：

- `attraction_names` / `rag_attraction_names` 用集合并集 reducer；`attractions_result`、`weather_result`、`hotel_result`、`history_plan`、`parse_error` 用列表累加 reducer。这使多轮补搜和修订可以叠加，而不是覆盖。
- 节点只返回**部分状态字典**，不要返回整个 state。
- 新增字段必须同时加到 `PlannerState` 和 `initial_state()`。
- `user_id` 用于 RAG 的用户私有文档过滤；`session_id` 用于日志与 checkpoint 线程标识。

### 防幻觉契约（修改 prompt/模型时必须保留）

LLM 只输出计划**框架与名称**（`agent/nodes/plan.py` 的 `PlannerOutput` / `DayPlanBrief`），所有具体详情由系统按名称从 state 确定性回填：

- 景点对象、酒店对象、天气、日期 → `plan.py` 按名称查找并回填；未知名称跳过/置空；空景点日按描述关键词或评分兜底填充。
- 景点详情（name/address/location/category/rating/photos/poi_id/ticket_price/visit_duration）→ `attraction.map_attraction_details()` 从原始 MCP 数据确定性映射，图片由 `photo` 字段直接解析；门票价缺失时填 0，不按知名度猜测。
- 景点 description → 仅把 name/type/alias/business_area/opentime2 交给快模型生成；失败、超时或空返回时使用确定性模板兜底。
- 酒店 → `hotel.map_hotel_details()` 直接映射原始数据，并用 Haversine 计算「距 X 约 Y km」。

不要让 LLM 直接生成地址、坐标、图片等易幻觉字段。

### 评估

`agent/nodes/evaluation.py` 先做确定性强校验（天数一致、每天有景点、游览总时长 ≤ `MAX_DAILY_MINUTES`、有酒店候选时每天必须有酒店），命中任一即一票否决；无硬性问题时才以 LLM 的 `passed` 为准。

### MCP 工具

`integrations/mcp.py` 用 `MultiServerMCPClient` 同时管理三个服务，按服务独立初始化并缓存工具；某服务失败只记录在 `errors`，不影响启动：

- `amap`（SSE）：`maps_text_search`（景点搜索）、`maps_search_detail`（POI 详情）、`maps_around_search`（周边酒店）、`maps_weather`（天气）；实际返回 15 个工具，节点按名称取用。
- `time`（stdio：`python -m mcp_server_time`）：`get_current_time`、`convert_time`。
- `rail`（stdio：`npx -y 12306-mcp`）：`get-current-date`、`get-station-code-of-citys`、`get-tickets`、`get-interline-tickets` 等 8 个工具。Windows 上经 `cmd.exe /c npx.cmd` 启动。

行程图只使用 amap 工具；对话助手通过 `modules/chat/agent.py` 的 `create_agent` 绑定 time + rail 工具。工具缺失时行程节点返回 `parse_error` 而不抛异常。MCP 结果是文本块，统一用 `agent/nodes/utils._extract_text()` 解析；详情批量获取用 `fetch_details()`（信号量限流 + 重试）。

### 对话 SSE

`POST /api/v1/chat/stream` 由 `sse-starlette` 的 `EventSourceResponse` 输出，10 秒心跳。事件：

```
data: {"type":"token","delta":"..."}
data: {"type":"done","session_id":"..."}
data: {"type":"error","message":"..."}
```

对话使用 LangChain `create_agent` + LangGraph checkpointer，`thread_id = chat_sessions.id`：

- `ChatService.prepare()` 校验 `user_id + session_id`，通过 `agent.aupdate_state()` 把用户消息写入 checkpointer；
- `stream()` 用 `agent.astream({"messages": []}, config, stream_mode="messages")` 运行 Agent，只把模型节点的文本 token 推给前端；
- 历史读取：`modules/chat/history.py` 用 `checkpointer.aget_tuple()` 取 `channel_values.messages`；
- 删除会话：`SessionService.delete_session()` 先 `checkpointer.adelete_thread(session_id)`，再删 `chat_sessions` 行；
- 重新生成：`agent.aget_state()` 找到最后一条助手消息，用 `RemoveMessage` 删除后重新流式生成。

不要再新增 `chat_messages` 表或手动搬运消息；checkpointer 是消息快照的唯一事实来源。

### RAG（Milvus 父子块 + 混合检索）

`agent/nodes/rag.py` 做 HyDE：快模型生成假设性答案文档 → `modules/knowledge/retrieval.py` 混合检索 → LLM 提取景点名。检索过滤语义与旧版一致：管理端内容按 `city`，用户内容按 `owner_id = user_id`，两者用 `or` 合并。

- **文档解析**：PDF 走 MinerU 云端 Precision API（`mineru-open-sdk` 的 `MinerU(token).extract(..., ocr=True)`，`MINERU_TOKEN` 必填），失败回退 pypdf；图片优先 Qwen-VL，失败时可用 MinerU OCR 兜底。文件会上传到 mineru.net。
- **Milvus 子块集合**（`integrations/milvus.py`，默认 `knowledge_chunks`）：字段 `id` / 元数据（`doc_id` / `parent_id` / `scope` / `owner_id` / `city` / `title` / `section` / `block_type` 等）/ 原始文本 `content` / 检索文本 `text` / 稠密向量 `dense` / 稀疏向量 `sparse`。`text` 开启 jieba 分析器并绑定服务端 **BM25 Function**，写入时只需给 `text` + `dense`；稠密 / 稀疏 / id / 过滤字段分别建索引。
- **父块表**：`knowledge_parent_chunks`（`modules/knowledge/models.py`），只存 PostgreSQL，不进入 Milvus。子块 metadata 的 `parent_id`（`{doc_id}:p{index}`）用于回查父块，父块正文加入提示词做增强。
- **切分**：`modules/knowledge/chunking.py` 先按 H1/H2 分父块，父块内按 H3 子标题、表格、路线、段落切子块；子块文本前缀「文档标题 + 章节」，表格逐行保留表头，路线行保持完整。
- **写入**：`KnowledgeService.ingest()` 先删同 `doc_id` 的 Milvus 子块和 PG 父块/文档行，再加新数据（先删再加）。管理端语料 `doc_id = admin:{城市}`，用户文档使用随机 hex。
- **混合检索**：稠密 top-N + BM25 top-N → RRF 融合 → DashScope `gte-rerank` Cross-Encoder 精排；精排失败自动回退 RRF 并熔断 5 分钟。Milvus 不可用时返回空结果，规划继续但无知识库上下文。
- **对话工具**：`modules/chat/agent.py` 的 create_agent 挂载 `search_knowledge` 工具，按当前 `city + user_id` 绑定过滤条件；对话回答涉及攻略细节时优先调用。

**Milvus schema 创建后不可改**：修改字段、维度或度量必须 `init_milvus --recreate`（会清空集合）后重新入库。Milvus 写入后会 flush，入库后无需重启后端。

### 行程 SSE 进度

`TravelPlanAgent.stream_events()` 从 `graph.astream_events(version="v2")` 中**只保留 `NODE_LABELS`（`agent/constants.py`）里登记的节点**的 chain 事件。新增图节点若不加入 `NODE_LABELS`，前端将收不到该节点的任何进度事件。

事件协议：`node_start` / `node_end` / `node_error` / `done`。`modules/trip/router.py` 用 `EventSourceResponse` 推流，客户端断开时取消图执行。前端解析在 `frontend/src/services/api.ts`，TS 类型在 `frontend/src/types/index.ts`，与 `modules/trip/schemas.py` 的 Pydantic 模型一一对应。

### 前端

- Vue 3 + Vue Router，四个路由：`/`（首页）、`/quick-start`（手账翻书选城）、`/chat`（AI 对话）、`/result`（结果页）。
- 跨页计划状态是 `src/store.ts` 的轻量 `reactive` store，**不是 Pinia**。
- 会话与消息以服务端为准：`store.ts` 只持久化 `lvji_client_id`（`getUserId()`）与 `lvji_active_session`；`Chat.vue` 挂载时 `GET /sessions`，选择会话时 `GET /sessions/{id}` 拉取消息。
- `views/Result.vue` 用 `VITE_AMAP_WEB_JS_KEY` 加载高德 JS API 2.0，并包含地图标注、PDF/PNG 导出逻辑。
- 翻书交互在 `components/sketchbook/*`，城市配置在 `data/sketchbookCities.ts`。
- 布局与动效样式在 `styles/` 下，其中 `sketchbook.css` 是翻书相关的核心样式。

### 配置与环境变量

- 后端读仓库根目录 `.env`（pydantic-settings，`core/config.py`）：`POSTGRES_*` / `OPENAI_*` / `EMBEDDING_MODEL_NAME` / `AMAP_API_KEY` / `HOST` / `PORT` / `CORS_ORIGINS` / `LOG_LEVEL` / `MCP_*` / `MILVUS_URI` / `MILVUS_DB_NAME` / `MILVUS_COLLECTION` / `MILVUS_DENSE_DIM` / `MILVUS_RERANK_*` / `MINERU_*` / `KNOWLEDGE_MARKDOWN_NORMALIZE` 等。
- `settings.milvus` 是独立配置组（`Milvus`）；默认 `http://127.0.0.1:19530`、`knowledge_chunks`、稠密 1024 维 COSINE、BM25 稀疏、`gte-rerank-v2`。项目只使用 Milvus，没有其他向量库后端。
- Milvus 采用 Windows Docker Desktop 单容器模式（`milvus-standalone`，内含 embedded etcd + 本地存储），端口 `19530` / `9091` / `2379`；集合由 `init_milvus` 或应用启动时创建。
- `settings.database.url` / `checkpoint_url` 由 `build_url()` 自动拼接：前者是 `postgresql+asyncpg://`（SQLAlchemy 元数据增删改查），后者是 `postgresql://`（psycopg checkpointer）。用户名/密码会做 URL 编码；默认值为 `127.0.0.1` / `5432` / `postgres` / `postgres` / `travel_agents`，部署时用 `POSTGRES_*` 覆盖。
- **Windows 事件循环**：MCP stdio 子进程需要 `ProactorEventLoop`，psycopg async 需要 `SelectorEventLoop`。应用主循环保持 Proactor，`core/database.py` 在独立 Selector 线程里运行 checkpointer 连接池，并把 `aget_tuple` / `aput` / `aput_writes` / `adelete_thread` 等 async 方法代理回来。uvicorn 的 `loop` 用 `backend.app.core.runtime:proactor_loop_factory`。
- 前端读 `frontend/.env` 的 `VITE_AMAP_WEB_JS_KEY`。它和后端 `AMAP_API_KEY` 是两把不同的 Key（Web 端 JS API vs 服务端）。
- Vite 将 `/api` 代理到 `http://127.0.0.1:8000`（`frontend/vite.config.ts`）。
- 前端 axios/fetch 与 Vite 代理超时都设为 10 分钟：Agent 单次运行可能长达约 5 分钟。

## Must Follow

- 所有 Python 入口都在仓库根目录执行；绝对导入 `backend.app.*` 依赖此 CWD。
- 节点只返回**部分状态字典**，不要返回整个 state。
- 新增状态字段必须同时加到 `PlannerState` 和 `initial_state()`。
- 新增图节点必须加入 `agent/constants.py` 的 `NODE_LABELS`，否则前端收不到该节点的 SSE 事件。
- 新增业务接口放在 `modules/<module>/router.py`，挂载时统一加 `/api/v1` 前缀，并用 `Depends` 注入 service 与 DB session。
- 业务错误抛 `AppError` 子类，不要在各层重复拼 `HTTPException` 响应。
- 知识库入库必须走 `KnowledgeService`：父块写 `knowledge_parent_chunks`，子块写 Milvus；**父块不要写入 Milvus**。
- 写入同一 `doc_id` 前必须先删旧数据（Milvus 子块 + PG 父块/文档行），保证「先删再加」幂等。
- Milvus 子块必须带 `parent_id`，查询侧必须按 `parent_id` 回查 PostgreSQL 父块再拼提示词。
- Milvus 集合 schema / 维度 / 度量创建后不可改；需要改时用 `init_milvus --recreate` 后重新入库，不要临时改集合配置。
- 检索过滤必须下推：管理端 `scope=admin + city`，用户内容 `scope=user + owner_id`。
- Cross-Encoder 精排失败要回退 RRF，不要让检索整体失败。
- 知识库检索只走 Milvus；Milvus 故障时返回空上下文，不要重新引入其他向量库后端。
- 保持防幻觉契约：LLM 只输出框架与名称，详情由系统按名称确定性回填。
- 保持 Vite 代理使用 `127.0.0.1` 而非 `localhost`，否则 Node 可能解析到 IPv6 `::1` 导致连不上后端。
- 前端超时保持 10 分钟（axios/fetch 与 Vite 代理），Agent 单次运行可能长达约 5 分钟。
- 新城市的语料放在 `backend/app/data/corpus/<城市名>.txt`，文件名即 metadata 中的 `city`。

## Never Do

- 不要让 LLM 直接生成地址、坐标、图片等易幻觉字段。
- 不要在节点里返回整个 state。
- 不要恢复 `backend.app.api.main` / `backend.app.services.*` / `backend.app.nodes.*` 旧路径；入口是 `backend.app.main`。
- 不要用 `python -m backend.app.main` 配合 `--reload`（入口不支持），需要热重载时用 `uvicorn backend.app.main:app --reload --loop backend.app.core.runtime:proactor_loop_factory`。
- 不要假设存在自动化测试或 lint 脚本（无 `pytest` / `npm test`）。
- 不要为统一品牌而批量重命名 `sketchbook` / `sb-*`。
- 不要用 Pinia 替换 `src/store.ts` 的轻量 store。
- 不要把 Vite 代理改成 `localhost`。
- 不要修改 Milvus 集合创建后的 schema（字段 / 维度 / 度量不可改，需 `init_milvus --recreate` 后重新入库）。
- 不要把父块写进 Milvus，也不要把子块正文只存 Milvus 而不留 `parent_id`。
- 不要用 `upsert` 代替「先删再加」；Milvus 删除必须按 `doc_id + owner_id + scope` 精确定位。
- 不要在 Cross-Encoder 失败时吞掉检索结果；必须回退 RRF 融合。
- 不要重新引入 Chroma 或其他第二套向量库（已按用户要求彻底移除）。
- 不要在 `/api/v1` 之外新增旧 `/api` 别名；前端 `services/api.ts` 已统一使用 `/api/v1`。

## 仓库特定注意事项

- `.env`、`frontend/.env`、`node_modules`、`.venv`、`dist/` 已 gitignore；知识库向量数据只存在 Milvus 容器中，不随仓库提交。
- 前端内部 `sketchbook` / `sb-*` 命名刻意保留，不要为统一品牌而批量改名。
- README 中关于 Pinia 的表述已过时，以 `src/store.ts` 的实际实现为准。
- 本机后端解释器是 conda `langchain` 环境（`D:\Development-Tools\anaconda3\envs\langchain\python.exe`）；仓库根目录 `.venv` 不可用。
- 12306 MCP 首次调用会下载 npm 包，可能耗时数十秒；`MCP_INIT_TIMEOUT` 默认 60s，可按需调大。
- Milvus 用 Windows Docker Desktop 的 `milvus-standalone` 单容器（`milvusdb/milvus:v3.0.6`，embedded etcd + 本地存储）。启动/停止容器前先确认用户是否允许；容器未启动时后端仍可启动，知识库检索降级为空上下文。
- `pymilvus` 需与 Milvus 大版本匹配（当前 `pymilvus 3.0.x` + Milvus 3.0.x）；升级镜像时同步升级客户端并 `init_milvus --recreate`。
- DashScope `gte-rerank` 可能因账户欠费/限流返回 `Access denied`；代码会回退 RRF 并熔断 5 分钟，不要把它当成检索故障。
- MinerU 使用 `mineru-open-sdk` 云端 Precision API（import 名仍是 `mineru`），必须配置 `MINERU_TOKEN`；不要同时安装本地 `mineru` 包，二者会争用同一个 `mineru` 命名空间。Precision 限制约 200MB / 200 页，文件会上传 mineru.net。

## More Rules

- 配置聚合根：`backend/app/core/config.py`
- 日志：`backend/app/core/logging.py`
- 数据库 / checkpointer：`backend/app/core/database.py`
- Windows 事件循环工厂：`backend/app/core/runtime.py`
- 依赖注入：`backend/app/core/deps.py`
- 异常：`backend/app/core/exceptions.py`、`backend/app/core/exception_handlers.py`
- 状态契约：`backend/app/agent/state.py`
- 图结构与路由：`backend/app/agent/graph.py`
- 节点标签与轮次上限：`backend/app/agent/constants.py`
- 门控与就绪判断：`backend/app/agent/nodes/gate.py`
- 防幻觉回填：`backend/app/agent/nodes/plan.py`、`attraction.py`、`hotel.py`
- 评估规则：`backend/app/agent/nodes/evaluation.py`
- 会话 / 对话：`backend/app/modules/sessions/`、`backend/app/modules/chat/`
- 知识库与 RAG 入库：`backend/app/modules/knowledge/`、`backend/app/integrations/milvus.py`
- 父子块切分：`backend/app/modules/knowledge/chunking.py`
- 混合检索与父块回填：`backend/app/modules/knowledge/retrieval.py`
- Markdown 排版优化：`backend/app/modules/knowledge/markdown.py`
- MinerU / VLM / PDF 抽取：`backend/app/modules/knowledge/extractors.py`
- Milvus 初始化 CLI：`backend/app/scripts/init_milvus.py`
- MCP：`backend/app/integrations/mcp.py`
- 响应/事件模型：`backend/app/modules/trip/schemas.py`、`frontend/src/types/index.ts`、`frontend/src/services/api.ts`
