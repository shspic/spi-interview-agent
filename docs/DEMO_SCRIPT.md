# 演示脚本

所有演示只使用 `docs/demo/` 和 `scripts.seed_demo_data` 生成的虚构内容。演示前关闭浏览器 Secret 面板、终端环境变量、Cookie 详情和真实日志。

## 1 分钟版

| 顺序 | 点击 | 讲解文本 | 预期页面 |
|---|---|---|---|
| 1 | `/interview` | “普通聊天机器人只给答案，这个项目把真实资料、岗位和训练闭环放进同一个可恢复工作台。” | 资料准备进度 |
| 2 | 选择岗位与项目，开始面试 | “耗时动作进入 BackgroundJob，页面可刷新、取消和恢复。” | 首题与任务进度 |
| 3 | 打开已准备的结果 | “评价同时说明证据不足和冲突，随后给出可执行改进任务。” | 五维评分与证据 |

失败备用路线：Worker 未在线时展示已准备的历史结果和架构图，不现场重试模型。

## 3 分钟版

1. 登录虚构账号：说明 Cookie/CSRF，不展示 Cookie 值。
2. 知识库上传 `fictional_background_job_project.md`：指出只支持 PDF/TXT/MD、20 MB 单文件与 200 MB 总量。
3. 个人资料新增虚构岗位/JD：设为当前岗位。
4. 面试 Agent 选择快速模式并开始：指出 BackgroundJob、进度、取消和刷新恢复。
5. 回答一题：用 `FICTIONAL_ANSWERS.md`，展示五维评价、证据不足和冲突边界。
6. 查看 Improvement、Retry 对比和 Resume 版本：强调不夸大未经证据支持的成果。
7. 打开架构图：用一句话说明 FastAPI + Worker + PostgreSQL + Chroma。

失败备用路线：使用已完成会话；不修改 Prompt、不启用真实 DeepSeek、不展示 traceback。

## 5 分钟版

在 3 分钟版基础上增加：

- RAG：Query Analysis → 有限多查询 → RRF → 所有权 → Confidence → Evidence Set。
- Agent：Supervisor 协调 Evidence、Interviewer、Evaluation、Improvement、Resume。
- Evals：Mock `81/81`、Retrieval `20/20`，安全指标要求为 0；真实模型仍需人工验收。
- 安全：HttpOnly Cookie、Refresh rotation、CSRF Origin、上传白名单、多用户隔离、Prompt Injection。
- 工程：BackgroundJob 幂等、`SKIP LOCKED`、lease/heartbeat、Alembic、Docker 与三类持久数据备份。
- 管理端：`/admin` 查看用量、审计、任务与脱敏 Worker 状态。
- 部署：HTTPS host proxy → frontend → API，Worker/PostgreSQL 不公开。

结束语：“项目已完成单机 HTTPS 公网部署，公开入口和基础 readiness 已核验；登录后完整业务、并发规模和真实模型质量仍按未完成项如实说明。”
