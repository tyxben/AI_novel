"""阿里云百炼万相 (DashScope) 图片生成后端。"""

import io
import logging
import os
import time

from PIL import Image

from src.imagegen.image_generator import ImageGenerator

log = logging.getLogger("novel")


class DashScopeBackend(ImageGenerator):
    """基于阿里云 DashScope API 的图片生成后端。

    支持万相 wan2.6-t2i 等模型，新用户有 100 张免费额度。
    """

    API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

    def __init__(self, config: dict) -> None:
        self._client = None
        self._model = config.get("model", "wan2.6-t2i")
        width = config.get("width", 1024)
        height = config.get("height", 1792)
        # 万相格式: "width*height"，像素总量需在 [1280*1280, 1440*1440] 范围
        self._size = config.get("size", f"{width}*{height}")
        self._api_key = config.get("api_key") or os.environ.get("DASHSCOPE_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "DashScope 需要 API Key。请设置环境变量 DASHSCOPE_API_KEY。"
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

    _MAX_RETRIES = 3

    def generate(self, prompt: str) -> Image.Image:
        """调用 DashScope API 生成图片，遇到限流/服务器错误/网络错误自动重试。"""
        import httpx

        client = self._get_client()
        last_exc: Exception | None = None

        for attempt in range(self._MAX_RETRIES):
            try:
                resp = client.post(
                    self.API_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "input": {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [{"text": prompt}],
                                }
                            ]
                        },
                        "parameters": {
                            "size": self._size,
                            "n": 1,
                            "prompt_extend": True,
                            "watermark": False,
                        },
                    },
                )
            except httpx.RequestError as exc:
                last_exc = exc
                delay = 2 ** attempt
                log.warning(
                    "DashScope 网络错误，%ds 后重试 (%d/%d): %s",
                    delay, attempt + 1, self._MAX_RETRIES, exc,
                )
                time.sleep(delay)
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
                delay = 2 ** attempt
                log.warning(
                    "DashScope HTTP %d，%ds 后重试 (%d/%d)",
                    resp.status_code, delay, attempt + 1, self._MAX_RETRIES,
                )
                time.sleep(delay)
                continue

            resp.raise_for_status()
            data = resp.json()

            # 从响应中提取图片 URL
            image_url = data["output"]["choices"][0]["message"]["content"][0]["image"]

            # 下载图片（URL 24小时有效）
            img_resp = client.get(image_url)
            img_resp.raise_for_status()
            image = Image.open(io.BytesIO(img_resp.content))

            log.debug("DashScope 生成图片: %dx%d", image.width, image.height)
            return image

        raise RuntimeError(
            f"DashScope 图片生成失败 ({self._MAX_RETRIES}次重试): {last_exc}"
        ) from last_exc
