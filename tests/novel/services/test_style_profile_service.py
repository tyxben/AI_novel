"""Tests for StyleProfileService — 按项目学习的用词指纹。

覆盖场景：

- ``build()`` 小样本（3 章手写 fixture）
- overused phrase 检测：构造"仿佛"出现在每章 → 应被检出
- ``detect_overuse`` 边界：空文本 / 没命中 / 部分命中
- 分词失败（jieba 返回空）兜底
- 持久化：save → load 往返
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.novel.models.style_profile import (
    OverusedPhrase,
    PacingPoint,
    StyleProfile,
)
from src.novel.services.style_profile_service import (
    DEFAULT_COVERAGE_THRESHOLD,
    StyleProfileService,
    _compute_action_density,
    _mean_std,
)
from src.novel.storage.file_manager import FileManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_chapter(chapter_number: int, full_text: str) -> SimpleNamespace:
    """StyleProfileService 只读 chapter_number + full_text。"""
    return SimpleNamespace(
        chapter_number=chapter_number,
        full_text=full_text,
        title=f"第{chapter_number}章",
    )


def _fake_novel(novel_id: str, chapters: list[SimpleNamespace]) -> SimpleNamespace:
    """服务只读 novel_id + chapters。"""
    return SimpleNamespace(novel_id=novel_id, chapters=chapters)


# 手写 3 章，故意在每章重复短语"仿佛看见"与"他缓缓开口"
_CH1 = (
    "他站在山巅，仿佛看见远方的城池。"
    "风雪呼啸，天色昏暗。"
    "他缓缓开口：这片土地将属于我。"
    "然而真相并非如此。"
    "他仿佛看见一道光芒划破长空。"
)
_CH2 = (
    "清晨的阳光洒落庭院，仿佛看见一场梦。"
    "少女站在花前，沉默良久。"
    "他缓缓开口，声音低沉而温柔。"
    "那一刻，时间似乎停滞。"
    "他仿佛看见昔日的画面。"
)
_CH3 = (
    "夜色深沉，群星点点。"
    "他仿佛看见远处的篝火。"
    "将军策马而来，眼神凌厉。"
    "他缓缓开口，下令全军出击。"
    "战鼓声响起，铁骑冲锋，喊杀震天。"
)


# ---------------------------------------------------------------------------
# build() — 基础统计
# ---------------------------------------------------------------------------


class TestBuild:
    def test_empty_novel_returns_empty_profile(self):
        novel = _fake_novel("nv_empty", chapters=[])
        svc = StyleProfileService()

        profile = svc.build(novel)

        assert isinstance(profile, StyleProfile)
        assert profile.novel_id == "nv_empty"
        assert profile.sample_size == 0
        assert profile.overused_phrases == []
        assert profile.pacing_curve == []
        assert profile.avg_sentence_len == 0.0
        assert profile.sentence_len_std == 0.0

    def test_chapters_with_blank_text_are_ignored(self):
        """有 chapter 但正文为空 → sample_size=0，不爆炸。"""
        chapters = [
            _fake_chapter(1, ""),
            _fake_chapter(2, "   \n  "),
        ]
        novel = _fake_novel("nv_blank", chapters=chapters)

        profile = StyleProfileService().build(novel)

        assert profile.sample_size == 0
        assert profile.pacing_curve == []
        assert profile.overused_phrases == []

    def test_build_with_three_chapters_populates_pacing_and_stats(self):
        chapters = [
            _fake_chapter(1, _CH1),
            _fake_chapter(2, _CH2),
            _fake_chapter(3, _CH3),
        ]
        novel = _fake_novel("nv_demo", chapters=chapters)

        profile = StyleProfileService().build(novel)

        assert profile.sample_size == 3
        # pacing: 每章一个点
        assert len(profile.pacing_curve) == 3
        chapter_nums = [p.chapter_number for p in profile.pacing_curve]
        assert chapter_nums == [1, 2, 3]
        for pt in profile.pacing_curve:
            assert 0.0 <= pt.action_density <= 1.0
        # 句长统计必为正数
        assert profile.avg_sentence_len > 0
        assert profile.sentence_len_std >= 0

    def test_overused_phrase_detected_when_coverage_reaches_threshold(self):
        """每章都出现"仿佛看见" → coverage = 1.0，必然被检出。"""
        chapters = [
            _fake_chapter(1, _CH1),
            _fake_chapter(2, _CH2),
            _fake_chapter(3, _CH3),
        ]
        novel = _fake_novel("nv_overuse", chapters=chapters)

        profile = StyleProfileService().build(novel)

        phrases = [p.phrase for p in profile.overused_phrases]
        # "仿佛看见" 在每章出现至少 1 次 —— bi/tri-gram 里应命中它或其子串
        # jieba 切分 "仿佛看见" 通常为 ['仿佛', '看见']，tri/bi-gram 拼接后 → "仿佛看见"
        assert any("仿佛" in p for p in phrases), (
            f"Expected '仿佛' overused, got phrases={phrases}"
        )

    def test_all_overused_entries_have_coverage_above_threshold(self):
        chapters = [
            _fake_chapter(1, _CH1),
            _fake_chapter(2, _CH2),
            _fake_chapter(3, _CH3),
        ]
        novel = _fake_novel("nv_cov", chapters=chapters)

        profile = StyleProfileService().build(novel)

        for entry in profile.overused_phrases:
            assert entry.chapter_coverage >= DEFAULT_COVERAGE_THRESHOLD
            assert entry.total_occurrences >= 1
            assert isinstance(entry, OverusedPhrase)

    def test_small_sample_returns_empty_overused(self):
        """样本 < 3 → overused 判定不稳定，直接返回空（避免误报）。"""
        chapters = [
            _fake_chapter(1, _CH1),
            _fake_chapter(2, _CH2),
        ]
        novel = _fake_novel("nv_small", chapters=chapters)

        profile = StyleProfileService().build(novel)

        assert profile.sample_size == 2
        assert profile.overused_phrases == []
        # pacing 仍然有
        assert len(profile.pacing_curve) == 2

    def test_custom_threshold_relaxes_filter(self):
        """传更低阈值 → 命中可能变多。"""
        chapters = [
            _fake_chapter(1, _CH1),
            _fake_chapter(2, _CH2),
            _fake_chapter(3, _CH3),
        ]
        novel = _fake_novel("nv_thr", chapters=chapters)

        strict = StyleProfileService(coverage_threshold=1.0).build(novel)
        loose = StyleProfileService(coverage_threshold=0.3).build(novel)

        assert len(loose.overused_phrases) >= len(strict.overused_phrases)

    def test_invalid_threshold_rejected(self):
        with pytest.raises(ValueError):
            StyleProfileService(coverage_threshold=0)
        with pytest.raises(ValueError):
            StyleProfileService(coverage_threshold=1.5)
        with pytest.raises(ValueError):
            StyleProfileService(coverage_threshold=-0.1)


# ---------------------------------------------------------------------------
# detect_overuse() — 边界条件
# ---------------------------------------------------------------------------


class TestDetectOveruse:
    def _profile_with_phrases(self, phrases: list[tuple[str, float]]) -> StyleProfile:
        return StyleProfile(
            novel_id="nv_t",
            overused_phrases=[
                OverusedPhrase(
                    phrase=ph,
                    chapter_coverage=cov,
                    total_occurrences=5,
                )
                for ph, cov in phrases
            ],
            sample_size=10,
        )

    def test_empty_text_returns_empty(self):
        profile = self._profile_with_phrases([("仿佛看见", 0.8)])
        svc = StyleProfileService()

        assert svc.detect_overuse("", profile) == []
        assert svc.detect_overuse("   \n", profile) == []

    def test_no_phrases_in_profile_returns_empty(self):
        profile = self._profile_with_phrases([])
        svc = StyleProfileService()

        assert svc.detect_overuse("任何文本都行", profile) == []

    def test_no_hits_returns_empty(self):
        profile = self._profile_with_phrases([("仿佛看见", 0.9)])
        svc = StyleProfileService()

        hits = svc.detect_overuse("完全不相关的正文段落。", profile)

        assert hits == []

    def test_partial_hit_only_returns_matching_phrases(self):
        profile = self._profile_with_phrases(
            [("仿佛看见", 0.8), ("缓缓开口", 0.7), ("从未出现", 0.9)]
        )
        svc = StyleProfileService()

        hits = svc.detect_overuse(
            "他仿佛看见远方，便缓缓开口。", profile
        )

        assert "仿佛看见" in hits
        assert "缓缓开口" in hits
        assert "从未出现" not in hits
        # 去重 + 保持可预测的数量
        assert len(hits) == len(set(hits))

    def test_threshold_filters_low_coverage_phrases(self):
        """coverage 低于 threshold 的 phrase 不参与匹配。"""
        profile = self._profile_with_phrases(
            [("仿佛看见", 0.2), ("缓缓开口", 0.9)]
        )
        svc = StyleProfileService()

        hits = svc.detect_overuse(
            "他仿佛看见远方，便缓缓开口。", profile, threshold=0.3
        )

        assert "仿佛看见" not in hits  # 0.2 < 0.3，被过滤
        assert "缓缓开口" in hits

    def test_duplicate_hits_deduplicated(self):
        profile = self._profile_with_phrases([("仿佛看见", 0.9)])
        svc = StyleProfileService()

        hits = svc.detect_overuse(
            "仿佛看见A。仿佛看见B。仿佛看见C。", profile
        )

        assert hits == ["仿佛看见"]


# ---------------------------------------------------------------------------
# update_incremental
# ---------------------------------------------------------------------------


class TestUpdateIncremental:
    def test_appends_pacing_point(self):
        profile = StyleProfile(novel_id="nv1", sample_size=2, pacing_curve=[])
        svc = StyleProfileService()

        new_profile = svc.update_incremental(
            profile, _fake_chapter(3, _CH1)
        )

        assert new_profile.sample_size == 3
        assert len(new_profile.pacing_curve) == 1
        assert new_profile.pacing_curve[0].chapter_number == 3

    def test_blank_chapter_does_not_increase_sample(self):
        profile = StyleProfile(novel_id="nv1", sample_size=2, pacing_curve=[])
        svc = StyleProfileService()

        new_profile = svc.update_incremental(profile, _fake_chapter(3, ""))

        assert new_profile.sample_size == 2
        assert new_profile.pacing_curve == []

    def test_replaces_pacing_for_same_chapter_number(self):
        """同一章号多次调用不会出现重复点。"""
        profile = StyleProfile(
            novel_id="nv1",
            sample_size=3,
            pacing_curve=[
                PacingPoint(chapter_number=3, action_density=0.1),
            ],
        )
        svc = StyleProfileService()

        new_profile = svc.update_incremental(
            profile, _fake_chapter(3, _CH3)
        )

        nums = [p.chapter_number for p in new_profile.pacing_curve]
        assert nums == [3]


# ---------------------------------------------------------------------------
# 分词失败兜底
# ---------------------------------------------------------------------------


class TestTokenizeFallback:
    def test_build_tolerates_jieba_returning_empty(self, monkeypatch):
        """当 jieba 分词返回空时，build 不应抛异常，返回空 overused。"""
        import src.novel.services.style_profile_service as mod

        monkeypatch.setattr(mod, "_tokenize", lambda text: [])

        chapters = [
            _fake_chapter(1, _CH1),
            _fake_chapter(2, _CH2),
            _fake_chapter(3, _CH3),
        ]
        novel = _fake_novel("nv_no_tokens", chapters=chapters)

        profile = mod.StyleProfileService().build(novel)

        # 样本数仍反映章节数，但 overused 空、pacing 中性
        assert profile.sample_size == 3
        assert profile.overused_phrases == []
        for pt in profile.pacing_curve:
            # _compute_action_density 空 tokens → 0.5
            assert pt.action_density == 0.5

    def test_compute_action_density_empty_tokens(self):
        assert _compute_action_density([]) == 0.5

    def test_compute_action_density_no_action_no_description(self):
        """有 tokens 但都不是 action/description → 0.5 中性。"""
        assert _compute_action_density(["的", "了", "是", "在"]) == 0.5

    def test_compute_action_density_all_action(self):
        d = _compute_action_density(["冲", "跳", "打", "砍"])
        assert d == 1.0

    def test_compute_action_density_all_description(self):
        d = _compute_action_density(["阳光", "月光", "夜色"])
        assert d == 0.0

    def test_mean_std_empty(self):
        assert _mean_std([]) == (0.0, 0.0)

    def test_mean_std_single(self):
        mean, std = _mean_std([5])
        assert mean == 5.0
        assert std == 0.0


# ---------------------------------------------------------------------------
# 持久化：save → load 往返
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_roundtrip_save_and_load(self, tmp_path):
        fm = FileManager(workspace_dir=str(tmp_path))
        novel_id = "nv_persist"
        # 必须先让 _novel_dir 合法 —— 创建目录即可
        fm._novel_dir(novel_id)

        profile = StyleProfile(
            novel_id=novel_id,
            overused_phrases=[
                OverusedPhrase(
                    phrase="仿佛看见",
                    chapter_coverage=0.8,
                    total_occurrences=12,
                )
            ],
            avg_sentence_len=18.5,
            sentence_len_std=4.2,
            pacing_curve=[
                PacingPoint(chapter_number=1, action_density=0.3),
                PacingPoint(chapter_number=2, action_density=0.7),
            ],
            sample_size=2,
        )

        path = fm.save_style_profile(novel_id, profile.model_dump())

        assert path.exists()
        assert path.name == "style_profile.json"
        assert path.parent.name == ".cache"

        loaded = fm.load_style_profile(novel_id)

        assert loaded is not None
        assert loaded["novel_id"] == novel_id
        assert loaded["sample_size"] == 2
        assert loaded["avg_sentence_len"] == 18.5
        assert len(loaded["overused_phrases"]) == 1
        assert loaded["overused_phrases"][0]["phrase"] == "仿佛看见"

        # 能反序列化回 StyleProfile
        restored = StyleProfile.model_validate(loaded)
        assert restored.overused_phrases[0].phrase == "仿佛看见"
        assert restored.pacing_curve[0].action_density == 0.3

    def test_load_returns_none_when_missing(self, tmp_path):
        fm = FileManager(workspace_dir=str(tmp_path))
        fm._novel_dir("nv_absent")

        assert fm.load_style_profile("nv_absent") is None

    def test_save_overwrites_existing_file(self, tmp_path):
        fm = FileManager(workspace_dir=str(tmp_path))
        novel_id = "nv_overwrite"
        fm._novel_dir(novel_id)

        fm.save_style_profile(novel_id, {"novel_id": novel_id, "sample_size": 1})
        fm.save_style_profile(novel_id, {"novel_id": novel_id, "sample_size": 5})

        loaded = fm.load_style_profile(novel_id)
        assert loaded is not None
        assert loaded["sample_size"] == 5

    def test_saved_json_is_utf8_and_not_ascii_escaped(self, tmp_path):
        """确认中文字符被直接写入，而不是被转成 \\uXXXX 。"""
        fm = FileManager(workspace_dir=str(tmp_path))
        novel_id = "nv_utf8"
        fm._novel_dir(novel_id)

        fm.save_style_profile(
            novel_id, {"novel_id": novel_id, "note": "仿佛看见"}
        )

        path = fm._style_profile_path(novel_id)
        raw = path.read_text(encoding="utf-8")
        assert "仿佛看见" in raw
        # 确保是合法 JSON
        parsed = json.loads(raw)
        assert parsed["note"] == "仿佛看见"
