# 旧同步长任务 API 收敛审计

## 策略

生产默认关闭 `ENABLE_SYNC_LONG_TASK_COMPAT`。旧公开同步长任务返回 HTTP 410、`replacement` 和 deprecation 元数据；测试环境可临时开启兼容以证明核心 service 行为没有分叉。生产配置校验会拒绝开启兼容。前端主流程只创建 BackgroundJob。

| 旧接口 | 分类 | 新入口 | 说明 |
|---|---|---|---|
| `POST /api/agent/ask` | 兼容过渡 / 生产废弃 | `/api/tasks/agent-ask` | 复用 Agent 核心 service，不能绕过额度、超时、取消和审计 |
| `POST /api/jobs/analyze` | 兼容过渡 / 生产废弃 | `/api/tasks/job-analysis` | Worker 复用岗位分析 service |
| `POST /api/interview/question` | 废弃 | 面试会话 + `/api/tasks/interview-start` | 独立旧题目接口不再作为主流程 |
| `POST /api/interview/evaluate` | 废弃 | `/api/tasks/interview-evaluation` | 新 payload 是 `session_id + turn_id + answer` |
| `POST /api/interview-sessions/{id}/start` | 兼容过渡 / 生产废弃 | `/api/tasks/interview-start` | 会话创建仍是轻量同步操作 |
| `POST /api/interview-sessions/{id}/answer` | 兼容过渡 / 生产废弃 | `/api/tasks/interview-evaluation` | 回答、评价、追问和恢复由同一 flow service 完成 |
| `POST /api/interview-sessions/{id}/improvements/retry` | 兼容过渡 / 生产废弃 | `/api/tasks/improvement-generation` | 失败后重新创建任务 |
| `POST /api/resume-project-descriptions/generate` | 兼容过渡 / 生产废弃 | `/api/tasks/resume-generation` | 版本读取与删除继续同步 |
| `POST /api/knowledge/rebuild` | 兼容过渡 / 生产废弃 | `/api/tasks/knowledge-rebuild` | 文件上传、列表、搜索和删除继续同步 |
| `POST /api/admin/maintenance/cleanup` | 兼容过渡 / 生产废弃 | `/api/tasks/data-retention-cleanup` | 清理预览继续同步，执行进入后台任务 |

继续保留的同步接口只有轻量 CRUD、只读详情、逐项 Improvement 状态切换、会话取消壳层、清理预览和显式账号删除。个人业务数据清理当前保留为受密码保护的同步管理操作，因为它不调用模型且需要立即报告文件/向量清理是否完整；它仍受 CSRF、限流、所有权和审计约束。
