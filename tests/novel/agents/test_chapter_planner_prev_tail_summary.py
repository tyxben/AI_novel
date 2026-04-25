"""ChapterPlanner previous_tail summarization tests.

Activates the dead ``previous_tail`` parameter so the Writer consumes a
structured summary instead of the raw prior chapter text.  All tests are
signature-level (no real LLM), marked ``signature``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.chapter_planner import ChapterPlanner
from src.novel.models.chapter_brief import ChapterBrief
from src.novel.models.novel import ChapterOutline


pytestmark = pytest.mark.signature


def _good_plan_payload() -> str:
    return json.dumps(
        {
            "revised_goal": "修正后的目标",
            "revision_reason": "no_revision",
            "scenes": [
                {
                    "scene_number": 1,
                    "title": "场景一",
                    "summary": "推进",
                    "characters_involved": ["主角"],
                    "mood": "蓄力",
                    "tension_level": 0.4,
                    "target_words": 900,
                    "narrative_focus": "描写",
                }
            ],
            "tone_notes": "紧凑",
            "end_hook": "黑影掠过",
            "end_hook_type": "悬疑",
        },
        ensure_ascii=False,
    )


def _make_planner_with_summary(summary: str) -> tuple[ChapterPlanner, MagicMock]:
    """Planner whose first LLM.chat() returns *summary*, second returns plan."""
    llm = MagicMock()
    llm.chat.side_effect = [
        LLMResponse(content=summary, model="test", usage=None),
        LLMResponse(content=_good_plan_payload(), model="test", usage=None),
    ]
    return ChapterPlanner(llm, ledger=None), llm


# ---------------------------------------------------------------------------
# _summarize_previous_tail (pure unit tests)
# ---------------------------------------------------------------------------


def test_summarize_none_returns_empty():
    planner = ChapterPlanner(MagicMock(), ledger=None)
    assert planner._summarize_previous_tail(None) == ""


def test_summarize_empty_returns_empty():
    planner = ChapterPlanner(MagicMock(), ledger=None)
    assert planner._summarize_previous_tail("") == ""
    assert planner._summarize_previous_tail("     ") == ""


def test_summarize_short_bypasses_llm():
    llm = MagicMock()
    planner = ChapterPlanner(llm, ledger=None)
    short = "主角走出矿道，回头看了一眼。"  # < 80 chars
    result = planner._summarize_previous_tail(short)
    assert result == short.strip()[:200]
    assert len(result) <= 200
    assert llm.chat.call_count == 0


def test_summarize_long_calls_llm():
    expected = "主角在矿道归来途中面对俘虏处置问题，情绪紧张。留下'是否杀俘'的钩子。"
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(content=expected, model="test", usage=None)
    planner = ChapterPlanner(llm, ledger=None)
    long_tail = "这是一段很长的原文内容。" * 20  # well over 80 chars
    result = planner._summarize_previous_tail(long_tail)
    assert result == expected
    assert len(result) <= 200
    assert llm.chat.call_count == 1


def test_summarize_llm_failure_returns_empty():
    llm = MagicMock()
    llm.chat.side_effect = RuntimeError("api down")
    planner = ChapterPlanner(llm, ledger=None)
    long_tail = "某一段很长的文字。" * 20
    result = planner._summarize_previous_tail(long_tail)
    assert result == ""


def test_summarize_empty_response_returns_empty():
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(content="", model="test", usage=None)
    planner = ChapterPlanner(llm, ledger=None)
    long_tail = "文字" * 50
    assert planner._summarize_previous_tail(long_tail) == ""


def test_summarize_response_capped_at_200_chars():
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content="啊" * 400, model="test", usage=None
    )
    planner = ChapterPlanner(llm, ledger=None)
    long_tail = "原文。" * 40
    result = planner._summarize_previous_tail(long_tail)
    assert len(result) == 200


def test_summarize_prompt_contains_禁止_keywords():
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(content="摘要", model="test", usage=None)
    planner = ChapterPlanner(llm, ledger=None)
    long_tail = "文字文字" * 25
    planner._summarize_previous_tail(long_tail)
    call = llm.chat.call_args
    messages = call.args[0] if call.args else call.kwargs.get("messages")
    assert messages[0]["role"] == "system"
    user_content = messages[1]["content"]
    assert "禁止复制原文" in user_content
    assert "禁止续写" in user_content
    assert "结构化" in user_content


# ---------------------------------------------------------------------------
# propose_chapter_brief integration
# ---------------------------------------------------------------------------


def _outline(chapter_number: int = 32) -> ChapterOutline:
    return ChapterOutline(
        chapter_number=chapter_number,
        title=f"第{chapter_number}章",
        goal="推进主线",
        key_events=["事件"],
        involved_characters=["主角"],
        estimated_words=2500,
        mood="蓄力",
    )


def test_propose_chapter_brief_fills_tail_summary():
    summary = "矿道外，主角面对俘虏抉择，情绪紧绷，钩子：杀俘 or 放走。"
    planner, llm = _make_planner_with_summary(summary)
    long_tail = "原文内容。" * 50
    proposal = planner.propose_chapter_brief(
        novel={"characters": [{"name": "主角"}]},
        volume_number=1,
        chapter_number=32,
        chapter_outline=_outline(32),
        previous_tail=long_tail,
    )
    assert proposal.brief.previous_chapter_tail_summary == summary
    assert len(proposal.brief.previous_chapter_tail_summary) <= 200
    # Two LLM calls: summary + plan
    assert llm.chat.call_count == 2


def test_propose_chapter_brief_no_prev_tail():
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content=_good_plan_payload(), model="test", usage=None
    )
    planner = ChapterPlanner(llm, ledger=None)
    proposal = planner.propose_chapter_brief(
        novel={"characters": [{"name": "主角"}]},
        volume_number=1,
        chapter_number=5,
        chapter_outline=_outline(5),
        previous_tail=None,
    )
    assert proposal.brief.previous_chapter_tail_summary == ""
    # Only the plan call should fire
    assert llm.chat.call_count == 1


def test_propose_chapter_brief_empty_prev_tail():
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content=_good_plan_payload(), model="test", usage=None
    )
    planner = ChapterPlanner(llm, ledger=None)
    proposal = planner.propose_chapter_brief(
        novel={"characters": [{"name": "主角"}]},
        volume_number=1,
        chapter_number=5,
        chapter_outline=_outline(5),
        previous_tail="",
    )
    assert proposal.brief.previous_chapter_tail_summary == ""
    assert llm.chat.call_count == 1


# ---------------------------------------------------------------------------
# to_legacy_chapter_brief dict mapping
# ---------------------------------------------------------------------------


def test_to_legacy_chapter_brief_excludes_runtime_derived_fields():
    """H3：previous_chapter_* 是每次规划的瞬时派生摘要，不应落盘
    到 novel.json，否则下次规划会读到 stale 数据。
    """
    brief = ChapterBrief(
        chapter_number=5,
        previous_chapter_tail_summary="X",
        previous_chapter_end_hook="Y",
    )
    legacy = brief.to_legacy_chapter_brief()
    assert "previous_chapter_tail_summary" not in legacy
    assert "previous_chapter_end_hook" not in legacy


def test_to_legacy_chapter_brief_preserves_end_hook():
    """C2：end_hook 必须进 legacy dict，否则
    _lookup_previous_end_hook(novel, n+1) 永远返回空。"""
    brief = ChapterBrief(
        chapter_number=5,
        end_hook="黑影掠过",
        end_hook_type="悬疑",
    )
    legacy = brief.to_legacy_chapter_brief()
    assert legacy["end_hook"] == "黑影掠过"
    assert legacy["end_hook_type"] == "悬疑"


# ---------------------------------------------------------------------------
# previous_chapter_end_hook lookup
# ---------------------------------------------------------------------------


def test_previous_chapter_end_hook_from_novel_dict():
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content=_good_plan_payload(), model="test", usage=None
    )
    planner = ChapterPlanner(llm, ledger=None)
    # Previous chapter (5) lives on the flat outline.chapters list
    novel = {
        "characters": [{"name": "主角"}],
        "outline": {
            "chapters": [
                {"chapter_number": 4, "chapter_brief": {"end_hook": "旧悬念"}},
                {"chapter_number": 5, "chapter_brief": {"end_hook": "悬念 Z"}},
            ]
        },
    }
    proposal = planner.propose_chapter_brief(
        novel=novel,
        volume_number=1,
        chapter_number=6,
        chapter_outline=_outline(6),
    )
    assert proposal.brief.previous_chapter_end_hook == "悬念 Z"


def test_previous_chapter_end_hook_from_volume_fallback():
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content=_good_plan_payload(), model="test", usage=None
    )
    planner = ChapterPlanner(llm, ledger=None)
    novel = {
        "characters": [{"name": "主角"}],
        "volumes": [
            {
                "volume_number": 1,
                "chapters": [
                    {"chapter_number": 5, "chapter_brief": {"end_hook": "卷内悬念"}},
                ],
            }
        ],
    }
    proposal = planner.propose_chapter_brief(
        novel=novel,
        volume_number=1,
        chapter_number=6,
        chapter_outline=_outline(6),
    )
    assert proposal.brief.previous_chapter_end_hook == "卷内悬念"


def test_previous_chapter_end_hook_missing_safe():
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content=_good_plan_payload(), model="test", usage=None
    )
    planner = ChapterPlanner(llm, ledger=None)
    # No chapter_brief / no end_hook anywhere
    novel = {
        "characters": [{"name": "主角"}],
        "outline": {
            "chapters": [{"chapter_number": 5, "title": "无钩子"}]
        },
    }
    proposal = planner.propose_chapter_brief(
        novel=novel,
        volume_number=1,
        chapter_number=6,
        chapter_outline=_outline(6),
    )
    assert proposal.brief.previous_chapter_end_hook == ""


def test_previous_chapter_end_hook_first_chapter_is_empty():
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content=_good_plan_payload(), model="test", usage=None
    )
    planner = ChapterPlanner(llm, ledger=None)
    novel = {"characters": [{"name": "主角"}]}
    proposal = planner.propose_chapter_brief(
        novel=novel,
        volume_number=1,
        chapter_number=1,
        chapter_outline=_outline(1),
    )
    assert proposal.brief.previous_chapter_end_hook == ""


def test_previous_chapter_end_hook_none_novel_safe():
    assert ChapterPlanner._lookup_previous_end_hook(None, 5) == ""


def test_previous_chapter_end_hook_handles_malformed_structure():
    # volumes is wrong type, outline missing — should not raise
    assert (
        ChapterPlanner._lookup_previous_end_hook(
            {"volumes": "not a list", "outline": 42}, 5
        )
        == ""
    )
