"""Tests for the post_writer chapter-level sanitize node + graph wiring.

post_writer 是 B 阶段瘦身产物（2026-04-27），插在 writer 和 reviewer 之间，
跑 chapter-level ``sanitize_chapter_text`` 兜底。本文件覆盖：

1. 节点本身：sanitize 行为、空文本/None 处理、决策日志、completed_nodes
2. graph 拓扑：post_writer 节点确实在 _get_node_functions() 返回值里
3. _ChapterRunner fallback 调用顺序：writer → post_writer → reviewer
"""

from __future__ import annotations

from typing import Any

from src.novel.agents.post_writer import post_writer_node


class TestPostWriterNode:
    def test_clean_text_passthrough(self) -> None:
        """无 UI 元素的文本不应被改动（只清空白）。"""
        text = "他走进房间。她笑了。窗外下着雨。"
        out = post_writer_node({"current_chapter_text": text})
        assert out["current_chapter_text"] == text
        assert out["completed_nodes"] == ["post_writer"]

    def test_strips_ui_elements(self) -> None:
        text = "他走进房间。【系统】检测到敌人。她笑了。"
        out = post_writer_node({"current_chapter_text": text})
        assert "【系统】" not in out["current_chapter_text"]
        assert "他走进房间" in out["current_chapter_text"]
        assert "她笑了" in out["current_chapter_text"]

    def test_decision_logged_when_text_changed(self) -> None:
        """文本被清洗后应记录 decision，含 delta_chars。"""
        text = "他走进房间。【系统】检测到敌人。她笑了。"
        out = post_writer_node({"current_chapter_text": text})
        decisions = out.get("decisions", [])
        assert len(decisions) == 1
        d = decisions[0]
        assert d["agent"] == "PostWriter"
        assert d["step"] == "sanitize"
        assert d["data"]["delta_chars"] > 0

    def test_no_decision_when_text_unchanged(self) -> None:
        text = "纯净文本。没有 UI 元素。"
        out = post_writer_node({"current_chapter_text": text})
        # 文本未变 → 不应记 sanitize decision
        assert out.get("decisions", []) == []

    def test_empty_text_skip_with_decision(self) -> None:
        out = post_writer_node({"current_chapter_text": ""})
        # 空文本走 skip 分支，记一条 decision，completed_nodes 仍设
        assert "current_chapter_text" not in out
        decisions = out["decisions"]
        assert len(decisions) == 1
        assert decisions[0]["step"] == "skip"
        assert out["completed_nodes"] == ["post_writer"]

    def test_missing_text_key_skip(self) -> None:
        """state 完全没有 current_chapter_text 也走 skip。"""
        out = post_writer_node({})
        assert "current_chapter_text" not in out
        assert out["decisions"][0]["step"] == "skip"
        assert out["completed_nodes"] == ["post_writer"]

    def test_keeps_allowlisted_marker(self) -> None:
        text = "他打开宝箱。【叮！】系统提示音响起。"
        out = post_writer_node({"current_chapter_text": text})
        assert "【叮！】" in out["current_chapter_text"]


