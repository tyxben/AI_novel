from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


class VideoGenTool:
    """封装视频生成模块，供 Agent 节点调用。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._gen: Any = None

    def _get_gen(self) -> Any:
        if self._gen is None:
            from src.videogen.video_generator import create_video_generator

            self._gen = create_video_generator(self.config["videogen"])
        return self._gen

    def run(
        self,
        prompt: str,
        output_path: Path,
        image_path: Path | None = None,
    ) -> Path:
        """生成视频片段。

        Args:
            prompt: 视频生成 prompt。
            output_path: 输出文件路径。
            image_path: 可选首帧图片（图生视频模式）。

        Returns:
            输出视频路径。
        """
        gen = self._get_gen()
        duration = self.config.get("videogen", {}).get("duration", 5)
        result = gen.generate(prompt=prompt, image_path=image_path, duration=duration)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(result.video_path), str(output_path))
        return output_path

    def close(self) -> None:
        """释放底层资源。"""
        if self._gen is not None:
            self._gen.close()
            self._gen = None
