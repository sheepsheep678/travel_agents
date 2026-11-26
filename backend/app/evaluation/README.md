# 评测说明

## 数据集

| key | 文件 | 内容 |
| --- | --- | --- |
| `base` | `datasets/retrieval_eval.jsonl` | 100 对基础 query/文档（冻结基线） |
| `hard` | `datasets/retrieval_eval_hard.jsonl` | 48 条：同城不同景点 12、跨城同名景点 12、长文档 12、模糊 query 12 |
| `all` | `base + hard` | 148 条合并评测 |

`hard` 数据集全部启用城市过滤（`filter: "city"`）；跨城同名条目带 `counterpart`
指向另一城市的同名文档，用于验证「不过滤时错误城市文档会不会压过目标」。
长文档带 `split: true`，入库时走 `chunk_parent_child` 切成多个子块，
指标按 `doc_id` 去重后取最佳名次。

## 对话评测（`chat_eval.py`）

- 数据集：`datasets/chat_eval.jsonl`，共 80 条：精准意图 30、模糊意图 30、危险意图 20；文本固定，不要改动。
- 运行：`python -m backend.app.evaluation.chat_eval`（可选 `--limit` / `--category` / `--concurrency` / `--no-judge`）。
- 流程：每条用例在独立 `thread_id` 中跑完整对话工作流，记录实际路由与回复；
  - 规则判定：精准/模糊看路由是否命中可接受意图；危险用例看是否明确拒绝。
  - 大模型评分：`JudgeResult(intent_ok, safety_ok, quality)`，质量分 0-100。
- 报告：`results/chat_eval_<时间>.json`（运行时生成，已 gitignore），内含 `dataset_sha256`，可用于确认测试文本未被改动。

评测时图使用 `tools=[]` + `MemorySaver`，不依赖 MCP / PostgreSQL。

## 向量检索评测（`retrieval_eval.py`）

- 运行：
  - `python -m backend.app.evaluation.retrieval_eval`（base，100 条）
  - `python -m backend.app.evaluation.retrieval_eval --dataset hard --hyde both`
  - `python -m backend.app.evaluation.retrieval_eval --dataset all --no-rerank --limit 20`
- 参数：`--dataset base|hard|all`、`--top-k`、`--limit`、`--no-rerank`、`--rebuild`、
  `--hyde off|on|both`、`--hyde-concurrency`、`--output`。
- 入库策略：默认在集合不存在、条数不足或数据集哈希变化时重建；显式 `--rebuild` 强制清空重灌。
- 隔离：默认写入 Milvus `default` 库，集合名按数据集区分：
  `retrieval_eval`（base）/ `retrieval_eval_hard`（hard）/ `retrieval_eval_all`（all）。
  可用 `RETRIEVAL_EVAL_DB` 与 `RETRIEVAL_EVAL_*_COLLECTION` 覆盖，不会动生产 `knowledge_chunks`。
- 指标：每条 query 计算 Recall@1 / Recall@5 / MRR@10 / nDCG@10，并汇总
  P50 / P95 延迟、按数据类型（同城负例、跨城同名、长文档、模糊 query）分组指标。
- 成本：报告 `usage` 记录 query embedding token 估算、精排文档数、HyDE 调用与 token；
  `estimated_cost_cny` 按 `EVAL_PRICE_*` 单价估算，单价默认为 0，只展示调用量。
- HyDE 消融：`--hyde both` 会同时跑「原问句」与「HyDE 假设答案」，输出 `ablation` 表。
- 跨城过滤校验：hard / all 会自动跑一次「不过滤」诊断，报告
  `city_filter_check.wrong_city_rate`，用于说明城市过滤的价值。

## 管理端评测入口

后端 `modules/admin` 提供（均需 `X-Admin-Token: $KNOWLEDGE_ADMIN_TOKEN`）：

- `GET /api/v1/admin/datasets`：数据集概览与样例。
- `POST /api/v1/admin/eval/runs`：启动评测（子进程执行 CLI，立即返回 `run_id`）。
- `GET /api/v1/admin/eval/runs/{id}`：轮询状态与日志尾部。
- `POST /api/v1/admin/eval/runs/{id}/cancel`：取消评测。
- `GET /api/v1/admin/eval/reports` / `GET /api/v1/admin/eval/reports/{name}`：历史报告。
- `GET /api/v1/admin/metrics`：进程内指标快照。

前端 `/admin` 页面提供评测表单、运行日志、HyDE 消融表、逐条明细、历史报告与指标看板。
Prometheus 抓取端点为根路径 `/metrics`（`METRICS_PATH` 可改）。
