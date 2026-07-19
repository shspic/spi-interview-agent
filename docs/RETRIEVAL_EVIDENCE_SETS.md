# 检索查询分析与证据集合

## 为什么不能只排一个 chunk

单条候选的向量距离和词项覆盖只能说明“这个片段与问题相关”，不能证明多部分问题已经被完整支持。一个高排名片段可能只覆盖上传流程、只覆盖某个技术栈，或来自名称相似的另一个项目。当前链路因此在既有 70% 距离语义分、30% 词项分和 0.12 多样性惩罚之外，增加查询分析、多路召回、候选融合、证据集合选择和集合级充分性判断；原有 Embedding、评分权重及硬拒绝边界均未改变。

## Query Analysis

`QueryAnalysis` 是完全确定性的内部结构，包含：`normalized_query`、`intent`、`intents`、`project_constraints`、`entity_terms`、`technical_terms`、`attribute_terms`、`numeric_requirements`、`negation_mode`、`required_facets` 和 `query_variants`。分析只使用问题本身以及当前用户经数据库所有权校验后的可信文件名，不访问网络、不调用 LLM，也不读取其他用户数据。

意图由少量可解释信号组合得出：是否/有没有用于 existence，明确否定表达用于 negative，数字与单位用于 numeric，以及/同时/分别用于 multi_part，步骤/流程/如何进入用于 multi_hop，相比/区别用于 comparison，“是否有资料证明”用于 evidence_check；普通技术词本身不会触发多跳。多个信号可以同时保留在 `intents`，兼容字段 `intent` 取确定性的主意图。

## Required facets

facet 只从查询中的项目限定、技术实体、属性、比较两端和流程部分生成，最多保留三个稳定、非重复的主要 facet。每个 facet 保存可解释的术语集合，用候选正文判断覆盖；文件名只辅助项目身份，不能伪造正文中的属性证据。多部分和多跳问题必须覆盖必要 facet，单个强 chunk 不能掩盖缺失 facet。

## 受控查询变体

每次最多生成两个变体，加原始问题后最多执行三次 Chroma 查询。变体来自主要 facet、项目限定与属性组合、技术缩写与全称或中英文别名；完全重复、单个通用词和过短变体会被丢弃。生成过程稳定、无随机数，不自动加入 JD 技能，不记录完整 query，也不会额外计业务额度。

## 候选融合

离线比较了四种方案：

- A：当前单 query 与单候选排序；
- B：确定性 facets、多 query、同 chunk 取最低距离；
- C：确定性 facets、多 query、RRF；
- D：确定性 facets、多 query、RRF 加 Evidence Set Selector。

生产选择 D。RRF 使用集中常量 `k=60`；同一 chunk 的最佳距离继续进入既有 70/30 确定性重排。不同路线先按当前用户的可信 `FileRecord` 集合、安全 category 和 `1.15` 硬拒绝边界过滤，再融合。每条路线使用受控 `candidate_k`，合并候选总数上限为 40；空知识库不执行多余查询，所有权始终是每个请求一次批量数据库查询，没有 N+1。

## 项目与文档身份

当前数据模型没有正式 `project_id`。实现不扩张数据库模型，而是只用当前用户数据库中的 `FileRecord.filename`、`category` 和用户边界构建受控文档组；查询中的项目名仅作为辅助一致性信号。Chroma metadata 中的项目名不可信，文件名命中不能绕过距离硬拒绝，其他用户文件名不会参与推断。缺少正式项目标识仍是已知限制。

## Evidence Set Selector

选择器先保证首条高相关，再在不超过 `top_k` 的前提下，按相关性、尚未覆盖的 facet、独立来源和项目一致性增加收益；完全重复或相邻近重复片段不能冒充独立证据。它允许同一文件的两个独立事实和多文件互补证据共同入选，但不会为了多样性选择明显无关、错误项目、JD 能力、其他用户或超过硬拒绝距离的片段。相同输入使用固定 tie-breaker，输出顺序稳定。

内部统计包括 `covered_facets`、`missing_facets`、`independent_source_count`、`duplicate_filtered_count` 和 `project_consistency`。这些统计用于决策和离线评估，不要求改变前端返回结构。

## 集合级 sufficient

单事实问题允许一个高置信证据通过；多部分和多跳问题要求关键 facet 完整覆盖，否则标为 partial 并对外映射为 `sufficient=false`。具体数字或技术属性必须由正文证据支持；只有 JD、其他用户或相似项目中的属性均不能通过。明确否定只能由明确否定语句支持；资料未提到的属性保持 unknown，不能从“没有检索到”推断为不存在；evidence_check 必须返回真实可信来源。

普通 Chat、Evidence Agent、Interview、Evaluation、Resume、Job Analysis 和旧面试流程均通过可信检索或 evidence wrapper 使用集合级结论。Evaluation 不把 partial 当完整支持，Resume 的候选事实仍逐项验证，Job Analysis 不把 JD 当用户能力。`/knowledge/search` 保持近似搜索展示语义，不强制 Agent 的严格充分性。没有修改 Prompt、评分权重、用户额度或前端。

