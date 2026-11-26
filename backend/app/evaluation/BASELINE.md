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

> 新版报告额外输出 nDCG@10、P50/P95 延迟、调用量与 HyDE 消融；
> 上述 Recall/MRR 基线来自 2026-11-23，重跑后请补充新列。

## 难负例评测集（待跑基线）

- 数据集：`datasets/retrieval_eval_hard.jsonl`（48 条：同城不同景点 12 / 跨城同名 12 /
  长文档 12 / 模糊 query 12）
- SHA256：`cc07358d4a17…`（以报告中的 `dataset_sha256` 为准）
- 集合：Milvus `default/retrieval_eval_hard`（base 为 `retrieval_eval`，互不覆盖）
- 首次运行：`python -m backend.app.evaluation.retrieval_eval --dataset hard --hyde both`
- 运行后请把 ablation 表、分类型指标与 `city_filter_check` 结果补到本节。
- 冒烟验证（2026-11-26，非完整基线）：集合已入库 48 文档 / 85 子块；14 条 query
  （含 2 条跨城同名）在 `--no-rerank --hyde off` 下 Recall@1/5=100%、nDCG@10=1.000、
  `wrong_city_rate=0`；1 条 query 的 `--hyde both` 正确输出 6 行消融表与
  HyDE token / 延迟用量。
