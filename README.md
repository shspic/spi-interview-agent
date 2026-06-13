# AI Interview RAG Coach

基于 RAG 的 AI 实习面试训练与岗位匹配助手。

本项目面向 AI 应用开发、后端开发、大模型应用开发等实习求职场景，支持用户上传个人资料、项目说明、技术笔记等本地文档，并基于本地知识库完成自由问答、岗位 JD 分析、模拟面试训练和历史记录管理。

## 1. 项目定位

很多求职者在准备 AI 应用开发实习时，会遇到几个问题：

* 不知道自己的项目经历如何匹配岗位 JD；
* 不知道面试官可能围绕项目问什么；
* 不知道如何把自己的学习经历、项目经历表达成面试回答；
* 直接问大模型时，大模型容易编造个人经历；
* 项目资料、岗位要求、面试记录分散，难以沉淀。

本项目通过本地知识库 + RAG 检索 + 大模型生成的方式，让 AI 回答尽量基于用户自己上传的资料，减少虚构内容，并辅助用户进行岗位分析和模拟面试训练。

## 2. 核心功能

### 2.1 知识库管理

支持上传本地资料文件，并构建向量知识库。

当前支持文件类型：

* `.txt`
* `.md`
* `.pdf`

主要能力：

* 上传文件；
* 查看文件列表；
* 删除文件；
* 预览文本解析结果；
* 预览文本切分结果；
* 重建知识库索引；
* 查看知识库状态；
* 基于 query 检索相似文本片段。

### 2.2 RAG 自由问答

用户可以基于本地知识库进行自由提问。

流程：

1. 用户输入问题；
2. 后端调用 embedding 模型生成查询向量；
3. 从 ChromaDB 中检索相关文本片段；
4. 将检索结果和用户问题拼接进 Prompt；
5. 调用 DeepSeek API 生成回答；
6. 返回回答结果和引用来源；
7. 保存问答历史。

### 2.3 岗位 JD 分析

用户可以粘贴实习岗位 JD，系统会结合本地知识库分析：

* 岗位摘要；
* 核心技能要求；
* 用户已有匹配点；
* 用户短板；
* 简历优化建议；
* 可能面试问题；
* 优先准备清单；
* 风险提示。

该模块强调：涉及用户经历、项目、技能时，必须基于本地知识库，不编造用户没有提供的信息。

### 2.4 模拟面试

系统支持根据岗位 JD 和本地知识库生成模拟面试题，并评价用户回答。

当前包含两个核心流程：

1. 生成模拟面试题；
2. 评价用户回答。

评价维度包括：

* 总分；
* 内容相关性；
* 个人经历匹配度；
* 技术准确性；
* 表达结构；
* 风险控制；
* 主要问题；
* 改进建议；
* 参考回答。

### 2.5 历史记录管理

前端历史记录页面支持查看和删除三类记录：

* 自由问答记录；
* 岗位分析记录；
* 模拟面试记录。

用户可以查看历史详情，包括问题、回答、岗位分析结果、面试评分、建议和参考回答。

## 3. 技术栈

### 后端

* Python
* FastAPI
* Uvicorn
* SQLAlchemy
* SQLite
* ChromaDB
* sentence-transformers
* pypdf
* OpenAI SDK 兼容调用 DeepSeek API

### 前端

* React
* Vite
* Axios
* CSS

### AI / RAG

* DeepSeek Chat API
* BAAI/bge-small-zh-v1.5 embedding model
* ChromaDB 向量数据库
* 文本解析
* 文本切分
* 向量检索
* Prompt Engineering

## 4. 项目结构

```text
NO1_agent/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── chat.py
│   │   │   ├── files.py
│   │   │   ├── health.py
│   │   │   ├── history.py
│   │   │   ├── interview.py
│   │   │   ├── interview_records.py
│   │   │   ├── jobs.py
│   │   │   ├── knowledge.py
│   │   │   └── llm.py
│   │   ├── core/
│   │   │   └── config.py
│   │   ├── db/
│   │   │   ├── database.py
│   │   │   └── models.py
│   │   ├── prompts/
│   │   │   ├── chat_prompt.py
│   │   │   ├── interview_prompt.py
│   │   │   └── job_analysis_prompt.py
│   │   ├── services/
│   │   │   ├── chat_service.py
│   │   │   ├── document_loader.py
│   │   │   ├── interview_service.py
│   │   │   ├── job_service.py
│   │   │   ├── llm_service.py
│   │   │   ├── text_splitter.py
│   │   │   └── vector_store.py
│   │   └── main.py
│   ├── data/
│   │   ├── uploads/
│   │   ├── chroma_db/
│   │   └── app.db
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── client.js
│   │   ├── pages/
│   │   │   ├── Chat.jsx
│   │   │   ├── History.jsx
│   │   │   ├── Interview.jsx
│   │   │   ├── JobAnalysis.jsx
│   │   │   └── KnowledgeBase.jsx
│   │   ├── App.jsx
│   │   ├── index.css
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
├── docs/
│   └── 需求文档.md
├── .gitignore
├── AGENTS.md
├── CLAUDE.md
└── README.md
```

