# 旅迹智绘（Travel-agents）Rules

基于 LangGraph 多智能体工作流的 AI 旅行规划系统：FastAPI 后端（`backend/app`）+ Vue 3/Vite 前端（`frontend`）。高德地图 MCP 提供真实 POI/天气数据，时间 MCP 与 12306 MCP 供对话助手查询实时信息，Milvus 存放知识库子块（稠密 + BM25 稀疏向量），PostgreSQL 存储用户/会话/消息/知识库元数据/父块与 LangGraph checkpointer。

品牌名是「旅迹智绘」，但前端内部的 `sketchbook` / `sb-*` 命名是刻意保留的，不要为统一品牌而批量改名。

## Tech Stack

- Backend: Python / FastAPI / LangGraph / LangChain / PostgreSQL（SQLAlchemy async + asyncpg）
- Checkpointer: `langgraph-checkpoint-postgres` + `psycopg`（AsyncPostgresSaver）
- Logging: structlog（彩色控制台 / 可选 JSON），只在 `main.py` 配置一次
- Observability: Prometheus（`prometheus_client`，根路径 `/metrics`）+ 进程内指标快照（管理端看板）
- RAG: Milvus 3.x（稠密 COSINE + BM25 稀疏向量 + jieba 分析器）+ 条件过滤 + RRF 融合 + DashScope `gte-rerank` Cross-Encoder 精排；父块存 PostgreSQL
- Cache: Redis 8.x（Docker Desktop 单容器，`redis://127.0.0.1:6379`），TTL 60s 缓存工具结果 / 会话历史 / 向量检索结果（对话回复不缓存）
- Data Source: 高德地图 MCP（SSE）、时间 MCP（stdio）、12306 MCP（stdio，`npx -y 12306-mcp`）、Milvus（Docker Desktop，`http://127.0.0.1:19530`）、Redis（Docker Desktop）
- Frontend: Vue 3 + TypeScript + Vite + Vue Router（`frontend/`）
- State: `src/store.ts` 轻量 `reactive` store（**不是 Pinia**）；会话与消息以服务端为准
- Export: 高德 JS API 2.0 / PDF / PNG

## 目录结构

```
backend/app/
  main.py                 # 唯一入口：structlog、lifespan、路由挂载、全局异常
  core/                   # config / logging / database / deps / exceptions / metrics
  integrations/           # llm / milvus / mcp（外部服务适配）
  agent/                  # LangGraph 图、state、prompts、constants、nodes/
  modules/
    admin/                # 管理端：评测运行 / 报告历史 / 指标快照
    health/               # GET /api/v1/health
    sessions/             # models / repository / schemas / service / router
    chat/                 # agent 工厂 / workflow（意图路由图）/ history / SSE service
    knowledge/            # 解析 / chunking / markdown / retrieval / PG 父块 + Milvus 子块 / ingest_cli
    memory/               # 分层记忆：会话摘要 / 事实 / 任务状态 + 跨会话长期记忆
    trip/                 # 行程规划 models / repository / service / router / schemas
  evaluation/             # chat_eval / retrieval_eval + datasets + results(运行时生成)
  scripts/                # init_db.py / init_milvus.py
  data/
    corpus/               # 11 座城市 txt 语料（文件名即 city）
    md5_milvus.text       # Milvus 入库去重账本（运行时生成）
```

## Commands

除注明外，均在仓库根目录执行（Python 代码使用绝对导入 `backend.app.*`，CWD 必须是仓库根目录）。

