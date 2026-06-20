import os
import re
import time
from urllib.parse import unquote

import httpx


def parse_readme_and_ingest():
    readme_path = os.path.join(os.path.dirname(__file__), "..", "README.md")
    if not os.path.exists(readme_path):
        print("❌ 找不到 README.md 文件！")
        return

    with open(readme_path, encoding="utf-8") as f:
        content = f.read()

    # 按分割线切分出每个报告的独立块
    blocks = content.split("---")

    success_count = 0
    # 跳过第一个块（通常是 README 的标题和前言）
    for block in blocks[1:]:
        block = block.strip()
        if not block:
            continue

        # 1. 提取分数、标题和文件名
        match = re.search(r'### \[([0-9\.]+)\] \[(.*?)\]\((.*?)\)', block)
        if not match:
            continue

        score = float(match.group(1))
        title = match.group(2)
        filename = unquote(match.group(3))

        # 2. 提取元数据（机构、年份、标签）
        meta_match = re.search(r'> \*\*机构\*\*: (.*?) \| \*\*年份\*\*: (.*?) \| \*\*标签\*\*: (.*)', block)
        institution = "未知"
        year = "2025"
        tags = []
        if meta_match:
            institution = meta_match.group(1).strip()
            year = meta_match.group(2).strip()
            tags_raw = meta_match.group(3)
            # 把类似 `量子计算` `产业政策` 拆分成数组
            tags = [t.strip('` ') for t in tags_raw.split() if t.strip('` ')]

        # 3. 提取评分理由
        reason_match = re.search(r'> \*\*评分理由\*\*: _(.*?)_', block)
        reason = reason_match.group(1) if reason_match else ""

        # 4. 提取核心摘要
        summary = ""
        lines = block.split('\n')
        reason_idx = -1
        for i, line in enumerate(lines):
            if '> **评分理由**:' in line:
                reason_idx = i
                break

        if reason_idx != -1:
            summary = "\n".join(lines[reason_idx+1:]).strip()

        # 5. 拼装成与原先完全一致的 payload
        wiki_payload = {
            "source_project": "pdf_archive",
            "topic": title,
            "content": summary,
            "metadata": {
                "tags": tags,
                "institution": institution,
                "year": year,
                "score": score,
                "score_reason": reason,
                "original_file": filename
            }
        }

        print(f"📥 正在批量导入: {title} ...")
        try:
            # 投递给常驻后端的 WikiAgent
            httpx.post("http://127.0.0.1:8000/api/v1/wiki/ingest", json=wiki_payload, timeout=10)
            print("  ✅ 成功加入后台处理队列")
            success_count += 1
        except Exception as e:
            print(f"  ❌ 投递失败 (请确保 uvicorn api:app 正在运行): {e}")

        # 稍微停顿，防止瞬间发太多请求把 FastAPI 的队列塞爆
        time.sleep(0.5)

    print(f"\n🎉 批量导入任务提交完毕，共提交 {success_count} 篇报告至后台队列。")
    print("👉 请在另一终端观察 `uvicorn api:app` 的处理日志。")

if __name__ == "__main__":
    parse_readme_and_ingest()
