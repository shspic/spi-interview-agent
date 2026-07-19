# SPI面试Agent

SPI面试Agent 是一个面向 AI 应用开发实习求职场景的智能面试训练与岗位匹配系统。

项目基于 FastAPI、React、SQLite、ChromaDB、DeepSeek、Tavily 和 LangGraph 构建，支持本地知识库管理、RAG 问答、岗位 JD 分析、模拟面试评价、联网搜索增强和 Agent 自动路由。

---

## 1. 项目定位

本项目主要解决 AI 应用开发实习准备中的三个问题：

1. 如何基于个人项目资料和学习笔记，进行有依据的面试问答训练；
2. 如何结合岗位 JD 分析自己与目标岗位的匹配度；
3. 如何通过 Agent 自动判断问题是否需要本地知识库、联网搜索或混合检索。

系统强调两点：

* 用户个人经历、项目经历和能力判断必须基于本地知识库；
* 当前岗位趋势、招聘要求和技术市场信息可以通过 Tavily 联网搜索补充。

---

## 2. 核心功能

### 2.1 知识库管理

支持上传：

* Markdown
* TXT
* PDF

系统会解析文档内容，切分为文本片段，并通过 embedding 模型写入 ChromaDB 向量库。

知识库页面支持：

* 文件上传
* 文件列表查看
* 文件删除
* 知识库状态查看
* 知识库索引重建

---

### 2.2 RAG 自由问答

用户可以基于本地知识库提问。

系统流程：

1. 用户输入问题；
2. 后端从 ChromaDB 检索相关片段；
3. 将相关片段与问题一起发送给 DeepSeek；
4. 返回基于本地知识库的回答；
5. 保存历史记录和引用来源。

---

### 2.3 岗位 JD 分析

用户可以粘贴岗位 JD，系统会结合本地知识库分析：

* 岗位核心要求
* 用户当前匹配点
* 用户短板
* 简历优化建议
* 面试准备建议

岗位分析支持可选 Tavily 联网搜索，用于补充当前岗位市场信息和技术趋势。

---

### 2.4 模拟面试

系统支持根据用户资料和岗位方向生成模拟面试问题，并对用户回答进行评价。

评价维度包括：

* 总分
* 内容相关性
* 个人经历匹配度
* 技术准确性
* 表达结构
* 风险控制
* 主要问题
* 改进建议
* 参考回答

---

### 2.5 LangGraph Agent

Agent 页面支持四种模式：

* auto：由 LLM Router 自动判断路线；
* local：只使用本地知识库；
* web：只使用 Tavily 联网搜索；
* hybrid：同时使用本地知识库和联网搜索。

Agent 工作流：

1. LLM Router 判断问题应该走 local / web / hybrid；
2. local 路线检索 ChromaDB 本地知识库；
3. web 路线调用 Tavily 联网搜索；
4. hybrid 路线同时使用本地知识库和联网搜索；
5. DeepSeek 生成最终回答；
6. 保存路由原因、执行轨迹、引用来源和历史记录。

---

### 2.6 历史记录

系统支持查看：

* 自由问答历史
* 岗位分析历史
* LangGraph Agent 历史
* 模拟面试历史

Agent 历史记录会保存：

* 用户问题
* Agent 回答
* 实际路由
* 路由原因
* 执行轨迹
* 本地知识库引用来源
* 联网搜索来源

---

### 2.7 系统状态自检

系统状态页用于检查：

* 后端服务状态
* DeepSeek API Key 是否配置
* Tavily API Key 是否配置
* 数据库记录数量
* 知识库文件数量
* 向量片段数量
* 索引状态

---

## 3. 技术栈

### 后端

* FastAPI
* Uvicorn
* SQLite
* SQLAlchemy
* ChromaDB
* sentence-transformers
* pypdf
* DeepSeek API
* Tavily API
* LangGraph

### 前端

* React
* Vite
* Axios
* JavaScript
* CSS

### AI / RAG / Agent

* RAG
* Embedding
* Vector Store
* LLM Router
* Tool Routing
* LangGraph Workflow
* Web Search Augmentation

---

## 4. 项目结构

```text
NO1_agent/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── prompts/
│   │   ├── services/
│   │   └── main.py
│   ├── data/
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── pages/
│   │   ├── utils/
│   │   ├── App.jsx
│   │   └── index.css
│   ├── package.json
│   └── vite.config.js
├── docs/
├── README.md
├── .gitignore
├── AGENTS.md
└── CLAUDE.md
```

