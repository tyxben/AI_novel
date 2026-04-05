"""LLM 统一抽象接口 + 工厂函数 + 自动检测。"""

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

log = logging.getLogger("novel")


@dataclass
class LLMResponse:
    """LLM 调用返回结果。"""

    content: str
    model: str
    usage: dict | None = field(default=None)
    finish_reason: str | None = field(default=None)
    """停止原因: "stop"=正常结束, "length"=触达 max_tokens 被截断。"""


class LLMClient(ABC):
    """LLM 客户端抽象基类。所有后端需实现 chat() 方法。"""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """发送消息并获取回复。

        Args:
            messages: OpenAI 格式消息列表 [{"role": "system", "content": ...}, ...]
            temperature: 生成温度。
            json_mode: 是否要求返回 JSON 格式。
            max_tokens: 最大输出 token 数（None 使用后端默认值）。

        Returns:
            LLMResponse 对象。
        """
        ...


def _detect_provider() -> tuple[str, dict]:
    """按优先级检测可用的 LLM provider。

    Returns:
        (provider_name, extra_config) 元组。
    """
    if os.environ.get("GEMINI_API_KEY"):
        log.info("自动检测 LLM: 使用 gemini provider")
        return "gemini", {}

    if os.environ.get("DEEPSEEK_API_KEY"):
        log.info("自动检测 LLM: 使用 deepseek provider")
        return "deepseek", {}

    if os.environ.get("OPENAI_API_KEY"):
        log.info("自动检测 LLM: 使用 openai provider")
        return "openai", {}

    # 检测本地 Ollama（使用 stdlib 避免额外依赖）
    try:
        import urllib.request

        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                log.info("自动检测 LLM: 使用 ollama provider")
                return "ollama", {}
    except Exception:
        log.debug("Ollama 服务未响应，跳过")

    raise RuntimeError(
        "未找到可用的 LLM provider。请设置以下环境变量之一: "
        "GEMINI_API_KEY, DEEPSEEK_API_KEY, OPENAI_API_KEY，"
        "或启动本地 Ollama 服务。"
    )


def create_llm_client(config: dict | None = None) -> LLMClient:
    """根据配置创建 LLM 客户端。

    Args:
        config: LLM 配置字典，可包含 provider, model, api_key 等字段。
                provider 支持: auto, openai, deepseek, gemini, ollama。

    Returns:
        对应后端的 LLMClient 实例。
    """
    config = config or {}
    provider = config.get("provider", "auto")
    original_provider = provider

    if provider == "auto":
        provider, extra = _detect_provider()
        config = {**config, **extra}

    try:
        return _create_for_provider(provider, config)
    except RuntimeError:
        if original_provider != "auto":
            # Specified provider failed (e.g. openai key missing) — fallback to auto-detect
            log.warning(
                "指定的 provider '%s' 不可用，尝试自动检测...", original_provider
            )
            try:
                fallback_provider, extra = _detect_provider()
                fallback_config = {k: v for k, v in config.items() if k not in ("provider", "model", "api_key", "api_key_env", "base_url")}
                fallback_config.update(extra)
                return _create_for_provider(fallback_provider, fallback_config)
            except RuntimeError:
                pass  # auto-detect also failed, raise original error
        raise


def _create_for_provider(provider: str, config: dict) -> "LLMClient":
    """Create LLM client for a specific provider."""
    if provider == "openai":
        from src.llm.openai_backend import OpenAIBackend

        return OpenAIBackend(config)

    if provider == "deepseek":
        from src.llm.openai_backend import OpenAIBackend

        deepseek_defaults = {
            "base_url": "https://api.deepseek.com",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model": "deepseek-chat",
        }
        # 用户配置覆盖默认值，但过滤 None 值
        merged = {**deepseek_defaults}
        for k, v in config.items():
            if v is not None:
                merged[k] = v
        return OpenAIBackend(merged)

    if provider == "gemini":
        from src.llm.gemini_backend import GeminiBackend

        return GeminiBackend(config)

    if provider == "ollama":
        from src.llm.ollama_backend import OllamaBackend

        return OllamaBackend(config)

    raise ValueError(f"未知的 LLM provider: {provider}")


def is_llm_available(config: dict | None = None) -> bool:
    """检测是否有可用的 LLM provider（不实际创建客户端）。"""
    config = config or {}
    provider = config.get("provider", "auto")
    if provider != "auto":
        return True
    try:
        _detect_provider()
        return True
    except RuntimeError:
        return False
