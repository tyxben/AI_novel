"""Tests for ChapterVerifier — 业务硬约束验证。"""

from __future__ import annotations

import pytest

from src.novel.services.chapter_verifier import (
    ChapterVerifier,
    Failure,
    VerifyReport,
    _extract_keywords,
)


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------


class TestExtractKeywords:
    def test_strips_published_prefix(self):
        kws = _extract_keywords(
            "[已发布] 黑风寨副寨主必报复辰风村，冲突未解决。"
        )
        assert any("黑风寨" in k or "副寨主" in k for k in kws)

    def test_strips_role_promise_prefix(self):
        kws = _extract_keywords("角色承诺: 必须把敌人引入五十米内。")
        # 不该把 "角色承诺" 也算进去
        assert not any("角色承诺" in k for k in kws)

    def test_chunks_by_punctuation(self):
        kws = _extract_keywords("黑风寨副寨主必报复，冲突未解决。")
        assert "黑风寨副寨主必报复" in kws or any(
            len(k) >= 4 for k in kws
        )

    def test_long_phrase_truncated(self):
        kws = _extract_keywords("非常非常非常非常非常长的一段没有标点的描述句")
        assert all(len(k) <= 12 for k in kws)
        assert kws  # 至少有一条

    def test_empty_input(self):
        assert _extract_keywords("") == []

    def test_too_short_phrases_dropped(self):
        kws = _extract_keywords("是。否。也。")
        assert kws == []


# ---------------------------------------------------------------------------
# ChapterVerifier — debt
# ---------------------------------------------------------------------------


@pytest.fixture
def verifier():
    return ChapterVerifier()


class TestDebtCheck:
    def test_passes_when_keyword_in_text(self, verifier):
        report = verifier.verify(
            "林辰下令围攻黑风寨副寨主，将其当场格杀。",
            must_fulfill_debts=[
                {
                    "debt_id": "d1",
                    "description": "[已发布] 黑风寨副寨主必报复辰风村",
                }
            ],
        )
        assert report.passed
        assert report.failures == []

    def test_fails_when_keyword_absent(self, verifier):
        report = verifier.verify(
            "林辰在矿场布防，气氛紧张。",
            must_fulfill_debts=[
                {
                    "debt_id": "d1",
                    "description": "[已发布] 黑风寨副寨主必报复辰风村",
                }
            ],
        )
        assert not report.passed
        assert any(f.rule == "debt" for f in report.failures)
        assert report.high_severity_count >= 1

    def test_multiple_debts_partial_pass(self, verifier):
        report = verifier.verify(
            "黑风寨副寨主跪在阶下。",
            must_fulfill_debts=[
                {"debt_id": "d1", "description": "黑风寨副寨主必报复"},
                {"debt_id": "d2", "description": "矿脉外运调货印必须找到"},
            ],
        )
        # d1 命中，d2 未命中
        rule_failures = [f for f in report.failures if f.rule == "debt"]
        assert len(rule_failures) == 1
        assert "d2" in rule_failures[0].detail


# ---------------------------------------------------------------------------
# ChapterVerifier — foreshadowing
# ---------------------------------------------------------------------------


class TestForeshadowingCheck:
    def test_passes_when_referenced(self, verifier):
        report = verifier.verify(
            "林辰摸出银纹灵石，纹路骤然亮起。",
            must_collect_foreshadowings=[
                {
                    "foreshadowing_id": "f1",
                    "content": "银纹灵石可能与林辰修炼链路相关",
                }
            ],
        )
        assert report.passed

    def test_fails_when_unreferenced(self, verifier):
        report = verifier.verify(
            "林辰布置阵型，与匪寇对峙。",
            must_collect_foreshadowings=[
                {
                    "foreshadowing_id": "f1",
                    "content": "银纹灵石可能与林辰修炼链路相关",
                }
            ],
        )
        assert not report.passed
        assert any(f.rule == "foreshadowing" for f in report.failures)


