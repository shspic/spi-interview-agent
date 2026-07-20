# 技术追问题库

每题按“30 秒 / 2 分钟 / 可能追问 / 边界”组织。

## RAG、Chroma、BGE、RRF、Evidence Set

**30 秒：** BGE 生成中文语义向量，Chroma 存储；查询做有限多查询并用 RRF 融合排名，随后校验 FileRecord 所有权与 confidence，形成 Evidence Set。近似搜索结果不自动成为 Agent 证据。

**2 分钟：** 多查询只扩展少量确定性变体，控制成本与漂移；RRF 避免直接比较不同查询的距离尺度；Evidence Set 关注组合是否足够回答，而不只看单片段。文件身份从数据库验证，跨用户片段直接拒绝。证据不足或冲突进入结构化提示。

**可能追问：** 为什么 Chroma？为何不用 reranker？阈值怎么定？

**边界：** 不声称适合海量向量或所有语言；不继续围绕旧 holdout 调参。

## Context Engineering 与 Prompt Injection

**30 秒：** 每个 Agent 只拿当前任务所需字段，系统指令与证据分层；上传文本视为不可信数据，不能改变权限、工具或事实边界。

**2 分钟：** Context 包含当前用户、会话阶段、Evidence Set 和严格结构化 schema，不携带其他用户内容或 Secret。注入测试验证不服从文档内指令、不泄露、不生成非法 evidence source。

**可能追问：** 仅靠 Prompt 足够吗？

**边界：** 不足够，因此权限、所有权、白名单和输出校验在代码层实现。

## 多用户隔离与上传安全

**30 秒：** 业务查询带 `user_id`，向量来源回查 FileRecord 所有权；上传只允许 PDF/TXT/MD，流式限制大小并使用受控存储路径。

**2 分钟：** 认证用户 ID 只来自服务端会话，不接受请求伪造；下载/删除解析路径必须位于该用户目录；文件名仅用于展示，内部 ID 与 SHA 不暴露给普通 UI。

**可能追问：** 管理员如何访问？PDF 恶意内容呢？

**边界：** 不是杀毒沙箱；生产仍需平台层恶意文件扫描与资源隔离。

## Evals 与 holdout

**30 秒：** Mock 评估验证稳定业务与安全行为，Retrieval 验证检索；Live Harness 默认关闭并要求人工确认与评分。holdout 冻结后只做最终测量，不据其结果反复调参。

**2 分钟：** 指标包括召回、MRR、证据有效性、跨用户泄露、Prompt Injection、未捕获异常和孤儿记录。机器通过不替代自然度、公平性与 Resume 夸大的人评。

**可能追问：** 如何处理评估污染？

**边界：** 当前数据集规模有限，不声称代表真实招聘分布。

## Cookie、CSRF 与 Refresh Rotation

**30 秒：** Access/Refresh 放 HttpOnly Cookie，CSRF token 可读并随写请求 header 返回；服务端校验 Origin。Refresh 在 AuthSession 中原子轮换，重放会撤销会话。

**2 分钟：** Access path `/api`，Refresh path `/api/auth`，生产 Secure、SameSite=Lax、host-only domain。Logout All 撤销用户全部会话；改密码后要求重新登录。

**可能追问：** SameSite 为什么还要 CSRF？多标签页如何失效？

**边界：** HTTPS 与可信代理配置错误会破坏安全假设，preflight 只能发现部分配置问题。

## Alembic、PostgreSQL 与 BackgroundJob

**30 秒：** Alembic 是 Schema 真源；生产 PostgreSQL 使用 `SKIP LOCKED` claim。任务具备幂等、额度、超时、取消、重试、lease 和 heartbeat。

**2 分钟：** 创建任务先按用户/类型/幂等键去重；Worker 在事务中 claim；执行中更新心跳，完成时提交结果与 Usage，失败释放或进入 retry_wait。过期 lease 恢复，终态不再 claim。

**可能追问：** 为什么不 Celery/Redis？如何保证 exactly-once？

**边界：** 实现的是幂等的 at-least-once 语义，不宣称绝对 exactly-once；当前没有大规模性能验证。

## Docker、备份与恢复

**30 秒：** Compose 包含 PostgreSQL、migrate、API、Worker、frontend；PostgreSQL 不公开端口。备份必须协调 pg_dump、uploads、Chroma，并定期恢复到新测试库。

**2 分钟：** migrate 完成后 API/Worker 才启动；readiness 检查认证、数据库、Schema、存储和任务表，Worker heartbeat 单独显示。恢复工具要求数据库名包含 `test` 或 `restore`，校验 SHA-256，不覆盖未知库。

**可能追问：** 如何回滚 migration？volume 损坏怎么办？

**边界：** 当前未引入 Kubernetes，也不声称跨机高可用。

## 为什么不用普通聊天机器人

**30 秒：** 核心价值不是“再生成一段答案”，而是让答案可追溯到当前用户资料，并通过评价、任务和 Retry 形成可测量训练过程。

**2 分钟：** 聊天窗口难以表达岗位、会话、证据、任务状态和版本关系，也不天然解决刷新恢复、取消、用量与审计。该项目用领域模型和 BackgroundJob 把这些状态显式化。

**可能追问：** 用户会不会觉得流程太重？

**边界：** 快速模式允许资料不完整时开始，并明确提示个性化证据有限。
