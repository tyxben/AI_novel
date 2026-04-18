"""Tests for ChapterSanitizer.

Cases include real bugs found in workspace/novels/novel_12e1c974:
- ch18/19 identical opening
- ch20 trailing "（全文约2350字）" annotation
- ch27 markdown header "# 第27章" leaking into body
- ch31→ch32 narrative continuation similarity
"""

from __future__ import annotations

import pytest

from src.novel.utils.chapter_sanitizer import sanitize_chapter, SanitizeResult


class TestMarkdownHeader:
    def test_strips_md_chapter_header(self):
        text = "# 第27章 三队布防\n林辰的脚步停在矿道口。"
        r = sanitize_chapter(text)
        assert "# 第27章" not in r.cleaned
        assert "林辰的脚步停在矿道口" in r.cleaned
        assert "strip_markdown_chapter_head" in r.actions

    def test_strips_double_hash_chapter(self):
        text = "## 第二十七章 标题\n正文"
        r = sanitize_chapter(text)
        assert "##" not in r.cleaned
        assert "正文" in r.cleaned

    def test_strips_chinese_numeral_chapter(self):
        text = "# 第二十七章 三队布防\n正文"
        r = sanitize_chapter(text)
        assert "第二十七章" not in r.cleaned

    def test_does_not_strip_inline_pound(self):
        """正文中的 # 不该被删（如对话符号）"""
        text = "林辰说：'#1 优先级'。"
        r = sanitize_chapter(text)
        assert "#1 优先级" in r.cleaned
        assert "strip_markdown_chapter_head" not in r.actions


class TestMetaAnnotations:
    def test_strips_wordcount_note(self):
        text = "正文结尾。\n（全文约2350字）"
        r = sanitize_chapter(text)
        assert "全文约" not in r.cleaned
        assert "strip_wordcount_note" in r.actions

    def test_strips_alternate_wordcount_format(self):
        text = "正文。(全文约 1900 字)"
        r = sanitize_chapter(text)
        assert "全文约" not in r.cleaned

    def test_strips_simple_wordcount(self):
        text = "正文。（约2500字）"
        r = sanitize_chapter(text)
        assert "约2500字" not in r.cleaned

    def test_strips_author_note(self):
        text = "正文。【作者注：这里需要后续修改】"
        r = sanitize_chapter(text)
        assert "作者注" not in r.cleaned
        assert "strip_author_note" in r.actions

    def test_strips_to_be_continued(self):
        text = "正文结尾。（待续）"
        r = sanitize_chapter(text)
        assert "待续" not in r.cleaned
        assert "strip_tbc_note" in r.actions

    def test_strips_unfinished_note(self):
        text = "正文。(未完待续)"
        r = sanitize_chapter(text)
        assert "未完待续" not in r.cleaned


class TestCodeFence:
    def test_strips_code_fence_lines(self):
        text = "正文\n```\n代码内容\n```\n更多正文"
        r = sanitize_chapter(text)
        assert "```" not in r.cleaned
        # 内容保留
        assert "代码内容" in r.cleaned
        assert "更多正文" in r.cleaned


class TestBlankLines:
    def test_collapses_excessive_blank_lines(self):
        text = "段一\n\n\n\n\n段二"
        r = sanitize_chapter(text)
        # 三个以上空行 → 折叠
        assert "\n\n\n" not in r.cleaned
        assert "段一" in r.cleaned and "段二" in r.cleaned

    def test_keeps_normal_double_newline(self):
        text = "段一\n\n段二"
        r = sanitize_chapter(text)
        assert r.cleaned == "段一\n\n段二"


