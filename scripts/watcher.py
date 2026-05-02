"""
WikiAgent Directory Watcher — 自动监控 incoming/ 目录
用法:
    uv run python scripts/watcher.py
环境变量:
    WATCHER_INTERVAL=30   # 轮询间隔（秒），默认 30 秒
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
WATCHER_INTERVAL = int(os.getenv("WATCHER_INTERVAL", "30"))


def has_documents() -> bool:
    if not INCOMING_DIR.exists():
        return False
    return any(f.suffix.lower() in SUPPORTED_EXTENSIONS for f in INCOMING_DIR.iterdir() if f.is_file())


async def run_ingest():
    """调用 ingest_documents.py 处理 incoming/ 中的文档。
    子进程的 stdout/stderr 直接继承到 watcher 自身的句柄，
    保证 ingest 的所有输出都进入 watcher.log，便于诊断 POST/LLM 失败。"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ── ingest 开始 ──────────────────")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "scripts/ingest_documents.py",
        cwd=str(PROJECT_ROOT),
    )
    returncode = await proc.wait()
    if returncode == 0:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ── ingest 完成 ──────────────────")
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ── ingest 失败 (rc={returncode}) ──────────────────")


async def main():
    sys.stdout.reconfigure(line_buffering=True)
    print(f"👁️  WikiAgent Watcher 启动")
    print(f"   监控目录: {INCOMING_DIR}")
    print(f"   轮询间隔: {WATCHER_INTERVAL} 秒")
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
