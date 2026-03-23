"""SettingImpactAnalyzer 单元测试"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.novel.services.setting_impact_analyzer import SettingImpactAnalyzer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_novel_data(
    current_chapter: int = 5,
    num_outline_chapters: int = 10,
) -> dict:
    """生成一个简化的 novel_data dict（模拟 FileManager.load_novel 返回值）。"""
    chapters = []
    for i in range(1, num_outline_chapters + 1):
        chapters.append(
            {
                "chapter_number": i,
                "title": f"第{i}章 测试标题",
                "goal": f"第{i}章的目标",
                "chapter_summary": f"第{i}章摘要文本",
                "key_events": [f"事件{i}"],
                "estimated_words": 2500,
                "mood": "蓄力",
            }
        )
    return {
        "novel_id": "test-novel-001",
        "current_chapter": current_chapter,
        "outline": {"chapters": chapters},
        "world_setting": {"era": "古代", "location": "中原"},
        "characters": [{"name": "主角", "role": "protagonist"}],
        "style_subcategory": "webnovel.shuangwen",
    }


def _make_llm_response(content: str) -> MagicMock:
    """构造 LLM response mock。"""
    resp = MagicMock()
    resp.content = content
    return resp


def _make_analyzer(
    llm_response: str | None = None,
    llm_side_effect: Exception | None = None,
    chapter_texts: dict[int, str | None] | None = None,
) -> tuple[SettingImpactAnalyzer, MagicMock, MagicMock]:
    """构造 analyzer + mock llm + mock file_manager。

    Returns:
        (analyzer, llm_mock, fm_mock)
    """
    llm = MagicMock()
    if llm_side_effect:
        llm.chat.side_effect = llm_side_effect
    elif llm_response is not None:
        llm.chat.return_value = _make_llm_response(llm_response)
    else:
        llm.chat.return_value = _make_llm_response("{}")

    fm = MagicMock()
    texts = chapter_texts or {}
    fm.load_chapter_text.side_effect = lambda nid, ch: texts.get(ch)

    analyzer = SettingImpactAnalyzer(llm, fm)
    return analyzer, llm, fm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnalyzeImpactNoChapters:
    """current_chapter=0 时直接返回无影响。"""

    def test_returns_no_impact(self):
        analyzer, llm, _ = _make_analyzer()
        novel_data = _make_novel_data(current_chapter=0)

        result = analyzer.analyze_impact(
            novel_id="test-001",
            novel_data=novel_data,
            modified_field="world_setting",
            old_value='{"era": "古代"}',
            new_value='{"era": "现代"}',
        )

        assert result["affected_chapters"] == []
        assert result["conflicts"] == []
        assert result["severity"] == "low"
        assert "尚未写" in result["summary"]
        # LLM should NOT be called
        llm.chat.assert_not_called()


class TestAnalyzeImpactNormal:
    """正常 LLM 返回 JSON 时解析正确。"""

    def test_parses_llm_response(self):
        llm_json = json.dumps(
            {
                "affected_chapters": [2, 4],
                "conflicts": [
                    {
                        "chapter_number": 2,
                        "conflict_text": "主角使用了古代兵器",
                        "reason": "新设定改为现代背景，古代兵器不合理",
                        "suggested_fix": "将兵器替换为现代武器",
                    },
                    {
                        "chapter_number": 4,
                        "conflict_text": "马车出行",
                        "reason": "现代背景不应该用马车",
                        "suggested_fix": "改为汽车",
                    },
                ],
                "severity": "high",
                "summary": "时代背景变更影响了2章内容",
            },
            ensure_ascii=False,
        )
        analyzer, llm, _ = _make_analyzer(
            llm_response=llm_json,
            chapter_texts={i: f"第{i}章正文内容..." for i in range(1, 6)},
        )
        novel_data = _make_novel_data(current_chapter=5)

        result = analyzer.analyze_impact(
            novel_id="test-001",
            novel_data=novel_data,
            modified_field="world_setting",
            old_value='{"era": "古代"}',
            new_value='{"era": "现代"}',
        )

        assert result["affected_chapters"] == [2, 4]
        assert len(result["conflicts"]) == 2
        assert result["conflicts"][0]["chapter_number"] == 2
        assert "古代兵器" in result["conflicts"][0]["conflict_text"]
        assert result["severity"] == "high"
        assert result["summary"] == "时代背景变更影响了2章内容"
        assert result["modified_field"] == "world_setting"

        # LLM was called once
        llm.chat.assert_called_once()
        call_kwargs = llm.chat.call_args
        assert call_kwargs.kwargs.get("temperature") == 0.3 or call_kwargs[1].get("temperature") == 0.3


class TestAnalyzeImpactLLMError:
    """LLM 异常时返回安全默认值。"""

    def test_returns_empty_on_llm_error(self):
        analyzer, _, _ = _make_analyzer(
            llm_side_effect=RuntimeError("API timeout"),
            chapter_texts={1: "some text"},
        )
        novel_data = _make_novel_data(current_chapter=1)

        result = analyzer.analyze_impact(
            novel_id="test-001",
            novel_data=novel_data,
            modified_field="characters",
            old_value="old",
            new_value="new",
        )

        assert result["affected_chapters"] == []
        assert result["conflicts"] == []
        assert result["severity"] == "low"
        assert "AI 分析失败" in result["summary"]


class TestAnalyzeImpactInvalidJSON:
    """LLM 返回非 JSON 时容错处理。"""

    def test_handles_garbage_output(self):
        analyzer, _, _ = _make_analyzer(
            llm_response="这不是 JSON，我无法分析",
            chapter_texts={1: "text"},
        )
        novel_data = _make_novel_data(current_chapter=1)

        result = analyzer.analyze_impact(
            novel_id="test-001",
            novel_data=novel_data,
            modified_field="outline",
            old_value="old",
            new_value="new",
        )

        assert result["affected_chapters"] == []
        assert result["conflicts"] == []
        assert result["severity"] == "medium"  # default
        assert result["summary"] == ""

    def test_extracts_json_from_markdown(self):
        """LLM 用 markdown 包裹 JSON 时也能解析。"""
        inner_json = json.dumps(
            {
                "affected_chapters": [3],
                "conflicts": [
                    {
                        "chapter_number": 3,
                        "conflict_text": "x",
                        "reason": "y",
                        "suggested_fix": "z",
                    }
                ],
                "severity": "medium",
                "summary": "ok",
            }
        )
        wrapped = f"根据分析，结果如下：\n```json\n{inner_json}\n```"
        analyzer, _, _ = _make_analyzer(
            llm_response=wrapped,
            chapter_texts={i: f"text{i}" for i in range(1, 6)},
        )
        novel_data = _make_novel_data(current_chapter=5)

        result = analyzer.analyze_impact(
            novel_id="test-001",
            novel_data=novel_data,
            modified_field="world_setting",
            old_value="old",
            new_value="new",
        )

        assert result["affected_chapters"] == [3]
        assert len(result["conflicts"]) == 1


class TestAnalyzeImpactFiltersInvalidChapters:
    """过滤超出范围的章节号。"""

    def test_filters_out_of_range(self):
        llm_json = json.dumps(
            {
                "affected_chapters": [0, 1, 3, 99, -1, "abc"],
                "conflicts": [
                    {
                        "chapter_number": 0,
                        "conflict_text": "x",
                        "reason": "out of range low",
                    },
                    {
                        "chapter_number": 3,
                        "conflict_text": "x",
                        "reason": "valid",
                    },
                    {
                        "chapter_number": 99,
                        "conflict_text": "x",
                        "reason": "out of range high",
                    },
                ],
                "severity": "high",
                "summary": "test",
            }
        )
        analyzer, _, _ = _make_analyzer(
            llm_response=llm_json,
            chapter_texts={i: f"text{i}" for i in range(1, 6)},
        )
        novel_data = _make_novel_data(current_chapter=5)

        result = analyzer.analyze_impact(
            novel_id="test-001",
            novel_data=novel_data,
            modified_field="characters",
            old_value="old",
            new_value="new",
        )

        # Only chapters 1 and 3 are valid (1 <= ch <= 5)
        assert 0 not in result["affected_chapters"]
        assert 99 not in result["affected_chapters"]
        assert -1 not in result["affected_chapters"]
        assert 1 in result["affected_chapters"]
        assert 3 in result["affected_chapters"]

        # Conflicts: only chapter 3 is valid (0 is out of range, 99 is out)
        conflict_chapters = [c["chapter_number"] for c in result["conflicts"]]
        assert 0 not in conflict_chapters
        assert 99 not in conflict_chapters
        assert 3 in conflict_chapters


class TestGenerateChaptersSummary:
    """验证摘要生成逻辑。"""

    def test_normal_summary(self):
        analyzer, _, fm = _make_analyzer(
            chapter_texts={
                1: "这是第一章的内容，讲述了主角的出场。" * 10,
                2: "第二章内容。",
                3: "第三章内容。",
            }
        )
        novel_data = _make_novel_data(current_chapter=3)

        summary = analyzer._generate_chapters_summary("test-001", novel_data)

        assert "第1章" in summary
        assert "第2章" in summary
        assert "第3章" in summary
        assert "目标:" in summary or "目标: " in summary
        assert "摘要:" in summary or "摘要: " in summary
        # 验证 FileManager 被调用了 3 次
        assert fm.load_chapter_text.call_count == 3

    def test_truncates_at_40_chapters(self):
        texts = {i: f"章节{i}内容" for i in range(1, 51)}
        analyzer, _, fm = _make_analyzer(chapter_texts=texts)
        novel_data = _make_novel_data(
            current_chapter=50, num_outline_chapters=50
        )

        summary = analyzer._generate_chapters_summary("test-001", novel_data)

        assert "仅显示前40章" in summary
        # Should have called load_chapter_text 40 times (stops at ch 40)
        assert fm.load_chapter_text.call_count == 40

    def test_no_chapters(self):
        analyzer, _, _ = _make_analyzer()
        novel_data = _make_novel_data(current_chapter=0)

        summary = analyzer._generate_chapters_summary("test-001", novel_data)

        assert summary == "（暂无已写章节）"

    def test_missing_chapter_text(self):
        """章节文本不存在时优雅降级。"""
        analyzer, _, _ = _make_analyzer(
            chapter_texts={1: None, 2: "有内容"}
        )
        novel_data = _make_novel_data(current_chapter=2)

        summary = analyzer._generate_chapters_summary("test-001", novel_data)

        assert "第1章" in summary
        assert "第2章" in summary
        # Chapter 1 should have empty preview
        assert "有内容" in summary


class TestParseImpactMissingFields:
    """缺少字段的容错处理。"""

    def test_empty_dict(self):
        analyzer, _, _ = _make_analyzer()
        result = analyzer._parse_impact(
            raw="{}",
            field="world_setting",
            old_val="old",
            new_val="new",
            max_chapter=10,
        )

        assert result["modified_field"] == "world_setting"
        assert result["affected_chapters"] == []
        assert result["conflicts"] == []
        assert result["severity"] == "medium"
        assert result["summary"] == ""

    def test_missing_conflicts_key(self):
        raw = json.dumps(
            {"affected_chapters": [1], "severity": "low", "summary": "ok"}
        )
        analyzer, _, _ = _make_analyzer()
        result = analyzer._parse_impact(
            raw=raw,
            field="characters",
            old_val="old",
            new_val="new",
            max_chapter=5,
        )

        assert result["affected_chapters"] == [1]
        assert result["conflicts"] == []
        assert result["severity"] == "low"

    def test_invalid_severity_defaults_to_medium(self):
        raw = json.dumps({"severity": "critical"})
        analyzer, _, _ = _make_analyzer()
        result = analyzer._parse_impact(
            raw=raw, field="x", old_val="", new_val="", max_chapter=5
        )

        assert result["severity"] == "medium"

    def test_conflict_missing_reason_skipped(self):
        """conflict 没有 reason 字段时被跳过。"""
        raw = json.dumps(
            {
                "conflicts": [
                    {
                        "chapter_number": 1,
                        "conflict_text": "text",
                        # no "reason" field
                    },
                    {
                        "chapter_number": 2,
                        "conflict_text": "text2",
                        "reason": "valid reason",
                    },
                ]
            }
        )
        analyzer, _, _ = _make_analyzer()
        result = analyzer._parse_impact(
            raw=raw, field="x", old_val="", new_val="", max_chapter=5
        )

        # Only the second conflict (with reason) should be kept
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["chapter_number"] == 2

    def test_non_dict_response(self):
        """LLM 返回 JSON array 而非 dict。"""
        analyzer, _, _ = _make_analyzer()
        result = analyzer._parse_impact(
            raw="[1, 2, 3]",
            field="x",
            old_val="",
            new_val="",
            max_chapter=5,
        )

        assert result["affected_chapters"] == []
        assert result["conflicts"] == []

    def test_truncates_long_values(self):
        """old_summary 和 new_summary 被截断到 200 字符。"""
        long_val = "x" * 500
        analyzer, _, _ = _make_analyzer()
        result = analyzer._parse_impact(
            raw="{}",
            field="f",
            old_val=long_val,
            new_val=long_val,
            max_chapter=5,
        )

        assert len(result["old_summary"]) == 200
        assert len(result["new_summary"]) == 200

    def test_affected_chapters_not_list(self):
        """affected_chapters 不是 list 时回退为空列表。"""
        raw = json.dumps({"affected_chapters": "all"})
        analyzer, _, _ = _make_analyzer()
        result = analyzer._parse_impact(
            raw=raw, field="x", old_val="", new_val="", max_chapter=5
        )

        assert result["affected_chapters"] == []
