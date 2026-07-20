# Release Candidate 人工验收清单

状态枚举：`implemented`、`statically validated`、`runtime validated`、`skipped_environment_unavailable`。

## 自动门禁

- [ ] 后端 pytest、Mock、Retrieval、Live `--check`
- [ ] 临时 SQLite Alembic 往返
- [ ] 前端 lint、build、Playwright
- [ ] `docker compose config --quiet`
- [ ] `python -m scripts.release_preflight --dry-run`
- [ ] `git diff --check` 与敏感信息扫描
- [ ] `npm audit --omit=dev --audit-level=high` 无未接受的高风险项；当前 Axios 的 Node 侧传递依赖 `form-data 4.0.5` 报告 2 个 high，上游 `4.0.6` 已修复但本次环境无法更新锁文件，发布前必须升级并重跑审计、lint 和 build

## Docker/PostgreSQL 手动门禁

Docker daemon 不可用时全部标记 `skipped_environment_unavailable`，不能填写通过。

- [ ] build PostgreSQL/API/Worker/frontend
- [ ] 空测试库 migration 到 head
- [ ] `pytest -m postgres` 验证最终数据库状态
- [ ] Cookie/CSRF 与 BackgroundJob 容器冒烟
- [ ] 停止/重启容器后的用户、文件、Chroma、任务持久化
- [ ] pg_dump + SHA-256
- [ ] 恢复到名称含 `restore` 的全新库并核对 Alembic、表数量、用户、任务、AuthSession
- [ ] 同窗口核对 uploads 与 Chroma 副本

## 人工产品验收

- [ ] 1440、1280、1024、768、390 px 无重大布局问题
- [ ] 未登录、普通用户、管理员路由边界
- [ ] 键盘焦点、Esc 关闭、移动导航、表格滚动
- [ ] queued/running/retry/cancel/failed/timed_out/terminal 任务状态
- [ ] 错误、空状态、加载、readiness 降级
- [ ] 真实 DeepSeek 仅由用户显式确认后运行并完成人工评分

禁止事项：不得调用真实模型、部署公网、写入真实 Secret、删除 volume、使用 `down -v` 或 push。
