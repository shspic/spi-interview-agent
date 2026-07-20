# 简历项目描述

以下描述只覆盖仓库已实现能力。最终测试数量应以最近一次本地验收报告为准。

## 精简版

- 独立开发证据驱动的 AI 求职训练工作台，使用 FastAPI、React、LangGraph、BGE、Chroma 与 PostgreSQL 串联资料、面试、评价、改进复练和简历表达。
- 设计数据库驱动 BackgroundJob，支持幂等、进度、取消、超时、重试、`SKIP LOCKED` claim、lease/heartbeat 与异常恢复。
- 构建多用户 RAG 安全链路：有限多查询、RRF、文件所有权、Confidence/Evidence Set、Prompt Injection 与跨用户泄露评估。
- 完成 Cookie/CSRF 会话、Alembic 双数据库迁移、Docker/Compose、备份恢复工具、Playwright E2E 与 Release Preflight。

## 标准版

目标：让求职者基于自己的项目资料和目标 JD 完成可解释、可复练、可恢复的面试训练，而非得到一次性聊天回答。

技术栈：Python 3.12、FastAPI、SQLAlchemy、Alembic、PostgreSQL/SQLite、LangGraph、DeepSeek、BGE、Chroma、React 19、Vite、Docker、Nginx、Playwright。

核心实现：建立 Evidence/Interviewer/Evaluation/Improvement/Resume Agent 协作链路；检索侧使用 Query Analysis、多查询与 RRF，并在数据库和向量层执行用户所有权校验；评价输出五维分数、证据引用、冲突、优化答案和后续任务。

工程化：耗时动作统一为 BackgroundJob，前端可轮询、取消和刷新恢复；生产配置要求 PostgreSQL、HTTPS Secure Cookie、明确 CORS/代理范围；PostgreSQL、uploads 和 Chroma 分开持久化与备份。

测试和安全：默认 Mock/检索评估不联网，覆盖认证、上传、限流、Alembic、任务恢复和多用户隔离；真实模型必须显式 gate 和人工评分。

## 岗位定制版

### AI 应用开发

突出完整产品闭环、结构化输出、Context Engineering、Evals、安全和可部署性。

### AI Agent 开发

突出 Supervisor 与五类 Agent 的职责边界、AgentRun 审计、失败恢复、BackgroundJob 和证据不足时的保守决策。

### RAG 开发

突出 PDF/TXT/MD 解析、BGE/Chroma、Query Analysis、多查询、RRF、Evidence Set、所有权校验和检索评估纪律。

### Python 后端

突出 FastAPI、SQLAlchemy、Alembic、PostgreSQL 并发、Cookie/CSRF、限流、上传安全、测试和运维工具。

### FastAPI 后端

突出依赖注入的认证边界、结构化错误、readiness、任务 API、旧同步接口 410 迁移、API no-store 和 OpenAPI deprecation。

不能夸大：不得写百万用户、企业客户、获奖、已公网运营、高并发生产验证或未测量性能提升。
