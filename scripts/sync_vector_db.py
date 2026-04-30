import os
from loguru import logger
from typing import List
from pathlib import Path

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


async def upsert_markdowns(file_paths: List[str]):
    """将给定的 markdown 文件异步解析并存入 ChromaDB (幂等: 同一文件重复写入不会产生重复向量)"""
    if not file_paths:
        return

    try:
        from langchain_community.document_loaders import TextLoader
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from langchain_chroma import Chroma

        import asyncio
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

    except Exception as e:
        logger.exception(f"Error during ChromaDB upsert for {file_paths}")

