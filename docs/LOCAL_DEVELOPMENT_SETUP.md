# 本地开发安全初始化

本地不设置 `DATABASE_URL` 时继续使用 `SQLITE_DB_PATH`。验证 PostgreSQL 时显式设置 `DATABASE_URL=postgresql+psycopg://...`；生产禁止回退 SQLite。后台任务需另启 `.venv\Scripts\python.exe -m app.worker`，SQLite 只允许一个 Worker。

## 1. 首次安装

本地统一使用前端 `http://localhost:5173`、后端 `http://localhost:8000`。Uvicorn 可以监听 `127.0.0.1`，但浏览器地址和 `VITE_API_BASE_URL` 应使用 `localhost`，不要在同一次会话中混用两个主机名。

```powershell
cd D:\spir\NO1_agent\backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

cd D:\spir\NO1_agent\frontend
npm install
```

## 2. 安全初始化 `.env`

旧 `.env` 没有认证阶段新增的 `JWT_SECRET_KEY` 和 `AUTH_CSRF_SECRET` 时，后端过去可以启动，但首次请求 `/api/auth/csrf` 才返回“认证服务尚未配置”。现在运行：

```powershell
cd D:\spir\NO1_agent\backend
.venv\Scripts\python.exe -m scripts.bootstrap_local_env
```

工具在文件不存在时基于 `.env.example` 创建 `.env`；已有文件只追加缺失字段。JWT、CSRF、邀请码和限流盐使用独立的密码学安全随机值。工具不显示值、不覆盖已有值，重复运行不会轮换 Secret，并拒绝修改声明为 production 的配置。`.env` 已被 Git 忽略，不要复制到文档或提交。

只检查就绪状态：

```powershell
.venv\Scripts\python.exe -m scripts.check_readiness
```

生产环境必须显式提供 Secret、HTTPS 和 `AUTH_COOKIE_SECURE=true`；不会自动生成临时 Secret。

## 3. 数据库初始化与接管

新数据库：

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
```

现有 SQLite 先只读核验：

```powershell
.venv\Scripts\python.exe -m scripts.adopt_existing_database
```

完全匹配时，用 `--apply` 先备份再 stamp。若只存在本项目已识别的三个旧外键和文件大小检查约束差异，可显式运行：

```powershell
.venv\Scripts\python.exe -m scripts.adopt_existing_database --apply --repair-known-legacy
```

任何额外表、列、类型、唯一约束、索引、外键或检查约束差异都会拒绝接管。不要删除或重命名 `backend/data`、`backend/data/uploads`、`backend/data/chroma_db`；不要对真实数据库执行 downgrade。

## 4. 启动与停止

后端统一入口会初始化本地配置、安全准备数据库，然后启动 Uvicorn：

```powershell
cd D:\spir\NO1_agent\backend
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend_dev.ps1
```

另开终端启动前端：

```powershell
cd D:\spir\NO1_agent\frontend
npm run dev
```

在各终端按 `Ctrl+C` 停止。脚本不会清空数据库、上传或 Chroma，也不会终止已占用端口的未知进程。

## 5. Cookie、CSRF 与旧浏览器状态

打开 `/api/health` 应看到 `status=ok`、`auth_ready=true`、`schema_ready=true`；`/api/auth/csrf` 应设置 `spi_csrf`。浏览器请求必须启用 credentials，写请求携带 `X-CSRF-Token`。旧版本如在 localStorage 中留下认证 Token，可以通过浏览器开发者工具清除；新版本不会读取它。

常见错误：401 表示需要重新登录；403 通常是 CSRF、Origin 或权限拒绝；429 是持久化限流；CORS 错误先检查是否统一使用 `localhost` 及 `CORS_ALLOWED_ORIGINS=http://localhost:5173`。

## 6. 管理员入口

管理员与普通用户共用登录页。登录用户摘要的 `is_admin=true` 时，右上角头像菜单显示“管理后台”；前端内部页面状态名为 `admin`，当前不是独立 URL 路由。页面本身再次检查角色，所有 `/api/admin/*` 接口由后端执行最终 401/403 校验，写操作继续携带 CSRF。

先注册普通账号，再在后端执行现有的显式、默认 dry-run CLI：

```powershell
.venv\Scripts\python.exe -m scripts.set_admin --username <用户名>
.venv\Scripts\python.exe -m scripts.set_admin --username <用户名> --apply
```

工具不创建默认密码，不输出密码，并写入管理员审计日志。不要擅自提升不明确的账号。
