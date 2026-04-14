"""PlotPlanner 伏笔集成测试

验证 Task 6.1.2 的三个增强：
1. 正向伏笔规划 (foreshadowings_to_plant)
2. 后置伏笔检索 (reusable_details)
3. 回收提醒 (foreshadowings_to_resolve)

外加向后兼容：PlotPlanner 未注入 foreshadowing_tool / knowledge_graph 时
plan_chapter 仍能工作，只是对应字段为空。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMClient, LLMResponse
from src.novel.agents.plot_planner import PlotPlanner
from src.novel.models.foreshadowing import DetailEntry
from src.novel.models.novel import ChapterOutline
from src.novel.storage.knowledge_graph import KnowledgeGraph


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="mock-model", usage=None)


def _mock_llm_scenes(scene_count: int = 3, total_words: int = 3000) -> str:
    """Return LLM JSON response containing ``scene_count`` dummy scenes."""
    per_scene = total_words // scene_count
    scenes = []
    for i in range(scene_count):
        scenes.append(
            {
                "scene_number": i + 1,
                "title": f"场景{i + 1}",
                "summary": f"第{i + 1}个场景内容",
                "characters_involved": ["张三"],
                "mood": "蓄力",
                "tension_level": 0.5,
                "target_words": per_scene,
                "narrative_focus": "对话",
                "foreshadowing_to_plant": None,
                "foreshadowing_to_collect": None,
            }
        )
    return json.dumps({"scenes": scenes}, ensure_ascii=False)


def _make_chapter_outline(**overrides) -> ChapterOutline:
    defaults = {
        "chapter_number": 9,
        "title": "线索浮现",
        "goal": "主角发现神秘信物",
        "key_events": ["进入古墓", "发现信物", "遭遇守墓人"],
        "involved_characters": ["张三"],
        "estimated_words": 2500,
        "mood": "蓄力",
    }
    defaults.update(overrides)
    return ChapterOutline(**defaults)


def _make_mock_llm(response_text: str | None = None) -> MagicMock:
    mock = MagicMock(spec=LLMClient)
    mock.chat.return_value = _make_llm_response(
        response_text if response_text is not None else _mock_llm_scenes(3)
    )
    return mock


# ---------------------------------------------------------------------------
# 1. 正向伏笔规划 (foreshadowings_to_plant)
# ---------------------------------------------------------------------------


def test_plant_from_chapter_brief_registers_to_kg():
    """chapter_brief.foreshadowing_plant 应登记到 KG 并返回到 plan。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()
    planner = PlotPlanner(mock_llm, knowledge_graph=kg)

    ch = _make_chapter_outline(
        chapter_brief={"foreshadowing_plant": ["神秘玉佩的来历", "老者留下的暗号"]},
    )
    plan = planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
    )

    plants = plan["foreshadowings_to_plant"]
    assert len(plants) == 2
    contents = {p["content"] for p in plants}
    assert "神秘玉佩的来历" in contents
    assert "老者留下的暗号" in contents

    # Each plant has a non-empty foreshadowing_id from KG registration
    for p in plants:
        assert p["foreshadowing_id"]
        assert p["target_chapter"] > ch.chapter_number

    # KG now contains foreshadowing nodes
    pending = kg.get_pending_foreshadowings(current_chapter=ch.chapter_number)
    assert len(pending) == 2
    pending_contents = {item["content"] for item in pending}
    assert "神秘玉佩的来历" in pending_contents
    assert "老者留下的暗号" in pending_contents


