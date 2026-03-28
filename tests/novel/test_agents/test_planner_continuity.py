"""PlotPlanner 连续性约束注入测试

验证 continuity_brief 和 debt_summary 从 state 传递到 PlotPlanner，
并正确注入到 LLM prompt 中。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.llm.llm_client import LLMClient, LLMResponse
from src.novel.agents.plot_planner import PlotPlanner, plot_planner_node
from src.novel.models.character import (
    Appearance,
    CharacterProfile,
    Personality,
)
from src.novel.models.novel import ChapterOutline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="mock-model", usage=None)


def _make_chapter_outline(**overrides) -> ChapterOutline:
    defaults = {
        "chapter_number": 5,
        "title": "深入秘境",
        "goal": "主角探索秘境获取宝物",
        "key_events": ["发现密道", "遭遇守卫", "获得残卷"],
        "involved_characters": ["张三", "李师傅"],
        "estimated_words": 3000,
        "mood": "蓄力",
    }
    defaults.update(overrides)
    return ChapterOutline(**defaults)


def _make_character() -> CharacterProfile:
    return CharacterProfile(
        name="张三",
        gender="男",
        age=18,
        occupation="少年侠客",
        appearance=Appearance(
            height="175cm",
            build="匀称",
            hair="黑色短发",
            eyes="明亮有神",
            clothing_style="粗布衣衫",
        ),
        personality=Personality(
            traits=["勇敢", "莽撞", "善良"],
            core_belief="正义必胜",
            motivation="为父报仇",
            flaw="冲动",
            speech_style="江湖豪爽",
        ),
    )


def _mock_llm_scenes(scene_count: int = 3, total_words: int = 3000) -> str:
    """生成模拟 LLM 返回的场景 JSON。"""
    per_scene = total_words // scene_count
    scenes = []
    moods = ["蓄力", "小爽", "蓄力"]
    focuses = ["对话", "动作", "描写"]
    for i in range(scene_count):
        scenes.append(
            {
                "scene_number": i + 1,
                "title": f"场景{i + 1}",
                "summary": f"第{i + 1}个场景的故事内容",
                "characters_involved": ["张三"],
                "mood": moods[i % len(moods)],
                "tension_level": round(0.3 + i * 0.15, 2),
                "target_words": per_scene,
                "narrative_focus": focuses[i % len(focuses)],
                "foreshadowing_to_plant": None,
                "foreshadowing_to_collect": None,
            }
        )
    return json.dumps({"scenes": scenes}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tests: decompose_chapter with continuity_brief and debt_summary
# ---------------------------------------------------------------------------


class TestDecomposeChapterContinuity:
    """Test continuity_brief and debt_summary injection into decompose_chapter."""

    def test_continuity_brief_appears_in_prompt(self):
        """continuity_brief 应出现在发送给 LLM 的 user message 中。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[_make_character()],
            continuity_brief="上章末尾张三正在逃跑，左臂受伤。禁止违反：张三不能使用左手持剑。",
        )

        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "连续性约束" in user_msg
        assert "张三正在逃跑" in user_msg
        assert "左臂受伤" in user_msg
        assert "禁止违反" in user_msg

    def test_debt_summary_appears_in_prompt(self):
        """debt_summary 应出现在发送给 LLM 的 user message 中。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[],
            debt_summary="第3章埋设的伏笔'神秘玉佩'尚未回收；第4章许诺的师傅教功法未兑现。",
        )

        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "未了结叙事义务" in user_msg
        assert "神秘玉佩" in user_msg
        assert "师傅教功法未兑现" in user_msg

    def test_both_continuity_and_debt_in_prompt(self):
        """同时传入 continuity_brief 和 debt_summary，两者都应出现。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[],
            continuity_brief="张三正与守卫对峙中",
            debt_summary="第2章的悬念未解决",
        )

        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "连续性约束" in user_msg
        assert "张三正与守卫对峙中" in user_msg
        assert "未了结叙事义务" in user_msg
        assert "第2章的悬念未解决" in user_msg

    def test_empty_continuity_brief_not_in_prompt(self):
        """空 continuity_brief 不应在 prompt 中出现连续性约束 section。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[],
            continuity_brief="",
            debt_summary="",
        )

        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "连续性约束" not in user_msg
        assert "未了结叙事义务" not in user_msg

    def test_backward_compat_no_continuity_params(self):
        """不传 continuity_brief 和 debt_summary 时（默认值），仍正常工作。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        planner = PlotPlanner(mock_llm)
        result = planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[_make_character()],
        )

        assert isinstance(result, list)
        assert len(result) == 3
        for scene in result:
            assert "scene_number" in scene
            assert "title" in scene

        # Prompt should not contain continuity sections
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "连续性约束" not in user_msg
        assert "未了结叙事义务" not in user_msg

    def test_system_prompt_has_continuity_rule(self):
        """system prompt 中应包含连续性约束规则（规则 11）。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[],
        )

        call_args = mock_llm.chat.call_args
        system_msg = call_args[0][0][0]["content"]
        assert "连续性约束" in system_msg
        assert "第一个场景必须承接上章遗留事项" in system_msg
        assert "禁止违反" in system_msg

    def test_continuity_appended_after_base_prompt(self):
        """连续性 section 应出现在基础 prompt 内容之后。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[],
            continuity_brief="承接上文内容",
            debt_summary="叙事债务内容",
        )

        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        # The base prompt should appear before continuity sections
        base_marker_pos = user_msg.index("请将此章节分解为")
        continuity_pos = user_msg.index("连续性约束")
        debt_pos = user_msg.index("未了结叙事义务")
        assert base_marker_pos < continuity_pos
        assert continuity_pos < debt_pos


