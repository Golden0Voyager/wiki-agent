import asyncio
from langchain_chroma import Chroma
from scripts.sync_vector_db import get_embeddings_model, DB_PATH

async def search():
    embeddings = get_embeddings_model()
    db = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)
    results = db.similarity_search_with_score("开源生态对人工智能有什么影响？", k=3)
    
    print("\n\n======== 🔎 知识库检索测试 (bge-m3) ========\n")
    for doc, score in results:
        print(f"[{score:.4f}] 来源: {doc.metadata.get('source', 'Unknown')}\n{doc.page_content[:200]}...\n{'-'*50}")

if __name__ == "__main__":
    asyncio.run(search())