def test_plant_detects_keyword_埋设_in_key_events():
    """key_events 含 '埋设' 关键词时自动识别为 plant。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()
    planner = PlotPlanner(mock_llm, knowledge_graph=kg)

    ch = _make_chapter_outline(
        key_events=["主角路过茶馆", "埋设神秘玉佩", "离开小镇"],
    )
    plan = planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
    )

    plants = plan["foreshadowings_to_plant"]
    assert len(plants) == 1
    assert plants[0]["content"] == "埋设神秘玉佩"

    # Registered to KG
    pending = kg.get_pending_foreshadowings(current_chapter=ch.chapter_number)
    assert any("玉佩" in item["content"] for item in pending)


def test_plant_detects_foreshadow_keyword_english():
    """key_events 含 'foreshadowing' 也应被识别。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()
    planner = PlotPlanner(mock_llm, knowledge_graph=kg)

    ch = _make_chapter_outline(
        key_events=["Mention relic (foreshadowing)", "Move to next scene"],
    )
    plan = planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
    )

    plants = plan["foreshadowings_to_plant"]
    assert len(plants) == 1
    assert "foreshadowing" in plants[0]["content"].lower()


def test_plant_no_duplication_between_brief_and_key_events():
    """同一内容同时出现在 brief 和 key_events 时不重复登记。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()
    planner = PlotPlanner(mock_llm, knowledge_graph=kg)

    ch = _make_chapter_outline(
        key_events=["埋设神秘玉佩", "推进剧情"],
        chapter_brief={"foreshadowing_plant": ["埋设神秘玉佩"]},
    )
    plan = planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
    )

    plants = plan["foreshadowings_to_plant"]
    # 内容相同不重复登记
    contents = [p["content"] for p in plants]
    assert contents.count("埋设神秘玉佩") == 1


def test_plant_without_knowledge_graph_still_returns_empty_list():
    """未注入 knowledge_graph 时，不会尝试登记，foreshadowings_to_plant 为空。"""
    mock_llm = _make_mock_llm()
    planner = PlotPlanner(mock_llm)  # 无 KG

    ch = _make_chapter_outline(
        chapter_brief={"foreshadowing_plant": ["神秘玉佩"]},
    )
    plan = planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
    )

    # 无 KG 时 fid 为 None，但仍返回内容（可由外部后续登记）
    plants = plan["foreshadowings_to_plant"]
    assert len(plants) == 1
    assert plants[0]["content"] == "神秘玉佩"
    assert plants[0]["foreshadowing_id"] is None


def test_plant_empty_outline_returns_empty():
    """无 plant 信号时 foreshadowings_to_plant 为空。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()
    planner = PlotPlanner(mock_llm, knowledge_graph=kg)

    ch = _make_chapter_outline()  # 无 brief、key_events 也没有埋设关键词
    plan = planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
    )

    assert plan["foreshadowings_to_plant"] == []


def test_plant_handles_kg_failure_gracefully():
    """KG 登记失败时不应抛异常，返回 foreshadowing_id=None。"""
    mock_llm = _make_mock_llm()
    failing_kg = MagicMock()
    failing_kg.add_foreshadowing_node.side_effect = RuntimeError("KG down")
    failing_kg.get_pending_foreshadowings.return_value = []

    planner = PlotPlanner(mock_llm, knowledge_graph=failing_kg)

    ch = _make_chapter_outline(
        chapter_brief={"foreshadowing_plant": ["神秘玉佩"]},
    )
    plan = planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
    )

    plants = plan["foreshadowings_to_plant"]
    assert len(plants) == 1
    assert plants[0]["foreshadowing_id"] is None
    assert plants[0]["content"] == "神秘玉佩"


# ---------------------------------------------------------------------------
# 2. 后置伏笔检索 (reusable_details)
# ---------------------------------------------------------------------------


def test_reusable_details_found_via_tool():
    """mock foreshadowing_tool 返回两条闲笔，plan 中应包含它们。"""
    mock_llm = _make_mock_llm()
    tool = MagicMock()
    tool.search_reusable_details.return_value = [
        DetailEntry(
            detail_id="d1",
            chapter=3,
            content="酒馆老板擦拭一把古剑",
            context="主角瞥见酒馆柜台后...",
            category="道具",
            status="available",
        ),
        DetailEntry(
            detail_id="d2",
            chapter=5,
            content="山道上的奇怪脚印",
            context="雨后山道留着深浅不一...",
            category="异常现象",
            status="available",
        ),
    ]

    planner = PlotPlanner(mock_llm, foreshadowing_tool=tool)

    ch = _make_chapter_outline(chapter_number=10)
    plan = planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
        reusable_query="主角需要一把信物触发回忆",
    )

    details = plan["reusable_details"]
    assert len(details) == 2
    assert details[0]["detail_id"] == "d1"
    assert details[0]["chapter"] == 3
    assert details[1]["detail_id"] == "d2"

    # Tool was called with correct query + current_chapter
    tool.search_reusable_details.assert_called_once()
    kwargs = tool.search_reusable_details.call_args.kwargs
    assert kwargs["query"] == "主角需要一把信物触发回忆"
    assert kwargs["current_chapter"] == 10


