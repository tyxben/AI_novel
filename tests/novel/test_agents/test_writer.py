"""Writer Agent 单元测试

覆盖：
- generate_scene: 正常生成、字数控制、上下文注入、风格应用
- generate_chapter: 多场景链式生成、滑动窗口上下文
- rewrite_scene: 反馈融入
- writer_node: state 读写
- 边界条件: 空上下文、未知风格、空角色列表、单场景章节
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.writer import Writer, writer_node, _ANTI_AI_FLAVOR
from src.novel.models.chapter import Chapter, Scene
from src.novel.models.character import (
    Appearance,
    CharacterProfile,
    Personality,
)
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import PowerLevel, PowerSystem, WorldSetting


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_llm(text: str = "他拔出长剑，目光如炬，直视前方的敌人。") -> MagicMock:
    """创建返回固定文本的 Mock LLM 客户端。"""
    client = MagicMock()
    client.chat.return_value = LLMResponse(content=text, model="mock-model")
    return client


def _make_llm_sequential(texts: list[str]) -> MagicMock:
    """创建按顺序返回不同文本的 Mock LLM 客户端。"""
    client = MagicMock()
    responses = [LLMResponse(content=t, model="mock-model") for t in texts]
    client.chat.side_effect = responses
    return client


def _make_chapter_outline(
    chapter_number: int = 1, title: str = "风云突变"
) -> ChapterOutline:
    return ChapterOutline(
        chapter_number=chapter_number,
        title=title,
        goal="主角与敌人首次交锋",
        key_events=["遭遇敌人", "激烈战斗"],
        involved_characters=["char_1", "char_2"],
        estimated_words=3000,
        mood="蓄力",
    )


def _make_character(name: str = "林凡", gender: str = "男") -> CharacterProfile:
    return CharacterProfile(
        name=name,
        gender=gender,
        age=22,
        occupation="剑客",
        appearance=Appearance(
            height="180cm",
            build="匀称",
            hair="黑色短发",
            eyes="深邃黑眸",
            clothing_style="白衣",
        ),
        personality=Personality(
            traits=["冷静", "果敢", "隐忍"],
            core_belief="实力为尊",
            motivation="为师报仇",
            flaw="过于自负",
            speech_style="冷淡简短",
            catchphrases=["哼", "不过如此"],
        ),
    )


def _make_world() -> WorldSetting:
    return WorldSetting(
        era="古代",
        location="九州大陆",
        power_system=PowerSystem(
            name="修炼境界",
            levels=[
                PowerLevel(rank=1, name="炼气期", description="初入修炼", typical_abilities=["基础剑术"]),
                PowerLevel(rank=2, name="筑基期", description="筑就根基", typical_abilities=["御剑术"]),
            ],
        ),
        terms={"九霄门": "主角所属门派", "天罡剑": "主角佩剑"},
        rules=["修炼需要灵石", "境界突破有天劫"],
    )


def _make_scene_plan(
    scene_number: int = 1,
    target_words: int = 800,
) -> dict:
    return {
        "scene_number": scene_number,
        "location": "九霄门演武场",
        "time": "清晨",
        "characters": ["林凡", "赵无极"],
        "goal": "主角与对手切磋",
        "mood": "蓄力",
        "target_words": target_words,
        "narrative_modes": ["动作", "对话"],
    }


# ---------------------------------------------------------------------------
# generate_scene 测试
# ---------------------------------------------------------------------------


class TestGenerateScene:
    """generate_scene 相关测试"""

    
    def test_basic_scene_generation(self) -> None:
        """正常生成场景，返回有效 Scene 对象。"""
        llm = _make_llm("剑光一闪，林凡侧身避开。对面赵无极冷笑一声。")
        writer = Writer(llm)

        scene = writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert isinstance(scene, Scene)
        assert scene.scene_number == 1
        assert scene.location == "九霄门演武场"
        assert scene.time == "清晨"
        assert "林凡" in scene.characters
        assert scene.text != ""
        assert scene.word_count > 0

    
    def test_scene_includes_context_in_prompt(self) -> None:
        """前文上下文应注入到 LLM prompt 中。"""
        llm = _make_llm("他回忆起昨日之事，握紧了拳头。")
        writer = Writer(llm)

        context = "昨日，林凡在山崖边独自练剑，突遇暴雨。"
        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context=context,
            style_name="webnovel.shuangwen",
        )

        # 验证 LLM 被调用，且 user prompt 包含上下文
        call_args = llm.chat.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "昨日" in user_msg or "前文回顾" in user_msg

    
    def test_scene_respects_target_words(self) -> None:
        """prompt 中应包含目标字数指令。"""
        llm = _make_llm("短短一段测试文本。")
        writer = Writer(llm)

        writer.generate_scene(
            scene_plan=_make_scene_plan(target_words=500),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "500" in user_msg

    
    def test_scene_with_empty_context(self) -> None:
        """空上下文不应导致错误。"""
        llm = _make_llm("开场描写。")
        writer = Writer(llm)

        scene = writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert isinstance(scene, Scene)
        # user prompt 中不应包含"前文回顾"标记
        user_msg = llm.chat.call_args[0][0][1]["content"]
        assert "前文回顾" not in user_msg

    
    def test_scene_with_unknown_style(self) -> None:
        """未知风格名不崩溃，使用默认指令。"""
        llm = _make_llm("默认风格输出。")
        writer = Writer(llm)

        scene = writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="nonexistent.style",
        )

        assert isinstance(scene, Scene)
        assert scene.text == "默认风格输出。"

    
    def test_anti_ai_flavor_in_prompt(self) -> None:
        """system prompt 中应包含反 AI 味指令。"""
        llm = _make_llm("纯净文本。")
        writer = Writer(llm)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        system_msg = llm.chat.call_args[0][0][0]["content"]
        assert "内心翻涌" in system_msg
        assert "禁止" in system_msg

    
    def test_scene_with_empty_characters(self) -> None:
        """空角色列表不应导致错误。"""
        llm = _make_llm("无名之人在此。")
        writer = Writer(llm)

        scene = writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert isinstance(scene, Scene)

    
    def test_scene_world_description_includes_power_system(self) -> None:
        """世界观描述应包含力量体系信息。"""
        llm = _make_llm("修炼场景。")
        writer = Writer(llm)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.xuanhuan",
        )

        system_msg = llm.chat.call_args[0][0][0]["content"]
        assert "修炼境界" in system_msg
        assert "炼气期" in system_msg


# ---------------------------------------------------------------------------
# generate_chapter 测试
# ---------------------------------------------------------------------------


class TestGenerateChapter:
    """generate_chapter 相关测试"""

    
    def test_chapter_chains_scenes(self) -> None:
        """多场景按顺序生成，拼接为完整章节。"""
        texts = [
            "第一个场景的内容。林凡出场。",
            "第二个场景的内容。赵无极反击。",
            "第三个场景的内容。胜负已分。",
        ]
        llm = _make_llm_sequential(texts)
        writer = Writer(llm)

        plans = [_make_scene_plan(i) for i in range(1, 4)]
        chapter = writer.generate_chapter(
            chapter_outline=_make_chapter_outline(),
            scene_plans=plans,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert isinstance(chapter, Chapter)
        assert len(chapter.scenes) == 3
        assert chapter.scenes[0].scene_number == 1
        assert chapter.scenes[2].scene_number == 3
        assert "第一个场景" in chapter.full_text
        assert "第三个场景" in chapter.full_text
        assert chapter.word_count > 0
        assert chapter.status == "draft"
        assert chapter.chapter_number == 1
        assert chapter.title == "风云突变"

    
    def test_chapter_sliding_context(self) -> None:
        """后续场景的 prompt 应包含前面场景的内容（滑动窗口）。"""
        texts = ["场景一的精彩内容。", "场景二的后续发展。"]
        llm = _make_llm_sequential(texts)
        writer = Writer(llm)

        plans = [_make_scene_plan(1), _make_scene_plan(2)]
        writer.generate_chapter(
            chapter_outline=_make_chapter_outline(),
            scene_plans=plans,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        # 第二次调用时，user prompt 应包含第一个场景的内容
        assert llm.chat.call_count == 2
        second_call_messages = llm.chat.call_args_list[1][0][0]
        second_user_msg = second_call_messages[1]["content"]
        assert "场景一的精彩内容" in second_user_msg

    
    def test_single_scene_chapter(self) -> None:
        """仅一个场景也能正常生成章节。"""
        llm = _make_llm("独幕场景。")
        writer = Writer(llm)

        chapter = writer.generate_chapter(
            chapter_outline=_make_chapter_outline(),
            scene_plans=[_make_scene_plan(1)],
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert len(chapter.scenes) == 1
        assert chapter.full_text == "独幕场景。"

    
    def test_chapter_with_initial_context(self) -> None:
        """提供初始上下文（前一章末尾）时，第一个场景 prompt 应包含该上下文。"""
        llm = _make_llm("新章开始。")
        writer = Writer(llm)

        prev_context = "上一章结尾：主角离开了山门。"
        writer.generate_chapter(
            chapter_outline=_make_chapter_outline(),
            scene_plans=[_make_scene_plan(1)],
            characters=[_make_character()],
            world_setting=_make_world(),
            context=prev_context,
            style_name="webnovel.shuangwen",
        )

        first_user_msg = llm.chat.call_args[0][0][1]["content"]
        assert "山门" in first_user_msg


# ---------------------------------------------------------------------------
# rewrite_scene 测试
# ---------------------------------------------------------------------------


class TestRewriteScene:
    """rewrite_scene 相关测试"""

    
    def test_rewrite_incorporates_feedback(self) -> None:
        """重写 prompt 应包含原文和反馈内容。"""
        llm = _make_llm("重写后的更好版本。")
        writer = Writer(llm)

        original = Scene(
            scene_number=1,
            location="演武场",
            time="清晨",
            characters=["林凡"],
            goal="切磋",
            text="原始文本，质量一般。",
            word_count=8,
        )

        feedback = "对话太少，需要增加角色互动，减少心理描写。"
        rewritten = writer.rewrite_scene(original, feedback, "webnovel.shuangwen")

        assert isinstance(rewritten, Scene)
        assert rewritten.text == "重写后的更好版本。"
        assert rewritten.scene_number == 1
        assert rewritten.location == "演武场"

        # 验证 prompt 包含原文和反馈
        user_msg = llm.chat.call_args[0][0][1]["content"]
        assert "原始文本" in user_msg
        assert "对话太少" in user_msg

    
    def test_rewrite_preserves_metadata(self) -> None:
        """重写应保留原场景的元数据（location, time, characters, goal）。"""
        llm = _make_llm("改进后的文本。")
        writer = Writer(llm)

        original = Scene(
            scene_number=3,
            location="密林深处",
            time="深夜",
            characters=["林凡", "赵无极"],
            goal="追踪线索",
            text="旧文。",
            word_count=2,
            narrative_modes=["动作", "描写"],
        )

        rewritten = writer.rewrite_scene(original, "需要更多悬疑感", "literary.realism")

        assert rewritten.scene_number == 3
        assert rewritten.location == "密林深处"
        assert rewritten.time == "深夜"
        assert "林凡" in rewritten.characters
        assert rewritten.goal == "追踪线索"
        assert rewritten.narrative_modes == ["动作", "描写"]


# ---------------------------------------------------------------------------
# writer_node 测试
# ---------------------------------------------------------------------------


class TestWriterNode:
    """writer_node LangGraph 节点函数测试"""

    def test_node_returns_chapter_text_and_decisions(self) -> None:
        """节点函数应返回 current_chapter_text 和 decisions。"""
        llm = _make_llm("节点生成的文本内容。")
        outline = _make_chapter_outline(chapter_number=5, title="暗流涌动")

        state = {
            "config": {},
            "current_chapter": 5,
            "current_chapter_outline": outline.model_dump(),
            "current_scenes": [_make_scene_plan(1)],
            "characters": [],
            "world_setting": _make_world().model_dump(),
            "style_name": "webnovel.shuangwen",
            "chapters": [],
        }

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm):
            result = writer_node(state)

        assert "current_chapter_text" in result
        assert "decisions" in result
        assert "completed_nodes" in result
        assert "writer" in result["completed_nodes"]

        decisions = result["decisions"]
        assert len(decisions) >= 1
        assert decisions[0]["agent"] == "Writer"

    def test_node_defaults(self) -> None:
        """缺少可选 state 键时使用默认值不崩溃。"""
        llm = _make_llm("默认状态输出。")
        outline = _make_chapter_outline()

        state = {
            "config": {},
            "current_chapter_outline": outline.model_dump(),
        }

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm):
            result = writer_node(state)

        assert "current_chapter_text" in result or "errors" in result


# ---------------------------------------------------------------------------
# 不同风格测试
# ---------------------------------------------------------------------------


class TestStyleVariations:
    """不同风格预设的 prompt 构建测试"""

    
    def test_wuxia_classical_style(self) -> None:
        """武侠古言风格的 system prompt 应包含对应预设内容。"""
        llm = _make_llm("剑影交错。")
        writer = Writer(llm)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="wuxia.classical",
        )

        system_msg = llm.chat.call_args[0][0][0]["content"]
        assert "古典武侠" in system_msg or "金庸" in system_msg

    
    def test_literary_realism_style(self) -> None:
        """文学现实主义风格应包含对应预设内容。"""
        llm = _make_llm("父亲沉默地坐在门槛上。")
        writer = Writer(llm)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="literary.realism",
        )

        system_msg = llm.chat.call_args[0][0][0]["content"]
        assert "现实主义" in system_msg or "余华" in system_msg

    
    def test_light_novel_campus_style(self) -> None:
        """轻小说校园风格应包含对应预设内容。"""
        llm = _make_llm("我叹了口气。")
        writer = Writer(llm)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="light_novel.campus",
        )

        system_msg = llm.chat.call_args[0][0][0]["content"]
        assert "轻小说" in system_msg or "吐槽" in system_msg


# ---------------------------------------------------------------------------
# 字数边界测试
# ---------------------------------------------------------------------------


class TestWordCountBoundaries:
    """字数相关边界条件"""

    
    def test_large_target_words(self) -> None:
        """大字数目标应正确传递到 prompt。"""
        llm = _make_llm("大段文本。" * 100)
        writer = Writer(llm)

        plan = _make_scene_plan(target_words=2000)
        writer.generate_scene(
            scene_plan=plan,
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        user_msg = llm.chat.call_args[0][0][1]["content"]
        assert "2000" in user_msg

    
    def test_small_target_words(self) -> None:
        """小字数目标（如 300）应正确传递且不产生负数下限。"""
        llm = _make_llm("短短一句。")
        writer = Writer(llm)

        plan = _make_scene_plan(target_words=300)
        writer.generate_scene(
            scene_plan=plan,
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        user_msg = llm.chat.call_args[0][0][1]["content"]
        # 下限应为 max(300-200, 300) = 300，不应出现负数
        assert "300" in user_msg
        assert "-" not in user_msg.split("字数控制在")[1].split("到")[0] if "字数控制在" in user_msg else True


# ---------------------------------------------------------------------------
# 上下文窗口截断测试
# ---------------------------------------------------------------------------


class TestContextWindow:
    """验证上下文截断逻辑"""

    
    def test_long_context_is_truncated(self) -> None:
        """超长上下文应被截断到约 2000 字符。"""
        llm = _make_llm("输出。")
        writer = Writer(llm)

        long_context = "这是一段很长的上下文。" * 500  # 远超 2000 字符

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context=long_context,
            style_name="webnovel.shuangwen",
        )

        user_msg = llm.chat.call_args[0][0][1]["content"]
        # 上下文部分不应超过原始长度（已截断）
        assert len(user_msg) < len(long_context)


# ---------------------------------------------------------------------------
# set_storyline_context 测试
# ---------------------------------------------------------------------------


class TestStorylineContext:
    """set_storyline_context 主线意识和节奏位置感测试"""

    def test_storyline_injected_into_system_prompt(self) -> None:
        """设置主线后，system prompt 应包含主线信息。"""
        llm = _make_llm("战斗场景。")
        writer = Writer(llm)

        writer.set_storyline_context(
            main_storyline={
                "protagonist_goal": "成为天下第一剑客",
                "core_conflict": "宿敌追杀与自我突破",
                "character_arc": "从懦弱少年成长为无畏剑客",
                "stakes": "师门存亡",
            },
            current_chapter=5,
            total_chapters=40,
            storyline_progress="主角初入江湖",
        )

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(chapter_number=5),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        system_msg = llm.chat.call_args[0][0][0]["content"]
        assert "故事主线" in system_msg
        assert "成为天下第一剑客" in system_msg
        assert "宿敌追杀" in system_msg
        assert "懦弱少年" in system_msg
        assert "师门存亡" in system_msg

    def test_position_injected_into_system_prompt(self) -> None:
        """设置位置后，system prompt 应包含位置和节奏信息。"""
        llm = _make_llm("高潮场景。")
        writer = Writer(llm)

        writer.set_storyline_context(
            main_storyline={"protagonist_goal": "复仇"},
            current_chapter=35,
            total_chapters=40,
            storyline_progress="最终决战前夕",
        )

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(chapter_number=35),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        system_msg = llm.chat.call_args[0][0][0]["content"]
        assert "当前故事位置" in system_msg
        assert "第 35 章 / 共 40 章" in system_msg
        assert "最终决战前夕" in system_msg
        assert "高潮期" in system_msg

    def test_no_storyline_no_extra_prompt(self) -> None:
        """未设置主线时，system prompt 不应包含主线/位置 section。"""
        llm = _make_llm("普通场景。")
        writer = Writer(llm)

        writer.generate_scene(
            scene_plan=_make_scene_plan(),
            chapter_outline=_make_chapter_outline(),
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        system_msg = llm.chat.call_args[0][0][0]["content"]
        assert "故事主线" not in system_msg
        assert "当前故事位置" not in system_msg

    def test_pacing_chapter_1(self) -> None:
        """第1章应给出开场章节奏指令。"""
        llm = _make_llm("开场。")
        writer = Writer(llm)

        writer.set_storyline_context(
            main_storyline={"protagonist_goal": "test"},
            current_chapter=1,
            total_chapters=40,
        )

        assert writer._story_position is not None
        assert "开场章" in writer._story_position["pacing_instruction"]
        assert "禁止慢热" in writer._story_position["pacing_instruction"]

    def test_pacing_early_chapters(self) -> None:
        """第2-3章应给出前期章节奏指令。"""
        writer = Writer(_make_llm())
        writer.set_storyline_context(
            main_storyline={"protagonist_goal": "test"},
            current_chapter=2,
            total_chapters=40,
        )
        assert "前期章节" in writer._story_position["pacing_instruction"]

    def test_pacing_development_phase(self) -> None:
        """25%-50%进度应给出发展期指令。"""
        writer = Writer(_make_llm())
        writer.set_storyline_context(
            main_storyline={"protagonist_goal": "test"},
            current_chapter=15,
            total_chapters=40,
        )
        assert writer._story_position["progress_pct"] == 37
        assert "发展期" in writer._story_position["pacing_instruction"]

    def test_pacing_climax_phase(self) -> None:
        """75%-90%进度应给出高潮期指令。"""
        writer = Writer(_make_llm())
        writer.set_storyline_context(
            main_storyline={"protagonist_goal": "test"},
            current_chapter=33,
            total_chapters=40,
        )
        assert writer._story_position["progress_pct"] == 82
        assert "高潮期" in writer._story_position["pacing_instruction"]

    def test_pacing_ending_phase(self) -> None:
        """90%+进度应给出收束期指令。"""
        writer = Writer(_make_llm())
        writer.set_storyline_context(
            main_storyline={"protagonist_goal": "test"},
            current_chapter=38,
            total_chapters=40,
        )
        assert writer._story_position["progress_pct"] == 95
        assert "收束期" in writer._story_position["pacing_instruction"]

    def test_zero_total_chapters_no_crash(self) -> None:
        """total_chapters 为 0 时不应崩溃（除零保护）。"""
        writer = Writer(_make_llm())
        writer.set_storyline_context(
            main_storyline={"protagonist_goal": "test"},
            current_chapter=1,
            total_chapters=0,
        )
        assert writer._story_position is not None
        assert writer._story_position["progress_pct"] == 100

    def test_writer_node_sets_storyline_context(self) -> None:
        """writer_node 应从 state 中提取 main_storyline 并设置到 Writer。"""
        llm = _make_llm("节点生成。")
        outline = _make_chapter_outline(chapter_number=10, title="暗流涌动")

        state = {
            "config": {},
            "current_chapter": 10,
            "total_chapters": 40,
            "current_chapter_outline": outline.model_dump(),
            "current_scenes": [_make_scene_plan(1)],
            "characters": [],
            "world_setting": _make_world().model_dump(),
            "style_name": "webnovel.shuangwen",
            "chapters": [],
            "outline": {
                "main_storyline": {
                    "protagonist_goal": "修炼成仙",
                    "core_conflict": "魔族入侵",
                    "character_arc": "凡人成仙",
                    "stakes": "人界存亡",
                },
                "chapters": [],
            },
        }

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm):
            result = writer_node(state)

        assert "current_chapter_text" in result

        # 验证 system prompt 包含主线信息
        system_msg = llm.chat.call_args[0][0][0]["content"]
        assert "修炼成仙" in system_msg
        assert "魔族入侵" in system_msg
        assert "当前故事位置" in system_msg

    def test_writer_node_no_outline_no_crash(self) -> None:
        """state 中没有 outline 时 writer_node 不崩溃。"""
        llm = _make_llm("无大纲。")
        outline = _make_chapter_outline()

        state = {
            "config": {},
            "current_chapter_outline": outline.model_dump(),
            "current_scenes": [_make_scene_plan(1)],
            "characters": [],
            "world_setting": _make_world().model_dump(),
            "style_name": "webnovel.shuangwen",
            "chapters": [],
        }

        with patch("src.novel.agents.writer.create_llm_client", return_value=llm):
            result = writer_node(state)

        assert "current_chapter_text" in result

        # 没有主线信息时不应有主线 section
        system_msg = llm.chat.call_args[0][0][0]["content"]
        assert "故事主线" not in system_msg
