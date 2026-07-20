# API 与上传安全边界

上传配额在 SQLite 通过 `BEGIN IMMEDIATE` 串行，在 PostgreSQL 通过锁用户行串行；失败路径释放预留。后台任务 API 不返回 Worker ID、输入引用或完整异常，跨用户查询/取消按不存在处理，并使用 `Cache-Control: no-store`。

> 浏览器认证已迁移为 HttpOnly Cookie、可轮换 Refresh Token、服务端 AuthSession 与会话绑定 CSRF；CORS 请求头不再允许浏览器 Bearer。详见 [认证与会话安全](AUTH_SESSION_SECURITY.md)。

本文记录当前 FastAPI 后端在朋友试用阶段的安全边界。实现目标是限制不可信请求的资源消耗和数据访问范围，不等同于 WAF、恶意软件扫描或完整渗透测试。

## 1. 威胁边界

请求按以下顺序受到约束：请求 ID 与请求体上限、认证和客户端来源判断、突发限流、业务字段校验、上传数量与流式大小限制、文件名和文件类型校验、格式专项校验、用户存储预留、用户所有权校验、受控业务处理、脱敏响应与日志。

管理员不会绕过上传类型、大小、路径、所有权、字段长度、登录安全或突发限流。健康检查保持公开；直接消耗 DeepSeek/Tavily 的联调接口只允许管理员访问。

## 2. 每日额度与突发限流

每日 `UsageEvent`/`DailyUsageCounter` 仍只负责原有业务额度，数值和口径未修改。登录失败、注册、上传和改密不会写入业务用量。

突发限流使用独立的 `rate_limit_buckets` 固定窗口表：

- 匿名范围：登录、注册，按客户端 IP 的加盐 HMAC 标识计数。
- 用户范围：上传、修改密码、Chat 突发和敏感管理员写操作，按用户 ID 的加盐 HMAC 标识计数。
- SQLite `INSERT ... ON CONFLICT DO UPDATE ... WHERE` 原子增加计数，应用重启后窗口仍有效。
- 每次检查按需删除已过期窗口，不保存密码、JWT、邀请码、请求体或明文 IP。
- 429 返回 `error_code`、`scope`、`message`、`retry_after_seconds`、`reset_at`，并包含 `Retry-After` 响应头。

固定窗口的边界附近可能允许相邻两个窗口各自达到上限。这是当前 SQLite 方案的已知特性，不是每日额度替代品。

## 3. 客户端 IP 与可信代理

默认仅使用 `request.client.host`，忽略客户端自行提供的 `X-Forwarded-For` 和 `X-Real-IP`。

只有直接连接来源命中 `APP_TRUSTED_PROXY_CIDRS` 时才解析代理头。`X-Forwarded-For` 从最右侧开始跳过已配置的可信代理，遇到第一个不可信地址即作为客户端地址，防止伪造最左侧地址。非法链回退到直接连接地址。支持 IPv4 和 IPv6。

生产环境必须按真实反向代理拓扑精确配置 CIDR，不能填写宽泛公网网段。数据库和日志不输出客户端明文 IP。

## 4. 当前文件白名单

当前真实解析能力只有以下三类，本阶段没有扩大类型：

| 类型 | 扩展名 | 允许的声明 MIME | 实际内容校验 |
|---|---|---|---|
| PDF | `.pdf` | `application/pdf`、受控 `application/octet-stream` 或缺失 | `%PDF-` 签名、严格结构读取、未加密、页数上限 |
| 文本 | `.txt` | `text/plain`、受控 `application/octet-stream` 或缺失 | UTF-8/GB18030、无 NUL、非已知二进制签名、控制字节比例和单行长度 |
| Markdown | `.md` | `text/markdown`、`text/x-markdown`、`text/plain`、受控 `application/octet-stream` 或缺失 | 与文本相同 |

CSV、XLS、XLSX、PNG、JPEG、SVG、HTML、JavaScript、EXE、DLL、BAT、CMD、PS1、普通 ZIP 和未知扩展名均返回 415。扩展名、声明 MIME 与实际内容必须同时满足规则；缺失 MIME 只在内容校验通过时兼容。

## 5. 流式写入、大小和数量

上传从 `UploadFile.file` 按 1 MiB chunk 写入用户目录内的随机 `.tmp/*.part` 文件，同时累计真实字节和 SHA-256。超过 `MAX_UPLOAD_FILE_SIZE_MB` 会立即停止，不依赖 `Content-Length`，返回 413 并删除临时文件。

