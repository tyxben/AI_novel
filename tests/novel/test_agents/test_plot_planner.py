"""PlotPlanner Agent 测试"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMClient, LLMResponse
from src.novel.agents.plot_planner import PlotPlanner, plot_planner_node
from src.novel.models.chapter import MoodTag
from src.novel.models.character import (
    Appearance,
    CharacterProfile,
    Personality,
)
from src.novel.models.novel import ChapterOutline, VolumeOutline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="mock-model", usage=None)


def _make_chapter_outline(**overrides) -> ChapterOutline:
    defaults = {
        "chapter_number": 1,
        "title": "初入江湖",
        "goal": "主角离开家乡，前往门派",
        "key_events": ["告别父母", "路遇强盗", "被师傅救下"],
        "involved_characters": ["张三", "李师傅"],
        "estimated_words": 3000,
        "mood": "蓄力",
    }
    defaults.update(overrides)
    return ChapterOutline(**defaults)


def _make_volume_outline(**overrides) -> VolumeOutline:
    defaults = {
        "volume_number": 1,
        "title": "起源篇",
        "core_conflict": "主角入门考验",
        "resolution": "通过考核正式入门",
        "chapters": [1, 2, 3, 4, 5],
    }
    defaults.update(overrides)
    return VolumeOutline(**defaults)


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
    moods = ["蓄力", "小爽", "蓄力", "大爽", "过渡"]
    focuses = ["对话", "动作", "描写", "心理"]
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
                "foreshadowing_to_plant": (
                    ["某个伏笔"] if i == 0 else None
                ),
                "foreshadowing_to_collect": None,
            }
        )
    return json.dumps({"scenes": scenes}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tests: decompose_chapter
# ---------------------------------------------------------------------------



def test_decompose_chapter_valid():
    """正常分解章节，返回有效场景列表。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

    planner = PlotPlanner(mock_llm)
    result = planner.decompose_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={"volume_theme": "修仙起步"},
        characters=[_make_character()],
    )

    assert isinstance(result, list)
    assert len(result) == 3
    for scene in result:
        assert "scene_number" in scene
        assert "title" in scene
        assert "summary" in scene
        assert "characters_involved" in scene
        assert "mood" in scene
        assert "tension_level" in scene
        assert "target_words" in scene
        assert "narrative_focus" in scene



def test_decompose_chapter_word_distribution():
    """场景字数之和应合理。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(
        _mock_llm_scenes(4, total_words=4000)
    )

    planner = PlotPlanner(mock_llm)
    result = planner.decompose_chapter(
        chapter_outline=_make_chapter_outline(estimated_words=4000),
        volume_context={},
        characters=[],
    )

    total = sum(s["target_words"] for s in result)
    # 每个场景至少 200 字
    assert all(s["target_words"] >= 200 for s in result)
    assert total > 0



def test_decompose_chapter_tension_clamped():
    """tension_level 应该被 clamp 到 [0.0, 1.0]。"""
    bad_scenes = json.dumps(
        {
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "异常场景",
                    "summary": "测试",
                    "characters_involved": [],
                    "mood": "蓄力",
                    "tension_level": 1.5,
                    "target_words": 1000,
                    "narrative_focus": "对话",
                },
                {
                    "scene_number": 2,
                    "title": "负数张力",
                    "summary": "测试",
                    "characters_involved": [],
                    "mood": "蓄力",
                    "tension_level": -0.3,
                    "target_words": 1000,
                    "narrative_focus": "描写",
                },
            ]
        },
        ensure_ascii=False,
    )

    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(bad_scenes)

    planner = PlotPlanner(mock_llm)
    result = planner.decompose_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
    )

    assert result[0]["tension_level"] == 1.0
    assert result[1]["tension_level"] == 0.0



def test_decompose_chapter_invalid_mood_fallback():
    """无效 mood 应回退为 '蓄力'。"""
    bad_scenes = json.dumps(
        {
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "奇怪",
                    "summary": "测试",
                    "characters_involved": [],
                    "mood": "超级无敌爽",
                    "tension_level": 0.5,
                    "target_words": 1000,
                    "narrative_focus": "对话",
                }
            ]
        },
        ensure_ascii=False,
    )

    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(bad_scenes)

    planner = PlotPlanner(mock_llm)
    result = planner.decompose_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
    )

    assert result[0]["mood"] == "蓄力"



def test_decompose_chapter_with_foreshadowing():
    """传入伏笔提示时，prompt 中应包含伏笔信息。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

    planner = PlotPlanner(mock_llm)
    hints = [
        {"content": "神秘玉佩的来历", "status": "pending"},
        {"content": "老者留下的暗号", "status": "pending"},
    ]
    result = planner.decompose_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[_make_character()],
        foreshadowing_hints=hints,
    )

    assert len(result) == 3
    # 验证 LLM 被调用时 prompt 包含伏笔
    call_args = mock_llm.chat.call_args
    user_msg = call_args[0][0][1]["content"]
    assert "神秘玉佩的来历" in user_msg
    assert "老者留下的暗号" in user_msg



