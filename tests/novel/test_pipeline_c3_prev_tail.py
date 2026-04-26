"""C3 真修回归：pipeline 三处 Writer 通道不再喂上章生原文。

P0 (commit ffffda2) 修了 chapter generation 的跨章 verbatim 通道；本文件
覆盖 P1 (即 C3 真修) 修的另外三处同源 bug：

* ``NovelPipeline.polish_chapters``     (Reviewer + Writer.polish_chapter)
* ``NovelPipeline.apply_feedback``      (Writer.rewrite_chapter)
* ``NovelPipeline.rewrite_affected_chapters``  (Writer.rewrite_chapter,
  setting-change propagation 路径)

修复后，三处都先调 ``summarize_previous_tail()`` 拿摘要，再传摘要给
Writer / Reviewer。本文件以 spy ``src.novel.pipeline.summarize_previous_tail``
+ 捕获 Writer/Reviewer kwargs 的方式断言：

1. 上章 500 字（或更多）原文在 ``summarize_previous_tail`` 入口被截住
2. Writer.polish/rewrite_chapter 拿到的 ``context`` 是 summarizer 返回值
3. summarizer 返回 ``""`` 时 Writer 也拿 ``""`` （不走任何 fallback 塞回生原文）
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.reviewer import Reviewer
from src.novel.agents.writer import Writer
from src.novel.models.critique_result import CritiqueIssue, CritiqueResult


_SENTINEL_SUMMARY = "<<SENTINEL-PREV-TAIL-SUMMARY>>"
_RAW_CH1 = "第一章原文：" + ("惊雷自天外坠落，破开夜幕。" * 60)


def _make_llm(text: str = "writer output") -> MagicMock:
    client = MagicMock()
    client.chat.return_value = LLMResponse(content=text, model="mock")
    return client


def _critique_with_issues(chapter_number: int = 2) -> CritiqueResult:
    return CritiqueResult(
        chapter_number=chapter_number,
        strengths=[],
        issues=[
            CritiqueIssue(
                type="pacing",
                severity="high",
                quote="某段",
                reason="节奏问题",
            )
        ],
        specific_revisions=[],
        overall_assessment="有问题待修。",
    )


def _setup_two_chapter_project(tmp_path: Path) -> tuple[str, str]:
    """Set up a 2-chapter project. Returns (workspace, project_path)."""
    novel_id = "novel_c3_test"
    project_path = tmp_path / "novels" / novel_id
    project_path.mkdir(parents=True)

    checkpoint = {
        "config": {"llm": {}},
        "outline": {
            "main_storyline": {"protagonist_goal": "成长"},
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "破晓",
                    "goal": "目标 1",
                    "key_events": ["事件 1"],
                    "estimated_words": 2500,
                    "mood": "蓄力",
                },
                {
                    "chapter_number": 2,
                    "title": "雷动",
                    "goal": "目标 2",
                    "key_events": ["事件 2"],
                    "estimated_words": 2500,
                    "mood": "小爽",
                },
            ],
        },
        "characters": [],
        "world_setting": {"era": "上古", "location": "九州"},
        "style_name": "webnovel.shuangwen",
        "chapters": [],
    }
    with open(project_path / "checkpoint.json", "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False)

    chapters_dir = project_path / "chapters"
    chapters_dir.mkdir()
    (chapters_dir / "chapter_001.txt").write_text(_RAW_CH1, encoding="utf-8")
    (chapters_dir / "chapter_002.txt").write_text(
        "第二章原始内容。" * 30, encoding="utf-8"
    )

    return str(tmp_path), str(project_path)


# =========================================================================
# polish_chapters 路径
# =========================================================================


class TestPolishChaptersPrevTailGoesThroughSummarizer:
    def test_polish_ch2_summarizes_ch1_tail(self, tmp_path: Path) -> None:
        """polish 第 2 章时：(a) summarizer 被调一次，入参是 ch1 末 500 字；
        (b) Writer.polish_chapter 拿到的 context 是 sentinel summary，不是生原文。
        """
        from src.novel.pipeline import NovelPipeline

        workspace, project_path = _setup_two_chapter_project(tmp_path)
        mock_llm = _make_llm("writer-polished")
        pipe = NovelPipeline(workspace=workspace)
        critique = _critique_with_issues(chapter_number=2)

        with patch(
            "src.llm.llm_client.create_llm_client", return_value=mock_llm
        ), patch(
            "src.novel.pipeline.summarize_previous_tail",
            return_value=_SENTINEL_SUMMARY,
        ) as mock_summarize, patch.object(
            Reviewer, "review", return_value=critique
        ) as mock_review, patch.object(
            Writer, "polish_chapter", return_value="polished"
        ) as mock_polish:
            pipe.polish_chapters(
                project_path, start_chapter=2, end_chapter=2
            )

        mock_summarize.assert_called_once()
        # 入参 raw_tail 必须是 ch1 末 500 字（以截尾比对，避免依赖空白）
        called_args, _ = mock_summarize.call_args
        raw_tail_arg = called_args[1]
        assert raw_tail_arg == _RAW_CH1[-500:]
        assert len(raw_tail_arg) <= 500

        # 信息边界：Writer 生成侧拿摘要（防 verbatim 复读），Reviewer 评估侧
        # 拿原文末 500 字（衔接 / typo / 跨章伏笔判断需要原始字面量）
        assert mock_polish.call_args.kwargs["context"] == _SENTINEL_SUMMARY
        assert mock_review.call_args.kwargs["previous_tail"] == _RAW_CH1[-500:]

    def test_polish_ch1_no_prev_chapter_no_summarize(
        self, tmp_path: Path
    ) -> None:
        """第 1 章无前文：summarizer 不被调，context 是空串。"""
        from src.novel.pipeline import NovelPipeline

        workspace, project_path = _setup_two_chapter_project(tmp_path)
        mock_llm = _make_llm("writer-polished")
        pipe = NovelPipeline(workspace=workspace)
        critique = _critique_with_issues(chapter_number=1)

        with patch(
            "src.llm.llm_client.create_llm_client", return_value=mock_llm
        ), patch(
            "src.novel.pipeline.summarize_previous_tail",
            return_value=_SENTINEL_SUMMARY,
        ) as mock_summarize, patch.object(
            Reviewer, "review", return_value=critique
        ) as mock_review, patch.object(
            Writer, "polish_chapter", return_value="polished"
        ) as mock_polish:
            pipe.polish_chapters(
                project_path, start_chapter=1, end_chapter=1
            )

        mock_summarize.assert_not_called()
        assert mock_polish.call_args.kwargs["context"] == ""
        assert mock_review.call_args.kwargs["previous_tail"] == ""

    def test_polish_summarizer_returns_empty_writer_gets_empty(
        self, tmp_path: Path
    ) -> None:
        """summarizer 返回 ""（短文本/LLM 失败/verbatim 泄漏）时，Writer 也拿
        ""，pipeline 绝不能 fallback 塞生原文。"""
        from src.novel.pipeline import NovelPipeline

        workspace, project_path = _setup_two_chapter_project(tmp_path)
        mock_llm = _make_llm("writer-polished")
        pipe = NovelPipeline(workspace=workspace)
        critique = _critique_with_issues(chapter_number=2)

        with patch(
            "src.llm.llm_client.create_llm_client", return_value=mock_llm
        ), patch(
            "src.novel.pipeline.summarize_previous_tail",
            return_value="",
        ), patch.object(
            Reviewer, "review", return_value=critique
        ) as mock_review, patch.object(
            Writer, "polish_chapter", return_value="polished"
        ) as mock_polish:
            pipe.polish_chapters(
                project_path, start_chapter=2, end_chapter=2
            )

        # 生成侧 context 是空串，绝不 fallback 塞生原文
        polish_context = mock_polish.call_args.kwargs["context"]
        assert polish_context == ""

        # 评估侧 Reviewer 仍拿原文末 500 字（不受 summarizer 返空影响——
        # 信息边界：评估侧需要原始字面量）
        review_prev_tail = mock_review.call_args.kwargs["previous_tail"]
        assert review_prev_tail == _RAW_CH1[-500:]


# =========================================================================
# apply_feedback (rewrite) 路径
# =========================================================================


class TestApplyFeedbackPrevTailGoesThroughSummarizer:
    def test_apply_feedback_rewrite_ch2_summarizes_ch1_tail(
        self, tmp_path: Path
    ) -> None:
        """apply_feedback 重写第 2 章时，前章原文经 summarize_previous_tail 截断，
        Writer.rewrite_chapter 拿到的 context 是 sentinel。"""
        from src.novel.pipeline import NovelPipeline

        workspace, project_path = _setup_two_chapter_project(tmp_path)
        mock_llm = _make_llm("rewritten")
        pipe = NovelPipeline(workspace=workspace)

        # apply_feedback 走 user-approved instruction 路径，跳过 LLM analysis
        with patch(
            "src.llm.llm_client.create_llm_client", return_value=mock_llm
        ), patch(
            "src.novel.pipeline.summarize_previous_tail",
            return_value=_SENTINEL_SUMMARY,
        ) as mock_summarize, patch.object(
            Writer, "rewrite_chapter", return_value="rewritten-ch2"
        ) as mock_rewrite:
            pipe.apply_feedback(
                project_path=project_path,
                feedback_text="加快节奏",
                rewrite_instructions={"2": "加快节奏"},
                dry_run=False,
            )

        mock_summarize.assert_called_once()
        called_args, _ = mock_summarize.call_args
        raw_tail_arg = called_args[1]
        # M4 修复后：三处都用 [-500:] 取末尾（旧 truncate_text 从开头切是 bug）
        assert raw_tail_arg == _RAW_CH1[-500:]
        assert len(raw_tail_arg) <= 500

        # Writer 拿 sentinel，不是生原文
        assert mock_rewrite.call_args.kwargs["context"] == _SENTINEL_SUMMARY


# =========================================================================
# rewrite_affected_chapters 路径
# =========================================================================


class TestRewriteAffectedChaptersPrevTailGoesThroughSummarizer:
    def test_rewrite_affected_ch2_summarizes_ch1_tail(
        self, tmp_path: Path
    ) -> None:
        """rewrite_affected_chapters 路径（旧 2000 字漏网）也走 summarizer。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        workspace, project_path = _setup_two_chapter_project(tmp_path)
        novel_id = Path(project_path).name

        # rewrite_affected_chapters 读 novel.json，不读 checkpoint。需要 novel.json
        fm = FileManager(workspace)
        fm.save_novel(
            novel_id,
            {
                "novel_id": novel_id,
                "outline": {
                    "chapters": [
                        {
                            "chapter_number": 1,
                            "title": "破晓",
                            "goal": "目标 1",
                            "key_events": ["事件 1"],
                            "estimated_words": 2500,
                            "mood": "蓄力",
                        },
                        {
                            "chapter_number": 2,
                            "title": "雷动",
                            "goal": "目标 2",
                            "key_events": ["事件 2"],
                            "estimated_words": 2500,
                            "mood": "小爽",
                        },
                    ]
                },
                "characters": [],
                "world_setting": {"era": "上古", "location": "九州"},
                "style_name": "webnovel.shuangwen",
            },
        )

        mock_llm = _make_llm("rewritten")
        pipe = NovelPipeline(workspace=workspace)

        impact = {
            "summary": "世界观里 era 改为新纪元",
            "affected_chapters": [2],
            "conflicts": [],
        }

        with patch(
            "src.llm.llm_client.create_llm_client", return_value=mock_llm
        ), patch(
            "src.novel.pipeline.summarize_previous_tail",
            return_value=_SENTINEL_SUMMARY,
        ) as mock_summarize, patch.object(
            Writer, "rewrite_chapter", return_value="rewritten-ch2"
        ) as mock_rewrite:
            pipe.rewrite_affected_chapters(project_path, impact)

        mock_summarize.assert_called_once()
        called_args, _ = mock_summarize.call_args
        raw_tail_arg = called_args[1]
        # rewrite_affected_chapters 已收到 P1 修复：从 prev_text[-2000:]
        # 改为 prev_text[-500:]，再交给 summarizer
        assert raw_tail_arg == _RAW_CH1[-500:]
        assert len(raw_tail_arg) <= 500

        assert mock_rewrite.call_args.kwargs["context"] == _SENTINEL_SUMMARY