全局 `MAX_REQUEST_BODY_MB` 同时限制声明长度和实际接收字节。单次文件数由 `MAX_UPLOAD_FILES_PER_REQUEST` 控制，默认保持与现有前端一致的 1，配置最大值为 5。所有文件先完成暂存和校验，任何一个失败都会清理本请求的全部暂存文件，不创建 `FileRecord`，也不会创建向量。

## 6. 文件名与路径

原文件名只用于安全显示：先进行 Unicode NFKC 规范化，路径分隔符、盘符、`..`、Windows 保留名和危险双扩展名会被拒绝；控制字符替换为下划线；尾部空格和点被移除；长度受 `MAX_FILENAME_CHARS` 限制。

物理文件名始终是随机 UUID 加已验证扩展名。临时路径和最终路径都经过 `resolve`/`is_relative_to` 检查，必须位于当前用户上传目录中。同名显示文件不会覆盖。API 不返回物理路径。

下载接口为 `GET /api/files/{file_id}/download`，先按 `file_id + user_id` 查询，再验证物理路径，始终使用 `application/octet-stream` 和 `Content-Disposition: attachment`，并带 `nosniff`。删除保持相同所有权和路径校验。

## 7. 用户总存储与并发

`files.size_bytes` 保存安全扫描后的实际字节数。旧数据库初始化时，仅对路径确实位于对应用户目录内的旧记录回填实际大小。

校验完成后，上传在 SQLite `BEGIN IMMEDIATE` 事务中计算已使用空间和未过期的 `upload_reservations`。只有总量不超过 `MAX_USER_STORAGE_MB` 才创建 15 分钟预留。因此同一用户的并发请求不能在单实例/同一 SQLite 数据库上同时忽略对方的预留。最终 `FileRecord` 与预留删除在同一数据库提交中完成。

## 8. 上传补偿与幂等

流程为：限流 → 文件数 → 流式暂存 → 类型/资源校验 → 总存储预留 → 原子移动 → 创建数据库记录并释放预留。

- 暂存、类型或配额失败：删除本请求临时文件。
- 文件移动后数据库失败：回滚数据库并删除本请求已移动的最终文件。
- 清理使用限定根目录和 `missing_ok`，不存在的临时文件不会导致补偿失败。
- 不按目录名清理其他用户文件。
- 可选 `Idempotency-Key` 接受 8–128 位受控字符；相同用户、相同键、相同内容和分类返回原记录，不重复占用空间；相同键对应不同内容返回 409。
- 上传本身不建立向量。后续知识库重建失败时，文件记录保留为明确的 `failed` 状态，错误文本为受控消息，不返回底层异常。

## 9. PDF 限制

PDF 在落入最终目录前检查签名，并用当前 `pypdf` 严格打开。加密 PDF 因项目没有密码输入流程而明确拒绝；损坏结构返回 415；超过 `MAX_PDF_PAGES` 返回 413。解析器只提取文本，不执行 JavaScript、嵌入文件或外部链接。知识库预览和重建会再次执行大小和结构检查，避免已保存文件被外部篡改后绕过上传校验。

## 10. XLSX ZIP、图片、CSV 与导出

当前项目没有 XLSX、XLS、图片/OCR 或 CSV 解析器，因此这些类型在扩展名白名单阶段直接拒绝，不会进入 ZIP 解压、Pillow、OCR 或表格解析。这样不会伪造尚不存在的压缩炸弹、图片像素或文件签名防护能力。

当前也没有把用户内容导出为 CSV/XLSX 的接口，因此不存在现行 CSV Formula Injection 输出面。未来若新增上述能力，必须先实现 ZIP entry/解压大小/压缩比/路径规则、图片总像素和解压炸弹策略，以及以 `= + - @` 开头单元格的公式转义，再加入白名单。

## 11. 业务字段限制

后端 Pydantic validator 统一拒绝 NUL 和危险控制字符，保留普通中文、换行、Markdown 和代码片段，不做静默截断。当前主要默认上限：

- Chat：`MAX_CHAT_INPUT_CHARS=6000`
- Interview 回答：`MAX_INTERVIEW_ANSWER_CHARS=12000`
- JD：`MAX_JOB_DESCRIPTION_CHARS=30000`
- Profile 自我介绍：`MAX_PROFILE_TEXT_CHARS=5000`
- Agent/任务输入：`MAX_TASK_INPUT_CHARS=12000`
- 用户名：3–32 位既有规则；密码继续遵守 8 字符和 bcrypt 72 UTF-8 字节规则；邀请码继续为 6–64 位受控字符。

目标岗位名、公司、技能项、文件 ID、会话标题、管理员筛选字段、清理确认文本等也有独立上限。超限返回 422，验证响应不包含 Pydantic 的原始 `input` 值。

## 12. CORS