def test_decompose_chapter_empty_scenes_fallback():
    """LLM 返回空场景列表时应回退到默认3场景结构。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response('{"scenes": []}')

    planner = PlotPlanner(mock_llm)
    scenes = planner.decompose_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
    )
    assert len(scenes) == 3
    assert scenes[0]["scene_number"] == 1
    assert scenes[1]["scene_number"] == 2
    assert scenes[2]["scene_number"] == 3
    # Each fallback scene should have a title and target_words
    for s in scenes:
        assert "title" in s
        assert s["target_words"] > 0



def test_decompose_chapter_llm_invalid_json():
    """LLM 返回无效 JSON 时应抛出 ValueError。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response("这不是JSON格式的输出")

    planner = PlotPlanner(mock_llm)
    with pytest.raises(ValueError):
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[],
        )


# ---------------------------------------------------------------------------
# Tests: design_rhythm
# ---------------------------------------------------------------------------



def test_design_rhythm_basic():
    """设计节奏应返回正确数量的章节节奏。"""
    mock_llm = MagicMock(spec=LLMClient)
    planner = PlotPlanner(mock_llm)

    vol = _make_volume_outline(chapters=[1, 2, 3, 4, 5])
    result = planner.design_rhythm(vol, genre="玄幻")

    assert len(result) == 5
    for item in result:
        assert "chapter_number" in item
        assert 0.0 <= item["overall_tension"] <= 1.0
        assert item["chapter_type"] in {"铺垫", "发展", "高潮", "过渡", "收束"}
        assert item["recommended_scenes"] >= 2



def test_design_rhythm_chapter_numbers_match():
    """节奏结果的章节号应与卷大纲一致。"""
    mock_llm = MagicMock(spec=LLMClient)
    planner = PlotPlanner(mock_llm)

    chapters = [10, 11, 12, 13, 14, 15]
    vol = _make_volume_outline(chapters=chapters)
    result = planner.design_rhythm(vol, genre="都市")

    assert [r["chapter_number"] for r in result] == chapters



def test_design_rhythm_unknown_genre():
    """未知题材应使用默认节奏模板。"""
    mock_llm = MagicMock(spec=LLMClient)
    planner = PlotPlanner(mock_llm)

    vol = _make_volume_outline(chapters=[1, 2, 3])
    result = planner.design_rhythm(vol, genre="未知题材XYZ")

    assert len(result) == 3
    # 应仍返回有效数据
    for item in result:
        assert 0.0 <= item["overall_tension"] <= 1.0


# ---------------------------------------------------------------------------
# Tests: suggest_cliffhanger
# ---------------------------------------------------------------------------



def test_suggest_cliffhanger_with_next_chapter():
    """有下一章时应返回悬念建议。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(
        json.dumps(
            {"cliffhanger": "一道黑影从门后闪过...", "type": "悬疑"},
            ensure_ascii=False,
        )
    )

    planner = PlotPlanner(mock_llm)
    result = planner.suggest_cliffhanger(
        chapter_outline=_make_chapter_outline(),
        next_chapter_outline=_make_chapter_outline(
            chapter_number=2, title="门派考验"
        ),
    )

    assert result == "一道黑影从门后闪过..."



def test_suggest_cliffhanger_none_when_not_appropriate():
    """LLM 认为不适合设悬念时应返回 None。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(
        json.dumps({"cliffhanger": None, "type": None})
    )

    planner = PlotPlanner(mock_llm)
    result = planner.suggest_cliffhanger(
        chapter_outline=_make_chapter_outline(),
        next_chapter_outline=None,
    )

    assert result is None



