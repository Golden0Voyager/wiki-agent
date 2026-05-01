import os
import sys
import warnings
warnings.filterwarnings("ignore")

from scripts.sync_vector_db import get_embeddings_model, DB_PATH
from langchain_chroma import Chroma

# 从环境变量获取 Gemini API Key
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ 错误: 未找到 GEMINI_API_KEY 环境变量。\n")
    print("请确保已在终端执行: export GEMINI_API_KEY='你的密钥'")
    sys.exit(1)


def get_context(query, k=5):
    """从本地向量库获取最相关的背景资料"""
    # 复用 sync_vector_db 的模型加载函数，确保嵌入模型一致 (bge-m3)
    embeddings = get_embeddings_model()

    vectorstore = Chroma(
        persist_directory=DB_PATH,
        embedding_function=embeddings
    )

    results = vectorstore.similarity_search_with_score(query, k=k)

    context_text = ""
    sources = set()

    for i, (doc, score) in enumerate(results):
        source_name = doc.metadata.get('source', '未知')
        sources.add(source_name)
        context_text += f"--- 资料片段 {i+1} (来源: {source_name}) ---\n"
        context_text += f"{doc.page_content.strip()}\n\n"

    return context_text, sources


def ask_gemini(query):
    import google.generativeai as genai
    genai.configure(api_key=api_key)

    print(f"🔍 正在从知识库检索相关内容...")
    context, sources = get_context(query)

    if not context.strip():
        print("⚠️ 知识库中未找到相关内容，Gemini 将基于自身知识库回答。")
        prompt = query
    else:
        prompt = f"""你是一个专业的行业分析助手。请根据下面提供的【参考资料】来回答【用户问题】。

【要求】:
1. 如果资料中没有直接答案，请根据资料内容进行合理解读，并明确指出这是你的推断。
2. 如果资料内容完全无关，请直说。
3. 请在回答的末尾列出参考的文档来源。
4. 回答要客观、专业、有深度。

【参考资料】:
{context}

【用户问题】:
{query}

回答："""

    print(f"🤖 正在调用 Gemini 生成回答...")

    model = genai.GenerativeModel('gemini-3.1-pro')

    try:
        response = model.generate_content(prompt)
        print("\n" + "=" * 50)
        print("💡 Gemini 的回答：")
        print("=" * 50 + "\n")
        print(response.text)
        print("\n" + "=" * 50)
        print("📄 本次回答参考了以下文件：")
        for s in sources:
            print(f"- {s}")
        print("=" * 50)

    except Exception as e:
        print(f"❌ 调用 Gemini 失败: {str(e)}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        user_query = " ".join(sys.argv[1:])
    else:
        user_query = input("请输入你想问的问题: ").strip()

    if user_query:
        ask_gemini(user_query)
