import asyncio
import logging
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any

from wiki_service import WikiService

from loguru import logger

# 关闭第三方库的刷屏日志
for _name in ("httpx", "chromadb", "uvicorn.access", "watchfiles"):
    logging.getLogger(_name).setLevel(logging.WARNING)

# 创建任务队列
ingest_queue = asyncio.Queue()
wiki_service = WikiService()

class IngestPayload(BaseModel):
    source_project: str
    topic: str
    content: str
    metadata: Dict[str, Any] = {}
    force: bool = False  # 绕过 content_hash 去重，恢复脚本/手工重投时使用

# 并发 Worker 数量 (LLM 调用是纯 I/O 等待，多 Worker 可大幅提升吞吐量)
WORKER_COUNT = 3

async def queue_worker(worker_id: int):
    """后台 Worker，从队列取任务并处理。文件写入操作由 WikiService 内部 asyncio.Lock 保护。"""
    logger.info(f"WikiService worker-{worker_id} started.")
    while True:
        try:
            payload = await ingest_queue.get()
        except asyncio.CancelledError:
            logger.info(f"Worker-{worker_id} cancelled.")
            break

        try:
            logger.info(f"[Worker-{worker_id}] Picked up: {payload['topic']}")
            await wiki_service.process_ingest_task(payload)
        except Exception as e:
            logger.exception(f"[Worker-{worker_id}] Error processing task")
        finally:
            ingest_queue.task_done()

# lifespan context manager for FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: 启动 N 个并发 Worker
    worker_tasks = [
        asyncio.create_task(queue_worker(i)) for i in range(WORKER_COUNT)
    ]
    logger.info(f"Started {WORKER_COUNT} concurrent ingest workers.")
    yield
    # Shutdown: 优雅地关闭所有 Worker 和 httpx 客户端
    for task in worker_tasks:
        task.cancel()
    await asyncio.gather(*worker_tasks, return_exceptions=True)
    if wiki_service._http_client and not wiki_service._http_client.is_closed:
        await wiki_service._http_client.aclose()

app = FastAPI(title="WikiAgent API", lifespan=lifespan)

@app.post("/api/v1/wiki/ingest")
async def ingest_content(payload: IngestPayload):
    """
    接收摄入请求并放入队列。
    异步非阻塞返回。
    """
    await ingest_queue.put(payload.model_dump())
    return {
        "status": "queued",
        "message": f"Task '{payload.topic}' from '{payload.source_project}' queued successfully.",
        "queue_size": ingest_queue.qsize()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
