# 最终架构图

以下 Mermaid 源码可直接在 GitHub Markdown 渲染。外部 DeepSeek/Tavily 只有在显式配置和业务需要时访问；默认测试不联网。

## 1. 系统架构

```mermaid
flowchart LR
    B["Browser"] -->|"HTTPS same origin"| RP["Reverse proxy"]
    RP --> FE["React frontend"]
    RP -->|"/api"| API["FastAPI"]
    API --> PG[("PostgreSQL")]
    API --> UP[("uploads volume")]
    API --> CH[("Chroma volume")]
    API -->|"create BackgroundJob"| PG
    WK["Worker"] -->|"claim / heartbeat / result"| PG
    WK --> UP
    WK --> CH
    WK -. "explicit live call" .-> DS["DeepSeek"]
    WK -. "optional web search" .-> TV["Tavily"]
```

## 2. RAG 流程

```mermaid
flowchart TD
    U["上传 PDF / TXT / MD"] --> V["类型、大小、文件名、配额校验"]
    V --> P["解析文本"] --> C["chunk"] --> E["BGE embedding"] --> CH[("Chroma")]
    Q["用户问题"] --> QA["Query Analysis"]
    QA --> MQ["有限多查询"] --> CH
    CH --> RRF["RRF 候选融合"]
    RRF --> OWN["FileRecord 所有权校验"]
    OWN --> CONF["Confidence"] --> ES["Evidence Set"]
    ES --> AG["Agent"]
    ES -->|"不足或冲突"| SAFE["保守表达与提示"] --> AG
```

## 3. Agent 流程

```mermaid
flowchart LR
    BJ["BackgroundJob"] --> S["Supervisor"]
    S --> EV["Evidence Agent"]
    EV --> IN["Interviewer Agent"]
    IN --> EA["Evaluation Agent"]
    EA --> IM["Improvement Agent"]
    IM --> RE["Resume Agent"]
    EV & IN & EA & IM & RE --> AR[("AgentRun")]
    AR --> S
    S -->|"progress / terminal result"| BJ
```

每个 Agent 只获得当前阶段必要的结构化上下文。`AgentRun` 保存可审计元数据，不在普通用户 UI 展示内部 Prompt、节点、payload 或执行 trace。

## 4. 认证流程

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as FastAPI
    participant DB as PostgreSQL
    B->>A: GET /auth/csrf
    A-->>B: CSRF Cookie
    B->>A: Login + X-CSRF-Token
    A->>DB: Create AuthSession
    A-->>B: Access Cookie + Refresh Cookie
    B->>A: Authenticated request
    A->>DB: Validate session and user
    B->>A: Refresh + CSRF + Origin
    A->>DB: Atomic rotation
    A-->>B: Rotated cookies
    B->>A: Logout / Logout All
    A->>DB: Revoke session(s)
    A-->>B: Clear cookies
```

## 5. 部署图

```mermaid
flowchart TB
    I["Internet"] -->|"HTTPS"| N["Host Nginx / platform proxy"]
    N --> F["frontend container :8080"]
    F --> A["API container :8000"]
    W["Worker container"] --> P[("PostgreSQL volume")]
    A --> P
    A & W --> U[("uploads volume")]
    A & W --> C[("Chroma volume")]
    BK["Backup job / operator"] --> P
    BK --> U
    BK --> C
    BK --> D[("verified backups")]
```

PostgreSQL 和 Worker 不暴露公网端口。API 也不直接对公网服务；外部代理只连接 loopback 上的 frontend 容器映射。
