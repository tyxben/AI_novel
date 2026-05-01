"""D4 回归：_persist_chapter_actual_summary helper + 4 处写盘点同步 outline.

事故根因：generate_chapters 主循环把 actual_summary 写到 state.outline，但持久化
只同步 characters/world_setting，novel.json.outline.actual_summary 永远空。重写
路径 (apply_feedback / rewrite_affected_chapters / polish_chapters) 完全跳过。
本测试覆盖 helper 行为 + 验证 4 处接入点都调用了 helper。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_outline_with_chapter(ch_num: int = 1) -> dict:
    return {
        "template": "cyclic_upgrade",
        "main_storyline": {"protagonist_goal": "G", "core_conflict": "C"},
        "acts": [{"name": "幕1", "description": "x", "start_chapter": 1, "end_chapter": 5}],
        "volumes": [
            {
                "volume_number": 1, "title": "vol1",
                "core_conflict": "x", "resolution": "x",
                "chapters": [ch_num],
            }
        ],
        "chapters": [
            {
                "chapter_number": ch_num,
                "title": f"第{ch_num}章·测试",
                "goal": "G",
                "key_events": ["E"],
                "estimated_words": 2500,
                "mood": "蓄力",
                # 故意不带 actual_summary
            }
        ],
    }


@pytest.fixture
def tmp_novel_dir(tmp_path: Path) -> Path:
    novel_id = "novel_d4_test"
    novel_dir = tmp_path / "novels" / novel_id
    novel_dir.mkdir(parents=True)
    (novel_dir / "chapters").mkdir()
    novel_data = {
        "novel_id": novel_id,
        "title": "D4 测试",
        "genre": "玄幻",
        "theme": "测试",
        "target_words": 5000,
        "outline": _make_outline_with_chapter(1),
        "characters": [],
        "world_setting": {"era": "古代", "location": "九州"},
        "status": "generating",
    }
    (novel_dir / "novel.json").write_text(
        json.dumps(novel_data, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Test: _persist_chapter_actual_summary helper
# ---------------------------------------------------------------------------


class TestPersistActualSummaryHelper:
    """单测 helper 行为：成功路径 + 防御。"""

    def test_writes_to_state_outline_and_novel_json(self, tmp_novel_dir):
        """成功路径：summary 同时写入 state.outline 和 novel.json.outline。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        novel_id = "novel_d4_test"
        state = {"outline": _make_outline_with_chapter(1)}

        with patch.object(
            pipe, "_generate_actual_summary",
            return_value="第1章实际摘要：主角觉醒。",
        ):
            result = pipe._persist_chapter_actual_summary(
                fm, novel_id, 1, "本章正文" * 30,
                "第1章·测试", state=state,
            )

        assert result == "第1章实际摘要：主角觉醒。"
        # state.outline 已写入
        assert state["outline"]["chapters"][0]["actual_summary"] == "第1章实际摘要：主角觉醒。"
        # novel.json.outline 已同步
        novel_data = fm.load_novel(novel_id)
        assert novel_data["outline"]["chapters"][0]["actual_summary"] == "第1章实际摘要：主角觉醒。"

    def test_skips_when_chapter_text_too_short(self, tmp_novel_dir):
        """防御：chapter_text 太短直接跳过，不调 LLM。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        state = {"outline": _make_outline_with_chapter(1)}

        with patch.object(pipe, "_generate_actual_summary") as mock_gen:
            result = pipe._persist_chapter_actual_summary(
                fm, "novel_d4_test", 1, "短", "第1章·测试", state=state,
            )

        assert result == ""
        mock_gen.assert_not_called()
        # outline 未被污染
        assert "actual_summary" not in state["outline"]["chapters"][0]

    def test_rejects_non_string_summary(self, tmp_novel_dir):
        """防御：_generate_actual_summary 返回非 str（如 MagicMock）应拒绝写入。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        state = {"outline": _make_outline_with_chapter(1)}

        with patch.object(
            pipe, "_generate_actual_summary",
            return_value=MagicMock(),  # 非 str
        ):
            result = pipe._persist_chapter_actual_summary(
                fm, "novel_d4_test", 1, "正文" * 30,
                "第1章·测试", state=state,
            )

        assert result == ""
        # state 与 novel.json 都不应被污染
        assert "actual_summary" not in state["outline"]["chapters"][0]
        novel_data = fm.load_novel("novel_d4_test")
        assert "actual_summary" not in novel_data["outline"]["chapters"][0]

    def test_logs_warning_on_llm_exception_no_raise(self, tmp_novel_dir, caplog):
        """LLM 异常应吞掉 + log warning，不阻断主流程。"""
        import logging
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        state = {"outline": _make_outline_with_chapter(1)}

        with patch.object(
            pipe, "_generate_actual_summary",
            side_effect=RuntimeError("API quota exhausted"),
        ):
            with caplog.at_level(logging.WARNING, logger="novel"):
                result = pipe._persist_chapter_actual_summary(
                    fm, "novel_d4_test", 1, "正文" * 30,
                    "第1章·测试", state=state,
                )

        assert result == ""
        assert any("生成失败" in rec.message for rec in caplog.records)

    def test_no_match_when_chapter_not_in_outline(self, tmp_novel_dir):
        """防御：ch_num 不在 outline 时不报错，summary 也不写到错误位置。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        state = {"outline": _make_outline_with_chapter(1)}

        with patch.object(
            pipe, "_generate_actual_summary",
            return_value="第99章摘要",
        ):
            result = pipe._persist_chapter_actual_summary(
                fm, "novel_d4_test", 99, "正文" * 30,
                "第99章·测试", state=state,
            )

        # helper 仍返回 summary（语义保留），但 outline 没匹配章 → 不写
        assert result == "第99章摘要"
        # ch1 outline 不应被错误污染
        assert "actual_summary" not in state["outline"]["chapters"][0]


# ---------------------------------------------------------------------------
# Test: 4 处写盘点都接入了 helper
# ---------------------------------------------------------------------------


class TestRewritePathsCallHelper:
    """验证 apply_feedback / rewrite_affected_chapters / polish_chapters 重写后
    都调用了 _persist_chapter_actual_summary。这是 D4 主修：旧代码这三处完全不
    回填 actual_summary。"""

    def test_rewrite_affected_chapters_calls_helper_after_save(self, tmp_novel_dir):
        """rewrite_affected_chapters 重写后应调 helper 刷新 actual_summary。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        novel_id = "novel_d4_test"

        # 准备一个 ch1 文本 + checkpoint
        fm.save_chapter_text(novel_id, 1, "原文" * 100)
        outline = _make_outline_with_chapter(1)
        checkpoint = {
            "outline": outline,
            "chapters": [{"chapter_number": 1, "title": "第1章·测试", "full_text": "原文" * 100}],
            "characters": [],
            "world_setting": {"era": "古代", "location": "九州"},
            "config": {"llm": {}},
        }
        (Path(tmp_novel_dir) / "novels" / novel_id / "checkpoint.json").write_text(
            json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8"
        )

        # Mock LLM + Writer.rewrite_chapter + helper
        impact = {
            "affected_chapters": [1],
            "summary": "角色名字改了",
            "conflicts": [{"chapter_number": 1, "reason": "x", "suggested_fix": "y"}],
        }
        with patch("src.llm.llm_client.create_llm_client") as mock_create_llm, \
             patch("src.novel.agents.writer.Writer") as MockWriter, \
             patch.object(pipe, "_persist_chapter_actual_summary") as mock_persist:
            mock_create_llm.return_value = MagicMock()
            mock_writer = MockWriter.return_value
            mock_writer.rewrite_chapter.return_value = "新文本" * 100

            pipe.rewrite_affected_chapters(
                project_path=str(Path(tmp_novel_dir) / "novels" / novel_id),
                impact=impact,
            )

        # helper 应被调用一次（针对 ch1），新文本传入
        assert mock_persist.call_count == 1
        call_args = mock_persist.call_args
        # 第 4 个参数是 chapter_text（新文本）
        args = call_args.args
        # signature: (fm, novel_id, ch_num, new_text, title, state=...)
        assert args[2] == 1, f"ch_num 错: {args}"
        assert "新文本" in args[3], f"应传新文本: {args[3][:50]}"

    def test_polish_chapters_calls_helper_after_save(self, tmp_novel_dir):
        """polish_chapters 精修后应调 helper 刷新 actual_summary。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        novel_id = "novel_d4_test"

        fm.save_chapter_text(novel_id, 1, "原文" * 200)
        outline = _make_outline_with_chapter(1)
        checkpoint = {
            "outline": outline,
            "chapters": [{"chapter_number": 1, "title": "第1章·测试", "full_text": "原文" * 200}],
            "characters": [],
            "world_setting": {"era": "古代", "location": "九州"},
            "config": {"llm": {}},
        }
        (Path(tmp_novel_dir) / "novels" / novel_id / "checkpoint.json").write_text(
            json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8"
        )

        with patch("src.llm.llm_client.create_llm_client") as mock_create_llm, \
             patch("src.novel.agents.writer.Writer") as MockWriter, \
             patch("src.novel.agents.reviewer.Reviewer") as MockReviewer, \
             patch.object(pipe, "_persist_chapter_actual_summary") as mock_persist:
            mock_create_llm.return_value = MagicMock()
            mock_writer = MockWriter.return_value
            mock_writer.polish_chapter.return_value = "精修文本" * 200
            # critique.issues 非空才走精修分支（issues 为空会 skip）
            mock_issue = MagicMock()
            mock_issue.type = "style"
            mock_issue.severity = "low"
            mock_issue.quote = "x"
            mock_issue.reason = "y"
            mock_reviewer = MockReviewer.return_value
            mock_critique = MagicMock()
            mock_critique.issues = [mock_issue]
            mock_critique.overall_assessment = "需要精修"
            mock_critique.to_writer_prompt.return_value = "改进点"
            mock_reviewer.review.return_value = mock_critique

            pipe.polish_chapters(
                project_path=str(Path(tmp_novel_dir) / "novels" / novel_id),
                start_chapter=1,
                end_chapter=1,
            )

        # helper 应被调用一次（针对 ch1，精修后新文本）
        assert mock_persist.call_count == 1, (
            f"polish 后应调 helper 一次，实际 {mock_persist.call_count}"
        )
        args = mock_persist.call_args.args
        assert args[2] == 1
        assert "精修文本" in args[3]

    def test_apply_feedback_calls_helper_after_save(self, tmp_novel_dir):
        """apply_feedback 重写后应调 helper 刷新 actual_summary（M1 review 加测）。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        novel_id = "novel_d4_test"

        fm.save_chapter_text(novel_id, 1, "原文" * 200)
        outline = _make_outline_with_chapter(1)
        checkpoint = {
            "outline": outline,
            "chapters": [
                {"chapter_number": 1, "title": "第1章·测试", "full_text": "原文" * 200}
            ],
            "characters": [],
            "world_setting": {"era": "古代", "location": "九州"},
            "config": {"llm": {}},
        }
        (Path(tmp_novel_dir) / "novels" / novel_id / "checkpoint.json").write_text(
            json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8"
        )

        # 用 rewrite_instructions 路径绕过 LLM 分析
        rewrite_instructions = {"1": "把主角名字从张三改成李四"}

        with patch("src.llm.llm_client.create_llm_client") as mock_create_llm, \
             patch("src.novel.agents.writer.Writer") as MockWriter, \
             patch("src.novel.services.prev_tail_summarizer.summarize_previous_tail",
                   return_value=""), \
             patch.object(pipe, "_persist_chapter_actual_summary") as mock_persist:
            mock_create_llm.return_value = MagicMock()
            mock_writer = MockWriter.return_value
            mock_writer.rewrite_chapter.return_value = "反馈重写新文本" * 100

            pipe.apply_feedback(
                project_path=str(Path(tmp_novel_dir) / "novels" / novel_id),
                feedback_text="改个名字",
                chapter_number=1,
                rewrite_instructions=rewrite_instructions,
                dry_run=False,
            )

        assert mock_persist.call_count >= 1, (
            f"apply_feedback 后应调 helper，实际 {mock_persist.call_count}"
        )
        args = mock_persist.call_args.args
        assert args[2] == 1
        assert "反馈重写新文本" in args[3]
