"""Direct tests for src/novel/tools/writer_postprocess.py module functions.

These cover the 4 post-processing functions independently of the Writer
agent. Backwards compatibility (Writer wrapper methods + module-level
``_sanitize_chapter_text``) is exercised by the existing
``tests/novel/test_writer_dedup_and_lock.py`` and
``tests/novel/test_writer_length_control.py`` suites — those are now de
facto contract tests for the wrappers.
"""

from __future__ import annotations

import pytest

from src.novel.models.character import (
    Appearance,
    CharacterProfile,
    Personality,
)
from src.novel.tools.writer_postprocess import (
    DEDUP_HARD_DELETE,
    DEDUP_STRIP_OVERLAP,
    SYSTEM_UI_ALLOWLIST,
    SYSTEM_UI_PATTERNS,
    check_character_names,
    dedup_paragraphs,
    sanitize_chapter_text,
    trim_to_hard_cap,
)


# ---------------------------------------------------------------------------
# sanitize_chapter_text
# ---------------------------------------------------------------------------


class TestSanitizeChapterText:
    def test_empty_input(self) -> None:
        assert sanitize_chapter_text("") == ""

    def test_none_input_passthrough(self) -> None:
        # 当前实现 if not text: return text，None 也透传
        assert sanitize_chapter_text(None) is None  # type: ignore[arg-type]

    def test_strips_bracketed_ui(self) -> None:
        text = "他走进房间。【系统】检测到敌人。她笑了。"
        out = sanitize_chapter_text(text)
        assert "【系统】" not in out
        assert "他走进房间" in out
        assert "她笑了" in out

    def test_keeps_allowlisted_marker(self) -> None:
        text = "他打开宝箱。【叮！】系统提示音响起。剑光一闪。"
        out = sanitize_chapter_text(text)
        assert "【叮！】" in out, f"allowlist 失效，输出: {out!r}"
        assert "他打开宝箱" in out

    def test_strips_stat_changes_arrow(self) -> None:
        text = "战斗结束。忠诚度：71→79。他松了一口气。"
        out = sanitize_chapter_text(text)
        assert "71→79" not in out
        assert "战斗结束" in out

    def test_strips_stat_changes_plus(self) -> None:
        text = "胜利后\n兵煞值+8\n继续前进。"
        out = sanitize_chapter_text(text)
        assert "兵煞值+8" not in out
        assert "胜利后" in out
        assert "继续前进" in out

    def test_collapses_3plus_newlines(self) -> None:
        text = "段一。\n\n\n\n段二。"
        out = sanitize_chapter_text(text)
        # 任意 3+ 连续 \n 被压成 \n\n
        assert "\n\n\n" not in out
        assert "段一" in out and "段二" in out

    def test_idempotent(self) -> None:
        """sanitize 应该可重复调用 — 第二次过不再改动文本。"""
        raw = "他走进房间。【系统】检测到敌人。【叮！】突袭！"
        once = sanitize_chapter_text(raw)
        twice = sanitize_chapter_text(once)
        assert once == twice

    def test_module_constants_exposed(self) -> None:
        """模块常量必须 public 暴露（writer.py 要 import alias）。"""
        assert isinstance(SYSTEM_UI_PATTERNS, list)
        assert len(SYSTEM_UI_PATTERNS) == 3
        assert "【叮！】" in SYSTEM_UI_ALLOWLIST


# ---------------------------------------------------------------------------
# trim_to_hard_cap
# ---------------------------------------------------------------------------


class TestTrimToHardCap:
    def test_under_cap_unchanged(self) -> None:
        text = "短文本。"
        assert trim_to_hard_cap(text, hard_cap=100, target=80) == text

    def test_empty_input(self) -> None:
        assert trim_to_hard_cap("", hard_cap=100, target=80) == ""

    def test_zero_cap_passthrough(self) -> None:
        text = "文本。" * 10
        assert trim_to_hard_cap(text, hard_cap=0, target=80) == text

    def test_negative_cap_passthrough(self) -> None:
        text = "文本。" * 10
        assert trim_to_hard_cap(text, hard_cap=-1, target=80) == text

    def test_cuts_at_sentence_boundary(self) -> None:
        text = "第一句话。第二句话。第三句话。第四句话。"
        # hard_cap=10 chars，应该 cut 到最近句末标点
        result = trim_to_hard_cap(text, hard_cap=10, target=8)
        assert len(result) <= 10
        assert result.endswith(("。", "！", "？"))

    def test_cuts_includes_trailing_quote(self) -> None:
        text = "他喊：「住手！」然后转身离去。还有更多内容。"
        # hard_cap 落在「住手！」附近，应带出闭合引号
        result = trim_to_hard_cap(text, hard_cap=12, target=10)
        assert len(result) <= 14  # +4 closing chars allowance

    def test_no_punct_window_falls_back(self) -> None:
        """窗口内没有句末标点 → 硬切到 hard_cap。"""
        text = "abcdefghij" * 10
        result = trim_to_hard_cap(text, hard_cap=15, target=10)
        # 字面切到 15 字（无句末标点找不到）
        assert len(result) == 15


# ---------------------------------------------------------------------------
# dedup_paragraphs
# ---------------------------------------------------------------------------


