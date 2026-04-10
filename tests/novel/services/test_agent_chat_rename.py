"""Tests for rename_chapter tool and _extract_title_from_text fix."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.novel.services.agent_chat import AgentToolExecutor, TOOLS
from src.novel.pipeline import _extract_title_from_text, _sanitize_title


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def novel_workspace(tmp_path):
    """Create a minimal novel workspace with one chapter."""
    novel_id = "test_novel_001"
    novel_dir = tmp_path / "novels" / novel_id
    chapters_dir = novel_dir / "chapters"
    chapters_dir.mkdir(parents=True)

    # Create novel.json with outline
    novel_data = {
        "title": "测试小说",
        "genre": "玄幻",
        "status": "in_progress",
        "current_chapter": 17,
        "target_words": 100000,
        "outline": {
            "chapters": [
                {"chapter_number": 17, "title": "旧标题十七章"},
                {"chapter_number": 18, "title": "第十八章占位"},
            ]
        },
        "characters": [],
    }
    (novel_dir / "novel.json").write_text(
        json.dumps(novel_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Create chapter_017.json
    chapter_data = {
        "chapter_number": 17,
        "title": "旧标题十七章",
        "full_text": "这是第十七章的正文内容。主角来到了一个新的地方。",
        "word_count": 23,
    }
    (chapters_dir / "chapter_017.json").write_text(
        json.dumps(chapter_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return tmp_path, novel_id


# ---------------------------------------------------------------------------
# rename_chapter tool tests
# ---------------------------------------------------------------------------


class TestRenameChapterTool:
    """Tests for the rename_chapter tool."""

    def test_tool_registered_in_tools_list(self):
        """rename_chapter should be in the TOOLS list."""
        names = {t["name"] for t in TOOLS}
        assert "rename_chapter" in names

    def test_tool_has_correct_parameters(self):
        """rename_chapter should require chapter_number and new_title."""
        tool = next(t for t in TOOLS if t["name"] == "rename_chapter")
        params = tool["parameters"]
        assert "chapter_number" in params
        assert params["chapter_number"]["type"] == "integer"
        assert "new_title" in params
        assert params["new_title"]["type"] == "string"

    def test_rename_changes_title_in_json(self, novel_workspace):
        """Renaming should update the title in the chapter JSON file."""
        workspace, novel_id = novel_workspace
        executor = AgentToolExecutor(str(workspace), novel_id)

        result = executor.execute("rename_chapter", {
            "chapter_number": 17,
            "new_title": "兵煞初锻",
        })

        assert result.get("success") is True
        assert result["old_title"] == "旧标题十七章"
        assert result["new_title"] == "兵煞初锻"
        assert result["chapter_number"] == 17

        # Verify the file was updated
        chapter_path = workspace / "novels" / novel_id / "chapters" / "chapter_017.json"
        data = json.loads(chapter_path.read_text(encoding="utf-8"))
        assert data["title"] == "兵煞初锻"
        # Content should be untouched
        assert "主角来到了一个新的地方" in data["full_text"]

    def test_rename_updates_outline(self, novel_workspace):
        """Renaming should also update the title in the outline."""
        workspace, novel_id = novel_workspace
        executor = AgentToolExecutor(str(workspace), novel_id)

        executor.execute("rename_chapter", {
            "chapter_number": 17,
            "new_title": "新的标题",
        })

        # Check outline in novel.json
        novel_json = workspace / "novels" / novel_id / "novel.json"
        novel_data = json.loads(novel_json.read_text(encoding="utf-8"))
        outline_chapters = novel_data["outline"]["chapters"]
        ch17 = next(c for c in outline_chapters if c["chapter_number"] == 17)
        assert ch17["title"] == "新的标题"

        # Chapter 18 should be unchanged
        ch18 = next(c for c in outline_chapters if c["chapter_number"] == 18)
        assert ch18["title"] == "第十八章占位"

    def test_rename_nonexistent_chapter_returns_error(self, novel_workspace):
        """Renaming a non-existent chapter should return an error."""
        workspace, novel_id = novel_workspace
        executor = AgentToolExecutor(str(workspace), novel_id)

        result = executor.execute("rename_chapter", {
            "chapter_number": 99,
            "new_title": "不存在的章节",
        })

        assert "error" in result
        assert "99" in result["error"]

    def test_rename_preserves_other_chapter_fields(self, novel_workspace):
        """Renaming should only change title, not other fields."""
        workspace, novel_id = novel_workspace
        executor = AgentToolExecutor(str(workspace), novel_id)

        executor.execute("rename_chapter", {
            "chapter_number": 17,
            "new_title": "天地初开",
        })

        chapter_path = workspace / "novels" / novel_id / "chapters" / "chapter_017.json"
        data = json.loads(chapter_path.read_text(encoding="utf-8"))
        assert data["title"] == "天地初开"
        assert data["chapter_number"] == 17
        assert data["word_count"] == 23
        assert data["full_text"] == "这是第十七章的正文内容。主角来到了一个新的地方。"


# ---------------------------------------------------------------------------
# _extract_title_from_text tests
# ---------------------------------------------------------------------------


class TestExtractTitleFromText:
    """Tests for the fixed _extract_title_from_text function."""

    def test_skips_markdown_headers(self):
        """Should not pick up lines starting with #."""
        text = "# 第16章 兵煞初锻\n灵气如潮水般涌入丹田。凌霄目光一凝，心中暗喜。"
        title = _extract_title_from_text(text, 17)
        assert not title.startswith("#")
        assert "第16章" not in title

    def test_skips_chapter_number_headers(self):
        """Should not pick up lines like '第16章 xxx'."""
        text = "第16章 兵煞初锻\n灵气涌入丹田，凌霄心中暗喜。"
        title = _extract_title_from_text(text, 17)
        assert "第16章" not in title

    def test_extracts_from_body_text(self):
        """Should extract title from actual body text, not headers."""
        text = "# 第16章 兵煞初锻\n第16章 兵煞初锻\n灵气如潮。凌霄目光一凝。"
        title = _extract_title_from_text(text, 17)
        # Both header lines are skipped; "灵气如潮" (4 chars) is the first valid match
        assert title == "灵气如潮"

    def test_empty_text_returns_default(self):
        """Empty text should return default '第N章'."""
        assert _extract_title_from_text("", 5) == "第5章"
        assert _extract_title_from_text("   \n  \n  ", 3) == "第3章"

    def test_skips_dialogue_opener_line(self):
        """Lines that start with a dialogue opener are skipped (Bug 2 fix).

        Previously the helper stripped quotes and kept the content. That
        produced bad "titles" like "没人说话" or "别开——" — dialogue
        fragments rather than narrative summaries. Now such lines are
        skipped in favor of the next narrative line or outline fallback.
        """
        text = '"命运的转折"。改变了一切，世界不再相同。'
        title = _extract_title_from_text(text, 1)
        # Dialogue opener line is skipped; falls through to "改变了一切"
        assert title != "命运的转折"
        # Either extracts narrative or falls through to placeholder
        assert title == "改变了一切" or title == "第1章"

    def test_all_lines_are_headers_returns_default(self):
        """If all first 5 lines are headers, should return default."""
        text = "# 第1章 开端\n第2章 续篇\n第3章 高潮\n第4章 转折\n第5章 结局"
        title = _extract_title_from_text(text, 10)
        assert title == "第10章"

    def test_normal_text_extraction(self):
        """Normal text without headers should work as before."""
        text = "风雪漫天，少年踏雪而来。"
        title = _extract_title_from_text(text, 1)
        # "风雪漫天" is 4 chars, should match
        assert len(title) >= 4
        assert len(title) <= 12

    def test_fallback_to_truncation(self):
        """Long lines without short sentences should be truncated.

        After Bug 2 fix, the cap is 12 chars (relaxed from the old 10).
        """
        text = "# 第1章 标题\n这是一段非常长的没有任何标点的文字内容需要被截断到合适的长度"
        title = _extract_title_from_text(text, 2)
        assert len(title) <= 12
        assert not title.startswith("#")

    # --- New sanitization tests ---

    def test_rejects_escaped_newlines_in_text(self):
        r"""Titles with literal \n escape sequences must be rejected."""
        text = '\\n\\n"我不来不行，这是宿命。"他说。'
        title = _extract_title_from_text(text, 22)
        assert "\\n" not in title
        assert title != ""

    def test_rejects_prompt_instruction_fragments(self):
        """Lines that look like prompt instructions (字数, 场景, etc.) are rejected."""
        text = "\\n字数：800字左右\\n第一幕：矿洞深处。少年凌霄抬起头。"
        title = _extract_title_from_text(text, 23)
        assert "字数" not in title
        assert "左右" not in title

    def test_rejects_leading_quote_dialogue(self):
        """Titles starting with dialogue quotes are stripped/rejected."""
        text = '"矿下先锁死！"他大喝一声。灵力涌动。'
        title = _extract_title_from_text(text, 24)
        # Should not start with a quote character
        assert not title.startswith('"')
        assert not title.startswith("\u201c")

    def test_text_with_only_prompt_fragments(self):
        """If ALL lines are prompt fragments, fallback to default title."""
        text = "字数：800字左右\n场景描写要求：\n注意节奏控制"
        title = _extract_title_from_text(text, 5)
        assert title == "第5章"

    def test_real_garbage_case_backslash_n(self):
        r"""Real-world case: '\n\n"我不来不行' should produce clean title."""
        # Simulate LLM returning raw \n in text
        text = '\n\n"我不来不行，矿脉已经快要枯竭了。"少年叹息。\n灵气如丝般稀薄。'
        title = _extract_title_from_text(text, 22)
        assert "\n" not in title
        assert len(title) >= 2


