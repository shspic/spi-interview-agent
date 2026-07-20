# PostgreSQL 生产数据库

本地开发和普通 `pytest` 默认使用 SQLite；生产与显式集成测试使用 PostgreSQL；Alembic 是唯一正式 Schema 管理入口。`DATABASE_URL` 优先于兼容变量 `SQLITE_DB_PATH`，开发环境未设置时才回退 SQLite；`APP_ENVIRONMENT=production` 必须显式配置：

```env
DATABASE_URL=postgresql+psycopg://app_user:change-me@postgres:5432/spi_app
```

驱动固定为 Psycopg 3。健康响应只报告数据库类型与 ready，不输出完整 URL。

事务兼容策略：Refresh 轮换使用旧 token hash 条件更新；Usage 用方言对应的 upsert 创建计数行，并在 PostgreSQL 锁定事件/计数行；RateLimit 使用带条件增量的 upsert；UploadReservation 在 SQLite 使用 `BEGIN IMMEDIATE`、在 PostgreSQL 锁用户行；任务 claim 在 PostgreSQL 使用 `FOR UPDATE SKIP LOCKED`，SQLite 仅允许一个 Worker。活跃岗位在两种方言均使用部分唯一索引。

现有业务时间为兼容已有 SQLite 数据继续保存规范 ISO 文本：认证和后台任务使用带 `+00:00` 的 UTC；日额度按 `APP_TIMEZONE` 计算并保存偏移；限流窗口使用 Unix 秒。Boolean/JSON 由 SQLAlchemy 映射。

显式 PostgreSQL 测试要求数据库名包含 `test`，测试在随机 Schema 执行 migration，结束只删除该 Schema：

```powershell
$env:TEST_POSTGRES_DATABASE_URL="postgresql+psycopg://test_user:change-me@localhost:5432/spi_test"
.venv\Scripts\python.exe -m pytest -m postgres
```

未配置时测试明确 skipped。SQLite 仅适合本地单 Worker；本阶段没有 Redis 或分布式强一致存储。
