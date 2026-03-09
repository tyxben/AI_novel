"""剪辑 Agent - 视频合成"""
from __future__ import annotations

from pathlib import Path

from src.agents.state import AgentState, Decision
from src.agents.utils import make_decision
from src.tools.video_assemble_tool import VideoAssembleTool
from src.logger import log


class EditorAgent:
    def __init__(self, config: dict):
        self.config = config
        self.video_tool = VideoAssembleTool(config)


def editor_node(state: AgentState) -> dict:
    """Editor 节点"""
    config = state["config"]
    workspace = Path(state["workspace"])
    agent = EditorAgent(config)
    decisions: list[Decision] = []

    images = [Path(p) for p in state["images"]]
    audio_files = state["audio_files"]
    srt_files = state["srt_files"]

    # 构造 audio_srt 列表（兼容现有 VideoAssembler 接口）
    audio_srt = []
    for a, s in zip(audio_files, srt_files):
        audio_srt.append({"audio": Path(a), "srt": Path(s)})

    # 输出路径
    input_stem = Path(state["input_file"]).stem
    output_dir = Path(config.get("project", {}).get("default_output", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{input_stem}.mp4"

    video_clips = None
    if state.get("video_clips"):
        video_clips = [Path(p) for p in state["video_clips"]]

    decisions.append(make_decision(
        "Editor", "start",
        f"开始合成视频: {len(images)} 个片段",
        f"输出: {output_path}",
    ))

    agent.video_tool.run(
        images=images,
        audio_srt=audio_srt,
        output_path=output_path,
        workspace=workspace,
        video_clips=video_clips,
    )

    decisions.append(make_decision(
        "Editor", "complete",
        f"视频合成完成: {output_path}",
        f"分辨率={config.get('video', {}).get('resolution', [1080, 1920])}",
    ))

    log.info("[Editor] 视频输出: %s", output_path)

    return {
        "final_video": str(output_path),
        "decisions": decisions,
    }
