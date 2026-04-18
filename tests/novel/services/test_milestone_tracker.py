"""Tests for milestone tracking — Intervention A: Volume Progress Budget.

Covers:
- MilestoneTracker: keyword completion, LLM completion, overdue detection,
  volume progress computation.
- ContinuityService: volume_progress injection + formatting.
- PlotPlanner: volume progress constraint section generation.
- VolumeSettlement: milestone settlement at volume boundaries.
- Round-trip: milestones survive checkpoint save/load.
- Migration: novels without milestones load without errors.
"""
from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from src.novel.models.narrative_control import (
    NarrativeMilestone,
    VolumeProgressReport,
)
from src.novel.services.milestone_tracker import MilestoneTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_novel_data(
    milestones: list[dict] | None = None,
    volume_number: int = 1,
    start_chapter: int = 1,
    end_chapter: int = 30,
    extra_volumes: list[dict] | None = None,
) -> dict:
    """Build a minimal novel_data dict for testing."""
    vol = {
        "volume_number": volume_number,
        "title": "测试卷",
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
        "theme": "测试主题",
        "climax": "测试高潮",
        "end_hook": "测试钩子",
    }
    if milestones is not None:
        vol["narrative_milestones"] = milestones
    volumes = [vol]
    if extra_volumes:
        volumes.extend(extra_volumes)
    return {
        "novel_id": "test_novel",
        "outline": {
            "volumes": volumes,
            "chapters": [{"chapter_number": i} for i in range(start_chapter, end_chapter + 1)],
        },
    }


def _make_milestone(
    milestone_id: str = "vol1_m1",
    description: str = "测试里程碑描述",
    target_range: list[int] | None = None,
    verification_type: str = "auto_keyword",
    criteria: list[str] | str | None = None,
    priority: str = "normal",
    status: str = "pending",
    completed_at: int | None = None,
) -> dict:
    """Build a single milestone dict."""
    return {
        "milestone_id": milestone_id,
        "description": description,
        "target_chapter_range": target_range or [5, 15],
        "verification_type": verification_type,
        "verification_criteria": criteria or ["关键词A", "关键词B"],
        "priority": priority,
        "status": status,
        "completed_at_chapter": completed_at,
    }


# ---------------------------------------------------------------------------
# NarrativeMilestone model tests
# ---------------------------------------------------------------------------

class TestNarrativeMilestoneModel:
    """Test the Pydantic model itself."""

    def test_valid_creation(self):
        m = NarrativeMilestone(
            milestone_id="vol1_m1",
            description="主角招募第一批追随者",
            target_chapter_range=[3, 8],
            verification_criteria=["招募", "追随者"],
            priority="critical",
        )
        assert m.milestone_id == "vol1_m1"
        assert m.status == "pending"
        assert m.completed_at_chapter is None

    def test_serialization_roundtrip(self):
        m = NarrativeMilestone(
            milestone_id="vol2_m3",
            description="击败筑基期对手",
            target_chapter_range=[30, 40],
            verification_criteria=["筑基期", "击败"],
            priority="high",
            status="completed",
            completed_at_chapter=35,
        )
        data = m.model_dump()
        m2 = NarrativeMilestone(**data)
        assert m2.milestone_id == m.milestone_id
        assert m2.status == "completed"
        assert m2.completed_at_chapter == 35

    def test_invalid_priority_rejected(self):
        with pytest.raises(Exception):
            NarrativeMilestone(
                milestone_id="bad",
                description="invalid priority test",
                target_chapter_range=[1, 5],
                verification_criteria=["x"],
                priority="invalid_value",
            )

    def test_description_too_short(self):
        with pytest.raises(Exception):
            NarrativeMilestone(
                milestone_id="bad",
                description="ab",  # min_length=5
                target_chapter_range=[1, 5],
                verification_criteria=["x"],
            )


# ---------------------------------------------------------------------------
# VolumeProgressReport model tests
# ---------------------------------------------------------------------------

class TestVolumeProgressReport:
    def test_valid_creation(self):
        r = VolumeProgressReport(
            volume_number=1,
            milestones_total=5,
            milestones_completed=3,
            milestones_overdue=1,
            completion_rate=0.6,
        )
        assert r.milestones_abandoned == 0
        assert r.milestones_inherited_to_next == 0
        assert r.settlement_timestamp  # auto-generated


# ---------------------------------------------------------------------------
# MilestoneTracker: keyword completion
# ---------------------------------------------------------------------------

