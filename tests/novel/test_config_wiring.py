"""Tests for wiring GenerationConfig and QualityConfig into pipeline code.

Covers:
- QualityReviewer: enable_llm_scoring config
- QualityReviewer: enable_rule_check config
- QualityCheckTool: blacklist_overrides parameter
- PlotPlanner: scene_per_chapter cap
- PlotPlanner: words_per_scene prompt injection
- PlotPlanner: words_per_chapter clamp
- quality_reviewer_node: config propagation
- plot_planner_node: config propagation
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMClient, LLMResponse
from src.novel.agents.plot_planner import PlotPlanner, plot_planner_node
from src.novel.agents.quality_reviewer import (
    QualityReviewer,
    quality_reviewer_node,
)
from src.novel.models.novel import ChapterOutline
from src.novel.tools.quality_check_tool import QualityCheckTool


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_fake_llm(response_json: dict | None = None) -> MagicMock:
    llm = MagicMock()
    if response_json is None:
        response_json = {
            "plot_coherence": 8.0,
            "writing_quality": 7.5,
            "character_portrayal": 7.0,
            "ai_flavor_score": 8.0,
            "summary": "ok",
        }
    llm.chat.return_value = FakeLLMResponse(
        content=json.dumps(response_json, ensure_ascii=False)
    )
    return llm


_CLEAN_TEXT = (
    "清晨的阳光透过窗帘洒进房间。\n"
    "李明揉了揉眼睛，从床上坐起来。\n"
    "今天是他入职新公司的第一天，他有些紧张。\n"
    "洗漱完毕，他穿上那套新买的西装，对着镜子整了整领带。\n"
    "出门时，楼下的早餐铺飘来阵阵包子的香气。\n"
)

_AI_FLAVOR_TEXT = (
    "他的内心翻涌着莫名的情绪。\n"
    "嘴角勾起一抹淡淡的笑意。\n"
    "空气仿佛凝固了。\n"
    "然而他并不知道，命运的齿轮开始转动。\n"
    "一股令人窒息的气息弥漫开来。\n"
)


def _make_chapter_outline(**overrides) -> ChapterOutline:
    defaults = {
        "chapter_number": 1,
        "title": "初入江湖",
        "goal": "主角离开家乡",
        "key_events": ["告别父母", "路遇强盗"],
        "involved_characters": ["张三"],
        "estimated_words": 3000,
        "mood": "蓄力",
    }
    defaults.update(overrides)
    return ChapterOutline(**defaults)


def _mock_llm_scenes(scene_count: int = 3, total_words: int = 3000) -> str:
    per_scene = total_words // scene_count
    scenes = []
    moods = ["蓄力", "小爽", "蓄力", "大爽", "过渡"]
    focuses = ["对话", "动作", "描写", "心理"]
    for i in range(scene_count):
        scenes.append({
            "scene_number": i + 1,
            "title": f"场景{i + 1}",
            "summary": f"第{i + 1}个场景",
            "characters_involved": ["张三"],
            "mood": moods[i % len(moods)],
            "tension_level": round(0.3 + i * 0.15, 2),
            "target_words": per_scene,
            "narrative_focus": focuses[i % len(focuses)],
            "foreshadowing_to_plant": None,
            "foreshadowing_to_collect": None,
        })
    return json.dumps({"scenes": scenes}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# QualityCheckTool: blacklist_overrides
# ---------------------------------------------------------------------------


class TestBlacklistOverrides:
    """Phase 0 架构重构：AI 味黑名单已废弃，overrides 现在永远无命中可过滤。

    保留这些测试作为 smoke test，确认 blacklist_overrides 参数传递不抛错；
    TODO(phase-1): StyleProfile 接管后用新的阈值机制重写这些测试。
    """

    def test_no_overrides_returns_empty_ai_flavor(self) -> None:
        """Stubbed blacklist → ai_flavor_issues always empty."""
        tool = QualityCheckTool()
        result = tool.rule_check(_AI_FLAVOR_TEXT)
        assert result.ai_flavor_issues == []

    def test_overrides_parameter_still_accepted(self) -> None:
        """blacklist_overrides 依然可以传入，不抛异常即可。"""
        tool = QualityCheckTool()
        result = tool.rule_check(
            _AI_FLAVOR_TEXT, blacklist_overrides={"内心翻涌": 0}
        )
        # Stubbed blacklist returns no hits, overrides become irrelevant.
        assert result.ai_flavor_issues == []

    def test_empty_overrides_same_as_none(self) -> None:
        """Empty dict should behave the same as no overrides."""
        tool = QualityCheckTool()
        result_none = tool.rule_check(_AI_FLAVOR_TEXT)
        result_empty = tool.rule_check(_AI_FLAVOR_TEXT, blacklist_overrides={})
        assert len(result_none.ai_flavor_issues) == len(result_empty.ai_flavor_issues)


# ---------------------------------------------------------------------------
# QualityReviewer: enable_rule_check
# ---------------------------------------------------------------------------


class TestEnableRuleCheck:
    """Test that enable_rule_check=False skips rule checks."""

    def test_rule_check_disabled_always_passes(self) -> None:
        """With enable_rule_check=False, AI-flavored text should pass rule check."""
        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(
            _AI_FLAVOR_TEXT,
            enable_rule_check=False,
        )
        assert report["rule_check"]["passed"] is True
        assert report["need_rewrite"] is False

    def test_rule_check_enabled_detects_issues(self) -> None:
        """Phase 0 架构重构：AI 味黑名单废弃；AI-flavored text 不再被 rule_check 判失败。

        TODO(phase-1): StyleProfile 接管后重写。
        """
        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(
            _AI_FLAVOR_TEXT,
            enable_rule_check=True,
        )
        # Rule check enabled but no AI flavor hits → passes.
        assert report["rule_check"]["ai_flavor_issues"] == []

    def test_rule_check_disabled_with_blacklist_overrides(self) -> None:
        """When rule check is disabled, blacklist_overrides are irrelevant."""
        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(
            _AI_FLAVOR_TEXT,
            enable_rule_check=False,
            blacklist_overrides={"内心翻涌": 0},
        )
        # Should still pass because rule check is disabled entirely
        assert report["rule_check"]["passed"] is True

    def test_blacklist_overrides_passed_to_rule_check(self) -> None:
        """When rule check is enabled, blacklist overrides are applied."""
        reviewer = QualityReviewer(None)
        # Allow all detected phrases with high thresholds
        overrides = {
            "内心翻涌": 10,
            "嘴角勾起一抹": 10,
            "空气仿佛凝固": 10,
            "然而他并不知道": 10,
            "命运的齿轮开始转动": 10,
            "一股令人窒息的气息": 10,
            "莫名的情绪": 10,
        }
        report = reviewer.review_chapter(
            _AI_FLAVOR_TEXT,
            enable_rule_check=True,
            blacklist_overrides=overrides,
        )
        # All AI flavor hits should be within threshold, so no AI flavor issues
        assert len(report["rule_check"]["ai_flavor_issues"]) == 0


# ---------------------------------------------------------------------------
# QualityReviewer: enable_llm_scoring (via node)
# ---------------------------------------------------------------------------


class TestEnableLLMScoring:
    """Test that quality.enable_llm_scoring config is respected."""

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_llm_scoring_disabled_forces_budget_mode(
        self, mock_create_llm: MagicMock
    ) -> None:
        """When enable_llm_scoring=False, budget_mode is True (LLM not called for scoring)."""
        mock_create_llm.return_value = _make_fake_llm()
        state: dict[str, Any] = {
            "current_chapter_text": _CLEAN_TEXT,
            "config": {
                "llm": {},
                "quality": {"enable_llm_scoring": False},
            },
            "current_chapter": 5,  # normally would trigger LLM scoring (5%5==0)
            "total_chapters": 25,
            "auto_approve_threshold": 6.0,
        }
        result = quality_reviewer_node(state)
        quality = result["current_chapter_quality"]
        # LLM scoring should be skipped -> empty scores
        assert quality["scores"] == {}
        assert quality["retention_scores"] == {}

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_llm_scoring_enabled_uses_budget_strategy(
        self, mock_create_llm: MagicMock
    ) -> None:
        """When enable_llm_scoring=True (default), normal budget strategy applies."""
        mock_create_llm.return_value = _make_fake_llm()
        state: dict[str, Any] = {
            "current_chapter_text": _CLEAN_TEXT,
            "config": {
                "llm": {},
                "quality": {"enable_llm_scoring": True},
            },
            "current_chapter": 5,  # 5%5==0, should trigger LLM scoring
            "total_chapters": 25,
            "auto_approve_threshold": 6.0,
        }
        result = quality_reviewer_node(state)
        quality = result["current_chapter_quality"]
        # LLM scoring should have run for chapter 5
        assert quality["scores"] != {}

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_llm_scoring_default_true(
        self, mock_create_llm: MagicMock
    ) -> None:
        """When quality config omits enable_llm_scoring, default is True."""
        mock_create_llm.return_value = _make_fake_llm()
        state: dict[str, Any] = {
            "current_chapter_text": _CLEAN_TEXT,
            "config": {"llm": {}, "quality": {}},
            "current_chapter": 10,  # 10%5==0 -> LLM scoring
            "total_chapters": 25,
            "auto_approve_threshold": 6.0,
        }
        result = quality_reviewer_node(state)
        quality = result["current_chapter_quality"]
        assert quality["scores"] != {}


# ---------------------------------------------------------------------------
# QualityReviewer Node: enable_rule_check + blacklist via config
# ---------------------------------------------------------------------------


class TestNodeRuleCheckConfig:
    """Test that quality_reviewer_node reads enable_rule_check and ai_flavor_blacklist from config."""

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_node_rule_check_disabled(self, mock_create_llm: MagicMock) -> None:
        """Node should skip rule check when config says so."""
        mock_create_llm.side_effect = RuntimeError("No LLM")
        state: dict[str, Any] = {
            "current_chapter_text": _AI_FLAVOR_TEXT,
            "config": {
                "llm": {},
                "quality": {"enable_rule_check": False},
            },
            "current_chapter": 1,
            "auto_approve_threshold": 6.0,
        }
        result = quality_reviewer_node(state)
        quality = result["current_chapter_quality"]
        # Rule check disabled -> passed=True even for AI-flavored text
        assert quality["rule_check"]["passed"] is True

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_node_blacklist_overrides_from_config(
        self, mock_create_llm: MagicMock
    ) -> None:
        """Node should pass ai_flavor_blacklist from config to rule_check."""
        mock_create_llm.side_effect = RuntimeError("No LLM")
        # Allow all detected phrases with high thresholds
        state: dict[str, Any] = {
            "current_chapter_text": _AI_FLAVOR_TEXT,
            "config": {
                "llm": {},
                "quality": {
                    "ai_flavor_blacklist": {
                        "内心翻涌": 10,
                        "嘴角勾起一抹": 10,
                        "空气仿佛凝固": 10,
                        "然而他并不知道": 10,
                        "命运的齿轮开始转动": 10,
                        "一股令人窒息的气息": 10,
                        "莫名的情绪": 10,
                    },
                },
            },
            "current_chapter": 1,
            "auto_approve_threshold": 6.0,
        }
        result = quality_reviewer_node(state)
        quality = result["current_chapter_quality"]
        # All AI flavor phrases should be within allowed limit -> 0 AI issues
        assert len(quality["rule_check"]["ai_flavor_issues"]) == 0
        # Should pass because no AI issues flagged
        assert quality["rule_check"]["passed"] is True


# ---------------------------------------------------------------------------
# PlotPlanner: scene_per_chapter cap
# ---------------------------------------------------------------------------


class TestScenePerChapterCap:
    """Test that generation.scene_per_chapter caps the scene count."""

    def test_cap_truncates_excess_scenes(self) -> None:
        """When LLM returns more scenes than max, truncate."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(5, 5000),
            model="mock",
            usage=None,
        )
        planner = PlotPlanner(mock_llm)
        result = planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(estimated_words=5000),
            volume_context={},
            characters=[],
            generation_config={"scene_per_chapter": 3},
        )
        assert len(result) == 3

    def test_default_cap_is_10(self) -> None:
        """Without config, default cap is 10 (effectively no cap for normal use)."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(4),
            model="mock",
            usage=None,
        )
        planner = PlotPlanner(mock_llm)
        result = planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[],
            generation_config={},
        )
        # 4 < 10, no truncation
        assert len(result) == 4

    def test_cap_preserves_first_n_scenes(self) -> None:
        """Truncation keeps the first N scenes."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(5, 5000),
            model="mock",
            usage=None,
        )
        planner = PlotPlanner(mock_llm)
        result = planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(estimated_words=5000),
            volume_context={},
            characters=[],
            generation_config={"scene_per_chapter": 2},
        )
        assert len(result) == 2
        assert result[0]["scene_number"] == 1
        assert result[1]["scene_number"] == 2