- 初始化 PostgreSQL（建库 + 建表 + checkpointer）：`python -m backend.app.scripts.init_db`
- 启动 Milvus 容器（Windows Docker Desktop）：`docker start milvus-standalone`
- 初始化 Milvus 数据库 / 知识库集合 / 记忆集合 / BM25 函数 / 索引：`python -m backend.app.scripts.init_milvus`
- 启动 Redis 缓存容器（Windows Docker Desktop）：`docker start redis`
- 重建 Milvus 集合（会清空知识库与记忆向量）：`python -m backend.app.scripts.init_milvus --recreate`
- 启动后端（默认 8000 端口）：`python -m backend.app.main`
- 启动前端（5173 端口，需先 `npm install`）：`cd frontend && npm run dev`
- 类型检查 + 生产构建：`cd frontend && npm run build`
- 管理端语料入库（父子块 → PG + Milvus）：`python -m backend.app.modules.knowledge.ingest_cli`（`--force` 忽略账本，`--city 青岛` 只处理一城）
- 不经 HTTP，直接跑整张图调试（内置青岛 3 天示例）：`python -m backend.app.agent.graph`
- 验证 MCP 工具加载（高德 / 时间 / 12306）：`python -m backend.app.integrations.mcp`
- 对话评测（80 条意图用例，规则 + 大模型评分）：`python -m backend.app.evaluation.chat_eval`（`--limit / --category / --concurrency / --no-judge`）
- 向量检索评测（base 100 / hard 48 / all 148）：`python -m backend.app.evaluation.retrieval_eval`（需 Milvus；`--dataset base|hard|all`；`--hyde off|on|both` 做消融；`--rebuild` 强制重灌；`--no-rerank / --limit / --output`）
- 管理端页面（评测入口 + 指标看板）：`http://127.0.0.1:5173/admin`（需要 `KNOWLEDGE_ADMIN_TOKEN`）
- 需要热重载时：`uvicorn backend.app.main:app --reload --loop backend.app.core.runtime:proactor_loop_factory`（Windows 下必须显式指定，见“事件循环”一节）

本仓库没有自动化测试和 lint 脚本，不要假设存在 `pytest` / `npm test` 命令。

## Architecture

### 请求与生命周期

`backend/app/main.py` 是唯一入口：`setup_logging()` 只在这里调用一次；lifespan 依次执行 `validate_config()` → `init_database()`（连接 PG、`create_all`、初始化 checkpointer）→ `init_milvus()`（建集合/索引，失败不阻断，检索降级为空上下文）→ `init_cache()`（连接 Redis，失败不阻断，缓存降级为直通）→ `init_mcp_async()`（高德/时间/12306 独立初始化，单服务失败不阻断启动）。关闭时依次 `close_mcp()` → `close_cache()` → `close_milvus()` → `close_database()`。

所有业务路由挂载在 `/api/v1` 下：

| 模块 | 路径 | 说明 |
| --- | --- | --- |
| health | `GET /api/v1/health` | 数据库、checkpointer、Redis、Milvus（知识库/记忆集合）、各 MCP 服务状态 |
| admin | `/api/v1/admin/*` | 管理端评测运行 / 报告历史 / 指标快照（需 `X-Admin-Token`） |
| sessions | `/api/v1/sessions` | 创建 / ensure / 列表 / 详情 / 删除 |
| chat | `POST /api/v1/chat/stream` | 对话 SSE（token / done / error） |
| chat | `POST /api/v1/chat/resume`、`/api/v1/chat/cancel` | 断线按字符偏移续传 / 取消后台生成 |
| knowledge | `/api/v1/knowledge/*` | 用户上传 / 列表 / 删除；管理端上传 |
| memory | `/api/v1/memory/*` | 会话情景记忆 / 用户长期记忆的查看与删除 |
| trip | `/api/v1/trip/prefill` | 从对话会话提取快速开始表单预填（会话记忆 + 最近对话 + 快模型） |
| trip | `/api/v1/trip/plan`、`/api/v1/trip/plan/stream` | 一次性 / SSE 行程规划 |
| trip | `/api/v1/trip/plan/resume`、`/api/v1/trip/plan/cancel` | 断线按 record_id + seq 续传 / 取消后台执行 |

路由只做参数与依赖注入，业务逻辑在对应模块的 `service.py`；数据库操作在 `repository.py`；`core/deps.py` 提供 `DbSession` 与各 service 的 `Depends`。业务错误抛 `core/exceptions.py` 的 `AppError` 子类，由 `core/exception_handlers.py` 统一转成 `{"success": false, "code": ..., "message": ...}`。

### 配置

`backend/app/core/config.py` 的 `settings = Settings()` 是唯一配置实例，按模块分组：`settings.app` / `server` / `database` / `amap` / `llm` / `rag` / `planner` / `knowledge` / `chat` / `logging` / `mcp`。每组是独立的 `BaseSettings`，字段用 `validation_alias` 读取仓库根目录 `.env` 的历史变量名（如 `OPENAI_API_KEY`、`AMAP_API_KEY`）。新增配置要加在对应分组，不要恢复扁平字段。

### 数据库与会话

