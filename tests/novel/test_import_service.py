"""ImportService 单元测试

覆盖：
- 章节自动分割（中文/英文/无标题）
- LLM 角色提取
- LLM 世界观提取
- 项目创建及文件持久化
- 边界条件（空文件、无章节标题、不存在路径）
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.novel.services.import_service import (
    ImportService,
    _extract_json_array,
    _extract_json_obj,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    content: str
    model: str = "fake-model"
    usage: dict | None = None


def _make_llm(response_content: str) -> MagicMock:
    """Create a mock LLM client returning the given content."""
    llm = MagicMock()
    llm.chat.return_value = FakeLLMResponse(content=response_content)
    return llm


SAMPLE_TEXT_WITH_CHAPTERS = """第一章 初出茅庐

少年陈风站在山门前，望着远处的群山出神。
师父说过，修炼之路漫漫，需要百折不挠的毅力。

第二章 意外之喜

一块奇异的玉石从天而降，陈风捡起来感到一阵温暖。
玉石中蕴含着强大的力量。

第三章 对决强敌

黑衣人出现在陈风面前，冷笑道："交出玉石！"
陈风握紧拳头，毫不退缩。
"""

SAMPLE_TEXT_ENGLISH_CHAPTERS = """Chapter 1: The Beginning

John stood at the edge of the world, looking out over the vast sea.

Chapter 2: The Journey

He set out on his journey, not knowing what lay ahead.

Chapter 3: The End