## 5. 后端启动方式

进入后端目录：

```powershell
cd D:\spir\NO1_agent\backend
```

创建并激活虚拟环境：

```powershell
py -3.12 -m venv .venv
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

后端默认地址：

```text
http://127.0.0.1:8000
```

Swagger 接口文档：

```text
http://127.0.0.1:8000/docs
```

## 6. 前端启动方式

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

前端默认地址：

```text
http://localhost:5173
```

## 7. 环境变量配置

后端需要在 `backend/.env` 中配置真实 API Key。

示例：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

TAVILY_API_KEY=your_tavily_api_key

CHROMA_PERSIST_DIR=./data/chroma_db
UPLOAD_DIR=./data/uploads
SQLITE_DB_PATH=./data/app.db
EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5
```

注意：

* `.env` 只用于本地开发；
* `.env` 不能提交到 Git；
* `.env.example` 只保留变量名示例，不能写真实 key。

## 8. 主要接口

### 健康检查

```text
GET /api/health
```

### 文件管理

```text
POST   /api/files/upload
GET    /api/files
DELETE /api/files/{file_id}
```

### 知识库

```text
POST /api/knowledge/preview-text
POST /api/knowledge/preview-chunks
POST /api/knowledge/rebuild
GET  /api/knowledge/status
POST /api/knowledge/search
```

### RAG 问答

```text
POST /api/chat/ask
```

### 岗位分析

```text
POST /api/jobs/analyze
```

### 模拟面试

```text
POST /api/interview/question
POST /api/interview/evaluate
```

### 历史记录

```text
GET    /api/history
GET    /api/history/{record_id}
DELETE /api/history/{record_id}
```

### 模拟面试记录

```text
GET    /api/interview-records
GET    /api/interview-records/{session_id}
DELETE /api/interview-records/{session_id}
```

## 9. 当前完成情况

已完成：

* FastAPI 后端服务；
* React 前端页面；
* SQLite 数据库存储；
* 文件上传与文件管理；
* 文档解析；
* 文本切分；
* ChromaDB 向量知识库；
* 本地 embedding 模型接入；
* DeepSeek API 接入；
* RAG 自由问答；
* 岗位 JD 分析；
* 模拟面试生成与评价；
* 自由问答历史记录；
* 岗位分析历史记录；
* 模拟面试历史记录；
* 前后端基础联调。

## 10. 当前限制

当前项目仍存在以下限制：

* 暂未实现用户登录系统；
* 暂未实现多用户隔离；
* 暂未实现生产环境部署；
* 暂未实现完整联网搜索；
* 暂未引入 LangGraph 等 Agent 编排框架；
* PDF 解析效果取决于原始 PDF 文本质量；
* 大模型输出质量依赖 Prompt 和输入资料质量。

## 11. 后续计划

后续可继续增强：

* 接入 Tavily，实现岗位信息联网搜索；
* 引入 LangGraph，实现 Agent 工作流；
* 增加简历生成模块；
* 增加面试会话连续追问能力；
* 增加知识库文件分组；
* 增加 Docker 部署；
* 增加在线演示部署；
* 优化 UI 体验；
* 增加测试用例和异常处理。

## 12. 项目价值

本项目完整覆盖了一个 AI 应用开发项目的核心链路：

```text
前端页面
后端 API
数据库
文件上传
文档解析
文本切分
Embedding
向量数据库
RAG 检索
大模型调用
Prompt 设计
历史记录管理
前后端联调
```

该项目可以作为 AI 应用开发、RAG 应用开发、后端开发实习方向的项目作品，用于展示对大模型应用工程化流程的理解和实践能力。
