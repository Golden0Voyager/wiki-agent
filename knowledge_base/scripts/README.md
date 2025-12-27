
# 知识库管理脚本 (Knowledge Base Management Scripts)

这个目录包含了用于维护和整理知识库 PDF 文件的核心 Python 脚本。

## 核心脚本说明

*   **`ai_organizer.py`**:
    *   **功能**: 自动提取 PDF 文本，调用 AI (ZhipuGLM) 分析文档内容，提取标签、年份、机构等元数据。
    *   **操作**: 重命名 PDF 文件为标准化格式 `[Tag1_Tag2]_{year}_{Institution}_{Title}.pdf`，并更新根目录的 `README.md` 索引文件。
    *   **依赖**: 需要设置 `ZHIPUAI_API_KEY` 环境变量。

*   **`clean_duplicates.py`**:
    *   **功能**: 基于 MD5 哈希值扫描并删除重复的 PDF 文件。
    *   **策略**: 优先保留文件名更规范（如 AI 命名过的）的文件。

*   **`flatten_kb.py`**:
    *   **功能**: 将所有子文件夹中的 PDF 移动到根目录，并删除空文件夹，保持“扁平化”结构。

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
python scripts/ai_organizer.py
```