At last, John found what he was looking for.
"""

SAMPLE_TEXT_NO_CHAPTERS = """这是一段没有章节分隔的连续文本。
主角在城市中游荡，寻找失落的记忆。
他遇到了一个神秘的女子，她似乎知道一切。
但她只是微笑着，不愿透露任何信息。
"""

CHARACTERS_JSON = json.dumps({
    "characters": [
        {"name": "陈风", "role": "主角", "description": "少年修仙者", "personality": "勇敢坚韧"},
        {"name": "黑衣人", "role": "反派", "description": "神秘强敌", "personality": "冷酷无情"},
    ]
})

WORLD_SETTING_JSON = json.dumps({
    "era": "架空",
    "location": "九州大陆",
    "rules": ["修炼境界分九重", "天地灵气为修炼之本"],
    "terms": {"灵石": "蕴含灵气的石头", "丹药": "修炼辅助药物"},
})


# ---------------------------------------------------------------------------
# JSON extraction helper tests
# ---------------------------------------------------------------------------


class TestJsonExtraction:
    """Test _extract_json_obj and _extract_json_array helpers."""

    def test_extract_json_obj_valid(self):
        result = _extract_json_obj('{"key": "value"}')
        assert result == {"key": "value"}

    def test_extract_json_obj_with_surrounding_text(self):
        result = _extract_json_obj('Here is the result: {"key": "value"} done.')
        assert result == {"key": "value"}

    def test_extract_json_obj_none(self):
        assert _extract_json_obj(None) is None

    def test_extract_json_obj_empty(self):
        assert _extract_json_obj("") is None

    def test_extract_json_obj_invalid(self):
        assert _extract_json_obj("not json at all") is None

    def test_extract_json_array_valid(self):
        result = _extract_json_array('[{"name": "a"}]')
        assert result == [{"name": "a"}]

    def test_extract_json_array_from_object(self):
        result = _extract_json_array('{"characters": [{"name": "a"}]}')
        assert result == [{"name": "a"}]

    def test_extract_json_array_none(self):
        assert _extract_json_array(None) is None

    def test_extract_json_array_with_surrounding_text(self):
        result = _extract_json_array('Result: [{"name": "a"}] end.')
        assert result == [{"name": "a"}]


# ---------------------------------------------------------------------------
# Chapter splitting tests
# ---------------------------------------------------------------------------


class TestChapterSplitting:
    """Test automatic chapter detection and splitting."""

    @pytest.fixture()
    def svc(self):
        return ImportService(llm_client=_make_llm("{}"))

    def test_split_chinese_chapters(self, svc):
        chapters = svc.split_chapters(SAMPLE_TEXT_WITH_CHAPTERS)
        assert len(chapters) == 3
        assert chapters[0]["chapter_number"] == 1
        assert "初出茅庐" in chapters[0]["title"]
        assert "陈风" in chapters[0]["text"]
        assert chapters[1]["chapter_number"] == 2
        assert "意外之喜" in chapters[1]["title"]
        assert chapters[2]["chapter_number"] == 3
        assert "对决强敌" in chapters[2]["title"]

    def test_split_english_chapters(self, svc):
        chapters = svc.split_chapters(SAMPLE_TEXT_ENGLISH_CHAPTERS)
        assert len(chapters) == 3
        assert "Beginning" in chapters[0]["title"]
        assert "Journey" in chapters[1]["title"]
        assert "End" in chapters[2]["title"]

    def test_no_chapter_titles_returns_single(self, svc):
        chapters = svc.split_chapters(SAMPLE_TEXT_NO_CHAPTERS)
        assert len(chapters) == 1
        assert chapters[0]["chapter_number"] == 1
        assert "游荡" in chapters[0]["text"]

    def test_split_empty_text(self, svc):
        # Empty string treated as no chapters
        chapters = svc.split_chapters("")
        assert len(chapters) == 1
        assert chapters[0]["text"] == ""

    def test_split_single_chapter_marker(self, svc):
        """A single chapter marker is not enough (need >= 2 matches)."""
        text = "第一章 开始\n\n一些内容。"
        chapters = svc.split_chapters(text)
        # Only 1 match: falls back to single chapter
        assert len(chapters) == 1

    def test_split_numeric_chapters(self, svc):
        text = "1. 序章\n\n内容一。\n\n2. 初遇\n\n内容二。\n\n3. 离别\n\n内容三。\n"
        chapters = svc.split_chapters(text)
        assert len(chapters) == 3
        assert "序章" in chapters[0]["title"]
        assert "初遇" in chapters[1]["title"]

    def test_split_chinese_with_numbers(self, svc):
        """Test numeric Chinese chapter markers: 第1章, 第2章."""
        text = "第1章 出发\n\n故事开始。\n\n第2章 途中\n\n路上遇到了困难。\n"
        chapters = svc.split_chapters(text)
        assert len(chapters) == 2
        assert "出发" in chapters[0]["title"]
        assert "途中" in chapters[1]["title"]

    def test_chapter_text_content(self, svc):
        """Verify each chapter's text does not include the next chapter's title."""
        chapters = svc.split_chapters(SAMPLE_TEXT_WITH_CHAPTERS)
        assert "第二章" not in chapters[0]["text"]
        assert "第三章" not in chapters[1]["text"]


# ---------------------------------------------------------------------------
# LLM extraction tests
# ---------------------------------------------------------------------------


class TestCharacterExtraction:
    """Test LLM-based character extraction."""

    def test_extract_characters_success(self):
        llm = _make_llm(CHARACTERS_JSON)
        svc = ImportService(llm)
        result = svc.extract_characters("some summary", "玄幻")
        assert len(result) == 2
        assert result[0]["name"] == "陈风"
        assert result[1]["name"] == "黑衣人"
        llm.chat.assert_called_once()

    def test_extract_characters_llm_returns_garbage(self):
        llm = _make_llm("I don't know how to do JSON")
        svc = ImportService(llm)
        result = svc.extract_characters("summary", "玄幻")
        assert result == []
        # Should have retried MAX_RETRIES times
        assert llm.chat.call_count == ImportService.MAX_RETRIES

    def test_extract_characters_llm_exception(self):
        llm = MagicMock()
        llm.chat.side_effect = RuntimeError("API down")
        svc = ImportService(llm)
        result = svc.extract_characters("summary", "玄幻")
        assert result == []

    def test_extract_characters_partial_json(self):
        """LLM returns JSON with extra text around it."""
        content = f"Here are the characters:\n{CHARACTERS_JSON}\nDone!"
        llm = _make_llm(content)
        svc = ImportService(llm)
        result = svc.extract_characters("summary", "玄幻")
        assert len(result) == 2


class TestWorldSettingExtraction:
    """Test LLM-based world setting extraction."""

    def test_extract_world_setting_success(self):
        llm = _make_llm(WORLD_SETTING_JSON)
        svc = ImportService(llm)
        result = svc.extract_world_setting("some summary", "玄幻")
        assert result["era"] == "架空"
        assert result["location"] == "九州大陆"
        assert len(result["rules"]) == 2
        assert "灵石" in result["terms"]

    def test_extract_world_setting_llm_returns_garbage(self):
        llm = _make_llm("no valid json here")
        svc = ImportService(llm)
        result = svc.extract_world_setting("summary", "玄幻")
        # Should return defaults
        assert result["era"] == "架空"
        assert result["location"] == "未知"
        assert result["rules"] == []

    def test_extract_world_setting_llm_exception(self):
        llm = MagicMock()
        llm.chat.side_effect = RuntimeError("API down")
        svc = ImportService(llm)
        result = svc.extract_world_setting("summary", "玄幻")
        assert result["era"] == "架空"


# ---------------------------------------------------------------------------
# Full import pipeline tests
# ---------------------------------------------------------------------------


class TestImportExistingDraft:
    """Test the complete import_existing_draft flow."""

    @pytest.fixture()
    def tmp_workspace(self, tmp_path):
        return str(tmp_path / "ws")

    @pytest.fixture()
    def sample_file(self, tmp_path):
        f = tmp_path / "novel.txt"
        f.write_text(SAMPLE_TEXT_WITH_CHAPTERS, encoding="utf-8")
        return str(f)

    @pytest.fixture()
    def svc(self):
        """ImportService with LLM that returns valid characters and world."""
        llm = MagicMock()
        call_count = 0

        def side_effect(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            # First call is character extraction, second is world setting
            if call_count <= ImportService.MAX_RETRIES:
                return FakeLLMResponse(content=CHARACTERS_JSON)
            return FakeLLMResponse(content=WORLD_SETTING_JSON)

        llm.chat.side_effect = side_effect
        return ImportService(llm)

    def test_import_creates_project_directory(self, svc, sample_file, tmp_workspace):
        result = svc.import_existing_draft(
            file_path=sample_file,
            genre="玄幻",
            workspace=tmp_workspace,
        )
        project_path = Path(result["workspace"])
        assert project_path.exists()
        assert (project_path / "novel.json").exists()

    def test_import_returns_correct_chapter_count(self, svc, sample_file, tmp_workspace):
        result = svc.import_existing_draft(
            file_path=sample_file,
            genre="玄幻",
            workspace=tmp_workspace,
        )
        assert result["total_chapters"] == 3
        assert len(result["chapters"]) == 3

    def test_import_saves_chapter_files(self, svc, sample_file, tmp_workspace):
        result = svc.import_existing_draft(
            file_path=sample_file,
            genre="玄幻",
            workspace=tmp_workspace,
        )
        chapters_dir = Path(result["workspace"]) / "chapters"
        assert chapters_dir.exists()
        # Should have 3 JSON + 3 TXT files
        json_files = list(chapters_dir.glob("*.json"))
        txt_files = list(chapters_dir.glob("*.txt"))
        assert len(json_files) == 3
        assert len(txt_files) == 3

    def test_import_novel_json_structure(self, svc, sample_file, tmp_workspace):
        result = svc.import_existing_draft(
            file_path=sample_file,
            genre="玄幻",
            workspace=tmp_workspace,
        )
        novel_json = Path(result["workspace"]) / "novel.json"
        with open(novel_json, encoding="utf-8") as f:
            data = json.load(f)
        assert data["genre"] == "玄幻"
        assert data["status"] == "writing"
        assert "outline" in data
        assert len(data["outline"]["chapters"]) == 3

    def test_import_returns_characters(self, svc, sample_file, tmp_workspace):
        result = svc.import_existing_draft(
            file_path=sample_file,
            genre="玄幻",
            workspace=tmp_workspace,
        )
        assert len(result["characters"]) >= 1

    def test_import_returns_world_setting(self, svc, sample_file, tmp_workspace):
        result = svc.import_existing_draft(
            file_path=sample_file,
            genre="玄幻",
            workspace=tmp_workspace,
        )
        ws = result["world_setting"]
        assert "era" in ws

    def test_import_calculates_total_words(self, svc, sample_file, tmp_workspace):
        result = svc.import_existing_draft(
            file_path=sample_file,
            genre="玄幻",
            workspace=tmp_workspace,
        )
        assert result["total_words"] > 0

    def test_import_no_auto_split(self, svc, sample_file, tmp_workspace):
        result = svc.import_existing_draft(
            file_path=sample_file,
            genre="玄幻",
            auto_split=False,
            workspace=tmp_workspace,
        )
        assert result["total_chapters"] == 1
        assert len(result["chapters"]) == 1

    # --- Boundary conditions ---

    def test_import_file_not_found(self, svc, tmp_workspace):
        with pytest.raises(FileNotFoundError):
            svc.import_existing_draft(
                file_path="/nonexistent/path/novel.txt",
                workspace=tmp_workspace,
            )

    def test_import_empty_file(self, svc, tmp_path, tmp_workspace):
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="文件内容为空"):
            svc.import_existing_draft(
                file_path=str(empty),
                workspace=tmp_workspace,
            )

    def test_import_whitespace_only_file(self, svc, tmp_path, tmp_workspace):
        ws_file = tmp_path / "whitespace.txt"
        ws_file.write_text("   \n\n\t  ", encoding="utf-8")
        with pytest.raises(ValueError, match="文件内容为空"):
            svc.import_existing_draft(
                file_path=str(ws_file),
                workspace=tmp_workspace,
            )

    def test_import_text_no_chapters(self, tmp_path, tmp_workspace):
        """Text without chapter markers becomes single chapter."""
        f = tmp_path / "plain.txt"
        f.write_text(SAMPLE_TEXT_NO_CHAPTERS, encoding="utf-8")
        llm = _make_llm(CHARACTERS_JSON)
        # For world setting call
        responses = [
            FakeLLMResponse(content=CHARACTERS_JSON),
            FakeLLMResponse(content=WORLD_SETTING_JSON),
        ]
        llm.chat.side_effect = responses
        svc = ImportService(llm)
        result = svc.import_existing_draft(
            file_path=str(f),
            genre="都市",
            workspace=tmp_workspace,
        )
        assert result["total_chapters"] == 1


# ---------------------------------------------------------------------------
# Summary truncation test
# ---------------------------------------------------------------------------


class TestMakeSummary:
    """Test _make_summary_for_extraction helper."""

    def test_short_text_unchanged(self):
        svc = ImportService(_make_llm("{}"))
        result = svc._make_summary_for_extraction("short text")
        assert result == "short text"

    def test_long_text_truncated(self):
        svc = ImportService(_make_llm("{}"))
        long_text = "a" * 5000
        result = svc._make_summary_for_extraction(long_text)
        assert len(result) < len(long_text)
        assert "[...中间省略...]" in result
        # First 2000 chars preserved
        assert result.startswith("a" * 2000)