# ---------------------------------------------------------------------------
# ChapterVerifier — banned phrases
# ---------------------------------------------------------------------------


class TestBannedPhraseCheck:
    def test_no_banned(self, verifier):
        report = verifier.verify(
            "林辰目光落在远处。",
            banned_phrases=["黑眸", "不由得"],
        )
        assert report.passed

    def test_low_severity_single(self, verifier):
        report = verifier.verify(
            "林辰黑眸一凝。",
            banned_phrases=["黑眸"],
        )
        assert not report.passed
        f = next(f for f in report.failures if f.rule == "banned_phrase")
        assert f.severity == "low"

    def test_medium_severity_two(self, verifier):
        report = verifier.verify(
            "林辰黑眸冷冽。她也黑眸如水。",
            banned_phrases=["黑眸"],
        )
        f = next(f for f in report.failures if f.rule == "banned_phrase")
        assert f.severity == "medium"

    def test_high_severity_three_plus(self, verifier):
        text = "黑眸一凝。黑眸冷下来。黑眸深不见底。黑眸睥睨。"
        report = verifier.verify(text, banned_phrases=["黑眸"])
        f = next(f for f in report.failures if f.rule == "banned_phrase")
        assert f.severity == "high"
        assert "4 次" in f.detail


# ---------------------------------------------------------------------------
# ChapterVerifier — length
# ---------------------------------------------------------------------------


class TestLengthCheck:
    def test_within_tolerance_passes(self, verifier):
        text = "字" * 2400  # 4% deviation from 2500
        report = verifier.verify(text, target_words=2500)
        assert report.passed
        assert report.word_count == 2400

    def test_medium_overage(self, verifier):
        text = "字" * 3100  # 24% over
        report = verifier.verify(text, target_words=2500)
        f = next(f for f in report.failures if f.rule == "length")
        assert f.severity == "medium"
        assert "偏长" in f.detail

    def test_high_overage(self, verifier):
        text = "字" * 5000  # 100% over
        report = verifier.verify(text, target_words=2500)
        f = next(f for f in report.failures if f.rule == "length")
        assert f.severity == "high"

    def test_high_underage(self, verifier):
        text = "字" * 1000  # 60% under
        report = verifier.verify(text, target_words=2500)
        f = next(f for f in report.failures if f.rule == "length")
        assert f.severity == "high"
        assert "偏短" in f.detail

    def test_skip_when_no_target(self, verifier):
        report = verifier.verify("短文")
        assert report.passed


# ---------------------------------------------------------------------------
# Combined + report
# ---------------------------------------------------------------------------


class TestReport:
    def test_to_writer_feedback_empty_when_passed(self, verifier):
        report = verifier.verify("正文", target_words=None)
        assert report.to_writer_feedback() == ""

    def test_to_writer_feedback_includes_all_failures(self, verifier):
        text = "黑眸冷冽。"  # 短 + 禁词
        report = verifier.verify(
            text,
            banned_phrases=["黑眸"],
            target_words=2500,
        )
        msg = report.to_writer_feedback()
        assert "黑眸" in msg
        assert "字数" in msg
        assert msg.startswith("上一稿未达硬性要求")

    def test_combined_failure(self, verifier):
        report = verifier.verify(
            "林辰黑眸一冷。" * 3,
            must_fulfill_debts=[
                {"debt_id": "d1", "description": "黑风寨副寨主必报复"}
            ],
            must_collect_foreshadowings=[
                {"foreshadowing_id": "f1", "content": "银纹灵石"}
            ],
            banned_phrases=["黑眸"],
            target_words=3000,
        )
        kinds = {f.rule for f in report.failures}
        assert {"debt", "foreshadowing", "banned_phrase", "length"}.issubset(kinds)
        assert report.high_severity_count >= 2

    def test_no_constraints_passes(self, verifier):
        report = verifier.verify("任意文本")
        assert report.passed
        assert report.word_count == 4
