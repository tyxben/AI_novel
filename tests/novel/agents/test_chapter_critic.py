"""Tests for ChapterCritic — Self-Refine 的批评角色。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.chapter_critic import (
    ChapterCritic,
    CritiqueResult,
    Issue,
    Revision,
)


@pytest.fixture
def mock_llm():
    return MagicMock()


def _llm_returns(mock_llm, payload: dict | str):
    """Helper: mock_llm.chat returns LLMResponse with given content."""
    if isinstance(payload, dict):
        content = json.dumps(payload, ensure_ascii=False)
    else:
        content = str(payload)
    mock_llm.chat.return_value = LLMResponse(
        content=content, model="mock", usage=None
    )


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class TestCritiqueResultModel:
    def test_default_empty(self):
        r = CritiqueResult()
        assert r.strengths == []
        assert r.issues == []
        assert r.specific_revisions == []
        assert r.high_severity_count == 0
        assert r.needs_refine is False

    def test_severity_counts(self):
        r = CritiqueResult(
            issues=[
                Issue(type="pacing", severity="high", reason="x"),
                Issue(type="dialogue", severity="medium", reason="y"),
                Issue(type="logic", severity="medium", reason="z"),
            ]
        )
        assert r.high_severity_count == 1
        assert r.medium_severity_count == 2
        assert r.needs_refine is True

    def test_needs_refine_only_low(self):
        r = CritiqueResult(
            issues=[
                Issue(type="pacing", severity="low", reason="x"),
                Issue(type="dialogue", severity="medium", reason="y"),
            ]
        )
        # 1 medium 不触发 refine（阈值 ≥2 medium 或 ≥1 high）
        assert r.needs_refine is False

    def test_quote_truncated(self):
        long_quote = "字" * 500
        i = Issue(type="pacing", severity="high", quote=long_quote, reason="x")
        assert len(i.quote) <= 200

    def test_writer_prompt_format(self):
        r = CritiqueResult(
            strengths=["开篇紧凑"],
            issues=[
                Issue(
                    type="trope_overuse",
                    severity="high",
                    quote="黑眸一凝",
                    reason="禁用词重复",
                )
            ],
            specific_revisions=[
                Revision(target="他黑眸一凝", suggestion="他眯起眼，瞳孔骤缩")
            ],
        )
        prompt = r.to_writer_prompt()
        assert "## 编辑批注" in prompt
        assert "保留的优点" in prompt
        assert "开篇紧凑" in prompt
        assert "🔴" in prompt
        assert "黑眸一凝" in prompt
        assert "瞳孔骤缩" in prompt

    def test_writer_prompt_empty_when_clean(self):
        r = CritiqueResult(strengths=["都好"])
        # 没有 issues / revisions → 空字符串
        assert r.to_writer_prompt() == ""


# ---------------------------------------------------------------------------
# ChapterCritic.critique
# ---------------------------------------------------------------------------


class TestChapterCritique:
    def test_happy_path_parses_structured_output(self, mock_llm):
        _llm_returns(
            mock_llm,
            {
                "strengths": ["节奏紧凑"],
                "issues": [
                    {
                        "type": "trope_overuse",
                        "severity": "high",
                        "quote": "黑眸一凝",
                        "reason": "AI 套路词重复出现",
                    }
                ],
                "specific_revisions": [
                    {
                        "target": "黑眸一凝",
                        "suggestion": "眯起眼睛，瞳孔骤缩",
                    }
                ],
                "overall_assessment": "整体可读但 AI 套路词太多",
            },
        )
        critic = ChapterCritic(mock_llm)
        r = critic.critique(
            "林辰黑眸一凝。" * 5,
            chapter_number=10,
            chapter_title="测试章",
            chapter_goal="冲突收束",
        )
        assert isinstance(r, CritiqueResult)
        assert "节奏紧凑" in r.strengths
        assert len(r.issues) == 1
        assert r.issues[0].type == "trope_overuse"
        assert r.issues[0].severity == "high"
        assert r.high_severity_count == 1
        assert r.needs_refine is True
        assert mock_llm.chat.called

    def test_llm_failure_returns_empty_safely(self, mock_llm):
        mock_llm.chat.side_effect = RuntimeError("network down")
        critic = ChapterCritic(mock_llm)
        r = critic.critique("正文", chapter_number=1)
        assert isinstance(r, CritiqueResult)
        assert r.issues == []
        assert "LLM 调用失败" in r.raw_response

    def test_empty_llm_response(self, mock_llm):
        _llm_returns(mock_llm, "")
        critic = ChapterCritic(mock_llm)
        r = critic.critique("正文", chapter_number=1)
        assert r.issues == []
        assert r.needs_refine is False

    def test_garbage_llm_response(self, mock_llm):
        _llm_returns(mock_llm, "this is not json at all")
        critic = ChapterCritic(mock_llm)
        r = critic.critique("正文", chapter_number=1)
        # 不抛异常，返回空结果但保留 raw
        assert r.issues == []
        assert r.raw_response == "this is not json at all"

    def test_partial_json_extracts_what_it_can(self, mock_llm):
        # JSON 嵌在文本里
        _llm_returns(
            mock_llm,
            'sure, here is your critique: {"strengths": ["开篇好"], "issues": []}',
        )
        critic = ChapterCritic(mock_llm)
        r = critic.critique("正文", chapter_number=1)
        assert "开篇好" in r.strengths

    def test_invalid_severity_falls_back(self, mock_llm):
        _llm_returns(
            mock_llm,
            {
                "issues": [
                    {"type": "pacing", "severity": "INVALID", "reason": "x"}
                ]
            },
        )
        critic = ChapterCritic(mock_llm)
        r = critic.critique("正文", chapter_number=1)
        # pydantic 拒绝非法 severity → 整个验证失败 → 空结果
        assert r.issues == []

    def test_prior_critiques_injected(self, mock_llm):
        _llm_returns(mock_llm, {"issues": [], "strengths": []})
        critic = ChapterCritic(mock_llm)
        prior = [
            CritiqueResult(
                issues=[Issue(type="pacing", severity="high", reason="拖沓")]
            )
        ]
        critic.critique(
            "正文", chapter_number=5, prior_critiques=prior
        )
        # 检查 prompt 中包含先前批注
        call_args = mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]
        assert "先前批注" in user_msg
        assert "拖沓" in user_msg

    def test_prev_chapter_tail_injected(self, mock_llm):
        _llm_returns(mock_llm, {"issues": [], "strengths": []})
        critic = ChapterCritic(mock_llm)
        critic.critique(
            "本章正文",
            chapter_number=2,
            prev_chapter_tail="上一章结尾林辰转身离去。",
        )
        user_msg = mock_llm.chat.call_args[0][0][1]["content"]
        assert "上一章结尾" in user_msg
        assert "林辰转身离去" in user_msg

    def test_uses_json_mode(self, mock_llm):
        _llm_returns(mock_llm, {"issues": [], "strengths": []})
        critic = ChapterCritic(mock_llm)
        critic.critique("正文", chapter_number=1)
        # 验证 LLM 被以 json_mode 调用
        kwargs = mock_llm.chat.call_args.kwargs
        assert kwargs.get("json_mode") is True
