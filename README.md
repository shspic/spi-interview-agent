# AURORA

**AI Interview Intelligence**
让潜力被看见，让成长有迹可循

一个面向 AI 应用与 Python 后端求职者的证据驱动训练工作台：把个人资料、目标岗位、结构化面试、评价、改进复练和简历表达串成可恢复的完整流程。

> 当前交付状态：已完成单机 Docker Compose 公网部署，入口为 <https://43.153.181.237:8443/>。2026-08-11 通过真实浏览器与匿名健康检查确认：登录页可访问，`/api/health/live` 返回 alive，`/api/health/ready` 返回 ready，PostgreSQL、Schema、存储、任务系统与 Worker 均就绪。匿名接口未暴露构建 commit，因此“线上实例与当前工作树完全一致”仍需发布版本标识证明；真实 DeepSeek 输出质量也仍以独立人工验收为准。

## 适用场景与核心能力

- 为目标岗位维护用户资料、JD、项目与简历文件。
- 上传 PDF、TXT、MD，经过安全校验、解析、chunk、BGE embedding 后写入 Chroma。
- 由 LangGraph Supervisor 协调 Evidence、Interviewer、Evaluation、Improvement 与 Resume Agent。
- 完成“开始面试 → 逐题回答 → 五维评价 → 改进任务 → Retry 对比 → Resume 版本”的训练闭环。
- 使用数据库驱动 BackgroundJob 处理索引、Agent、岗位分析、面试启动/评价、改进与简历生成。
- 为用户和管理员提供用量、系统 readiness、任务状态、Worker 心跳、审计与认证安全事件视图。

## 技术栈

- 前端：React 19、Vite 8、Axios、原生 History API 路由、CSS Design Tokens、Playwright 1.61.1。
- 后端：Python 3.12、FastAPI、SQLAlchemy、Alembic、Pydantic、Uvicorn。
- 数据：开发可用 SQLite；生产要求 PostgreSQL；Chroma 保存向量，独立 volume 保存 uploads。
- AI：DeepSeek、LangGraph、Tavily、`BAAI/bge-small-zh-v1.5`、RAG、RRF 与 Evidence Set。
- 交付：Docker/Compose、Nginx 同站点反向代理、pg_dump/restore、Release Preflight。

## 架构

浏览器只访问同一 HTTPS Origin。反向代理提供 SPA 和 `/api`；FastAPI 负责认证、业务与任务创建，Worker 从 PostgreSQL claim 任务。PostgreSQL、uploads 和 Chroma 是三类必须协调备份的持久数据。

完整系统、RAG、Agent、认证和部署 Mermaid 图见 [最终架构](docs/ARCHITECTURE.md)。

## RAG、Agent 与 Context Engineering

上传文件先校验类型、大小、安全文件名和用户存储配额，再解析、切分并建立向量索引。查询经过确定性 Query Analysis、有限多查询、RRF 融合、文件所有权校验、confidence 和 Evidence Set 选择；`/knowledge/search` 只是近似搜索展示，不代表 Agent 已采纳为证据。

LangGraph 不是普通聊天 UI 的包装。Supervisor 按任务阶段协调证据、提问、评价、改进与简历表达；上下文只携带当前用户允许的文件摘要、结构化 Evidence Set 和必要会话状态。证据不足时降低结论强度，冲突会显式提示，Resume 禁止扩写未被资料支持的成果。

## 安全边界

- HttpOnly Access/Refresh Cookie、服务端 AuthSession、Refresh 原子轮换与撤销。
- 同站点 CSRF double-submit token、Origin 校验、明确 CORS Origin 和可信代理 CIDR。
- 多用户查询在数据库和向量检索层都带所有权条件；管理员 UI 不显示 Token、Cookie、Secret、IP 明文或完整用户内容。
- 上传只支持 PDF/TXT/MD，限制单文件、请求体、页数、行长度、用户总存储和速率。
- Prompt Injection 评估要求跨用户泄露、非法 evidence source 和 unsafe behavior 均为 0。
- 旧同步长任务默认返回受控 410；生产禁止开启 `ENABLE_SYNC_LONG_TASK_COMPAT`。

