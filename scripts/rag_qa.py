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

    print("🌐 正在从 OpenRouter 获取免费模型列表...")
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
        print(f"✅ 发现 {len(models)} 个适合 RAG 的免费模型")
        return models

    except Exception as e:
        print(f"⚠️ 获取 OpenRouter 模型失败: {e}")
        return []


# ── RAG 主流程 ───────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("💡 WikiAgent RAG 问答终端")
    print("   模型: ModelScope 6 模型轮换 + OpenRouter 免费模型池")
    print("   检索: bge-m3 + ChromaDB (常驻/本地回退)")
    print("=" * 50)
    print()

    # 预加载 OpenRouter 缓存
    or_models = fetch_openrouter_rag_models()

    while True:
        query = input("请输入你想问的问题: ").strip()
        if not query:
            continue
        if query.lower() in ("exit", "quit", "q"):
            break

        # 1. 检索
        print("\n🔍 正在从知识库检索相关内容...")
        results = search_documents(query, k=5)
        if not results:
            print("❌ 知识库中未找到相关内容。")
            continue

        context_parts = []
        sources = set()
        for doc, meta, score in results:
            context_parts.append(f"【来源: {meta.get('source', '未知')}】\n{doc}")
            sources.add(meta.get("source", "未知"))
        context = "\n\n---\n\n".join(context_parts)

        # 2. 构建 Prompt
        system_prompt = (
            "你是一个基于本地知识库的问答助手。请严格根据下面提供的参考资料回答问题。"
            "如果参考资料中没有足够信息，请明确告知'根据现有资料无法回答'，不要编造。"
            "回答时请引用参考的文档来源。"
        )
        user_prompt = f"参考资料:\n\n{context}\n\n用户问题: {query}\n\n请根据参考资料回答。"

        # 3. 调用 LLM（ModelScope 优先 → OpenRouter 降级）
        print("🤖 正在调用 LLM 生成回答...")

        # 3a. ModelScope 池
        ms_key = _get_api_key("MODELSCOPE_API_KEY")
        answer = None
        if ms_key:
            global _ms_index
            from openai import OpenAI
            client = OpenAI(api_key=ms_key, base_url="https://api-inference.modelscope.cn/v1")
            for _ in range(len(_MODELSCOPE_MODELS)):
                model = _MODELSCOPE_MODELS[_ms_index % len(_MODELSCOPE_MODELS)]
                _ms_index += 1
                print(f"  → 尝试 ModelScope / {model.split('/')[-1]} ...")
                answer = _call_llm(client, model, system_prompt, user_prompt)
                if answer:
                    print(f"  ✅ ModelScope / {model.split('/')[-1]} 响应成功")
                    break

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
                    print(f"  → 尝试 OpenRouter / {mid} ...")
                    answer = _call_llm(client, mid, system_prompt, user_prompt)
                    if answer:
                        print(f"  ✅ OpenRouter / {mid} 响应成功")
                        break

        # 3c. 全部失败
        if not answer:
            print("❌ 所有 Provider 均失败，无法生成回答。")
            continue

        # 4. 输出
        print("\n" + "=" * 50)
        print("💡 回答：")
        print("=" * 50)
        print(answer)
        print("=" * 50)
        print(f"\n📄 本次回答参考了以下文件：")
        for s in sorted(sources):
            print(f"   - {s}")
        print()


if __name__ == "__main__":
    main()
