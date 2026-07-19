# 真实 Embedding 检索校准

## 为什么 Mock 不能代替真实 Embedding

Mock 评估能稳定验证候选池、所有权过滤、距离过滤、去重、确定性排序和 `top_k` 行为，但它的距离与顺序是人工固定的。它不能反映 BGE 对同义表达、中英文混合、否定语义、长短文本和相似项目的真实平方 L2 分布，也不能判断 `EVIDENCE_MAX_DISTANCE=0.8` 与候选池倍数是否适合真实向量。

因此真实校准是独立的测量模式，不替代现有 81 个 Mock case，也不改变其期望。

## 完全隔离原则

真实校准仅在显式 `--real-embedding` 时运行，并且：

- 先设置 `SKIP_DOTENV=1`，不读取项目 `.env`；
- 设置 Hugging Face、Transformers 离线变量，并在运行期间阻断 socket 网络连接；
- 只从已缓存 snapshot 以 `local_files_only=True` 加载模型；
- 使用系统临时目录中的独立 SQLite、Chroma 和上传目录；
- collection 名称每次独立创建，不访问 `personal_knowledge_base`；
- 只使用虚构用户、文件记录和项目资料；
- 不导入或调用 DeepSeek、Tavily，不需要 API Key；
- 临时路径在执行前与生产默认数据库、Chroma、上传目录做交叉检查；
- 报告不记录缓存绝对路径、用户名、Secret、Prompt 或完整文档原文。

不允许使用真实用户资料，因为真实校准会生成可长期保留的指标和 case 报告；即使结果目录被 Git ignore，真实资料仍会扩大本地复制、误提交和调试输出的暴露面。

## 合成数据集

固定数据集位于 `backend/evals/retrieval_calibration_cases.json`，包含 35 个 query、48 个 chunk、2 个虚构用户，覆盖：

- FastAPI、React、ChromaDB、BGE、RAG、Pandas、Matplotlib、SQLite 等精确技术匹配；
- 向量数据库、检索增强生成、接口服务、前端界面、语义向量等同义表达；
- 中英文混合和中文无空格查询；
- 相似但无关的 FastAPI 项目；
- 未使用 Redis、未部署 Kubernetes、没有百万用户、没有 95% 准确率和没有 50% 性能提升等否定事实；
- 技术词堆砌、长短文本、可信文件名、完全重复和相邻近重复；
- project、resume、other/JD 分类；
- Chroma `user_id` 过滤和 SQLite 批量所有权复核。

数据集中的相关来源是事先固定的语义标注。真实运行失败时不得删除 case、修改期望或为固定样本硬编码排序。

## 本地模型缓存

生产配置模型标识为 `BAAI/bge-small-zh-v1.5`。当前实现使用 `sentence-transformers`，文档和 query 都设置 `normalize_embeddings=True`，向量维度为 512。校准不会下载模型；缓存缺失时状态为 `skipped_model_cache_missing`。

只读检查：

```powershell
cd D:\spir\NO1_agent\backend
.venv\Scripts\python.exe -m evals.run_retrieval_calibration --check-model-cache
```

输出只包含模型标识、缓存是否存在、是否允许离线加载、是否会下载和校准能否运行，不显示缓存路径或令牌。

真实校准：

```powershell
.venv\Scripts\python.exe -m evals.run_retrieval_calibration --real-embedding
```

不带 `--real-embedding` 时不会加载模型或运行校准。

## 指标定义

- Recall@K：正例 query 的相关来源在前 K 名中的覆盖比例。
- Precision@3：所有 query 前 3 个位置中相关来源所占比例；不足 3 个结果仍以 3 为分母。
- MRR：正例 query 首个相关来源排名的倒数均值。
- 空结果准确率：无相关来源 query 是否在阈值和分类过滤后返回空集。
- false reject rate：已标注相关的 query-source 对中，距离超过当前阈值的比例。
- false accept rate：预先标注为明显无关的 query-source 对中，距离未超过当前阈值的比例。
- 候选池截断：至少一个相关来源未进入当前候选池的 case 数量。
- 排序提升/退化：先比较 Recall@3，再比较 MRR，不只观察首个相关来源。

每次运行在 `backend/evals/results/retrieval-calibration-<timestamp>/` 生成 `summary.json`、`cases.json`、`distance-distribution.json` 和 `report.md`。结果目录继续由 Git ignore。

## 2026-07-19 实测结果

运行基于 Git 检查点 `fceef17f13fc05254fe103f53ef17787ffb63d25`，模型来自本地缓存，网络已禁用。

| 方案 | Recall@1 | Recall@3 | Recall@5 | Precision@3 | MRR | 空结果准确率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 纯向量距离 | 64.58% | 66.15% | 68.75% | 24.76% | 78.12% | 0% |
| 距离 + 当前词项 | 64.58% | 66.15% | 69.79% | 24.76% | 78.12% | 0% |
| 距离 + 词项 + 去重/多样性 | 64.58% | 69.79% | 69.79% | 27.62% | 78.12% | 0% |

去重/多样性提升 `exact_chromadb`、`keyword_stuffing` 和 `duplicates_and_neighbors`，没有检测到退化 case。最终重复比例为 0，排序不稳定、跨用户泄露和非法 source_id 均为 0。

## 距离分布

