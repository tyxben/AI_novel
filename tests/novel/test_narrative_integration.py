"""Narrative Control Integration Tests

Tests the integration of narrative control services (ObligationTracker,
BriefValidator, DebtExtractor) into existing agents (Writer, QualityReviewer,
NovelDirector).

Covers:
- Writer.generate_scene with debt_summary injection
- Writer.generate_chapter with debt_summary passed to first scene only
- QualityReviewer.review_chapter with brief validation and debt extraction
- QualityReviewer.review_chapter without narrative control services
- QualityReviewer creates debts for unfulfilled brief items
- NovelDirector.generate_story_arcs basic arc generation
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.novel_director import NovelDirector
from src.novel.agents.quality_reviewer import QualityReviewer, quality_reviewer_node
from src.novel.agents.writer import Writer
from src.novel.models.character import Appearance, CharacterProfile, Personality
from src.novel.models.novel import ChapterOutline, VolumeOutline
from src.novel.models.world import WorldSetting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm(text: str = "他拔出长剑，目光如炬。") -> MagicMock:
    """Create a mock LLM client returning fixed text."""
    client = MagicMock()
    client.chat.return_value = LLMResponse(content=text, model="mock-model")
    return client


def _make_llm_sequential(texts: list[str]) -> MagicMock:
    """Create a mock LLM client returning different texts in sequence."""
    client = MagicMock()
    responses = [LLMResponse(content=t, model="mock-model") for t in texts]
    client.chat.side_effect = responses
    return client


def _make_chapter_outline(chapter_number: int = 1) -> ChapterOutline:
    return ChapterOutline(
        chapter_number=chapter_number,
        title="风云突变",
        goal="主角与敌人首次交锋",
        key_events=["遭遇敌人", "激烈战斗"],
        involved_characters=["char_1"],
        estimated_words=3000,
        mood="蓄力",
    )


def _make_character() -> CharacterProfile:
    return CharacterProfile(
        name="林凡",
        gender="男",
        age=22,
        occupation="剑客",
        appearance=Appearance(
            height="180cm",
            build="匀称",
            hair="黑色短发",
            eyes="深邃黑眸",
            clothing_style="白衣",
        ),
        personality=Personality(
            traits=["冷静", "果敢", "隐忍"],
            core_belief="实力为尊",
            motivation="为师报仇",
            flaw="过于自负",
            speech_style="简洁有力",
        ),
    )


def _make_world() -> WorldSetting:
    return WorldSetting(era="上古时代", location="九天大陆")


def _make_scene_plan(scene_number: int = 1) -> dict:
    return {
        "scene_number": scene_number,
        "location": "山谷",
        "time": "清晨",
        "characters_involved": ["林凡"],
        "goal": "发现敌人踪迹",
        "mood": "蓄力",
        "target_words": 800,
    }


# Clean text that passes rule checks
_CLEAN_TEXT = (
    "清晨的阳光透过窗帘洒进房间。\n"
    "李明揉了揉眼睛，从床上坐起来。\n"
    "今天是他入职新公司的第一天，他有些紧张。\n"
    "洗漱完毕，他穿上那套新买的西装，对着镜子整了整领带。\n"
    "出门时，楼下的早餐铺飘来阵阵包子的香气。\n"
    "他买了两个肉包子和一杯豆浆，边走边吃。\n"
    "地铁站里人头攒动，他挤上了早高峰的列车。\n"
)


# ---------------------------------------------------------------------------
# Writer + debt_summary Tests
# ---------------------------------------------------------------------------


class TestWriterWithDebtSummary:
    """Test debt_summary injection into Writer."""

    def test_writer_generate_scene_with_debt_summary(self) -> None:
        """When debt_summary is provided, it should appear in the LLM messages."""
        debt_text = "## 待解决的叙事债务\n- 第3章遗留：主角答应师妹探索密林"
        llm = _make_llm("林凡拔出长剑，目光如炬。")
        writer = Writer(llm)

        scene = writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
            debt_summary=debt_text,
        )

        # Verify the LLM was called
        assert llm.chat.call_count == 1
        call_args = llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1].get("messages", [])
        user_msg = messages[1]["content"]

        # Verify debt_summary appears in user prompt
        assert "前文未了结的叙事义务" in user_msg
        assert "主角答应师妹探索密林" in user_msg

        # Verify scene was generated
        assert scene.text == "林凡拔出长剑，目光如炬。"

    def test_writer_generate_scene_without_debt_summary(self) -> None:
        """When debt_summary is empty, no debt section should appear."""
        llm = _make_llm("林凡拔出长剑。")
        writer = Writer(llm)

        scene = writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
            debt_summary="",
        )

        call_args = llm.chat.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1].get("messages", [])
        user_msg = messages[1]["content"]

        # No debt section should be in the prompt
        assert "前文未了结的叙事义务" not in user_msg
        assert scene.text == "林凡拔出长剑。"

    def test_writer_generate_chapter_debt_only_first_scene(self) -> None:
        """Debt summary should only be injected into the first scene."""
        debt_text = "## 待解决的叙事债务\n- 第3章遗留：报仇承诺"

        # Need multiple LLM responses for multiple scenes
        llm = _make_llm_sequential(["场景一正文。", "场景二正文。", "场景三正文。"])
        writer = Writer(llm)

        chapter = writer.generate_chapter(
            chapter_outline=_make_chapter_outline(),
            scene_plans=[_make_scene_plan(i) for i in range(1, 4)],
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
            debt_summary=debt_text,
        )

        assert len(chapter.scenes) == 3

        # Check first scene's call had debt_summary
        first_call = llm.chat.call_args_list[0]
        first_messages = first_call[0][0] if first_call[0] else first_call[1].get("messages", [])
        first_user_msg = first_messages[1]["content"]
        assert "前文未了结的叙事义务" in first_user_msg

        # Check second and third scene calls did NOT have debt_summary
        for i in [1, 2]:
            nth_call = llm.chat.call_args_list[i]
            nth_messages = nth_call[0][0] if nth_call[0] else nth_call[1].get("messages", [])
            nth_user_msg = nth_messages[1]["content"]
            assert "前文未了结的叙事义务" not in nth_user_msg


# ---------------------------------------------------------------------------
# QualityReviewer + narrative control Tests
# ---------------------------------------------------------------------------


class TestQualityReviewerWithNarrativeControl:
    """Test QualityReviewer with brief validation and debt extraction."""

    def test_review_with_brief_validation(self) -> None:
        """When brief_validator is provided, it should be called and result stored."""
        mock_brief_validator = MagicMock()
        mock_brief_validator.validate_chapter.return_value = {
            "chapter_number": 5,
            "overall_pass": True,
            "pass_rate": 1.0,
            "item_results": [],
            "unfulfilled_items": [],
            "suggested_debts": [],
        }

        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(
            chapter_text=_CLEAN_TEXT,
            budget_mode=True,
            chapter_brief={"main_conflict": "主角首战"},
            brief_validator=mock_brief_validator,
            chapter_number=5,
        )

        # BriefValidator was called
        mock_brief_validator.validate_chapter.assert_called_once_with(
            chapter_text=_CLEAN_TEXT,
            chapter_brief={"main_conflict": "主角首战"},
            chapter_number=5,
        )

        # Result stored in report
        assert "brief_fulfillment" in report
        assert report["brief_fulfillment"]["overall_pass"] is True

    def test_review_without_services(self) -> None:
        """Without narrative services, review works normally (backwards compatible)."""
        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(
            chapter_text=_CLEAN_TEXT,
            budget_mode=True,
        )

        # Standard report fields present
        assert "rule_check" in report
        assert report["scores"] == {}
        # Narrative fields not present
        assert "brief_fulfillment" not in report
        assert "debts_extracted" not in report

    def test_review_creates_debts_for_unfulfilled_brief(self) -> None:
        """When brief validation fails, debts should be created via obligation_tracker."""
        mock_brief_validator = MagicMock()
        mock_brief_validator.validate_chapter.return_value = {
            "chapter_number": 5,
            "overall_pass": False,
            "pass_rate": 0.5,
            "item_results": [],
            "unfulfilled_items": ["main_conflict"],
            "suggested_debts": [
                {
                    "type": "must_pay_next",
                    "description": "第5章未完成: main_conflict — 主角首战",
                    "urgency_level": "high",
                },
            ],
        }

        mock_tracker = MagicMock()

        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(
            chapter_text=_CLEAN_TEXT,
            budget_mode=True,
            chapter_brief={"main_conflict": "主角首战"},
            brief_validator=mock_brief_validator,
            obligation_tracker=mock_tracker,
            chapter_number=5,
        )

        # Obligation tracker should have been called
        assert mock_tracker.add_debt.call_count == 1
        debt_call = mock_tracker.add_debt.call_args
        assert debt_call[1]["source_chapter"] == 5
        assert debt_call[1]["debt_type"] == "must_pay_next"
        assert "main_conflict" in debt_call[1]["description"]

    def test_review_with_debt_extractor(self) -> None:
        """When debt_extractor is provided, debts should be extracted and added."""
        mock_extractor = MagicMock()
        mock_extractor.extract_from_chapter.return_value = {
            "debts": [
                {
                    "debt_id": "debt_5_0_abc123",
                    "source_chapter": 5,
                    "type": "pay_within_3",
                    "description": "角色承诺: 一定要报仇",
                    "urgency_level": "normal",
                },
                {
                    "debt_id": "debt_5_1_def456",
                    "source_chapter": 5,
                    "type": "must_pay_next",
                    "description": "待完成动作: 赶往北方",
                    "urgency_level": "high",
                },
            ],
            "method": "rule_based",
            "confidence": 0.6,
        }

        mock_tracker = MagicMock()

        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(
            chapter_text=_CLEAN_TEXT,
            budget_mode=True,
            debt_extractor=mock_extractor,
            obligation_tracker=mock_tracker,
            chapter_number=5,
        )

        # Debt extractor was called
        mock_extractor.extract_from_chapter.assert_called_once_with(
            chapter_text=_CLEAN_TEXT,
            chapter_number=5,
        )

        # Debts count stored
        assert report["debts_extracted"] == 2

        # Both debts added to tracker
        assert mock_tracker.add_debt.call_count == 2

    def test_review_debt_extractor_without_tracker(self) -> None:
        """Debt extractor works without obligation tracker (just counts)."""
        mock_extractor = MagicMock()
        mock_extractor.extract_from_chapter.return_value = {
            "debts": [
                {
                    "debt_id": "debt_5_0_abc123",
                    "source_chapter": 5,
                    "type": "pay_within_3",
                    "description": "角色承诺: 一定要报仇",
                    "urgency_level": "normal",
                },
            ],
            "method": "rule_based",
            "confidence": 0.6,
        }

        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(
            chapter_text=_CLEAN_TEXT,
            budget_mode=True,
            debt_extractor=mock_extractor,
            chapter_number=5,
        )

        assert report["debts_extracted"] == 1

    def test_review_brief_validator_error_handled(self) -> None:
        """Brief validation errors should be caught and logged, not crash."""
        mock_brief_validator = MagicMock()
        mock_brief_validator.validate_chapter.side_effect = RuntimeError("LLM 故障")

        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(
            chapter_text=_CLEAN_TEXT,
            budget_mode=True,
            chapter_brief={"main_conflict": "主角首战"},
            brief_validator=mock_brief_validator,
            chapter_number=5,
        )

        # Should not crash, brief_fulfillment should not be in report
        assert "brief_fulfillment" not in report

    def test_review_debt_extractor_error_handled(self) -> None:
        """Debt extraction errors should be caught and logged, not crash."""
        mock_extractor = MagicMock()
        mock_extractor.extract_from_chapter.side_effect = RuntimeError("提取失败")

        reviewer = QualityReviewer(None)
        report = reviewer.review_chapter(
            chapter_text=_CLEAN_TEXT,
            budget_mode=True,
            debt_extractor=mock_extractor,
            chapter_number=5,
        )

        # Should not crash, debts_extracted should not be in report
        assert "debts_extracted" not in report


# ---------------------------------------------------------------------------
# QualityReviewer node + narrative control state Tests
# ---------------------------------------------------------------------------


class TestQualityReviewerNodeWithNarrativeControl:
    """Test quality_reviewer_node extracts services from state."""

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_node_passes_services_from_state(self, mock_create_llm: MagicMock) -> None:
        """Node should extract narrative services from state and pass to review."""
        mock_create_llm.side_effect = RuntimeError("No LLM")

        mock_tracker = MagicMock()
        mock_validator = MagicMock()
        mock_validator.validate_chapter.return_value = {
            "chapter_number": 3,
            "overall_pass": True,
            "pass_rate": 1.0,
            "item_results": [],
            "unfulfilled_items": [],
            "suggested_debts": [],
        }
        mock_extractor = MagicMock()
        mock_extractor.extract_from_chapter.return_value = {
            "debts": [],
            "method": "rule_based",
            "confidence": 0.6,
        }

        state = {
            "current_chapter_text": _CLEAN_TEXT,
            "config": {"llm": {}},
            "current_chapter": 3,
            "total_chapters": 10,
            "auto_approve_threshold": 6.0,
            "obligation_tracker": mock_tracker,
            "brief_validator": mock_validator,
            "debt_extractor": mock_extractor,
            "current_chapter_brief": {"main_conflict": "发现线索"},
        }

        result = quality_reviewer_node(state)
        assert "quality_reviewer" in result["completed_nodes"]

        # Brief validator was called
        mock_validator.validate_chapter.assert_called_once()
        # Debt extractor was called
        mock_extractor.extract_from_chapter.assert_called_once()

    @patch("src.novel.agents.quality_reviewer.create_llm_client")
    def test_node_works_without_services(self, mock_create_llm: MagicMock) -> None:
        """Node should work normally when no narrative services in state."""
        mock_create_llm.side_effect = RuntimeError("No LLM")

        state = {
            "current_chapter_text": _CLEAN_TEXT,
            "config": {"llm": {}},
            "current_chapter": 1,
            "auto_approve_threshold": 6.0,
        }

        result = quality_reviewer_node(state)
        assert "quality_reviewer" in result["completed_nodes"]
        quality = result["current_chapter_quality"]
        assert "rule_check" in quality


# ---------------------------------------------------------------------------
# NovelDirector arc generation Tests
# ---------------------------------------------------------------------------


class TestNovelDirectorArcGeneration:
    """Test NovelDirector.generate_story_arcs."""

    def test_generate_arcs_basic(self) -> None:
        """Generate arcs for a volume with 10 chapters."""
        arc_json = json.dumps({
            "name": "初入江湖",
            "hook": "主角被逐出师门",
            "closure_method": "获得第一个盟友",
            "residual_question": "师门灭亡的真相是什么？",
        }, ensure_ascii=False)
        llm = _make_llm(arc_json)
        director = NovelDirector(llm)

        volume_outline = VolumeOutline(
            volume_number=1,
            title="初出茅庐",
            core_conflict="主角被追杀",
            resolution="击败第一个敌人",
            chapters=list(range(1, 11)),
        )
        chapter_outlines = [
            _make_chapter_outline(i) for i in range(1, 11)
        ]

        arcs = director.generate_story_arcs(volume_outline, chapter_outlines, "玄幻")

        # Should have 2 arcs for 10 chapters (ceil(10/5) = 2)
        assert len(arcs) == 2

        # All chapters assigned
        all_chapters = []
        for arc in arcs:
            all_chapters.extend(arc["chapters"])
        assert sorted(all_chapters) == list(range(1, 11))

        # Each arc has required fields
        for arc in arcs:
            assert "arc_id" in arc
            assert "name" in arc
            assert "hook" in arc
            assert "escalation_point" in arc
            assert "turning_point" in arc
            assert "closure_method" in arc
            assert "residual_question" in arc
            assert arc["volume_id"] == 1
            assert 3 <= len(arc["chapters"]) <= 7

    def test_generate_arcs_small_volume(self) -> None:
        """Volume with 5 chapters should produce 1 arc."""
        arc_json = json.dumps({
            "name": "序幕",
            "hook": "开始",
            "closure_method": "结束",
            "residual_question": "然后呢？",
        }, ensure_ascii=False)
        llm = _make_llm(arc_json)
        director = NovelDirector(llm)

        volume_outline = VolumeOutline(
            volume_number=1,
            title="序",
            core_conflict="冲突",
            resolution="解决",
            chapters=[1, 2, 3, 4, 5],
        )
        chapter_outlines = [_make_chapter_outline(i) for i in range(1, 6)]

        arcs = director.generate_story_arcs(volume_outline, chapter_outlines, "武侠")

        assert len(arcs) == 1
        assert arcs[0]["chapters"] == [1, 2, 3, 4, 5]

    def test_generate_arcs_minimal_volume(self) -> None:
        """Volume with 3 chapters (minimum for an arc) should return 1 arc."""
        arc_json = json.dumps({
            "name": "序章",
            "hook": "钩子",
            "closure_method": "收束",
            "residual_question": "悬念",
        }, ensure_ascii=False)
        llm = _make_llm(arc_json)
        director = NovelDirector(llm)

        volume_outline = VolumeOutline(
            volume_number=1,
            title="短卷",
            core_conflict="小冲突",
            resolution="解决",
            chapters=[1, 2, 3],
        )
        chapter_outlines = [_make_chapter_outline(i) for i in range(1, 4)]

        arcs = director.generate_story_arcs(volume_outline, chapter_outlines, "玄幻")
        assert len(arcs) == 1
        assert arcs[0]["chapters"] == [1, 2, 3]

    def test_generate_arcs_llm_failure_fallback(self) -> None:
        """LLM failure should produce placeholder arcs."""
        llm = MagicMock()
        llm.chat.side_effect = RuntimeError("LLM 不可用")
        director = NovelDirector(llm)

        volume_outline = VolumeOutline(
            volume_number=1,
            title="卷一",
            core_conflict="矛盾",
            resolution="解决",
            chapters=list(range(1, 8)),
        )
        chapter_outlines = [_make_chapter_outline(i) for i in range(1, 8)]

        arcs = director.generate_story_arcs(volume_outline, chapter_outlines, "玄幻")

        # Should still return arcs with placeholder data
        assert len(arcs) >= 1
        for arc in arcs:
            assert "arc_id" in arc
            assert "name" in arc
            assert len(arc["chapters"]) >= 3

    def test_generate_arcs_arc_id_format(self) -> None:
        """Arc IDs should follow the format arc_{volume_id}_{arc_number}."""
        arc_json = json.dumps({
            "name": "测试弧线",
            "hook": "钩子",
            "closure_method": "收束",
            "residual_question": "悬念",
        }, ensure_ascii=False)
        llm = _make_llm(arc_json)
        director = NovelDirector(llm)

        volume_outline = VolumeOutline(
            volume_number=2,
            title="卷二",
            core_conflict="矛盾",
            resolution="解决",
            chapters=list(range(31, 46)),
        )
        chapter_outlines = [_make_chapter_outline(i) for i in range(31, 46)]

        arcs = director.generate_story_arcs(volume_outline, chapter_outlines, "都市")

        for i, arc in enumerate(arcs):
            assert arc["arc_id"] == f"arc_2_{i + 1}"