- 业务表：`users`、`chat_sessions`、`knowledge_documents`、`trip_plans`（每次规划一条，含 thread_id / 请求 / 结果 / 状态）、`session_memories`（每会话一条派生记忆，删除会话时级联删除）。
- 对话消息不落业务表：`chat_sessions` 只记录“有哪些会话”（user_id + session_id + 标题/城市），消息内容快照由 LangGraph checkpointer 按 `thread_id = session_id` 保存。
- LangGraph checkpoint 由 `AsyncPostgresSaver` 管理，表由 `setup()` 创建；不要把 checkpoint 表写进 `Base.metadata`。
- `user_id` = 浏览器匿名 ID（前端 `localStorage` 的 `lvji_client_id`），知识库归属按 `user_id` 计算。
- `session_id` = 服务端 `chat_sessions.id`；前端提交 `user_id + session_id`，后端 `SessionService.assert_session()` 校验归属。
- 每次行程规划使用独立 `thread_id = "{session_id|user_id}:{uuid}"`，避免同一线程的叠加 reducer 把多次规划状态混在一起。

### 图结构与门控语义

图定义在 `agent/graph.py`，状态在 `agent/state.py`：

```
START ─┬─ attraction_tool_node → attraction_enrich_node → hotel_tool_node → hotel_enrich_node ─┐
       ├─ weather_tool_node ─────────────────────────────────────────────────────────────────────┤
       ├─ transport_tool_node（填了出发城市时查 12306 去/返程车次，失败降级为空）─────────────────┤→ plan_gate_node
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
- `memory_context` 由 `TripService.prepare()` 从 `session_memories` + 长期记忆拼出，写入规划提示词作为表单字段的补充；表单字段优先，待确认信息必须标注“待确认”。

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

行程图只使用 amap 工具；对话工作流的推荐/规划节点通过 `modules/chat/workflow/tools.py` 把全部 MCP 工具（amap + time + rail）和知识库工具绑定到 LLM。工具缺失时行程节点返回 `parse_error` 而不抛异常。MCP 结果是文本块，统一用 `agent/nodes/utils._extract_text()` 解析；详情批量获取用 `fetch_details()`（信号量限流 + 重试）。

### 对话 SSE

`POST /api/v1/chat/stream` 由 `sse-starlette` 的 `EventSourceResponse` 输出，10 秒心跳。事件：

```
data: {"type":"token","delta":"..."}
data: {"type":"done","session_id":"..."}
data: {"type":"error","message":"..."}
```

生成在后台任务中执行，客户端断开只停止订阅、不中断生成；重连调用 `POST /api/v1/chat/resume`（`user_id` / `session_id` / `offset`，按已收 Unicode 码点数补发 token），`POST /api/v1/chat/cancel` 终止后台生成并保留已生成文本。

对话是 `modules/chat/workflow/` 下的 LangGraph 工作流，`thread_id = chat_sessions.id`：

```
START → memory_load（加载/压缩记忆）→ intent（正则寒暄 → 快模型结构化识别 → Command 路由）
          ├─ chitchat（子图：业务意图守卫 → 闲聊回复，轮次上限 3）
          ├─ recommend / plan（LLM.bind_tools → 工具节点 → 回到 LLM 循环）
          ├─ human（打印日志模拟转人工）
          ├─ fallback（反问用户）
          └─ dangerous → END（固定拒绝话术）
        上述工作流 → safety（大模型复核）→ memory_save（异步写记忆）→ END