| 分布 | min | P50 | P95 |
| --- | ---: | ---: | ---: |
| 相关 | 0.2136 | 0.6685 | 1.3427 |
| 无关 | 0.2736 | 1.1711 | 1.4637 |

相关与无关距离在 7 个 case 中发生次序重叠。当前 `0.8` 阈值拒绝 18/48 个相关 query-source 对，false reject rate 为 37.5%；在 71 个明显无关对中接纳 8 个，false accept rate 为 11.27%。3 个预期空结果 case 都有候选落入阈值，因此空结果准确率为 0%。这些结果说明单一平方 L2 阈值不能完整区分当前合成集中的相关与无关语义。

## 候选池和参数比较

当前 `top_k=5`、候选倍数 3 时有 5 个 case 的部分相关来源未进入候选池：`exact_bge`、`synonym_embedding`、`mixed_bge_chinese`、`similar_fastapi_rag`、`duplicates_and_neighbors`。

受控模拟使用同一固定数据集，比较的是距离加词项方案；不会写入生产配置：

| 组合 | Recall@3 | Precision@3 | False reject | False accept | 截断 case |
| --- | ---: | ---: | ---: | ---: | ---: |
| 当前：阈值 0.8 / 倍数 3 / 语义 0.7 | 66.15% | 24.76% | 18 | 8 | 5 |
| 阈值 0.7 | 59.90% | 21.90% | 23 | 5 | 5 |
| 阈值 0.9 | 70.83% | 27.62% | 12 | 14 | 5 |
| 倍数 2 | 66.15% | 24.76% | 18 | 8 | 5 |
| 倍数 4 | 66.15% | 24.76% | 18 | 8 | 4 |
| 语义权重 0.6 | 66.15% | 24.76% | 18 | 8 | 5 |
| 语义权重 0.8 | 66.15% | 24.76% | 18 | 8 | 5 |

## 当前结论与下一阶段建议

本阶段不修改 `EVIDENCE_MAX_DISTANCE`、候选池参数、70/30 权重或 0.12 多样性惩罚。真实校准证明 Mock 通过并不代表真实向量可靠：当前阈值 false reject 较高，放宽阈值又明显增加 false accept；仅扩大候选池或改变语义权重也没有解决主要问题。

下一阶段应先逐 case 分析以下问题，再决定是否调整生产参数：

1. 区分“相关来源距离超过 0.8”和“相关来源未进入候选池”两类失败；
2. 复核 BGE 对文件名弱信号、否定表达和多相关来源 query 的适配；
3. 设计阈值与空结果策略时同时约束 false reject 和 false accept，不能只优化 Recall；
4. 若扩大候选池，先验证超过上限 20 是否确有稳定收益；
5. 保留当前固定集，并新增独立验证集，避免围绕这 35 个 query 过拟合。

## 已知局限

- 语料完全合成，规模远小于生产知识库。
- 标注体现本项目当前证据语义，不代表通用搜索基准。
- 没有 Cross Encoder 或额外 LLM reranker；这是刻意保持的当前生产链路边界。
- Chroma collection 没有显式 distance metadata，当前版本默认返回平方 L2；依赖版本变化后应重新验证。
- 本次只测本机已缓存的 BGE，不比较其他 Embedding 模型。

## 独立验证与最终保留集结果

检索可靠性阶段新增 25 query / 42 chunk 的 validation 和同规模 final holdout。两者均为全新虚构主题，包含 3 个虚构用户和 7 个无答案 query，并由 manifest SHA-256 固定。运行命令为：

```powershell
.venv\Scripts\python.exe -m evals.run_retrieval_calibration --real-embedding --dataset validation
.venv\Scripts\python.exe -m evals.run_retrieval_calibration --real-embedding --dataset holdout --final-holdout
```

final holdout 只有在 `retrieval_production_freeze.json` 中的生产文件与数据 manifest 哈希全部匹配时才能运行，并生成 `final-holdout-marker.json`。最终置信度加受控扩展方案在 validation 的 Recall@1/3/5 为 60.19%/84.26%/89.81%，Precision@3 为 28.00%，MRR 为 84.72%，无答案准确率为 100%，FR/FA 为 15.38%/8.00%。

冻结后的 final holdout 为 60.19%/70.37%/75.00%，Precision@3 22.67%，MRR 79.63%，无答案准确率 85.71%，FR/FA 26.92%/6.00%。泄露、非法 source 和排序不稳定均为 0。该结果未达到全部目标，且未用于再次调参。充分性设计、调用方策略和失败分析见 [检索证据充分性](RETRIEVAL_CONFIDENCE.md)。

## Coverage 独立集合结果

后续阶段没有复用上述集合调参，而是新建 coverage development 30/50、validation 25/45 和 final holdout 25/45 三套 query/chunk 数据，并在修改生产算法前冻结 validation 与 holdout。最终选择确定性 query facets、最多三路 BGE 查询、RRF 与证据集合选择。validation 的 Recall@3/MRR/Facet@3/Complete 为 78.70%/88.89%/90.62%/85.71%；正式 final holdout 为 81.48%/89.81%/83.87%/69.23%。final 的跨用户泄露、非法 source、排序不稳定和未捕获异常均为 0，但总体目标未通过，结果没有被用于再次调参。详见 [检索查询分析与证据集合](RETRIEVAL_EVIDENCE_SETS.md)。
