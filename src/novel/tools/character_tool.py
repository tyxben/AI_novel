"""角色设计工具 - 封装 CharacterService

提供角色提取和档案生成的简洁接口。
"""

from __future__ import annotations

from typing import Any

from src.novel.models.character import CharacterProfile
from src.novel.services.character_service import CharacterService


class CharacterTool:
    """角色设计工具 - CharacterService 的薄包装。"""

    def __init__(self, llm_client: Any):
        """
        Args:
            llm_client: 实现 ``chat(messages, temperature, json_mode)`` 的 LLMClient。
        """
        self.service = CharacterService(llm_client)

    def extract(self, outline_summary: str, genre: str) -> list[dict]:
        """从大纲摘要提取角色名单。

        Args:
            outline_summary: 大纲摘要文本。
            genre: 小说题材。

        Returns:
            角色列表，每项包含 name 和 role。
        """
        return self.service.extract_characters(outline_summary, genre)

    def generate_profile(
        self, name: str, role: str, genre: str, context: str
    ) -> CharacterProfile:
        """生成完整角色档案。

        Args:
            name: 角色名称。
            role: 角色类型。
            genre: 小说题材。
            context: 大纲上下文。

        Returns:
            CharacterProfile 模型实例。
        """
        return self.service.generate_profile(name, role, genre, context)
