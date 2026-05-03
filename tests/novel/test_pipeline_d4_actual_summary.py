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


# ---------------------------------------------------------------------------
# Test: H2 cost optimization — previous_text 文本未变时跳过 LLM
# ---------------------------------------------------------------------------


class TestPersistActualSummaryH2CostOptimization:
    """D4-H2 follow-up: helper 接 previous_text 参数；文本未变时复用现有 actual_summary。

    polish 100 章场景：部分章 polish 实际未改字节（critique.issues 触发但
    polish_chapter 返回原文）。这些章应跳过 LLM 重新生成，节省 LLM call。"""

    def test_skips_llm_when_previous_text_equals_chapter_text(self, tmp_novel_dir):
        """previous_text 与 chapter_text 字节相同 + outline 已有 summary →
        跳过 LLM call，返回现值。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        novel_id = "novel_d4_test"

        # outline 已有 actual_summary（前次写入）
        outline = _make_outline_with_chapter(1)
        outline["chapters"][0]["actual_summary"] = "旧摘要：主角已觉醒"
        state = {"outline": outline}
        # novel.json 同步已有现值
        novel_data = fm.load_novel(novel_id)
        novel_data["outline"]["chapters"][0]["actual_summary"] = "旧摘要：主角已觉醒"
        fm.save_novel(novel_id, novel_data)

        chapter_text = "本章正文" * 30
        with patch.object(pipe, "_generate_actual_summary") as mock_gen:
            result = pipe._persist_chapter_actual_summary(
                fm, novel_id, 1, chapter_text, "第1章·测试",
                state=state, previous_text=chapter_text,
            )

        # H2 核心：未调 LLM
        mock_gen.assert_not_called()
        # 返回沿用现值
        assert result == "旧摘要：主角已觉醒"
        # outline 未被改写
        assert state["outline"]["chapters"][0]["actual_summary"] == "旧摘要：主角已觉醒"

    def test_calls_llm_when_previous_text_differs(self, tmp_novel_dir):
        """previous_text 与 chapter_text 不同 → 仍调 LLM 生成新 summary。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        state = {"outline": _make_outline_with_chapter(1)}

        with patch.object(
            pipe, "_generate_actual_summary",
            return_value="新摘要：主角拜师入门",
        ) as mock_gen:
            result = pipe._persist_chapter_actual_summary(
                fm, "novel_d4_test", 1, "新文本" * 50,
                "第1章·测试",
                state=state, previous_text="原文" * 50,
            )

        mock_gen.assert_called_once()
        assert result == "新摘要：主角拜师入门"
        assert state["outline"]["chapters"][0]["actual_summary"] == "新摘要：主角拜师入门"

    def test_calls_llm_when_previous_text_equal_but_no_existing_summary(
        self, tmp_novel_dir
    ):
        """previous_text == chapter_text 但 outline 无现值 → 仍走 LLM 兜底首次回填。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        state = {"outline": _make_outline_with_chapter(1)}  # 无 actual_summary

        chapter_text = "本章正文" * 30
        with patch.object(
            pipe, "_generate_actual_summary",
            return_value="首次摘要",
        ) as mock_gen:
            result = pipe._persist_chapter_actual_summary(
                fm, "novel_d4_test", 1, chapter_text, "第1章·测试",
                state=state, previous_text=chapter_text,
            )

        # 无现值时仍生成（避免永远空白）
        mock_gen.assert_called_once()
        assert result == "首次摘要"

    def test_omitting_previous_text_always_generates(self, tmp_novel_dir):
        """主循环新章路径：未传 previous_text → 永远调 LLM 生成（D4 主修行为不变）。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        # outline 已有现值，但未传 previous_text → 不该跳过
        outline = _make_outline_with_chapter(1)
        outline["chapters"][0]["actual_summary"] = "旧值"
        state = {"outline": outline}

        with patch.object(
            pipe, "_generate_actual_summary",
            return_value="新主循环摘要",
        ) as mock_gen:
            pipe._persist_chapter_actual_summary(
                fm, "novel_d4_test", 1, "正文" * 30,
                "第1章·测试", state=state,
            )

        # 默认行为：永远生成（兼容 D4 主修原契约）
        mock_gen.assert_called_once()
        assert state["outline"]["chapters"][0]["actual_summary"] == "新主循环摘要"


class TestPolishPathPassesPreviousText:
    """D4-H2 接入点回归：polish/apply_feedback/rewrite_affected 三路径必须显式传
    previous_text，否则 H2 优化失效。"""

    def test_polish_chapters_passes_previous_text(self, tmp_novel_dir):
        """polish_chapters 路径下，helper 调用必须带 previous_text=原 chapter_text。"""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=str(tmp_novel_dir))
        fm = FileManager(str(tmp_novel_dir))
        novel_id = "novel_d4_test"

        original_text = "原文" * 200
        fm.save_chapter_text(novel_id, 1, original_text)
        outline = _make_outline_with_chapter(1)
        checkpoint = {
            "outline": outline,
            "chapters": [{"chapter_number": 1, "title": "第1章·测试", "full_text": original_text}],
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
            mock_writer.polish_chapter.return_value = "精修后" * 200
            mock_issue = MagicMock(type="style", severity="low", quote="x", reason="y")
            mock_reviewer = MockReviewer.return_value
            mock_crit = MagicMock(issues=[mock_issue], overall_assessment="x")
            mock_crit.to_writer_prompt.return_value = "改"
            mock_reviewer.review.return_value = mock_crit

            pipe.polish_chapters(
                project_path=str(Path(tmp_novel_dir) / "novels" / novel_id),
                start_chapter=1, end_chapter=1,
            )

        assert mock_persist.call_count == 1
        kwargs = mock_persist.call_args.kwargs
        assert kwargs.get("previous_text") == original_text, (
            f"polish 必须传 previous_text=原文以触发 H2 跳过，实际 kwargs: {kwargs}"
        )

    def test_main_loop_backfill_uses_helper_not_inline_llm(self):
        """M2 静态契约：generate_chapters backfill 块应调 _persist_chapter_actual_summary
        helper，不应再直接调 _generate_actual_summary（旧路径会绕过类型校验/失败 log
        统一行为）。验证主循环 backfill 节点重构到 helper 路径。"""
        import inspect
        from src.novel.pipeline import NovelPipeline

        src = inspect.getsource(NovelPipeline.generate_chapters)
        # 找到 backfill 段落（"自动补全 actual_summary" 注释或 log）
        backfill_idx = src.find("发现 %d 章需要补全 actual_summary")
        assert backfill_idx > 0, "找不到 backfill 块标记"
        # 取该段落 +/- 1500 字符为 backfill 上下文（避免误命中主循环 helper 调用）
        start = max(0, backfill_idx - 200)
        end = min(len(src), backfill_idx + 1500)
        backfill_block = src[start:end]
        # 必须调 helper（M2 修复后行为）
        assert "_persist_chapter_actual_summary" in backfill_block, (
            "M2 backfill 块应调用 _persist_chapter_actual_summary helper"
        )
        # 不应再写 ch["actual_summary"] = summary inline（旧路径已被 helper 取代）
        assert 'ch["actual_summary"] = summary' not in backfill_block, (
            "M2: backfill 块不应再 inline 写 outline；应交由 helper 统一处理"
        )