来源来自 `CORS_ALLOWED_ORIGINS`，不接受 `*`。启用 credentials 时仍只回显明确允许的来源。方法限制为 GET、POST、PUT、PATCH、DELETE、OPTIONS；请求头限制为 Content-Type、Idempotency-Key、X-CSRF-Token、X-Request-ID，不再允许浏览器 Bearer 注入。

开发环境统一使用 `http://localhost:5173`。生产环境未配置 `CORS_ALLOWED_ORIGINS` 时默认不允许跨域来源。恶意 Origin 不会获得 `Access-Control-Allow-Origin`。

## 13. 请求 ID、安全响应头与错误

服务端为每个请求生成 UUIDv4；只有合法客户端 UUIDv4 才会被接受，否则替换。响应通过 `X-Request-ID` 返回，并通过上下文写入 AgentRun 的可空 `request_id` 字段。

所有 API 正常和错误响应包含：

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Cache-Control: no-store`

错误响应包含 `error_code`、`message`、`request_id`、脱敏 `details`，并暂时保留 `detail` 兼容现有前端。500 总是通用消息；422 去除原始输入；受控错误会移除 Windows/常见 Unix 绝对路径和疑似 Secret 值。CSP 建议由实际前端域名对应的反向代理设置，本阶段不在 API 上添加可能破坏 Vite 的规则。

应用中间件会移除已有 `Server` 头；Uvicorn 启动时仍应使用 `--no-server-header`，因为协议服务器可能在应用返回之后自行添加该头。

## 14. 日志

请求日志只记录 request_id、method、路由 path、状态码、耗时和异常类型，不记录 query string、请求头或请求体。不得新增 Authorization、Cookie、密码、邀请码、JWT、API Key、完整 Chat/JD/简历/回答或上传内容日志。

Agent 与检索已有安全日志继续只记录 ID、计数和拒绝原因枚举，不记录跨用户非法 chunk 原文。

## 15. SQLite 迁移与局限

当前 Schema 已由 Alembic 接管。应用正常启动不再执行 `Base.metadata.create_all`、手工补列/索引或 `agent_runs` 重建；现有数据库必须先做完整结构核验和 SQLite 备份，再由显式接管命令 stamp。详细流程见 `DATABASE_MIGRATIONS.md`。

SQLite 适合当前单机朋友试用，但写锁会限制高并发，固定窗口不是精确滑动窗口，多进程部署也缺少集中式全局协调。正式生产化前应引入 Alembic、PostgreSQL，并用 Redis/Lua 或等价原子存储实现分布式限流和存储预留；不要简单把当前表计数复制到多个独立数据库。

## 16. 配置

除已有配置外，本阶段新增：

| 配置 | 含义 |
|---|---|
| `APP_ENVIRONMENT` | development/test/production |
| `CORS_ALLOWED_ORIGINS` | 逗号分隔明确来源 |
| `APP_TRUSTED_PROXY_CIDRS` | 逗号分隔可信直连代理网段 |
| `RATE_LIMIT_HASH_SALT` | HMAC 盐；未设置时回退 JWT Secret，不能使用 `change-me` |
| `MAX_REQUEST_BODY_MB` | 实际请求体总上限 |
| `MAX_UPLOAD_FILE_SIZE_MB` | 单文件实际字节上限 |
| `MAX_UPLOAD_FILES_PER_REQUEST` | 单次文件数上限 |
| `MAX_USER_STORAGE_MB` | 用户文件总量上限 |
| `MAX_PDF_PAGES` | PDF 页数上限 |
| `MAX_TEXT_LINE_CHARS` | 文本单行字符上限 |
| `MAX_FILENAME_CHARS` | 显示文件名上限 |
| `MAX_*_CHARS` | 各业务输入字符上限 |
| `*_RATE_LIMIT_ATTEMPTS` | 对应范围窗口次数 |
| `*_RATE_LIMIT_WINDOW_SECONDS` | 对应窗口秒数 |

所有数值有有限范围，非法 CIDR、Origin、环境名或相互冲突的请求体/文件大小在配置构造时受控失败。`.env.example` 只提供被代码拒绝的 Secret 占位值；不要修改或提交真实 `.env`。

## 17. 测试

安全测试只使用 TestClient、临时 SQLite 和临时上传目录，不访问网络、真实数据库、真实上传目录、DeepSeek、Tavily、Embedding 或 Chroma：

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q tests\test_api_security.py
.venv\Scripts\python.exe -m pytest -q
```

完整发布前还应运行 Mock 评估、Retrieval 单组、前端 lint/build 和 Git 敏感信息扫描。当前未执行真实恶意样本沙箱、杀毒扫描或全量 Playwright。