class TestGraphWiring:
    def test_post_writer_in_node_functions(self) -> None:
        from src.novel.agents.graph import _get_node_functions

        nodes = _get_node_functions()
        assert "post_writer" in nodes
        assert callable(nodes["post_writer"])

    def test_chapter_runner_invokes_post_writer_between_writer_and_reviewer(
        self,
    ) -> None:
        """fallback runner 必须按 writer → post_writer → reviewer 顺序调。"""
        from src.novel.agents.graph import _ChapterRunner

        call_order: list[str] = []

        def make_node(name: str, returns: dict[str, Any]):
            def _fn(state: dict) -> dict[str, Any]:
                call_order.append(name)
                return returns

            return _fn

        nodes = {
            "chapter_planner": make_node(
                "chapter_planner",
                {"current_chapter_outline": {"chapter_number": 1}},
            ),
            "writer": make_node(
                "writer",
                {"current_chapter_text": "他【系统】走开。"},
            ),
            "post_writer": post_writer_node,  # 跑真的，不 mock
            "reviewer": make_node("reviewer", {"current_chapter_quality": {}}),
            "state_writeback": make_node("state_writeback", {}),
        }

        runner = _ChapterRunner(nodes=nodes)
        final = runner.invoke({})

        assert call_order == [
            "chapter_planner",
            "writer",
            "reviewer",
            "state_writeback",
        ]
        # post_writer 跑了真函数没记 call_order，但应该已清洗 writer 输出
        assert "【系统】" not in final["current_chapter_text"]
        assert "他" in final["current_chapter_text"]

    def test_chapter_runner_post_writer_optional(self) -> None:
        """fallback 在缺 post_writer 时仍能跑（向后兼容旧 mock）。"""
        from src.novel.agents.graph import _ChapterRunner

        nodes = {
            "chapter_planner": lambda s: {"current_chapter_outline": {}},
            "writer": lambda s: {"current_chapter_text": "正文。"},
            "reviewer": lambda s: {"current_chapter_quality": {}},
            # 没 post_writer / state_writeback
        }
        runner = _ChapterRunner(nodes=nodes)
        final = runner.invoke({})
        # 没 post_writer 也能跑；没清洗 raw 也保留
        assert final["current_chapter_text"] == "正文。"

    def test_writer_no_longer_sanitizes_chapter_level(self) -> None:
        """B 阶段瘦身后 generate_chapter 末尾不再调 _sanitize_chapter_text。

        这是行为契约：post_writer 节点接管 chapter-level 兜底，Writer
        不应再做。借此防止有人加回那行冗余调用。
        """
        import inspect

        from src.novel.agents import writer as writer_mod

        src = inspect.getsource(writer_mod.Writer.generate_chapter)
        # 章节级 join 后不应再有 _sanitize_chapter_text 调用
        # （per-scene 调用在 generate_scene 里，不在 generate_chapter 源码内）
        assert "_sanitize_chapter_text(full_text)" not in src


class TestPipelineDirectCallPathHasSanitize:
    """B 阶段 review H2 防回归：pipeline 直调路径（不经 post_writer 节点）
    必须自己跑 sanitize 兜底，否则 polish/rewrite 章节里 UI 元素会落盘。"""

    def test_rewrite_chapter_strips_ui_elements(self) -> None:
        from unittest.mock import MagicMock

        from src.llm.llm_client import LLMResponse
        from src.novel.agents.writer import Writer
        from src.novel.models.novel import ChapterOutline

        leaky = (
            "他走进房间。【系统】检测到敌人。她笑了。" * 5
        )
        llm = MagicMock()
        llm.chat.return_value = LLMResponse(content=leaky, model="m")

        outline = ChapterOutline(
            chapter_number=1,
            title="测试",
            goal="测试",
            key_events=["事件"],
            estimated_words=1000,
            mood="蓄力",
        )

        writer = Writer(llm)
        out = writer.rewrite_chapter(
            original_text="原文" * 100,
            rewrite_instruction="改",
            chapter_outline=outline,
            characters=[],
            world_setting=__import__(
                "src.novel.models.world", fromlist=["WorldSetting"]
            ).WorldSetting(era="今", location="此"),
            context="",
            style_name="webnovel.shuangwen",
            is_propagation=False,
        )
        assert "【系统】" not in out
        assert "他走进房间" in out

    def test_polish_chapter_strips_ui_elements(self) -> None:
        from unittest.mock import MagicMock

        from src.llm.llm_client import LLMResponse
        from src.novel.agents.writer import Writer
        from src.novel.models.novel import ChapterOutline

        leaky = (
            "精修后的文本。【系统】检测到敌人。继续推进剧情。" * 5
        )
        llm = MagicMock()
        llm.chat.return_value = LLMResponse(content=leaky, model="m")

        outline = ChapterOutline(
            chapter_number=1,
            title="测试",
            goal="测试",
            key_events=["事件"],
            estimated_words=1000,
            mood="蓄力",
        )

        writer = Writer(llm)
        out = writer.polish_chapter(
            chapter_text="原文" * 100,
            critique="改一下",
            chapter_outline=outline,
            characters=[],
            world_setting=__import__(
                "src.novel.models.world", fromlist=["WorldSetting"]
            ).WorldSetting(era="今", location="此"),
            context="",
            style_name="webnovel.shuangwen",
        )
        assert "【系统】" not in out
        assert "精修后的文本" in out
