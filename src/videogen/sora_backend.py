"""OpenAI Sora 视频生成后端。

API 文档: https://developers.openai.com/api/docs/guides/video-generation
模型: sora-2 ($0.10/s), sora-2-pro ($0.30~0.50/s)

支持分辨率:
  - 720x1280  (竖屏标准)    sora-2: $0.10/s, pro: $0.30/s
  - 1280x720  (横屏标准)    sora-2: $0.10/s, pro: $0.30/s
  - 1024x1792 (竖屏高清)    仅 pro: $0.50/s
  - 1792x1024 (横屏高清)    仅 pro: $0.50/s

请求流程:
  1. POST /v1/videos → 返回 {id, status}
  2. GET  /v1/videos/{id} 轮询状态 → queued → in_progress → completed
  3. GET  /v1/videos/{id}/content 下载 MP4 (含同步音频)

新特性 (Sora 2):
  - 自动生成同步音频（对话、音效、环境音）
  - 原生竖屏支持 (720x1280)
  - Remix API: POST /v1/videos/{id}/remix
"""

import logging
import os
from pathlib import Path

from src.videogen.base_backend import BaseVideoBackend

log = logging.getLogger("novel")

# Sora 支持的分辨率
_SORA2_SIZES = {"720x1280", "1280x720"}
_SORA2_PRO_SIZES = {"720x1280", "1280x720", "1024x1792", "1792x1024"}

# Sora seconds 参数只支持固定档位 (API 实测)
_SORA2_DURATIONS = [4, 8, 12]
_SORA2_PRO_DURATIONS = [10, 15, 25]


def _snap_duration(target: float, model: str) -> str:
    """将目标时长对齐到 Sora 支持的固定档位。"""
    options = _SORA2_PRO_DURATIONS if "pro" in model else _SORA2_DURATIONS
    best = min(options, key=lambda d: abs(d - target))
    return str(best)


def _validate_size(size: str, model: str) -> str:
    """验证分辨率是否支持，不支持则回退到默认值。"""
    valid = _SORA2_PRO_SIZES if "pro" in model else _SORA2_SIZES
    if size in valid:
        return size
    default = "720x1280"
    log.warning("Sora 不支持分辨率 %s (model=%s)，回退到 %s", size, model, default)
    return default


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
        self._size: str = _validate_size(
            config.get("size", "720x1280"), self._model
        )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
        }

    def _submit_task(
        self, prompt: str, image_path: Path | None, duration: float
    ) -> str:
        """提交 Sora 视频生成任务。"""
        client = self._get_client()
        seconds = _snap_duration(duration, self._model)

        data = {
            "model": self._model,
            "prompt": prompt,
            "size": self._size,
            "seconds": seconds,
        }

        # 图生视频：通过 input_reference 字段上传 (multipart/form-data)
        # 注意: 图片分辨率必须与视频 size 一致
        if image_path and image_path.exists():
            img_bytes = image_path.read_bytes()
            suffix = image_path.suffix.lower().lstrip(".")
            mime = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "webp": "image/webp",
            }.get(suffix, "image/png")
            files = {"input_reference": (image_path.name, img_bytes, mime)}
            resp = client.post(
                f"{self._base_url}/v1/videos",
                headers=self._headers(),
                data=data,
                files=files,
            )
        else:
            # 纯文本生成：使用 JSON 格式
            resp = client.post(
                f"{self._base_url}/v1/videos",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=data,
            )
        if resp.status_code >= 400:
            log.error("Sora API 错误 %d: %s", resp.status_code, resp.text)
        resp.raise_for_status()

        result = resp.json()
        task_id = result.get("id", "")
        if not task_id:
            raise RuntimeError(f"Sora 未返回视频 ID: {result}")
        log.info(
            "Sora 任务已提交: id=%s, model=%s, size=%s, seconds=%s",
            task_id, self._model, self._size, seconds,
        )
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
        """返回 content 端点 URL 供下载（含同步音频的 MP4）。"""
        raw = task_result.get("raw", {})
        video_id = raw.get("id", "")
        if not video_id:
            raise RuntimeError(f"Sora 未返回视频 ID: {raw}")
        return f"{self._base_url}/v1/videos/{video_id}/content"

    def _download_video(self, url: str, output_path: Path) -> Path:
        """重写下载方法，添加 Authorization header。"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        client = self._get_client()
        resp = client.get(url, headers=self._headers())
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
        log.debug("Sora 视频已下载: %s (%d bytes)", output_path, len(resp.content))
        return output_path

    def _get_video_metadata(self, task_result: dict) -> dict:
        """提取视频元信息。"""
        raw = task_result.get("raw", {})
        try:
            w, h = self._size.split("x")
            width, height = int(w), int(h)
        except (ValueError, AttributeError):
            width, height = 720, 1280

        return {
            "duration": float(raw.get("seconds", 5)),
            "width": width,
            "height": height,
        }
