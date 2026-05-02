import os
import sys
import warnings

warnings.filterwarnings("ignore")

# 确保能从项目根目录导入 scripts 模块
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from scripts.sync_vector_db import search_documents, DB_PATH


# ── UI 调色板（v2 极简风：青色品牌 + 软边框） ─────────────────────
B  = "\033[1m"
D  = "\033[2m"
C  = "\033[36m"
DC = "\033[2;36m"
BC = "\033[1;36m"
G  = "\033[32m"
R  = "\033[31m"
NC = "\033[0m"

_BOX_W = 58
_BAR = "─" * (_BOX_W - 2)


def _panel_open(title: str) -> None:
    inner = _BOX_W - 2 - 1 - len(title) - 1 - 1
    print(f"{DC}╭─{NC} {BC}{title}{NC} {DC}{'─' * inner}╮{NC}")


def _panel_close() -> None:
    print(f"{DC}╰{_BAR}╯{NC}")


def main():
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        k = 5
    else:
        print(f"\n  {D}用法: uv run python scripts/query_kb.py '量子计算'{NC}\n")
        try:
            query = input(f"{BC}›{NC} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        k = 5

    if not query:
        print(f"  {R}✗{NC} {D}搜索词不能为空{NC}")
        return

    results = search_documents(query, k=k)

    print()
    if not results:
        _panel_open("search")
        print(f"{DC}│{NC}  {B}{query}{NC}     {D}no results{NC}")
        _panel_close()
        print()
        return

    _panel_open("search")
    print(f"{DC}│{NC}  {B}{query}{NC}     {C}{len(results)} results{NC}")
    _panel_close()
    print()

    for i, (content, metadata, score) in enumerate(results, 1):
        source = metadata.get("source", "未知来源")
        # 内容片段：单行显示前 80 字（避免占据屏幕），dim 灰处理
        snippet = content.strip().replace("\n", " ")
        if len(snippet) > 80:
            snippet = snippet[:80] + "…"

        print(f"  {BC}{i}{NC}  {B}{score:.2f}{NC}   {C}{source}{NC}")
        print(f"         {D}{snippet}{NC}")
        print()


if __name__ == "__main__":
    main()