---

## 5. 后端启动

进入后端目录：

```powershell
cd D:\spir\NO1_agent\backend
```

激活虚拟环境：

```powershell
.\.venv\Scripts\activate
```

安装依赖：

```powershell
pip install -r requirements.txt
```

启动后端：

```powershell
uvicorn app.main:app --reload
```

后端地址：

```text
http://127.0.0.1:8000
```

Swagger 文档：

```text
http://127.0.0.1:8000/docs
```

---

## 6. 前端启动

进入前端目录：

```powershell
cd D:\spir\NO1_agent\frontend
```

安装依赖：

```powershell
npm install
```

启动前端：

```powershell
npm run dev
```

前端地址：

```text
http://localhost:5173
```

---

## 7. 环境变量

后端需要创建：

```text
backend/.env
```

参考：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

TAVILY_API_KEY=your_tavily_api_key

CHROMA_PERSIST_DIR=data/chroma_db
UPLOAD_DIR=data/uploads
SQLITE_DB_PATH=data/app.db
EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5
```

注意：

```text
backend/.env 不应提交到 Git。
```

---

## 8. 推荐演示流程

1. 启动后端；
2. 启动前端；
3. 打开系统状态页，确认后端、DeepSeek、Tavily、知识库状态正常；
4. 上传个人项目资料或技术笔记；
5. 重建知识库索引；
6. 进入自由问答页面，测试本地 RAG 问答；
7. 进入岗位分析页面，粘贴岗位 JD 并启用联网搜索；
8. 进入模拟面试页面，生成问题并评价回答；
9. 进入 LangGraph Agent 页面，测试 auto / local / web / hybrid；
10. 进入历史记录页面，查看问答、岗位分析、Agent 执行轨迹和模拟面试记录。

---

## 9. 项目亮点

### RAG 亮点

* 支持多格式文档上传与解析；
* 使用 ChromaDB 管理本地向量库；
* 回答时保留引用来源；
* 明确限制模型不能编造用户经历。

### Agent 亮点

* 使用 LangGraph 构建 Agent 工作流；
* 使用 LLM Router 自动判断 local / web / hybrid；
* 支持 Tavily 联网搜索；
* 保存路由原因和执行轨迹；
* 可在历史记录中查看 Agent 的工具调用过程。

### 工程亮点

* 前后端分离；
* FastAPI 提供结构化接口；
* React 构建多页面交互；
* SQLite 保存业务记录；
* 系统状态页用于自检；
* `.env` 与本地数据不进入 Git。

---

## 10. 当前限制

* 当前项目主要面向本地演示；
* 尚未进行 Docker 化部署；
* 知识库索引重建为手动触发；
* Agent 路由质量依赖 LLM 输出；
* 大模型回答质量依赖本地知识库质量和 Prompt 约束。

---

## 11. 后续优化方向

* 增加用户登录与多用户隔离；
* 增加异步任务队列处理索引重建；
* 增加 Docker Compose 一键启动；
* 优化 Agent 工具调用过程可视化；
* 增加更多面试题库和岗位样例；
* 支持导出面试报告和岗位分析报告。

```
```

---

## 12. 项目评估

项目提供默认不访问真实网络、模型或用户数据的 Mock 评估基线：

```powershell
cd D:\spir\NO1_agent\backend
.venv\Scripts\python.exe -m evals.run_evals
.venv\Scripts\python.exe -m evals.run_evals --group retrieval
.venv\Scripts\python.exe -m evals.run_retrieval_calibration --check-model-cache
# 仅在本地缓存存在时人工显式运行；不会下载模型
.venv\Scripts\python.exe -m evals.run_retrieval_calibration --real-embedding
```

每次运行的 JSON、case 明细和 Markdown 报告位于 `backend/evals/results/<运行时间>/`，详细指标、门槛和首次结果参见 [自动化评估基线](docs/EVALUATION_BASELINE.md)，证据所有权与 Prompt Injection 防护参见 [Agent 安全边界](docs/AGENT_SECURITY.md)，候选池与确定性重排参见 [检索候选与排序](docs/RETRIEVAL_RANKING.md)，真实 BGE/Chroma 的隔离测量参见 [真实 Embedding 检索校准](docs/RETRIEVAL_CALIBRATION.md)。
