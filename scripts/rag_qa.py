import os
import sys
import time
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# 确保能从项目根目录导入 scripts 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync_vector_db import search_documents


# ── ModelScope 模型池（自动轮换）─────────────────────────────────
_MODELSCOPE_MODELS = [
    "deepseek-ai/DeepSeek-V4-Flash",
    "Qwen/Qwen3.5-397B-A17B",
    "inclusionAI/Ling-2.6-1T",
    "deepseek-ai/DeepSeek-V3.2",
    "moonshotai/Kimi-K2.5",
    "MiniMax/MiniMax-M1-80k",
]

# 全局轮询索引
_ms_index = 0

# OpenRouter 缓存
_OR_CACHE_FILE = PROJECT_ROOT / ".openrouter_models.json"
_OR_CACHE_TTL = 86400  # 24 小时
_or_models = None  # 懒加载


# ── UI 调色板（v2 极简风：青色品牌 + 软边框） ─────────────────────
B  = "\033[1m"
D  = "\033[2m"
C  = "\033[36m"
DC = "\033[2;36m"
BC = "\033[1;36m"
G  = "\033[32m"
Y  = "\033[33m"
R  = "\033[31m"
NC = "\033[0m"

# 固定外框宽度（含两端 │），避免中英混排时再做列宽校准
_BOX_W = 58
# 顶/底栏的横线长度（去掉 "╭─" / "╰─" 两字符与"╮"/"╯"一字符）
_BAR = "─" * (_BOX_W - 2)


def _print_panel_open(title: str) -> None:
    """打印一个软边框面板的顶栏：╭─ title ────╮"""
    inner = _BOX_W - 2 - 1 - len(title) - 1 - 1  # ╭─ space title space ─╮
    print(f"{DC}╭─{NC} {BC}{title}{NC} {DC}{'─' * inner}╮{NC}")


def _print_panel_close() -> None:
    print(f"{DC}╰{_BAR}╯{NC}")


def _info(label: str, value: str) -> None:
    """单行 dim 状态：'  label   value'"""
    print(f"  {D}{label:<11}{NC}{value}")


# ── 工具函数 ─────────────────────────────────────────────────────

