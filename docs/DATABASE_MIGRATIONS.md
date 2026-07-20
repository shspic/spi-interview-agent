# 数据库迁移

当前 head 为 `20260720_0002`。`0001` 保留已接管业务基线，`0002` 增加后台任务、Worker、维护表和 Resume 幂等字段，并修复 PostgreSQL 活跃岗位部分唯一索引。空 SQLite/PostgreSQL 必须通过 `alembic upgrade head` 初始化，禁止用 `Base.metadata.create_all()` 绕过。

## 1. 接管边界

应用正常启动不再执行 `Base.metadata.create_all`、手工 `ALTER TABLE`、索引补丁或 `agent_runs` 重建。正式 Schema 由 Alembic 接管。旧函数只保留给显式兼容路径和隔离测试，默认关闭，production 禁止通过 `ENABLE_LEGACY_SCHEMA_PATCHES` 启用。

目录为 `backend/alembic.ini`、`backend/alembic/env.py`、`backend/alembic/script.py.mako` 和 `backend/alembic/versions/`。迁移直接使用当前 `Base.metadata` 做后续差异检测，不复制模型；revision 文件本身包含可审查的显式 `op.create_table`、约束和索引，不调用 `create_all`。

## 2. 基线

基线 revision 是 `20260720_0001`，覆盖认证阶段完成后的 20 张正式表，包括用户、文件、历史、目标岗位、面试会话/轮次/改进任务、AgentRun、简历描述、用量、管理员审计、删除日志、注册设置、限流、上传预留、AuthSession 和认证事件。SQLite 在线迁移启用 batch mode；数据库 URL 来自 `ALEMBIC_DATABASE_URL`（受控测试覆盖）、`DATABASE_URL` 或现有 `SQLITE_DB_PATH`，`alembic.ini` 不保存真实凭据。

## 3. 常用命令

```powershell
cd D:\spir\NO1_agent\backend
.venv\Scripts\python.exe -m alembic current
.venv\Scripts\python.exe -m alembic heads
.venv\Scripts\python.exe -m alembic history
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic downgrade -1
```

只在临时或已确认可丢弃的数据库执行 downgrade。生产环境不自动执行未知迁移，本地启动脚本会显式运行安全准备命令。

## 4. 新数据库

对不存在或无业务表的 SQLite 运行 `alembic upgrade head`。升级后应用检查数据库 revision 必须等于代码 head；未迁移、落后或未知 revision 都会受控拒绝启动。`/api/health` 只公开 `schema_ready` 布尔值，不公开 URL 或 revision。

## 5. 现有数据库接管

`python -m scripts.adopt_existing_database` 默认 dry-run。它比较全部表和列、SQLite 类型等价性、nullable、必要默认值、唯一约束、命名索引、关键外键与命名检查约束；不是只看表名。

完全匹配后 `--apply` 使用 SQLite backup API 创建一致性备份，再执行 `stamp head` 并复查 current。当前历史库可能只有四个已知差异：三个用户外键缺少级联、文件表缺少大小检查。只有同时传入 `--apply --repair-known-legacy`，且差异集合严格相等时，才会先备份、用 batch mode 重建三张子表、再次完整核验并 stamp；出现任何额外差异都停止。

## 6. 备份与恢复

独立备份命令：

```powershell
.venv\Scripts\python.exe -m scripts.backup_sqlite
```

备份写入 Git ignored 的 `backend/backups`，文件名含 UTC 时间戳，不覆盖旧文件，并运行 SQLite integrity check。恢复时先停止后端，保留当前数据库副本，再由维护者把选定备份复制到配置指向的位置并运行 `alembic current` 和只读完整性检查；不要在服务运行时直接覆盖数据库。

## 7. 测试与生产注意事项

迁移测试使用临时 SQLite，验证空库 upgrade、20 张表、索引/约束/外键、downgrade/re-upgrade、Schema 拒绝和备份可读性。测试通过 `SKIP_DOTENV=1` 与内存/临时 URL，不读取真实 `.env` 或开发数据库。

生产执行 upgrade 前必须有可恢复备份和维护窗口；不得把密码放入 `alembic.ini` 或日志。当前仍是单机 SQLite。未来迁移 PostgreSQL 时应新增独立 revision 和数据验证流程，不复用 SQLite 文件级假设。
