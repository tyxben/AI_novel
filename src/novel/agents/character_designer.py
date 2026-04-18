"""CharacterDesigner - 角色设计师 Agent

负责：
1. 从大纲中提取角色列表
2. 为每个角色生成完整档案
3. 验证角色行为一致性（OOC 检测）
4. 作为 LangGraph 节点管理角色状态
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.llm.llm_client import create_llm_client
from src.novel.agents.state import Decision, NovelState
from src.novel.llm_utils import get_stage_llm_config
from src.novel.models.character import CharacterProfile
from src.novel.tools.character_tool import CharacterTool

log = logging.getLogger("novel")


def _make_decision(
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    """创建 CharacterDesigner 的决策记录。"""
    return Decision(
        agent="CharacterDesigner",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


class CharacterDesigner:
    """角色设计师 Agent - 负责角色提取、档案生成和一致性检查。"""

    def __init__(self, llm_client: Any):
        """
        Args:
            llm_client: 实现 ``chat(messages, temperature, json_mode)`` 的 LLMClient。
        """
        self.llm = llm_client
        self.tool = CharacterTool(llm_client)

    def create_characters(
        self, outline: dict, genre: str
    ) -> list[CharacterProfile]:
        """从大纲提取角色并生成完整档案。

        Args:
            outline: 大纲 dict（Outline.model_dump()）。
            genre: 小说题材。

        Returns:
            角色档案列表。
        """
        # 提取大纲摘要
        outline_summary = self._extract_outline_summary(outline)

        # 提取角色名单
        raw_characters = self.tool.extract(outline_summary, genre)

        # 为每个角色生成完整档案
        profiles: list[CharacterProfile] = []
        for char_info in raw_characters:
            name = char_info.get("name", "未命名角色")
            role = char_info.get("role", "配角")
            try:
                profile = self.tool.generate_profile(
                    name=name,
                    role=role,
                    genre=genre,
                    context=outline_summary,
                )
                profiles.append(profile)
            except Exception as exc:
                log.warning("角色 %s 档案生成失败: %s", name, exc)
                # 继续处理其他角色

        return profiles

    def validate_character_consistency(
        self, chapter_text: str, characters: list[CharacterProfile]
    ) -> tuple[bool, list[str]]:
        """检查章节中的角色行为是否 OOC（Out of Character）。

        基于规则匹配检查 speech_style 违规，不依赖 LLM。

        Args:
            chapter_text: 章节正文。
            characters: 角色档案列表。

        Returns:
            (is_consistent, violations) 元组。
        """
        violations: list[str] = []

        if not chapter_text or not chapter_text.strip():
            return True, []

        for character in characters:
            name = character.name
            # 检查角色是否出现在章节中
            if name not in chapter_text:
                continue

            # 检查 speech_style 违规
            speech_style = character.personality.speech_style
            style_violations = self._check_speech_style(
                chapter_text, name, speech_style
            )
            violations.extend(style_violations)

            # 检查口头禅一致性（口头禅应该出现在角色对话中）
            # 这里只做基础检查

        is_consistent = len(violations) == 0
        return is_consistent, violations

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _extract_outline_summary(self, outline: dict) -> str:
        """从大纲 dict 提取摘要文本。"""
        parts: list[str] = []

        for act in outline.get("acts", []):
            name = act.get("name", "")
            desc = act.get("description", "")
            if name:
                parts.append(f"{name}: {desc}")

        for vol in outline.get("volumes", []):
            title = vol.get("title", "")
            conflict = vol.get("core_conflict", "")
            if title:
                parts.append(f"{title} - {conflict}")

        if not parts:
            return "暂无大纲摘要"

        return "; ".join(parts)

    def _check_speech_style(
        self, text: str, character_name: str, speech_style: str
    ) -> list[str]:
        """检查角色对话是否符合其语言风格。

        规则匹配：
        - "冷淡简短" 风格的角色不应该有长篇大论的对话
        - "文绉绉" 风格的角色不应该使用现代网络用语
        - "江湖豪爽" 风格不应该用很文雅的措辞
        """
        violations: list[str] = []

        # 提取角色对话（简单实现：查找 "角色名" 后面的对话内容）
        dialogues = self._extract_character_dialogues(text, character_name)

        if not dialogues:
            return []

        # 冷淡简短风格检查
        if "冷淡" in speech_style or "简短" in speech_style:
            for dialogue in dialogues:
                if len(dialogue) > 50:
                    violations.append(
                        f"角色「{character_name}」语言风格为「{speech_style}」，"
                        f"但出现了超过50字的长对话"
                    )
                    break  # 只报告一次

        # 文绉绉风格检查
        if "文绉绉" in speech_style or "古言" in speech_style:
            modern_words = ["OK", "搞定", "牛逼", "666", "yyds"]
            for dialogue in dialogues:
                for word in modern_words:
                    if word in dialogue:
                        violations.append(
                            f"角色「{character_name}」语言风格为「{speech_style}」，"
                            f"但对话中出现了现代用语「{word}」"
                        )

        return violations

    def _extract_character_dialogues(
        self, text: str, character_name: str
    ) -> list[str]:
        """简单提取角色的对话内容。

        查找模式：角色名 + 说/道/笑道/... + "对话内容"
        """
        dialogues: list[str] = []
        # 查找中文引号包裹的对话
        search_start = 0
        while True:
            # 查找角色名出现的位置
            name_pos = text.find(character_name, search_start)
            if name_pos == -1:
                break

            # 在角色名后面找对话（向后查找最近的引号对）
            after_name = text[name_pos + len(character_name) : name_pos + len(character_name) + 30]
            quote_start = after_name.find("\u201c")  # "
            if quote_start == -1:
                quote_start = after_name.find('"')
            if quote_start >= 0:
                abs_start = name_pos + len(character_name) + quote_start + 1
                # 查找闭合引号
                close_quote = text.find("\u201d", abs_start)  # "
                if close_quote == -1:
                    close_quote = text.find('"', abs_start)
                if close_quote > abs_start:
                    dialogues.append(text[abs_start:close_quote])

            search_start = name_pos + len(character_name)

        return dialogues


# ---------------------------------------------------------------------------
# LangGraph 节点函数
# ---------------------------------------------------------------------------


def character_designer_node(state: dict) -> dict:
    """LangGraph 节点：CharacterDesigner。

    - 如果 state 中没有 characters 或列表为空：从大纲提取并生成角色
    - 如果 state 中已有 characters：跳过（复用现有角色）
    """
    decisions: list[Decision] = []
    errors: list[dict] = []

    # 已有角色数据 -> 跳过
    existing_characters = state.get("characters", [])
    if existing_characters:
        decisions.append(
            _make_decision(
                step="entry",
                decision=f"角色已存在（{len(existing_characters)} 个），跳过生成",
                reason="resume 模式或角色已在之前生成",
            )
        )
        return {
            "decisions": decisions,
            "completed_nodes": ["character_designer"],
        }

    # 获取 LLM 客户端
    llm_config = get_stage_llm_config(state, "character_design")
    try:
        llm = create_llm_client(llm_config)
    except Exception as exc:
        return {
            "errors": [
                {
                    "agent": "CharacterDesigner",
                    "message": f"LLM 初始化失败: {exc}",
                }
            ],
            "completed_nodes": ["character_designer"],
        }

    designer = CharacterDesigner(llm)
    # Phase 0 架构重构：零默认体裁。state 必须带 genre。
    genre = state.get("genre")
    if not genre:
        raise ValueError(
            "state 缺少 genre 字段（Phase 0 架构重构：禁止默认回退到玄幻）"
        )
    outline = state.get("outline", {})

    try:
        profiles = designer.create_characters(outline, genre)
        decisions.append(
            _make_decision(
                step="create_characters",
                decision=f"角色生成完成: {len(profiles)} 个角色",
                reason=f"为 {genre} 题材创建角色档案",
                data={
                    "character_names": [p.name for p in profiles],
                    "character_count": len(profiles),
                },
            )
        )
    except Exception as exc:
        log.error("角色生成失败: %s", exc)
        return {
            "errors": errors
            + [
                {
                    "agent": "CharacterDesigner",
                    "message": f"角色生成失败: {exc}",
                }
            ],
            "decisions": decisions,
            "completed_nodes": ["character_designer"],
        }

    return {
        "characters": [p.model_dump() for p in profiles],
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["character_designer"],
    }