class TestKeywordCompletion:
    def test_all_keywords_present_completes(self):
        ms = [_make_milestone(criteria=["青云山门", "攻占"])]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        completed = tracker.check_milestone_completion(
            chapter_num=10,
            chapter_text="主角率军攻占了青云山门，正式接管。",
        )
        assert completed == ["vol1_m1"]
        # In-place mutation should mark the milestone as completed
        assert ms[0]["status"] == "completed"
        assert ms[0]["completed_at_chapter"] == 10

    def test_partial_keywords_not_completed(self):
        ms = [_make_milestone(criteria=["青云山门", "攻占"])]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        completed = tracker.check_milestone_completion(
            chapter_num=10,
            chapter_text="主角前往青云山门探查地形。",
        )
        assert completed == []
        assert ms[0]["status"] == "pending"

    def test_no_keywords_not_completed(self):
        ms = [_make_milestone(criteria=["三座山峰", "扩张"])]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        completed = tracker.check_milestone_completion(
            chapter_num=10,
            chapter_text="主角在训练场练习剑法。",
        )
        assert completed == []

    def test_already_completed_milestone_skipped(self):
        ms = [_make_milestone(status="completed", completed_at=5)]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        completed = tracker.check_milestone_completion(
            chapter_num=10,
            chapter_text="关键词A和关键词B都出现了。",
        )
        assert completed == []

    def test_chapter_before_range_not_checked(self):
        ms = [_make_milestone(target_range=[10, 20], criteria=["关键词"])]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        completed = tracker.check_milestone_completion(
            chapter_num=5,
            chapter_text="关键词出现了。",
        )
        assert completed == []

    def test_single_string_criteria(self):
        ms = [_make_milestone(criteria="招募追随者")]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        completed = tracker.check_milestone_completion(
            chapter_num=10,
            chapter_text="成功招募追随者，队伍壮大。",
        )
        assert completed == ["vol1_m1"]


# ---------------------------------------------------------------------------
# MilestoneTracker: LLM completion check
# ---------------------------------------------------------------------------

class TestLLMCompletion:
    def test_llm_review_completes_when_true(self):
        ms = [_make_milestone(
            verification_type="llm_review",
            criteria="判断是否建立了分封制度",
        )]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)

        mock_llm = MagicMock()
        mock_llm.chat.return_value = MagicMock(
            content='{"completed": true, "reason": "分封制度已建立"}'
        )

        completed = tracker.check_milestone_completion(
            chapter_num=10,
            chapter_text="全文...",
            chapter_summary="主角建立了分封制度",
            llm_client=mock_llm,
        )
        assert completed == ["vol1_m1"]

    def test_llm_review_not_completed_when_false(self):
        ms = [_make_milestone(
            verification_type="llm_review",
            criteria="判断是否建立了分封制度",
        )]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)

        mock_llm = MagicMock()
        mock_llm.chat.return_value = MagicMock(
            content='{"completed": false, "reason": "尚未建立"}'
        )

        completed = tracker.check_milestone_completion(
            chapter_num=10,
            chapter_text="全文...",
            llm_client=mock_llm,
        )
        assert completed == []

    def test_llm_review_skipped_without_client(self):
        ms = [_make_milestone(verification_type="llm_review", criteria="prompt")]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        completed = tracker.check_milestone_completion(
            chapter_num=10,
            chapter_text="全文...",
            llm_client=None,
        )
        assert completed == []

    def test_llm_exception_handled_gracefully(self):
        ms = [_make_milestone(verification_type="llm_review", criteria="prompt")]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("LLM unavailable")

        completed = tracker.check_milestone_completion(
            chapter_num=10,
            chapter_text="全文...",
            llm_client=mock_llm,
        )
        assert completed == []


# ---------------------------------------------------------------------------
# MilestoneTracker: overdue detection
# ---------------------------------------------------------------------------

class TestOverdueDetection:
    def test_pending_past_range_marked_overdue(self):
        ms = [_make_milestone(target_range=[5, 10])]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        overdue = tracker.mark_overdue_milestones(current_chapter=11)
        assert overdue == ["vol1_m1"]
        assert ms[0]["status"] == "overdue"

    def test_pending_within_range_not_overdue(self):
        ms = [_make_milestone(target_range=[5, 15])]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        overdue = tracker.mark_overdue_milestones(current_chapter=10)
        assert overdue == []
        assert ms[0]["status"] == "pending"

    def test_completed_not_marked_overdue(self):
        ms = [_make_milestone(target_range=[5, 10], status="completed", completed_at=8)]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        overdue = tracker.mark_overdue_milestones(current_chapter=15)
        assert overdue == []


