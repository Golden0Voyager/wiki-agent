import os
import sys
import warnings
warnings.filterwarnings("ignore")

from scripts.sync_vector_db import get_embeddings_model, DB_PATH
from langchain_chroma import Chroma

def main():
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        k = 3
    else:
        print("💡 提示: 也可以使用命令行参数: uv run python scripts/query_kb.py '量子计算' 5")
        query = input("请输入搜索关键词或问题: ").strip()
        k = 3

    if not query:
        return

    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        print("请先运行 uv run python scripts/build_vector_db.py 构建知识库")
        return

    # 复用 sync_vector_db 的模型加载函数，确保嵌入模型一致
    print("⬇️ 加载模型中...")
    embeddings = get_embeddings_model()

    vectorstore = Chroma(
        persist_directory=DB_PATH,
        embedding_function=embeddings
    )

    print(f"🔍 正在搜索: '{query}' ...")
    results = vectorstore.similarity_search_with_score(query, k=k)

    print(f"\n✅ 找到 {len(results)} 个相关片段:\n")
    for i, (doc, score) in enumerate(results):
        print(f"--- 结果 #{i+1} (距离: {score:.4f}) ---")
        print(f"📄 来源: {doc.metadata.get('source', '未知')}")

        content = doc.page_content.strip()
        preview = content if len(content) < 300 else content[:300] + "..."
        print(f"📝 内容预览:\n{preview}")
        print("-" * 50 + "\n")

if __name__ == "__main__":
    main()