详见 [认证安全](docs/AUTH_SESSION_SECURITY.md)、[API 与上传安全](docs/API_AND_UPLOAD_SECURITY.md) 和 [Agent 安全边界](docs/AGENT_SECURITY.md)。

## BackgroundJob

任务状态包括 `queued`、`running`、`retry_wait`、`cancel_requested`、`succeeded`、`failed`、`cancelled`、`timed_out`。幂等键防止重复创建；PostgreSQL `SKIP LOCKED` 防止多 Worker 重复 claim；lease、heartbeat 和过期恢复处理 Worker 中断；终态停止前端轮询。Worker 与兼容同步入口复用同一核心 service，不维护两套业务逻辑。

接口迁移表见 [同步 API 收敛审计](docs/SYNC_API_AUDIT.md)，实现说明见 [后台任务](docs/BACKGROUND_JOBS.md)。

## 本地启动

```powershell
cd D:\spir\NO1_agent\backend
.venv\Scripts\python.exe -m scripts.bootstrap_local_env
.venv\Scripts\python.exe -m alembic upgrade head
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend_dev.ps1
```

另开终端：

```powershell
cd D:\spir\NO1_agent\frontend
npm ci
npm run dev
```

默认开发入口为 `http://localhost:5173`，API 文档为 `http://localhost:8000/docs`。不要把 `backend/.env` 提交到 Git。

## Docker 启动

本地使用纯虚构 process-only 环境变量后执行：

```powershell
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

停止可执行 `docker compose down`，禁止使用 `down -v`。生产必须叠加 `deploy/docker-compose.production.yml`，详见 [部署与 Release 流程](docs/DEPLOYMENT.md) 与 [Docker 说明](docs/DOCKER_PRODUCTION.md)。

## 环境变量与生产要求

以 `backend/.env.example` 和 `deploy/.env.production.example` 为清单。生产至少要求：

```env
APP_ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://...
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
AUTH_COOKIE_DOMAIN=
CORS_ALLOWED_ORIGINS=https://example.com
APP_TRUSTED_PROXY_CIDRS=172.30.0.0/24
ENABLE_LEGACY_SCHEMA_PATCHES=false
ENABLE_SYNC_LONG_TASK_COMPAT=false
```

Secret 只能来自受限环境文件或 Secret Manager。HTTPS 是生产硬要求；HSTS 只在全链路 HTTPS 稳定后启用。

## Alembic 与数据库

正常启动不会依赖运行时 `create_all`。新库执行 `alembic upgrade head`；现有旧 SQLite 先按 [迁移文档](docs/DATABASE_MIGRATIONS.md) 接管。生产必须使用 PostgreSQL psycopg 驱动。临时 SQLite 的验证顺序是 `upgrade head → current → downgrade -1 → upgrade head`，不得对真实开发库 downgrade。

## 测试与 Evals

```powershell
cd D:\spir\NO1_agent\backend
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m evals.run_evals
.venv\Scripts\python.exe -m evals.run_evals --group retrieval
.venv\Scripts\python.exe -m evals.run_live_agent_smoke --check

