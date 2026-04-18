"""ChapterPlanner tests — Phase 2-δ.

Covers:

* Happy path (LedgerStore supplies foreshadowings/debts/characters).
* Ledger-less degraded path (missing LedgerStore → empty ledger fields).
* Malformed LLM JSON fallback → default scene structure.
* ``update_chapter_brief`` merges edits.
* ``chapter_planner_node`` writes ``current_scenes`` +
  ``current_chapter_outline.chapter_brief``.
* End-hook evaluation helper produces sensible scores.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _good_llm_payload() -> str:
    return json.dumps(
        {
            "revised_goal": "修正后的目标",
            "revision_reason": "前章角色受伤，本章需调整",
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "接续上章",
                    "summary": "接续上章结尾，主角回到据点",
                    "characters_involved": ["主角"],
                    "mood": "蓄力",
                    "tension_level": 0.4,
                    "target_words": 900,
                    "narrative_focus": "描写",
                },
                {
                    "scene_number": 2,
                    "title": "回收伏笔",
                    "summary": "碰到神秘人，回收第5章伏笔",
                    "characters_involved": ["主角", "神秘人"],
                    "mood": "反转",
                    "tension_level": 0.8,
                    "target_words": 1100,
                    "narrative_focus": "对话",
                },
            ],
            "tone_notes": "节奏紧凑",
            "end_hook": "身后传来脚步声",
            "end_hook_type": "悬疑",
        },
        ensure_ascii=False,
    )


@pytest.fixture
def mock_llm_good() -> MagicMock:
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content=_good_llm_payload(), model="test", usage=None
    )
    return llm


@pytest.fixture
def mock_llm_bad_json() -> MagicMock:
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content="not valid json at all", model="test", usage=None
    )
    return llm


@pytest.fixture
def fake_ledger() -> MagicMock:
    ledger = MagicMock()
    ledger.snapshot_for_chapter.return_value = {
        "pending_debts": [
            {"description": "主角答应救师妹", "urgency_level": "high"}
        ],
        "collectable_foreshadowings": [
            {"content": "神秘令牌", "planted_chapter": 5}
        ],
        "plantable_foreshadowings": [],
        "active_characters": [
            {"name": "主角", "last_appearance": 11},
            {"name": "师妹", "last_appearance": 10},
        ],
        "world_facts": [
            {"name": "归墟阵", "category": "术法"},
        ],
        "pending_milestones": [
            {"description": "抵达归墟"}
        ],
    }
    return ledger


# ---------------------------------------------------------------------------
# propose_chapter_brief
# ---------------------------------------------------------------------------


def test_propose_brief_happy_path_with_ledger(mock_llm_good, fake_ledger):
    from src.novel.agents.chapter_planner import ChapterPlanner
    from src.novel.models.novel import ChapterOutline

    planner = ChapterPlanner(mock_llm_good, ledger=fake_ledger)
    outline = ChapterOutline(
        chapter_number=12,
        title="旧事浮现",
        goal="主角重返旧地",
        key_events=["抵达旧地", "遭遇旧敌"],
        involved_characters=["主角"],
        estimated_words=2500,
        mood="蓄力",
    )

    proposal = planner.propose_chapter_brief(
        novel={"characters": [{"name": "主角"}]},
        volume_number=1,
        chapter_number=12,
        chapter_outline=outline,
    )

    # Ledger fields populated
    assert proposal.brief.must_fulfill_debts == ["主角答应救师妹"]
    assert proposal.brief.must_collect_foreshadowings == ["神秘令牌"]
    assert "主角" in proposal.brief.active_characters
    assert "归墟阵" in proposal.brief.world_facts_to_respect

    # Scenes flattened into scene_plans for Writer
    assert len(proposal.scene_plans) == 2
    assert proposal.scene_plans[0]["summary"].startswith("接续上章")

    # Hook fields set
    assert proposal.brief.end_hook == "身后传来脚步声"
    assert proposal.brief.end_hook_type == "悬疑"

    # Ledger was actually queried for chapter 12
    fake_ledger.snapshot_for_chapter.assert_called_once_with(12)

    # No warnings when ledger works
    assert proposal.warnings == []


def test_propose_brief_without_ledger(mock_llm_good):
    from src.novel.agents.chapter_planner import ChapterPlanner
    from src.novel.models.novel import ChapterOutline

    planner = ChapterPlanner(mock_llm_good, ledger=None)
    outline = ChapterOutline(
        chapter_number=3,
        title="开局",
        goal="展开主线",
        key_events=["出场"],
        involved_characters=["主角"],
        estimated_words=2200,
        mood="蓄力",
    )

    proposal = planner.propose_chapter_brief(
        novel={"characters": [{"name": "主角"}, {"name": "配角"}]},
        volume_number=1,
        chapter_number=3,
        chapter_outline=outline,
    )

    # No ledger → empty foreshadowings / debts
    assert proposal.brief.must_fulfill_debts == []
    assert proposal.brief.must_collect_foreshadowings == []
    # Active characters fall back to the novel roster
    assert "主角" in proposal.brief.active_characters
    # Scene plans still produced from LLM
    assert len(proposal.scene_plans) == 2
    # Warning about missing ledger is exposed to the caller
    assert any("no_ledger" in w or "ledger" in w for w in proposal.warnings)


def test_propose_brief_llm_bad_json_falls_back(mock_llm_bad_json, fake_ledger):
    from src.novel.agents.chapter_planner import ChapterPlanner
    from src.novel.models.novel import ChapterOutline

    planner = ChapterPlanner(mock_llm_bad_json, ledger=fake_ledger)
    outline = ChapterOutline(
        chapter_number=5,
        title="Test",
        goal="推进",
        key_events=["a"],
        involved_characters=["主角"],
        estimated_words=2100,
        mood="蓄力",
    )

    proposal = planner.propose_chapter_brief(
        novel={"characters": []},
        volume_number=1,
        chapter_number=5,
        chapter_outline=outline,
    )

    # Falls back to default 3-scene structure
    assert len(proposal.scene_plans) == 3
    # Ledger fields still populated because the bad-LLM path is separate
    assert proposal.brief.must_fulfill_debts == ["主角答应救师妹"]


def test_propose_brief_ledger_raises_gracefully(mock_llm_good):
    from src.novel.agents.chapter_planner import ChapterPlanner
    from src.novel.models.novel import ChapterOutline

    broken_ledger = MagicMock()
    broken_ledger.snapshot_for_chapter.side_effect = RuntimeError("db down")

    planner = ChapterPlanner(mock_llm_good, ledger=broken_ledger)
    outline = ChapterOutline(
        chapter_number=7,
        title="Test",
        goal="推进",
        key_events=["a"],
        involved_characters=[],
        estimated_words=2200,
        mood="蓄力",
    )

    proposal = planner.propose_chapter_brief(
        novel={"characters": [{"name": "主角"}]},
        volume_number=1,
        chapter_number=7,
        chapter_outline=outline,
    )

    assert proposal.brief.must_fulfill_debts == []
    assert any("ledger_error" in w for w in proposal.warnings)
    # Falls back to novel-based character list
    assert "主角" in proposal.brief.active_characters


# ---------------------------------------------------------------------------
# update_chapter_brief
# ---------------------------------------------------------------------------


def test_update_chapter_brief_merges_edits(mock_llm_good, fake_ledger):
    from src.novel.agents.chapter_planner import ChapterPlanner

    planner = ChapterPlanner(mock_llm_good, ledger=fake_ledger)
    base = {
        "chapter_number": 4,
        "goal": "原目标",
        "scenes": [
            {"summary": "s1", "characters": ["主角"], "title": "老场景"},
        ],
        "must_collect_foreshadowings": [],
        "must_fulfill_debts": [],
        "active_characters": ["主角"],
        "world_facts_to_respect": [],
        "target_words": 2500,
        "chapter_type": "buildup",
        "tone_notes": "",
        "end_hook": "",
        "end_hook_type": "",
    }

    proposal = planner.update_chapter_brief(
        base,
        edits={
            "goal": "新目标",
            "tone_notes": "节奏加快",
            "scenes": [
                {"summary": "改写的场景", "characters": ["主角"]},
            ],
        },
    )

    assert proposal.brief.goal == "新目标"
    assert proposal.brief.tone_notes == "节奏加快"
    assert len(proposal.brief.scenes) == 1
    assert proposal.brief.scenes[0].summary == "改写的场景"
    # Source tag switches to manual_edit
    assert proposal.source == "manual_edit"


def test_update_chapter_brief_rejects_malformed_scene(mock_llm_good):
    from src.novel.agents.chapter_planner import ChapterPlanner

    planner = ChapterPlanner(mock_llm_good, ledger=None)
    base = {
        "chapter_number": 1,
        "goal": "",
        "scenes": [],
        "must_collect_foreshadowings": [],
        "must_fulfill_debts": [],
        "active_characters": [],
        "world_facts_to_respect": [],
        "target_words": 2500,
        "chapter_type": "buildup",
        "tone_notes": "",
        "end_hook": "",
        "end_hook_type": "",
    }
    proposal = planner.update_chapter_brief(
        base,
        edits={"scenes": ["not a dict", {"summary": "ok"}]},
    )
    # Malformed scene silently dropped; valid one retained
    summaries = [s.summary for s in proposal.brief.scenes]
    assert summaries == ["ok"]


def test_update_chapter_brief_bad_type_raises():
    from src.novel.agents.chapter_planner import ChapterPlanner

    planner = ChapterPlanner(MagicMock(), ledger=None)
    with pytest.raises(TypeError):
        planner.update_chapter_brief(brief="not a dict", edits={})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# evaluate_hook
# ---------------------------------------------------------------------------


def test_evaluate_hook_strong_ending_scores_high():
    from src.novel.agents.chapter_planner import ChapterPlanner

    text = "前文内容。最后他猛然抬头，身后忽然出现一道黑影！"
    result = ChapterPlanner.evaluate_hook(text)
    assert result["score"] >= 7
    assert result["needs_improvement"] is False


def test_evaluate_hook_empty_text():
    from src.novel.agents.chapter_planner import ChapterPlanner

    result = ChapterPlanner.evaluate_hook("")
    assert result["score"] == 0
    assert result["needs_improvement"] is True
    assert result["hook_type"] == "none"


def test_evaluate_hook_bland_ending_flagged():
    from src.novel.agents.chapter_planner import ChapterPlanner

    text = "这一天过得很平静。大家都睡下了。"
    result = ChapterPlanner.evaluate_hook(text)
    assert result["score"] <= 6


# ---------------------------------------------------------------------------
# chapter_planner_node (LangGraph integration)
# ---------------------------------------------------------------------------


def test_chapter_planner_node_writes_scenes_and_brief(fake_ledger):
    from src.novel.agents.chapter_planner import chapter_planner_node

    mock_llm = MagicMock()
    mock_llm.chat.return_value = LLMResponse(
        content=_good_llm_payload(), model="test", usage=None
    )

    state = {
        "current_chapter": 12,
        "current_chapter_outline": {
            "chapter_number": 12,
            "title": "旧事浮现",
            "goal": "主角重返旧地",
            "key_events": ["抵达旧地"],
            "involved_characters": ["主角"],
            "estimated_words": 2500,
            "mood": "蓄力",
        },
        "ledger_store": fake_ledger,
        "characters": [{"name": "主角"}],
        "config": {"llm": {"outline_generation": "m"}},
    }

    with patch(
        "src.novel.agents.chapter_planner.create_llm_client",
        return_value=mock_llm,
    ):
        result = chapter_planner_node(state)

    assert "chapter_planner" in result["completed_nodes"]
    assert result["errors"] == []
    scenes = result["current_scenes"]
    assert len(scenes) == 2
    # current_chapter_outline should be updated (goal revised)
    revised = result["current_chapter_outline"]
    assert revised["goal"] == "修正后的目标"
    assert revised["chapter_brief"]["foreshadowing_collect"] == ["神秘令牌"]
    # Structured brief snapshot stored
    assert result["current_chapter_brief"]["must_fulfill_debts"] == [
        "主角答应救师妹"
    ]
    # Decision log records the planner
    assert result["decisions"][0]["agent"] == "ChapterPlanner"


def test_chapter_planner_node_errors_when_outline_missing():
    from src.novel.agents.chapter_planner import chapter_planner_node

    state = {"current_chapter": 3, "config": {}}
    result = chapter_planner_node(state)
    assert "chapter_planner" in result["completed_nodes"]
    assert any(
        "当前章节大纲" in e.get("message", "") for e in result.get("errors", [])
    )


def test_chapter_planner_node_handles_llm_init_failure():
    from src.novel.agents.chapter_planner import chapter_planner_node

    state = {
        "current_chapter": 2,
        "current_chapter_outline": {
            "chapter_number": 2,
            "title": "t",
            "goal": "g",
            "key_events": [],
            "involved_characters": [],
            "estimated_words": 2500,
            "mood": "蓄力",
        },
        "config": {},
    }

    with patch(
        "src.novel.agents.chapter_planner.create_llm_client",
        side_effect=RuntimeError("no api key"),
    ):
        result = chapter_planner_node(state)

    assert any(
        "LLM 初始化失败" in e.get("message", "")
        for e in result.get("errors", [])
    )
