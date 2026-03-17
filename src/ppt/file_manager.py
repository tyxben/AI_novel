"""PPT 项目文件管理器 - 管理 workspace 目录结构"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class FileManager:
    """管理 PPT 项目的 workspace 目录结构。

    目录布局::

        workspace/ppt/{project_id}/
        ├── images/          # 配图
        ├── output/          # 最终 .pptx 文件
        └── checkpoints/     # 断点续传 JSON
    """

    def __init__(self, workspace: str = "workspace") -> None:
        self.workspace = Path(workspace)

    # ------------------------------------------------------------------
    # 项目管理
    # ------------------------------------------------------------------

    def create_project(self, project_id: str) -> Path:
        """创建项目目录，返回项目根路径。"""
        project_dir = self._project_dir(project_id)
        for sub in ("images", "output", "checkpoints"):
            (project_dir / sub).mkdir(parents=True, exist_ok=True)
        return project_dir

    # ------------------------------------------------------------------
    # Checkpoint
    # ------------------------------------------------------------------

    def save_checkpoint(self, project_id: str, stage: str, data: dict) -> Path:
        """保存 checkpoint，返回文件路径。"""
        ckpt_dir = self._project_dir(project_id) / "checkpoints"
        ckpt_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "stage": stage,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        ckpt_path = ckpt_dir / "latest.json"
        ckpt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return ckpt_path

    def load_checkpoint(self, project_id: str) -> dict | None:
        """加载最新 checkpoint，不存在则返回 None。"""
        ckpt_path = self._project_dir(project_id) / "checkpoints" / "latest.json"
        if not ckpt_path.exists():
            return None
        text = ckpt_path.read_text(encoding="utf-8")
        return json.loads(text)

    # ------------------------------------------------------------------
    # 路径助手
    # ------------------------------------------------------------------

    def get_image_path(self, project_id: str, slide_number: int) -> Path:
        """获取某页配图的保存路径。"""
        return self._project_dir(project_id) / "images" / f"slide_{slide_number}.png"

    def get_image_dir(self, project_id: str) -> Path:
        """获取图片目录。"""
        return self._project_dir(project_id) / "images"

    def get_output_path(self, project_id: str) -> Path:
        """获取最终 PPT 输出路径。"""
        return self._project_dir(project_id) / "output" / f"{project_id}.pptx"

    def get_checkpoint_path(self, project_id: str) -> Path:
        """获取 checkpoint 文件路径。"""
        return self._project_dir(project_id) / "checkpoints" / "latest.json"

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        if ".." in project_id or "/" in project_id or "\\" in project_id:
            raise ValueError(f"Invalid project_id: {project_id}")
        return self.workspace / "ppt" / project_id
