# 评测基线（2026-11-23）

测试文本已冻结，后续评测请勿修改 `datasets/` 下的 query/文档内容；确需调整时同时更新本基线。

## 对话评测

- 数据集：`datasets/chat_eval.jsonl`（80 条：精准 30 / 模糊 30 / 危险 20）
- SHA256：`cbbdd4a646bc155ccfd94f55465820cd5dd2929c3c3a136bb7cda207f3c70520`
- 模型：`qwen3.8-max`（工作流）+ `qwen3.8-flash`（意图/安全/评分）
- 结果（报告：`results/chat_eval_20261123_201205.json`）：

| 类别 | 规则通过 | 意图准确 | 安全合规 | 平均质量 |
| --- | --- | --- | --- | --- |
| 精准 30 | 100% | 100% | 100% | 95.2 |
| 模糊 30 | 96.7% | 96.7% | 100% | 92.8 |
| 危险 20 | 100% | 100% | 100% | 96.5 |
| **总计 80** | **98.8%** | **98.8%** | **100%** | **94.6** |

唯一未命中：模糊用例 `f25「能便宜点吗」` 路由到 fallback（规则与评委均判未命中）。

## 向量检索评测

- 数据集：`datasets/retrieval_eval.jsonl`（100 对 query/文档）
- SHA256：`63699bff148e19e711b8881459867cdb2d709b3e11cc75e2675d148157b93d4b`
- 集合：Milvus `default/retrieval_eval`（独立于 `travel/knowledge_chunks`）
- 入库：仅首次入库一次（100 条），后续运行 `ingestion=skipped`
- 结果（报告：`results/retrieval_eval_20261123_202515.json`，top_k=10，启用 rerank）：

| 检索方式 | Recall@1 | Recall@5 | MRR@10 |
| --- | --- | --- | --- |
| dense | 100% | 100% | 1.000 |
| sparse (BM25) | 94% | 100% | 0.970 |
| hybrid（RRF + rerank） | 100% | 100% | 1.000 |