class TestOpeningDuplicateDetection:
    def test_detects_identical_first_sentence(self):
        """ch18 → ch19 真实 bug: 首句一字不差"""
        prev = "矿道里潮气发冷，火把一靠近，岩壁就渗出细细水珠。然后林辰..."
        curr = "矿道里潮气发冷，火把一靠近，岩壁就渗出细细水珠。新一章发生..."
        r = sanitize_chapter(curr, prev_chapter_text=prev)
        assert r.opening_duplicate is True
        assert "opening_duplicate_flagged" in r.actions

    def test_detects_near_identical_opening(self):
        """ch21 → ch22 真实 bug"""
        prev = "晨光刺破西岭的雾气，照在辰风村简陋的木栅栏上。前一章。"
        curr = "晨光刺破西岭的雾气，照在辰风村简陋的木栅栏上。新一章。"
        r = sanitize_chapter(curr, prev_chapter_text=prev)
        assert r.opening_duplicate is True

    def test_detects_continuation_from_prev_end(self):
        """LLM 把上章结尾整段复制到本章开头（rare but seen in real bugs）"""
        prev_end = "灵气如潮水般涌入丹田，凌霄目光一凝，心中暗喜。"
        prev = "之前内容很多很多。" * 20 + prev_end
        curr = "灵气如潮水般涌入丹田，凌霄目光一凝，心中暗喜。新一章。"
        r = sanitize_chapter(curr, prev_chapter_text=prev)
        assert r.opening_duplicate is True

    def test_paraphrased_continuation_not_caught(self):
        """边界说明: 仅语义相似（无字面重叠）的延续 rule-based 抓不到，
        需要 embedding 才行。这里固化预期行为，便于未来升级时回归。"""
        prev_end = "林辰睁眼时，看见倒悬星辰组成的瞳孔。"
        prev = "前文。" * 20 + prev_end
        curr = "瞳孔深处的星辰褪去，视野重新聚焦于棚顶。"
        r = sanitize_chapter(curr, prev_chapter_text=prev)
        # rule-based 能力外，记录为 False 以便后续语义升级时翻转
        assert r.opening_duplicate is False

    def test_different_openings_pass(self):
        prev = "晨光刺破西岭的雾气，照在辰风村简陋的木栅栏上。"
        curr = "矿道深处的阴风卷着煤灰扑面而来，林辰皱眉。"
        r = sanitize_chapter(curr, prev_chapter_text=prev)
        assert r.opening_duplicate is False

    def test_no_prev_text_no_duplicate(self):
        r = sanitize_chapter("林辰睁开眼。")
        assert r.opening_duplicate is False

    def test_punctuation_diff_still_caught(self):
        """标点不同但实质相同的开头应被识别"""
        prev = "晨光刺破西岭的雾气，照在辰风村。"
        curr = "晨光，刺破西岭的雾气！照在辰风村……"
        r = sanitize_chapter(curr, prev_chapter_text=prev)
        assert r.opening_duplicate is True

    def test_short_text_does_not_trigger(self):
        """文本太短无法可靠判断"""
        prev = "短文。"
        curr = "另一段短。"
        r = sanitize_chapter(curr, prev_chapter_text=prev)
        assert r.opening_duplicate is False


class TestEmptyAndEdgeCases:
    def test_empty_text(self):
        r = sanitize_chapter("")
        assert r.cleaned == ""
        assert r.actions == []
        assert r.changed is False

    def test_clean_text_unchanged(self):
        text = "林辰站在矿场前，目光扫过远方。"
        r = sanitize_chapter(text)
        assert r.cleaned == text
        assert r.changed is False

    def test_combined_pollutants(self):
        """ch20 真实 case: markdown + meta + 多余空行"""
        text = (
            "# 第20章 西岭夜伏\n"
            "\n\n\n"
            "林辰带队悄然摸近破庙。\n\n"
            "一阵厮杀后，周彪伏诛。\n"
            "（全文约2350字）"
        )
        r = sanitize_chapter(text)
        assert "# 第20章" not in r.cleaned
        assert "全文约" not in r.cleaned
        assert "\n\n\n" not in r.cleaned
        assert "林辰带队悄然摸近破庙" in r.cleaned
        assert "一阵厮杀后，周彪伏诛" in r.cleaned
        # 至少触发 3 个 action
        assert len(r.actions) >= 3
