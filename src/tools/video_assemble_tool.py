from __future__ import annotations

from pathlib import Path
from typing import Any


class VideoAssembleTool:
    """封装视频合成模块，供 Agent 节点调用。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def run(
        self,
        images: list[Path],
        audio_srt: list[dict],
        output_path: Path,
        workspace: Path,
        video_clips: list[Path] | None = None,
    ) -> Path:
        from src.video.video_assembler import VideoAssembler

        assembler = VideoAssembler(self.config["video"], workspace)
        assembler.assemble(
            images=images,
            audio_srt=audio_srt,
            output_path=output_path,
            video_clips=video_clips,
        )
        return output_path
