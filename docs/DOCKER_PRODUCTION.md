# 本地生产化 Docker

Compose 包含 `postgres`、一次性 `migrate`、`backend`、`worker` 和 `frontend`。API/Worker 复用非 root Python 镜像；前端由非特权 Nginx 提供静态文件并同源代理 `/api`。

```powershell
$env:POSTGRES_PASSWORD="<随机值>"
$env:JWT_SECRET_KEY="<随机值>"
$env:AUTH_CSRF_SECRET="<另一个随机值>"
$env:REGISTRATION_INVITE_CODE="<随机值>"
$env:RATE_LIMIT_HASH_SALT="<随机值>"
docker compose config
docker compose build
docker compose up -d
```

只有前端绑定 `127.0.0.1:8080`；PostgreSQL/API 不映射宿主端口。migration 成功后 API/Worker 才启动。持久卷为 `postgres_data`、`uploads`、`chroma`、`backups`。

`docker compose down` 保留数据。不要随意执行 `down -v`，它会删除持久卷。本地 Compose 使用 HTTP 和 `Secure=false`；公网部署前必须启用生产模式、HTTPS、Secure Cookie、可信代理和独立 Secret 管理。

`/api/health/live` 不查数据库；`/api/health/ready` 检查认证、数据库、Alembic head、持久目录和任务表。Worker 用数据库 heartbeat 健康检查。
