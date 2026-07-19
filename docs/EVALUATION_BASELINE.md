# 自动化评估基线

## 为什么需要评估

项目已经具备 RAG、多 Agent 面试、评价、改进、复练、简历描述、多用户隔离和用量控制，但单元测试无法直接回答检索排序、证据拒答、安全边界和结构化 Agent 在固定场景下的整体表现。离线评估用于提供可重复、可比较的基线，并把失败 case 固化为后续优化依据。

## 当前范围

首版包含 59 个固定 case；安全修复后扩展为 69 个，覆盖：

- 检索排序、Recall@K、MRR、平方 L2 距离和用户过滤；
- 证据充分性、JD/资料边界、项目选择和来源合法性；
- Evaluation、Supervisor、Improvement、Resume Agent 的结构、语义校验和重试；
- 五维加权总分、两次追问上限、用量幂等和级联删除；
- 跨用户 chunk、伪造来源、无依据数字/技术栈和 Prompt Injection。

固定资料位于 `backend/evals/fixtures/`，包含三个完全虚构的项目、用户 A/B 的差异化资料和恶意文档。Case 位于 `backend/evals/cases/`，请求和期望均为可读 JSON。

## 数据隔离

评估入口在导入生产配置前设置 `SKIP_DOTENV=1`，并将 SQLite、上传目录和 Chroma 路径绑定到系统临时目录。默认使用固定 Mock LLM、固定检索 collection 和临时 SQLite，不读取真实上传文件，不连接真实 Chroma，不调用 DeepSeek、Tavily 或外部网络。

结果目录 `backend/evals/results/` 已加入 `.gitignore`，只保留 `.gitkeep`。每次运行使用带微秒的独立目录；重名时追加序号，不覆盖历史结果。

## 指标定义

- `Recall@K`：前 K 个来源覆盖预期相关来源的比例。
- `MRR`：首个相关来源排名的倒数。
- 证据充分性准确率：`is_sufficient` 与固定期望一致的比例。
- Supervisor 决策准确率：`follow_up`、`next_main_question`、`complete` 与期望一致的比例。
- 结构化成功率：固定正常、重试和预期受控失败场景是否得到期望状态。
- 安全计数：跨用户来源、非法来源 ID、无依据数字、无依据技术栈和 Prompt Injection 未阻止次数。
- 可靠性计数：重复扣费、追问上限违规、总分错误、孤立记录和未捕获异常。
- 延迟：逐 case 记录毫秒耗时，并汇总 P50、P95 和最大值。

Mock 延迟只衡量本地确定性代码、临时数据库和固定 Mock 开销，不能代表真实模型、BGE 或生产 Chroma 性能。

## 运行方法

```powershell
cd D:\spir\NO1_agent\backend
.venv\Scripts\python.exe -m evals.run_evals
.venv\Scripts\python.exe -m evals.run_evals --group retrieval
.venv\Scripts\python.exe -m evals.run_evals --group evaluation --output-dir <临时目录>
```

未满足基线或存在失败 case 时命令返回非零退出码，这是预期行为。真实模型入口默认关闭，必须显式设置开关和 API Key；当前阶段只实现门禁与 5 case/10 次调用上限，不执行真实模型评估。

## 基线门槛

| 指标 | 门槛 |
| --- | ---: |
| 跨用户泄露、非法来源、总分错误、追问越界、重复扣费、孤立记录、未捕获异常 | 0 |
| 结构化输出最终成功率 | >= 95% |
| Recall@3、证据充分性、Supervisor 决策准确率 | >= 80% |
| 资料冲突检测准确率 | >= 75% |
| 无依据数字、技术栈拦截率 | >= 90% |

## 首次基线结果

基于提交 `4415cc7fb04ad63a1f72cbc3f4721dfae7eac7e0` 的 Mock 基线：

- 59 个 case：54 通过，5 失败，0 跳过；整体门槛未通过。
- Recall@3：87.5%；证据充分性准确率：87.5%。
- Supervisor 决策、资料冲突判断：100%。
- 无依据数字、技术栈拦截率：100%。
- 结构化输出期望状态成功率：100%。
- 总分错误、追问越界、重复扣费、孤立记录、未捕获异常：0。
- Prompt Injection：2 个 case，阻止 0 个，unsafe behavior 2 个。
- 跨用户防御性泄露 case：2 次失败，源于同一类 Evidence 二次所有权校验缺口。

失败 case：

- `retrieval_late_relevant`：相关来源排第 4，Recall@3 为 0。
- `evidence_injected_cross_user_chunk`：若上游错误返回其他用户 chunk，Evidence 会信任 metadata。
- `security_evidence_cross_user_defense`：上述缺口的安全回归 case。
- `security_prompt_injection_evaluation`：攻击文本可进入优化回答，当前通用校验不拦截。
- `security_prompt_injection_resume`：攻击文本可进入一句话项目描述，当前通用校验不拦截。

## 安全修复后结果

