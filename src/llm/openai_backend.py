"""OpenAI + DeepSeek 后端 (共用 OpenAI 兼容协议)。"""

import logging
import os

from src.llm.llm_client import LLMClient, LLMResponse

log = logging.getLogger("novel")


class OpenAIBackend(LLMClient):
    """基于 OpenAI SDK 的后端，同时支持 OpenAI 和 DeepSeek。"""

    def __init__(self, config: dict) -> None:
        self._model = config.get("model", "gpt-4o-mini")
        self._base_url = config.get("base_url")
        self._api_key_env = config.get("api_key_env", "OPENAI_API_KEY")
        self._api_key = config.get("api_key") or os.environ.get(self._api_key_env)
        if not self._api_key:
            raise RuntimeError(
                f"未找到 API Key。请设置环境变量 {self._api_key_env} "
                f"或在配置中指定 api_key。"
            )
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            kwargs = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            kwargs["timeout"] = 120.0
            self._client = OpenAI(**kwargs)
        return self._client

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        kwargs: dict = {
            "model": self._model,
            "temperature": temperature,
            "messages": messages,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            usage=usage,
            finish_reason=choice.finish_reason,
        )