# =========================================================================
# 端到端 backstop：不依赖 summarize_previous_tail import 路径
# =========================================================================


class TestE2ENoRawSubstringLeaksToWriter:
    """这条防御纵深的测试故意**不** patch summarize_previous_tail。

    spy mock (前面三个 class) 的 patch 路径 ``src.novel.pipeline.summarize_previous_tail``
    依赖 pipeline 用 ``from ... import summarize_previous_tail`` 这种 module-level
    binding——如果未来重构成 ``from src.novel.services import prev_tail_summarizer``
    + 调 ``prev_tail_summarizer.summarize_previous_tail(...)``，spy 失效但测试
    照样 PASS（典型 mock 错位盲区，code review M3）。

    这里只 patch LLM 出入口 (`llm.chat`)：summarizer 真跑、返一个 clean summary
    不与 ``_RAW_CH1`` 重叠，verbatim 守卫放行。然后断言 Writer 拿到的 context
    不含任何 15-char ``_RAW_CH1`` 子串——只要 pipeline 任何一处把生原文塞回
    Writer，这条断言就报警。
    """

    def test_polish_no_15char_substring_leaks_to_writer(
        self, tmp_path: Path
    ) -> None:
        from src.novel.pipeline import NovelPipeline

        workspace, project_path = _setup_two_chapter_project(tmp_path)
        # 这个摘要不与 _RAW_CH1 ("惊雷自天外坠落，破开夜幕。" * 60) 任何 15+
        # 字连续重叠，让 summarize 服务的 verbatim 守卫放行
        clean_summary = "状态：主角处境危急，悬念待解。"
        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(
            content=clean_summary, model="m"
        )

        pipe = NovelPipeline(workspace=workspace)
        critique = _critique_with_issues(chapter_number=2)

        with patch(
            "src.llm.llm_client.create_llm_client", return_value=mock_llm
        ), patch.object(
            Reviewer, "review", return_value=critique
        ), patch.object(
            Writer, "polish_chapter", return_value="polished"
        ) as mock_polish:
            pipe.polish_chapters(
                project_path, start_chapter=2, end_chapter=2
            )

        polish_context = mock_polish.call_args.kwargs["context"]
        # 真跑 summarize_previous_tail 后，Writer 拿到的 context 应是 clean
        # summary（也允许 ""，但绝不能含任何 _RAW_CH1 的 15-char 子串）
        assert polish_context == clean_summary or polish_context == ""
        for i in range(0, len(_RAW_CH1) - 15):
            substr = _RAW_CH1[i : i + 15]
            assert substr not in polish_context, (
                f"ch1 substring at offset {i} ({substr!r}) leaked to "
                f"Writer.polish_chapter context"
            )