# ---------------------------------------------------------------------------
# MilestoneTracker: progress computation
# ---------------------------------------------------------------------------

class TestVolumeProgress:
    def test_on_track(self):
        """< 50% chapters used, >= 50% milestones done => on_track."""
        ms = [
            _make_milestone("m1", status="completed", completed_at=3),
            _make_milestone("m2", status="pending"),
        ]
        # start=1, end=30, chapter=10 => 9/30 consumed (30%)
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        p = tracker.compute_volume_progress(chapter_num=10)
        assert p["progress_health"] == "on_track"
        assert p["chapters_consumed"] == 9
        assert p["chapters_remaining"] == 21

    def test_behind_schedule(self):
        """> 50% chapters used, < 50% milestones done, no overdue => behind_schedule."""
        ms = [
            _make_milestone("m1", status="pending", target_range=[1, 30]),
            _make_milestone("m2", status="pending", target_range=[1, 30]),
            _make_milestone("m3", status="pending", target_range=[1, 30]),
            _make_milestone("m4", status="completed", completed_at=5, target_range=[1, 10]),
        ]
        # start=1, end=30, chapter=20 => 19/30 consumed (63%), 1/4 done (25%)
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        p = tracker.compute_volume_progress(chapter_num=20)
        assert p["progress_health"] == "behind_schedule"

    def test_critical_with_overdue(self):
        """Any overdue milestone => critical."""
        ms = [
            _make_milestone("m1", status="overdue", target_range=[5, 10]),
            _make_milestone("m2", status="completed", completed_at=3, target_range=[1, 5]),
        ]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        p = tracker.compute_volume_progress(chapter_num=15)
        assert p["progress_health"] == "critical"
        assert len(p["milestones_overdue"]) == 1

    def test_no_milestones_is_on_track(self):
        nd = _make_novel_data(milestones=[])
        tracker = MilestoneTracker(nd)
        p = tracker.compute_volume_progress(chapter_num=10)
        assert p["progress_health"] == "on_track"

    def test_chapter_outside_any_volume(self):
        nd = _make_novel_data(milestones=[])
        tracker = MilestoneTracker(nd)
        p = tracker.compute_volume_progress(chapter_num=999)
        assert p == {}


# ---------------------------------------------------------------------------
# MilestoneTracker: get_milestones_for_chapter
# ---------------------------------------------------------------------------

class TestGetMilestonesForChapter:
    def test_returns_pending_in_range(self):
        ms = [
            _make_milestone("m1", target_range=[5, 15]),
            _make_milestone("m2", target_range=[20, 25]),
        ]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        result = tracker.get_milestones_for_chapter(10)
        assert len(result) == 1
        assert result[0].milestone_id == "m1"

    def test_empty_when_all_completed(self):
        ms = [
            _make_milestone("m1", status="completed", completed_at=8, target_range=[5, 15]),
        ]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        result = tracker.get_milestones_for_chapter(10)
        assert result == []

    def test_empty_when_no_milestones(self):
        nd = _make_novel_data(milestones=[])
        tracker = MilestoneTracker(nd)
        result = tracker.get_milestones_for_chapter(10)
        assert result == []


# ---------------------------------------------------------------------------
# ContinuityService: volume_progress injection
# ---------------------------------------------------------------------------

