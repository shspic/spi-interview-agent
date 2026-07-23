# AURORA 公网部署交接

本文是部署交接清单，不包含任何真实 Secret，也不授权本轮执行公网部署。

## 1. 建议规格与运行时

- 最低建议：2 vCPU、4 GB RAM、40 GB SSD；若在同机运行 embedding 或数据量增长，建议 4 vCPU、8 GB RAM。
- 使用受支持的 64 位 Linux、Docker Engine 27+ 与 Docker Compose v2.30+。
- 不得用 Vite、Uvicorn `--reload` 或其他开发服务器直接暴露公网。

## 2. 生产环境变量

以 `deploy/.env.production.example` 和 `backend/.env.example` 为清单，只在服务器受限文件或 Secret Manager 中填写真实值。核心变量包括：

```text
APP_ENVIRONMENT
DATABASE_URL
POSTGRES_PASSWORD
JWT_SECRET_KEY
AUTH_CSRF_SECRET
RATE_LIMIT_HASH_SALT
REGISTRATION_INVITE_CODE
AUTH_COOKIE_SECURE
AUTH_COOKIE_SAMESITE
AUTH_COOKIE_DOMAIN
AUTH_REQUIRE_ORIGIN_CHECK
CORS_ALLOWED_ORIGINS
APP_TRUSTED_PROXY_CIDRS
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL
DEEPSEEK_MODEL
TAVILY_API_KEY
TEMPORARY_PASSWORD_TTL_HOURS
PASSWORD_RESET_REQUEST_RATE_LIMIT
PASSWORD_RESET_REQUEST_RATE_LIMIT_WINDOW_SECONDS
PASSWORD_RESET_REQUEST_NOTE_MAX_LENGTH
```

生产环境必须使用互不相同的高熵 `JWT_SECRET_KEY`、`AUTH_CSRF_SECRET` 和 `RATE_LIMIT_HASH_SALT`。DeepSeek/Tavily Key 不写入镜像、Git、日志或前端变量。

## 3. 域名、HTTPS 与浏览器安全

1. 将正式域名指向反向代理，只开放 TCP 80/443；SSH 仅允许受限管理来源。
2. 使用可信 CA 证书，将 HTTP 308 跳转到 HTTPS。
3. `CORS_ALLOWED_ORIGINS` 只列正式 HTTPS Origin，不使用 `*`，不带路径。
4. CSRF Trusted Origins 与反向代理转发的协议/主机必须一致；保留 Origin 校验。
5. `AUTH_COOKIE_SECURE=true`；同站部署优先 `SameSite=lax`，没有明确跨站需求不要改为 `none`。
6. Cookie Domain 留空可获得最小主机作用域；只有经过验证的多子域需求才设置。

## 4. 持久数据与备份

- PostgreSQL 使用独立持久 volume，不与容器生命周期绑定。
- 上传文件、Chroma/vector 数据分别使用持久 volume；三类数据必须在同一维护窗口协调备份。
- 数据库每天执行加密 `pg_dump`，保留多个周期，并将副本存放到独立故障域。
- 上传与向量目录使用文件级快照或对象存储备份。
- 每季度在隔离环境执行恢复演练，核对数据库 revision、文件数量、向量可检索性与权限隔离。
- 日志启用大小/时间轮转，禁止记录请求正文、响应正文、密码、Cookie、Token 和临时密码。

## 5. 首次启动与迁移

1. 在隔离环境执行 `docker compose -f docker-compose.yml -f deploy/docker-compose.production.yml config --quiet`。
2. 备份目标数据库。
3. 运行一次 `migrate` 服务执行 `alembic upgrade head`，确认退出码为 0。
4. 启动 PostgreSQL、backend、worker、frontend/HTTPS proxy。
5. 首次管理员通过受控命令创建或授权；不要在脚本中硬编码密码。
6. 在后台设置注册邀请码，并通过可信渠道分发。

迁移失败时不得继续启动新版本应用，也不得对真实数据库执行 `downgrade` 试错。

## 6. 健康检查与验收

检查：

- `/api/health/live` 返回存活；
- `/api/health/ready` 返回 ready；
- PostgreSQL、backend、worker、frontend 均 healthy；
- 登录、注册、密码重置申请、管理员审批、强制改密和重新登录闭环；
- 普通用户无法访问 `/admin`，强制改密用户无法调用业务 API；
- 面试、知识库、历史、用量和后台任务可用；
- 电脑 1440/1024px 与手机 390/375px 无横向溢出；
- HTTPS、Secure Cookie、CSRF、CORS 和安全响应头符合预期。

## 7. 运维与回滚

- 监控容器重启、ready 状态、Worker 心跳、数据库容量、备份结果和 5xx。
- 管理员审批生成的临时密码只显示一次，必须通过可信渠道传递；工单与聊天记录不得长期留存。
- 回滚前先停止应用写入并再次备份数据库、uploads 与 Chroma。
- 应用回滚优先部署上一份已验证镜像；如果新迁移只增加兼容字段，可保留新 Schema。
- 只有在隔离环境验证 downgrade 且确认不会丢数据时才考虑 Schema 回退；否则恢复迁移前备份。
- 回滚后重新执行健康检查、登录、权限、面试和知识库验收。
