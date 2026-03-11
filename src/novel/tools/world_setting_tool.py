"""世界观设定工具 - 封装 WorldService

提供世界观生成和力量体系定义的简洁接口。
"""

from __future__ import annotations

from typing import Any

from src.novel.models.world import PowerSystem, WorldSetting
from src.novel.services.world_service import WorldService


class WorldSettingTool:
    """世界观设定工具 - WorldService 的薄包装。"""

    def __init__(self, llm_client: Any):
        """
        Args:
            llm_client: 实现 ``chat(messages, temperature, json_mode)`` 的 LLMClient。
        """
        self.service = WorldService(llm_client)

    def generate(self, genre: str, outline_summary: str) -> WorldSetting:
        """生成世界观设定。

        Args:
            genre: 小说题材。
            outline_summary: 大纲摘要。

        Returns:
            WorldSetting 模型实例。
        """
        return self.service.create_world_setting(genre, outline_summary)

    def generate_power_system(
        self, genre: str, world_context: str
    ) -> PowerSystem | None:
        """生成力量体系。

        Args:
            genre: 小说题材。
            world_context: 世界观上下文。

        Returns:
            PowerSystem 模型实例，或 None（非玄幻/武侠题材）。
        """
        return self.service.define_power_system(genre, world_context)