class TestContinuityServiceVolumeProgress:
    def test_brief_contains_volume_progress(self):
        from src.novel.services.continuity_service import ContinuityService

        ms = [
            _make_milestone("m1", status="completed", completed_at=5, target_range=[1, 10],
                            description="激活系统"),
            _make_milestone("m2", status="overdue", target_range=[5, 10],
                            description="攻占青云山门"),
        ]
        nd = _make_novel_data(milestones=ms)
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=12, novel_data=nd)
        vp = brief.get("volume_progress", {})
        assert vp
        assert vp["progress_health"] == "critical"
        assert "激活系统" in vp["milestones_completed"]
        assert "攻占青云山门" in vp["milestones_overdue"]

    def test_format_includes_volume_progress_block(self):
        from src.novel.services.continuity_service import ContinuityService

        ms = [
            _make_milestone("m1", status="completed", completed_at=5, target_range=[1, 10],
                            description="激活系统"),
            _make_milestone("m2", status="overdue", target_range=[5, 10],
                            description="攻占青云山门"),
        ]
        nd = _make_novel_data(milestones=ms)
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=12, novel_data=nd)
        formatted = svc.format_for_prompt(brief)
        assert "当前卷进度摘要" in formatted
        assert "激活系统" in formatted
        assert "攻占青云山门" in formatted
        assert "逾期里程碑" in formatted

    def test_no_novel_data_no_crash(self):
        from src.novel.services.continuity_service import ContinuityService

        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=5, novel_data=None)
        assert brief.get("volume_progress") == {}

    def test_novel_without_milestones_no_crash(self):
        from src.novel.services.continuity_service import ContinuityService

        nd = _make_novel_data(milestones=None)
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=5, novel_data=nd)
        vp = brief.get("volume_progress", {})
        # No milestones => empty or on_track
        assert vp.get("progress_health", "on_track") == "on_track"

    def test_format_prompt_length_under_500(self):
        """Volume progress block should be < 500 chars."""
        from src.novel.services.continuity_service import ContinuityService

        ms = [
            _make_milestone("m1", status="completed", completed_at=5,
                            target_range=[1, 10], description="里程碑一里程碑一里程碑"),
            _make_milestone("m2", status="pending", target_range=[10, 20],
                            description="里程碑二里程碑二里程碑二"),
            _make_milestone("m3", status="overdue", target_range=[5, 10],
                            description="逾期里程碑逾期里程碑"),
        ]
        nd = _make_novel_data(milestones=ms)
        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=15, novel_data=nd)
        formatted = svc.format_for_prompt(brief)
        # Extract just the volume progress section
        lines = formatted.split("\n")
        vp_lines = []
        in_vp = False
        for line in lines:
            if "当前卷进度摘要" in line:
                in_vp = True
            elif in_vp and line.startswith("###"):
                break
            if in_vp:
                vp_lines.append(line)
        vp_block = "\n".join(vp_lines)
        assert len(vp_block) < 500


# ---------------------------------------------------------------------------
# NOTE: Phase 2-δ removed PlotPlanner; the ``_build_volume_progress_section``
# helper no longer exists.  Volume-progress formatting now happens inline
# inside ChapterPlanner's prompt, so these old tests are retired.  The
# MilestoneTracker tests above still cover the data-level behaviour.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# VolumeSettlement: milestone settlement
# ---------------------------------------------------------------------------

class TestVolumeSettlementMilestones:
    def test_settle_inherits_critical_to_next_volume(self):
        from src.novel.services.volume_settlement import VolumeSettlement

        ms = [
            _make_milestone("m1", status="completed", completed_at=8,
                            priority="critical", target_range=[1, 10]),
            _make_milestone("m2", status="overdue", priority="critical",
                            target_range=[5, 20]),
            _make_milestone("m3", status="pending", priority="normal",
                            target_range=[15, 25]),
        ]
        vol2 = {
            "volume_number": 2, "title": "卷二",
            "start_chapter": 31, "end_chapter": 60,
        }
        nd = _make_novel_data(milestones=ms, extra_volumes=[vol2])
        vs = VolumeSettlement(db=None, outline=nd.get("outline", {}))
        report = vs.settle_volume_milestones(volume_number=1, novel_data=nd)

        assert report["milestones_total"] == 3
        assert report["milestones_completed"] == 1
        assert report["milestones_inherited_to_next"] == 1
        assert report["completion_rate"] == pytest.approx(1 / 3, abs=0.01)

        # Verify inherited milestone appears in vol2
        vol2_ms = nd["outline"]["volumes"][1].get("narrative_milestones", [])
        assert len(vol2_ms) == 1
        assert vol2_ms[0]["milestone_id"] == "m2"
        assert vol2_ms[0]["inherited_from_volume"] == 1
        assert vol2_ms[0]["status"] == "pending"

    def test_settle_abandons_at_last_volume(self):
        from src.novel.services.volume_settlement import VolumeSettlement

        ms = [
            _make_milestone("m1", status="overdue", priority="critical",
                            target_range=[1, 10]),
        ]
        nd = _make_novel_data(milestones=ms)
        vs = VolumeSettlement(db=None, outline=nd.get("outline", {}))
        report = vs.settle_volume_milestones(volume_number=1, novel_data=nd)

        assert report["milestones_abandoned"] == 1
        assert report["milestones_inherited_to_next"] == 0
        assert ms[0]["status"] == "abandoned"

    def test_settle_creates_report_on_volume(self):
        from src.novel.services.volume_settlement import VolumeSettlement

        ms = [
            _make_milestone("m1", status="completed", completed_at=5,
                            priority="critical", target_range=[1, 10]),
        ]
        nd = _make_novel_data(milestones=ms)
        vs = VolumeSettlement(db=None, outline=nd.get("outline", {}))
        report = vs.settle_volume_milestones(volume_number=1, novel_data=nd)

        vol = nd["outline"]["volumes"][0]
        assert "settlement_report" in vol
        assert vol["settlement_report"]["milestones_completed"] == 1

    def test_settle_nonexistent_volume_returns_empty(self):
        from src.novel.services.volume_settlement import VolumeSettlement

        nd = _make_novel_data(milestones=[])
        vs = VolumeSettlement(db=None, outline=nd.get("outline", {}))
        report = vs.settle_volume_milestones(volume_number=99, novel_data=nd)
        assert report == {}

    def test_settlement_brief_includes_milestone_warning(self):
        """get_settlement_brief should warn about incomplete critical milestones."""
        from src.novel.services.volume_settlement import VolumeSettlement
        from unittest.mock import patch

        ms = [
            _make_milestone("m1", status="pending", priority="critical",
                            target_range=[1, 30], description="必须完成的大事"),
        ]
        nd = _make_novel_data(milestones=ms)
        outline = nd["outline"]

        mock_db = MagicMock()
        vs = VolumeSettlement(db=mock_db, outline=outline)

        # ObligationTracker is imported inside get_settlement_brief,
        # so we patch it at its source module.
        with patch("src.novel.services.obligation_tracker.ObligationTracker") as MockOT:
            mock_tracker = MagicMock()
            mock_tracker.get_debts_for_chapter.return_value = []
            MockOT.return_value = mock_tracker

            brief = vs.get_settlement_brief(chapter_num=29)  # within 3 of end(30)
            assert brief["is_settlement_zone"]
            assert "里程碑警告" in brief["settlement_prompt"]
            assert "必须完成的大事" in brief["settlement_prompt"]


