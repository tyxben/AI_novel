"""OpenAI Sora 视频生成后端。

API 文档: https://platform.openai.com/docs/api-reference/videos
模型: sora-2, sora-2-pro
"""

import logging
import os
from pathlib import Path

from src.videogen.base_backend import BaseVideoBackend

log = logging.getLogger("novel")

# Sora seconds 参数只支持固定档位
_SORA2_DURATIONS = [4, 8, 12]
_SORA2_PRO_DURATIONS = [10, 15, 25]


def _snap_duration(target: float, model: str) -> str:
    """将目标时长对齐到 Sora 支持的档位。"""
    options = _SORA2_PRO_DURATIONS if "pro" in model else _SORA2_DURATIONS
    best = min(options, key=lambda d: abs(d - target))
    return str(best)


class SoraBackend(BaseVideoBackend):
    """OpenAI Sora 视频生成后端。"""

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._api_key: str = config.get("api_key") or os.environ.get(
            "OPENAI_API_KEY", ""
        )
        if not self._api_key:
            raise RuntimeError(
                "Sora 需要 OpenAI API Key，请设置 OPENAI_API_KEY 环境变量"
                "或在 config 中设置 videogen.api_key"
            )
        self._base_url: str = config.get("base_url", "https://api.openai.com")
        self._model: str = config.get("model", "sora-2")
        self._size: str = config.get("size", "1024x1792")  # 竖屏 9:16

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
        }

    def _submit_task(
        self, prompt: str, image_path: Path | None, duration: float
    ) -> str:
        """提交 Sora 视频生成任务。

        使用 multipart/form-data 格式提交（与 OpenAI 文档一致）。
        """
        client = self._get_client()
        seconds = _snap_duration(duration, self._model)

        data = {
            "model": self._model,
            "prompt": prompt,
            "size": self._size,
            "seconds": seconds,
        }

        # 图生视频：通过 image 字段上传
        files = None
        if image_path and image_path.exists():
            img_bytes = image_path.read_bytes()
            suffix = image_path.suffix.lower()
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "webp": "image/webp"}.get(suffix.lstrip("."), "image/png")
            files = {"image": (image_path.name, img_bytes, mime)}

        resp = client.post(
            f"{self._base_url}/v1/videos",
            headers=self._headers(),
            data=data,
            files=files,
        )
        resp.raise_for_status()
        result = resp.json()
        task_id = result.get("id", "")
        if not task_id:
            raise RuntimeError(f"Sora 未返回视频 ID: {result}")
        log.info("Sora 任务已提交: id=%s, model=%s, seconds=%s", task_id, self._model, seconds)
        return task_id

    def _query_task(self, task_id: str) -> dict:
        """查询 Sora 视频生成状态。"""
        client = self._get_client()
        resp = client.get(
            f"{self._base_url}/v1/videos/{task_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        raw = resp.json()

        status = raw.get("status", "")
        state_map = {
            "completed": "completed",
            "failed": "failed",
            "queued": "processing",
            "in_progress": "processing",
        }
        return {
            "state": state_map.get(status, "processing"),
            "raw": raw,
            "error": raw.get("error", ""),
        }

    def _get_video_url(self, task_result: dict) -> str:
        """从完成结果中提取视频 URL。"""
        raw = task_result.get("raw", {})
        url = raw.get("url", "")
        if not url:
            # 尝试从 output 字段获取
            url = raw.get("output", {}).get("url", "")
        if not url:
            raise RuntimeError(f"Sora 未返回视频 URL: {raw}")
        return url

    def _get_video_metadata(self, task_result: dict) -> dict:
        """提取视频元信息。"""
        raw = task_result.get("raw", {})
        # 从 size 参数推断宽高
        try:
            w, h = self._size.split("x")
            width, height = int(w), int(h)
        except (ValueError, AttributeError):
            width, height = 1024, 1792

        return {
            "duration": float(raw.get("seconds", 5)),
            "width": width,
            "height": height,
        }