class TestDedupParagraphs:
    def test_empty_previous_unchanged(self) -> None:
        text = "新段落内容很多很多很多。"
        assert dedup_paragraphs(text, []) == text

    def test_empty_new_text(self) -> None:
        result = dedup_paragraphs("", ["前文。" * 10])
        assert result == ""

    def test_unrelated_content_kept(self) -> None:
        text = "完全不同的新内容描写当下场景。"
        prev = "完全不相关的前文段落讲述其他事件。"
        result = dedup_paragraphs(text, [prev])
        assert result == text

    def test_hard_dup_removes_paragraph(self) -> None:
        """≥60% 句子重复 → 整段删除（句子需 >=6 字才入比较集）。"""
        prev = "他走进了昏暗的房间。她坐在窗边的桌子前。窗外下着倾盆大雨。"
        # 全部 3 句重复 = 100%，>=60%，整段删
        new_text = "他走进了昏暗的房间。她坐在窗边的桌子前。窗外下着倾盆大雨。"
        result = dedup_paragraphs(new_text, [prev])
        assert result == ""

    def test_partial_dup_strips_only_overlap(self) -> None:
        """≥40% < 60% → 只剥重复句保留独有句。"""
        prev = "他走进了昏暗的房间。她坐在窗边的桌子前。窗外下着倾盆大雨。"
        new_text = (
            "他走进了昏暗的房间。她坐在窗边的桌子前。"
            "他伸手打开了窗户。一阵清凉微风吹了进来。"
        )
        # 2 句重复 + 2 句新 = 50%
        result = dedup_paragraphs(new_text, [prev])
        assert "他走进了昏暗的房间" not in result
        assert "她坐在窗边的桌子前" not in result
        assert "他伸手打开了窗户" in result
        assert "一阵清凉微风吹了进来" in result

    def test_thresholds_constant(self) -> None:
        """阈值常量必须 public 暴露给 ChapterPlanner / 测试。"""
        assert DEDUP_HARD_DELETE == 0.6
        assert DEDUP_STRIP_OVERLAP == 0.4


# ---------------------------------------------------------------------------
# check_character_names
# ---------------------------------------------------------------------------


def _char(name: str, gender: str = "男", age: int = 30) -> CharacterProfile:
    return CharacterProfile(
        name=name,
        gender=gender,
        age=age,
        occupation="测试",
        appearance=Appearance(
            height="180cm",
            build="健壮",
            hair="短发",
            eyes="深色",
            clothing_style="便装",
        ),
        personality=Personality(
            traits=["冷静", "果断", "沉稳"],
            core_belief="活下去",
            motivation="完成任务",
            flaw="冲动",
            speech_style="简短",
        ),
    )


class TestCheckCharacterNames:
    def test_empty_text(self) -> None:
        assert check_character_names("", [_char("张三")]) == ""

    def test_no_characters(self) -> None:
        text = "他走过去。"
        assert check_character_names(text, []) == text

    def test_replaces_unique_placeholder(self) -> None:
        """单一性别匹配的占位符 → 替换为已知角色名。"""
        text = "女学生A走进教室坐下。"
        result = check_character_names(text, [_char("林玲", gender="女", age=18)])
        assert "女学生A" not in result
        assert "林玲" in result

    def test_keeps_placeholder_when_ambiguous(self) -> None:
        """多个候选 → 不替换（避免误改）。"""
        text = "男学生A说话。"
        chars = [
            _char("王伟", gender="男", age=18),
            _char("李强", gender="男", age=18),
        ]
        result = check_character_names(text, chars)
        # 候选 >1 时保留占位符（log warn 但不替换）
        assert "男学生A" in result

    def test_pronoun_prefix_not_warned(self) -> None:
        """「他低头」「她转身」等代词+动词组合不应当作未知角色名。"""
        text = "他低头看着地面。她转身离开。"
        # 不应抛错，且原文不变（无替换）
        result = check_character_names(text, [_char("陈远")])
        assert result == text

    def test_known_name_passthrough(self) -> None:
        text = "陈远说：「我同意。」"
        result = check_character_names(text, [_char("陈远")])
        assert result == text

    def test_partial_match_treated_known(self) -> None:
        """部分匹配也算已知（"陈工" 应匹配 "陈远"）。"""
        # 注意当前实现：name in kn or kn in name 都算 known
        text = "陈说道：「好的。」"
        result = check_character_names(text, [_char("陈远")])
        assert result == text


# ---------------------------------------------------------------------------
# Writer wrapper backwards compatibility
# ---------------------------------------------------------------------------


class TestWriterWrappersDelegateToModule:
    """Writer 的私有 wrapper 方法应该委托给本模块函数 — 行为一致。"""

    def test_writer_sanitize_alias_is_module_function(self) -> None:
        from src.novel.agents.writer import _sanitize_chapter_text

        assert _sanitize_chapter_text is sanitize_chapter_text

    def test_writer_trim_wrapper_matches_module(self) -> None:
        from src.novel.agents.writer import Writer

        text = "句子一。" * 50
        a = Writer._trim_to_hard_cap(text, hard_cap=80, target=50)
        b = trim_to_hard_cap(text, hard_cap=80, target=50)
        assert a == b

    def test_writer_dedup_wrapper_matches_module(self) -> None:
        from unittest.mock import MagicMock

        from src.novel.agents.writer import Writer

        writer = Writer(MagicMock())
        new_text = "他走进房间。她坐在桌前。窗外下着雨。"
        prev = ["他走进房间。她坐在桌前。窗外下着雨。"]
        a = writer._deduplicate_paragraphs(new_text, prev)
        b = dedup_paragraphs(new_text, prev)
        assert a == b

    def test_writer_check_names_wrapper_matches_module(self) -> None:
        from src.novel.agents.writer import Writer

        text = "女学生A走进教室。"
        chars = [_char("林玲", gender="女", age=18)]
        a = Writer._check_character_names(text, chars)
        b = check_character_names(text, chars)
        assert a == b

    def test_writer_dedup_constants_alias_module(self) -> None:
        from src.novel.agents import writer as writer_mod

        assert writer_mod._DEDUP_HARD_DELETE == DEDUP_HARD_DELETE
        assert writer_mod._DEDUP_STRIP_OVERLAP == DEDUP_STRIP_OVERLAP
