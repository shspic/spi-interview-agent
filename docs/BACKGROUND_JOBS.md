# 数据库后台任务

现有 `ImprovementTask` 是用户训练待办，不是执行队列。本阶段新增 `BackgroundJob`、`BackgroundJobEvent`、短期 `BackgroundJobArtifact`、`WorkerHeartbeat` 和 `MaintenanceState`。任务表只保存状态、进度、lease、幂等 hash、额度事件 ID 和安全引用，不保存完整文件、简历或内部 Prompt；API 不返回输入引用、Worker ID 或完整异常。

```text
queued -> running -> succeeded
queued -> cancelled
running -> cancel_requested -> cancelled
running -> retry_wait -> running
running -> failed | timed_out
```

终态不可改写。进度为 `0..100`，阶段与 `message_code` 不含用户原文。PostgreSQL 使用 `FOR UPDATE SKIP LOCKED`；SQLite 拒绝并发大于 1 和第二个活跃 Worker。

```powershell
.venv\Scripts\python.exe -m app.worker
.venv\Scripts\python.exe -m app.worker --once
.venv\Scripts\python.exe -m app.worker --maintenance --dry-run
```

客户端发送 8 到 128 位 `Idempotency-Key`，服务端只保存 HMAC hash。同一用户、类型与 key 返回原任务。需要额度的任务在 quota 绑定前不可 claim；成功只 commit 一次，失败、取消、超时 release。Worker 通过 lease、heartbeat、最大尝试次数和受控退避恢复。

创建接口返回 `202`：`/api/tasks/knowledge-rebuild`、`agent-ask`、`job-analysis`、`interview-start`、`interview-evaluation`、`improvements`、`resume`；查询与取消使用 `/api/tasks/{task_id}`。跨用户统一 404，响应 `no-store`，写操作受 Cookie/CSRF 保护。

前端 Agent、岗位分析和知识库重建已接入轮询、取消和刷新恢复；旧同步 API 暂时保留兼容。完整面试工作台逐步骤异步 UI 仍是后续收口项。

Worker 每分钟尝试恢复 lease、释放孤立额度和清理历史；PostgreSQL 用 advisory lock，SQLite 因单 Worker 串行。数据保留最多每天执行一次，并支持 dry-run。
