"""WorldBuilder - 世界观构建师 Agent

负责：
1. 根据题材和大纲生成世界观设定
2. 为玄幻/武侠题材生成力量体系
3. 验证章节内容是否违反世界观规则
4. 作为 LangGraph 节点管理世界观状态
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.llm.llm_client import create_llm_client
from src.novel.agents.state import Decision, NovelState
from src.novel.models.world import WorldSetting
from src.novel.tools.world_setting_tool import WorldSettingTool

log = logging.getLogger("novel")


def _make_decision(
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    """创建 WorldBuilder 的决策记录。"""
    return Decision(
        agent="WorldBuilder",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


class WorldBuilder:
    """世界观构建师 Agent - 负责生成和维护世界观设定。"""

    def __init__(self, llm_client: Any):
        """
        Args:
            llm_client: 实现 ``chat(messages, temperature, json_mode)`` 的 LLMClient。
        """
        self.llm = llm_client
        self.tool = WorldSettingTool(llm_client)

    def create_world(self, genre: str, outline: dict) -> WorldSetting:
        """创建完整世界观设定（含力量体系）。

        Args:
            genre: 小说题材。
            outline: 大纲 dict（Outline.model_dump()）。

        Returns:
            WorldSetting 模型实例。
        """
        # 从大纲提取摘要
        outline_summary = self._extract_outline_summary(outline)

        # 生成基础世界观
        world_setting = self.tool.generate(genre, outline_summary)

        # 为合适的题材生成力量体系
        power_system = self.tool.generate_power_system(
            genre, f"{world_setting.era} - {world_setting.location}"
        )
        if power_system is not None:
            world_setting.power_system = power_system

        return world_setting

    def validate_consistency(
        self, chapter_text: str, world_setting: WorldSetting
    ) -> tuple[bool, list[str]]:
        """检查章节文本是否违反世界观规则。

        使用规则匹配进行基础检查，不依赖 LLM。

        Args:
            chapter_text: 章节正文。
            world_setting: 世界观设定。

        Returns:
            (is_consistent, violations) 元组。
            is_consistent 为 True 表示无违规，violations 为违规描述列表。
        """
        violations: list[str] = []

        if not chapter_text or not chapter_text.strip():
            return True, []

        # 检查 1: 专有名词一致性（检测是否出现定义中的关键词变体）
        for term, definition in world_setting.terms.items():
            # 如果正文中提到了该专有名词的定义内容但名称不同，可能是不一致
            # 这里做简单的存在性检查
            pass  # 基础版本不做变体检测，留给 ConsistencyChecker

        # 检查 2: 世界规则违反
        # 基于规则关键词的简单匹配
        text_lower = chapter_text.lower()
        for rule in world_setting.rules:
            # 提取规则中的否定词和关键概念
            if "不能" in rule or "禁止" in rule or "不可" in rule:
                # 提取被禁止的行为关键词
                forbidden_keywords = self._extract_forbidden_keywords(rule)
                for keyword in forbidden_keywords:
                    if keyword in text_lower:
                        violations.append(
                            f"可能违反世界规则「{rule}」: 文本中出现了「{keyword}」"
                        )

        # 检查 3: 力量体系一致性
        if world_setting.power_system:
            level_names = {
                lv.name for lv in world_setting.power_system.levels
            }
            # 检查是否出现了不在力量体系中的境界名称
            # 简单规则：如果文中提到了 "XX期" / "XX境" 但不在已定义列表中
            for level in world_setting.power_system.levels:
                for ability in level.typical_abilities:
                    # 检查低等级能力是否出现在应该是高等级的上下文中
                    pass  # 留给更复杂的检查

        is_consistent = len(violations) == 0
        return is_consistent, violations

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _extract_outline_summary(self, outline: dict) -> str:
        """从大纲 dict 提取摘要文本。"""
        parts: list[str] = []

        # 从 acts 提取
        for act in outline.get("acts", []):
            name = act.get("name", "")
            desc = act.get("description", "")
            if name:
                parts.append(f"{name}: {desc}")

        # 从 volumes 提取
        for vol in outline.get("volumes", []):
            title = vol.get("title", "")
            conflict = vol.get("core_conflict", "")
            if title:
                parts.append(f"{title} - {conflict}")

        if not parts:
            return "暂无大纲摘要"

        return "; ".join(parts)

    def _extract_forbidden_keywords(self, rule: str) -> list[str]:
        """从规则描述中提取被禁止的关键词。

        简单实现：提取"不能"/"禁止"/"不可"后面的词。
        """
        keywords: list[str] = []
        for delimiter in ["不能", "禁止", "不可"]:
            if delimiter in rule:
                parts = rule.split(delimiter)
                for part in parts[1:]:
                    # 取分隔符后面的前几个字作为关键词
                    word = part.strip()
                    if word:
                        # 取前4个字作为关键词（避免过长匹配不上）
                        keyword = word[:4].rstrip("，。、；")
                        if len(keyword) >= 2:
                            keywords.append(keyword)
        return keywords


# ---------------------------------------------------------------------------
# LangGraph 节点函数
# ---------------------------------------------------------------------------


def world_builder_node(state: dict) -> dict:
    """LangGraph 节点：WorldBuilder。

    - 如果 state 中没有 world_setting：根据大纲生成世界观
    - 如果 state 中已有 world_setting：跳过（复用现有设定）
    """
    decisions: list[Decision] = []
    errors: list[dict] = []

    # 已有世界观设定 -> 跳过
    if state.get("world_setting") is not None:
        decisions.append(
            _make_decision(
                step="entry",
                decision="世界观已存在，跳过生成",
                reason="resume 模式或世界观已在之前生成",
            )
        )
        return {
            "decisions": decisions,
            "completed_nodes": ["world_builder"],
        }

    # 获取 LLM 客户端
    llm_config = state.get("config", {}).get("llm", {})
    try:
        llm = create_llm_client(llm_config)
    except Exception as exc:
        return {
            "errors": [
                {
                    "agent": "WorldBuilder",
                    "message": f"LLM 初始化失败: {exc}",
                }
            ],
            "completed_nodes": ["world_builder"],
        }

    builder = WorldBuilder(llm)
    genre = state.get("genre", "玄幻")
    outline = state.get("outline", {})

    try:
        world_setting = builder.create_world(genre, outline)
        decisions.append(
            _make_decision(
                step="create_world",
                decision=f"世界观生成完成: {world_setting.era} - {world_setting.location}",
                reason=f"为 {genre} 题材创建世界观设定",
                data={
                    "era": world_setting.era,
                    "location": world_setting.location,
                    "has_power_system": world_setting.power_system is not None,
                    "terms_count": len(world_setting.terms),
                    "rules_count": len(world_setting.rules),
                },
            )
        )
    except Exception as exc:
        log.error("世界观生成失败: %s", exc)
        return {
            "errors": errors
            + [
                {
                    "agent": "WorldBuilder",
                    "message": f"世界观生成失败: {exc}",
                }
            ],
            "decisions": decisions,
            "completed_nodes": ["world_builder"],
        }

    return {
        "world_setting": world_setting.model_dump(),
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["world_builder"],
    }