# =========================================================================
# 集成 / 防御纵深：Writer 提示词文案口径
# =========================================================================


class TestWriterPromptLabelsAlignedWithSummary:
    """Writer 提示词文案应反映"上下文是摘要不是原文"的事实。

    P0 之前用【前文回顾 — 严禁照抄以下文字】预设是生原文；C3 后改为
    【前章状态摘要 — 仅供衔接参考，严禁照抄】。
    """

    def _make_outline(self):
        from src.novel.models.novel import ChapterOutline

        return ChapterOutline(
            chapter_number=2,
            title="雷动",
            goal="目标 2",
            key_events=["事件 2"],
            estimated_words=2500,
            mood="小爽",
        )

    def _make_world(self):
        from src.novel.models.world import WorldSetting

        return WorldSetting(era="上古", location="九州")

    def test_polish_chapter_uses_summary_label(self) -> None:
        llm = _make_llm("polished")
        writer = Writer(llm)
        writer.polish_chapter(
            chapter_text="原始章节正文",
            critique="【问题1】xx",
            chapter_outline=self._make_outline(),
            characters=[],
            world_setting=self._make_world(),
            context="前章状态：主角站在崖边。",
            style_name="webnovel.shuangwen",
        )
        messages = llm.chat.call_args[1].get("messages") or llm.chat.call_args[0][0]
        user_msg = messages[1]["content"]
        assert "前章状态摘要" in user_msg
        # 旧文案不再出现
        assert "前文回顾" not in user_msg

    def test_rewrite_chapter_direct_uses_summary_label(self) -> None:
        llm = _make_llm("rewritten")
        writer = Writer(llm)
        writer.rewrite_chapter(
            original_text="原文" * 100,
            rewrite_instruction="改",
            chapter_outline=self._make_outline(),
            characters=[],
            world_setting=self._make_world(),
            context="前章状态：主角站在崖边。",
            style_name="webnovel.shuangwen",
            is_propagation=False,
        )
        # 取最后一次 chat call (rewrite 内可能续写)
        messages = (
            llm.chat.call_args[1].get("messages") or llm.chat.call_args[0][0]
        )
        user_msg = messages[1]["content"]
        assert "前章状态摘要" in user_msg
        assert "前文回顾" not in user_msg

    def test_rewrite_chapter_propagation_uses_summary_label(self) -> None:
        llm = _make_llm("rewritten")
        writer = Writer(llm)
        writer.rewrite_chapter(
            original_text="原文" * 100,
            rewrite_instruction="微调",
            chapter_outline=self._make_outline(),
            characters=[],
            world_setting=self._make_world(),
            context="前章状态：主角站在崖边。",
            style_name="webnovel.shuangwen",
            is_propagation=True,
        )
        messages = (
            llm.chat.call_args[1].get("messages") or llm.chat.call_args[0][0]
        )
        user_msg = messages[1]["content"]
        assert "前章状态摘要" in user_msg
        # 旧的【修改后的前文】裸标签不再出现（该口径默认是生原文，会误导）
        assert "【修改后的前文】" not in user_msg


