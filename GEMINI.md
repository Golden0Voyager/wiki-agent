# Project Intelligence: Knowledge Base

专注于个人知识资产的矢量化、图谱化及长效记忆管理。

## 🚀 运行环境 (Runtime)
- **环境管理**: `uv` (强制)
- **依赖库**: LangChain, ChromaDB/Pinecone
- **存储位置**: `chroma_db/` 目录严禁提交至 Git。

## 🧠 AI 协作规范 (AI Patterns)
- **推荐模型**: **Gemini 3.0 Pro** (用于构建复杂的知识链) 或 **DeepSeek-V3** (高性能推理)。
- **任务目标**: 确保知识库的可索引性和检索精度 (RAG)。

## 🔒 隐私声明 (Privacy)
- 本仓库包含个人笔记与思维记录，确保 `.env` 中的 OpenSearch/OpenAI 密钥物理隔离。