```

- 父状态：`messages` / `city` / `user_id` / `session_id` / `previous_workflow` / `activated_workflow` / `pending_reply` / `chitchat_count` / `tool_round` / `memory_summary` / `memory_facts` / `memory_task_state` / `memory_context` / `turn_count`；闲聊子图声明 `chitchat_count` 与记忆字段，计数随父状态往返持久化。
- 推荐 / 规划不再使用 `create_agent`：`agent_llm_node` 流式调用 `llm.bind_tools(tools)`，`route_after_agent()` 有 `tool_calls` 时路由到 `agent_tools`，`agent_tools_node` 按工具名从 `tool_map`（缺失时回落 `get_mcp_tool`）执行并写回 `ToolMessage`，再按 `activated_workflow` 回到 `recommend` / `plan`；到达 `CHAT_MAX_TOOL_ROUNDS` 后改用未绑定工具的 `plain_llm` 强制作答，避免悬空工具调用。
- `_sanitize_history()` 会在每次调用模型前剔除未配对的 `AIMessage(tool_calls)` 与孤立 `ToolMessage`，防止客户端中断留下悬空工具调用导致上游 400。
- 意图识别用快模型 `with_structured_output(IntentResult)`，输出 `intent` / `reason` / `risk_level`；`risk_level >= 3` 或 `dangerous` 直接结束。
- `ChatService.prepare()` 校验 `user_id + session_id`，通过 `agent.aupdate_state()` 把用户消息写入 checkpointer；
- `stream()` 用 `agent.astream({"messages": []}, config, stream_mode="custom")`，节点通过 `get_stream_writer()` 推送 `{"type":"token","delta":...}`；意图识别与安全围栏的内部调用不会泄漏到前端。
- 子图（chitchat）的 custom 事件不会传回父图，因此闲聊回复先写入 `pending_reply`，由父图 `emit_reply` 节点统一推送。
- 历史读取：`modules/chat/history.py` 用 `checkpointer.aget_tuple()` 取 `channel_values.messages`；
- 删除会话：`SessionService.delete_session()` 先 `checkpointer.adelete_thread(session_id)`，再删 `chat_sessions` 行；
- 重新生成：`agent.aget_state()` 找到最后一条助手消息，用 `RemoveMessage` 删除后重新流式生成（`as_node="safety"`）。

不要再新增 `chat_messages` 表或手动搬运消息；checkpointer 是消息快照的唯一事实来源。

### 可观测性与管理端评测

`core/metrics.py` 是唯一指标入口，`prometheus_client` 为可选依赖：

- Prometheus 指标（根路径 `/metrics`，由 `METRICS_PATH` 覆盖）：LLM 请求延迟 / token、
  HTTP 请求、缓存命中 / 未命中 / 降级、精排结果（含 `circuit_breaker` 熔断计数）、
  LangGraph 节点耗时、MCP / 知识库工具耗时。
- LLM 指标通过 `LLM` 模型实例的 `callbacks=[LLMMetricsCallback]` 采集，
  `get_llm()` / `get_fast_llm()` 构建时自动挂载；`bind_tools` / `with_structured_output`
  也走同一实例。token 缺失时按字符估算，标签 `source=api|estimate`。
- 缓存指标在 `integrations/cache.cache_get_json()` 内统一打点；工具耗时在 `wrap_tool()`；
  精排指标在 `integrations/milvus._rerank()`。
- 行程图在 `stream_events()` 的节点结束回调里记录；对话图通过
  `modules/chat/agent.chat_config()` 挂 `NodeMetricsCallback`。
- `snapshot()` 维护与 Prometheus 同源的进程内聚合，管理端看板无需 Prometheus 也能读。
- `modules/admin` 通过独立 Python 子进程执行 `retrieval_eval` / `chat_eval`
  （`sys.executable -m ...`），避免在 API 进程内修改 Milvus 全局配置或阻塞事件循环；
  同类型评测同时只允许一个任务，日志保留尾部若干行。管理端接口统一要求
  `X-Admin-Token: $KNOWLEDGE_ADMIN_TOKEN`。

### 记忆系统（分层记忆）

`modules/memory/` 实现四层记忆，消息原文仍以 checkpointer 为唯一事实来源，摘要只是派生材料：

- **工作记忆**：最近 `MEMORY_WINDOW_ROUNDS` 轮（默认 5，按用户消息计数）完整原文；记忆关闭时回退到 `CHAT_MAX_HISTORY_MESSAGES`。
- **情景记忆**：`session_memories` 表（`session_id` 主键，外键级联删除），保存滚动摘要、已确认/待确认事实、外置任务状态与轮次；窗口外历史达到 `MEMORY_SUMMARY_TRIGGER_MESSAGES` 后，用快模型增量压缩，摘要按 `old + "\n---\n" + new` 滚动拼接，超长时才调用模型合并。
- **语义记忆**：用户偏好、事实、规则、历史任务结果，存 Milvus `user_memories` 集合（`MILVUS_MEMORY_COLLECTION`），稠密 + BM25 混合召回后按 RRF + 重要度排序。
- **程序记忆**：工具使用经验、成功工作流、失败教训，同样存 `user_memories`，`kind=workflow/lesson`；工具失败与知识库空结果由 `memory_save` 确定性回写。

写入时机：`memory_load`（轮首）负责加载与压缩；`memory_save`（轮末）只把任务挂到后台，异步完成四类触发——明确“记住…”指令、摘要确认事实升级、每 `MEMORY_EXTRACT_INTERVAL_ROUNDS` 轮批量抽取、知识检索失败回写“知识缺口”。所有记忆读写失败只记 warning，绝不阻断对话或推迟 `done` 事件。

冲突消解：新抽取的 confirmed 记忆（`preference/fact/rule/task_result`）写入前，按 `user_id + city + kind` 拉取已确认旧记忆交给快模型判定；确认被推翻时先插入新记忆、再 `adelete_memory_ids` 删除旧条目，并同步剔除 `session_memories.facts` 中被推翻的事实。摘要压缩用 `removed_facts` 做同样的替换。程序记忆（`workflow/lesson/gap`）保持只追加；判定失败按追加降级。

提示词只注入精简区块：会话摘要、已确认事实、待确认信息（明确标注“待确认”）、当前任务状态、长期记忆 top-k；检索只返回 `status=confirmed` 的长期记忆。

管理接口：`GET /api/v1/memory`、`DELETE /api/v1/memory/{memory_id}`、`DELETE /api/v1/memory`、`GET /api/v1/memory/session/{session_id}`（均需 `user_id`，会话接口还会校验归属）。

### RAG（Milvus 父子块 + 混合检索）

`agent/nodes/rag.py` 做 HyDE：快模型生成假设性答案文档 → `modules/knowledge/retrieval.py` 混合检索 → LLM 提取景点名。检索过滤语义与旧版一致：管理端内容按 `city`，用户内容按 `owner_id = user_id`，两者用 `or` 合并。

- **文档解析**：PDF 走 MinerU 云端 Precision API（`mineru-open-sdk` 的 `MinerU(token).extract(..., ocr=True)`，`MINERU_TOKEN` 必填），失败回退 pypdf；图片优先 Qwen-VL，失败时可用 MinerU OCR 兜底。文件会上传到 mineru.net。
- **Milvus 子块集合**（`integrations/milvus.py`，默认 `knowledge_chunks`）：字段 `id` / 元数据（`doc_id` / `parent_id` / `scope` / `owner_id` / `city` / `title` / `section` / `block_type` 等）/ 原始文本 `content` / 检索文本 `text` / 稠密向量 `dense` / 稀疏向量 `sparse`。`text` 开启 jieba 分析器并绑定服务端 **BM25 Function**，写入时只需给 `text` + `dense`；稠密 / 稀疏 / id / 过滤字段分别建索引。
- **父块表**：`knowledge_parent_chunks`（`modules/knowledge/models.py`），只存 PostgreSQL，不进入 Milvus。子块 metadata 的 `parent_id`（`{doc_id}:p{index}`）用于回查父块，父块正文加入提示词做增强。
- **切分**：`modules/knowledge/chunking.py` 先按 H1/H2 分父块，父块内按 H3 子标题、表格、路线、段落切子块；子块文本前缀「文档标题 + 章节」，表格逐行保留表头，路线行保持完整。MinerU 输出的 HTML `<table>` 会在切分前确定性转成 Markdown 管道表格（有 `<th>` 用 `<th>` 做表头，否则合成 `列1/列2…`；`rowspan`/`colspan` 用重复文本补齐），否则整张表会被当成一个普通段落。
- **写入**：`KnowledgeService.ingest()` 先删同 `doc_id` 的 Milvus 子块和 PG 父块/文档行，再加新数据（先删再加）。管理端语料 `doc_id = admin:{城市}`，用户文档使用随机 hex。
- **混合检索**：稠密 top-N + BM25 top-N → RRF 融合 → DashScope `gte-rerank` Cross-Encoder 精排；精排失败自动回退 RRF 并熔断 5 分钟。Milvus 不可用时返回空结果，规划继续但无知识库上下文。
- **对话工具**：`modules/chat/workflow/tools.py` 为推荐/规划节点挂载 `search_knowledge` 工具，按当前 `city + user_id` 绑定过滤条件；对话回答涉及攻略细节时优先调用。

**Milvus schema 创建后不可改**：修改字段、维度或度量必须 `init_milvus --recreate`（会清空知识库与记忆集合）后重新入库。Milvus 写入后会 flush，入库后无需重启后端。

### Redis 缓存

`integrations/cache.py` 是唯一的缓存层，key 统一带 `REDIS_KEY_PREFIX`（默认 `lvji`）+ 命名空间 + 参数 sha1：

- **工具结果**：`wrap_tool()` 在 `McpRegistry._load_one()` 里给每个 MCP 工具套一层缓存（行程规划与对话两条链路共用），知识库工具在 `_make_knowledge_tool()` 里用 `city:user_id` 作用域单独包装。
- **会话历史**：`ChatHistory.aget_messages()` 读缓存加速，所有写入 checkpointer 的路径（prepare / stream 结束 / 重新生成 / 删除会话）都会主动失效；checkpointer 仍是唯一事实来源。
- **向量检索结果**：`retrieve_knowledge()` 在调用 Milvus 前先查缓存，命中直接还原 `Document` 列表（含空结果）。
- **对话回复不缓存**：`agent_llm_node` 与 `chitchat_reply_node` 每次都会真实调用模型，保证多轮对话与重新生成拿到新回复。
- 默认 TTL 60s（`REDIS_TTL`）；Redis 连不上只记 warning，所有读写降级为直通，绝不中断业务。本地 `redis` 容器带 `--requirepass root`，`.env` 的 `REDIS_URL` 需要写 `redis://:root@127.0.0.1:6379/0`。

