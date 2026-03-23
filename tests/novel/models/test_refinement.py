"""Tests for src.novel.models.refinement data models."""
import pytest
from pydantic import ValidationError

from src.novel.models.refinement import (
    ProofreadingIssue,
    ProofreadingIssueType,
    SettingConflict,
    SettingImpact,
)


class TestProofreadingIssue:
    """ProofreadingIssue model tests."""

    def test_create_normal(self):
        issue = ProofreadingIssue(
            issue_type=ProofreadingIssueType.TYPO,
            original="他走的很快",
            correction="他走得很快",
            explanation="的/得 用法错误",
        )
        assert issue.issue_type == ProofreadingIssueType.TYPO
        assert issue.original == "他走的很快"
        assert issue.correction == "他走得很快"
        assert issue.explanation == "的/得 用法错误"

    def test_create_with_string_type(self):
        """ProofreadingIssueType is a str enum, can be created from string."""
        issue = ProofreadingIssue(
            issue_type="punctuation",
            original="你好,",
            correction="你好，",
        )
        assert issue.issue_type == ProofreadingIssueType.PUNCTUATION

    def test_default_explanation(self):
        issue = ProofreadingIssue(
            issue_type=ProofreadingIssueType.GRAMMAR,
            original="abc",
            correction="def",
        )
        assert issue.explanation == ""

    def test_missing_original_raises(self):
        with pytest.raises(ValidationError):
            ProofreadingIssue(
                issue_type=ProofreadingIssueType.TYPO,
                correction="fixed",
            )

    def test_missing_correction_raises(self):
        with pytest.raises(ValidationError):
            ProofreadingIssue(
                issue_type=ProofreadingIssueType.TYPO,
                original="broken",
            )

    def test_empty_original_raises(self):
        with pytest.raises(ValidationError):
            ProofreadingIssue(
                issue_type=ProofreadingIssueType.TYPO,
                original="",
                correction="fixed",
            )

    def test_empty_correction_raises(self):
        with pytest.raises(ValidationError):
            ProofreadingIssue(
                issue_type=ProofreadingIssueType.TYPO,
                original="broken",
                correction="",
            )

    def test_all_issue_types(self):
        for itype in ProofreadingIssueType:
            issue = ProofreadingIssue(
                issue_type=itype,
                original="a",
                correction="b",
            )
            assert issue.issue_type == itype


class TestSettingConflict:
    """SettingConflict model tests."""

    def test_create_normal(self):
        conflict = SettingConflict(
            chapter_number=5,
            conflict_text="主角用右手持剑",
            reason="主角设定为左撇子",
            suggested_fix="改为左手持剑",
        )
        assert conflict.chapter_number == 5
        assert conflict.conflict_text == "主角用右手持剑"
        assert conflict.reason == "主角设定为左撇子"
        assert conflict.suggested_fix == "改为左手持剑"

    def test_default_suggested_fix(self):
        conflict = SettingConflict(
            chapter_number=1,
            conflict_text="some text",
            reason="some reason",
        )
        assert conflict.suggested_fix == ""

    def test_chapter_number_must_be_positive(self):
        with pytest.raises(ValidationError):
            SettingConflict(
                chapter_number=0,
                conflict_text="text",
                reason="reason",
            )

    def test_missing_conflict_text_raises(self):
        with pytest.raises(ValidationError):
            SettingConflict(
                chapter_number=1,
                conflict_text="",
                reason="reason",
            )

    def test_missing_reason_raises(self):
        with pytest.raises(ValidationError):
            SettingConflict(
                chapter_number=1,
                conflict_text="text",
                reason="",
            )


class TestSettingImpact:
    """SettingImpact model tests."""

    def test_create_normal(self):
        impact = SettingImpact(
            modified_field="character.weapon",
            old_summary="长剑",
            new_summary="短刀",
            affected_chapters=[3, 5, 7],
            conflicts=[
                SettingConflict(
                    chapter_number=3,
                    conflict_text="拔出长剑",
                    reason="武器已改为短刀",
                )
            ],
            severity="high",
            summary="武器变更影响3个章节",
        )
        assert impact.modified_field == "character.weapon"
        assert impact.old_summary == "长剑"
        assert impact.new_summary == "短刀"
        assert impact.affected_chapters == [3, 5, 7]
        assert len(impact.conflicts) == 1
        assert impact.severity == "high"
        assert impact.summary == "武器变更影响3个章节"

    def test_defaults(self):
        impact = SettingImpact(modified_field="world.era")
        assert impact.old_summary == ""
        assert impact.new_summary == ""
        assert impact.affected_chapters == []
        assert impact.conflicts == []
        assert impact.severity == "medium"
        assert impact.summary == ""

    def test_severity_must_be_valid(self):
        with pytest.raises(ValidationError):
            SettingImpact(
                modified_field="x",
                severity="critical",  # not in low/medium/high
            )

    def test_missing_modified_field_raises(self):
        with pytest.raises(ValidationError):
            SettingImpact()
