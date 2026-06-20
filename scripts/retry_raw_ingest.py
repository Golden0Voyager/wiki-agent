"""
重发 raw/ 目录下的待处理任务到 WikiAgent 队列。
自动按 content hash 去重，同一份文档只发送一次。
已处理的 hash 也会被过滤（读取 processed_hashes.json）。
"""
import json
from pathlib import Path

import httpx

PROJECT_DIR = Path(__file__).parent
raw_dir = PROJECT_DIR / "raw"
processed_path = PROJECT_DIR / "processed_hashes.json"

# 加载已处理 hash
processed = set()
if processed_path.exists():
    try:
        processed = set(json.loads(processed_path.read_text(encoding="utf-8")))
    except Exception:
        pass

# 按 hash 去重：同一份文档只保留最新的那条记录
seen_hashes = {}
for file in sorted(raw_dir.glob("*.json")):
    with open(file) as f:
        payload = json.load(f)
    content_hash = payload.get("hash", "")
    seen_hashes[content_hash] = (file, payload)

unique_items = list(seen_hashes.values())
# 过滤掉已处理的
pending = [(f, p) for f, p in unique_items if p.get("hash", "") not in processed]

print(f"📦 raw/ 共 {len(list(raw_dir.glob('*.json')))} 文件 → 去重后 {len(unique_items)} 份 → 待处理 {len(pending)} 份\n")

if not pending:
    print("✅ 所有文档均已处理，无需重发！")
else:
    for file, payload in pending:
        topic = payload.get("topic", "unknown")
        h = payload.get("hash", "N/A")[:8]
        if "source" in payload and "source_project" not in payload:
            payload["source_project"] = payload.pop("source")

        print(f"🚀 Resending: {topic} (hash: {h}...)")
        try:
            r = httpx.post(
                "http://127.0.0.1:8000/api/v1/wiki/ingest",
                json={
                    "source_project": payload.get("source_project", "pdf_archive"),
                    "topic": topic,
                    "content": payload.get("content", ""),
                    "metadata": payload.get("metadata", {}),
                },
                timeout=60.0,
            )
            print(f"   ✅ {r.status_code}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")
