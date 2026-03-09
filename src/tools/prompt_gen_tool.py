from __future__ import annotations

from typing import Any


class PromptGenTool:
    """封装 Prompt 生成模块，供 Agent 节点调用。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._gen: Any = None

    def _get_gen(self) -> Any:
        if self._gen is None:
            from src.promptgen.prompt_generator import PromptGenerator

            prompt_cfg = dict(self.config.get("promptgen", {}))
            global_llm = self.config.get("llm", {})
            module_llm = prompt_cfg.get("llm", {})
            prompt_cfg["llm"] = {**global_llm, **module_llm}
            self._gen = PromptGenerator(prompt_cfg)
        return self._gen

    def run(
        self,
        text: str,
        segment_index: int,
        full_text: str | None = None,
    ) -> str:
        gen = self._get_gen()
        if full_text:
            gen.set_full_text(full_text)
        return gen.generate(text, segment_index=segment_index)

    def run_video_prompt(self, text: str, segment_index: int) -> str:
        gen = self._get_gen()
        return gen.generate_video_prompt(text, segment_index=segment_index)
