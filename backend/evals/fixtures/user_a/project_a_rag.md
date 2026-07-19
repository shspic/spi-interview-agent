# RAG 文档问答系统

项目使用 FastAPI 提供文档上传和问答接口，React 构建操作页面，ChromaDB 保存向量，BGE Embedding 生成归一化向量，DeepSeek 生成回答。系统支持文档上传、向量检索和引用来源展示。

测试用户负责文档上传、向量检索和引用来源模块。资料没有使用 Kubernetes 或 Redis，也没有百万用户、95% 准确率或 50% 性能提升等数据。
