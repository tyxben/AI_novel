"""即梦/Seedance 视频生成后端 (火山方舟 API)。"""

import base64
import logging
import os
from pathlib import Path

from src.videogen.base_backend import BaseVideoBackend

log = logging.getLogger("novel")

# 分辨率映射：配置值 -> API 参数
_RESOLUTION_MAP = {
    "720p": "720p",
    "1080p": "1080p",
    "2k": "2k",
    "2K": "2k",
}


class SeedanceBackend(BaseVideoBackend):
    """基于火山方舟 REST API 的即梦/Seedance 视频生成后端。"""

    DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

    def __init__(self, config: dict) -> None:
        super().__init__(config)

        self._api_key: str = (
            config.get("api_key")
            or os.environ.get("JIMENG_API_KEY")
            or os.environ.get("SEEDANCE_API_KEY")
            or ""
        )
        if not self._api_key:
            raise RuntimeError(
                "Seedance 需要 API Key。请设置环境变量 JIMENG_API_KEY 或 SEEDANCE_API_KEY。"
            )

        self._base_url: str = config.get("base_url", self.DEFAULT_BASE_URL).rstrip("/")
        self._model: str = config.get("model", "seedance-2.0")
        self._aspect_ratio: str = config.get("aspect_ratio", "9:16")
        self._resolution: str = _RESOLUTION_MAP.get(
            config.get("resolution", "1080p"), "1080p"
        )
        self._audio: bool = config.get("audio", False)

    # ------------------------------------------------------------------
    # BaseVideoBackend 必需实现
    # ------------------------------------------------------------------

    def _submit_task(
        self, prompt: str, image_path: Path | None, duration: float
    ) -> str:
        """提交视频生成任务到 Seedance API。"""
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "aspect_ratio": self._aspect_ratio,
            "duration": int(duration),
            "audio": self._audio,
            "resolution": self._resolution,
        }

        # 图生视频：读取图片并 base64 编码
        if image_path is not None:
            image_data = Path(image_path).read_bytes()
            b64_str = base64.b64encode(image_data).decode("ascii")
            payload["references"] = [
                {"type": "image", "data": b64_str},
            ]

        client = self._get_client()
        url = f"{self._base_url}/v1/video/generations"
        resp = client.post(
            url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        task_id = data.get("data", {}).get("task_id") or data.get("task_id", "")
        if not task_id:
            raise RuntimeError(f"Seedance API 未返回 task_id: {data}")

        log.debug("Seedance 任务已提交: task_id=%s", task_id)
        return task_id

    def _query_task(self, task_id: str) -> dict:
        """查询 Seedance 视频生成任务状态。"""
        client = self._get_client()
        url = f"{self._base_url}/v1/video/generations/{task_id}"
        resp = client.get(
            url,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        resp.raise_for_status()
        body = resp.json()

        # 标准化状态字段
        inner = body.get("data", body)
        raw_status = inner.get("status", "").lower()

        state_map = {
            "completed": "completed",
            "success": "completed",
            "succeed": "completed",
            "failed": "failed",
            "fail": "failed",
            "error": "failed",
        }
        state = state_map.get(raw_status, "processing")

        return {
            "state": state,
            "raw": inner,
            "error": inner.get("error", inner.get("message", "")),
        }

    def _get_video_url(self, task_result: dict) -> str:
        """从完成的任务结果中提取视频下载 URL。"""
        raw = task_result.get("raw", {})
        url = raw.get("url") or raw.get("video_url", "")
        if not url:
            raise RuntimeError(f"Seedance 任务结果中无视频 URL: {raw}")
        return url

    def _get_video_metadata(self, task_result: dict) -> dict:
        """从完成的任务结果中提取视频元信息。"""
        raw = task_result.get("raw", {})

        # 根据分辨率和宽高比推断尺寸
        width, height = self._infer_dimensions()

        return {
            "duration": float(raw.get("duration", 5)),
            "width": int(raw.get("width", width)),
            "height": int(raw.get("height", height)),
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _infer_dimensions(self) -> tuple[int, int]:
        """根据分辨率和宽高比推算视频尺寸。"""
        # 短边基准
        short_side = {"720p": 720, "1080p": 1080, "2k": 1440}.get(
            self._resolution, 1080
        )

        ratio_map = {
            "9:16": (9, 16),
            "16:9": (16, 9),
            "1:1": (1, 1),
            "4:3": (4, 3),
            "3:4": (3, 4),
            "21:9": (21, 9),
        }
        rw, rh = ratio_map.get(self._aspect_ratio, (9, 16))

        if rw < rh:
            # 竖屏：width = short_side
            width = short_side
            height = int(short_side * rh / rw)
        else:
            # 横屏或正方形：height = short_side
            height = short_side
            width = int(short_side * rw / rh)

        return width, height
