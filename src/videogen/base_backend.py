"""视频生成后端公共基类。

提取所有云端视频生成后端的共同逻辑：
- httpx.Client 懒加载
- 异步轮询框架
- 视频下载
- 资源清理
"""

import logging
import time
from pathlib import Path

from src.videogen.video_generator import VideoGenerator

log = logging.getLogger("novel")


class BaseVideoBackend(VideoGenerator):
    """云端视频生成后端公共基类。

    子类需实现:
        _submit_task(prompt, image_path, duration) -> str (task_id)
        _query_task(task_id) -> dict  {"state": "completed"|"failed"|"processing", ...}
        _get_video_url(task_result) -> str
        _get_video_metadata(task_result) -> dict  {"duration": float, "width": int, "height": int}
    """

    def __init__(self, config: dict) -> None:
        self._client = None
        self._poll_interval: int = config.get("poll_interval", 10)
        self._poll_timeout: int = config.get("poll_timeout", 300)
        self._output_dir: Path = Path(config.get("output_dir", "videos"))

    def _get_client(self):
        """懒加载 httpx.Client。"""
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=120)
        return self._client

    def close(self) -> None:
        """关闭 HTTP 客户端连接。"""
        if self._client is not None:
            self._client.close()
            self._client = None

    def _poll_task(self, task_id: str) -> dict:
        """轮询任务状态直到完成或超时。

        Args:
            task_id: 视频生成任务 ID。

        Returns:
            完成状态的任务结果字典。

        Raises:
            RuntimeError: 视频生成失败。
            TimeoutError: 轮询超时。
        """
        deadline = time.time() + self._poll_timeout
        while time.time() < deadline:
            result = self._query_task(task_id)
            state = result.get("state", "")

            if state == "completed":
                log.info("视频生成完成: task_id=%s", task_id)
                return result
            if state == "failed":
                error = result.get("error", "unknown")
                raise RuntimeError(f"视频生成失败: {error} (task_id={task_id})")

            log.debug(
                "视频生成中: task_id=%s, state=%s, 等待 %ds...",
                task_id,
                state,
                self._poll_interval,
            )
            time.sleep(self._poll_interval)

        raise TimeoutError(
            f"视频生成超时 ({self._poll_timeout}s): task_id={task_id}"
        )

    def _download_video(self, url: str, output_path: Path) -> Path:
        """下载视频到本地文件。

        Args:
            url: 视频下载 URL。
            output_path: 本地保存路径。

        Returns:
            保存后的文件路径。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        client = self._get_client()
        resp = client.get(url)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
        log.debug("视频已下载: %s (%d bytes)", output_path, len(resp.content))
        return output_path

    def generate(
        self, prompt: str, image_path: Path | None = None, duration: float = 5.0
    ) -> "VideoResult":
        """编排完整的视频生成流程：提交 -> 轮询 -> 下载。"""
        from src.videogen.video_generator import VideoResult

        log.info("提交视频生成任务: prompt=%s..., image=%s", prompt[:50], image_path)
        task_id = self._submit_task(prompt, image_path, duration)
        log.info("任务已提交: task_id=%s", task_id)

        task_result = self._poll_task(task_id)

        video_url = self._get_video_url(task_result)
        output_path = self._output_dir / f"{task_id}.mp4"
        self._download_video(video_url, output_path)

        metadata = self._get_video_metadata(task_result)
        return VideoResult(
            video_path=output_path,
            duration=metadata.get("duration", duration),
            width=metadata.get("width", 0),
            height=metadata.get("height", 0),
        )

    # --- 子类必须实现的方法 ---

    def _submit_task(
        self, prompt: str, image_path: Path | None, duration: float
    ) -> str:
        """提交视频生成任务，返回 task_id。"""
        raise NotImplementedError

    def _query_task(self, task_id: str) -> dict:
        """查询任务状态，返回包含 'state' 字段的字典。

        state 取值: 'completed', 'failed', 'processing'
        """
        raise NotImplementedError

    def _get_video_url(self, task_result: dict) -> str:
        """从完成的任务结果中提取视频下载 URL。"""
        raise NotImplementedError

    def _get_video_metadata(self, task_result: dict) -> dict:
        """从完成的任务结果中提取视频元信息。

        Returns:
            {"duration": float, "width": int, "height": int}
        """
        raise NotImplementedError