def _get_api_key(env_name):
    raw = os.getenv(env_name, "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    return keys[0] if keys else None


def _call_llm(client, model, system_prompt, user_prompt):
    """调用单个模型，成功返回 content，失败返回 None"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=4096,
        )
        if response.choices and response.choices[0].message.content:
            return response.choices[0].message.content
        return None
    except Exception:
        return None


# ── OpenRouter 自动获取与筛选 ────────────────────────────────────

def _should_refresh_or_cache():
    if not _OR_CACHE_FILE.exists():
        return True
    age = time.time() - _OR_CACHE_FILE.stat().st_mtime
    return age > _OR_CACHE_TTL


def fetch_openrouter_rag_models(force=False):
    """
    从 OpenRouter API 获取免费模型列表，按 RAG 适用性筛选。
    结果缓存到 .openrouter_models.json，24 小时内复用。
    """
    global _or_models

    if not force and _or_models is not None:
        return _or_models

    if not force and not _should_refresh_or_cache():
        try:
            with open(_OR_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _or_models = data.get("models", [])
                return _or_models
        except Exception:
            pass

    print(f"  {D}fetching{NC}     openrouter free models …")
    try:
        import httpx
        resp = httpx.get("https://openrouter.ai/api/v1/models", timeout=30)
        resp.raise_for_status()
        all_models = resp.json().get("data", [])

        models = []
        for m in all_models:
            mid = m.get("id", "")
            if not mid.endswith(":free"):
                continue
            # 排除小模型
            if any(p in mid.lower() for p in ["-3b-", "-4b-", "-7b-", "-8b-", "-9b-", "-12b-", "nano", "mini", "xs"]):
                continue
            ctx = m.get("context_length", 0)
            if ctx < 32768:
                continue
            models.append({"id": mid, "context": ctx})

        # 缓存
        with open(_OR_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"models": models, "cached_at": time.time()}, f, indent=2)

        _or_models = models
        print(f"  {G}✓{NC} {len(models)} {D}rag-ready models cached{NC}")
        return models

    except Exception as e:
        print(f"  {R}✗{NC} openrouter fetch failed {D}({e}){NC}")
        return []


# ── RAG 主流程 ───────────────────────────────────────────────────

def _print_intro_panel():
    print()
    _print_panel_open("wikiagent rag")
    print(f"{DC}│{NC}  {B}retrieval{NC}    bge-m3 {D}→{NC} chromadb                         {DC}│{NC}")
    print(f"{DC}│{NC}  {B}generation{NC}   modelscope (6) {D}→{NC} openrouter (free)        {DC}│{NC}")
    print(f"{DC}│{NC}  {B}exit{NC}         {C}q{NC}                                          {DC}│{NC}")
    _print_panel_close()
    print()


def _print_answer(answer: str) -> None:
    """answer 内容长度可变，用顶/底分隔线代替逐行右框，避免中英混排破对齐。"""
    print()
    _print_panel_open("answer")
    print(f"{DC}│{NC}")
    for line in answer.splitlines() or [""]:
        print(f"{DC}│{NC}  {line}")
    print(f"{DC}│{NC}")
    _print_panel_close()
    print()


def main():
    _print_intro_panel()

    # 预加载 OpenRouter 缓存
    or_models = fetch_openrouter_rag_models()
    print()

    while True:
        try:
            query = input(f"{BC}›{NC} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query.lower() in ("exit", "quit", "q"):
            break

        # 1. 检索
        t0 = time.time()
        results = search_documents(query, k=5)
        if not results:
            print(f"  {R}✗{NC} {D}知识库中未找到相关内容{NC}\n")
            continue

        context_parts = []
        sources = set()
        for doc, meta, score in results:
            context_parts.append(f"【来源: {meta.get('source', '未知')}】\n{doc}")
            sources.add(meta.get("source", "未知"))
        context = "\n\n---\n\n".join(context_parts)

        retrieve_dt = time.time() - t0
        print()
        print(f"  {D}searching{NC}     {C}{len(results)} chunks{NC} {D}·{NC} {C}{len(sources)} sources{NC} {D}({retrieve_dt:.1f}s){NC}")

        # 2. 构建 Prompt
        system_prompt = (
            "你是一个基于本地知识库的问答助手。请严格根据下面提供的参考资料回答问题。"
            "如果参考资料中没有足够信息，请明确告知'根据现有资料无法回答'，不要编造。"
            "回答时请引用参考的文档来源。"
        )
        user_prompt = f"参考资料:\n\n{context}\n\n用户问题: {query}\n\n请根据参考资料回答。"

        # 3. 调用 LLM（ModelScope 优先 → OpenRouter 降级）
        answer = None
        used_provider = None
        used_model = None
        used_dt = 0.0

        # 3a. ModelScope 池
        ms_key = _get_api_key("MODELSCOPE_API_KEY")
        if ms_key:
            global _ms_index
            from openai import OpenAI
            client = OpenAI(api_key=ms_key, base_url="https://api-inference.modelscope.cn/v1")
            for _ in range(len(_MODELSCOPE_MODELS)):
                model = _MODELSCOPE_MODELS[_ms_index % len(_MODELSCOPE_MODELS)]
                _ms_index += 1
                short = model.split('/')[-1]
                t1 = time.time()
                answer = _call_llm(client, model, system_prompt, user_prompt)
                dt = time.time() - t1
                if answer:
                    used_provider, used_model, used_dt = "modelscope", short, dt
                    print(f"  {D}modelscope{NC}    {short:<24} {dt:>4.1f}s  {G}✓{NC}")
                    break
                else:
                    print(f"  {D}modelscope    {short:<24} {dt:>4.1f}s  ✗{NC}")

        # 3b. OpenRouter 池
        if not answer and or_models:
            or_key = _get_api_key("OPENROUTER_API_KEY")
            if or_key:
                from openai import OpenAI
                client = OpenAI(
                    api_key=or_key,
                    base_url="https://openrouter.ai/api/v1",
                    default_headers={"HTTP-Referer": "https://localhost", "X-Title": "WikiAgent"},
                )
                for m in or_models:
                    mid = m["id"]
                    short = mid.replace(":free", "")
                    t1 = time.time()
                    answer = _call_llm(client, mid, system_prompt, user_prompt)
                    dt = time.time() - t1
                    if answer:
                        used_provider, used_model, used_dt = "openrouter", short, dt
                        print(f"  {D}openrouter{NC}    {short:<24} {dt:>4.1f}s  {G}✓{NC}")
                        break
                    else:
                        print(f"  {D}openrouter    {short:<24} {dt:>4.1f}s  ✗{NC}")

        # 3c. 全部失败
        if not answer:
            print(f"\n  {R}✗{NC} {D}所有 Provider 均失败，无法生成回答{NC}\n")
            continue

        # 4. 输出
        _print_answer(answer)

        print(f"  {B}sources{NC}")
        for s in sorted(sources):
            print(f"   {D}·{NC} {C}{s}{NC}")
        print()


if __name__ == "__main__":
    main()
