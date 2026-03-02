"""可灵 (Kling) 视频生成后端 — 快手 AI 视频生成 API。

异步流程：
1. POST /v1/videos/text2video 或 /v1/videos/image2video -> task_id
2. GET /v1/videos/{task_id} -> task_status + videos[]
"""

import base64
import logging
import os
from pathlib import Path

from src.videogen.base_backend import BaseVideoBackend

log = logging.getLogger("novel")

# 宽高比 -> (width, height) 参考映射（基于 1080p 短边）
_ASPECT_DIMENSIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:3": (1440, 1080),
    "3:4": (1080, 1440),
    "3:2": (1620, 1080),
    "2:3": (1080, 1620),
    "21:9": (2520, 1080),
}


class KlingBackend(BaseVideoBackend):
    """基于可灵 (Kling) REST API 的视频生成后端。

    支持文生视频和图生视频两种模式，通过 image_path 参数自动切换。
    """

    BASE_URL = "https://api.klingai.com"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._model: str = config.get("model", "kling-v2-6")
        self._mode: str = config.get("mode", "std")
        self._aspect_ratio: str = config.get("aspect_ratio", "9:16")
        self._negative_prompt: str = config.get("negative_prompt", "")
        self._cfg_scale: float | None = config.get("cfg_scale")
        self._callback_url: str = config.get("callback_url", "")

        self._api_key: str = config.get("api_key") or os.environ.get(
            "KLING_API_KEY", ""
        )
        if not self._api_key:
            raise RuntimeError(
                "可灵 (Kling) 需要 API Key。请设置环境变量 KLING_API_KEY。"
            )

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # BaseVideoBackend 必需实现
    # ------------------------------------------------------------------

    def _submit_task(
        self, prompt: str, image_path: Path | None, duration: float
    ) -> str:
        """提交视频生成任务到可灵 API。

        根据 image_path 是否提供，自动选择文生视频或图生视频端点。
        """
        client = self._get_client()

        # 通用参数
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "duration": int(duration),
            "aspect_ratio": self._aspect_ratio,
            "mode": self._mode,
        }

        if self._negative_prompt:
            payload["negative_prompt"] = self._negative_prompt
        if self._cfg_scale is not None:
            payload["cfg_scale"] = self._cfg_scale
        if self._callback_url:
            payload["callback_url"] = self._callback_url

        # 选择端点
        if image_path is not None:
            endpoint = f"{self.BASE_URL}/v1/videos/image2video"
            image_data = Path(image_path).read_bytes()
            b64_str = base64.b64encode(image_data).decode("ascii")
            payload["image"] = f"data:image/png;base64,{b64_str}"
        else:
            endpoint = f"{self.BASE_URL}/v1/videos/text2video"

        resp = client.post(
            endpoint,
            headers=self._auth_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        # 可灵响应格式: {"code": 0, "data": {"task_id": "..."}} 或扁平 {"task_id": "..."}
        task_id = (
            data.get("data", {}).get("task_id")
            or data.get("task_id", "")
        )
        if not task_id:
            raise RuntimeError(f"可灵 API 未返回 task_id: {data}")

        log.debug("可灵任务已提交: task_id=%s, model=%s, mode=%s", task_id, self._model, self._mode)
        return task_id

    def _query_task(self, task_id: str) -> dict:
        """查询可灵视频生成任务状态。

        可灵 task_status 映射:
            "succeed"    -> "completed"
            "failed"     -> "failed"
            "submitted"  -> "processing"
            "processing" -> "processing"
        """
        client = self._get_client()
        resp = client.get(
            f"{self.BASE_URL}/v1/videos/{task_id}",
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        body = resp.json()

        # 可灵嵌套格式: {"code": 0, "data": {"task_id": ..., "task_status": ..., "task_result": ...}}
        inner = body.get("data", body)
        raw_status = inner.get("task_status", "").lower()

        state_map = {
            "succeed": "completed",
            "success": "completed",
            "completed": "completed",
            "failed": "failed",
            "fail": "failed",
        }
        state = state_map.get(raw_status, "processing")

        error_msg = ""
        if state == "failed":
            error_msg = (
                inner.get("task_status_msg", "")
                or body.get("message", "unknown error")
            )

        return {
            "state": state,
            "raw": inner,
            "error": error_msg,
        }

    def _get_video_url(self, task_result: dict) -> str:
        """从完成的任务结果中提取视频下载 URL。

        可灵格式: task_result.raw.task_result.videos[0].url
        """
        raw = task_result.get("raw", {})
        videos = raw.get("task_result", {}).get("videos", [])

        if not videos:
            raise RuntimeError(f"可灵任务结果中无视频: {raw}")

        url = videos[0].get("url", "")
        if not url:
            raise RuntimeError(f"可灵视频条目中无 URL: {videos[0]}")

        log.debug("可灵视频 URL: %s", url)
        return url

    def _get_video_metadata(self, task_result: dict) -> dict:
        """从完成的任务结果中提取视频元信息。"""
        raw = task_result.get("raw", {})
        videos = raw.get("task_result", {}).get("videos", [])

        duration = 0.0
        width = 0
        height = 0

        if videos:
            video = videos[0]
            # duration 可能是字符串 "5.1" 或数值
            duration = float(video.get("duration", 0))
            width = int(video.get("width", 0))
            height = int(video.get("height", 0))

        # 如果 API 未返回尺寸，根据宽高比推断
        if width == 0 or height == 0:
            dims = _ASPECT_DIMENSIONS.get(self._aspect_ratio, (1080, 1920))
            width, height = dims

        return {
            "duration": duration,
            "width": width,
            "height": height,
        }
