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

        # 兼容新版 ollama SDK (v0.2+) 返回 ChatResponse 对象
        if isinstance(response, dict):
            content = response.get("message", {}).get("content", "")
        else:
            msg = getattr(response, "message", None)
            content = getattr(msg, "content", "") if msg else ""

        usage = None
        _get = response.get if isinstance(response, dict) else lambda k, d=None: getattr(response, k, d)
        if _get("prompt_eval_count"):
            usage = {
                "prompt_tokens": _get("prompt_eval_count", 0) or 0,
                "completion_tokens": _get("eval_count", 0) or 0,
                "total_tokens": (_get("prompt_eval_count", 0) or 0)
                + (_get("eval_count", 0) or 0),
            }

        # Ollama: done_reason = "stop" | "length"
        finish_reason = _get("done_reason")

        return LLMResponse(
            content=content,
            model=self._model,
            usage=usage,
            finish_reason=finish_reason,
        )
