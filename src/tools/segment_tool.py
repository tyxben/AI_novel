from __future__ import annotations

from typing import Any


class SegmentTool:
    """封装文本分段模块，供 Agent 节点调用。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def run(self, text: str) -> list[dict]:
        from src.segmenter.text_segmenter import create_segmenter

        seg_cfg = dict(self.config.get("segmenter", {"method": "simple", "max_chars": 100, "min_chars": 20}))
        # 合并全局 llm 配置
        global_llm = self.config.get("llm", {})
        module_llm = seg_cfg.get("llm", {})
        seg_cfg["llm"] = {**global_llm, **module_llm}
        segmenter = create_segmenter(seg_cfg)
        return segmenter.segment(text)