### 行程 SSE 进度

`TravelPlanAgent.stream_events()` 从 `graph.astream_events(version="v2")` 中**只保留 `NODE_LABELS`（`agent/constants.py`）里登记的节点**的 chain 事件。新增图节点若不加入 `NODE_LABELS`，前端将收不到该节点的任何进度事件。

事件协议：`meta` / `node_start` / `node_end` / `node_error` / `done`，每个事件带递增 `seq`。图在后台任务中执行（事件缓冲在进程内 `_RUNS`，TTL 15 分钟），客户端断开只停止订阅；重连调用 `POST /api/v1/trip/plan/resume`（`record_id` + `after=最后收到的 seq`）补发未收到的事件，`POST /api/v1/trip/plan/cancel` 终止后台执行。进程重启后 `resume` 用数据库中的记录状态合成 `done`。前端解析在 `frontend/src/services/api.ts`，TS 类型在 `frontend/src/types/index.ts`，与 `modules/trip/schemas.py` 的 Pydantic 模型一一对应。

### 前端

- Vue 3 + Vue Router，四个路由：`/`（首页）、`/quick-start`（手账翻书选城）、`/chat`（AI 对话）、`/result`（结果页）。
- 跨页计划状态是 `src/store.ts` 的轻量 `reactive` store，**不是 Pinia**。
- 会话与消息以服务端为准：`store.ts` 只持久化 `lvji_client_id`（`getUserId()`）与 `lvji_active_session`；`Chat.vue` 挂载时 `GET /sessions`，选择会话时 `GET /sessions/{id}` 拉取消息。
- `views/Result.vue` 用 `VITE_AMAP_WEB_JS_KEY` 加载高德 JS API 2.0，并包含地图标注、PDF/PNG 导出逻辑。
- 翻书交互在 `components/sketchbook/*`，城市配置在 `data/sketchbookCities.ts`。
- 布局与动效样式在 `styles/` 下，其中 `sketchbook.css` 是翻书相关的核心样式。

