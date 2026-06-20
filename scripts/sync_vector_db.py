import os
from pathlib import Path

from loguru import logger

KB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(KB_ROOT, "chroma_db")
EMBEDDING_MODEL = "BAAI/bge-m3"

# 懒加载机制，避免在主进程导入时就分配大量内存或显存
_embeddings_model = None

def get_embeddings_model():
    global _embeddings_model
    if _embeddings_model is None:
        logger.info(f"Loading HuggingFace Embeddings model: {EMBEDDING_MODEL} ...")
        import torch
        from langchain_huggingface import HuggingFaceEmbeddings
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        _embeddings_model = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={'device': device},
            encode_kwargs={'normalize_embeddings': True}
        )
        logger.info(f"Embeddings model loaded on {device}.")
    return _embeddings_model

import hashlib


def _make_chunk_id(source: str, chunk_index: int) -> str:
    """基于来源文件名 + chunk 序号生成确定性 ID，确保同一卡片更新时覆盖旧向量"""
    raw = f"{source}::chunk_{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def upsert_markdowns(file_paths: list[str]):
    """将给定的 markdown 文件异步解析并存入 ChromaDB (幂等: 同一文件重复写入不会产生重复向量)"""
    if not file_paths:
        return

    try:
        import asyncio

        from langchain_chroma import Chroma
        from langchain_community.document_loaders import TextLoader
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        loop = asyncio.get_running_loop()

        def _process():
            embeddings = get_embeddings_model()
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=600,
                chunk_overlap=100,
                separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""]
            )

            # 打开持久化 DB 实例 (复用同一个 collection)
            db = Chroma(
                persist_directory=DB_PATH,
                embedding_function=embeddings,
            )
            collection = db._collection

            for path_str in file_paths:
                path = Path(path_str)
                if not path.exists():
                    continue

                filename = path.name
                loader = TextLoader(str(path), encoding="utf-8")
                docs = loader.load()

                for doc in docs:
                    doc.metadata["source"] = filename

                splits = text_splitter.split_documents(docs)
                if not splits:
                    continue

                # 1. 删除该文件的旧向量 (按 source metadata 过滤)
                try:
                    old_ids = collection.get(where={"source": filename})["ids"]
                    if old_ids:
                        collection.delete(ids=old_ids)
                        logger.info(f"Deleted {len(old_ids)} old chunks for {filename}")
                except Exception:
                    pass  # 首次写入时无旧数据，忽略

                # 2. 用确定性 ID 写入新向量
                chunk_ids = [_make_chunk_id(filename, i) for i in range(len(splits))]
                db.add_documents(documents=splits, ids=chunk_ids)
                logger.info(f"Upserted {len(splits)} chunks for {filename}")

            logger.success("ChromaDB sync completed.")

        await loop.run_in_executor(None, _process)

    except Exception:
        logger.exception(f"Error during ChromaDB upsert for {file_paths}")


def search_documents(query: str, k: int = 5) -> list[tuple[str, dict, float]]:
    """
    统一向量检索接口。
    优先尝试常驻向量服务 (HTTP)，失败则回退到本地加载模型。
    
    返回: [(content, metadata, score), ...]
    """
    # 1. 尝试常驻服务
    try:
        import httpx
        resp = httpx.post(
            "http://127.0.0.1:8001/search",
            json={"query": query, "k": k},
            timeout=30.0,
        )
        if resp.status_code == 200:
            results = []
            for r in resp.json().get("results", []):
                results.append((r["content"], r["metadata"], r["score"]))
            return results
    except Exception:
        pass  # 服务未启动或异常，回退到本地

    # 2. 本地回退
    logger.info("Vector service unavailable, falling back to local model loading...")
    embeddings = get_embeddings_model()
    from langchain_chroma import Chroma
    vectorstore = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)
    raw_results = vectorstore.similarity_search_with_score(query, k=k)
    return [(doc.page_content, doc.metadata, float(score)) for doc, score in raw_results]
