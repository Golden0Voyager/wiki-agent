import os
import sys
import warnings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
import google.generativeai as genai

# 忽略不必要的警告
warnings.filterwarnings("ignore")

# --- 配置 ---
KB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(KB_ROOT, "chroma_db")
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"

# 从环境变量获取 Gemini API Key
# 注意：你的 .zshrc 里配置的是 GEMINI_API_KEY
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ 错误: 未找到 GEMINI_API_KEY 环境变量。\n")
    print("请确保已在终端执行: export GEMINI_API_KEY='你的密钥'")
    sys.exit(1)

genai.configure(api_key=api_key)

def get_context(query, k=5):
    """从本地向量库获取最相关的背景资料"""
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': True}
    )
    
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
    print(f"🔍 正在从知识库检索相关内容...")
    context, sources = get_context(query)
    
    if not context.strip():
        print("⚠️ 知识库中未找到相关内容，Gemini 将基于自身知识库回答。")
        prompt = query
    else:
        # 构造 RAG 提示词
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
    
    # 使用最新的 gemini-1.5-flash (快) 或 gemini-1.5-pro (强)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    try:
        response = model.generate_content(prompt)
        print("\n" + "="*50)
        print("💡 Gemini 的回答：")
        print("="*50 + "\n")
        print(response.text)
        print("\n" + "="*50)
        print("📄 本次回答参考了以下文件：")
        for s in sources:
            print(f"- {s}")
        print("="*50)
        
    except Exception as e:
        print(f"❌ 调用 Gemini 失败: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        user_query = " ".join(sys.argv[1:])
    else:
        user_query = input("请输入你想问的问题: ").strip()
    
    if user_query:
        ask_gemini(user_query)