# ---------------------------------------------------------------------------
# PlotPlanner: words_per_scene prompt injection
# ---------------------------------------------------------------------------


class TestWordsPerSceneConfig:
    """Test that generation.words_per_scene is injected into the LLM prompt."""

    def test_words_per_scene_in_prompt(self) -> None:
        """When config has words_per_scene, the prompt includes the range."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(3),
            model="mock",
            usage=None,
        )
        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[],
            generation_config={"words_per_scene": [500, 1000]},
        )
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "场景字数范围：500-1000字" in user_msg

    def test_no_words_per_scene_no_extra_prompt(self) -> None:
        """Without words_per_scene config, no extra prompt section."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(3),
            model="mock",
            usage=None,
        )
        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[],
            generation_config={},
        )
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "场景字数范围" not in user_msg


# ---------------------------------------------------------------------------
# PlotPlanner: words_per_chapter clamp
# ---------------------------------------------------------------------------


class TestWordsPerChapterClamp:
    """Test that generation.words_per_chapter clamps the estimated_words."""

    def test_clamp_raises_low_estimate(self) -> None:
        """When estimated_words < min, clamp to min."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(3),
            model="mock",
            usage=None,
        )
        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(estimated_words=500),
            volume_context={},
            characters=[],
            generation_config={"words_per_chapter": [2000, 3000]},
        )
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        # The prompt should show 2000 (clamped), not 500
        assert "2000" in user_msg
        assert "500" not in user_msg.split("场景")[0]  # 500 should not appear as estimated words

    def test_clamp_lowers_high_estimate(self) -> None:
        """When estimated_words > max, clamp to max."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(3),
            model="mock",
            usage=None,
        )
        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(estimated_words=10000),
            volume_context={},
            characters=[],
            generation_config={"words_per_chapter": [2000, 3000]},
        )
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        # The prompt should show 3000 (clamped), not 10000
        assert "3000" in user_msg

    def test_no_clamp_when_within_range(self) -> None:
        """When estimated_words is within range, no clamping."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(3),
            model="mock",
            usage=None,
        )
        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(estimated_words=2500),
            volume_context={},
            characters=[],
            generation_config={"words_per_chapter": [2000, 3000]},
        )
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "2500" in user_msg

    def test_no_config_uses_original_estimate(self) -> None:
        """Without words_per_chapter config, original estimated_words is used."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(3),
            model="mock",
            usage=None,
        )
        planner = PlotPlanner(mock_llm)
        planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(estimated_words=8000),
            volume_context={},
            characters=[],
            generation_config={},
        )
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "8000" in user_msg


