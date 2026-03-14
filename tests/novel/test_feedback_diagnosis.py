"""Tests for FeedbackAnalyzer three-step diagnosis chain.

Tests: diagnose, locate_evidence, plan_fix, analyze integration,
and pipeline.apply_feedback with the diagnosis chain.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.feedback_analyzer import FeedbackAnalyzer, _keyword_search


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def analyzer(mock_llm):
    return FeedbackAnalyzer(mock_llm)


@pytest.fixture
def sample_outline_chapters():
    return [
        {
            "chapter_number": i,
            "title": f"第{i}章标题",
            "goal": f"第{i}章目标",
            "involved_characters": ["主角", "配角A"],
        }
        for i in range(1, 6)
    ]


@pytest.fixture
def sample_characters():
    return [{"name": "主角"}, {"name": "配角A"}]


@pytest.fixture
def sample_chapter_texts():
    return {
        1: (
            "主角走进了山谷，感受到一股强大的灵压。"
            "他决定先修炼一番再继续前进。\n\n"
            "配角A在旁边说道：小心点，这里有危险。"
        ),
        2: (
            "主角突然暴怒，对配角A拳脚相加。"
            "这完全不符合他温和的性格。\n\n"
            "配角A被打得很惨，但主角毫无悔意。"
        ),
        3: "第三章的内容，主角继续修炼。功力大增，突破了瓶颈。",
    }


# ---------------------------------------------------------------------------
# _keyword_search tests
# ---------------------------------------------------------------------------


class TestKeywordSearch:
    def test_finds_matching_paragraphs(self):
        text = "第一段内容\n\n主角修炼突破\n\n第三段其他内容"
        results = _keyword_search(text, ["修炼"])
        assert len(results) == 1
        assert results[0]["paragraph_index"] == 1
        assert "修炼" in results[0]["text_excerpt"]
        assert results[0]["keyword"] == "修炼"

    def test_empty_text_returns_empty(self):
        assert _keyword_search("", ["关键词"]) == []

    def test_empty_keywords_returns_empty(self):
        assert _keyword_search("一些文本", []) == []

    def test_no_match_returns_empty(self):
        assert _keyword_search("一些文本内容", ["不存在的词"]) == []

    def test_deduplicates_paragraphs(self):
        text = "主角修炼突破"
        results = _keyword_search(text, ["主角", "修炼"])
        # Same paragraph matched by two keywords — should only appear once
        assert len(results) == 1

    def test_truncates_excerpt(self):
        long_para = "字" * 500
        results = _keyword_search(long_para, ["字"])
        assert len(results[0]["text_excerpt"]) == 300


# ---------------------------------------------------------------------------
# diagnose tests
# ---------------------------------------------------------------------------


class TestDiagnose:
    def test_classifies_feedback_correctly(self, analyzer, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {
                    "problem_type": "character",
                    "severity": "high",
                    "diagnosis": "主角行为与前期性格设定不一致",
                    "search_keywords": ["主角", "暴怒", "性格"],
                }
            ),
            model="test",
            usage=None,
        )

        result = analyzer.diagnose("主角不对劲", chapter_number=2)

        assert result["problem_type"] == "character"
        assert result["severity"] == "high"
        assert "不一致" in result["diagnosis"]
        assert isinstance(result["search_keywords"], list)
        assert len(result["search_keywords"]) > 0

    def test_translates_vague_feedback(self, analyzer, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {
                    "problem_type": "pacing",
                    "severity": "medium",
                    "diagnosis": "章节节奏拖沓，缺少冲突和转折",
                    "search_keywords": ["修炼", "突破"],
                }
            ),
            model="test",
            usage=None,
        )

        result = analyzer.diagnose("这段拖", chapter_number=3)

        assert result["problem_type"] == "pacing"
        assert "拖" in result["diagnosis"] or "节奏" in result["diagnosis"]

    def test_handles_invalid_problem_type(self, analyzer, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {
                    "problem_type": "invalid_type",
                    "severity": "high",
                    "diagnosis": "some diagnosis",
                    "search_keywords": [],
                }
            ),
            model="test",
            usage=None,
        )

        result = analyzer.diagnose("反馈", chapter_number=1)
        assert result["problem_type"] == "other"

    def test_handles_invalid_severity(self, analyzer, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {
                    "problem_type": "character",
                    "severity": "critical",
                    "diagnosis": "diagnosis",
                    "search_keywords": [],
                }
            ),
            model="test",
            usage=None,
        )

        result = analyzer.diagnose("反馈", chapter_number=1)
        assert result["severity"] == "medium"

    def test_handles_llm_parse_failure(self, analyzer, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content="这不是JSON",
            model="test",
            usage=None,
        )

        result = analyzer.diagnose("主角不对劲", chapter_number=2)

        assert result["problem_type"] == "other"
        assert result["severity"] == "medium"
        assert result["diagnosis"] == "主角不对劲"
        assert result["search_keywords"] == []

    def test_handles_empty_diagnosis_field(self, analyzer, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {
                    "problem_type": "character",
                    "severity": "high",
                    "diagnosis": "",
                    "search_keywords": ["主角"],
                }
            ),
            model="test",
            usage=None,
        )

        result = analyzer.diagnose("原始反馈", chapter_number=1)
        # Empty diagnosis should fallback to original feedback text
        assert result["diagnosis"] == "原始反馈"

    def test_handles_non_list_keywords(self, analyzer, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {
                    "problem_type": "style",
                    "severity": "low",
                    "diagnosis": "诊断内容",
                    "search_keywords": "not a list",
                }
            ),
            model="test",
            usage=None,
        )

        result = analyzer.diagnose("反馈", chapter_number=1)
        assert result["search_keywords"] == []

    def test_global_feedback_no_chapter(self, analyzer, mock_llm):
        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {
                    "problem_type": "pacing",
                    "severity": "medium",
                    "diagnosis": "全局节奏问题",
                    "search_keywords": ["节奏"],
                }
            ),
            model="test",
            usage=None,
        )

        result = analyzer.diagnose("整体节奏太慢", chapter_number=None)
        assert result["problem_type"] == "pacing"


# ---------------------------------------------------------------------------
# locate_evidence tests
# ---------------------------------------------------------------------------


class TestLocateEvidence:
    def test_finds_evidence_with_matching_keywords(
        self, analyzer, mock_llm, sample_chapter_texts
    ):
        diagnosis = {
            "problem_type": "character",
            "severity": "high",
            "diagnosis": "主角行为不一致",
            "search_keywords": ["暴怒", "性格"],
        }

        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {
                    "evidence": [
                        {"index": 0, "issue": "主角突然暴怒不符合性格"},
                    ]
                }
            ),
            model="test",
            usage=None,
        )

        result = analyzer.locate_evidence(
            diagnosis, sample_chapter_texts, chapter_number=2
        )

        assert len(result) == 1
        assert result[0]["chapter"] == 2
        assert result[0]["issue"] == "主角突然暴怒不符合性格"

    def test_returns_empty_when_no_keywords(
        self, analyzer, sample_chapter_texts
    ):
        diagnosis = {
            "problem_type": "other",
            "severity": "low",
            "diagnosis": "模糊诊断",
            "search_keywords": [],
        }

        result = analyzer.locate_evidence(
            diagnosis, sample_chapter_texts, chapter_number=1
        )
        assert result == []

    def test_returns_empty_when_no_chapter_texts(self, analyzer):
        diagnosis = {
            "problem_type": "character",
            "severity": "high",
            "diagnosis": "诊断",
            "search_keywords": ["主角"],
        }

        result = analyzer.locate_evidence(diagnosis, {}, chapter_number=1)
        assert result == []

    def test_returns_empty_when_no_keyword_match(
        self, analyzer, sample_chapter_texts
    ):
        diagnosis = {
            "problem_type": "character",
            "severity": "high",
            "diagnosis": "诊断",
            "search_keywords": ["完全不存在的词汇XYZ"],
        }

        result = analyzer.locate_evidence(
            diagnosis, sample_chapter_texts, chapter_number=1
        )
        assert result == []
        # LLM should not be called when there are no candidates
        analyzer.llm.chat.assert_not_called()

    def test_handles_llm_verification_failure(
        self, analyzer, mock_llm, sample_chapter_texts
    ):
        diagnosis = {
            "problem_type": "character",
            "severity": "high",
            "diagnosis": "诊断",
            "search_keywords": ["主角"],
        }

        mock_llm.chat.return_value = LLMResponse(
            content="not json",
            model="test",
            usage=None,
        )

        result = analyzer.locate_evidence(
            diagnosis, sample_chapter_texts, chapter_number=1
        )
        assert result == []

    def test_handles_llm_returns_empty_evidence(
        self, analyzer, mock_llm, sample_chapter_texts
    ):
        diagnosis = {
            "problem_type": "character",
            "severity": "high",
            "diagnosis": "诊断",
            "search_keywords": ["主角"],
        }

        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps({"evidence": []}),
            model="test",
            usage=None,
        )

        result = analyzer.locate_evidence(
            diagnosis, sample_chapter_texts, chapter_number=1
        )
        assert result == []

    def test_filters_invalid_evidence_indices(
        self, analyzer, mock_llm, sample_chapter_texts
    ):
        diagnosis = {
            "problem_type": "character",
            "severity": "high",
            "diagnosis": "诊断",
            "search_keywords": ["主角"],
        }

        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {
                    "evidence": [
                        {"index": 0, "issue": "valid issue"},
                        {"index": 999, "issue": "out of range"},
                        {"index": "not_int", "issue": "bad index"},
                        "not a dict",
                    ]
                }
            ),
            model="test",
            usage=None,
        )

        result = analyzer.locate_evidence(
            diagnosis, sample_chapter_texts, chapter_number=1
        )
        # Only index 0 is valid
        assert len(result) == 1
        assert result[0]["issue"] == "valid issue"

    def test_prioritizes_target_chapter(
        self, analyzer, mock_llm, sample_chapter_texts
    ):
        """Target chapter should be searched first."""
        diagnosis = {
            "problem_type": "character",
            "severity": "high",
            "diagnosis": "诊断",
            "search_keywords": ["主角"],
        }

        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {"evidence": [{"index": 0, "issue": "issue in target ch"}]}
            ),
            model="test",
            usage=None,
        )

        result = analyzer.locate_evidence(
            diagnosis, sample_chapter_texts, chapter_number=2
        )

        # Verify LLM was called and the first candidate is from chapter 2
        call_args = mock_llm.chat.call_args
        prompt_text = call_args[1]["messages"][1]["content"] if "messages" in call_args[1] else call_args[0][0][1]["content"]
        # Chapter 2 should appear first in the candidates
        assert "第2章" in prompt_text


# ---------------------------------------------------------------------------
# plan_fix tests
# ---------------------------------------------------------------------------


class TestPlanFix:
    def test_generates_instructions_from_evidence(
        self, analyzer, mock_llm, sample_outline_chapters
    ):
        diagnosis = {
            "problem_type": "character",
            "severity": "high",
            "diagnosis": "主角行为不一致",
        }
        evidence = [
            {
                "chapter": 2,
                "paragraph_index": 0,
                "text_excerpt": "主角突然暴怒",
                "issue": "暴怒不符合性格",
            }
        ]

        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {
                    "target_chapters": [2],
                    "propagation_chapters": [3],
                    "rewrite_instructions": {
                        "2": "将主角暴怒改为冷静应对，引用「主角突然暴怒」"
                    },
                    "character_changes": None,
                    "summary": "修改第2章主角不一致的行为",
                }
            ),
            model="test",
            usage=None,
        )

        result = analyzer.plan_fix(
            diagnosis, evidence, sample_outline_chapters
        )

        assert result["target_chapters"] == [2]
        assert "2" in result["rewrite_instructions"]
        assert result["feedback_type"] == "character"
        assert result["severity"] == "high"

    def test_empty_evidence_returns_minimal_result(
        self, analyzer, sample_outline_chapters
    ):
        diagnosis = {
            "problem_type": "pacing",
            "severity": "low",
            "diagnosis": "节奏问题",
        }

        result = analyzer.plan_fix(diagnosis, [], sample_outline_chapters)

        assert result["target_chapters"] == []
        assert result["rewrite_instructions"] == {}
        assert "未在正文中找到" in result["summary"]
        # LLM should not be called when there's no evidence
        analyzer.llm.chat.assert_not_called()

    def test_handles_llm_parse_failure_fallback(
        self, analyzer, mock_llm, sample_outline_chapters
    ):
        diagnosis = {
            "problem_type": "character",
            "severity": "high",
            "diagnosis": "行为不一致",
        }
        evidence = [
            {
                "chapter": 2,
                "paragraph_index": 0,
                "text_excerpt": "主角暴怒片段",
                "issue": "不符合性格",
            }
        ]

        mock_llm.chat.return_value = LLMResponse(
            content="not valid json at all",
            model="test",
            usage=None,
        )

        result = analyzer.plan_fix(
            diagnosis, evidence, sample_outline_chapters
        )

        # Fallback should still produce instructions from evidence
        assert result["target_chapters"] == [2]
        assert "2" in result["rewrite_instructions"]
        assert "主角暴怒片段" in result["rewrite_instructions"]["2"]
        assert "不符合性格" in result["rewrite_instructions"]["2"]

    def test_validates_chapter_numbers_in_range(
        self, analyzer, mock_llm, sample_outline_chapters
    ):
        diagnosis = {"problem_type": "style", "severity": "low", "diagnosis": "d"}
        evidence = [
            {
                "chapter": 1,
                "paragraph_index": 0,
                "text_excerpt": "text",
                "issue": "issue",
            }
        ]

        mock_llm.chat.return_value = LLMResponse(
            content=json.dumps(
                {
                    "target_chapters": [1, 999],
                    "propagation_chapters": [2, -1],
                    "rewrite_instructions": {"1": "fix it", "999": "invalid"},
                    "summary": "ok",
                }
            ),
            model="test",
            usage=None,
        )

        result = analyzer.plan_fix(
            diagnosis, evidence, sample_outline_chapters
        )

        assert 999 not in result["target_chapters"]
        assert -1 not in result["propagation_chapters"]
        assert "999" not in result["rewrite_instructions"]


# ---------------------------------------------------------------------------
# analyze (integration) tests
# ---------------------------------------------------------------------------


class TestAnalyzeIntegration:
    def test_analyze_calls_diagnose_then_generates_plan(
        self, analyzer, mock_llm, sample_outline_chapters, sample_characters
    ):
        # First call = diagnose, second call = plan generation
        mock_llm.chat.side_effect = [
            LLMResponse(
                content=json.dumps(
                    {
                        "problem_type": "character",
                        "severity": "high",
                        "diagnosis": "主角行为不一致",
                        "search_keywords": ["主角", "暴怒"],
                    }
                ),
                model="test",
                usage=None,
            ),
            LLMResponse(
                content=json.dumps(
                    {
                        "feedback_type": "character",
                        "severity": "high",
                        "target_chapters": [2],
                        "propagation_chapters": [3],
                        "rewrite_instructions": {"2": "修改主角行为"},
                        "character_changes": None,
                        "summary": "修改第2章",
                    }
                ),
                model="test",
                usage=None,
            ),
        ]

        result = analyzer.analyze(
            feedback_text="主角不对劲",
            chapter_number=2,
            outline_chapters=sample_outline_chapters,
            characters=sample_characters,
        )

        assert result["feedback_type"] == "character"
        assert result["target_chapters"] == [2]
        assert "diagnosis" in result
        assert result["diagnosis"]["problem_type"] == "character"
        assert mock_llm.chat.call_count == 2

    def test_analyze_backward_compatible(
        self, analyzer, mock_llm, sample_outline_chapters, sample_characters
    ):
        """analyze() should still return all expected keys."""
        mock_llm.chat.side_effect = [
            LLMResponse(
                content=json.dumps(
                    {
                        "problem_type": "pacing",
                        "severity": "medium",
                        "diagnosis": "节奏慢",
                        "search_keywords": [],
                    }
                ),
                model="test",
                usage=None,
            ),
            LLMResponse(
                content=json.dumps(
                    {
                        "feedback_type": "pacing",
                        "severity": "medium",
                        "target_chapters": [3],
                        "propagation_chapters": [],
                        "rewrite_instructions": {"3": "加快节奏"},
                        "character_changes": None,
                        "summary": "加快第3章节奏",
                    }
                ),
                model="test",
                usage=None,
            ),
        ]

        result = analyzer.analyze(
            feedback_text="节奏太慢",
            chapter_number=3,
            outline_chapters=sample_outline_chapters,
            characters=sample_characters,
        )

        # All original keys must be present
        for key in [
            "feedback_type",
            "severity",
            "target_chapters",
            "propagation_chapters",
            "rewrite_instructions",
            "summary",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_analyze_fallback_when_both_llm_calls_fail(
        self, analyzer, mock_llm, sample_outline_chapters, sample_characters
    ):
        mock_llm.chat.side_effect = [
            LLMResponse(content="bad json 1", model="test", usage=None),
            LLMResponse(content="bad json 2", model="test", usage=None),
        ]

        result = analyzer.analyze(
            feedback_text="反馈内容",
            chapter_number=5,
            outline_chapters=sample_outline_chapters,
            characters=sample_characters,
        )

        # Should not crash and should provide fallback
        assert result["feedback_type"] == "other"
        assert result["target_chapters"] == [5]
        assert "diagnosis" in result

    def test_analyze_with_none_chapter(
        self, analyzer, mock_llm, sample_outline_chapters, sample_characters
    ):
        mock_llm.chat.side_effect = [
            LLMResponse(
                content=json.dumps(
                    {
                        "problem_type": "style",
                        "severity": "low",
                        "diagnosis": "风格问题",
                        "search_keywords": [],
                    }
                ),
                model="test",
                usage=None,
            ),
            LLMResponse(
                content=json.dumps(
                    {
                        "feedback_type": "style",
                        "severity": "low",
                        "target_chapters": [],
                        "propagation_chapters": [],
                        "rewrite_instructions": {},
                        "character_changes": None,
                        "summary": "风格建议",
                    }
                ),
                model="test",
                usage=None,
            ),
        ]

        result = analyzer.analyze(
            feedback_text="文风太平",
            chapter_number=None,
            outline_chapters=sample_outline_chapters,
            characters=sample_characters,
        )

        assert result["feedback_type"] == "style"

    def test_analyze_llm_exception_does_not_crash(
        self, analyzer, mock_llm, sample_outline_chapters, sample_characters
    ):
        """If LLM raises an exception, analyze should propagate it (not silently fail)."""
        mock_llm.chat.side_effect = Exception("LLM connection error")

        with pytest.raises(Exception, match="LLM connection error"):
            analyzer.analyze(
                feedback_text="反馈",
                chapter_number=1,
                outline_chapters=sample_outline_chapters,
                characters=sample_characters,
            )


# ---------------------------------------------------------------------------
# pipeline.apply_feedback integration tests
# ---------------------------------------------------------------------------


class TestPipelineDiagnosisChain:
    """Test that pipeline.apply_feedback integrates the diagnosis chain."""

    @patch("src.novel.pipeline.NovelPipeline._load_checkpoint")
    @patch("src.novel.pipeline.NovelPipeline._get_file_manager")
    @patch("src.llm.llm_client.create_llm_client")
    def test_dry_run_returns_diagnosis(
        self, mock_create_llm, mock_get_fm, mock_load_cp
    ):
        """dry_run should include diagnosis in the analysis."""
        from src.novel.pipeline import NovelPipeline

        mock_llm = MagicMock()
        mock_create_llm.return_value = mock_llm

        # diagnose call
        # analyze second call
        mock_llm.chat.side_effect = [
            LLMResponse(
                content=json.dumps(
                    {
                        "problem_type": "character",
                        "severity": "high",
                        "diagnosis": "主角行为不一致",
                        "search_keywords": ["主角"],
                    }
                ),
                model="test",
                usage=None,
            ),
            LLMResponse(
                content=json.dumps(
                    {
                        "feedback_type": "character",
                        "severity": "high",
                        "target_chapters": [2],
                        "propagation_chapters": [],
                        "rewrite_instructions": {"2": "修改行为"},
                        "character_changes": None,
                        "summary": "修改第2章",
                    }
                ),
                model="test",
                usage=None,
            ),
        ]

        mock_load_cp.return_value = {
            "config": {"llm": {}},
            "outline": {
                "chapters": [
                    {"chapter_number": i, "title": f"Ch{i}", "goal": "g"}
                    for i in range(1, 4)
                ]
            },
            "characters": [{"name": "主角"}],
        }

        pipe = NovelPipeline(workspace="/tmp/test_ws")
        result = pipe.apply_feedback(
            project_path="/tmp/test_ws/novels/test_novel",
            feedback_text="主角不对劲",
            chapter_number=2,
            dry_run=True,
        )

        assert "analysis" in result
        analysis = result["analysis"]
        assert "diagnosis" in analysis
        assert analysis["diagnosis"]["problem_type"] == "character"

    @patch("src.novel.pipeline.NovelPipeline._load_checkpoint")
    @patch("src.novel.pipeline.NovelPipeline._get_file_manager")
    @patch("src.llm.llm_client.create_llm_client")
    def test_full_run_with_evidence_enhances_instructions(
        self, mock_create_llm, mock_get_fm, mock_load_cp
    ):
        """Full run should locate evidence and enhance rewrite instructions."""
        from src.novel.pipeline import NovelPipeline

        mock_llm = MagicMock()
        mock_create_llm.return_value = mock_llm

        mock_fm = MagicMock()
        mock_fm.load_chapter_text.return_value = None
        mock_get_fm.return_value = mock_fm

        # Call sequence:
        # 1. diagnose
        # 2. analyze (plan)
        # 3. locate_evidence (LLM verification)
        # 4. plan_fix (LLM)
        # 5. writer.rewrite_chapter (LLM)
        mock_llm.chat.side_effect = [
            # 1. diagnose
            LLMResponse(
                content=json.dumps(
                    {
                        "problem_type": "character",
                        "severity": "high",
                        "diagnosis": "主角行为不一致",
                        "search_keywords": ["暴怒"],
                    }
                ),
                model="test",
                usage=None,
            ),
            # 2. analyze plan
            LLMResponse(
                content=json.dumps(
                    {
                        "feedback_type": "character",
                        "severity": "high",
                        "target_chapters": [2],
                        "propagation_chapters": [],
                        "rewrite_instructions": {"2": "原始指令"},
                        "character_changes": None,
                        "summary": "修改第2章",
                    }
                ),
                model="test",
                usage=None,
            ),
            # 3. locate_evidence verification
            LLMResponse(
                content=json.dumps(
                    {
                        "evidence": [
                            {"index": 0, "issue": "暴怒不符合性格"}
                        ]
                    }
                ),
                model="test",
                usage=None,
            ),
            # 4. plan_fix
            LLMResponse(
                content=json.dumps(
                    {
                        "target_chapters": [2],
                        "propagation_chapters": [],
                        "rewrite_instructions": {
                            "2": "将「暴怒」改为冷静——基于证据的精准指令"
                        },
                        "character_changes": None,
                        "summary": "精准修改第2章暴怒段落",
                    }
                ),
                model="test",
                usage=None,
            ),
            # 5. writer rewrite
            LLMResponse(
                content="重写后的第2章内容，主角冷静应对。",
                model="test",
                usage=None,
            ),
        ]

        mock_load_cp.return_value = {
            "config": {"llm": {}},
            "outline": {
                "chapters": [
                    {
                        "chapter_number": i,
                        "title": f"Ch{i}",
                        "goal": "g",
                        "involved_characters": ["主角"],
                        "scenes": [{"description": "scene"}],
                    }
                    for i in range(1, 4)
                ]
            },
            "characters": [{"name": "主角", "role": "protagonist", "traits": ["温和"]}],
            "chapters": [
                {
                    "chapter_number": 2,
                    "full_text": "主角突然暴怒，这不符合他一贯温和的性格。",
                }
            ],
            "world_setting": {"era": "古代", "location": "玄幻大陆"},
            "style_name": "webnovel.shuangwen",
        }

        pipe = NovelPipeline(workspace="/tmp/test_ws")
        result = pipe.apply_feedback(
            project_path="/tmp/test_ws/novels/test_novel",
            feedback_text="主角不对劲",
            chapter_number=2,
            dry_run=False,
        )

        # The analysis should have evidence attached
        analysis = result["analysis"]
        assert "evidence" in analysis
        assert len(analysis["evidence"]) > 0
        # Instructions should be enhanced
        assert "精准" in analysis["rewrite_instructions"].get("2", "") or "暴怒" in analysis["rewrite_instructions"].get("2", "")

    @patch("src.novel.pipeline.NovelPipeline._load_checkpoint")
    @patch("src.novel.pipeline.NovelPipeline._get_file_manager")
    @patch("src.llm.llm_client.create_llm_client")
    def test_no_evidence_keeps_original_instructions(
        self, mock_create_llm, mock_get_fm, mock_load_cp
    ):
        """When no evidence is found, original instructions should be kept."""
        from src.novel.pipeline import NovelPipeline

        mock_llm = MagicMock()
        mock_create_llm.return_value = mock_llm

        mock_fm = MagicMock()
        mock_fm.load_chapter_text.return_value = None
        mock_get_fm.return_value = mock_fm

        mock_llm.chat.side_effect = [
            # 1. diagnose
            LLMResponse(
                content=json.dumps(
                    {
                        "problem_type": "pacing",
                        "severity": "medium",
                        "diagnosis": "节奏问题",
                        "search_keywords": ["完全不存在的词XYZ"],
                    }
                ),
                model="test",
                usage=None,
            ),
            # 2. analyze plan
            LLMResponse(
                content=json.dumps(
                    {
                        "feedback_type": "pacing",
                        "severity": "medium",
                        "target_chapters": [1],
                        "propagation_chapters": [],
                        "rewrite_instructions": {"1": "原始指令应保留"},
                        "character_changes": None,
                        "summary": "节奏调整",
                    }
                ),
                model="test",
                usage=None,
            ),
            # 3. writer rewrite (no locate_evidence call because no keyword match)
            LLMResponse(
                content="重写后的内容",
                model="test",
                usage=None,
            ),
        ]

        mock_load_cp.return_value = {
            "config": {"llm": {}},
            "outline": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "Ch1",
                        "goal": "g",
                        "involved_characters": ["主角"],
                        "scenes": [{"description": "scene"}],
                    }
                ]
            },
            "characters": [{"name": "主角", "role": "protagonist", "traits": []}],
            "chapters": [
                {"chapter_number": 1, "full_text": "普通的第一章内容没有匹配"}
            ],
            "world_setting": {"era": "古代", "location": "大陆"},
            "style_name": "webnovel.shuangwen",
        }

        pipe = NovelPipeline(workspace="/tmp/test_ws")
        result = pipe.apply_feedback(
            project_path="/tmp/test_ws/novels/test_novel",
            feedback_text="节奏太慢",
            chapter_number=1,
            dry_run=False,
        )

        # Original instructions should be preserved (no evidence found)
        analysis = result["analysis"]
        assert "evidence" not in analysis
        assert analysis["rewrite_instructions"]["1"] == "原始指令应保留"