# ---------------------------------------------------------------------------
# _sanitize_title tests
# ---------------------------------------------------------------------------


class TestSanitizeTitle:
    """Tests for the _sanitize_title helper function."""

    def test_strips_escaped_newlines(self):
        assert _sanitize_title("\\n\\n暗夜降临", 1) == "暗夜降临"

    def test_rejects_dialogue_opener_titles(self):
        """After Bug 2 fix, titles starting with dialogue quotes are rejected.

        Previously the helper stripped surrounding quotes and returned the
        content as the title. That produced "titles" like "别开——" when the
        LLM accidentally output a dialogue fragment. The new contract is to
        treat dialogue-opener titles as invalid and let the downstream
        fallback pick a narrative phrase or an outline-derived title.
        """
        assert _sanitize_title("\u201c命运之门\u201d", 1) == "第1章"
        assert _sanitize_title('"开端"', 1) == "第1章"

    def test_rejects_prompt_keywords(self):
        assert _sanitize_title("字数控制在800", 5) == "第5章"
        assert _sanitize_title("场景一：矿洞", 3) == "第3章"
        assert _sanitize_title("注意力集中", 2) == "第2章"

    def test_rejects_too_long(self):
        """Cap relaxed from 15 to 25 chars (Bug 2 fix).

        Legitimate Chinese chapter titles can run up to 15-20 chars — the
        old 15-char cap rejected valid outputs. The new cap is 25 chars,
        above which we assume a full sentence has leaked.
        """
        # 26 chars — now rejected
        assert _sanitize_title("一" * 26, 1) == "第1章"
        # 20 chars — now passes (used to be rejected)
        mid_len = "一二三四五六七八九十一二三四五六七八九二"  # 20 chars
        assert _sanitize_title(mid_len, 1) == mid_len

    def test_rejects_too_short(self):
        assert _sanitize_title("a", 1) == "第1章"
        assert _sanitize_title("", 1) == "第1章"

    def test_passes_valid_title(self):
        assert _sanitize_title("暗夜降临", 1) == "暗夜降临"
        assert _sanitize_title("龙吟九天", 3) == "龙吟九天"

    def test_strips_actual_newlines(self):
        assert _sanitize_title("\n暗夜\n", 1) == "暗夜"

    def test_rejects_left_right_pattern(self):
        """'左右' is a prompt meta-word (e.g., '800字左右')."""
        assert _sanitize_title("800字左右", 1) == "第1章"
