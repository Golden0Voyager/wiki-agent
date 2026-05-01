"""
WikiAgent Directory Watcher — 自动监控 incoming/ 目录
用法:
    uv run python scripts/watcher.py
环境变量:
    WATCHER_INTERVAL=900  # 轮询间隔（秒），默认 15 分钟
"""
import os
import sys
import time
import asyncio
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INCOMING_DIR = PROJECT_ROOT / "incoming"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".md", ".txt", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg"}
WATCHER_INTERVAL = int(os.getenv("WATCHER_INTERVAL", "900"))


def has_documents() -> bool:
    if not INCOMING_DIR.exists():
        return False
    return any(f.suffix.lower() in SUPPORTED_EXTENSIONS for f in INCOMING_DIR.iterdir() if f.is_file())


async def run_ingest():
    """调用 ingest_documents.py 处理 incoming/ 中的文档。"""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uv", "run", "python", "scripts/ingest_documents.py",
        cwd=str(PROJECT_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 文档摄入完成")
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ 摄入失败: {stderr.decode()[:200]}")


async def main():
    print(f"👁️  WikiAgent Watcher 启动")
    print(f"   监控目录: {INCOMING_DIR}")
    print(f"   轮询间隔: {WATCHER_INTERVAL} 秒 ({WATCHER_INTERVAL // 60} 分钟)")
    print(f"   支持格式: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    print("   按 Ctrl+C 停止\n")

    while True:
        try:
            if has_documents():
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📂 发现新文档，开始处理...")
                await run_ingest()
            await asyncio.sleep(WATCHER_INTERVAL)
        except KeyboardInterrupt:
            print("\n🛑 Watcher 已停止")
            break


if __name__ == "__main__":
    asyncio.run(main())
