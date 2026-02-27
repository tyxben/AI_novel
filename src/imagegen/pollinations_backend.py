"""Pollinations.ai 图片生成后端 — 完全免费，无需 API Key。"""

import io
import logging
import urllib.parse

from PIL import Image

from src.imagegen.image_generator import ImageGenerator

log = logging.getLogger("novel")


class PollinationsBackend(ImageGenerator):
    """基于 Pollinations.ai 的免费图片生成后端。

    无需注册、无需 API Key，直接 GET 请求即可生成图片。
    """

    BASE_URL = "https://image.pollinations.ai/prompt"

    def __init__(self, config: dict) -> None:
        self._client = None
        self._width = config.get("width", 1024)
        self._height = config.get("height", 1792)
        self._model = config.get("model", "flux")

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=120, follow_redirects=True)
        return self._client

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None

    def __del__(self):
        self.close()

    def generate(self, prompt: str) -> Image.Image:
        """调用 Pollinations.ai 生成图片。"""
        encoded_prompt = urllib.parse.quote(prompt, safe="")
        url = (
            f"{self.BASE_URL}/{encoded_prompt}"
            f"?width={self._width}&height={self._height}"
            f"&model={self._model}&nologo=true"
        )

        client = self._get_client()
        resp = client.get(url)
        resp.raise_for_status()

        image = Image.open(io.BytesIO(resp.content))
        log.debug("Pollinations 生成图片: %dx%d", image.width, image.height)
        return image
