"""
WikiAgent 统一配置中心。
所有环境变量、系统参数、Provider 配置集中在此管理，支持 .env 文件热加载与验证。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """集中管理所有环境变量与系统参数"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 允许环境中存在未定义变量，不报错
    )

    # ── LLM Provider API Keys（支持逗号分隔的多 Key） ─────────────
    nvidia_api_key: str | None = None
    groq_api_key: str | None = None
    modelscope_api_key: str | None = None
    aihubmix_api_key: str | None = None
    openrouter_api_key: str | None = None
    zhipuai_api_key: str | None = None
    zhipuai_api_key_backup: str | None = None
    hunyuan_api_key: str | None = None
    tokenhub_api_key: str | None = None    # 腾讯 TokenHub (hy3-preview)
    ai_api_key: str | None = None          # 兼容旧配置名
    gemini_api_key: str | None = None
    siliconflow_api_key: str | None = None

    # ── Provider Base URLs ────────────────────────────────────────
    hunyuan_base_url: str = "https://api.hunyuan.cloud.tencent.com/v1"
    tokenhub_base_url: str = "https://tokenhub.tencentmaas.com/v1"
    ai_api_base: str | None = None

    # ── Circuit Breaker 参数 ─────────────────────────────────────
    cb_fail_threshold: int = 3
    cb_cooldown_seconds: int = 60

    # ── LLM 调用参数 ─────────────────────────────────────────────
    llm_max_retries: int = 3
    llm_timeout: float = 120.0

    # ── 系统路径 ─────────────────────────────────────────────────
    wiki_base_dir: str | None = None       # 默认使用当前工作目录

    # ── 功能开关 ─────────────────────────────────────────────────
    dedup_enabled: bool = True
    chroma_sync_enabled: bool = True

    # ── 工具方法 ─────────────────────────────────────────────────
    def parse_keys(self, raw: str | None) -> list[str]:
        """从逗号分隔的字符串中解析 API Key 列表"""
        if not raw:
            return []
        return [k.strip() for k in raw.split(",") if k.strip()]


# 全局单例 —— 在模块导入时即完成解析与验证
settings = Settings()
