"""章节任务书 (chapter_brief) 系统测试。

测试要点：
- ChapterOutline 能接受 chapter_brief 字段
- chapter_brief 默认为空 dict
- PlotPlanner 在 chapter_brief 存在时将其注入 prompt
- Writer 在 chapter_brief 存在时将其注入 system_prompt
- writer_node 正确传递 chapter_brief
- 兼容旧数据（没有 chapter_brief 的大纲不会崩溃）
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.models.novel import ChapterOutline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_BRIEF = {
    "main_conflict": "主角被围困在幻阵中",
    "payoff": "主角突破幻阵，实力大涨",
    "character_arc_step": "从犹豫不决到果断出手",
    "foreshadowing_plant": ["神秘老者的身份"],
    "foreshadowing_collect": ["第2章埋的古玉发光"],
    "end_hook_type": "悬疑",
}


def _make_chapter_outline(**overrides) -> ChapterOutline:
    defaults = {
        "chapter_number": 5,
        "title": "幻阵困局",
        "goal": "主角突破幻阵",
        "key_events": ["进入幻阵", "遭遇幻兽", "突破"],
        "mood": "大爽",
        "estimated_words": 2500,
    }
    defaults.update(overrides)
    return ChapterOutline(**defaults)


def _mock_llm(content: str = "测试内容") -> MagicMock:
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(content=content, model="test", usage=None)
    return llm


# ---------------------------------------------------------------------------
# 1. ChapterOutline 模型测试
# ---------------------------------------------------------------------------


class TestChapterOutlineModel:
    def test_chapter_brief_default_empty(self):
        """chapter_brief 默认为空 dict"""
        outline = _make_chapter_outline()
        assert outline.chapter_brief == {}

    def test_chapter_brief_accepts_valid_data(self):
        """chapter_brief 接受完整的任务书数据"""
        outline = _make_chapter_outline(chapter_brief=SAMPLE_BRIEF)
        assert outline.chapter_brief == SAMPLE_BRIEF
        assert outline.chapter_brief["main_conflict"] == "主角被围困在幻阵中"
        assert outline.chapter_brief["end_hook_type"] == "悬疑"
        assert isinstance(outline.chapter_brief["foreshadowing_plant"], list)

    def test_chapter_brief_partial_data(self):
        """chapter_brief 接受部分字段"""
        partial = {"main_conflict": "敌人来袭", "payoff": "击退敌人"}
        outline = _make_chapter_outline(chapter_brief=partial)
        assert outline.chapter_brief["main_conflict"] == "敌人来袭"
        assert "foreshadowing_plant" not in outline.chapter_brief

    def test_chapter_brief_model_dump_roundtrip(self):
        """chapter_brief 序列化/反序列化往返一致"""
        outline = _make_chapter_outline(chapter_brief=SAMPLE_BRIEF)
        dumped = outline.model_dump()
        restored = ChapterOutline(**dumped)
        assert restored.chapter_brief == SAMPLE_BRIEF

    def test_backward_compat_no_chapter_brief(self):
        """兼容旧数据：没有 chapter_brief 字段不会崩溃"""
        data = {
            "chapter_number": 1,
            "title": "旧章节",
            "goal": "旧目标",
            "key_events": ["事件"],
            "mood": "蓄力",
        }
        outline = ChapterOutline(**data)
        assert outline.chapter_brief == {}


# ---------------------------------------------------------------------------
# 2. NovelDirector 大纲解析测试
# ---------------------------------------------------------------------------


class TestNovelDirectorParseBrief:
    def test_parse_outline_with_chapter_brief(self):
        """_parse_outline 正确解析 chapter_brief"""
        from src.novel.agents.novel_director import NovelDirector

        llm = _mock_llm()
        director = NovelDirector(llm)

        data = {
            "acts": [{"name": "第一幕", "description": "开端", "start_chapter": 1, "end_chapter": 2}],
            "volumes": [{"volume_number": 1, "title": "卷一", "core_conflict": "矛盾", "resolution": "解决", "chapters": [1, 2]}],
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "第1章",
                    "goal": "目标",
                    "key_events": ["事件1"],
                    "mood": "蓄力",
                    "chapter_brief": SAMPLE_BRIEF,
                },
                {
                    "chapter_number": 2,
                    "title": "第2章",
                    "goal": "目标2",
                    "key_events": ["事件2"],
                    "mood": "小爽",
                },
            ],
            "main_storyline": {"protagonist_goal": "变强"},
        }

        outline = director._parse_outline(data, "cyclic_upgrade", 2)
        ch1 = outline.chapters[0]
        ch2 = outline.chapters[1]

        assert ch1.chapter_brief == SAMPLE_BRIEF
        # 没有 chapter_brief 的章节应该兜底为空 dict
        assert ch2.chapter_brief == {}

    def test_parse_outline_chapter_brief_non_dict_fallback(self):
        """chapter_brief 为非 dict 类型时兜底为空 dict"""
        from src.novel.agents.novel_director import NovelDirector

        llm = _mock_llm()
        director = NovelDirector(llm)

        data = {
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "第1章",
                    "goal": "目标",
                    "key_events": ["事件"],
                    "mood": "蓄力",
                    "chapter_brief": "这不是dict",
                },
            ],
            "main_storyline": {},
        }

        outline = director._parse_outline(data, "cyclic_upgrade", 1)
        assert outline.chapters[0].chapter_brief == {}


# ---------------------------------------------------------------------------
# 3. PlotPlanner 注入 chapter_brief 测试
# ---------------------------------------------------------------------------


class TestPlotPlannerBrief:
    def test_decompose_injects_chapter_brief(self):
        """decompose_chapter 在 chapter_brief 存在时将其注入 prompt"""
        from src.novel.agents.plot_planner import PlotPlanner

        scene_response = json.dumps({
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "场景1",
                    "summary": "概要",
                    "characters_involved": ["主角"],
                    "mood": "大爽",
                    "tension_level": 0.8,
                    "target_words": 800,
                    "narrative_focus": "动作",
                }
            ]
        })
        llm = _mock_llm(scene_response)
        planner = PlotPlanner(llm)

        outline = _make_chapter_outline(chapter_brief=SAMPLE_BRIEF)
        planner.decompose_chapter(
            chapter_outline=outline,
            volume_context={},
            characters=[],
        )

        # 检查 LLM 被调用时的 prompt 中包含章节任务书内容
        call_args = llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        user_msg = messages[1]["content"]

        assert "章节任务书" in user_msg
        assert "主角被围困在幻阵中" in user_msg
        assert "主角突破幻阵，实力大涨" in user_msg
        assert "从犹豫不决到果断出手" in user_msg
        assert "悬疑" in user_msg

    def test_decompose_no_chapter_brief(self):
        """decompose_chapter 在没有 chapter_brief 时不崩溃"""
        from src.novel.agents.plot_planner import PlotPlanner

        scene_response = json.dumps({
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "场景1",
                    "summary": "概要",
                    "characters_involved": ["主角"],
                    "mood": "蓄力",
                    "tension_level": 0.5,
                    "target_words": 800,
                    "narrative_focus": "描写",
                }
            ]
        })
        llm = _mock_llm(scene_response)
        planner = PlotPlanner(llm)

        outline = _make_chapter_outline()  # 默认空 chapter_brief
        scenes = planner.decompose_chapter(
            chapter_outline=outline,
            volume_context={},
            characters=[],
        )

        assert len(scenes) == 1
        # 没有 chapter_brief 时不应该出现"章节任务书"
        call_args = llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        user_msg = messages[1]["content"]
        assert "章节任务书" not in user_msg

    def test_decompose_partial_chapter_brief(self):
        """decompose_chapter 处理部分 chapter_brief 字段"""
        from src.novel.agents.plot_planner import PlotPlanner

        scene_response = json.dumps({
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "场景1",
                    "summary": "概要",
                    "characters_involved": [],
                    "mood": "蓄力",
                    "tension_level": 0.5,
                    "target_words": 800,
                    "narrative_focus": "描写",
                }
            ]
        })
        llm = _mock_llm(scene_response)
        planner = PlotPlanner(llm)

        partial_brief = {"main_conflict": "敌人来袭"}
        outline = _make_chapter_outline(chapter_brief=partial_brief)
        planner.decompose_chapter(
            chapter_outline=outline,
            volume_context={},
            characters=[],
        )

        call_args = llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        user_msg = messages[1]["content"]
        assert "章节任务书" in user_msg
        assert "敌人来袭" in user_msg
        # 没有 payoff 字段，不应该出现 "本章爽点"
        assert "本章爽点" not in user_msg


# ---------------------------------------------------------------------------
# 4. Writer 注入 chapter_brief 测试
# ---------------------------------------------------------------------------


class TestWriterBrief:
    def test_set_chapter_brief(self):
        """set_chapter_brief 正确设置任务书"""
        llm = _mock_llm("生成的场景文本")
        from src.novel.agents.writer import Writer
        writer = Writer(llm)

        writer.set_chapter_brief(SAMPLE_BRIEF)
        assert writer._chapter_brief == SAMPLE_BRIEF

        writer.set_chapter_brief(None)
        assert writer._chapter_brief is None

        writer.set_chapter_brief({})
        assert writer._chapter_brief is None

    def test_generate_scene_injects_chapter_brief(self):
        """generate_scene 在 chapter_brief 存在时将其注入 system_prompt"""
        llm = _mock_llm("这是生成的场景正文内容，主角突破了幻阵。")
        from src.novel.agents.writer import Writer
        from src.novel.models.world import WorldSetting

        writer = Writer(llm)
        writer.set_chapter_brief(SAMPLE_BRIEF)

        outline = _make_chapter_outline(chapter_brief=SAMPLE_BRIEF)
        scene_plan = {
            "scene_number": 1,
            "target_words": 800,
            "summary": "突破幻阵",
            "mood": "大爽",
            "characters_involved": [],
        }
        world = WorldSetting(era="远古", location="大陆")

        writer.generate_scene(
            scene_plan=scene_plan,
            chapter_outline=outline,
            characters=[],
            world_setting=world,
            context="",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        system_msg = messages[0]["content"]

        assert "本章任务书" in system_msg
        assert "主角被围困在幻阵中" in system_msg
        assert "主角突破幻阵，实力大涨" in system_msg
        assert "从犹豫不决到果断出手" in system_msg
        assert "悬疑" in system_msg

    def test_generate_scene_no_chapter_brief(self):
        """generate_scene 在没有 chapter_brief 时不注入任务书"""
        llm = _mock_llm("这是生成的场景正文内容。")
        from src.novel.agents.writer import Writer
        from src.novel.models.world import WorldSetting

        writer = Writer(llm)
        # 不设置 chapter_brief

        outline = _make_chapter_outline()
        scene_plan = {
            "scene_number": 1,
            "target_words": 800,
            "summary": "日常",
            "mood": "日常",
            "characters_involved": [],
        }
        world = WorldSetting(era="现代", location="城市")

        writer.generate_scene(
            scene_plan=scene_plan,
            chapter_outline=outline,
            characters=[],
            world_setting=world,
            context="",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        system_msg = messages[0]["content"]

        assert "本章任务书" not in system_msg

    def test_generate_chapter_sets_brief_from_outline(self):
        """generate_chapter 从 chapter_outline 中自动设置 chapter_brief"""
        llm = _mock_llm("这是生成的场景正文。")
        from src.novel.agents.writer import Writer
        from src.novel.models.world import WorldSetting

        writer = Writer(llm)
        outline = _make_chapter_outline(chapter_brief=SAMPLE_BRIEF)
        scene_plans = [{"scene_number": 1, "target_words": 800}]
        world = WorldSetting(era="远古", location="大陆")

        writer.generate_chapter(
            chapter_outline=outline,
            scene_plans=scene_plans,
            characters=[],
            world_setting=world,
            context="",
            style_name="webnovel.shuangwen",
        )

        # chapter_brief 应该被自动设置
        assert writer._chapter_brief == SAMPLE_BRIEF


# ---------------------------------------------------------------------------
# 5. writer_node 传递 chapter_brief 测试
# ---------------------------------------------------------------------------


class TestWriterNodeBrief:
    @patch("src.novel.agents.writer.create_llm_client")
    def test_writer_node_passes_chapter_brief(self, mock_create):
        """writer_node 从 state 中取出 chapter_brief 并设置到 writer"""
        from src.novel.agents.writer import writer_node

        mock_llm = _mock_llm("生成的章节内容。")
        mock_create.return_value = mock_llm

        state = {
            "config": {"llm": {}},
            "current_chapter": 5,
            "total_chapters": 40,
            "current_scenes": [{"scene_number": 1, "target_words": 800}],
            "style_name": "webnovel.shuangwen",
            "outline": {
                "main_storyline": {"protagonist_goal": "变强"},
            },
            "current_chapter_outline": {
                "chapter_number": 5,
                "title": "幻阵困局",
                "goal": "突破幻阵",
                "key_events": ["进入幻阵"],
                "mood": "大爽",
                "estimated_words": 2500,
                "chapter_brief": SAMPLE_BRIEF,
            },
            "characters": [],
            "world_setting": {"era": "远古", "location": "大陆"},
            "chapters": [],
        }

        result = writer_node(state)

        # 应该成功生成，无错误
        assert not result.get("errors") or len(result["errors"]) == 0
        assert "writer" in result.get("completed_nodes", [])

        # 检查 LLM 调用的 system prompt 中包含任务书
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        system_msg = messages[0]["content"]
        assert "本章任务书" in system_msg

    @patch("src.novel.agents.writer.create_llm_client")
    def test_writer_node_no_chapter_brief(self, mock_create):
        """writer_node 在没有 chapter_brief 时正常工作"""
        from src.novel.agents.writer import writer_node

        mock_llm = _mock_llm("生成的章节内容。")
        mock_create.return_value = mock_llm

        state = {
            "config": {"llm": {}},
            "current_chapter": 1,
            "total_chapters": 10,
            "current_scenes": [{"scene_number": 1, "target_words": 800}],
            "style_name": "webnovel.shuangwen",
            "outline": {"main_storyline": {}},
            "current_chapter_outline": {
                "chapter_number": 1,
                "title": "开端",
                "goal": "目标",
                "key_events": ["事件"],
                "mood": "蓄力",
                "estimated_words": 2500,
                # 没有 chapter_brief
            },
            "characters": [],
            "world_setting": {"era": "现代", "location": "城市"},
            "chapters": [],
        }

        result = writer_node(state)

        assert not result.get("errors") or len(result["errors"]) == 0
        assert "writer" in result.get("completed_nodes", [])


# ---------------------------------------------------------------------------
# 6. 大纲 prompt 包含 chapter_brief 要求
# ---------------------------------------------------------------------------


class TestOutlinePromptBrief:
    def test_outline_prompt_includes_chapter_brief_format(self):
        """大纲生成 prompt 中包含 chapter_brief 的 JSON 格式要求"""
        from src.novel.agents.novel_director import NovelDirector

        llm = _mock_llm()
        director = NovelDirector(llm)

        prompt = director._build_outline_prompt(
            genre="玄幻",
            theme="修炼",
            target_words=100000,
            template_name="cyclic_upgrade",
            act_count=3,
            volume_count=1,
            chapters_per_volume=40,
            total_chapters=40,
        )

        assert "chapter_brief" in prompt
        assert "main_conflict" in prompt
        assert "payoff" in prompt
        assert "character_arc_step" in prompt
        assert "foreshadowing_plant" in prompt
        assert "foreshadowing_collect" in prompt
        assert "end_hook_type" in prompt
