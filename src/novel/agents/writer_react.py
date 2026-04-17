"""ReAct 模式的 Writer Agent。

继承 ReactAgent 基类，注册 WriterToolkit 中的工具，
通过多轮 Thought-Action-Observe 循环完成场景生成。
"""

from __future__ import annotations

import logging
from typing import Any

from src.llm.llm_client import LLMClient
from src.novel.models.chapter import Scene
from src.novel.models.character import CharacterProfile
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import WorldSetting
from src.novel.templates.style_presets import get_style
from src.novel.tools.react_writer_tools import WriterToolkit
from src.novel.utils import count_words, truncate_text
from src.react import ReactAgent, ReactResult, ReactTool

log = logging.getLogger("novel.writer_react")
_MAX_CONTEXT = 4000


class WriterReactAgent(ReactAgent):
    """ReAct 模式的 Writer，通过工具循环完成场景生成和自检。"""

    def __init__(self, llm: LLMClient):
        super().__init__(llm)
        self.toolkit = WriterToolkit(llm)
        self._tools.clear()  # 清除默认 submit

        self.register_tool(
            ReactTool(
                name="generate_draft",
                description="生成场景初稿",
                parameters={
                    "scene_prompt": {
                        "type": "string",
                        "description": "场景prompt",
                    }
                },
                func=self.toolkit.generate_draft,
            )
        )
        self.register_tool(
            ReactTool(
                name="check_repetition",
                description="检查与前文重复",
                parameters={},
                func=self.toolkit.check_repetition,
                check_tool=True,
            )
        )
        self.register_tool(
            ReactTool(
                name="check_character_names",
                description="检查角色名称",
                parameters={},
                func=self.toolkit.check_character_names,
                check_tool=True,
            )
        )
        self.register_tool(
            ReactTool(
                name="check_narrative_logic",
                description="AI检查叙事逻辑",
                parameters={},
                func=self.toolkit.check_narrative_logic,
                check_tool=True,
            )
        )
        self.register_tool(
            ReactTool(
                name="revise_draft",
                description="修改草稿",
                parameters={
                    "issues": {"type": "string"},
                    "focus": {
                        "type": "string",
                        "description": "可选",
                    },
                },
                func=self.toolkit.revise_draft,
            )
        )
        self.register_tool(
            ReactTool(
                name="get_current_draft",
                description="获取当前草稿",
                parameters={},
                func=self.toolkit.get_current_draft,
            )
        )
        self.register_tool(
            ReactTool(
                name="submit",
                description="提交终稿",
                parameters={
                    "text": {
                        "type": "string",
                        "description": "可选，留空用当前草稿",
                    }
                },
                func=self.toolkit.submit_final,
            )
        )

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def generate_scene(
        self,
        scene_plan: dict[str, Any],
        chapter_outline: ChapterOutline,
        characters: list[CharacterProfile],
        world_setting: WorldSetting,
        context: str,
        style_name: str,
        max_iterations: int = 6,
        budget_mode: bool = False,
        scenes_written_summary: str = "",
        debt_summary: str = "",
        feedback_prompt: str = "",
        continuity_brief: str = "",
    ) -> Scene:
        """ReAct 模式生成单个场景。

        工作流: generate_draft -> check_* -> revise (如有问题) -> submit
        如果 ReAct 循环未产出有效文本，降级到 one-shot Writer。
        """
        target = scene_plan.get("target_words", 800)
        self.toolkit.set_context(
            target_words=target,
            characters=characters,
            previous_text=(
                truncate_text(context, _MAX_CONTEXT) if context else ""
            ),
        )

        scene_prompt = self._build_scene_prompt(
            scene_plan,
            chapter_outline,
            characters,
            world_setting,
            context,
            style_name,
            scenes_written_summary,
            debt_summary,
            feedback_prompt,
            continuity_brief=continuity_brief,
        )

        system = (
            f"你是专业小说写手（ReAct模式）。\n"
            f"创作第{chapter_outline.chapter_number}章"
            f"「{chapter_outline.title}」"
            f"第{scene_plan.get('scene_number', 1)}个场景。\n\n"
            f"工作流：\n1. generate_draft 生成初稿\n2. check 检查\n"
            f"3. revise 修改（如有问题）\n4. submit 提交"
        )

        task = (
            f"生成第{chapter_outline.chapter_number}章"
            f"第{scene_plan.get('scene_number', 1)}个场景。\n"
            f"目标：{scene_plan.get('goal', '')}\n"
            f"字数：{target}字\n\n"
            f"请调用 generate_draft，传入以下 scene_prompt：\n{scene_prompt}"
        )

        result: ReactResult = self.run(
            task=task,
            system_prompt=system,
            max_iterations=max_iterations,
            budget_mode=budget_mode,
        )

        text = result.output or ""
        if isinstance(text, dict):
            text = text.get("draft", "") or text.get("text", "")
        text = str(text).strip()

        # Sanitize: reject raw tool-call JSON that leaked as output
        if text and (
            text.startswith('{"thinking"')
            or text.startswith('{"tool"')
            or text.startswith('{"draft_preview"')
        ):
            log.warning(
                "ReAct output contains raw tool-call JSON, "
                "falling back to toolkit draft"
            )
            text = self.toolkit._draft or ""

        if not text or len(text) < 50:
            log.warning("ReAct 未产出有效文本，降级 one-shot Writer")
            from src.novel.agents.writer import Writer

            return Writer(self.llm).generate_scene(
                scene_plan=scene_plan,
                chapter_outline=chapter_outline,
                characters=characters,
                world_setting=world_setting,
                context=context,
                style_name=style_name,
                scenes_written_summary=scenes_written_summary,
                debt_summary=debt_summary,
                feedback_prompt=feedback_prompt,
                continuity_brief=continuity_brief,
            )

        # 后处理硬截：与 Writer.generate_scene 保持一致的兜底层
        # （DeepSeek 不听 prompt 字数，只能在这里强制收口）
        from src.novel.agents.writer import Writer as _Writer
        text = _Writer._trim_to_hard_cap(text, hard_cap=int(target * 1.2), target=target)

        chars = scene_plan.get(
            "characters_involved", scene_plan.get("characters", [])
        )
        return Scene(
            scene_number=scene_plan.get("scene_number", 1),
            location=scene_plan.get("location", "未指定"),
            time=scene_plan.get("time", "未指定"),
            characters=chars or ["unknown"],
            goal=scene_plan.get("goal", scene_plan.get("summary", "未指定")),
            text=text,
            word_count=count_words(text),
            narrative_modes=scene_plan.get("narrative_modes", []),
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_scene_prompt(
        self,
        scene_plan: dict[str, Any],
        chapter_outline: ChapterOutline,
        characters: list[CharacterProfile],
        world_setting: WorldSetting | None,
        context: str,
        style_name: str,
        scenes_written: str,
        debt_summary: str,
        feedback_prompt: str,
        continuity_brief: str = "",
    ) -> str:
        """构建传给 generate_draft 工具的场景 prompt。"""
        try:
            style_data = get_style(style_name)
            style_text = style_data.get("system_prompt", "")
        except Exception:
            style_text = "你是专业小说写手。"

        target = scene_plan.get("target_words", 800)

        char_lines: list[str] = []
        for c in characters:
            name = c.name if hasattr(c, "name") else c.get("name", "?")
            gender = (
                getattr(c, "gender", "?")
                if hasattr(c, "gender")
                else c.get("gender", "?")
            )
            age = (
                getattr(c, "age", "?")
                if hasattr(c, "age")
                else c.get("age", "?")
            )
            char_lines.append(f"- {name}（{gender}，{age}岁）")

        world_desc = ""
        if world_setting:
            world_desc = (
                f"时代：{world_setting.era}，地点：{world_setting.location}"
            )
            if world_setting.rules:
                world_desc += f"，规则：{'、'.join(world_setting.rules[:3])}"

        parts: list[str] = [style_text]
        parts.append(
            f"\n第{chapter_outline.chapter_number}章"
            f"「{chapter_outline.title}」"
        )
        parts.append(
            f"本章目标：{chapter_outline.goal}\n"
            f"情绪基调：{chapter_outline.mood}"
        )
        if world_desc:
            parts.append(f"\n【世界观】{world_desc}")
        if char_lines:
            parts.append("\n【角色】\n" + "\n".join(char_lines))
        if feedback_prompt:
            parts.append(f"\n{feedback_prompt}")
        if continuity_brief:
            parts.append(f"\n{continuity_brief}")
        if debt_summary:
            parts.append(f"\n【叙事义务】\n{debt_summary}")
        parts.append(
            f"\n【场景】地点：{scene_plan.get('location', '?')}，"
            f"时间：{scene_plan.get('time', '?')}"
        )
        parts.append(
            f"目标：{scene_plan.get('goal', scene_plan.get('summary', '?'))}"
        )
        # 与 Writer.generate_scene 保持一致的字数硬约束（DeepSeek 实测对此无视，
        # 但更听话的模型有效；最终由 _trim_to_hard_cap 在出口兜底）
        _hard_cap = int(target * 1.2)
        parts.append(
            f"【字数硬约束】≤ {_hard_cap} 字（目标 {target}）；"
            f"超出视为失败输出，输出前自检字数，超了必须删减"
        )
        if scenes_written:
            parts.append(
                f"\n【已写内容-禁止重复】\n{scenes_written[:800]}"
            )
        if context:
            parts.append(
                f"\n【前文】\n{truncate_text(context, _MAX_CONTEXT)}"
            )
        return "\n".join(parts)
