"""Writer 跨章复读防御测试

验证 Writer 不再从 state["chapters_text"] / FileManager 读上章原文，
而是只消费 chapter_brief 的结构化摘要（previous_chapter_tail_summary +
previous_chapter_end_hook）。这是修复 ch32 verbatim 复读 bug 的核心断言。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.writer import Writer, writer_node
from src.novel.models.chapter import Chapter, Scene
from src.novel.models.character import (
    Appearance,
    CharacterProfile,
    Personality,
)
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import WorldSetting


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_llm(text: str = "场景输出。") -> MagicMock:
    client = MagicMock()
    client.chat.return_value = LLMResponse(content=text, model="mock-model")
    return client


def _make_outline(chapter_number: int = 32, title: str = "test") -> ChapterOutline:
    return ChapterOutline(
        chapter_number=chapter_number,
        title=title,
        goal="测试目标",
        key_events=["事件1"],
        involved_characters=["主角"],
        estimated_words=2500,
        mood="蓄力",
    )


def _make_world() -> WorldSetting:
    return WorldSetting(era="未知", location="未知")


def _make_scene_plan(scene_number: int = 1, target_words: int = 800) -> dict:
    return {
        "scene_number": scene_number,
        "location": "矿道",
        "time": "黄昏",
        "characters": ["主角"],
        "goal": "场景目标",
        "mood": "紧张",
        "target_words": target_words,
        "narrative_modes": ["动作"],
    }


def _make_fake_chapter(outline: ChapterOutline, text: str = "x" * 500) -> Chapter:
    scene = Scene(
        scene_number=1,
        location="t",
        time="t",
        characters=["主角"],
        goal="t",
        text=text,
        word_count=len(text),
        narrative_modes=[],
    )
    return Chapter(
        chapter_number=outline.chapter_number,
        title=outline.title,
        scenes=[scene],
        full_text=text,
        word_count=len(text),
        outline=outline,
        status="draft",
    )


# ---------------------------------------------------------------------------
# writer_node 测试
# ---------------------------------------------------------------------------


@pytest.mark.signature
class TestWriterNodeNoRawPrev:
    """writer_node 不再读上章原文，只消费 chapter_brief 摘要。"""

    def test_writer_node_ignores_raw_chapters_text(self) -> None:
        """即使 state.chapters_text 有上章原文，Writer 也不应把原文塞进 context。

        同时验证 chapter_brief 的摘要字段会正确注入 context。
        """
        llm = _make_llm()
        outline = _make_outline(chapter_number=32)

        raw_prev_text = (
            "这是上章的原文 abcdefg12345 这是一长段应该被屏蔽的上章内容"
            "……" * 50
        )
        state = {
            "config": {},
            "current_chapter": 32,
            "current_chapter_outline": outline.model_dump(),
            "current_scenes": [_make_scene_plan(1)],
            "characters": [],
            "world_setting": _make_world().model_dump(),
            "style_name": "webnovel.shuangwen",
            "chapters": [],
            "chapters_text": {31: raw_prev_text},
            "chapter_brief": {
                "previous_chapter_tail_summary": "主角在矿道面对俘虏",
                "previous_chapter_end_hook": "是否杀俘",
            },
        }

        captured_kwargs: dict = {}

        def _fake_generate_chapter(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return _make_fake_chapter(outline)

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm), \
             patch.object(Writer, "generate_chapter", side_effect=_fake_generate_chapter):
            result = writer_node(state)

        assert "current_chapter_text" in result
        ctx = captured_kwargs.get("context", "")
        assert "abcdefg12345" not in ctx, (
            "Writer context 不应包含上章原文标记字符串"
        )
        # 摘要内容出现
        assert "矿道" in ctx or "杀俘" in ctx, (
            f"Writer context 应包含 chapter_brief 摘要, got: {ctx!r}"
        )

    def test_writer_node_reads_current_chapter_brief_primary_path(self) -> None:
        """生产链路：chapter_planner_node 把 brief 写到 state["current_chapter_brief"]
        （Pydantic dump）+ state["current_chapter_outline"]["chapter_brief"]（legacy dict）。
        Writer 必须优先从 current_chapter_brief 读，这才是真实 planner→writer 连通的路径。
        """
        llm = _make_llm()
        outline = _make_outline(chapter_number=32)
        outline_dict = outline.model_dump()
        outline_dict["chapter_brief"] = {
            "previous_chapter_tail_summary": "LEGACY_SUMMARY_不应命中",
            "previous_chapter_end_hook": "LEGACY_HOOK_不应命中",
        }

        state = {
            "config": {},
            "current_chapter": 32,
            "current_chapter_outline": outline_dict,
            "current_scenes": [_make_scene_plan(1)],
            "characters": [],
            "world_setting": _make_world().model_dump(),
            "style_name": "webnovel.shuangwen",
            "chapters": [],
            "current_chapter_brief": {
                "previous_chapter_tail_summary": "PRIMARY_主角在矿道",
                "previous_chapter_end_hook": "PRIMARY_是否杀俘",
            },
        }

        captured_kwargs: dict = {}

        def _fake_generate_chapter(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return _make_fake_chapter(outline)

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm), \
             patch.object(Writer, "generate_chapter", side_effect=_fake_generate_chapter):
            writer_node(state)

        ctx = captured_kwargs.get("context", "")
        assert "PRIMARY_主角在矿道" in ctx, (
            f"应从 current_chapter_brief 读摘要, got: {ctx!r}"
        )
        assert "LEGACY" not in ctx, (
            "current_chapter_brief 存在时不应 fallback 到 legacy chapter_brief"
        )

    def test_writer_node_legacy_chapter_brief_fallback(self) -> None:
        """只有 current_chapter_outline.chapter_brief（legacy）时 Writer 能 fallback。

        向后兼容路径：老的节点只写 legacy dict，不写 current_chapter_brief 顶层。
        """
        llm = _make_llm()
        outline = _make_outline(chapter_number=32)
        outline_dict = outline.model_dump()
        outline_dict["chapter_brief"] = {
            "previous_chapter_tail_summary": "LEGACY_主角在山洞",
            "previous_chapter_end_hook": "LEGACY_遇敌",
        }

        state = {
            "config": {},
            "current_chapter": 32,
            "current_chapter_outline": outline_dict,
            "current_scenes": [_make_scene_plan(1)],
            "characters": [],
            "world_setting": _make_world().model_dump(),
            "style_name": "webnovel.shuangwen",
            "chapters": [],
        }

        captured_kwargs: dict = {}

        def _fake_generate_chapter(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return _make_fake_chapter(outline)

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm), \
             patch.object(Writer, "generate_chapter", side_effect=_fake_generate_chapter):
            writer_node(state)

        ctx = captured_kwargs.get("context", "")
        assert "LEGACY_主角在山洞" in ctx or "LEGACY_遇敌" in ctx, (
            f"缺 current_chapter_brief 时应 fallback 到 legacy, got: {ctx!r}"
        )

    def test_writer_node_no_filemanager_call(self) -> None:
        """即使 chapters_text 为空，Writer 也不应 fallback 去调 FileManager.load_chapter_text。"""
        llm = _make_llm()
        outline = _make_outline(chapter_number=32)

        state = {
            "config": {},
            "current_chapter": 32,
            "novel_id": "novel_abc",
            "workspace": "workspace",
            "current_chapter_outline": outline.model_dump(),
            "current_scenes": [_make_scene_plan(1)],
            "characters": [],
            "world_setting": _make_world().model_dump(),
            "style_name": "webnovel.shuangwen",
            "chapters": [],
            "chapters_text": {},
            "chapter_brief": {},
        }

        mock_fm_cls = MagicMock()
        mock_fm_instance = MagicMock()
        mock_fm_cls.return_value = mock_fm_instance

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm), \
             patch.object(Writer, "generate_chapter", return_value=_make_fake_chapter(outline)), \
             patch("src.novel.storage.file_manager.FileManager", mock_fm_cls):
            writer_node(state)

        assert mock_fm_instance.load_chapter_text.call_count == 0, (
            "Writer 不应再通过 FileManager.load_chapter_text 读上章原文"
        )
        # 构造器也不应被调（没有人应该去构造 FileManager 读章节）
        assert mock_fm_cls.call_count == 0, (
            "Writer 不应再构造 FileManager 实例去读上章原文"
        )

    def test_writer_node_chapter_one_empty_context(self) -> None:
        """首章 (current_chapter=1) 没有前章，context 必须是空字符串。"""
        llm = _make_llm()
        outline = _make_outline(chapter_number=1)

        state = {
            "config": {},
            "current_chapter": 1,
            "current_chapter_outline": outline.model_dump(),
            "current_scenes": [_make_scene_plan(1)],
            "characters": [],
            "world_setting": _make_world().model_dump(),
            "style_name": "webnovel.shuangwen",
            "chapters": [],
            # 即使 chapter_brief 意外带了摘要，首章也不应注入（current_chapter>1 才走分支）
            "chapter_brief": {
                "previous_chapter_tail_summary": "不应被使用",
                "previous_chapter_end_hook": "不应被使用",
            },
        }

        captured_kwargs: dict = {}

        def _fake_generate_chapter(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return _make_fake_chapter(outline)

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm), \
             patch.object(Writer, "generate_chapter", side_effect=_fake_generate_chapter):
            writer_node(state)

        assert captured_kwargs.get("context", "MISSING") == "", (
            "首章 context 必须为空字符串"
        )

    def test_writer_node_missing_brief_fields_safe(self) -> None:
        """chapter_brief 缺失字段或为空时不抛异常，context 是空或只含能拼的部分。"""
        llm = _make_llm()
        outline = _make_outline(chapter_number=10)

        # 情况 1：chapter_brief 完全缺失
        state_no_brief = {
            "config": {},
            "current_chapter": 10,
            "current_chapter_outline": outline.model_dump(),
            "current_scenes": [_make_scene_plan(1)],
            "characters": [],
            "world_setting": _make_world().model_dump(),
            "style_name": "webnovel.shuangwen",
            "chapters": [],
        }

        captured: list[dict] = []

        def _fake_generate_chapter(*args, **kwargs):
            captured.append(kwargs)
            return _make_fake_chapter(outline)

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm), \
             patch.object(Writer, "generate_chapter", side_effect=_fake_generate_chapter):
            writer_node(state_no_brief)
        assert captured[-1].get("context", "MISSING") == ""

        # 情况 2：chapter_brief 只有 tail_summary
        state_only_tail = dict(state_no_brief)
        state_only_tail["chapter_brief"] = {"previous_chapter_tail_summary": "只有结尾"}

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm), \
             patch.object(Writer, "generate_chapter", side_effect=_fake_generate_chapter):
            writer_node(state_only_tail)
        ctx_tail = captured[-1].get("context", "")
        assert "只有结尾" in ctx_tail
        assert "上章钩子" not in ctx_tail

        # 情况 3：chapter_brief 只有 end_hook
        state_only_hook = dict(state_no_brief)
        state_only_hook["chapter_brief"] = {"previous_chapter_end_hook": "钩子内容"}

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm), \
             patch.object(Writer, "generate_chapter", side_effect=_fake_generate_chapter):
            writer_node(state_only_hook)
        ctx_hook = captured[-1].get("context", "")
        assert "钩子内容" in ctx_hook
        assert "上章结尾状态" not in ctx_hook

        # 情况 4：字段是 None
        state_none = dict(state_no_brief)
        state_none["chapter_brief"] = {
            "previous_chapter_tail_summary": None,
            "previous_chapter_end_hook": None,
        }
        with patch("src.novel.agents.writer.create_llm_client", return_value=llm), \
             patch.object(Writer, "generate_chapter", side_effect=_fake_generate_chapter):
            writer_node(state_none)
        assert captured[-1].get("context", "MISSING") == ""


# ---------------------------------------------------------------------------
# generate_scene 提示词文案测试
# ---------------------------------------------------------------------------


@pytest.mark.signature
class TestGenerateScenePromptWording:
    """generate_scene 首场景提示词新文案 — 衔接要点 + 严禁照抄。"""

    def test_generate_scene_first_scene_prompt_wording(self) -> None:
        llm = _make_llm("场景输出。")
        writer = Writer(llm)

        writer.generate_scene(
            scene_plan=_make_scene_plan(scene_number=1, target_words=800),
            chapter_outline=_make_outline(chapter_number=32, title="t"),
            characters=[],
            world_setting=_make_world(),
            context="主角在矿道面对俘虏",
            style_name="webnovel.shuangwen",
        )

        user_prompt = llm.chat.call_args[0][0][1]["content"]
        assert "上章衔接要点" in user_prompt, (
            f"首场景 user_prompt 应包含新文案「上章衔接要点」, got preview: {user_prompt[:500]}"
        )
        assert "严禁照抄" in user_prompt, (
            "首场景 user_prompt 应包含「严禁照抄」指令"
        )
        assert "必须从这里接续" not in user_prompt, (
            "旧文案「必须从这里接续」不应再出现"
        )


# ---------------------------------------------------------------------------
# generate_chapter running_context 隔离测试
# ---------------------------------------------------------------------------


@pytest.mark.signature
class TestGenerateChapterRunningContextIsolation:
    """running_context 只包含本章已写场景，不应带跨章 context。"""

    def _setup_sequential_llm(self, texts: list[str]) -> MagicMock:
        client = MagicMock()
        responses = [LLMResponse(content=t, model="mock-model") for t in texts]
        client.chat.side_effect = responses
        return client

    def test_generate_chapter_running_context_no_cross_chapter(self) -> None:
        """第 2 次 LLM call（第二场景）的 user_prompt 不应包含跨章 context token，
        但应包含本章第一场景的 text。"""
        llm = self._setup_sequential_llm(
            [
                "第一场景文本XYZ" * 20,
                "第二场景文本ABC" * 20,
                "第三场景文本MNO" * 20,
            ]
        )
        writer = Writer(llm)
        outline = _make_outline(chapter_number=5)

        writer.generate_chapter(
            chapter_outline=outline,
            scene_plans=[
                _make_scene_plan(scene_number=1, target_words=500),
                _make_scene_plan(scene_number=2, target_words=500),
                _make_scene_plan(scene_number=3, target_words=500),
            ],
            characters=[],
            world_setting=_make_world(),
            context="CROSS_CHAPTER_SUMMARY_UNIQUE_TOKEN",
            style_name="webnovel.shuangwen",
        )

        # 第 2 次 call 对应第二场景
        second_call = llm.chat.call_args_list[1]
        second_user_prompt = second_call[0][0][1]["content"]

        assert "CROSS_CHAPTER_SUMMARY_UNIQUE_TOKEN" not in second_user_prompt, (
            "第二场景 user_prompt 不应包含跨章 context token"
            f"，preview: {second_user_prompt[:500]}"
        )
        assert "第一场景文本XYZ" in second_user_prompt, (
            "第二场景 user_prompt 应包含第一场景 text（scenes_written_summary 或 running_context）"
        )

    def test_generate_chapter_first_scene_uses_context(self) -> None:
        """第 1 次 LLM call（首场景）的 user_prompt 必须包含 context token。"""
        llm = self._setup_sequential_llm(
            [
                "第一场景文本XYZ" * 20,
                "第二场景文本ABC" * 20,
                "第三场景文本MNO" * 20,
            ]
        )
        writer = Writer(llm)
        outline = _make_outline(chapter_number=5)

        writer.generate_chapter(
            chapter_outline=outline,
            scene_plans=[
                _make_scene_plan(scene_number=1, target_words=500),
                _make_scene_plan(scene_number=2, target_words=500),
                _make_scene_plan(scene_number=3, target_words=500),
            ],
            characters=[],
            world_setting=_make_world(),
            context="CROSS_CHAPTER_SUMMARY_UNIQUE_TOKEN",
            style_name="webnovel.shuangwen",
        )

        first_call = llm.chat.call_args_list[0]
        first_user_prompt = first_call[0][0][1]["content"]

        assert "CROSS_CHAPTER_SUMMARY_UNIQUE_TOKEN" in first_user_prompt, (
            "首场景 user_prompt 必须包含 context token（brief 摘要）"
        )
