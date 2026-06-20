import asyncio
import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from config import settings

# 不可重试的 HTTP 状态码 — 遇到后直接跳到下一个 Provider
NON_RETRYABLE_STATUS = {400, 401, 403, 422}

# ── NVIDIA NIM 免费 tier 策略参数 ─────────────────────────
NVIDIA_RPM_LIMIT = 24                    # 留 40% 余量，实际硬顶 40 RPM
NVIDIA_MONTHLY_REQUEST_BUDGET = 1000     # 免费 tier 月度请求上限（按请求数计）
NVIDIA_REQUEST_WARN_THRESHOLD = 0.8      # 80% 预警线


class NvidiaRateLimiter:
    """NVIDIA NIM 免费 tier 专用速率限制器 + 请求数监控

    单例模式，进程内共享令牌桶和请求计数。
    持久化到 .nvidia_usage.json，重启后数据不丢失。

    注意: NVIDIA 免费 tier 实际限制为:
      - 速率: 40 RPM (burst ~10 RPM sustained)
      - 月度: ~1,000 requests/month (按请求数计，非 credits)
      - 页面上不显示余额，只显示 Rate Limits
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 令牌桶 (限流 24 RPM)
        self._tokens = float(NVIDIA_RPM_LIMIT)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

        # 请求数追踪 (按月重置)
        self._usage_file = Path(__file__).parent / ".nvidia_usage.json"
        self._requests_this_month = 0
        self._current_month = datetime.now().strftime("%Y-%m")
        self._load_usage()

    def _load_usage(self):
        if self._usage_file.exists():
            try:
                data = json.loads(self._usage_file.read_text())
                saved_month = data.get("month", "")
                if saved_month == self._current_month:
                    self._requests_this_month = data.get("requests", 0)
                else:
                    # 新月自动重置
                    self._requests_this_month = 0
            except Exception:
                self._requests_this_month = 0

    def _save_usage(self):
        try:
            remaining = max(0, NVIDIA_MONTHLY_REQUEST_BUDGET - self._requests_this_month)
            self._usage_file.write_text(
                json.dumps(
                    {
                        "requests": self._requests_this_month,
                        "budget": NVIDIA_MONTHLY_REQUEST_BUDGET,
                        "remaining": remaining,
                        "percent": round(self._requests_this_month / NVIDIA_MONTHLY_REQUEST_BUDGET * 100, 1),
                        "month": self._current_month,
                        "updated_at": datetime.now().isoformat(),
                    },
                    indent=2,
                )
            )
        except Exception as e:
            logger.warning(f"Failed to save NVIDIA usage: {e}")

    @property
    def is_near_limit(self) -> bool:
        """是否接近月度请求上限"""
        return self._requests_this_month >= NVIDIA_MONTHLY_REQUEST_BUDGET * NVIDIA_REQUEST_WARN_THRESHOLD

    @property
    def status(self) -> dict:
        remaining = max(0, NVIDIA_MONTHLY_REQUEST_BUDGET - self._requests_this_month)
        return {
            "requests": self._requests_this_month,
            "budget": NVIDIA_MONTHLY_REQUEST_BUDGET,
            "remaining": remaining,
            "percent": round(self._requests_this_month / NVIDIA_MONTHLY_REQUEST_BUDGET * 100, 1),
            "near_limit": self.is_near_limit,
        }

    async def acquire(self) -> bool:
        """尝试获取一个请求令牌。返回 True 可继续调用，False 需降级。"""
        if self.is_near_limit:
            logger.warning(
                f"⚠️  NVIDIA 本月已用 {self._requests_this_month}/{NVIDIA_MONTHLY_REQUEST_BUDGET} 请求 "
                f"({self.status['percent']}%)。 跳过 NVIDIA 池以避免触顶。"
            )
            return False

        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            refill_rate = NVIDIA_RPM_LIMIT / 60.0  # tokens per second
            self._tokens = min(float(NVIDIA_RPM_LIMIT), self._tokens + elapsed * refill_rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            else:
                wait_needed = (1.0 - self._tokens) / refill_rate
                logger.warning(
                    f"⏳  NVIDIA rate limit active: need to wait {wait_needed:.1f}s. Downgrading."
                )
                return False

    def record_call(self):
        """记录一次成功的 NVIDIA 调用"""
        self._requests_this_month += 1
        self._save_usage()
        logger.info(
            f"📊  NVIDIA 本月请求: {self._requests_this_month}/{NVIDIA_MONTHLY_REQUEST_BUDGET} "
            f"(剩余 {NVIDIA_MONTHLY_REQUEST_BUDGET - self._requests_this_month})"
        )


# ── Provider 配置 (含 Circuit Breaker) ────────────────────

class ProviderConfig:
    """单个 LLM Provider 的配置，内置三态熔断器 (CLOSED → OPEN → HALF-OPEN)"""
    def __init__(self, name: str, api_base: str, model: str, api_keys: list[str]):
        self.name = name
        self.api_base = api_base
        self.model = model
        self.api_keys = api_keys
        self._key_index = 0

        # Circuit Breaker 状态
        self._fail_count = 0
        self._last_fail_time: float = 0

    def rotate_key(self):
        if self.api_keys:
            self._key_index = (self._key_index + 1) % len(self.api_keys)

    @property
    def current_key(self) -> str:
        if not self.api_keys:
            return ""
        return self.api_keys[self._key_index]

    @property
    def is_available(self) -> bool:
        """熔断器健康检查: 连续失败达到阈值后进入冷却期，冷却结束后允许单次探测"""
        if self._fail_count < settings.cb_fail_threshold:
            return True
        # 冷却期已过 → HALF-OPEN，允许一次探测
        return (time.monotonic() - self._last_fail_time) >= settings.cb_cooldown_seconds

    def mark_success(self):
        """调用成功 → 重置熔断计数器"""
        self._fail_count = 0

    def mark_failed(self):
        """调用失败 → 累积失败次数并记录时间"""
        self._fail_count += 1
        self._last_fail_time = time.monotonic()


def _build_nvidia_extract_pool() -> list[ProviderConfig]:
    """构建 NVIDIA 内部多模型 Extract 池（按 JSON 稳定性 + 速度排序）"""
    keys = settings.parse_keys(settings.nvidia_api_key) or settings.parse_keys(os.getenv("NVIDAI_API_KEY"))
    if not keys:
        return []

    base = "https://integrate.api.nvidia.com/v1"
    pool = []

    # (name, model_id, size_category)
    # size_category 用于 credits 估算: small/medium/large/xlarge
    models = [
        ("NVIDIA-Qwen3", "qwen/qwen3-coder-480b-a35b-instruct", "xlarge"),      # 1s, 480B, 最强
        ("NVIDIA-Mistral", "mistralai/mistral-large-3-675b-instruct-2512", "xlarge"),  # 2s, 675B
        ("NVIDIA-Minimax", "minimaxai/minimax-m2.7", "large"),                  # 3s, 230B
        ("NVIDIA-Llama", "meta/llama-3.3-70b-instruct", "medium"),              # 10s, 70B
        ("NVIDIA-Gemma", "google/gemma-4-31b-it", "small"),                     # 5s, 31B, 省 credits
    ]

    for name, model, size in models:
        p = ProviderConfig(name, base, model, keys)
        p._nvidia_size = size
        pool.append(p)

    return pool


def _build_extract_chain() -> list[ProviderConfig]:
    """构建【极速提取链】: NVIDIA Pool → Groq → ModelScope → AIHubMix → OpenRouter → ZhipuAI → Tencent"""
    chain = []

    # L1: NVIDIA 多模型池（内部 5 模型轮询，附限速器）
    chain.extend(_build_nvidia_extract_pool())

    # L2: Groq (Qwen3 32B)
    keys = settings.parse_keys(settings.groq_api_key)
    if keys:
        chain.append(ProviderConfig("Groq", "https://api.groq.com/openai/v1", "qwen/qwen3-32b", keys))

    # L3: ModelScope (DS V4 Flash)
    keys = settings.parse_keys(settings.modelscope_api_key)
    if keys:
        chain.append(ProviderConfig("ModelScope", "https://api-inference.modelscope.cn/v1", "deepseek-ai/DeepSeek-V4-Flash", keys))

    # L4: AIHubMix (gpt-4.1-free: 快速提取)
    # 可用: coding-minimax-m2.7-free, gpt-4.1-free
    # 限流: coding-glm-5.1-free, k2.6-code-preview-free
    # 不可用: ling-2.6-flash-free(404), qwen3.6-plus-preview-free(400)
    keys = settings.parse_keys(settings.aihubmix_api_key)
    if keys:
        chain.append(ProviderConfig("AIHubMix", "https://aihubmix.com/v1", "gpt-4.1-free", keys))

    # L5: OpenRouter (GLM 4.5 Air Free)
    keys = settings.parse_keys(settings.openrouter_api_key)
    if keys:
        chain.append(ProviderConfig("OpenRouter", "https://openrouter.ai/api/v1", "z-ai/glm-4.5-air:free", keys))

    # L6: ZhipuAI 主账号 (GLM 4.7 Flash)
    keys = settings.parse_keys(settings.zhipuai_api_key)
    if keys:
        chain.append(ProviderConfig("ZhipuAI", "https://open.bigmodel.cn/api/paas/v4", "glm-4.7-flash", keys))

    # L6b: ZhipuAI 备用账号 (GLM 4.7 Flash)
    keys = settings.parse_keys(settings.zhipuai_api_key_backup)
    if keys:
        chain.append(ProviderConfig("ZhipuAI-Backup", "https://open.bigmodel.cn/api/paas/v4", "glm-4.7-flash", keys))

    # L7: Tencent (Hunyuan Lite)
    keys = settings.parse_keys(settings.hunyuan_api_key) or settings.parse_keys(settings.ai_api_key)
    if keys:
        base = settings.hunyuan_base_url or settings.ai_api_base or "https://api.hunyuan.cloud.tencent.com/v1"
        chain.append(ProviderConfig("Tencent", base, "hunyuan-lite", keys))

    return chain


def _build_generate_chain() -> list[ProviderConfig]:
    """构建【语义增强链】: Tencent-TokenHub → AIHubMix → OpenRouter → ZhipuAI → Tencent-Hunyuan"""
    chain = []

    # L0: Tencent TokenHub (hy3-preview: 100万免费token，主力生成)
    keys = settings.parse_keys(settings.tokenhub_api_key)
    if keys:
        chain.append(ProviderConfig("Tencent-TokenHub", settings.tokenhub_base_url, "hy3-preview", keys))

    # L1: AIHubMix (k2.6-code-preview-free: 综合实力最强，hy3-preview 的 fallback)
    # 次选: coding-minimax-m2.7-free (2.7版本大模型，实力强)
    # 降级: coding-glm-5.1-free
    # 不可用: ling-2.6-flash-free(404), qwen3.6-plus-preview-free(400)
    keys = settings.parse_keys(settings.aihubmix_api_key)
    if keys:
        chain.append(ProviderConfig("AIHubMix-Kimi", "https://aihubmix.com/v1", "k2.6-code-preview-free", keys))
        chain.append(ProviderConfig("AIHubMix-MiniMax", "https://aihubmix.com/v1", "coding-minimax-m2.7-free", keys))
        chain.append(ProviderConfig("AIHubMix-GLM5", "https://aihubmix.com/v1", "coding-glm-5.1-free", keys))

    # L2: OpenRouter (GLM 4.5 Air Free)
    keys = settings.parse_keys(settings.openrouter_api_key)
    if keys:
        chain.append(ProviderConfig("OpenRouter", "https://openrouter.ai/api/v1", "z-ai/glm-4.5-air:free", keys))

    # L3: ZhipuAI 主账号 (GLM 4.7 Flash)
    keys = settings.parse_keys(settings.zhipuai_api_key)
    if keys:
        chain.append(ProviderConfig("ZhipuAI", "https://open.bigmodel.cn/api/paas/v4", "glm-4.7-flash", keys))

    # L3b: ZhipuAI 备用账号 (GLM 4.7 Flash)
    keys = settings.parse_keys(settings.zhipuai_api_key_backup)
    if keys:
        chain.append(ProviderConfig("ZhipuAI-Backup", "https://open.bigmodel.cn/api/paas/v4", "glm-4.7-flash", keys))

    # L4: Tencent (Hunyuan Lite)
    keys = settings.parse_keys(settings.hunyuan_api_key) or settings.parse_keys(settings.ai_api_key)
    if keys:
        base = settings.hunyuan_base_url or settings.ai_api_base or "https://api.hunyuan.cloud.tencent.com/v1"
        chain.append(ProviderConfig("Tencent", base, "hunyuan-lite", keys))

    return chain


# ── 核心服务 ─────────────────────────────────────────────

class WikiService:
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.raw_dir = self.base_dir / "raw"
        self.wiki_dir = self.base_dir / "wiki"
        self.schema_dir = self.base_dir / "schema"
        self.processed_hashes_path = self.base_dir / "processed_hashes.json"

        # 确保子目录存在
        for d in ["entities", "concepts", "sources"]:
            (self.wiki_dir / d).mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        # 解析 wiki_dir 的绝对路径，用于安全校验
        self._wiki_dir_resolved = self.wiki_dir.resolve()

        # 构建双路径 Provider 优先级链
        self.extract_providers = _build_extract_chain()
        self.generate_providers = _build_generate_chain()

        # 兼容旧代码，将 extract 作为默认 providers
        self.providers = self.extract_providers

        if not self.extract_providers or not self.generate_providers:
            logger.error("⚠️ 未检测到完整的 API Key 配置！请检查 .zshenv.secrets")
        else:
            logger.info(f"Extract Path: {' → '.join([p.name for p in self.extract_providers])}")
            logger.info(f"Generate Path: {' → '.join([p.name for p in self.generate_providers])}")

        # 加载已处理 hash 记录
        self._processed_hashes = self._load_processed_hashes()

        # 复用 httpx 客户端 (性能: 避免每次调用都创建新连接)
        self._http_client: httpx.AsyncClient | None = None

        # 文件写入锁 (并发 Worker 安全: 保护 index.md / log.md / processed_hashes.json)
        self._file_lock = asyncio.Lock()

    # ── 去重层 ────────────────────────────────────────────

    def _load_processed_hashes(self) -> set:
        if self.processed_hashes_path.exists():
            try:
                return set(json.loads(self.processed_hashes_path.read_text(encoding="utf-8")))
            except Exception:
                return set()
        return set()

    def _save_processed_hash(self, content_hash: str):
        """原子写入 processed_hashes.json，并保留备份副本防止损坏"""
        self._processed_hashes.add(content_hash)
        try:
            data = json.dumps(sorted(self._processed_hashes), ensure_ascii=False, indent=2)
            temp_path = self.processed_hashes_path.with_suffix(".json.tmp")
            backup_path = self.processed_hashes_path.with_suffix(".json.bak")

            # 1. 写入临时文件
            temp_path.write_text(data, encoding="utf-8")

            # 2. 若原文件存在，先备份
            if self.processed_hashes_path.exists():
                self.processed_hashes_path.replace(backup_path)

            # 3. 原子替换
            temp_path.replace(self.processed_hashes_path)
        except OSError as e:
            logger.warning(f"Failed to persist processed hash: {e}")

    # ── 流水线步骤（可独立测试、监控、重试） ──────────────

    def _compute_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:12]

    def _is_duplicate(self, content_hash: str, force: bool = False) -> bool:
        return content_hash in self._processed_hashes and not force

    async def _persist_raw(self, payload: dict[str, Any], content_hash: str) -> Path:
        """Step 2: 持久化原始 payload 到 raw/ 目录"""
        now = datetime.now()
        source_project = payload["source_project"]
        raw_filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{source_project}_{content_hash}.json"
        raw_path = self.raw_dir / raw_filename

        if not raw_path.exists():
            raw_payload = {
                "source": source_project,
                "topic": payload["topic"],
                "content": payload["content"],
                "metadata": payload.get("metadata", {}),
                "ingested_at": now.isoformat(),
                "hash": content_hash
            }
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(raw_payload, f, ensure_ascii=False, indent=2)
        return raw_path

    async def _run_analyze_phase(self, content: str, source_project: str, topic: str) -> dict[str, Any]:
        """Step 3: Analyze Phase — 实体与概念提取 (极速提取链)"""
        purpose = self._read_file(self.schema_dir / "purpose.md")
        analysis_prompt_tmpl = self._read_file(self.schema_dir / "analyze_prompt.md")
        analysis_input = f"SOURCE: {source_project}\nTOPIC: {topic}\nCONTENT: {content}\n\nPURPOSE:\n{purpose}"
        return await self._call_llm_json(
            analysis_prompt_tmpl, analysis_input, providers=self.extract_providers)

    async def _run_generate_phase(
        self,
        analysis_results: dict[str, Any],
        content: str,
        content_hash: str,
        source_project: str
    ) -> str:
        """Step 4: Generate Phase — Markdown 页面生成 (语义增强链)"""
        candidate_context = self._build_candidate_context(analysis_results)
        generate_prompt_tmpl = self._read_file(self.schema_dir / "generate_prompt.md")
        gen_input = (
            f"ANALYSIS_RESULTS: {json.dumps(analysis_results, ensure_ascii=False)}\n"
            f"ORIGINAL_CONTENT: {content}\n\n"
            f"CANDIDATE_CONTEXT:\n{candidate_context}"
        )

        # 替换模版变量
        generate_prompt_tmpl = generate_prompt_tmpl.replace(
            "{{TIMESTAMP}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        generate_prompt_tmpl = generate_prompt_tmpl.replace("{{HASH}}", content_hash)
        generate_prompt_tmpl = generate_prompt_tmpl.replace("{{SOURCE}}", source_project)

        return await self._call_llm_text(
            generate_prompt_tmpl, gen_input, providers=self.generate_providers)

    async def _commit_results(
        self,
        analysis_results: dict[str, Any],
        source_project: str,
        topic: str,
        content_hash: str
    ):
        """Step 6: 原子提交 — 更新索引、写日志、标记已处理"""
        async with self._file_lock:
            self._update_and_sanitize_index(analysis_results)
            entities = ', '.join([e['name'] for e in analysis_results.get('entities', [])])
            log_entry = f"- **[{source_project.upper()}]**: 摄入 `{topic}`，识别实体: {entities}"
            self._append_to_log(log_entry)
            self._save_processed_hash(content_hash)

    # ── 主流程编排器 ────────────────────────────────────────

    async def process_ingest_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        异步处理单条摄入任务 (由 Queue Worker 调用)。
        将完整流水线拆分为 7 个可独立监控的步骤。
        """
        source_project = payload.get("source_project", "unknown")
        topic = payload.get("topic", "unknown")
        content = payload.get("content", "")

        try:
            # Step 1: 去重检查
            content_hash = self._compute_content_hash(content)
            if self._is_duplicate(content_hash, payload.get("force")):
                logger.info(f"⏭️  Skipping duplicate: {topic} (hash: {content_hash})")
                return {"status": "skipped", "reason": "duplicate", "hash": content_hash}

            logger.info(f"Processing ingest task: {topic} from {source_project}")

            # Step 2: 持久化 Raw
            await self._persist_raw(payload, content_hash)

            # Step 3: Analyze
            analysis_results = await self._run_analyze_phase(content, source_project, topic)
            if analysis_results.get("error"):
                logger.error(f"Analyze phase failed for {topic}: {analysis_results['error']}")
                return {"status": "failed", "phase": "analyze", "error": analysis_results["error"], "hash": content_hash}

            # Step 4: Generate
            generated_md = await self._run_generate_phase(
                analysis_results, content, content_hash, source_project)

            # Step 5: 写入文件
            created_pages = self._process_generated_markdown(generated_md)

            # Step 6: 提交结果（索引 + 日志 + hash）
            await self._commit_results(analysis_results, source_project, topic, content_hash)

            # Step 7: 向量同步
            await self._trigger_chroma_sync(created_pages)

            logger.success(f"✅ Successfully processed {topic}. Created/Updated {len(created_pages)} pages.")
            return {"status": "success", "pages": created_pages, "hash": content_hash}

        except Exception as e:
            logger.exception(f"Failed to process ingest task: {topic}")
            return {"status": "failed", "phase": "unknown", "error": str(e), "topic": topic}

    # ── 候选上下文构建 ────────────────────────────────────

    def _build_candidate_context(self, analysis: dict[str, Any]) -> str:
        """根据提取的实体，在本地查找已有的 Markdown 内容作为候选上下文"""
        candidates = []
        entities_to_check = [e["name"] for e in analysis.get("entities", [])]
        concepts_to_check = [c["name"] for c in analysis.get("concepts", [])]

        for name in entities_to_check + concepts_to_check:
            entity_path = self.wiki_dir / "entities" / f"{name}.md"
            concept_path = self.wiki_dir / "concepts" / f"{name}.md"

            if entity_path.exists():
                candidates.append(f"--- EXISTING ENTITY: {name} ---\n{entity_path.read_text(encoding='utf-8')}")
            elif concept_path.exists():
                candidates.append(f"--- EXISTING CONCEPT: {name} ---\n{concept_path.read_text(encoding='utf-8')}")

        if not candidates:
            return "No existing entities found."
        return "\n\n".join(candidates)

    # ── LLM 调用核心 (DRY) ────────────────────────────────

    async def _get_http_client(self) -> httpx.AsyncClient:
        """复用 httpx 客户端，避免每次调用创建/销毁连接的开销"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=120.0)
        return self._http_client

    async def _call_llm_core(
        self,
        system_prompt: str,
        user_content: str,
        max_retries: int = 3,
        providers: list[ProviderConfig] | None = None,
        response_validator: Callable[[str], None] | None = None,
    ) -> str:
        """
        核心 LLM 调用方法。遍历 Provider 优先级链，集成 Circuit Breaker 熔断感知。

        Args:
            providers: 可选的自定义 Provider 链。为 None 时使用默认的 self.providers。
            response_validator: 可选响应校验回调。若校验抛异常，视作可重试错误，
                自动触发同 provider 重试 / fallback 到下一 provider，避免 200 + 残缺响应静默失败。
        """
        target_providers = providers or self.providers
        if not target_providers:
            raise RuntimeError("No LLM providers configured.")

        last_error = None
        client = await self._get_http_client()
        skipped = []

        for provider in target_providers:
            # Circuit Breaker: 跳过处于熔断冷却期的 Provider
            if not provider.is_available:
                skipped.append(provider.name)
                continue

            # NVIDIA 专属速率限制: 超限或 credits 不足时跳过整个 NVIDIA 池
            if provider.name.startswith("NVIDIA-"):
                limiter = NvidiaRateLimiter()
                if not await limiter.acquire():
                    skipped.append(provider.name)
                    continue

            for attempt in range(max_retries):
                try:
                    resp = await client.post(
                        f"{provider.api_base}/chat/completions",
                        headers={"Authorization": f"Bearer {provider.current_key}"},
                        json={
                            "model": provider.model,
                            "max_tokens": 4096,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_content}
                            ]
                        },
                    )

                    # 不可重试错误 (400/401/403/422) → 直接跳到下一个 Provider
                    if resp.status_code in NON_RETRYABLE_STATUS:
                        logger.warning(
                            f"[{provider.name}] Non-retryable {resp.status_code}: "
                            f"{resp.text[:150]}. Skipping to next provider.")
                        provider.mark_failed()
                        break

                    # 429 Rate Limit → 轮换 Key + 指数退避 (不消耗通用重试)
                    if resp.status_code == 429:
                        logger.warning(f"[{provider.name}] 429 Rate Limit. Rotating key...")
                        provider.rotate_key()
                        await asyncio.sleep(2 * (attempt + 1))
                        continue

                    # 其他非 200 错误 → 作为可重试错误
                    if resp.status_code != 200:
                        logger.error(f"[{provider.name}] API Error {resp.status_code}: {resp.text[:200]}")
                        resp.raise_for_status()

                    # ✅ HTTP 200 → 拿到 raw content
                    content = resp.json()["choices"][0]["message"]["content"]

                    # 可选响应校验：若校验失败（如 JSON 不可解析），视作可重试错误
                    # 不消耗 provider 健康度（mark_success 推迟到校验通过之后）
                    if response_validator is not None:
                        try:
                            response_validator(content)
                        except Exception as ve:
                            last_error = ve
                            logger.warning(
                                f"[{provider.name}] Response validator rejected output "
                                f"(attempt {attempt+1}/{max_retries}): {ve}"
                            )
                            if attempt < max_retries - 1:
                                provider.rotate_key()
                                await asyncio.sleep(1)
                            continue  # 进入同 provider 下一次重试，或耗尽后切下一 provider

                    # ✅ 校验通过 → 重置熔断器
                    provider.mark_success()

                    # NVIDIA 专属: 记录请求数
                    if provider.name.startswith("NVIDIA-"):
                        NvidiaRateLimiter().record_call()

                    return content

                except Exception as e:
                    last_error = e
                    logger.warning(f"[{provider.name}] Attempt {attempt+1}/{max_retries} failed: {e}")
                    if attempt < max_retries - 1:
                        provider.rotate_key()
                        await asyncio.sleep(2)

            # 当前 Provider 已耗尽所有重试 → 标记失败并降级
            provider.mark_failed()
            logger.warning(f"[{provider.name}] Exhausted. Falling back to next provider...")

        if skipped:
            logger.info(f"Skipped providers in cooldown: {', '.join(skipped)}")

        raise RuntimeError(f"All providers exhausted. Last error: {last_error}")

    async def _call_llm_json(
        self,
        system_prompt: str,
        user_content: str,
        max_retries: int = 3,
        providers: list[ProviderConfig] | None = None
    ) -> dict[str, Any]:
        """调用 LLM 并解析 JSON 响应。

        把 _extract_json 作为 response_validator 注入 _call_llm_core：解析失败时
        会被 core 的内层循环作为可重试错误处理，自动重试 / 切 provider，避免
        '200 + 残缺 JSON' 静默失败。"""
        try:
            raw_text = await self._call_llm_core(
                system_prompt, user_content, max_retries,
                providers=providers,
                response_validator=lambda t: self._extract_json(t),
            )
            logger.info(f"LLM JSON response snippet: {raw_text[:200]}")
            return self._extract_json(raw_text)
        except Exception as e:
            logger.error(f"LLM JSON call failed: {e}")
            return {"error": str(e), "entities": [], "concepts": []}

    async def _call_llm_text(
        self,
        system_prompt: str,
        user_content: str,
        max_retries: int = 3,
        providers: list[ProviderConfig] | None = None
    ) -> str:
        """调用 LLM 并返回纯文本响应"""
        try:
            return await self._call_llm_core(system_prompt, user_content, max_retries, providers=providers)
        except Exception as e:
            logger.error(f"LLM Text call failed: {e}")
            return f"Error: {e}"

    # ── JSON 解析鲁棒化 ──────────────────────────────────

    def _extract_json(self, raw_text: str) -> dict[str, Any]:
        """多策略提取 JSON，处理大模型各种包裹格式。

        三种策略均失败时抛 ValueError，以便 _call_llm_core 内部循环将其视作可重试错误，
        自动触发 provider 链 fallback（避免 NVIDIA-Qwen3 截断时整个任务直接失败）。"""
        # 策略1: 直接解析
        try:
            return json.loads(raw_text.strip())
        except (json.JSONDecodeError, ValueError):
            pass

        # 策略2: 提取 ```json ... ``` 代码块 (不区分大小写)
        match = re.search(r'```[jJ][sS][oO][nN]?\s*\n(.*?)\n\s*```', raw_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except (json.JSONDecodeError, ValueError):
                pass

        # 策略3: 提取第一个 { ... } 块 (贪婪匹配最外层大括号)
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except (json.JSONDecodeError, ValueError):
                pass

        raise ValueError(f"Cannot parse JSON from response: {raw_text[:300]}")

    # ── Markdown 生成处理 ─────────────────────────────────

    def _process_generated_markdown(self, raw_md: str) -> list[str]:
        pages = []
        chunks = re.split(r'--- FILE: (.*?) ---', raw_md)
        if len(chunks) > 1:
            for i in range(1, len(chunks), 2):
                path_str = chunks[i].strip().lstrip("/")
                content = chunks[i+1].strip()
                # 去除大模型可能包裹的 markdown 代码块标识（多种变体）
                content = re.sub(r"^```[a-zA-Z]*\s*\n?", "", content)
                content = re.sub(r"\n?```\s*$", "", content)
                content = content.strip()

                full_path = (self.wiki_dir / path_str).resolve()

                # 安全校验: 使用 resolve() 防止符号链接绕过
                if not str(full_path).startswith(str(self._wiki_dir_resolved)):
                    logger.warning(f"Detected potential path traversal attempt: {path_str}")
                    continue

                full_path.parent.mkdir(parents=True, exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
                pages.append(str(full_path))
        return pages

    # ── Index 管理 ────────────────────────────────────────

    def _update_and_sanitize_index(self, analysis: dict[str, Any]):
        """更新 index.md 并立即清洗悬空链接 (合并为单次读写，避免两次磁盘 I/O)"""
        index_path = self.wiki_dir / "index.md"
        content = self._read_file(index_path)
        if not content:
            return

        # Phase 1: 追加新链接
        for entity in analysis.get("entities", []):
            if f"[[{entity['name']}]]" not in content:
                content = content.replace(
                    "<!-- LLM-MANAGED SECTION START: entities -->",
                    f"<!-- LLM-MANAGED SECTION START: entities -->\n- [[{entity['name']}]]"
                )

        for concept in analysis.get("concepts", []):
            if f"[[{concept['name']}]]" not in content:
                content = content.replace(
                    "<!-- LLM-MANAGED SECTION START: concepts -->",
                    f"<!-- LLM-MANAGED SECTION START: concepts -->\n- [[{concept['name']}]]"
                )

        # Phase 2: 清洗悬空链接
        existing_names = set()
        for subdir in ["entities", "concepts"]:
            dirpath = self.wiki_dir / subdir
            if dirpath.exists():
                for f in dirpath.iterdir():
                    if f.suffix == ".md":
                        existing_names.add(f.stem)

        lines = content.split("\n")
        cleaned_lines = []
        removed = []

        for line in lines:
            match = re.match(r'^- \[\[(.+?)\]\]\s*$', line)
            if match:
                link_name = match.group(1)
                if link_name not in existing_names:
                    removed.append(link_name)
                    continue
            cleaned_lines.append(line)

        if removed:
            logger.info(f"🧹 Index 清洗: 移除 {len(removed)} 个悬空链接: {removed}")

        # 单次写入
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("\n".join(cleaned_lines))

    # ── 工具方法 ──────────────────────────────────────────

    def _read_file(self, path: Path) -> str:
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _append_to_log(self, entry: str):
        log_path = self.wiki_dir / "log.md"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{entry} (Time: {datetime.now().strftime('%H:%M:%S')})")

    async def _trigger_chroma_sync(self, file_paths: list[str]):
        """调用 sync_vector_db 模块同步文件到 ChromaDB"""
        try:
            from scripts.sync_vector_db import upsert_markdowns
            await upsert_markdowns(file_paths)
        except Exception as e:
            logger.error(f"Failed to trigger ChromaDB sync: {e}")