cd ..\frontend
npm run lint
npm run build
npm run test:e2e
```

当前后端静态收集为 `413 tests`；最近一次完整隔离回归记录为 `410 passed, 3 skipped`，跳过项是需要显式 PostgreSQL 测试库的集成测试。2026-08-11 重新收集确认仍为 413 项；本轮全量重跑在 180 秒上限内执行到 52% 且未出现失败，但未完成，因此不把本轮写成 413 项通过。Mock 评估最近完整记录为 `81/81`，Retrieval 为 `20/20`。Playwright 当前静态收集 `43 tests`；公网仅完成登录页、CSRF、live/readiness 的匿名冒烟，不能声称 43 项线上全部通过。E2E fixture 不访问真实模型，也不能替代登录后的完整线上业务验收。

## Live Harness

真实 DeepSeek 验证默认关闭。先运行 `--check` 查看 case 数、最大调用数、Token 和成本上限；真实运行必须显式开 gate 并人工确认，数据全为虚构，报告脱敏。人工评分覆盖问题自然度、追问合理性、评分公平性、证据忠实度、优化答案自然度和 Resume 是否夸大。详见 [真实模型验证](docs/LIVE_MODEL_VALIDATION.md)。

## 管理员、数据保留与备份

- 管理后台正式 URL：`/admin`。未登录跳转登录，普通用户得到 403，权限不来自 localStorage。
- 管理员可查看用户、Usage、Agent Runs、Audit、邀请码、清理、Background Jobs 和脱敏 Worker 状态。
- 默认业务数据保留期为 7 天，可预览后通过后台任务清理；账号删除需要密码、用户名和固定确认文本。
- PostgreSQL dump 不包含 uploads 与 Chroma，三者必须在同一维护窗口协调备份并定期恢复演练。

## Release Preflight

```powershell
cd D:\spir\NO1_agent\backend
.venv\Scripts\python.exe -m scripts.release_preflight --dry-run
```

工具只读，输出 `pass/warn/fail`，不打印 Secret、不迁移、不建管理员、不调用模型；生产 `fail` 时退出非零。

## 演示

先创建一个没有真实资料的本地账号，再执行：

```powershell
cd D:\spir\NO1_agent\backend
.venv\Scripts\python.exe -m scripts.seed_demo_data --username <虚构演示账号>
```

工具只允许 development/test，不创建默认密码，不覆盖已有资料，可用 `--cleanup` 只清理自身标记的数据。点击顺序与 1/3/5 分钟讲法见 [演示脚本](docs/DEMO_SCRIPT.md)，素材位于 `docs/demo/`。

## 目录结构

```text
backend/app/        FastAPI、服务、模型、Agent 与安全边界
backend/alembic/    数据库迁移
backend/evals/      Mock、Retrieval 与 Live Harness
backend/scripts/    初始化、备份、恢复、preflight、demo seed
frontend/src/       路由、页面、组件、Design Tokens
frontend/e2e/       Playwright 浏览器测试与虚构 API fixture
deploy/             生产 Compose、HTTPS Nginx、环境模板
docs/               架构、部署、演示、简历和面试材料
```

## API 入口

- `/api/auth/*`：Cookie 会话、CSRF、登录、轮换与撤销。
- `/api/tasks/*`：后台任务创建、查询与取消。
- `/api/interview-sessions/*`：轻量会话 CRUD、详情和只读结果。
- `/api/files`、`/api/knowledge/*`：上传、索引和近似搜索。
- `/api/admin/*`：管理员受保护接口。
- `/api/health/live`、`/api/health/ready`：存活和就绪。

## 已知局限

- `axios` 当前为 `1.18.0`，传递依赖 `form-data` 已锁定到 `4.0.6`，旧文档中的 `4.0.5` 风险说明已经失效；本轮未重新执行联网 `npm audit`，因此仍不声称依赖审计完全无风险。
- 当前是单机 Compose 公网部署，已验证公开入口与基础 readiness；未经过真实用户运营、大规模并发、高可用或故障切换验证。
- 不支持 CSV、Excel、图片 OCR，也未更换 BGE embedding。
- SQLite 只适合本地单 Worker；生产并发路径要求 PostgreSQL。
- Live DeepSeek 质量需要用户后续付费、显式确认并人工验收。
- Chroma、uploads 与 PostgreSQL 的一致备份仍需要维护窗口协调。
- E2E fixture 验证浏览器主流程；公网 readiness 已确认 PostgreSQL 与 Worker 就绪，但登录后的真实文件、RAG、面试和后台任务闭环仍需线上人工验收。

## Roadmap

优先完成线上备份恢复演练、证书自动续期监控、登录后核心业务冒烟、真实模型人工评分和可回滚发布版本标识；不计划仅为扩大技术栈引入 Redis、Celery、Kafka、RabbitMQ 或 Kubernetes。

## License

当前仓库未声明开源许可证。除非仓库所有者另行添加 License，不应推定获得复制、分发或商用授权。
