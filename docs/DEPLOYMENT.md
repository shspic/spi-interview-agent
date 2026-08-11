# 通用 Linux 服务器部署与 Release 流程

本项目采用同站点架构：浏览器只访问 `https://<域名>/` 与 `/api/`。PostgreSQL 和 Worker 不映射宿主机公网端口。本文不代替云平台、DNS 或证书供应商文档，也不会自动购买或部署任何资源。

> 当前实例：<https://43.153.181.237:8443/>。2026-08-11 已通过真实浏览器和匿名接口验证登录页、TLS、`/api/health/live` 与 `/api/health/ready`；readiness 显示 PostgreSQL、Schema、存储、任务系统和 Worker 均就绪。该结果证明单机公网实例可访问，不等于大规模并发、高可用、备份恢复或全部登录后业务已验收。当前使用 IP 地址证书，应持续监控自动续期；仓库不记录证书私钥或真实 Secret。

## 1. Preflight

1. 由用户按 Docker 官方文档安装受支持的 Docker Engine 与 Compose 插件。
2. 克隆仓库并检出待发布 commit；确认 `git status --short` 与发布清单一致。
3. 在仓库外创建权限为 `600` 的生产环境文件，可从 `deploy/.env.production.example` 复制；用 Secret Manager 或强随机值替换全部占位符。
4. 不设置 `AUTH_COOKIE_DOMAIN`，同站点部署使用 host-only Cookie；`CORS_ALLOWED_ORIGINS` 只填最终 HTTPS Origin。
5. 运行：

```bash
docker version
docker compose version
docker compose --env-file /secure/path/spi.env -f docker-compose.yml -f deploy/docker-compose.production.yml config --quiet
docker compose --env-file /secure/path/spi.env -f docker-compose.yml -f deploy/docker-compose.production.yml run --rm backend python -m scripts.release_preflight
```

任何 `FAIL` 都必须先处理。Preflight 只读，不迁移、不建管理员、不调用模型。

## 2. Deploy

```bash
docker compose --env-file /secure/path/spi.env -f docker-compose.yml -f deploy/docker-compose.production.yml build
docker compose --env-file /secure/path/spi.env -f docker-compose.yml -f deploy/docker-compose.production.yml up -d postgres
docker compose --env-file /secure/path/spi.env -f docker-compose.yml -f deploy/docker-compose.production.yml run --rm migrate
docker compose --env-file /secure/path/spi.env -f docker-compose.yml -f deploy/docker-compose.production.yml up -d backend worker frontend
docker compose --env-file /secure/path/spi.env -f docker-compose.yml -f deploy/docker-compose.production.yml ps
```

反向代理使用 `deploy/nginx-https.conf.template`，由运维注入域名与证书路径后执行 Nginx 自检。先确认 HTTPS，再考虑开启 HSTS。不要把渲染后的证书路径或生产配置提交到 Git。

## 3. 初始化管理员与邀请码

只在目标环境显式执行一次，命令会交互读取信息，不要把密码放进 shell history：

```bash
docker compose --env-file /secure/path/spi.env exec backend python -m scripts.set_admin
```

邀请码优先通过受保护的 `/admin` 页面设置；修改后旧邀请码立即失效。管理员不应使用 `admin`、`administrator` 等通用用户名。

## 4. Post-deploy smoke

```bash
curl --fail --silent https://<域名>/healthz
curl --fail --silent https://<域名>/api/health/live
curl --fail --silent https://<域名>/api/health/ready
docker compose --env-file /secure/path/spi.env logs --tail=200 backend worker frontend postgres
```

在浏览器开发者工具中确认：Cookie 带 `Secure`、`HttpOnly`（access/refresh）、预期 `SameSite=Lax`；写请求带 CSRF header；响应没有 `Server` 版本；API 返回 `Cache-Control: no-store`。再用虚构账号完成注册、TXT 上传、索引任务、面试任务和注销。

## 5. 三类持久数据与备份

必须在同一维护窗口协调备份 PostgreSQL、`uploads` volume 和 `chroma` volume。`pg_dump` 不包含后两类数据。

```bash
docker compose --env-file /secure/path/spi.env exec -e PGHOST=postgres -e PGPORT=5432 -e PGUSER=spi_app -e PGDATABASE=spi_app backend python -m scripts.backup_postgres
```

备份工具生成 UTC 时间戳 custom dump 与 SHA-256。恢复演练只能指向名称包含 `test` 或 `restore` 的全新数据库：

```bash
python -m scripts.restore_postgres backups/postgres-<UTC>.dump --target-database spi_restore_test --confirm RESTORE_TO_NEW_DATABASE
```

同时以只读挂载方式恢复 uploads/Chroma 副本，核对测试用户、文件数、BackgroundJob、AuthSession、向量集合与 Alembic head。禁止对未知数据库执行恢复。

## 6. 升级、回滚、停止

升级前先备份并记录当前 image digest/commit。构建新镜像，先执行 migrate，再逐个重启 API、Worker、frontend。回滚代码时必须确认数据库迁移是否向后兼容；不明确时停止并从已验证备份恢复到新实例。

```bash
docker compose --env-file /secure/path/spi.env stop frontend worker backend
docker compose --env-file /secure/path/spi.env down
```

永远不要使用 `docker compose down -v`。停止前观察运行中任务；Worker 允许宽限退出，过期 lease 会由后续 Worker 恢复。

## 7. 日常运维

- 每日观察 readiness、Worker 心跳、失败/超时任务、PostgreSQL 与 volume 磁盘占用。
- 定期运行备份和独立 restore test；只保留已验证可恢复的备份链。
- 通过 BackgroundJob 执行保留期清理，不绕过预览与审计。
- Secret 轮换顺序：新增 Secret、滚动重启、验证、撤销旧 Secret。JWT/CSRF Secret 轮换会使现有会话失效，应提前通知。
- 生产环境不得开启旧 Schema patch、旧同步长任务兼容或调试模式。
