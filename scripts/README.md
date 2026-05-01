
# 知识库管理脚本 (Knowledge Base Management Scripts)

这个目录包含了用于维护、整理和检索知识库的核心 Python 脚本。

## 核心脚本说明

### 文档摄入与整理

*   **`ingest_documents.py`** (原 `ai_organizer.py`):
    *   **功能**: 自动提取 PDF 文本，调用 AI 分析文档内容，提取标签、年份、机构等元数据。
    *   **操作**: 重命名 PDF 文件为标准化格式 `[Tag1_Tag2]_{year}_{Institution}_{Title}.pdf`，并更新根目录的 `README.md` 索引文件。
    *   **依赖**: 需要设置多 Provider API Key 环境变量（详见项目根目录 `CLAUDE.md`）。

*   **`clean_duplicates.py`**:
    *   **功能**: 基于 MD5 哈希值扫描并删除重复的 PDF 文件。
    *   **策略**: 优先保留文件名更规范（如 AI 命名过的）的文件。

*   **`flatten_kb.py`**:
    *   **功能**: 将所有子文件夹中的 PDF 移动到根目录，并删除空文件夹，保持“扁平化”结构。

### 向量检索与 RAG

*   **`vector_service.py`** (新增):
    *   **功能**: 常驻 HTTP 向量检索服务，监听 `localhost:8001`。
    *   **优势**: 启动时预加载 bge-m3 模型到 MPS，消除每次查询 10-15s 的加载时间。
    *   **用法**: 直接查询 `POST /search {"query": "...", "k": 5}` 即可。

*   **`rag_qa.py`** (原 `ask_gemini.py`):
    *   **功能**: RAG 问答终端。使用 `search_documents` 检索后，调用 LLM 生成回答。
    *   **策略**: ModelScope 6 模型轮换 → OpenRouter 免费模型池自动获取 → 兜底。

*   **`query_kb.py`**:
    *   **功能**: 纯向量检索 CLI，无 LLM 生成。快速查询知识库片段。

*   **`sync_vector_db.py`**:
    *   **功能**: 向量库同步 CLI。支持将 `wiki/` 目录下的 markdown 文件幂等同步到 ChromaDB。
    *   **接口**: 提供 `search_documents()` 统一检索接口，优先 HTTP 调用常驻服务，失败则本地回退。

### 服务与监控

*   **`watcher.py`** (新增):
    *   **功能**: 目录监控服务。轮询 `incoming/` 目录（默认 15 分钟间隔），发现新文档自动调用 `ingest_documents.py`。
    *   **配置**: 通过 `WATCHER_INTERVAL` 环境变量调整轮询间隔。

*   **`retry_raw_ingest.py`** (原 `resend.py`):
    *   **功能**: 重试 `raw/` 目录下未成功摄入的历史记录。

## 使用方法

在使用脚本前，请确保安装了必要的依赖：

```bash
# 如果使用 pip
pip install -r requirements.txt

# 或者使用 uv (推荐)
uv pip install -r requirements.txt
```

在项目根目录下运行脚本 (示例):

```bash
# 整理 PDF
python scripts/ingest_documents.py

# 启动向量服务 (常驻)
python scripts/vector_service.py &

# 启动目录监控 (常驻)
python scripts/watcher.py &

# 向量检索
python scripts/query_kb.py "量子计算"

# RAG 问答
python scripts/rag_qa.py

# 同步 wiki 到向量库
python scripts/sync_vector_db.py
```
