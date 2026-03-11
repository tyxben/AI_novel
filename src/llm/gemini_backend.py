"""Google Gemini 后端 (免费 1000次/天)。"""

import logging
import os

from src.llm.llm_client import LLMClient, LLMResponse

log = logging.getLogger("novel")


class GeminiBackend(LLMClient):
    """基于 google-genai SDK 的 Gemini 后端。"""

    def __init__(self, config: dict) -> None:
        self._model = config.get("model", "gemini-2.0-flash-lite")
        self._api_key = config.get("api_key") or os.environ.get("GEMINI_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "未找到 Gemini API Key。请设置环境变量 GEMINI_API_KEY "
                "或在配置中指定 api_key。"
            )
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        from google.genai import types

        # 分离 system 消息和用户消息
        system_parts = []
        contents = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                system_parts.append(content)
            elif role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=content)]))
            elif role == "assistant":
                contents.append(types.Content(role="model", parts=[types.Part(text=content)]))

        # 构建生成配置
        gen_config_kwargs: dict = {"temperature": temperature}
        if json_mode:
            gen_config_kwargs["response_mime_type"] = "application/json"
        if max_tokens is not None:
            gen_config_kwargs["max_output_tokens"] = max_tokens
        gen_config = types.GenerateContentConfig(
            **gen_config_kwargs,
            system_instruction="\n".join(system_parts) if system_parts else None,
        )

        response = client.models.generate_content(
            model=self._model,
            contents=contents,
            config=gen_config,
        )

        # 安全获取文本（response.text 在内容被安全过滤时可能抛出 ValueError）
        text = ""
        try:
            text = response.text or ""
        except ValueError:
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    text = candidate.content.parts[0].text or ""

        usage = None
        if response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
                "total_tokens": response.usage_metadata.total_token_count,
            }

        return LLMResponse(
            content=text,
            model=self._model,
            usage=usage,
        )