def test_reusable_details_filters_out_promoted():
    """已升级的闲笔 (status=promoted) 不应出现在结果中。"""
    mock_llm = _make_mock_llm()
    tool = MagicMock()
    tool.search_reusable_details.return_value = [
        DetailEntry(
            detail_id="d1",
            chapter=3,
            content="available 闲笔",
            context="...",
            category="道具",
            status="available",
        ),
        DetailEntry(
            detail_id="d2",
            chapter=4,
            content="已升级闲笔",
            context="...",
            category="道具",
            status="promoted",
        ),
    ]

    planner = PlotPlanner(mock_llm, foreshadowing_tool=tool)
    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
        reusable_query="相关查询",
    )

    details = plan["reusable_details"]
    assert len(details) == 1
    assert details[0]["detail_id"] == "d1"


def test_reusable_details_query_auto_built_from_goal():
    """未传 reusable_query 时，自动基于 chapter_outline.goal 构建查询。"""
    mock_llm = _make_mock_llm()
    tool = MagicMock()
    tool.search_reusable_details.return_value = []

    planner = PlotPlanner(mock_llm, foreshadowing_tool=tool)
    ch = _make_chapter_outline(
        goal="主角寻找神秘信物",
        key_events=["进入古墓", "发现玉佩"],
    )
    planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
    )

    # Ensure tool was called; query should contain goal text
    tool.search_reusable_details.assert_called_once()
    used_query = tool.search_reusable_details.call_args.kwargs["query"]
    assert "主角寻找神秘信物" in used_query


def test_reusable_details_without_tool_returns_empty():
    """未注入 foreshadowing_tool 时 reusable_details 为空。"""
    mock_llm = _make_mock_llm()
    planner = PlotPlanner(mock_llm)  # 无 tool

    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
        reusable_query="需要一把剑",
    )

    assert plan["reusable_details"] == []


def test_reusable_details_empty_query_skips_search():
    """查询无法构建（空 goal + 空 key_events）时不调用 tool。"""
    mock_llm = _make_mock_llm()
    tool = MagicMock()

    planner = PlotPlanner(mock_llm, foreshadowing_tool=tool)
    ch = _make_chapter_outline(goal=" ", key_events=[""])
    # ChapterOutline 要求 goal 非空，所以这里只能 force-setattr
    object.__setattr__(ch, "goal", "")
    object.__setattr__(ch, "key_events", [])

    plan = planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
    )

    assert plan["reusable_details"] == []
    tool.search_reusable_details.assert_not_called()


def test_reusable_details_handles_tool_failure():
    """tool.search_reusable_details 抛异常时返回空列表而非崩溃。"""
    mock_llm = _make_mock_llm()
    tool = MagicMock()
    tool.search_reusable_details.side_effect = RuntimeError("vector store down")

    planner = PlotPlanner(mock_llm, foreshadowing_tool=tool)
    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
        reusable_query="something",
    )

    assert plan["reusable_details"] == []


def test_reusable_details_accepts_plain_dict():
    """tool 返回 plain dict 时也能正常处理（灵活 mock 支持）。"""
    mock_llm = _make_mock_llm()
    tool = MagicMock()
    tool.search_reusable_details.return_value = [
        {
            "detail_id": "d99",
            "chapter": 2,
            "content": "墙上的裂缝",
            "context": "主角盯着斑驳墙面...",
            "category": "环境",
            "status": "available",
        }
    ]

    planner = PlotPlanner(mock_llm, foreshadowing_tool=tool)
    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
        reusable_query="线索",
    )

    details = plan["reusable_details"]
    assert len(details) == 1
    assert details[0]["detail_id"] == "d99"
    assert details[0]["chapter"] == 2