### 配置与环境变量

- 后端读仓库根目录 `.env`（pydantic-settings，`core/config.py`）：`POSTGRES_*` / `OPENAI_*` / `EMBEDDING_MODEL_NAME` / `AMAP_API_KEY` / `HOST` / `PORT` / `CORS_ORIGINS` / `LOG_LEVEL` / `MCP_*` / `MILVUS_URI` / `MILVUS_DB_NAME` / `MILVUS_COLLECTION` / `MILVUS_MEMORY_COLLECTION` / `MILVUS_DENSE_DIM` / `MILVUS_RERANK_*` / `MINERU_*` / `KNOWLEDGE_MARKDOWN_NORMALIZE` / `MEMORY_*` / `REDIS_ENABLED` / `REDIS_URL` / `REDIS_TTL` / `REDIS_KEY_PREFIX` / `REDIS_TIMEOUT` 等。
- `settings.milvus` 是独立配置组（`Milvus`）；默认 `http://127.0.0.1:19530`、知识库 `knowledge_chunks`、长期记忆 `user_memories`、稠密 1024 维 COSINE、BM25 稀疏、`gte-rerank-v2`。项目只使用 Milvus，没有其他向量库后端。
- `settings.memory` 是独立配置组（`Memory`）：`MEMORY_ENABLED` / `MEMORY_WINDOW_ROUNDS` / `MEMORY_SUMMARY_*` / `MEMORY_EXTRACT_INTERVAL_ROUNDS` / `MEMORY_LONG_TERM_*` / `MEMORY_CONTEXT_MAX_CHARS` / `MEMORY_WRITEBACK_KNOWLEDGE_GAP`。
- `settings.metrics`（`Metrics`）：`METRICS_ENABLED` / `METRICS_PATH`。
- `settings.evaluation`（`Evaluation`）：`EVAL_HYDE_CONCURRENCY`、`EVAL_PRICE_EMBEDDING_PER_1K` / `EVAL_PRICE_RERANK_PER_1K` / `EVAL_PRICE_LLM_INPUT_PER_1K` / `EVAL_PRICE_LLM_OUTPUT_PER_1K`（成本估算单价，默认 0 只展示调用量）、`EVAL_ADMIN_RUN_TTL_SECONDS` / `EVAL_ADMIN_LOG_LINES`。
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
- 对话工作流节点只能通过 `get_stream_writer()` 推送面向用户的 `{"type":"token"}`；`stream_mode` 固定为 `custom`。
- 推荐 / 规划只能用 `llm.bind_tools()` + `agent_tools_node` 的工具循环，不要恢复 `create_agent`；工具节点必须按工具名取用，并对每个 `tool_call` 都回写 `ToolMessage`（失败也要回写错误文本）。
- 工具缓存统一走 `integrations/cache.wrap_tool()`，不要在业务代码里手写 Redis 读写；缓存 TTL 保持 60s，Redis 故障时降级为直通。
- 新增对话状态字段必须同步加到 `ChatState` 与 `initial_chat_state()`；闲聊子图新增字段同步加到 `ChitchatState`。
- 新增业务接口放在 `modules/<module>/router.py`，挂载时统一加 `/api/v1` 前缀，并用 `Depends` 注入 service 与 DB session。
- 业务错误抛 `AppError` 子类，不要在各层重复拼 `HTTPException` 响应。
- 知识库入库必须走 `KnowledgeService`：父块写 `knowledge_parent_chunks`，子块写 Milvus；**父块不要写入 Milvus**。
- 写入同一 `doc_id` 前必须先删旧数据（Milvus 子块 + PG 父块/文档行），保证「先删再加」幂等。
- Milvus 子块必须带 `parent_id`，查询侧必须按 `parent_id` 回查 PostgreSQL 父块再拼提示词。
- Milvus 集合 schema / 维度 / 度量创建后不可改；需要改时用 `init_milvus --recreate` 后重新入库，不要临时改集合配置。
- 检索过滤必须下推：管理端 `scope=admin + city`，用户内容 `scope=user + owner_id`。
- Cross-Encoder 精排失败要回退 RRF，不要让检索整体失败。
- 知识库检索只走 Milvus；Milvus 故障时返回空上下文，不要重新引入其他向量库后端。
- 记忆摘要只是提示词材料，checkpointer 里的消息原文才是唯一事实来源；滚动摘要必须拼接旧摘要，不确定信息标注“待确认”。
- 长期记忆只能写入 `MILVUS_MEMORY_COLLECTION`（默认 `user_memories`），不要混入 `knowledge_chunks`。
- 记忆读写失败必须降级为无记忆继续对话；`memory_save` 必须异步，不得推迟 SSE `done` 事件。
- 新增记忆状态字段必须同步加到 `ChatState`、`initial_chat_state()`；闲聊子图需要的字段同步加到 `ChitchatState`。
- 保持防幻觉契约：LLM 只输出框架与名称，详情由系统按名称确定性回填。
- 保持 Vite 代理使用 `127.0.0.1` 而非 `localhost`，否则 Node 可能解析到 IPv6 `::1` 导致连不上后端。
- 前端超时保持 10 分钟（axios/fetch 与 Vite 代理），Agent 单次运行可能长达约 5 分钟。
- 新城市的语料放在 `backend/app/data/corpus/<城市名>.txt`，文件名即 metadata 中的 `city`。
- 管理端接口放在 `modules/admin/router.py`，统一 `/api/v1/admin` 前缀，并校验 `X-Admin-Token`。
- 新增指标统一走 `core/metrics.py` 的 `observe_*` / `snapshot()`，不要在业务代码里直接 import `prometheus_client`。
- 管理端评测必须通过独立子进程复用 `retrieval_eval` / `chat_eval` CLI，不要在 API 进程内修改 `settings.milvus.collection` / `db_name`。

