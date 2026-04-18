"""Phase 1-B: ChapterOutline.chapter_type × target_words 推算测试。

覆盖 DESIGN.md Part 1 / Part 6 的字段契约：
- chapter_type 默认 "buildup"
- target_words 显式值优先于 chapter_type × base_words
- 五种 chapter_type 的倍率都正确（setup 0.8 / buildup 1.0 / climax 1.5 /
  resolution 1.2 / interlude 0.6）
- 边界：target_words 下限 500、上限 10000
- 向后兼容：estimated_words 仍保留
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.novel.models.novel import (
    BASE_CHAPTER_WORDS,
    CHAPTER_TYPE_WORD_MULTIPLIER,
    ChapterOutline,
)


def _make(**overrides):
    defaults = dict(
        chapter_number=1,
        title="第一章",
        goal="展示主角",
        key_events=["登场"],
    )
    defaults.update(overrides)
    return ChapterOutline(**defaults)


class TestChapterTypeDefaults:
    def test_default_chapter_type_is_buildup(self):
        co = _make()
        assert co.chapter_type == "buildup"

    def test_default_target_words_is_none(self):
        co = _make()
        assert co.target_words is None

    def test_estimated_words_backward_compat_default(self):
        # 不指定 target_words，但 estimated_words 默认值仍存在
        co = _make()
        assert co.estimated_words == 2500


class TestResolvedTargetWords:
    @pytest.mark.parametrize(
        "chapter_type,expected",
        [
            ("setup", int(round(BASE_CHAPTER_WORDS * 0.8))),
            ("buildup", int(round(BASE_CHAPTER_WORDS * 1.0))),
            ("climax", int(round(BASE_CHAPTER_WORDS * 1.5))),
            ("resolution", int(round(BASE_CHAPTER_WORDS * 1.2))),
            ("interlude", int(round(BASE_CHAPTER_WORDS * 0.6))),
        ],
    )
    def test_resolved_from_chapter_type(self, chapter_type, expected):
        co = _make(chapter_type=chapter_type)
        assert co.resolved_target_words == expected

    def test_explicit_target_words_overrides_type_multiplier(self):
        co = _make(chapter_type="climax", target_words=1800)
        # climax 倍率 1.5 本应给 3750，但显式指定 1800 必须优先
        assert co.resolved_target_words == 1800

    def test_resolved_is_int(self):
        co = _make(chapter_type="climax")
        assert isinstance(co.resolved_target_words, int)

    def test_multiplier_map_complete(self):
        """确保倍率表覆盖所有 Literal 类型，防止未来新增 type 漏填。"""
        expected = {"setup", "buildup", "climax", "resolution", "interlude"}
        assert set(CHAPTER_TYPE_WORD_MULTIPLIER.keys()) == expected


class TestTargetWordsValidation:
    def test_target_words_below_lower_bound_rejected(self):
        with pytest.raises(ValidationError):
            _make(target_words=100)

    def test_target_words_above_upper_bound_rejected(self):
        with pytest.raises(ValidationError):
            _make(target_words=20000)

    def test_target_words_lower_boundary_accepted(self):
        co = _make(target_words=500)
        assert co.resolved_target_words == 500

    def test_target_words_upper_boundary_accepted(self):
        co = _make(target_words=10000)
        assert co.resolved_target_words == 10000


class TestChapterTypeValidation:
    def test_invalid_chapter_type_rejected(self):
        with pytest.raises(ValidationError):
            _make(chapter_type="badtype")

    def test_all_valid_chapter_types_accepted(self):
        for t in ("setup", "buildup", "climax", "resolution", "interlude"):
            co = _make(chapter_type=t)
            assert co.chapter_type == t


class TestSerialization:
    def test_dump_roundtrip_keeps_new_fields(self):
        co = _make(chapter_type="climax", target_words=3800)
        dumped = co.model_dump()
        assert dumped["chapter_type"] == "climax"
        assert dumped["target_words"] == 3800
        restored = ChapterOutline(**dumped)
        assert restored.chapter_type == "climax"
        assert restored.target_words == 3800
        assert restored.resolved_target_words == 3800

    def test_legacy_dict_without_new_fields_still_parses(self):
        # 老数据不含 chapter_type / target_words（迁移脚本未跑时的场景）
        legacy = {
            "chapter_number": 3,
            "title": "某章",
            "goal": "目标",
            "key_events": ["事件"],
            "estimated_words": 2500,
        }
        co = ChapterOutline(**legacy)
        assert co.chapter_type == "buildup"
        assert co.target_words is None
        assert co.resolved_target_words == BASE_CHAPTER_WORDS