# ---------------------------------------------------------------------------
# 3. 回收提醒 (foreshadowings_to_resolve)
# ---------------------------------------------------------------------------


def test_resolve_reminder_within_lookahead_window():
    """pending 伏笔 target_chapter 在 [当前章, 当前章+2] 区间内应出现在 reminder。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()
    # 预置一条 target=10 的 pending 伏笔
    kg.add_foreshadowing_node(
        foreshadowing_id="fs_due_at_10",
        planted_chapter=5,
        content="神秘玉佩的秘密",
        target_chapter=10,
        status="pending",
    )

    planner = PlotPlanner(mock_llm, knowledge_graph=kg)

    # 规划第 9 章：target=10 在 [9, 11] 窗口内
    ch = _make_chapter_outline(chapter_number=9)
    plan = planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
    )

    reminders = plan["foreshadowings_to_resolve"]
    assert len(reminders) == 1
    assert reminders[0]["foreshadowing_id"] == "fs_due_at_10"
    assert reminders[0]["content"] == "神秘玉佩的秘密"
    assert reminders[0]["target_chapter"] == 10
    assert reminders[0]["planted_chapter"] == 5


def test_resolve_reminder_excludes_far_future_targets():
    """target 远在未来（>当前章+2）的 pending 不进入 reminder。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()
    kg.add_foreshadowing_node(
        foreshadowing_id="fs_far",
        planted_chapter=5,
        content="遥远的伏笔",
        target_chapter=30,
        status="pending",
    )

    planner = PlotPlanner(mock_llm, knowledge_graph=kg)
    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(chapter_number=9),
        volume_context={},
        characters=[],
    )

    assert plan["foreshadowings_to_resolve"] == []


def test_resolve_reminder_excludes_unresolved_target_minus_one():
    """target_chapter == -1（未指定回收章）的伏笔不出现在 reminder。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()
    kg.add_foreshadowing_node(
        foreshadowing_id="fs_noplan",
        planted_chapter=5,
        content="未计划回收的伏笔",
        target_chapter=-1,
        status="pending",
    )

    planner = PlotPlanner(mock_llm, knowledge_graph=kg)
    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(chapter_number=9),
        volume_context={},
        characters=[],
    )

    assert plan["foreshadowings_to_resolve"] == []


def test_resolve_reminder_excludes_collected():
    """已回收 (status=collected) 的伏笔不出现在 reminder。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()
    kg.add_foreshadowing_node(
        foreshadowing_id="fs_done",
        planted_chapter=3,
        content="已回收",
        target_chapter=10,
        status="collected",
    )

    planner = PlotPlanner(mock_llm, knowledge_graph=kg)
    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(chapter_number=9),
        volume_context={},
        characters=[],
    )

    assert plan["foreshadowings_to_resolve"] == []


def test_resolve_reminder_without_kg_returns_empty():
    """未注入 KG 时 foreshadowings_to_resolve 为空。"""
    mock_llm = _make_mock_llm()
    planner = PlotPlanner(mock_llm)

    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(chapter_number=9),
        volume_context={},
        characters=[],
    )

    assert plan["foreshadowings_to_resolve"] == []


