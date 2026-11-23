# 评测说明

## 对话评测（`chat_eval.py`）

- 数据集：`datasets/chat_eval.jsonl`，共 80 条：精准意图 30、模糊意图 30、危险意图 20；文本固定，不要改动。
- 运行：`python -m backend.app.evaluation.chat_eval`（可选 `--limit` / `--category` / `--concurrency` / `--no-judge`）。
- 流程：每条用例在独立 `thread_id` 中跑完整对话工作流，记录实际路由与回复；
  - 规则判定：精准/模糊看路由是否命中可接受意图；危险用例看是否明确拒绝。
  - 大模型评分：`JudgeResult(intent_ok, safety_ok, quality)`，质量分 0-100。
- 报告：`results/chat_eval_<时间>.json`（运行时生成，已 gitignore），内含 `dataset_sha256`，可用于确认测试文本未被改动。

评测时图使用 `tools=[]` + `MemorySaver`，不依赖 MCP / PostgreSQL。

## 向量检索评测（`retrieval_eval.py`）

- 数据集：`datasets/retrieval_eval.jsonl`，共 100 对 query / 文档（10 城市 × 10 条），文本固定，不要改动。
- 运行：`python -m backend.app.evaluation.retrieval_eval`（需 Milvus；可选 `--no-rerank` / `--limit` / `--rebuild`）。
- 入库策略：默认只在首次（集合不存在或条数不足 100）时入库，之后每次执行只做检索评测；只有修改数据集或需要清空重来时加 `--rebuild`。
- 入库标记：`results/retrieval_eval_ingested.json` 记录 `dataset_sha256` 与条数；报告同样包含该哈希，两者不一致时会告警但仍只评测（不自动重灌）。
- 隔离：默认写入 Milvus `default` 库的 `retrieval_eval` 集合（可用 `RETRIEVAL_EVAL_DB` / `RETRIEVAL_EVAL_COLLECTION` 覆盖），不会动 `travel` 库的 `knowledge_chunks`。
- 指标：稠密、BM25 稀疏、混合检索各自的 Recall@1 / Recall@5 / MRR@10。
