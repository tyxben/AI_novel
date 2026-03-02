"""MiniMax 海螺视频 (Hailuo) 生成后端。

三步异步流程：
1. POST /v1/video_generation -> task_id
2. GET /v1/query/video_generation?task_id=xxx -> file_id
3. GET /v1/files/retrieve?file_id=xxx -> download_url
"""

import base64
import logging
import os
from pathlib import Path

from src.videogen.base_backend import BaseVideoBackend

log = logging.getLogger("novel")


class MinimaxBackend(BaseVideoBackend):
    """基于 MiniMax 海螺 API 的视频生成后端。"""

    BASE_URL = "https://api.minimax.io"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._model = config.get("model", "MiniMax-Hailuo-02")
        self._resolution = config.get("resolution", "768P")
        self._api_key = config.get("api_key") or os.environ.get("MINIMAX_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "MiniMax 需要 API Key。请设置环境变量 MINIMAX_API_KEY。"
            )

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _submit_task(
        self, prompt: str, image_path: Path | None, duration: float
    ) -> str:
        """提交视频生成任务到 MiniMax API。"""
        client = self._get_client()

        # MiniMax 只支持 6s 和 10s
        allowed = [6, 10]
        snap = min(allowed, key=lambda d: abs(d - duration))

        payload = {
            "prompt": prompt,
            "model": self._model,
            "duration": snap,
            "resolution": self._resolution,
        }

        if image_path is not None:
            image_data = Path(image_path).read_bytes()
            b64 = base64.b64encode(image_data).decode("utf-8")
            payload["first_frame_image"] = f"data:image/png;base64,{b64}"

        resp = client.post(
            f"{self.BASE_URL}/v1/video_generation",
            headers=self._auth_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        task_id = data.get("task_id")
        if not task_id:
            base_resp = data.get("base_resp", {})
            status_msg = base_resp.get("status_msg", "")
            if "insufficient balance" in status_msg:
                raise RuntimeError("MiniMax 余额不足，请到 platform.minimax.io 充值")
            raise RuntimeError(f"MiniMax 视频生成失败: {status_msg or data}")

        log.debug("MiniMax 任务已提交: task_id=%s", task_id)
        return task_id

    def _query_task(self, task_id: str) -> dict:
        """查询 MiniMax 任务状态。

        MiniMax 状态映射:
            "Success" -> "completed"
            "Fail"    -> "failed"
            其他       -> "processing"
        """
        client = self._get_client()
        resp = client.get(
            f"{self.BASE_URL}/v1/query/video_generation",
            params={"task_id": task_id},
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status", "")
        if status == "Success":
            return {
                "state": "completed",
                "file_id": data.get("file_id"),
                "raw": data,
            }
        elif status == "Fail":
            return {
                "state": "failed",
                "error": data.get("base_resp", {}).get("status_msg", "unknown"),
            }
        else:
            return {"state": "processing", "status": status}

    def _get_video_url(self, task_result: dict) -> str:
        """通过 file_id 获取视频下载 URL（MiniMax 三步流程的第三步）。"""
        file_id = task_result.get("file_id")
        if not file_id:
            raise RuntimeError(f"MiniMax 任务结果中无 file_id: {task_result}")

        client = self._get_client()
        resp = client.get(
            f"{self.BASE_URL}/v1/files/retrieve",
            params={"file_id": file_id},
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

        download_url = data.get("file", {}).get("download_url")
        if not download_url:
            raise RuntimeError(f"MiniMax 未返回 download_url: {data}")

        log.debug("MiniMax 视频下载 URL: %s", download_url)
        return download_url

    def _get_video_metadata(self, task_result: dict) -> dict:
        """从任务结果提取视频元信息。"""
        raw = task_result.get("raw", {})
        return {
            "duration": raw.get("duration", 0),
            "width": raw.get("width", 0),
            "height": raw.get("height", 0),
        }
