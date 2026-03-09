from __future__ import annotations

from pathlib import Path
from typing import Any


class ImageGenTool:
    """封装图片生成模块，供 Agent 节点调用。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._gen: Any = None

    def _get_gen(self) -> Any:
        if self._gen is None:
            from src.imagegen.image_generator import create_image_generator

            self._gen = create_image_generator(self.config["imagegen"])
        return self._gen

    def run(self, prompt: str, output_path: Path) -> Path:
        gen = self._get_gen()
        img = gen.generate(prompt)
        img.save(str(output_path))
        return output_path