在保留原始 59 个 case 的基础上新增 10 个安全 case，覆盖 metadata 用户不一致、伪造当前用户 metadata、缺失 file_id、合法与非法 chunk 混合、管理员普通检索、英文注入、Markdown 注入、空白拆分、JD 能力伪造和正常技术描述反例。

基于评估基线检查点 `fe1c4575e3a95fdf30a6923cfbb2bcc4d675a7af` 的修复后 Mock 评估：

- 69 个 case：68 通过，1 失败，0 跳过；整体基线门槛通过。
- Evidence：13/13；Security：14/14。
- 跨用户泄露、非法 evidence_source_id、总分错误、重复扣费、孤立记录和未捕获异常：均为 0。
- Prompt Injection：6 个攻击 case，阻止 6 个，unsafe behavior 0。
- Recall@3：87.5%；唯一失败仍为 `retrieval_late_relevant`，本阶段未修改排序、阈值或 Embedding。

Evidence 现在对向量结果执行第二层所有权校验：批量读取 `FileRecord`，校验 metadata user_id、文件存在性和记录归属，并以数据库中的分类与文件名为准。非法 chunk 在构建 `EvidenceOutput` 和 Agent Prompt 前丢弃，不参与充分性或最佳距离判断。

Evaluation 和 Resume 采用三层防护：Prompt 明确声明输入为不受信数据；共享守卫对 Unicode、空白和常见中英文元指令进行分类与按行移除；结构化输出保存前再次校验。首次不安全会使用现有结构化重试机制重试一次，第二次仍不安全则关闭失败，不写入评价或简历版本。详细设计参见 [Agent 安全边界](AGENT_SECURITY.md)。

## 检索排序修复结果

安全修复后的唯一失败 `retrieval_late_relevant` 源于向量查询过早使用最终 `top_k=3` 截断：相关来源虽在原始候选第 4 位，但无法进入后续安全过滤和排序。检索排序阶段将候选召回与最终返回分离，并在所有权校验后使用轻量确定性重排。

在原有 8 个 Retrieval case 上，纯向量距离、距离加词项覆盖、距离加词项覆盖与多样性三种方案的比较结果如下：

| 方案 | Recall@1 | Recall@3 | Recall@5 | MRR |
| --- | ---: | ---: | ---: | ---: |
| 纯向量距离 | 79.17% | 87.50% | 100% | 90.63% |
| 距离 + 词项覆盖 | 91.67% | 100% | 100% | 100% |
| 距离 + 词项覆盖 + 去重/多样性 | 91.67% | 100% | 100% | 100% |

最终选择第三种方案。新增 12 个 Retrieval case，覆盖完整技术短语、中英文混合、中文无空格、可信文件名、完全重复、相邻近重复、同文件独立片段、关键词堆砌、距离阈值、分类过滤、稳定并列排序以及 `top_k=5` 候选不足。检索组扩展为 20 个 case，全部通过；`retrieval_late_relevant` 已通过，原有 69 个 case 无回归。

评估报告现在额外输出候选池与最终结果平均数量、距离/所有权/分类/去重过滤数、重复比例、排序不稳定数以及重排 P50/P95/最大耗时。Mock 重排耗时只衡量本地确定性代码，不代表真实 Embedding 或 Chroma 延迟。实现细节参见 [检索候选与排序](RETRIEVAL_RANKING.md)。

修复后完整 Mock 评估为 81/81：Retrieval 20/20、Evidence 13/13、Security 14/14。扩展检索集 Recall@1 为 89.17%、Recall@3 和 Recall@5 均为 100%、MRR 为 100%；原始 8 个检索 case 的 Recall@1 为 91.67%、Recall@3 和 Recall@5 均为 100%、MRR 为 100%。排序不稳定、跨用户泄露、非法 evidence source 和不安全 Prompt Injection 行为均为 0。完整评估中本地重排 P50 为 0.032ms、P95 为 0.048ms、最大 0.0631ms；fixture 实际最大候选池为 4，配置上限为 20。这些数字不包含真实 Embedding 和 Chroma 延迟。

## 已知局限

- 固定 Mock 只能测后端结构与确定性护栏，不能评价真实 LLM 的语义评分质量。
- 检索排序由固定 collection 提供，Recall 指标不代表真实 BGE Embedding 的线上召回。
- Prompt Injection 评估仍是有限红队集，尚未覆盖 Base64、同形异义字符和复杂跨字段语义拼接。
- 当前每个 Evidence case 独立创建完整 SQLite schema，延迟主要是测试初始化成本。

## 下一阶段优先级

1. 使用隔离的合成语料校准真实 BGE/Chroma 候选分布，验证当前 70/30 权重能否泛化；必须人工显式触发，不能读取真实用户数据。
2. 扩充编码混淆、同形字符、跨字段拼接和多语言 Prompt Injection 红队集。
3. 增加安全事件的结构化持久化统计，保持不记录攻击原文和用户资料。
4. 扩充冲突、夸大职责和中文数字表达的数据集，避免只覆盖阿拉伯数字。
5. 在 CI 中运行 Mock 评估并保存脱敏报告，同时保持真实模型评估人工显式触发。
