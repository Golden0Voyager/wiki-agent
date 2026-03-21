# Project Intelligence: Knowledge Base

专注于个人知识资产的矢量化、图谱化及长效记忆管理。

## 🚀 运行环境 (Runtime)
- **环境管理**: `uv` (强制)
- **依赖库**: LangChain, ChromaDB/Pinecone
- **存储位置**: `chroma_db/` 目录严禁提交至 Git。

## 🧠 AI 协作规范 (AI Patterns)
- **推荐模型**: **Gemini 1.5 Pro** (用于构建复杂的知识链) 或 **DeepSeek-V3** (高性能推理)。
- **任务目标**: 确保知识库的可索引性和检索精度 (RAG)。

## 📁 隔离规范 (Isolation)
- **数据库**: `chroma_db/` 目录严禁提交。
- **配置**: 确保 `.env` 中的 API 密钥物理隔离。