def test_resolve_reminder_empty_kg():
    """KG 为空时 reminder 为空（不崩溃）。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()  # 空 KG
    planner = PlotPlanner(mock_llm, knowledge_graph=kg)

    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(chapter_number=9),
        volume_context={},
        characters=[],
    )

    assert plan["foreshadowings_to_resolve"] == []


def test_resolve_reminder_handles_kg_failure():
    """KG 查询失败时返回空 list 而非崩溃。"""
    mock_llm = _make_mock_llm()
    failing_kg = MagicMock()
    failing_kg.get_pending_foreshadowings.side_effect = RuntimeError("graph err")
    # Ensure the plant path doesn't error either (return falsy)

    planner = PlotPlanner(mock_llm, knowledge_graph=failing_kg)
    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(chapter_number=9),
        volume_context={},
        characters=[],
    )

    assert plan["foreshadowings_to_resolve"] == []


# ---------------------------------------------------------------------------
# Integration: plan_chapter returns full structure
# ---------------------------------------------------------------------------


def test_plan_chapter_returns_all_four_keys():
    """plan_chapter 返回 dict 必须包含 scenes + 三个伏笔字段。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()
    tool = MagicMock()
    tool.search_reusable_details.return_value = []

    planner = PlotPlanner(mock_llm, foreshadowing_tool=tool, knowledge_graph=kg)
    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
    )

    assert set(plan.keys()) == {
        "scenes",
        "foreshadowings_to_plant",
        "foreshadowings_to_resolve",
        "reusable_details",
    }
    assert isinstance(plan["scenes"], list)
    assert isinstance(plan["foreshadowings_to_plant"], list)
    assert isinstance(plan["foreshadowings_to_resolve"], list)
    assert isinstance(plan["reusable_details"], list)


def test_plan_chapter_combines_all_three_features():
    """端到端：plant + resolve + reusable 同时生效。"""
    mock_llm = _make_mock_llm()
    kg = KnowledgeGraph()
    kg.add_foreshadowing_node(
        foreshadowing_id="fs_old",
        planted_chapter=2,
        content="老者留下的戒指",
        target_chapter=10,
        status="pending",
    )

    tool = MagicMock()
    tool.search_reusable_details.return_value = [
        DetailEntry(
            detail_id="detail_007",
            chapter=4,
            content="酒馆墙上的剑痕",
            context="主角注意到墙上有一道剑痕...",
            category="环境",
            status="available",
        ),
    ]

    planner = PlotPlanner(mock_llm, foreshadowing_tool=tool, knowledge_graph=kg)

    ch = _make_chapter_outline(
        chapter_number=9,
        chapter_brief={"foreshadowing_plant": ["神秘光芒"]},
    )
    plan = planner.plan_chapter(
        chapter_outline=ch,
        volume_context={},
        characters=[],
        reusable_query="寻找旧武器的线索",
    )

    # Plant: 神秘光芒 登记到 KG
    plants = plan["foreshadowings_to_plant"]
    assert len(plants) == 1
    assert plants[0]["content"] == "神秘光芒"
    assert plants[0]["foreshadowing_id"] is not None

    # Resolve: fs_old 在 [9, 11] 窗口
    resolves = plan["foreshadowings_to_resolve"]
    assert len(resolves) == 1
    assert resolves[0]["foreshadowing_id"] == "fs_old"

    # Reusable: detail_007
    reusable = plan["reusable_details"]
    assert len(reusable) == 1
    assert reusable[0]["detail_id"] == "detail_007"

    # Scenes still populated
    assert len(plan["scenes"]) == 3


def test_plan_chapter_backward_compat_no_tool_no_kg():
    """未注入 foreshadowing_tool / knowledge_graph 时 plan_chapter 仍可工作。"""
    mock_llm = _make_mock_llm()
    planner = PlotPlanner(mock_llm)  # 旧签名：只给 llm

    plan = planner.plan_chapter(
        chapter_outline=_make_chapter_outline(),
        volume_context={},
        characters=[],
    )

    assert plan["scenes"]
    assert plan["foreshadowings_to_plant"] == []
    assert plan["foreshadowings_to_resolve"] == []
    assert plan["reusable_details"] == []


def test_plan_chapter_llm_failure_propagates():
    """LLM 抛异常时 plan_chapter 应透传 ValueError（与 decompose_chapter 一致）。"""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.chat.return_value = _make_llm_response("not json at all")

    planner = PlotPlanner(mock_llm)
    with pytest.raises(ValueError):
        planner.plan_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[],
        )
