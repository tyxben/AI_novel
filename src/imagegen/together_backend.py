"""Together.ai 图片生成后端 (Flux.1 Schnell 免费)。"""

import base64
import io
import logging
import os
import time

from PIL import Image

from src.imagegen.image_generator import ImageGenerator

log = logging.getLogger("novel")


class TogetherBackend(ImageGenerator):
    """基于 Together.ai REST API 的云端图片生成后端。"""

    API_URL = "https://api.together.xyz/v1/images/generations"

    def __init__(self, config: dict) -> None:
        self._client = None
        self._model = config.get("model", "black-forest-labs/FLUX.1-schnell-Free")
        self._steps = config.get("steps", 4)
        self._width = config.get("width", 1024)
        self._height = config.get("height", 1792)
        self._api_key = config.get("api_key") or os.environ.get("TOGETHER_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "Together.ai 需要 API Key。请设置环境变量 TOGETHER_API_KEY。"
            )

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=120)
        return self._client

    def close(self):
        """关闭 HTTP 客户端连接。"""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()

    _MAX_RETRIES = 3

    def generate(self, prompt: str) -> Image.Image:
        """调用 Together.ai API 生成图片，遇到限流/服务器错误/网络错误自动重试。"""
        import httpx

        client = self._get_client()
        last_exc: Exception | None = None

        for attempt in range(self._MAX_RETRIES):
            try:
                response = client.post(
                    self.API_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "width": self._width,
                        "height": self._height,
                        "steps": self._steps,
                        "n": 1,
                        "response_format": "b64_json",
                    },
                )
            except httpx.RequestError as exc:
                last_exc = exc
                delay = 2 ** attempt
                log.warning(
                    "Together.ai 网络错误，%ds 后重试 (%d/%d): %s",
                    delay, attempt + 1, self._MAX_RETRIES, exc,
                )
                time.sleep(delay)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
                delay = 2 ** attempt
                log.warning(
                    "Together.ai HTTP %d，%ds 后重试 (%d/%d)",
                    response.status_code, delay, attempt + 1, self._MAX_RETRIES,
                )
                time.sleep(delay)
                continue

            response.raise_for_status()

            data = response.json()
            b64_data = data["data"][0]["b64_json"]
            image_bytes = base64.b64decode(b64_data)
            image = Image.open(io.BytesIO(image_bytes))

            log.debug("Together.ai 生成图片: %dx%d", image.width, image.height)
            return image

        raise RuntimeError(
            f"Together.ai 图片生成失败 ({self._MAX_RETRIES}次重试): {last_exc}"
        ) from last_exc