# ---------------------------------------------------------------------------
# Tests: plot_planner_node reads continuity from state
# ---------------------------------------------------------------------------


class TestPlotPlannerNodeContinuity:
    """Test that plot_planner_node reads continuity_brief and debt_summary from state."""

    def test_node_passes_continuity_brief_from_state(self):
        """节点应从 state 读取 continuity_brief 并传递给 decompose_chapter。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        state = {
            "config": {},
            "current_chapter_outline": _make_chapter_outline().model_dump(),
            "characters": [],
            "continuity_brief": "上章张三刚到山门前，身上有伤。",
        }

        with patch(
            "src.novel.agents.plot_planner.create_llm_client",
            return_value=mock_llm,
        ):
            result = plot_planner_node(state)

        assert len(result["current_scenes"]) == 3
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "连续性约束" in user_msg
        assert "张三刚到山门前" in user_msg

    def test_node_passes_debt_summary_from_state(self):
        """节点应从 state 读取 debt_summary 并传递给 decompose_chapter。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        state = {
            "config": {},
            "current_chapter_outline": _make_chapter_outline().model_dump(),
            "characters": [],
            "debt_summary": "遗留伏笔：藏宝图碎片（第3章埋设）需在本章回收。",
        }

        with patch(
            "src.novel.agents.plot_planner.create_llm_client",
            return_value=mock_llm,
        ):
            result = plot_planner_node(state)

        assert len(result["current_scenes"]) == 3
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "未了结叙事义务" in user_msg
        assert "藏宝图碎片" in user_msg

    def test_node_passes_both_from_state(self):
        """节点应从 state 同时读取 continuity_brief 和 debt_summary。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        state = {
            "config": {},
            "current_chapter_outline": _make_chapter_outline().model_dump(),
            "characters": [],
            "continuity_brief": "上章末尾正在战斗中",
            "debt_summary": "悬念待解",
        }

        with patch(
            "src.novel.agents.plot_planner.create_llm_client",
            return_value=mock_llm,
        ):
            result = plot_planner_node(state)

        assert len(result["current_scenes"]) == 3
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "上章末尾正在战斗中" in user_msg
        assert "悬念待解" in user_msg

    def test_node_works_without_continuity_in_state(self):
        """state 中没有 continuity_brief 和 debt_summary 时节点仍正常工作。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        state = {
            "config": {},
            "current_chapter_outline": _make_chapter_outline().model_dump(),
            "characters": [],
            # No continuity_brief or debt_summary
        }

        with patch(
            "src.novel.agents.plot_planner.create_llm_client",
            return_value=mock_llm,
        ):
            result = plot_planner_node(state)

        assert len(result["current_scenes"]) == 3
        assert "plot_planner" in result["completed_nodes"]
        # No continuity sections in prompt
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "连续性约束" not in user_msg
        assert "未了结叙事义务" not in user_msg

    def test_node_handles_empty_strings_in_state(self):
        """state 中 continuity_brief 和 debt_summary 为空字符串时不注入。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

        state = {
            "config": {},
            "current_chapter_outline": _make_chapter_outline().model_dump(),
            "characters": [],
            "continuity_brief": "",
            "debt_summary": "",
        }

        with patch(
            "src.novel.agents.plot_planner.create_llm_client",
            return_value=mock_llm,
        ):
            result = plot_planner_node(state)

        assert len(result["current_scenes"]) == 3
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "连续性约束" not in user_msg
        assert "未了结叙事义务" not in user_msg
