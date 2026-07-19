# 认证与会话安全

## 1. 迁移目标

浏览器不再接收或保存 JWT。旧流程把 Access Token 写入 `localStorage` 并注入 `Authorization: Bearer`，任何能在页面执行的脚本都可能读取它，而且服务端无法按设备可靠撤销。新流程只使用服务端会话和 Cookie：Access、Refresh 都是 `HttpOnly`，前端只能维护安全的用户摘要。

## 2. Token 与会话职责

- Access Token 是默认 15 分钟的 HS256 JWT，只包含 `sub`、`session_id`、`token_type=access`、`token_version`、`iat`、`exp`、`jti`。签名、有效期通过后仍必须查询 `AuthSession`。
- Refresh Token 是 `session_uuid.random_secret` 形式的高熵随机值，有效期默认 7 天。数据库只保存 SHA-256 哈希，每次刷新后原子轮换。
- `AuthSession` 保存 UUID、用户、Refresh/CSRF 哈希、创建/访问/过期/撤销时间、撤销原因和 Token 版本；不保存明文 Token、Cookie、完整 User-Agent 或 IP。
- 一个会话只属于一个用户。用户删除时通过外键级联删除会话。

## 3. Cookie

| Cookie | Path | HttpOnly | 默认 SameSite | 用途 |
|---|---|---:|---|---|
| `spi_access` | `/api` | 是 | `lax` | 短期 Access JWT |
| `spi_refresh` | `/api/auth` | 是 | `lax` | 刷新、退出所需 Refresh Token |
| `spi_csrf` | `/` | 否 | `lax` | 前端复制到 `X-CSRF-Token` |

设置与删除使用完全相同的名称、Path、Domain、Secure 和 SameSite。生产环境必须使用 HTTPS 并配置 `AUTH_COOKIE_SECURE=true`；`SameSite=None` 也强制要求 Secure。Cookie Domain 默认留空，不扩大到父域。

## 4. CSRF 与来源校验

`GET /api/auth/csrf` 初始化登录前 Token。Token 含绑定值、过期时间和随机数，并使用 `AUTH_CSRF_SECRET` 做 HMAC-SHA256 签名。登录后绑定值改为 AuthSession UUID 的 HMAC，不向 JavaScript 暴露数据库会话主键；数据库保存完整 CSRF Token 的 SHA-256 哈希。

所有 POST、PUT、PATCH、DELETE 必须同时满足：Cookie 与 `X-CSRF-Token` 完全相同、签名和有效期有效、会话绑定与数据库哈希一致。登录和注册使用短期 `preauth` 绑定；Refresh、Logout 和所有已认证写接口使用会话绑定。GET、HEAD、OPTIONS 不做状态修改，也不要求 CSRF。

危险请求还会优先验证 `Origin`，缺失时检查 `Referer`。只接受明确的 `CORS_ALLOWED_ORIGINS` 或请求同源。普通 `X-Forwarded-*` 头不会直接参与判定；代理来源仍由现有受信代理设置处理。来源检查是纵深防御，不能代替 CSRF Token。

## 5. 认证流程

1. 页面加载先获取 CSRF，再请求 `/api/auth/me`。
2. 注册验证邀请码但不自动登录，也不返回 Token；前端随后执行登录。
3. 登录成功创建 AuthSession，设置三种 Cookie，只返回用户安全摘要。
4. `/api/auth/me` 只验证当前 Access 和服务端会话，不触发刷新，并返回 `Cache-Control: no-store`。
5. Access 过期时，前端通过共享 Promise 发起一次 `/api/auth/refresh`。服务端原子替换 Refresh 哈希并轮换 CSRF，再设置新 Access。
6. Logout 仅撤销当前会话并清 Cookie；重复、无 Cookie Logout 幂等。
7. Logout All 撤销当前用户全部活动会话并清当前浏览器 Cookie。

## 6. Refresh 并发与前端重试

Refresh 使用带旧哈希条件的数据库 `UPDATE`。同一个旧 Token 即使并发到达，也至多一个请求更新一行并成功；其余返回统一 401，不创建新 AuthSession、不计业务额度，也不撤销其他设备。