## Never Do

- 不要让 LLM 直接生成地址、坐标、图片等易幻觉字段。
- 不要在节点里返回整个 state。
- 不要恢复 `backend.app.api.main` / `backend.app.services.*` / `backend.app.nodes.*` 旧路径；入口是 `backend.app.main`。
- 不要用 `python -m backend.app.main` 配合 `--reload`（入口不支持），需要热重载时用 `uvicorn backend.app.main:app --reload --loop backend.app.core.runtime:proactor_loop_factory`。
- 不要假设存在自动化测试或 lint 脚本（无 `pytest` / `npm test`）。
- 不要为统一品牌而批量重命名 `sketchbook` / `sb-*`。
- 不要用 Pinia 替换 `src/store.ts` 的轻量 store。
- 不要在 API 进程内直接跑检索评测（会切换全局 Milvus 配置并影响生产检索）。
- 不要绕过 `X-Admin-Token` 暴露 `/api/v1/admin/*` 管理端接口。
- 不要把 Vite 代理改成 `localhost`。
- 不要修改 Milvus 集合创建后的 schema（字段 / 维度 / 度量不可改，需 `init_milvus --recreate` 后重新入库）。
- 不要把父块写进 Milvus，也不要把子块正文只存 Milvus 而不留 `parent_id`。
- 不要用 `upsert` 代替「先删再加」；Milvus 删除必须按 `doc_id + owner_id + scope` 精确定位。
- 不要在 Cross-Encoder 失败时吞掉检索结果；必须回退 RRF 融合。
- 不要重新引入 Chroma 或其他第二套向量库（已按用户要求彻底移除）。
- 不要用会话摘要覆盖或删除 checkpointer 中的消息原文。
- 不要把长期记忆写进知识库集合，也不要在轮末同步执行记忆抽取拖慢回复。
- 不要把“待确认”的长期记忆以已确认事实的口吻注入提示词。
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
- 对话 → 快速开始预填：`backend/app/modules/trip/prefill.py`、`backend/app/modules/trip/service.py`
- 防幻觉回填：`backend/app/agent/nodes/plan.py`、`attraction.py`、`hotel.py`
- 评估规则：`backend/app/agent/nodes/evaluation.py`
- 会话 / 对话：`backend/app/modules/sessions/`、`backend/app/modules/chat/`
- 对话工作流（意图路由 / 闲聊子图 / 安全围栏）：`backend/app/modules/chat/workflow/`
- 分层记忆（摘要压缩 / 事实抽取 / 长期记忆）：`backend/app/modules/memory/`
- 长期记忆向量层：`backend/app/integrations/memory_milvus.py`
- 对话与检索评测：`backend/app/evaluation/chat_eval.py`、`retrieval_eval.py`、`datasets/`（`retrieval_eval_hard.jsonl` 为难负例 / 长文档 / 模糊 query）
- 可观测性指标：`backend/app/core/metrics.py`
- 管理端评测 / 报告 / 指标：`backend/app/modules/admin/`
- 管理端看板：`frontend/src/views/Admin.vue`、`frontend/src/components/admin/`、`frontend/src/styles/admin.css`
- 知识库与 RAG 入库：`backend/app/modules/knowledge/`、`backend/app/integrations/milvus.py`
- 父子块切分：`backend/app/modules/knowledge/chunking.py`
- 混合检索与父块回填：`backend/app/modules/knowledge/retrieval.py`
- Markdown 排版优化：`backend/app/modules/knowledge/markdown.py`
- MinerU / VLM / PDF 抽取：`backend/app/modules/knowledge/extractors.py`
- Milvus 初始化 CLI：`backend/app/scripts/init_milvus.py`
- Redis 缓存（工具结果 / 会话历史 / 检索结果）：`backend/app/integrations/cache.py`
- MCP：`backend/app/integrations/mcp.py`
- 响应/事件模型：`backend/app/modules/trip/schemas.py`、`frontend/src/types/index.ts`、`frontend/src/services/api.ts`
