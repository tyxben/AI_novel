"""Tests for chapter text sanitizer."""
from src.novel.agents.writer import _sanitize_chapter_text


class TestSanitizeChapterText:
    def test_strips_system_brackets(self):
        text = "林辰看向天空。【系统】检测到任务完成。他笑了。"
        result = _sanitize_chapter_text(text)
        assert "【系统】" not in result
        assert "林辰看向天空" in result
        assert "他笑了" in result

    def test_strips_stat_changes(self):
        text = "钱七点头。\n【钱七忠诚度：71→79】\n他离开了。"
        result = _sanitize_chapter_text(text)
        assert "忠诚度：71→79" not in result
        assert "钱七点头" in result
        assert "他离开了" in result

    def test_preserves_allowlisted_marker(self):
        text = "【叮！】系统提示音响起。林辰皱眉。"
        result = _sanitize_chapter_text(text)
        assert "【叮！】" in result
        assert "林辰皱眉" in result

    def test_strips_value_changes(self):
        text = "他完成了锻体。\n【兵煞值+8】\n身体一阵发热。"
        result = _sanitize_chapter_text(text)
        assert "兵煞值+8" not in result
        assert "身体一阵发热" in result

    def test_collapses_excess_newlines(self):
        text = "段一。\n\n\n\n段二。"
        result = _sanitize_chapter_text(text)
        assert "\n\n\n" not in result

    def test_empty_input(self):
        assert _sanitize_chapter_text("") == ""
        assert _sanitize_chapter_text(None) == None or _sanitize_chapter_text(None) == ""

    def test_no_system_content_unchanged(self):
        text = "林辰拔出长剑，朝山下走去。月光洒在剑刃上。"
        result = _sanitize_chapter_text(text)
        assert result == text
