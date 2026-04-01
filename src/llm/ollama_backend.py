"""Ollama 本地后端 (离线, 无需 API Key)。"""

import logging

from src.llm.llm_client import LLMClient, LLMResponse

log = logging.getLogger("novel")


class OllamaBackend(LLMClient):
    """基于 ollama Python 包的本地推理后端。"""

    def __init__(self, config: dict) -> None:
        self._model = config.get("model", "qwen2.5:7b")
        self._host = config.get("host", "http://localhost:11434")
        self._client = None

    def _get_client(self):
        if self._client is None:
            from ollama import Client
            from httpx import Timeout

            self._client = Client(host=self._host, timeout=Timeout(120.0))
        return self._client

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        options: dict = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "options": options,
        }
        if json_mode:
            kwargs["format"] = "json"

        try:
            response = client.chat(**kwargs)
        except Exception as exc:
            raise RuntimeError(f"Ollama API 调用失败: {exc}") from exc

        content = response.get("message", {}).get("content", "")

        usage = None
        if "prompt_eval_count" in response:
            usage = {
                "prompt_tokens": response.get("prompt_eval_count", 0),
                "completion_tokens": response.get("eval_count", 0),
                "total_tokens": response.get("prompt_eval_count", 0)
                + response.get("eval_count", 0),
            }

        # Ollama: done_reason = "stop" | "length"
        finish_reason = response.get("done_reason")

        return LLMResponse(
            content=content,
            model=self._model,
            usage=usage,
            finish_reason=finish_reason,
        )
