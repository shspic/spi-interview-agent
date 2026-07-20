# 备份与恢复

持久数据由 PostgreSQL、uploads 和 Chroma 三部分组成，不存在分布式强一致快照。建议维护窗口暂停写入，依次备份三者并记录同一批次时间戳。

PostgreSQL 脚本从 `PGHOST`、`PGPORT`、`PGUSER`、`PGDATABASE` 和可选 `PGPASSWORD` 读取连接，密码不进入命令参数：

```powershell
.venv\Scripts\python.exe -m scripts.backup_postgres
```

备份使用 UTC 文件名、不覆盖旧文件，运行 `pg_restore --list` 并生成 SHA-256。恢复只允许全新且名称含 `test` 或 `restore` 的数据库；目标已存在时 `createdb` 失败，不覆盖当前库：

```powershell
.venv\Scripts\python.exe -m scripts.restore_postgres `
  .\backups\postgres-20260720T000000Z.dump `
  --target-database spi_restore_test `
  --confirm RESTORE_TO_NEW_DATABASE
```

恢复后检查 `alembic_version`、readiness、文件记录与磁盘、Chroma 用户隔离和虚构检索。文件删除继续采用向量、文件、数据库的补偿式顺序；跨三种存储不声称强一致。备份、数据库、uploads 和 Chroma 都不得进入镜像或 Git。