def test_suggest_cliffhanger_no_next_chapter():
    """无下一章（卷末）时 prompt 中应注明。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(
        json.dumps({"cliffhanger": None, "type": None})
    )

    planner = PlotPlanner(mock_llm)
    planner.suggest_cliffhanger(
        chapter_outline=_make_chapter_outline(),
        next_chapter_outline=None,
    )

    call_args = mock_llm.chat.call_args
    user_msg = call_args[0][0][1]["content"]
    assert "最后一章" in user_msg


# ---------------------------------------------------------------------------
# Tests: plot_planner_node
# ---------------------------------------------------------------------------



def test_plot_planner_node_success():
    """节点函数正常执行，返回 current_scenes 和 decisions。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

    state = {
        "config": {},
        "current_chapter_outline": _make_chapter_outline().model_dump(),
        "characters": [],
    }

    with patch("src.novel.agents.plot_planner.create_llm_client", return_value=mock_llm):
        result = plot_planner_node(state)

    assert "current_scenes" in result
    assert isinstance(result["current_scenes"], list)
    assert len(result["current_scenes"]) == 3
    assert "decisions" in result
    assert len(result["decisions"]) >= 1
    assert result["decisions"][0]["agent"] == "PlotPlanner"
    assert "completed_nodes" in result
    assert "plot_planner" in result["completed_nodes"]


def test_plot_planner_node_error_handling():
    """LLM 失败时节点应返回空 current_scenes 和错误信息。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.side_effect = RuntimeError("LLM 服务不可用")

    state = {
        "config": {},
        "current_chapter_outline": _make_chapter_outline().model_dump(),
    }

    with patch("src.novel.agents.plot_planner.create_llm_client", return_value=mock_llm):
        result = plot_planner_node(state)

    assert result["current_scenes"] == []
    assert "errors" in result
    assert len(result["errors"]) >= 1
    assert result["decisions"][0]["decision"] == "场景分解失败"


def test_plot_planner_node_minimal_state():
    """只提供必要字段时节点也能正常工作。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(2))

    state = {
        "config": {},
        "current_chapter_outline": _make_chapter_outline().model_dump(),
    }

    with patch("src.novel.agents.plot_planner.create_llm_client", return_value=mock_llm):
        result = plot_planner_node(state)

    assert len(result["current_scenes"]) == 2



def test_decompose_invalid_narrative_focus_fallback():
    """无效的 narrative_focus 应回退为 '描写'。"""
    bad_scenes = json.dumps(
        {
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "测试",
                    "summary": "测试",
                    "characters_involved": [],
                    "mood": "蓄力",
                    "tension_level": 0.5,
                    "target_words": 1000,
                    "narrative_focus": "跳舞",
                }
            ]
        },
        ensure_ascii=False,
    )
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(bad_scenes)

    planner = PlotPlanner(mock_llm)
    result = planner.decompose_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
    )

    assert result[0]["narrative_focus"] == "描写"



def test_decompose_missing_fields_defaults():
    """LLM 返回的场景缺少字段时应使用默认值。"""
    minimal_scenes = json.dumps(
        {
            "scenes": [
                {"scene_number": 1},
                {},
            ]
        },
        ensure_ascii=False,
    )
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(minimal_scenes)

    planner = PlotPlanner(mock_llm)
    result = planner.decompose_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
    )

    assert len(result) == 2
    # 第一个保留 scene_number=1，第二个补为 2
    assert result[0]["scene_number"] == 1
    assert result[1]["scene_number"] == 2
    # 都有默认 mood
    assert result[0]["mood"] == "蓄力"
    assert result[1]["mood"] == "蓄力"
    # target_words 至少 200
    assert result[0]["target_words"] >= 200
    assert result[1]["target_words"] >= 200


# ---------------------------------------------------------------------------
# Tests: decompose_chapter 主线推进追踪
# ---------------------------------------------------------------------------