## 多跳、多证据与缺失属性

多查询提高候选覆盖，集合选择负责把互补片段放进有限 `top_k`；是否完整则由 facet 集合而非最高单条分数决定。对于“项目用了什么框架以及如何隔离用户”这类问题，框架与隔离是独立 facet；对于用户量、准确率、部署平台、Redis、Kubernetes、消息队列、PostgreSQL、Docker、付费用户和延迟等属性，如果可信项目材料没有正文证据，结果必须 insufficient/unknown。

## 数据集冻结纪律

本阶段创建后立即冻结三套全新虚构数据：development 为 30 query / 50 chunk，validation 为 25/45，final holdout 为 25/45，均含 3 个虚构用户。SHA-256 分别为 `cb2e4baf5f29e9658c9dac2c0740010173f3bd556b64f58c016f274559785c9b`、`abded30dccb7332577c4bc30066b752a5575f4a36e0f36020fb65a41c42a9263` 和 `12ed8f6b004c47e71dd5c0c2661181067ea260a9b073b74f213e0349208d3185`。三者与旧集合无 query/chunk 完全重复；manifest 固定文件哈希，production freeze 固定生产文件哈希和配置。

development 用于实现，validation 用于 A～D 方案选择。生产逻辑冻结后才正式运行一次 final holdout，并写入 `formal_run_completed=true`；之后未修改生产文件、参数、fixture 或期望。

## 真实 BGE 方案比较

下表均使用本地缓存的 `BAAI/bge-small-zh-v1.5`、归一化 512 维向量、临时 Chroma、网络禁用。P3 同时保留原始值与 available-relevance-normalized 值。

| 集合/方案 | R@1/3/5 | raw/normalized P@3 | MRR | NA | FR/FA | Facet@3 | Complete | Partial→Complete | Project | Negative | Unknown | Redundancy |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| development A | 46.38/71.74/86.96% | 39.13/71.74% | 78.19% | 42.86% | 19.05/57.14% | 85.37% | 76.47% | 100% | 37.50% | 100% | 42.86% | 0% |
| development D | 54.35/79.71/87.68% | 46.38/79.71% | 88.77% | 71.43% | 16.67/28.57% | 92.68% | 82.35% | 66.67% | 62.50% | 100% | 71.43% | 0% |
| validation A | 43.52/58.33/68.52% | 33.33/58.33% | 72.87% | 75.00% | 33.33/25.00% | 65.62% | 50.00% | 100% | 50.00% | 66.67% | 75.00% | 0% |
| validation D | 53.70/78.70/80.56% | 46.30/78.70% | 88.89% | 100% | 21.21/0% | 90.62% | 85.71% | 66.67% | 100% | 66.67% | 100% | 0% |
| final A | 40.74/72.22/82.41% | 38.89/72.22% | 77.31% | 62.50% | 24.24/37.50% | 74.19% | 53.85% | 100% | 50.00% | 100% | 62.50% | 0% |
| final D | 53.70/81.48/86.11% | 46.30/81.48% | 89.81% | 87.50% | 18.18/12.50% | 83.87% | 69.23% | 60.00% | 75.00% | 100% | 87.50% | 0% |

在 development 上 D 相对 A 改善 6 个 case、退化 1 个；validation 改善 8 个、退化 0 个；final holdout 改善 6 个、退化 2 个。B/C 的多查询改善有限且在这些小集合中表现接近，真正的完整性增益主要来自集合选择，但 final 的退化和未达标项被完整保留。

## 性能成本

final holdout 中 A 平均查询 1 次、候选 13.52、P50/P95 为 58.79/340.39ms；D 平均 2.64 次、最大 3 次、候选 19.32、P50/P95 为 147.45/670.39ms。D 的融合 P50/P95 为 0.17/0.25ms，集合选择为 0.73/12.50ms；主要额外成本来自多次向量查询。每 case 的 FileRecord 批量查询为 1 次。

## 已知局限

- final holdout 的总体目标评估为失败：FA 12.50%、Facet@3 83.87%、Complete 69.23%、Partial→Complete 60%、Project 75% 和 Unknown 87.50% 未达目标。
- 小规模合成数据不能代表生产查询分布，规则式中文语义分析仍可能漏掉隐含关系。
- `project_id` 缺失使文件名辅助信号无法提供强项目身份保证。
- 多查询使 final P95 从 340.39ms 增至 670.39ms，需要在真实规模监控，但不能通过放宽安全边界换取速度。
- 明确否定与上位概念否定仍有标注及语义边界，不能把未命中等同于不存在。
- 本阶段未引入 Cross Encoder、LLM rewrite/reranker、网络服务或新 Embedding 模型。
