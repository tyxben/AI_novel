"""SiliconFlow (硅基流动) 图片生成后端 — FLUX.1 Schnell 免费。"""

import io
import logging
import os
import time

from PIL import Image

from src.imagegen.image_generator import ImageGenerator

log = logging.getLogger("novel")

_MAX_RETRIES = 5
_RETRY_BASE_DELAY = 3  # seconds


class SiliconFlowBackend(ImageGenerator):
    """基于 SiliconFlow REST API 的云端图片生成后端。

    免费模型 FLUX.1-schnell 默认 4 步，无需调整 steps。
    图片以 URL 形式返回（1小时有效），自动下载转为 PIL Image。
    """

    API_URL = "https://api.siliconflow.cn/v1/images/generations"

    def __init__(self, config: dict) -> None:
        self._client = None
        self._model = config.get("model", "black-forest-labs/FLUX.1-schnell")
        width = config.get("width", 1024)
        height = config.get("height", 1792)
        self._image_size = config.get("image_size", f"{width}x{height}")
        self._api_key = config.get("api_key") or os.environ.get("SILICONFLOW_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "SiliconFlow 需要 API Key。请设置环境变量 SILICONFLOW_API_KEY。"
            )

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=120)
        return self._client

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()

    def generate(self, prompt: str) -> Image.Image:
        """调用 SiliconFlow API 生成图片并下载，遇到 429 自动重试。"""
        client = self._get_client()

        for attempt in range(_MAX_RETRIES):
            resp = client.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "image_size": self._image_size,
                },
            )
            if resp.status_code == 429:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                log.warning("SiliconFlow 429 限流，%ds 后重试 (%d/%d)", delay, attempt + 1, _MAX_RETRIES)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            break
        else:
            resp.raise_for_status()  # raise the last 429

        data = resp.json()
        image_url = data["images"][0]["url"]

        # 下载图片（URL 1小时有效）
        img_resp = client.get(image_url)
        img_resp.raise_for_status()
        image = Image.open(io.BytesIO(img_resp.content))

        log.debug("SiliconFlow 生成图片: %dx%d", image.width, image.height)
        return image