def test_decompose_chapter_with_main_storyline():
    """传入 outline 包含 main_storyline 时，prompt 中应包含主线信息。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

    planner = PlotPlanner(mock_llm)
    outline = {
        "main_storyline": {
            "protagonist_goal": "成为天下第一",
            "core_conflict": "魔族入侵",
            "character_arc": "从懦弱少年成长为盖世英雄",
            "stakes": "人族存亡",
        },
    }
    result = planner.decompose_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[_make_character()],
        outline=outline,
    )

    assert len(result) == 3
    call_args = mock_llm.chat.call_args
    user_msg = call_args[0][0][1]["content"]
    assert "主线信息" in user_msg
    assert "成为天下第一" in user_msg
    assert "魔族入侵" in user_msg
    assert "从懦弱少年成长为盖世英雄" in user_msg
    assert "人族存亡" in user_msg


def test_decompose_chapter_with_storyline_progress():
    """chapter_outline 有 storyline_progress 时，prompt 中应包含本章主线推进。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

    planner = PlotPlanner(mock_llm)
    chapter = _make_chapter_outline(storyline_progress="主角获得神器碎片")
    result = planner.decompose_chapter(
        chapter_outline=chapter,
        volume_context={},
        characters=[],
    )

    assert len(result) == 3
    call_args = mock_llm.chat.call_args
    user_msg = call_args[0][0][1]["content"]
    assert "本章主线推进：主角获得神器碎片" in user_msg


def test_decompose_chapter_with_both_outline_and_progress():
    """同时有 outline.main_storyline 和 chapter_outline.storyline_progress。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

    planner = PlotPlanner(mock_llm)
    outline = {
        "main_storyline": {
            "protagonist_goal": "复仇",
            "core_conflict": "家族灭门",
        },
    }
    chapter = _make_chapter_outline(storyline_progress="发现仇人线索")
    result = planner.decompose_chapter(
        chapter_outline=chapter,
        volume_context={},
        characters=[],
        outline=outline,
    )

    assert len(result) == 3
    call_args = mock_llm.chat.call_args
    user_msg = call_args[0][0][1]["content"]
    assert "复仇" in user_msg
    assert "家族灭门" in user_msg
    assert "本章主线推进：发现仇人线索" in user_msg


def test_decompose_chapter_no_outline_no_progress():
    """不传 outline 且无 storyline_progress 时，prompt 中不应有主线 section。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

    planner = PlotPlanner(mock_llm)
    result = planner.decompose_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
    )

    assert len(result) == 3
    call_args = mock_llm.chat.call_args
    user_msg = call_args[0][0][1]["content"]
    assert "主线信息" not in user_msg


def test_decompose_chapter_empty_main_storyline():
    """outline 存在但 main_storyline 为空 dict 时，不注入主线 section。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

    planner = PlotPlanner(mock_llm)
    result = planner.decompose_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
        outline={"main_storyline": {}},
    )

    assert len(result) == 3
    call_args = mock_llm.chat.call_args
    user_msg = call_args[0][0][1]["content"]
    assert "主线信息" not in user_msg


def test_decompose_chapter_system_prompt_has_mainline_rules():
    """system prompt 中应包含主线推进要求（规则 6/7/8）。"""
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
    assert "每个场景必须服务于主线推进" in system_msg
    assert "至少有一个场景必须让主线产生实质性进展" in system_msg
    assert "主角朝目标靠近或遭遇新障碍" in system_msg


def test_plot_planner_node_passes_outline():
    """节点函数应将 state 中的 outline 传递给 decompose_chapter。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response(_mock_llm_scenes(3))

    outline_data = {
        "main_storyline": {
            "protagonist_goal": "修炼成仙",
            "core_conflict": "天劫将至",
        },
    }
    state = {
        "config": {},
        "current_chapter_outline": _make_chapter_outline().model_dump(),
        "characters": [],
        "outline": outline_data,
    }

    with patch("src.novel.agents.plot_planner.create_llm_client", return_value=mock_llm):
        result = plot_planner_node(state)

    assert len(result["current_scenes"]) == 3
    call_args = mock_llm.chat.call_args
    user_msg = call_args[0][0][1]["content"]
    assert "修炼成仙" in user_msg
    assert "天劫将至" in user_msg
