"""精修功能（polish_chapter + polish_chapters pipeline）测试

覆盖：
- Writer.polish_chapter: 正常精修、跳过逻辑、prompt 内容、温度、主线注入
- NovelPipeline.polish_chapters: 缺失项目、基本流程（Reviewer.review → polish）、
  跳过通过章节、跳过无文本章节、progress callback
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.reviewer import Reviewer
from src.novel.agents.writer import Writer
from src.novel.models.character import (
    Appearance,
    CharacterProfile,
    Personality,
)
from src.novel.models.critique_result import (
    CritiqueIssue,
    CritiqueResult,
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


def _make_critique_needs_refine(chapter_number: int = 1) -> CritiqueResult:
    """构造一个 needs_refine=True 的 CritiqueResult（≥1 high issue）。"""
    return CritiqueResult(
        chapter_number=chapter_number,
        strengths=["节奏紧凑"],
        issues=[
            CritiqueIssue(
                type="pacing",
                severity="high",
                quote="某段原文",
                reason="前半段拖沓，建议精简",
            ),
        ],
        specific_revisions=[],
        overall_assessment="整体可以，但节奏需要调整。",
    )


def _make_critique_pass(chapter_number: int = 1) -> CritiqueResult:
    """构造一个 needs_refine=False 的 CritiqueResult（无 issue）。"""
    return CritiqueResult(
        chapter_number=chapter_number,
        strengths=["节奏稳定", "人物立体"],
        issues=[],
        specific_revisions=[],
        overall_assessment="本章完成度很高，无需修改。",
    )


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

    def test_polish_no_textual_shortcircuit_guard(self) -> None:
        """即使 critique 包含"审稿通过/无需修改"字面量，Writer 也不再短路。

        跳过逻辑统一收到 pipeline 层（按 CritiqueResult.issues 判），Writer 层
        只要被调用就照样走 LLM。
        """
        llm = _make_llm("精修后的内容")
        writer = Writer(llm)
        outline = _make_chapter_outline()

        result = writer.polish_chapter(
            chapter_text="原始内容",
            critique="审稿通过，无需修改",  # 旧守卫会命中，现在不该短路
            chapter_outline=outline,
            characters=[_make_character()],
            world_setting=_make_world(),
            context="",
            style_name="webnovel.shuangwen",
        )

        llm.chat.assert_called_once()
        assert result == "精修后的内容"

    def test_polish_skips_partial_match_not_triggered(self) -> None:
        """历史守卫用的"审稿通过+无需修改"已整段移除；任何 critique 都会走 LLM。"""
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
        """提供前章上下文时，user prompt 应包含 "前章状态摘要" 标签。

        历史标签是【前文回顾 — 严禁照抄以下文字】，但 C3 真修后 pipeline
        实际传入的是摘要而非生原文，文案改为【前章状态摘要 — 严禁照抄】。
        """
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
        assert "前章状态摘要" in user_msg
        assert "激烈的战斗" in user_msg
        # 旧文案不再回流（C3 修复后所有 polish/rewrite context 都是摘要，
        # 不能再用"前文回顾"这种暗示原文的标签）
        assert "前文回顾" not in user_msg

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
        """基本精修流程：Reviewer 发现问题 → Writer 精修 → 返回结果。"""
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
                        "key_events": ["关键事件 1"],
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

        # 走 Reviewer.review 路径：返回 needs_refine=True 的 CritiqueResult
        # Writer 的 polish_chapter 走 LLM，所以 LLM 还要 mock 一次精修响应
        mock_llm = _make_llm("精修后的章节内容。")

        pipe = NovelPipeline(workspace=str(tmp_path))

        critique = _make_critique_needs_refine(chapter_number=1)

        with patch(
            "src.llm.llm_client.create_llm_client", return_value=mock_llm
        ), patch.object(
            Reviewer,
            "review",
            return_value=critique,
        ) as mock_review:
            result = pipe.polish_chapters(str(novel_dir))

        assert result["novel_id"] == novel_id
        assert isinstance(result["polished_chapters"], list)
        assert isinstance(result["skipped_chapters"], list)
        assert isinstance(result["errors"], list)

        # Reviewer.review 应被调用一次，且 kwargs 与检查点里的 outline 对齐
        mock_review.assert_called_once()
        kwargs = mock_review.call_args.kwargs
        assert kwargs["chapter_number"] == 1
        assert kwargs["chapter_title"] == "测试章"
        assert kwargs["chapter_goal"] == "测试目标"
        # 首章没有前文，previous_tail 必须是空串
        assert kwargs["previous_tail"] == ""

        # 精修结果
        assert len(result["polished_chapters"]) == 1
        ch = result["polished_chapters"][0]
        assert ch["chapter_number"] == 1
        assert "original_chars" in ch
        assert "polished_chars" in ch
        assert "before_style" in ch
        assert "after_style" in ch
        assert "issues" in ch
        assert isinstance(ch["issues"], list)
        assert len(ch["issues"]) == 1
        assert ch["issues"][0]["type"] == "pacing"
        assert ch["issues"][0]["severity"] == "high"
        assert ch["issues"][0]["reason"] == "前半段拖沓，建议精简"
        assert "critique_full" in ch
        # critique_full 是 to_writer_prompt() 的输出
        assert "编辑批注" in ch["critique_full"]
        assert ch["critique_summary"].startswith("整体可以")

    def test_polish_chapters_skips_when_pass(self, tmp_path: Path) -> None:
        """needs_refine=False 的章节应被跳过。"""
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
                        "key_events": ["关键事件 1"],
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

        # LLM 不应被用于精修（审稿通过）
        mock_llm = _make_llm("不应被精修调用")

        pipe = NovelPipeline(workspace=str(tmp_path))
        critique = _make_critique_pass(chapter_number=1)

        with patch(
            "src.llm.llm_client.create_llm_client", return_value=mock_llm
        ), patch.object(
            Reviewer,
            "review",
            return_value=critique,
        ), patch.object(Writer, "polish_chapter") as mock_polish:
            result = pipe.polish_chapters(str(novel_dir))

        # 章节应被跳过
        assert 1 in result["skipped_chapters"]
        assert len(result["polished_chapters"]) == 0
        # 直接断言 Writer.polish_chapter 未被调用（而非依赖 LLM 未触发的间接证据）
        mock_polish.assert_not_called()
        mock_llm.chat.assert_not_called()

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
                        "key_events": ["关键事件 1"],
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
                        "key_events": ["关键事件 1"],
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
        critique = _make_critique_pass(chapter_number=1)

        with patch(
            "src.llm.llm_client.create_llm_client", return_value=mock_llm
        ), patch.object(
            Reviewer,
            "review",
            return_value=critique,
        ):
            pipe.polish_chapters(str(novel_dir), progress_callback=callback)

        assert callback.call_count >= 1
        # 最后一次调用应该是 1.0 完成
        last_call = callback.call_args_list[-1]
        assert last_call[0][0] == 1.0

    def test_polish_chapters_preserves_all_issue_fields(
        self, tmp_path: Path
    ) -> None:
        """Reviewer 返回多字段 issue 时，pipeline 要把 type/severity/quote/reason
        全部无损翻译成 result["polished_chapters"][i]["issues"] 里的 dict。
        """
        from src.novel.pipeline import NovelPipeline

        novel_id = "novel_issue_fields"
        novel_dir = tmp_path / "novels" / novel_id
        novel_dir.mkdir(parents=True)

        checkpoint = {
            "config": {"llm": {}},
            "outline": {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "多问题章",
                        "goal": "验证 issue 字段",
                        "key_events": ["事件 A", "事件 B"],
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
            f.write("原始章节正文。")

        # 构造一个带 2 条 issue 的 CritiqueResult（1 high + 1 medium）
        critique = CritiqueResult(
            chapter_number=1,
            strengths=["场面感好"],
            issues=[
                CritiqueIssue(
                    type="pacing",
                    severity="high",
                    quote="某段拖沓原文片段",
                    reason="前半节奏过慢，建议压缩两百字",
                ),
                CritiqueIssue(
                    type="dialogue",
                    severity="medium",
                    quote="一段对白片段",
                    reason="角色语气与设定不符",
                ),
            ],
            specific_revisions=[],
            overall_assessment="两条 issue。",
        )

        mock_llm = _make_llm("精修后的章节正文。")
        pipe = NovelPipeline(workspace=str(tmp_path))

        with patch(
            "src.llm.llm_client.create_llm_client", return_value=mock_llm
        ), patch.object(Reviewer, "review", return_value=critique):
            result = pipe.polish_chapters(str(novel_dir))

        assert len(result["polished_chapters"]) == 1
        issues = result["polished_chapters"][0]["issues"]
        assert len(issues) == 2

        # 字段必须与输入逐条一致
        assert issues[0] == {
            "type": "pacing",
            "severity": "high",
            "quote": "某段拖沓原文片段",
            "reason": "前半节奏过慢，建议压缩两百字",
        }
        assert issues[1] == {
            "type": "dialogue",
            "severity": "medium",
            "quote": "一段对白片段",
            "reason": "角色语气与设定不符",
        }
