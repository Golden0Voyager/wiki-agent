"""
一次性恢复脚本：从 README.md 提取 AI 指数年度报告条目，重新 POST 到 wiki API。

背景：5/2 13:37 watcher 摄入 AI 指数 PDF 时，uvicorn 正在重启，POST 落空，
README.md 写入成功但 wiki/ 卡片未生成、raw/ 也无对应 JSON。
此脚本从 README.md 反向构造 payload，重新投递到队列。

用法：
    ./start.sh start    # 确保 uvicorn 运行
    .venv/bin/python scripts/recover_ai_index.py
"""
import re
import sys
import httpx
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
ARCHIVE_FILENAME = (
    "[人工智能_科技产业]_2026_斯坦福大学以人为本人工智能研究所（HAI）"
    "_AI指数年度报告.pdf"
)

# ── 1. 从 README.md 抽取条目 ──────────────────────────────────────
text = README.read_text(encoding="utf-8")
pattern = re.compile(
    r"### \[(?P<score>[\d.]+)\] \[(?P<title>AI指数年度报告)\]\([^)]+\)\s*\n"
    r"\s*\n"
    r"> \*\*机构\*\*: (?P<institution>[^|]+) \| "
    r"\*\*年份\*\*: (?P<year>\d+) \| "
    r"\*\*标签\*\*: (?P<tags>[^\n]+)\s*\n"
    r">\s*\n"
    r"> \*\*评分理由\*\*: _(?P<reason>[^_]+)_\s*\n"
    r"\s*\n"
    r"(?P<summary>.*?)\n---",
    re.DOTALL,
)
match = pattern.search(text)
if not match:
    sys.exit("❌ README.md 中未找到 'AI指数年度报告' 条目，无法恢复。")

g = match.groupdict()
tags = re.findall(r"`([^`]+)`", g["tags"])
# 还原 ingest_documents.py 在写 README 时加的加粗包装
summary = g["summary"].replace("**【", "【").replace("】**", "】").strip()

payload = {
    "source_project": "pdf_archive",
    "topic": g["title"].strip(),
    "content": summary,
    "force": True,  # 恢复脚本：始终绕过去重，便于在修复 prompt 后重投
    "metadata": {
        "tags": tags,
        "institution": g["institution"].strip(),
        "year": g["year"].strip(),
        "score": float(g["score"]),
        "score_reason": g["reason"].strip(),
        "original_file": ARCHIVE_FILENAME,
    },
}

print(f"📦 准备投递")
print(f"   topic        {payload['topic']}")
print(f"   score        {payload['metadata']['score']}")
print(f"   tags         {tags}")
print(f"   summary      {len(summary)} 字")
print()

# ── 2. POST 到 wiki API ──────────────────────────────────────────
try:
    resp = httpx.post(
        "http://127.0.0.1:8000/api/v1/wiki/ingest",
        json=payload,
        timeout=10.0,
    )
    print(f"✅ HTTP {resp.status_code}")
    print(f"   {resp.text}")
    print()
    print("─ 接下来 ─────────────────────────────────────")
    print("uvicorn 的 3 个 worker 会异步处理这个任务，建议：")
    print("  1. ./start.sh logs        # 实时观察 worker 处理日志")
    print("  2. tail -f wiki/log.md    # 等待新 entity / concept 卡片落盘")
except httpx.ConnectError as e:
    sys.exit(f"❌ 无法连接 uvicorn (127.0.0.1:8000)。请先 `./start.sh start`。\n   {e}")