前端所有请求启用 `withCredentials`。多个 401 共享一个刷新 Promise。刷新成功后仅自动重放 GET、HEAD、OPTIONS；上传、Chat、Agent、Evaluation 等非幂等请求不会自动重放，避免重复业务任务或额度消耗。CSRF 403 会先重新获取 Token，但非幂等原请求同样不自动重放。刷新失败时进入未登录状态。

## 7. 撤销事件

- 修改密码：撤销该用户全部会话、清当前 Cookie、要求重新登录。
- 管理员重置密码：撤销目标用户全部会话。
- 禁用账号：撤销目标用户全部会话；重新启用不会恢复旧会话。
- 删除账号：AuthSession 级联删除。
- Logout：只撤销当前会话。
- Logout All：撤销当前用户全部会话。
- 达到默认 5 个活动会话时：按创建时间稳定撤销最旧会话后允许新登录。

当前“个人业务数据清理”明确保留账号，因此不撤销会话；管理员“删除用户”会删除账号并清理会话。

## 8. Bearer 策略

浏览器和外部 API 默认都不接受 Bearer。登录响应不再暴露 JWT；只有 Cookie 可以进入会话认证。请求同时带 Cookie 与 Authorization 会以认证来源冲突返回 401。当前没有机器客户端需求，因此没有保留兼容开关。

## 9. CORS

CORS 启用 credentials，但 origins 必须是明确列表，不能使用 `*`。允许的认证相关请求头为 `Content-Type`、`X-CSRF-Token`、`Idempotency-Key` 和 `X-Request-ID`，不再允许浏览器 Bearer 注入。推荐生产环境通过同站点反向代理提供 `/api`，减少跨站 Cookie 兼容问题。

## 10. 配置

```env
AUTH_ACCESS_TOKEN_MINUTES=15
AUTH_REFRESH_TOKEN_DAYS=7
AUTH_MAX_ACTIVE_SESSIONS=5
AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=lax
AUTH_COOKIE_DOMAIN=
AUTH_ACCESS_COOKIE_NAME=spi_access
AUTH_REFRESH_COOKIE_NAME=spi_refresh
AUTH_CSRF_COOKIE_NAME=spi_csrf
AUTH_CSRF_SECRET=change-me
AUTH_REQUIRE_ORIGIN_CHECK=true
```

本地 HTTP 开发可显式使用 `Secure=false`。开发环境在未设置 `AUTH_CSRF_SECRET` 时为兼容旧 `.env` 会回退到 `JWT_SECRET_KEY`；生产环境启动校验要求独立 CSRF Secret、Secure Cookie 和明确 CORS origins。不要提交真实 `.env`。

## 11. 安全事件与日志

`auth_security_events` 记录 `login_success`、`login_failed`、`session_refreshed`、`logout`、`logout_all`、`password_changed`、`admin_password_reset`、`account_disabled`、`session_revoked`、`csrf_rejected` 等脱敏事件。只保存用户 ID、事件、结果、会话 ID 的 12 位哈希和时间，不保存密码、邀请码、Token、Cookie、CSRF、完整 IP 或 User-Agent。安全事件纳入现有 `DATA_RETENTION_DAYS` 预览与过期清理，不改变当前保留天数；正式上线前可再根据合规要求拆分独立周期和访问权限。

## 12. SQLite 增量兼容与局限

当前继续使用 `Base.metadata.create_all`：旧库启动时只新增 `auth_sessions`、`auth_security_events` 及索引，不重建用户表、不删除旧数据。旧 JWT 缺少 `session_id`、`token_type` 和 `jti`，Cookie 认证也不读取 Authorization，因此立即失效。

已知局限：SQLite 写锁适合当前单机阶段，但不是多实例会话协调方案；本阶段没有设备管理列表、复杂风控、OAuth 或分布式会话存储。下一阶段数据库结构变更必须由 Alembic 接管；若未来迁移 PostgreSQL/多实例，再评估集中式撤销与限流，不应在本阶段提前引入 Redis。
