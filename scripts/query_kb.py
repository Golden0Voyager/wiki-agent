import os
import argparse
import sys
# 抑制警告信息
import warnings
warnings.filterwarnings("ignore")

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

# --- 配置 ---
KB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(KB_ROOT, "chroma_db")
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"

def main():
    # 支持命令行参数，也可以直接运行交互模式
    if len(sys.argv) > 1:
        query = sys.argv[1]
        k = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    else:
        print("💡 提示: 也可以使用命令行参数: python scripts/query_kb.py '量子计算' 5")
        query = input("请输入搜索关键词或问题: ").strip()
        k = 3

    if not query:
        return

    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库不存在: {DB_PATH}")
        print("请先运行 python scripts/build_vector_db.py 构建知识库")
        return

    # 1. 初始化 Embedding (必须与构建时一致)
    print("⬇️ 加载模型中...")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': True}
    )

    # 2. 加载数据库
    vectorstore = Chroma(
        persist_directory=DB_PATH, 
        embedding_function=embeddings
    )

    # 3. 搜索
    print(f"🔍 正在搜索: '{query}' ...")
    # score 越小越相似 (Chroma 默认是 L2 距离，但在 LangChain wrapper 中行为可能调整，
    # 通常 similarity_search_with_score 返回的是距离)
    results = vectorstore.similarity_search_with_score(query, k=k)

    # 4. 展示结果
    print(f"\n✅ 找到 {len(results)} 个相关片段:\n")
    for i, (doc, score) in enumerate(results):
        # 转换 score 为更直观的相似度 (如果是 Cosine Distance: 0是完全一样, 1是完全不同)
        # 这里直接打印原始分
        print(f"--- 结果 #{i+1} (距离: {score:.4f}) ---")
        print(f"📄 来源: {doc.metadata.get('source', '未知')}")
        # PyPDFLoader 读取的 metadata 里通常有 page
        page = doc.metadata.get('page', 0) + 1 
        print(f"📖 页码: P{page}")
        
        content = doc.page_content.strip()
        # 简单截断展示
        preview = content if len(content) < 200 else content[:200] + "..."
        print(f"📝 内容预览:\n{content}") 
        print("-" * 50 + "\n")

if __name__ == "__main__":
    main()