# =========================================================================
# summarizer service 单元防御
# =========================================================================


class TestSummarizerServiceContract:
    """直接打 service，不经 pipeline / planner。"""

    def test_returns_empty_when_input_empty(self) -> None:
        from src.novel.services.prev_tail_summarizer import (
            summarize_previous_tail,
        )

        llm = _make_llm("never called")
        assert summarize_previous_tail(llm, "") == ""
        assert summarize_previous_tail(llm, "    ") == ""
        llm.chat.assert_not_called()

    def test_returns_short_input_directly_no_llm_call(self) -> None:
        """<80 chars 直接返回，不调 LLM。"""
        from src.novel.services.prev_tail_summarizer import (
            summarize_previous_tail,
        )

        llm = _make_llm("never called")
        result = summarize_previous_tail(llm, "短文本，不到 80 字。")
        assert result == "短文本，不到 80 字。"
        llm.chat.assert_not_called()

    def test_discards_summary_with_long_verbatim_overlap(self) -> None:
        """LLM 返回里夹了 >=15 字源文本子串 → 整段丢弃返 ""。"""
        from src.novel.services.prev_tail_summarizer import (
            summarize_previous_tail,
        )

        source = "惊雷自天外坠落破开夜幕照亮主角苍白的脸庞。" * 5
        # 含 16 字连续源串（"惊雷自天外坠落破开夜幕照亮主角"）
        leaky = "概括：惊雷自天外坠落破开夜幕照亮主角醒来后冲出。"
        llm = MagicMock()
        llm.chat.return_value = LLMResponse(content=leaky, model="m")

        result = summarize_previous_tail(llm, source)
        assert result == ""

    def test_returns_summary_when_no_overlap(self) -> None:
        from src.novel.services.prev_tail_summarizer import (
            summarize_previous_tail,
        )

        source = "惊雷自天外坠落，破开夜幕。" * 10
        clean = "状态：主角于雷雨夜醒来，处境危急，悬念待解。"
        llm = MagicMock()
        llm.chat.return_value = LLMResponse(content=clean, model="m")

        result = summarize_previous_tail(llm, source)
        assert result == clean

    def test_returns_empty_on_llm_failure(self) -> None:
        from src.novel.services.prev_tail_summarizer import (
            summarize_previous_tail,
        )

        source = "原文。" * 100
        llm = MagicMock()
        llm.chat.side_effect = RuntimeError("api down")

        result = summarize_previous_tail(llm, source)
        assert result == ""

    def test_caps_summary_to_max_chars(self) -> None:
        from src.novel.services.prev_tail_summarizer import (
            summarize_previous_tail,
        )

        source = "原文。" * 100
        long_summary = "状态描述：" + ("不冲突词汇 " * 200)
        llm = MagicMock()
        llm.chat.return_value = LLMResponse(content=long_summary, model="m")

        result = summarize_previous_tail(llm, source)
        assert len(result) <= 200
