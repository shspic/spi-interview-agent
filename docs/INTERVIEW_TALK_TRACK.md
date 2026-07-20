# 面试讲法

## 为什么做这个项目

**30 秒：** 普通题库和聊天机器人无法核对个人经历，也不能形成持续改进。我把个人资料、目标 JD、证据检索、面试评价、改进复练和简历表达做成一个可恢复闭环。

**2 分钟：** 从“答案是否真实”出发设计数据与 Agent 边界：文件归属当前用户，Evidence Set 只接收通过阈值与所有权检查的片段；评价和 Resume 对证据不足保持保守。工程上把耗时操作放入数据库任务表，解决浏览器刷新、重复提交、超时和 Worker 中断。

**可能追问：** 为什么不用聊天机器人？如何防止编造？为什么要后台任务？

**不能夸大：** 没有真实企业客户、公网投产或真实招聘效果数据。

## 为什么用 LangGraph

**30 秒：** 任务包含证据、提问、评价、改进和简历五种不同职责，需要显式状态与可审计转移，LangGraph 比一个巨型 Prompt 更容易约束和测试。

**2 分钟：** Supervisor 只做阶段协调，Evidence 管资料，Interviewer 管问题，Evaluation 管结构化评分，Improvement 产出任务，Resume 只改写被证据支持的经历。每步记录 AgentRun，失败由 BackgroundJob 管理，而不是把工具执行过程暴露给用户。

**可能追问：** 为什么不用函数串联？状态如何恢复？

**不能夸大：** 图工作流不自动等于更聪明，质量仍依赖证据与模型人工验收。

## 如何讲工程闭环

**30 秒：** FastAPI 创建 BackgroundJob，PostgreSQL 用 `SKIP LOCKED` claim；幂等键防重复，lease/heartbeat 支持恢复，前端终态停轮询。Cookie/CSRF、上传安全和所有权贯穿 API。

**2 分钟：** 先讲一致性：Usage reserve/commit/release 与任务状态；再讲并发：多 Worker claim；再讲故障：超时、取消、重试等待、lease 过期；最后讲交付：Alembic、Compose、readiness、三类持久数据备份和只读 preflight。

**可能追问：** Redis/Celery 更成熟，为什么不用？PostgreSQL 锁会不会成为瓶颈？

**不能夸大：** 当前规模适合单机 RC，没有做大规模负载验证；需求扩大后才评估专业队列。

## 已知局限与下一步

**30 秒：** 最大未完成门禁是真实 Docker/PostgreSQL 恢复演练和真实 DeepSeek 人工验收；当前 E2E fixture 不能替代它们。

**2 分钟：** 下一步先在安全测试库执行 migration、并发、持久化与 restore test，再由用户明确确认小规模 Live Harness，人工评问题自然度、公平性、忠实度和 Resume 夸大。通过前不会声称生产就绪。

**可能追问：** 如果验证失败先改哪里？如何避免 holdout 污染？

**不能夸大：** 不说“已上线”“高并发”“零故障”。
