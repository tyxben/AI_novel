"""P0 集成测试 — chapter_planner_node / brief 持久化 / verbatim 防护端到端

code-reviewer 指出的 CRITICAL 问题的集成层守护：

C1：chapter_planner_node 必须从 state 抽上章 tail 传 propose_chapter_brief。
C2：end_hook 必须进 legacy dict，才能让后续章节的 _lookup_previous_end_hook 命中。
H2：_summarize_previous_tail 遇到 verbatim 重叠必须降级为空。
H3：派生摘要（previous_chapter_tail_summary/end_hook）不应进 legacy dict 落盘。
M2：writer 端到端路径不得把上章原文塞进 LLM messages。
M4：连续章节的 brief 不应缓存失效。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.chapter_planner import ChapterPlanner, chapter_planner_node
from src.novel.agents.writer import Writer, writer_node
from src.novel.models.chapter import Chapter, Scene
from src.novel.models.chapter_brief import ChapterBrief
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import WorldSetting


pytestmark = pytest.mark.signature


# ---------------------------------------------------------------------------
# 公共 fixtures
# ---------------------------------------------------------------------------


def _make_outline(chapter_number: int = 6) -> ChapterOutline:
    return ChapterOutline(
        chapter_number=chapter_number,
        title=f"第{chapter_number}章",
        goal="推进主线",
        key_events=["事件"],
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
# C1 守护：chapter_planner_node 抽 prev_tail
# ---------------------------------------------------------------------------


class _PlannerSpy:
    """Capture the kwargs chapter_planner_node passes to propose_chapter_brief."""

    def __init__(self) -> None:
        self.kwargs: dict = {}

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        # Return a minimal valid proposal so the node completes without error
        brief = ChapterBrief(chapter_number=kwargs["chapter_number"])
        from src.novel.models.chapter_brief import ChapterBriefProposal

        return ChapterBriefProposal(brief=brief, scene_plans=[])


def _build_planner_state(current_chapter: int = 6, **overrides) -> dict:
    base = {
        "config": {},
        "current_chapter": current_chapter,
        "current_chapter_outline": _make_outline(current_chapter).model_dump(),
        "chapters_text": {},
        "chapters": [],
    }
    base.update(overrides)
    return base


def test_chapter_planner_node_passes_prev_tail_from_state() -> None:
    """C1：chapters_text 里有上章 → 取末 500 字并传 propose_chapter_brief."""
    prev_text = "这是第五章的全文内容。" * 100  # well over 500 chars
    state = _build_planner_state(
        current_chapter=6,
        chapters_text={5: prev_text},
    )

    spy = _PlannerSpy()
    with patch(
        "src.novel.agents.chapter_planner.create_llm_client",
        return_value=MagicMock(),
    ), patch.object(ChapterPlanner, "propose_chapter_brief", side_effect=spy):
        chapter_planner_node(state)

    prev_tail = spy.kwargs.get("previous_tail")
    assert prev_tail, "propose_chapter_brief 必须收到非空 previous_tail"
    assert len(prev_tail) <= 500
    # tail must be a suffix of the prev_text
    assert prev_text.endswith(prev_tail)
    # first char should NOT be from the start of prev_text (i.e., we sliced)
    assert prev_tail != prev_text


def test_chapter_planner_node_prev_tail_fallback_from_chapters() -> None:
    """C1 fallback：chapters_text 空，但 chapters[*].full_text 有 → 读后者。"""
    full_text = "第五章 主角在山洞遇险..." + "内容" * 300
    state = _build_planner_state(
        current_chapter=6,
        chapters_text={},
        chapters=[
            {"chapter_number": 5, "full_text": full_text, "title": "t"},
        ],
    )

    spy = _PlannerSpy()
    with patch(
        "src.novel.agents.chapter_planner.create_llm_client",
        return_value=MagicMock(),
    ), patch.object(ChapterPlanner, "propose_chapter_brief", side_effect=spy):
        chapter_planner_node(state)

    prev_tail = spy.kwargs.get("previous_tail")
    assert prev_tail, "fallback 必须从 chapters[*].full_text 取到 previous_tail"
    assert len(prev_tail) <= 500
    assert full_text.endswith(prev_tail)


def test_chapter_planner_node_prev_tail_string_keyed_dict() -> None:
    """C1 防御：chapters_text 意外用字符串 key 时仍能取到."""
    prev_text = "之前章节的原文内容。" * 60
    state = _build_planner_state(
        current_chapter=6,
        chapters_text={"5": prev_text},
    )

    spy = _PlannerSpy()
    with patch(
        "src.novel.agents.chapter_planner.create_llm_client",
        return_value=MagicMock(),
    ), patch.object(ChapterPlanner, "propose_chapter_brief", side_effect=spy):
        chapter_planner_node(state)

    assert spy.kwargs.get("previous_tail"), "字符串 key 时也必须能取到 previous_tail"


def test_chapter_planner_node_first_chapter_no_prev_tail() -> None:
    """C1：首章 previous_tail 必须是空串."""
    state = _build_planner_state(
        current_chapter=1,
        chapters_text={0: "should be ignored"},  # 不应被用
    )

    spy = _PlannerSpy()
    with patch(
        "src.novel.agents.chapter_planner.create_llm_client",
        return_value=MagicMock(),
    ), patch.object(ChapterPlanner, "propose_chapter_brief", side_effect=spy):
        chapter_planner_node(state)

    assert spy.kwargs.get("previous_tail") == ""


def test_chapter_planner_node_missing_prev_tail_graceful() -> None:
    """C1：没有上章文本时 previous_tail=""，node 不抛."""
    state = _build_planner_state(current_chapter=6)  # empty chapters_text / chapters

    spy = _PlannerSpy()
    with patch(
        "src.novel.agents.chapter_planner.create_llm_client",
        return_value=MagicMock(),
    ), patch.object(ChapterPlanner, "propose_chapter_brief", side_effect=spy):
        result = chapter_planner_node(state)

    assert spy.kwargs.get("previous_tail") == ""
    assert "errors" not in result or not any(
        e.get("agent") == "ChapterPlanner" for e in result.get("errors", [])
    )


# ---------------------------------------------------------------------------
# C2 守护：end_hook roundtrip through legacy dict
# ---------------------------------------------------------------------------


def test_end_hook_roundtrip_through_to_legacy() -> None:
    """C2：to_legacy_chapter_brief 必须包含 end_hook，
    且 _lookup_previous_end_hook 能从这份 legacy dict 读出同一个钩子."""
    brief = ChapterBrief(
        chapter_number=5,
        end_hook="黑影掠过",
        end_hook_type="悬疑",
    )
    legacy = brief.to_legacy_chapter_brief()
    assert legacy["end_hook"] == "黑影掠过"
    assert legacy["end_hook_type"] == "悬疑"

    # 构造 novel dict 模拟 chapter_planner_node 落盘后的形态
    novel = {
        "outline": {
            "chapters": [
                {"chapter_number": 5, "chapter_brief": legacy},
            ]
        }
    }
    assert ChapterPlanner._lookup_previous_end_hook(novel, 6) == "黑影掠过"


# ---------------------------------------------------------------------------
# H3 守护：运行时摘要字段不应进 legacy dict
# ---------------------------------------------------------------------------


def test_to_legacy_chapter_brief_excludes_runtime_summary() -> None:
    """H3：previous_chapter_tail_summary / previous_chapter_end_hook
    是运行时派生字段（上章瞬时摘要），必须被 to_legacy_chapter_brief 剔除
    以免落盘到 novel.json 变成 stale data。"""
    brief = ChapterBrief(
        chapter_number=5,
        previous_chapter_tail_summary="X",
        previous_chapter_end_hook="Y",
    )
    legacy = brief.to_legacy_chapter_brief()
    assert "previous_chapter_tail_summary" not in legacy
    assert "previous_chapter_end_hook" not in legacy


# ---------------------------------------------------------------------------
# H2 守护：_summarize_previous_tail 的 verbatim overlap 检查
# ---------------------------------------------------------------------------


def test_summarize_verbatim_overlap_rejected(caplog) -> None:
    """H2：LLM 返回的摘要若与原文有 >=15 字连续重叠 → 降级为空串 + 打 warning."""
    overlap_phrase = "主角在矿道里独自走着一段很远的路"  # 17 chars, definitely >=15
    previous_tail = (
        "某日清晨，" + overlap_phrase + "，思考着如何应对前方的困局。" * 10
    )
    llm = MagicMock()
    # Summary that contains the overlapping substring of length >=15
    llm.chat.return_value = LLMResponse(
        content="概述：" + overlap_phrase + "。",
        model="test",
        usage=None,
    )
    planner = ChapterPlanner(llm, ledger=None)

    with caplog.at_level("WARNING", logger="novel.agents.chapter_planner"):
        result = planner._summarize_previous_tail(previous_tail)

    assert result == ""
    # A warning should have been emitted
    assert any(
        "verbatim" in rec.message.lower() or "verbatim" in rec.getMessage().lower()
        for rec in caplog.records
    ), "verbatim overlap 必须 log.warning"


def test_summarize_no_verbatim_overlap_passes() -> None:
    """H2：正常 LLM 摘要（无 >=15 字重叠）应该通过."""
    previous_tail = "主角在矿道里独自走着，思考着如何应对。" * 5
    llm = MagicMock()
    # Use character-level different summary - no 15 char overlap
    llm.chat.return_value = LLMResponse(
        content="概述主角独自行进，思考应对方案，情绪紧张。",
        model="test",
        usage=None,
    )
    planner = ChapterPlanner(llm, ledger=None)
    result = planner._summarize_previous_tail(previous_tail)
    assert result  # not empty
    assert len(result) <= 200


def test_has_long_verbatim_overlap_helper() -> None:
    """H2 helper 本身的单元测试."""
    source = "某天夜里主角走进了漆黑山洞里面全是怪物等着他去挑战战斗"
    # summary with only a 9-char substring — below default min_len 15
    summary_short = "......主角走进了漆黑山......"
    assert not ChapterPlanner._has_long_verbatim_overlap(
        summary_short, source, min_len=15
    )

    # summary with a 16-char contiguous substring from source
    long_match = "主角走进了漆黑山洞里面全是怪物等"  # 16 chars
    assert len(long_match) >= 15
    assert long_match in source
    summary_long = "前言" + long_match + "后文"
    assert ChapterPlanner._has_long_verbatim_overlap(
        summary_long, source, min_len=15
    )

    # 空输入安全
    assert not ChapterPlanner._has_long_verbatim_overlap("", "abc", 15)
    assert not ChapterPlanner._has_long_verbatim_overlap("abc", "", 15)
    assert not ChapterPlanner._has_long_verbatim_overlap("abc", "abcdef", 15)


# ---------------------------------------------------------------------------
# M4 守护：连续章节的 brief 不串
# ---------------------------------------------------------------------------


def test_writer_node_consecutive_chapters_refresh_brief() -> None:
    """M4：连续 ch2 / ch3 两次 writer_node 调用，
    ch3 读到的应该是 ch3 的 brief 摘要，不应串到 ch2."""
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(content="scene.", model="t")
    contexts: list[str] = []

    def _fake_generate_chapter(*args, **kwargs):
        contexts.append(kwargs.get("context", ""))
        # chapter_number 从 chapter_outline 取
        outline = kwargs.get("chapter_outline") or args[0]
        return _make_fake_chapter(outline)

    # Chapter 2 brief: 摘要 "ch1 摘要"
    state_ch2 = {
        "config": {},
        "current_chapter": 2,
        "current_chapter_outline": _make_outline(2).model_dump(),
        "current_scenes": [_make_scene_plan(1)],
        "characters": [],
        "world_setting": _make_world().model_dump(),
        "style_name": "webnovel.shuangwen",
        "chapters": [],
        "current_chapter_brief": {
            "previous_chapter_tail_summary": "ch1 摘要",
        },
    }

    state_ch3 = {
        "config": {},
        "current_chapter": 3,
        "current_chapter_outline": _make_outline(3).model_dump(),
        "current_scenes": [_make_scene_plan(1)],
        "characters": [],
        "world_setting": _make_world().model_dump(),
        "style_name": "webnovel.shuangwen",
        "chapters": [],
        "current_chapter_brief": {
            "previous_chapter_tail_summary": "ch2 摘要",
        },
    }

    with patch(
        "src.novel.agents.writer.create_llm_client", return_value=llm
    ), patch.object(
        Writer, "generate_chapter", side_effect=_fake_generate_chapter
    ):
        writer_node(state_ch2)
        writer_node(state_ch3)

    assert len(contexts) == 2
    assert "ch1 摘要" in contexts[0]
    assert "ch2 摘要" in contexts[1]
    assert "ch1 摘要" not in contexts[1], (
        "ch3 context 不应泄漏 ch2 的 brief"
    )


# ---------------------------------------------------------------------------
# M2 守护：writer_node 端到端，LLM messages 里不得含上章原文
# ---------------------------------------------------------------------------


def test_writer_node_full_path_no_raw_in_llm_messages() -> None:
    """M2：完整端到端（不 mock generate_chapter），
    断言所有 LLM messages 拼起来不含上章原文标记字符串；
    且含 brief 摘要 SAFE token."""
    sentinel_raw = "abcdefg12345"
    raw_prev_text = ("一段应该被屏蔽的上章内容 " + sentinel_raw + " 更多内容") * 100

    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content="这是生成的场景文本。" * 30, model="t"
    )

    outline = _make_outline(32)
    state = {
        "config": {},
        "current_chapter": 32,
        "current_chapter_outline": outline.model_dump(),
        "current_scenes": [_make_scene_plan(1, target_words=300)],
        "characters": [],
        "world_setting": _make_world().model_dump(),
        "style_name": "webnovel.shuangwen",
        "chapters": [],
        "chapters_text": {31: raw_prev_text},  # 即使 state 里有原文 writer_node 也不应读
        "current_chapter_brief": {
            "previous_chapter_tail_summary": "摘要 SAFE_TOKEN_XYZ",
        },
    }

    with patch("src.novel.agents.writer.create_llm_client", return_value=llm):
        result = writer_node(state)

    assert "current_chapter_text" in result, (
        f"writer_node 失败: {result.get('errors')}"
    )
    # Collect all message content across all LLM chat calls
    all_content_parts: list[str] = []
    for call in llm.chat.call_args_list:
        messages = call.args[0] if call.args else call.kwargs.get("messages")
        for msg in messages or []:
            all_content_parts.append(msg.get("content", ""))
    all_content = "\n".join(all_content_parts)

    assert sentinel_raw not in all_content, (
        f"LLM messages 中泄漏了上章原文 sentinel {sentinel_raw!r}"
    )
    assert "SAFE_TOKEN_XYZ" in all_content, (
        "LLM messages 必须含 brief 摘要 SAFE_TOKEN_XYZ"
    )


# ---------------------------------------------------------------------------
# Pipeline rewrite/polish context 硬化
# ---------------------------------------------------------------------------


def test_rewrite_chapter_prompt_has_verbatim_warning() -> None:
    """C3：rewrite_chapter 的 user_prompt 必须带 '严禁照抄' 警告."""
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(content="重写后的章节内容。" * 100, model="t")

    writer = Writer(llm)
    outline = _make_outline(5)
    original = "原始章节内容。" * 200
    context = "上章结尾的原文" * 20

    writer.rewrite_chapter(
        original_text=original,
        rewrite_instruction="把主角改成女性",
        chapter_outline=outline,
        characters=[],
        world_setting=_make_world(),
        context=context,
        style_name="webnovel.shuangwen",
    )

    first_call = llm.chat.call_args_list[0]
    messages = first_call.kwargs.get("messages") or (
        first_call.args[0] if first_call.args else None
    )
    assert messages, "Writer 必须调 llm.chat 并传 messages"
    user_prompt = messages[1]["content"]
    assert "严禁照抄" in user_prompt, (
        f"rewrite_chapter prompt 必须含 '严禁照抄' 警告. preview: {user_prompt[:400]}"
    )


def test_polish_chapter_prompt_has_verbatim_warning() -> None:
    """C3：polish_chapter 的 user_prompt 必须带 '严禁照抄' 警告."""
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(content="精修后的章节。" * 100, model="t")

    writer = Writer(llm)
    outline = _make_outline(5)
    chapter_text = "原始章节内容。" * 200
    context = "上章结尾的原文" * 20

    writer.polish_chapter(
        chapter_text=chapter_text,
        critique="请修正节奏问题",
        chapter_outline=outline,
        characters=[],
        world_setting=_make_world(),
        context=context,
        style_name="webnovel.shuangwen",
    )

    first_call = llm.chat.call_args_list[0]
    messages = first_call.kwargs.get("messages") or (
        first_call.args[0] if first_call.args else None
    )
    assert messages, "Writer 必须调 llm.chat 并传 messages"
    user_prompt = messages[1]["content"]
    assert "严禁照抄" in user_prompt, (
        f"polish_chapter prompt 必须含 '严禁照抄' 警告. preview: {user_prompt[:400]}"
    )