# ---------------------------------------------------------------------------
# Round-trip: milestones survive JSON serialization
# ---------------------------------------------------------------------------

class TestSerializationRoundTrip:
    def test_milestones_survive_json_roundtrip(self):
        ms = [
            _make_milestone("m1", status="completed", completed_at=5),
            _make_milestone("m2", status="overdue"),
        ]
        nd = _make_novel_data(milestones=ms)
        # Simulate checkpoint save/load
        serialized = json.dumps(nd, ensure_ascii=False)
        loaded = json.loads(serialized)
        tracker = MilestoneTracker(loaded)
        p = tracker.compute_volume_progress(chapter_num=10)
        assert p["progress_health"] == "critical"  # overdue present


# ---------------------------------------------------------------------------
# Migration: novels without milestones
# ---------------------------------------------------------------------------

class TestMigrationSafety:
    def test_novel_without_milestones_loads_fine(self):
        """Novel data without narrative_milestones should not crash."""
        nd = {
            "novel_id": "old_novel",
            "outline": {
                "volumes": [
                    {
                        "volume_number": 1,
                        "title": "旧卷",
                        "start_chapter": 1,
                        "end_chapter": 30,
                    }
                ],
                "chapters": [],
            },
        }
        tracker = MilestoneTracker(nd)
        assert tracker.get_milestones_for_chapter(10) == []
        assert tracker.check_milestone_completion(10, "some text") == []
        assert tracker.mark_overdue_milestones(10) == []
        p = tracker.compute_volume_progress(10)
        assert p["progress_health"] == "on_track"

    def test_novel_without_outline_loads_fine(self):
        nd = {"novel_id": "bare_novel"}
        tracker = MilestoneTracker(nd)
        assert tracker.get_milestones_for_chapter(1) == []
        assert tracker.compute_volume_progress(1) == {}

    def test_malformed_milestone_skipped(self):
        """A milestone dict missing required fields should be skipped, not crash."""
        ms = [
            {"milestone_id": "bad", "description": "too short"},  # missing fields
            _make_milestone("m1"),
        ]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        result = tracker.get_milestones_for_chapter(10)
        # Only the valid milestone should be returned
        assert len(result) <= 1


# ---------------------------------------------------------------------------
# Multiple milestones in one chapter
# ---------------------------------------------------------------------------

class TestMultipleMilestones:
    def test_multiple_milestones_completed_in_one_chapter(self):
        ms = [
            _make_milestone("m1", criteria=["招募"], target_range=[1, 20]),
            _make_milestone("m2", criteria=["攻占"], target_range=[1, 20]),
        ]
        nd = _make_novel_data(milestones=ms)
        tracker = MilestoneTracker(nd)
        completed = tracker.check_milestone_completion(
            chapter_num=10,
            chapter_text="主角招募部队后攻占了据点。",
        )
        assert set(completed) == {"m1", "m2"}