# ---------------------------------------------------------------------------
# PlotPlanner Node: config propagation
# ---------------------------------------------------------------------------


class TestPlotPlannerNodeConfig:
    """Test that plot_planner_node passes generation config from state."""

    def test_node_passes_generation_config(self) -> None:
        """Node should extract generation config and pass to decompose_chapter."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(5, 5000),
            model="mock",
            usage=None,
        )
        state = {
            "config": {
                "generation": {
                    "scene_per_chapter": 2,
                    "words_per_scene": [400, 800],
                    "words_per_chapter": [2000, 3000],
                },
            },
            "current_chapter_outline": _make_chapter_outline(
                estimated_words=5000
            ).model_dump(),
            "characters": [],
        }
        with patch(
            "src.novel.agents.plot_planner.create_llm_client",
            return_value=mock_llm,
        ):
            result = plot_planner_node(state)

        # Should be capped to 2 scenes
        assert len(result["current_scenes"]) == 2
        # The prompt should contain words_per_scene guidance
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "场景字数范围：400-800字" in user_msg
        # estimated_words should be clamped to 3000
        assert "3000" in user_msg

    def test_node_no_generation_config(self) -> None:
        """Without generation config in state, defaults apply."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(3),
            model="mock",
            usage=None,
        )
        state = {
            "config": {},
            "current_chapter_outline": _make_chapter_outline().model_dump(),
            "characters": [],
        }
        with patch(
            "src.novel.agents.plot_planner.create_llm_client",
            return_value=mock_llm,
        ):
            result = plot_planner_node(state)

        assert len(result["current_scenes"]) == 3
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        # No words_per_scene section
        assert "场景字数范围" not in user_msg


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    """Ensure existing callers without new params still work."""

    def test_review_chapter_no_new_params(self) -> None:
        """review_chapter works without enable_rule_check or blacklist_overrides."""
        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(_CLEAN_TEXT)
        assert report["rule_check"]["passed"] is True

    def test_rule_check_no_blacklist_overrides(self) -> None:
        """rule_check works without blacklist_overrides."""
        tool = QualityCheckTool()
        result = tool.rule_check(_CLEAN_TEXT)
        assert result.passed is True

    def test_decompose_chapter_no_generation_config(self) -> None:
        """decompose_chapter works without generation_config."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = LLMResponse(
            content=_mock_llm_scenes(3),
            model="mock",
            usage=None,
        )
        planner = PlotPlanner(mock_llm)
        result = planner.decompose_chapter(
            chapter_outline=_make_chapter_outline(),
            volume_context={},
            characters=[],
        )
        assert len(result) == 3
