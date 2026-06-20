"""
Vector Service — 常驻向量检索服务
避免每次 RAG 问答重复加载 bge-m3 模型。
启动时加载一次，通过 HTTP POST /search 提供检索能力。

Usage:
    uv run python scripts/vector_service.py
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

KB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(KB_ROOT, "chroma_db")
EMBEDDING_MODEL = "BAAI/bge-m3"

_vectorstore = None


def _load_model():
    """加载 bge-m3 模型到 MPS（只执行一次）"""
    global _vectorstore
    if _vectorstore is not None:
        return

    import torch
    from langchain_chroma import Chroma
    from langchain_huggingface import HuggingFaceEmbeddings

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"🚀 加载嵌入模型 {EMBEDDING_MODEL} 到 {device.upper()} ...")

    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True},
    )

    _vectorstore = Chroma(
        persist_directory=DB_PATH,
        embedding_function=embeddings,
    )
    print(f"✅ 向量服务就绪。ChromaDB: {DB_PATH}")


class VectorSearchHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 静默日志，避免污染终端

    def _respond_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_POST(self):
        if self.path == "/search":
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_len).decode())
                query = body.get("query", "")
                k = body.get("k", 5)

                if not _vectorstore:
                    self._respond_json({"error": "Vectorstore not loaded"}, 503)
                    return

                results = _vectorstore.similarity_search_with_score(query, k=k)
                formatted = []
                for doc, score in results:
                    formatted.append({
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "score": float(score),
                    })

                self._respond_json({"results": formatted})
            except Exception as e:
                self._respond_json({"error": str(e)}, 500)
        else:
            self._respond_json({"error": "Not found"}, 404)


def run(host="localhost", port=8001):
    _load_model()
    server = HTTPServer((host, port), VectorSearchHandler)
    server.vectorstore = _vectorstore
    print(f"🌐 向量服务运行在 http://{host}:{port}/search")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 向量服务已停止")


if __name__ == "__main__":
    run()
