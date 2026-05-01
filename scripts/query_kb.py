import os
import sys
import warnings

warnings.filterwarnings("ignore")

# 确保能从项目根目录导入 scripts 模块
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from scripts.sync_vector_db import search_documents, DB_PATH


def main():
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        k = 5
    else:
        print("💡 提示: 也可以使用命令行参数: uv run python scripts/query_kb.py '量子计算' 5")
        query = input("请输入搜索关键词或问题: ").strip()
        k = 5

    if not query:
        print("❌ 搜索词不能为空")
        return

    print(f"\n🔍 正在搜索: '{query}' ...\n")
    results = search_documents(query, k=k)

    if not results:
        print("❌ 未找到相关结果")
        return

    print(f"✅ 找到 {len(results)} 个相关片段:\n")
    for i, (content, metadata, score) in enumerate(results, 1):
        source = metadata.get("source", "未知来源")
        print(f"--- 结果 #{i} (距离: {score:.4f}) ---")
        print(f"📄 来源: {source}")
        print(f"📝 内容预览:")
        print(content[:300] + "..." if len(content) > 300 else content)
        print()


if __name__ == "__main__":
    main()
