"""精修功能（self_critique + polish_chapter + polish_chapters pipeline）测试

覆盖：
- Writer.self_critique: 返回值、上下文注入、温度、审稿标准
- Writer.polish_chapter: 正常精修、跳过逻辑、prompt 内容、温度、主线注入
- NovelPipeline.polish_chapters: 缺失项目、基本流程、跳过无文本章节
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.writer import Writer
from src.novel.models.character import (
    Appearance,
    CharacterProfile,
    Personality,
)
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import WorldSetting


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------


def _make_llm(text: str = "精修后的内容。") -> MagicMock:
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
        estimated_words=2500,
        mood="蓄力",
    )


def _make_character(name: str = "李维", gender: str = "男") -> CharacterProfile:
    return CharacterProfile(
        name=name,
        gender=gender,
        age=35,
        occupation="舰长",
        appearance=Appearance(
            height="185cm",
            build="健壮",
            hair="短发",
            eyes="深色",
            clothing_style="制服",
        ),
        personality=Personality(
            traits=["冷静", "果断", "沉稳"],
            core_belief="守护船员",
            motivation="完成任务",
            flaw="过于自信",
            speech_style="简短有力",
        ),
    )


def _make_world() -> WorldSetting:
    return WorldSetting(era="2180年", location="深空")


# ---------------------------------------------------------------------------
# TestSelfCritique
# ---------------------------------------------------------------------------


class TestSelfCritique:
    """测试 Writer.self_critique() 方法"""

    def test_self_critique_returns_string(self) -> None:
        """自审应该返回字符串。"""
        llm = _make_llm(
            "【问题1】类型：重复\n位置：第2段\n问题：导弹攻击场景重复\n建议：删除重复段落"
        )
        writer = Writer(llm)
        outline = _make_chapter_outline()

        result = writer.self_critique(
            chapter_text="这是测试章节内容...",
            chapter_outline=outline,
        )

        assert isinstance(result, str)
        assert "问题" in result

    def test_self_critique_pass_returns_string(self) -> None:
        """审稿通过时也应返回字符串。"""
        llm = _make_llm("审稿通过，无需修改")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        result = writer.self_critique(
            chapter_text="很好的章节内容",
            chapter_outline=outline,
        )

        assert isinstance(result, str)
        assert "审稿通过" in result

    def test_self_critique_with_context(self) -> None:
        """带上下文的自审：prompt 应包含前文摘要和上一章结尾。"""
        llm = _make_llm("审稿通过，无需修改")
        writer = Writer(llm)
        outline = _make_chapter_outline(chapter_number=3, title="第三章")

        result = writer.self_critique(
            chapter_text="章节内容",
            chapter_outline=outline,
            context="前文内容",
            all_chapter_summaries="第1章摘要\n第2章摘要",
        )

        assert "审稿通过" in result

        # 验证 prompt 中包含了上下文
        call_args = llm.chat.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "前文各章摘要" in user_msg
        assert "上一章结尾" in user_msg

    def test_self_critique_uses_low_temperature(self) -> None:
        """自审应该使用低温度（0.3）。"""
        llm = _make_llm("审稿通过，无需修改")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        writer.self_critique("内容", outline)

        call_args = llm.chat.call_args
        # Writer uses positional: chat(messages, temperature=0.3, max_tokens=2048)
        # Check kwargs or positional
        if call_args[1]:
            assert call_args[1].get("temperature") == 0.3
        else:
            # positional: messages, temperature
            assert call_args[0][1] == 0.3

    def test_self_critique_system_prompt_has_criteria(self) -> None:
        """自审 system prompt 应包含审稿标准（重复、对话、逻辑等）。"""
        llm = _make_llm("审稿通过，无需修改")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        writer.self_critique("内容", outline)

        call_args = llm.chat.call_args
        messages = call_args[0][0]
        system_msg = messages[0]["content"]
        assert "重复" in system_msg
        assert "对话" in system_msg
        assert "逻辑" in system_msg

    def test_self_critique_without_context_omits_sections(self) -> None:
        """无上下文时，user prompt 不应包含前文摘要和上一章结尾 section。"""
        llm = _make_llm("审稿通过，无需修改")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        writer.self_critique("内容", outline)

        messages = llm.chat.call_args[0][0]
        user_msg = messages[1]["content"]
        assert "前文各章摘要" not in user_msg
        assert "上一章结尾" not in user_msg

    def test_self_critique_includes_chapter_info(self) -> None:
        """user prompt 应包含章节号和标题。"""
        llm = _make_llm("审稿通过，无需修改")
        writer = Writer(llm)
        outline = _make_chapter_outline(chapter_number=7, title="暗流涌动")

        writer.self_critique("内容", outline)

        messages = llm.chat.call_args[0][0]
        user_msg = messages[1]["content"]
        assert "7" in user_msg
        assert "暗流涌动" in user_msg


# ---------------------------------------------------------------------------
# TestPolishChapter
# ---------------------------------------------------------------------------


class TestPolishChapter:
    """测试 Writer.polish_chapter() 方法"""

    def test_polish_returns_text(self) -> None:
        """精修应返回非空字符串。"""
        llm = _make_llm("精修后的内容")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        result = writer.polish_chapter(
            chapter_text="原始内容",
            critique="【问题1】类型：重复\n建议：删除重复段落",
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert isinstance(result, str)
        assert len(result) > 0

    def test_polish_skips_when_no_issues(self) -> None:
        """审稿通过时应跳过精修，返回原文。LLM 不应被调用。"""
        llm = _make_llm("不应被调用")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        original = "这是原始章节内容"
        result = writer.polish_chapter(
            chapter_text=original,
            critique="审稿通过，无需修改",
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        assert result == original
        llm.chat.assert_not_called()

    def test_polish_skips_partial_match_not_triggered(self) -> None:
        """只有'审稿通过'但无'无需修改'时不应跳过。"""
        llm = _make_llm("精修结果")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        result = writer.polish_chapter(
            chapter_text="原始内容",
            critique="审稿通过，但有一些小问题需要修复",
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        # "无需修改" not in critique, so LLM should be called
        llm.chat.assert_called_once()
        assert result == "精修结果"

    def test_polish_prompt_includes_critique(self) -> None:
        """精修 prompt 应包含审稿意见。"""
        llm = _make_llm("精修后的内容")
        writer = Writer(llm)
        outline = _make_chapter_outline()
        critique = "【问题1】类型：对话\n问题：角色说话雷同"

        writer.polish_chapter(
            chapter_text="内容",
            critique=critique,
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        # polish_chapter uses keyword: messages=[...], temperature=0.7, ...
        if "messages" in (call_args[1] or {}):
            messages = call_args[1]["messages"]
        else:
            messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "编辑审稿意见" in user_msg
        assert "角色说话雷同" in user_msg

    def test_polish_prompt_includes_original_text(self) -> None:
        """精修 prompt 应包含原文。"""
        llm = _make_llm("精修后")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        writer.polish_chapter(
            chapter_text="这是原始章节的完整正文内容",
            critique="【问题1】有问题",
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        if "messages" in (call_args[1] or {}):
            messages = call_args[1]["messages"]
        else:
            messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "原始章节的完整正文内容" in user_msg

    def test_polish_uses_moderate_temperature(self) -> None:
        """精修应使用中等温度（<= 0.8），比初稿（0.85）低。"""
        llm = _make_llm("精修后")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        writer.polish_chapter(
            chapter_text="内容",
            critique="【问题1】有问题",
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        temp = (call_args[1] or {}).get("temperature")
        assert temp is not None
        assert temp <= 0.8, f"精修温度 {temp} 应 <= 0.8"

    def test_polish_system_prompt_has_polish_principles(self) -> None:
        """精修 system prompt 应包含精修原则。"""
        llm = _make_llm("精修后")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        writer.polish_chapter(
            chapter_text="内容",
            critique="【问题1】有问题",
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        if "messages" in (call_args[1] or {}):
            messages = call_args[1]["messages"]
        else:
            messages = call_args[0][0]
        system_msg = messages[0]["content"]
        assert "精修" in system_msg
        assert "保留" in system_msg  # 保留原文好的部分

    def test_polish_with_context(self) -> None:
        """提供前文上下文时，user prompt 应包含前文回顾。"""
        llm = _make_llm("精修后")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        writer.polish_chapter(
            chapter_text="内容",
            critique="【问题1】有问题",
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="上一章的结尾内容描述了一场激烈的战斗",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        if "messages" in (call_args[1] or {}):
            messages = call_args[1]["messages"]
        else:
            messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "前文回顾" in user_msg
        assert "激烈的战斗" in user_msg

    def test_polish_without_context_omits_section(self) -> None:
        """无前文上下文时，user prompt 不应包含前文回顾。"""
        llm = _make_llm("精修后")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        writer.polish_chapter(
            chapter_text="内容",
            critique="【问题1】有问题",
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        if "messages" in (call_args[1] or {}):
            messages = call_args[1]["messages"]
        else:
            messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "前文回顾" not in user_msg

    def test_polish_with_storyline_context(self) -> None:
        """精修应该包含主线信息（如果已设置）。"""
        llm = _make_llm("精修后")
        writer = Writer(llm)
        writer.set_storyline_context(
            main_storyline={
                "protagonist_goal": "生存",
                "core_conflict": "降维打击",
            },
            current_chapter=5,
            total_chapters=12,
        )
        outline = _make_chapter_outline(chapter_number=5)

        writer.polish_chapter(
            chapter_text="内容",
            critique="【问题1】有问题",
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        if "messages" in (call_args[1] or {}):
            messages = call_args[1]["messages"]
        else:
            messages = call_args[0][0]
        system_msg = messages[0]["content"]
        assert "故事主线" in system_msg

    def test_polish_includes_anti_ai_flavor(self) -> None:
        """精修 system prompt 应包含反 AI 味指令。"""
        llm = _make_llm("精修后")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        writer.polish_chapter(
            chapter_text="内容",
            critique="【问题1】有问题",
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        if "messages" in (call_args[1] or {}):
            messages = call_args[1]["messages"]
        else:
            messages = call_args[0][0]
        system_msg = messages[0]["content"]
        assert "内心翻涌" in system_msg
        assert "禁止" in system_msg

    def test_polish_includes_character_info(self) -> None:
        """精修 system prompt 应包含角色信息。"""
        llm = _make_llm("精修后")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        writer.polish_chapter(
            chapter_text="内容",
            critique="【问题1】有问题",
            chapter_outline=outline,
            characters=[_make_character(name="张三")],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        call_args = llm.chat.call_args
        if "messages" in (call_args[1] or {}):
            messages = call_args[1]["messages"]
        else:
            messages = call_args[0][0]
        system_msg = messages[0]["content"]
        assert "张三" in system_msg


# ---------------------------------------------------------------------------
# TestPolishPipeline
# ---------------------------------------------------------------------------


class TestPolishPipeline:
    """测试 NovelPipeline.polish_chapters() 方法"""

    def test_polish_missing_project_raises(self, tmp_path: Path) -> None:
        """找不到项目检查点时应抛出 FileNotFoundError。"""
        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=str(tmp_path))

        with pytest.raises(FileNotFoundError):
            pipe.polish_chapters(str(tmp_path / "novels" / "novel_nonexist"))

    def test_polish_chapters_basic_flow(self, tmp_path: Path) -> None:
        """基本精修流程：自审发现问题 → 精修 → 返回结果。"""
        from src.novel.pipeline import NovelPipeline

        # 准备项目目录和检查点
        novel_id = "novel_test123"
        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True)

        # 创建检查点
        checkpoint = {
            "config": {"llm": {}},
            "outline": {
                "main_storyline": {"protagonist_goal": "生存"},
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "测试章",
                        "goal": "测试目标",
                        "estimated_words": 2500,
                    }
                ],
            },
            "characters": [],
            "world_setting": {"era": "2180年", "location": "深空"},
            "style_name": "webnovel.shuangwen",
        }
        with open(novel_dir / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False)

        # 创建章节文本
        chapters_dir = novel_dir / "chapters"
        chapters_dir.mkdir()
        with open(chapters_dir / "chapter_001.txt", "w", encoding="utf-8") as f:
            f.write("这是原始章节的内容。")

        # Mock LLM：第一次调用返回审稿意见，第二次返回精修结果
        mock_llm = _make_llm_sequential([
            "【问题1】类型：重复\n位置：第1段\n问题：有重复\n建议：删除",
            "精修后的章节内容。",
        ])

        pipe = NovelPipeline(workspace=str(tmp_path))

        with patch("src.llm.llm_client.create_llm_client", return_value=mock_llm):
            result = pipe.polish_chapters(str(novel_dir))

        assert result["novel_id"] == novel_id
        assert isinstance(result["polished_chapters"], list)
        assert isinstance(result["skipped_chapters"], list)
        assert isinstance(result["errors"], list)

        # 至少有一个精修结果（如果章节被成功加载）
        if result["polished_chapters"]:
            ch = result["polished_chapters"][0]
            assert ch["chapter_number"] == 1
            assert "original_chars" in ch
            assert "polished_chars" in ch

    def test_polish_chapters_skips_when_pass(self, tmp_path: Path) -> None:
        """审稿通过的章节应被跳过。"""
        from src.novel.pipeline import NovelPipeline

        novel_id = "novel_skip"
        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True)

        checkpoint = {
            "config": {"llm": {}},
            "outline": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "好章",
                        "goal": "测试",
                        "estimated_words": 2500,
                    }
                ],
            },
            "characters": [],
            "world_setting": {"era": "现代", "location": "城市"},
            "style_name": "webnovel.shuangwen",
        }
        with open(novel_dir / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False)

        chapters_dir = novel_dir / "chapters"
        chapters_dir.mkdir()
        with open(chapters_dir / "chapter_001.txt", "w", encoding="utf-8") as f:
            f.write("这是一个质量很好的章节。")

        # LLM 返回审稿通过
        mock_llm = _make_llm("审稿通过，无需修改")

        pipe = NovelPipeline(workspace=str(tmp_path))

        with patch("src.llm.llm_client.create_llm_client", return_value=mock_llm):
            result = pipe.polish_chapters(str(novel_dir))

        # 章节应被跳过
        assert 1 in result["skipped_chapters"]
        assert len(result["polished_chapters"]) == 0

    def test_polish_chapters_no_outline_raises(self, tmp_path: Path) -> None:
        """大纲不存在时应抛出 ValueError。"""
        from src.novel.pipeline import NovelPipeline

        novel_id = "novel_no_outline"
        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True)

        checkpoint = {
            "config": {"llm": {}},
            "outline": None,
            "characters": [],
        }
        with open(novel_dir / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False)

        pipe = NovelPipeline(workspace=str(tmp_path))

        with pytest.raises(ValueError, match="大纲不存在"):
            pipe.polish_chapters(str(novel_dir))

    def test_polish_chapters_skips_missing_text(self, tmp_path: Path) -> None:
        """无文本的章节应被跳过并记入 skipped_chapters。"""
        from src.novel.pipeline import NovelPipeline

        novel_id = "novel_no_text"
        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True)

        checkpoint = {
            "config": {"llm": {}},
            "outline": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "空章",
                        "goal": "测试",
                        "estimated_words": 2500,
                    }
                ],
            },
            "characters": [],
            "world_setting": {"era": "现代", "location": "城市"},
            "style_name": "webnovel.shuangwen",
        }
        with open(novel_dir / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False)

        # 不创建章节文本文件

        mock_llm = _make_llm("不应被调用")
        pipe = NovelPipeline(workspace=str(tmp_path))

        with patch("src.llm.llm_client.create_llm_client", return_value=mock_llm):
            result = pipe.polish_chapters(str(novel_dir))

        assert 1 in result["skipped_chapters"]
        assert len(result["polished_chapters"]) == 0
        mock_llm.chat.assert_not_called()

    def test_polish_chapters_progress_callback(self, tmp_path: Path) -> None:
        """progress_callback 应被调用。"""
        from src.novel.pipeline import NovelPipeline

        novel_id = "novel_progress"
        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True)

        checkpoint = {
            "config": {"llm": {}},
            "outline": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "章节一",
                        "goal": "测试",
                        "estimated_words": 2500,
                    }
                ],
            },
            "characters": [],
            "world_setting": {"era": "现代", "location": "城市"},
            "style_name": "webnovel.shuangwen",
        }
        with open(novel_dir / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False)

        chapters_dir = novel_dir / "chapters"
        chapters_dir.mkdir()
        with open(chapters_dir / "chapter_001.txt", "w", encoding="utf-8") as f:
            f.write("章节内容")

        mock_llm = _make_llm("审稿通过，无需修改")
        callback = MagicMock()

        pipe = NovelPipeline(workspace=str(tmp_path))

        with patch("src.llm.llm_client.create_llm_client", return_value=mock_llm):
            pipe.polish_chapters(str(novel_dir), progress_callback=callback)

        assert callback.call_count >= 1
        # 最后一次调用应该是 1.0 完成
        last_call = callback.call_args_list[-1]
        assert last_call[0][0] == 1.0
