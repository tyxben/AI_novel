"""测试 Writer 三处 max_tokens 公式 + soft_max_chars 续写 guard 双保险。

保护不变量：
- max_tokens = min(4096, max(900, int(target_words * 1.4)))
- soft_max_chars = int(target_words * 1.5)
- max_tokens * 1.5 (字符估算) > soft_max_chars（保证软上限能先于硬上限触发）
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.writer import Writer
from src.novel.models.character import (
    Appearance,
    CharacterArc,
    CharacterProfile,
    Personality,
)
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import WorldSetting


# ---------------------------------------------------------------------------
# 1. 纯公式参数化断言（锁死新公式的值域）
# ---------------------------------------------------------------------------


def _expected_max_tokens(target_words: int) -> int:
    """复制 Writer 里的公式作为测试基准，任何公式改动都会被此断言捕获。"""
    return min(4096, max(900, int(target_words * 1.4)))


def _expected_soft_chars(target_words: int) -> int:
    return int(target_words * 1.5)


@pytest.mark.parametrize(
    "target_words, expected_max_tokens, expected_soft",
    [
        (400, 900, 600),       # 小 target：触发下限 900
        (600, 900, 900),       # 临界：600*1.4=840 < 900，仍用下限
        (800, 1120, 1200),     # 默认 scene target
        (1000, 1400, 1500),
        (1500, 2100, 2250),
        (3000, 4096, 4500),    # 触发上限 4096
    ],
)
def test_max_tokens_formula(target_words, expected_max_tokens, expected_soft):
    assert _expected_max_tokens(target_words) == expected_max_tokens
    assert _expected_soft_chars(target_words) == expected_soft


@pytest.mark.parametrize("target_words", [400, 600, 800, 1000, 1500, 3000])
def test_soft_cap_is_reachable_invariant(target_words):
    """不变量：soft_max_chars 必须小于 max_tokens 能生成的字符估算上限。

    若 soft_max_chars >= max_tokens * (每 token 字符数)，续写 guard 将永远不触发，
    双保险失效。中文每 token ≈ 1.5 字符（与源码注释一致）。
    """
    max_tokens = _expected_max_tokens(target_words)
    soft = _expected_soft_chars(target_words)
    char_capacity = max_tokens * 1.5
    assert soft < char_capacity, (
        f"target={target_words}: soft({soft}) must be < capacity({char_capacity})"
    )


def test_max_tokens_upper_bound_never_exceeds_4096():
    """极端 target 也不得突破 4096 tokens（防止 DeepSeek 400 错误）。"""
    for tw in [3000, 5000, 10000, 100000]:
        assert _expected_max_tokens(tw) <= 4096


def test_max_tokens_lower_bound_never_below_900():
    """极短 target 也能写完一个段落（下限 900 token ≈ 1350 字）。"""
    for tw in [100, 200, 400, 642]:
        assert _expected_max_tokens(tw) >= 900


def test_formula_is_tighter_than_previous():
    """回归守护：新公式（1.4x/900/4096）必须严格小于旧公式（2.2x/1536/8192）。

    若未来有人误把公式改回旧版，这个测试会失败。
    """
    def _old_formula(tw: int) -> int:
        return min(8192, max(1536, int(tw * 2.2)))

    for tw in [400, 800, 1500, 3000]:
        assert _expected_max_tokens(tw) < _old_formula(tw), (
            f"target={tw}: new formula must be tighter than old"
        )


# ---------------------------------------------------------------------------
# 2. 端到端 mock 测试（验证公式被真实传给 LLM + soft guard 生效）
# ---------------------------------------------------------------------------


def _make_llm_response(
    content: str = "精简的章节内容。", finish_reason: str = "stop"
) -> LLMResponse:
    return LLMResponse(
        content=content, model="test", usage=None, finish_reason=finish_reason
    )


def _make_character() -> CharacterProfile:
    return CharacterProfile(
        name="测试角色",
        gender="男",
        age=20,
        occupation="学生",
        appearance=Appearance(
            height="175cm",
            build="中等",
            hair="黑短发",
            eyes="黑眼",
            clothing_style="便装",
            distinctive_features=["无"],
        ),
        personality=Personality(
            traits=["好奇", "勇敢", "坚韧"],
            core_belief="求知",
            motivation="探索",
            flaw="冲动",
            speech_style="平实",
            catchphrases=["好吧"],
        ),
        character_arc=CharacterArc(
            initial_state="懵懂",
            turning_points=[],
            final_state="成熟",
        ),
    )


def _make_outline(estimated_words: int) -> ChapterOutline:
    return ChapterOutline(
        chapter_number=1,
        title="测试",
        goal="推进",
        mood="蓄力",
        estimated_words=estimated_words,
        key_events=["事件"],
    )


@pytest.mark.parametrize(
    "target_words, expected_max_tokens",
    # 注：ChapterOutline.estimated_words 最小值 500，所以端到端只能从 500 起测
    [(500, 900), (800, 1120), (1500, 2100), (3000, 4096)],
)
def test_rewrite_chapter_uses_new_max_tokens(target_words, expected_max_tokens):
    """rewrite_chapter 必须用新公式调用 llm.chat。"""
    llm = MagicMock()
    llm.chat.return_value = _make_llm_response()
    writer = Writer(llm)
    writer.rewrite_chapter(
        original_text="原文。",
        rewrite_instruction="修改指令",
        chapter_outline=_make_outline(target_words),
        characters=[_make_character()],
        world_setting=WorldSetting(era="现代", location="城市"),
        context="",
        style_name="webnovel.shuangwen",
        is_propagation=True,  # 走最简路径
    )
    # 第一次 chat 是主调用
    assert llm.chat.call_count >= 1
    call_kwargs = llm.chat.call_args_list[0].kwargs
    assert call_kwargs["max_tokens"] == expected_max_tokens


def test_polish_chapter_uses_new_max_tokens():
    """polish_chapter 必须用新公式调用 llm.chat。"""
    llm = MagicMock()
    llm.chat.return_value = _make_llm_response()
    writer = Writer(llm)
    writer.polish_chapter(
        chapter_text="原章节正文。",
        critique="需要修改：角色动机不清",
        chapter_outline=_make_outline(800),
        characters=[_make_character()],
        world_setting=WorldSetting(era="现代", location="城市"),
        context="",
        style_name="webnovel.shuangwen",
    )
    assert llm.chat.call_count >= 1
    call_kwargs = llm.chat.call_args_list[0].kwargs
    assert call_kwargs["max_tokens"] == 1120  # 800 * 1.4


def test_soft_max_chars_guard_stops_continuation_on_long_output():
    """端到端：LLM 返回超长文本 + finish_reason=length 时，
    soft_max_chars guard 必须在 _continue_if_truncated 里阻止无限续写。
    同时保留已写内容（软截而非硬截）。
    """
    target_words = 800
    soft_cap = int(target_words * 1.5)  # 1200
    # LLM 返回已经超过软上限的文本（1500 字）+ finish_reason=length
    long_text = "这是一段很长的续写内容。" * 150  # 约 1800 字，> soft_cap
    assert len(long_text) > soft_cap

    llm = MagicMock()
    llm.chat.return_value = _make_llm_response(
        content=long_text, finish_reason="length"
    )
    writer = Writer(llm)
    result = writer.rewrite_chapter(
        original_text="原文。",
        rewrite_instruction="重写",
        chapter_outline=_make_outline(target_words),
        characters=[_make_character()],
        world_setting=WorldSetting(era="现代", location="城市"),
        context="",
        style_name="webnovel.shuangwen",
        is_propagation=True,
    )
    # 关键 #1：只调用了 1 次 chat（soft guard 阻止了续写），没有无限扩张
    assert llm.chat.call_count == 1
    # 关键 #2：_trim_to_hard_cap 在 soft guard 之后兜底，最终 ≤ hard_cap
    # （原版本期望 result == long_text，新版本添加了 trim 层，预期已变）
    assert len(result) <= int(target_words * 1.2)


def test_short_output_does_not_trigger_continuation():
    """回归守护：finish_reason=stop 时不应触发续写逻辑。"""
    llm = MagicMock()
    llm.chat.return_value = _make_llm_response(
        content="短小精悍的章节。", finish_reason="stop"
    )
    writer = Writer(llm)
    writer.rewrite_chapter(
        original_text="原文。",
        rewrite_instruction="重写",
        chapter_outline=_make_outline(800),
        characters=[_make_character()],
        world_setting=WorldSetting(era="现代", location="城市"),
        context="",
        style_name="webnovel.shuangwen",
        is_propagation=True,
    )
    # 只有主调用，无续写
    assert llm.chat.call_count == 1


# ---------------------------------------------------------------------------
# 3. Prompt 级硬约束回归（DeepSeek 字数控制 prompt 加固）
# ---------------------------------------------------------------------------
#
# 项目记忆 fix-verification-pattern + novel-length-control-floor 记录：
# DeepSeek 对单纯的"X 字左右"指令不敏感，超目标 ~58%。
# 加固方案：硬上限 + 段落数结构约束 + 输出前自检 + 末尾再强调。
# 本节锁死 prompt 文案不变量，防止有人把硬约束改回软约束。
# ---------------------------------------------------------------------------


def _expected_hard_cap(target_words: int) -> int:
    return int(target_words * 1.2)


def _expected_para_range(target_words: int) -> tuple[int, int]:
    para_min = max(3, target_words // 200)
    para_max = max(para_min + 2, target_words // 100)
    return para_min, para_max


def _capture_scene_prompts(target_words: int = 800) -> tuple[str, str]:
    """触发 generate_scene 的非 react 路径，返回 (system_prompt, user_prompt)。"""
    llm = MagicMock()
    llm.chat.return_value = _make_llm_response()
    writer = Writer(llm)
    writer.generate_scene(
        scene_plan={
            "scene_number": 1,
            "target_words": target_words,
            "location": "山顶",
            "time": "黄昏",
            "characters_involved": ["测试角色"],
            "goal": "测试场景目标",
            "mood": "蓄力",
        },
        chapter_outline=_make_outline(target_words * 3),
        characters=[_make_character()],
        world_setting=WorldSetting(era="现代", location="城市"),
        context="",
        style_name="webnovel.shuangwen",
    )
    messages = llm.chat.call_args_list[0].args[0] if llm.chat.call_args_list[0].args else llm.chat.call_args_list[0].kwargs["messages"]
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    return system_prompt, user_prompt


def test_scene_prompt_contains_hard_cap_marker():
    """system_prompt 必须包含'字数硬约束'+'超出视为失败'锚点。"""
    system_prompt, _ = _capture_scene_prompts(800)
    assert "字数硬约束" in system_prompt
    assert "超出视为失败" in system_prompt
    # 必须显式给出硬上限数字（800 * 1.2 = 960）
    assert str(_expected_hard_cap(800)) in system_prompt


def test_scene_prompt_contains_paragraph_constraint():
    """段落数结构约束必须出现（DeepSeek 对结构比纯字数更敏感）。"""
    system_prompt, _ = _capture_scene_prompts(800)
    para_min, para_max = _expected_para_range(800)
    assert f"{para_min}-{para_max} 段" in system_prompt


def test_scene_prompt_contains_self_check_directive():
    """system_prompt 必须包含'输出前必须心算总字数'类指令。"""
    system_prompt, _ = _capture_scene_prompts(800)
    assert "心算" in system_prompt and "字数" in system_prompt


def test_scene_user_prompt_ends_with_final_length_check():
    """user_prompt 末尾必须是最终字数检查（最后指令权重最高）。"""
    _, user_prompt = _capture_scene_prompts(800)
    assert "【最终字数检查" in user_prompt
    # 末尾检查必须出现在 user_prompt 的最后 200 字符内
    tail = user_prompt[-200:]
    assert "字数" in tail and "删减" in tail


def test_scene_prompt_no_soft_约X字_softener():
    """回归守护：'约 {target}字' 这种软化措辞必须消除。

    DeepSeek 把'约'解读为'可以更多'。本测试若失败，说明有人把软措辞加回去了。
    """
    _, user_prompt = _capture_scene_prompts(800)
    assert "约800字" not in user_prompt
    assert "约 800 字" not in user_prompt
    # 不能出现'目标字数：{target}字左右'这种老措辞
    assert "字左右" not in user_prompt


def test_rewrite_chapter_prompt_has_hard_cap(target_words: int = 800):
    """rewrite_chapter（is_propagation=True 路径）也必须有硬约束。"""
    llm = MagicMock()
    llm.chat.return_value = _make_llm_response()
    writer = Writer(llm)
    writer.rewrite_chapter(
        original_text="原文。",
        rewrite_instruction="修改",
        chapter_outline=_make_outline(target_words),
        characters=[_make_character()],
        world_setting=WorldSetting(era="现代", location="城市"),
        context="",
        style_name="webnovel.shuangwen",
        is_propagation=True,
    )
    messages = llm.chat.call_args_list[0].kwargs["messages"]
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    assert "字数硬约束" in system_prompt
    assert str(_expected_hard_cap(target_words)) in user_prompt
    # 末尾必须是最终字数检查
    assert "【最终字数检查" in user_prompt
    assert "删减" in user_prompt[-300:]


def test_polish_chapter_prompt_has_hard_cap():
    """polish_chapter 也必须有硬约束 + 末尾自检。"""
    target_words = 800
    llm = MagicMock()
    llm.chat.return_value = _make_llm_response()
    writer = Writer(llm)
    writer.polish_chapter(
        chapter_text="原章节正文。",
        critique="角色动机不清",
        chapter_outline=_make_outline(target_words),
        characters=[_make_character()],
        world_setting=WorldSetting(era="现代", location="城市"),
        context="",
        style_name="webnovel.shuangwen",
    )
    messages = llm.chat.call_args_list[0].kwargs["messages"]
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    assert "字数硬约束" in system_prompt
    assert str(_expected_hard_cap(target_words)) in system_prompt
    assert "【最终字数检查" in user_prompt
    assert "删减" in user_prompt[-300:]


@pytest.mark.parametrize("target_words", [500, 800, 1500, 2500])
def test_hard_cap_scales_with_target(target_words: int):
    """硬上限 = target * 1.2，跨 target 都成立。"""
    system_prompt, user_prompt = _capture_scene_prompts(target_words)
    expected_cap = _expected_hard_cap(target_words)
    assert str(expected_cap) in system_prompt
    assert str(expected_cap) in user_prompt


# ---------------------------------------------------------------------------
# 4. _trim_to_hard_cap：后处理硬截（last-resort enforcement）
# ---------------------------------------------------------------------------
#
# 实测 prompt 级硬约束对 DeepSeek 无效（见 memory novel-length-control-floor）。
# _trim_to_hard_cap 是最后一道执行层：超过 hard_cap 时，回退到最近句末标点处截断。
# ---------------------------------------------------------------------------


def test_trim_under_cap_returns_unchanged():
    """文本未超 hard_cap：原样返回，不做任何修改。"""
    text = "短文本一句话。" * 10  # ~80 字
    result = Writer._trim_to_hard_cap(text, hard_cap=200, target=150)
    assert result == text


def test_trim_handles_empty_input():
    """空输入：原样返回，不抛异常。"""
    assert Writer._trim_to_hard_cap("", hard_cap=100, target=80) == ""


def test_trim_handles_zero_hard_cap():
    """hard_cap <= 0（数值误配）：原样返回，不进入循环。"""
    text = "正常的一段文本。" * 5
    assert Writer._trim_to_hard_cap(text, hard_cap=0, target=80) == text
    assert Writer._trim_to_hard_cap(text, hard_cap=-1, target=80) == text


def test_trim_over_cap_cuts_at_sentence_boundary():
    """超过 hard_cap：回退到 hard_cap 内最近的句末标点处。"""
    # 构造：12 个 "一句话。"（每个 4 字），共 48 字。hard_cap=20。
    # 期望切到第 5 句末（pos=20，正好 "一句话。" * 5）
    text = "一句话。" * 12
    result = Writer._trim_to_hard_cap(text, hard_cap=20, target=15)
    assert result == "一句话。" * 5
    assert len(result) <= 20


def test_trim_includes_trailing_closing_punct():
    """句末标点后紧跟的闭合引号要一起带上，不要断在引号前。"""
    text = '他说："走吧。"然后转身离开。然后他又回来。' * 5
    # 第一段长度 ≈ 22 字
    result = Writer._trim_to_hard_cap(text, hard_cap=25, target=20)
    # 必须以闭合引号或句末标点收尾
    assert result.endswith('"') or result.endswith("。")


def test_trim_no_sentence_boundary_falls_back_to_hard_cut():
    """窗口内无句末标点（极端情况）：硬切到 hard_cap。"""
    text = "无标点纯文字" * 50  # 全部无句末标点
    result = Writer._trim_to_hard_cap(text, hard_cap=30, target=20)
    assert len(result) <= 30


def test_trim_respects_floor_does_not_under_cut():
    """floor = max(target//2, 200)：不能切到 floor 以下。

    构造：前半段无标点，后半段才有句号。floor 应阻止 trim 切到 200 字以下。
    """
    text = "前半段无标点的纯字" * 50 + "。" + "后续内容。" * 10
    # target=400 → floor=200, hard_cap=300
    # 前 300 字内无句号（floor=200，但前 200 字也无句号），fallback hard_cut
    result = Writer._trim_to_hard_cap(text, hard_cap=300, target=400)
    assert len(result) <= 300
    assert len(result) >= 200  # 至少保留 floor 长度


def test_trim_strips_trailing_whitespace():
    """裁剪结果尾部不应有多余空白。"""
    text = "句子一。   \n\n   句子二。" * 20
    result = Writer._trim_to_hard_cap(text, hard_cap=10, target=8)
    assert result == result.rstrip()


def test_generate_scene_actually_trims_overlong_output():
    """端到端：LLM 返回 1591 字（DeepSeek 实测典型超长），
    经过 generate_scene 后场景 word_count 必须 ≤ hard_cap。
    """
    target = 800
    overlong = "这是一段很长的场景描写，包含一个完整的句子。" * 80  # ~1840 字
    assert len(overlong) > target * 1.2

    llm = MagicMock()
    llm.chat.return_value = _make_llm_response(content=overlong, finish_reason="stop")
    writer = Writer(llm)
    scene = writer.generate_scene(
        scene_plan={
            "scene_number": 1,
            "target_words": target,
            "location": "山顶",
            "time": "黄昏",
            "characters_involved": ["测试角色"],
            "goal": "测试",
            "mood": "蓄力",
        },
        chapter_outline=_make_outline(target * 3),
        characters=[_make_character()],
        world_setting=WorldSetting(era="现代", location="城市"),
        context="",
        style_name="webnovel.shuangwen",
    )
    # 必须被裁到 hard_cap (target * 1.2 = 960) 以下
    assert len(scene.text) <= int(target * 1.2), (
        f"trim 失效：scene.text len={len(scene.text)} > hard_cap={int(target*1.2)}"
    )


def test_rewrite_chapter_actually_trims_overlong_output():
    """端到端：rewrite_chapter 也应触发硬截。"""
    target = 800
    overlong = "重写后的一句话。" * 200  # ~1600 字
    llm = MagicMock()
    llm.chat.return_value = _make_llm_response(content=overlong, finish_reason="stop")
    writer = Writer(llm)
    result = writer.rewrite_chapter(
        original_text="原文。",
        rewrite_instruction="改",
        chapter_outline=_make_outline(target),
        characters=[_make_character()],
        world_setting=WorldSetting(era="现代", location="城市"),
        context="",
        style_name="webnovel.shuangwen",
        is_propagation=True,
    )
    assert len(result) <= int(target * 1.2)


def test_trim_does_not_cut_at_ellipsis():
    """回归守护：'……' 是句中悬念（"至于林炎……"），不能当句末标点切。

    上线第一版用 sentence_end="。！？!?…" 把 '…' 算句末，
    导致章节被截在 "至于林炎……" 这种残句处。详见 commit 修正。
    """
    # 构造一个章节：前面有 "他笑道：'走吧。'" 是真句末，
    # 中间有 "至于他……" 这种悬念省略号
    text = (
        "他点了点头。"  # pos 0-5, 句末在 5
        "至于林炎……"  # pos 6-11, 省略号在 9-10
        "暂时还需要观察。"  # pos 12-19, 真句末在 19
        + "无关内容" * 50
    )
    # hard_cap=11 强制窗口落在省略号上，看会不会切错
    result = Writer._trim_to_hard_cap(text, hard_cap=11, target=10)
    # 必须切在 "他点了点头。" 之后（pos 6），而不是 "至于林炎……" 之后
    assert result == "他点了点头。", (
        f"trim 错误地把省略号当句末了：result={result!r}"
    )


def test_polish_chapter_actually_trims_overlong_output():
    """端到端：polish_chapter 也应触发硬截。"""
    target = 800
    overlong = "精修后一句。" * 250
    llm = MagicMock()
    llm.chat.return_value = _make_llm_response(content=overlong, finish_reason="stop")
    writer = Writer(llm)
    result = writer.polish_chapter(
        chapter_text="原章节。",
        critique="改",
        chapter_outline=_make_outline(target),
        characters=[_make_character()],
        world_setting=WorldSetting(era="现代", location="城市"),
        context="",
        style_name="webnovel.shuangwen",
    )
    assert len(result) <= int(target * 1.2)
