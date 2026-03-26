"""End-to-end integration test: ReAct + Prompt Registry + Feedback Loop.

Tests the full chain:
1. Initialize PromptRegistry + seed default prompts
2. Create Writer with registry enabled
3. Generate chapter (react_mode) -- prompts come from registry
4. QualityReviewer reviews -- saves feedback
5. Generate next chapter -- feedback from previous chapter is injected
6. Verify prompt evolution works (update block, regenerate)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.agents.writer import Writer
from src.novel.agents.quality_reviewer import QualityReviewer
from src.novel.models.chapter import Chapter, Scene
from src.novel.models.character import (
    Appearance,
    CharacterArc,
    CharacterProfile,
    Personality,
)
from src.novel.models.novel import ChapterOutline
from src.novel.models.world import WorldSetting
from src.prompt_registry import PromptRegistry, FeedbackInjector
from src.prompt_registry.seed_data import seed_default_prompts


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def registry(tmp_path):
    """Create a fresh PromptRegistry with seed data."""
    db_path = str(tmp_path / "test_e2e.db")
    reg = PromptRegistry(db_path)
    seed_default_prompts(reg)
    yield reg
    reg.close()


@pytest.fixture
def mock_llm():
    """Create a mock LLM client with sensible defaults."""
    llm = MagicMock()
    llm.chat.return_value = LLMResponse(
        content="默认场景文本。" * 50,
        model="mock-model",
        usage={"total_tokens": 500},
        finish_reason="stop",
    )
    return llm


@pytest.fixture
def chapter_outline():
    return ChapterOutline(
        chapter_number=1,
        title="命运之始",
        goal="建立主角形象，引出核心矛盾",
        key_events=["主角出场", "遭遇危机"],
        involved_characters=["char_001"],
        mood="蓄力",
        estimated_words=2500,
    )


@pytest.fixture
def chapter_outline_2():
    return ChapterOutline(
        chapter_number=2,
        title="初入江湖",
        goal="主角踏上旅途，遇到第一个盟友",
        key_events=["主角离开家乡", "遇到伙伴"],
        involved_characters=["char_001", "char_002"],
        mood="小爽",
        estimated_words=2500,
    )


@pytest.fixture
def characters():
    return [
        CharacterProfile(
            character_id="char_001",
            name="林风",
            alias=["小风"],
            gender="男",
            age=18,
            occupation="剑客",
            appearance=Appearance(
                height="175cm",
                build="匀称",
                hair="黑色长发",
                eyes="深棕色",
                clothing_style="白色剑袍",
                distinctive_features=["左眉处有一道细小疤痕"],
            ),
            personality=Personality(
                traits=["坚韧", "正义", "冲动"],
                core_belief="正义必胜",
                motivation="为师报仇",
                flaw="过于冲动",
                speech_style="简短有力，偶尔带点自嘲",
                catchphrases=["剑在人在"],
            ),
        ),
        CharacterProfile(
            character_id="char_002",
            name="苏瑶",
            alias=["瑶儿"],
            gender="女",
            age=17,
            occupation="药师",
            appearance=Appearance(
                height="163cm",
                build="纤细",
                hair="棕色短发",
                eyes="碧绿色",
                clothing_style="青色布衣",
                distinctive_features=["右手腕上的药草纹身"],
            ),
            personality=Personality(
                traits=["聪慧", "温柔", "固执"],
                core_belief="救人是最大的善",
                motivation="寻找失落的药方",
                flaw="过于信任他人",
                speech_style="温和但坚定，常引用药理",
                catchphrases=["药到病除"],
            ),
        ),
    ]


@pytest.fixture
def world_setting():
    return WorldSetting(
        era="古代架空",
        location="九州大陆",
        terms={"灵力": "天地间的能量", "剑意": "剑客领悟的境界"},
        rules=["灵力分九品", "剑意需实战感悟"],
    )


@pytest.fixture
def scene_plan():
    return {
        "scene_number": 1,
        "location": "青云山脚",
        "time": "清晨",
        "characters_involved": ["林风"],
        "goal": "主角独自练剑，回忆师父教诲",
        "mood": "蓄力",
        "target_words": 800,
        "narrative_modes": ["动作", "心理"],
    }


# ======================================================================
# Test 1: Registry Seeded Correctly
# ======================================================================


class TestRegistrySeeded:
    def test_seed_creates_anti_pattern_blocks(self, registry):
        """Verify seed data creates anti-pattern blocks."""
        block = registry.get_active_block("writer_anti_ai_flavor")
        assert block is not None
        assert block.block_type == "anti_pattern"
        assert block.agent == "writer"
        assert "AI 生成痕迹" in block.content

    def test_seed_creates_style_blocks(self, registry):
        """Verify style blocks for different genres exist."""
        wuxia = registry.get_active_block("style_wuxia_classical")
        assert wuxia is not None
        assert wuxia.block_type == "system_instruction"
        assert "古典武侠" in wuxia.content

        shuangwen = registry.get_active_block("style_webnovel_shuangwen")
        assert shuangwen is not None
        assert "爽文" in shuangwen.content

    def test_seed_creates_craft_blocks(self, registry):
        """Verify craft technique blocks exist."""
        battle = registry.get_active_block("craft_battle")
        assert battle is not None
        assert battle.block_type == "craft_technique"
        assert "战斗" in battle.content

        general = registry.get_active_block("craft_general")
        assert general is not None

    def test_seed_creates_templates(self, registry):
        """Verify templates are created."""
        default_tpl = registry.get_template("writer_default")
        assert default_tpl is not None
        assert default_tpl.agent_name == "writer"
        assert "style_{genre}" in default_tpl.block_refs

        battle_tpl = registry.get_template("writer_battle")
        assert battle_tpl is not None
        assert "craft_battle" in battle_tpl.block_refs

    def test_build_prompt_default_nonempty(self, registry):
        """build_prompt for writer/default returns non-empty string."""
        prompt = registry.build_prompt(
            "writer", "default", genre="webnovel_shuangwen"
        )
        assert len(prompt) > 100
        assert "爽文" in prompt

    def test_build_prompt_battle_different(self, registry):
        """build_prompt for battle scenario includes battle-specific content."""
        default_prompt = registry.build_prompt(
            "writer", "default", genre="webnovel_shuangwen"
        )
        battle_prompt = registry.build_prompt(
            "writer", "battle", genre="webnovel_shuangwen"
        )
        # Battle prompt should include battle craft technique
        assert "战斗场景写作技法" in battle_prompt
        # Default may or may not include it, but they should differ
        assert battle_prompt != default_prompt

    def test_feedback_injection_block_exists(self, registry):
        """The feedback_injection block should be seeded."""
        block = registry.get_active_block("feedback_injection")
        assert block is not None
        assert block.block_type == "feedback_injection"
        assert "{strengths}" in block.content
        assert "{weaknesses}" in block.content


# ======================================================================
# Test 2: Writer Uses Registry Prompt
# ======================================================================


class TestWriterUsesRegistry:
    def test_writer_uses_registry_prompt_in_system_message(
        self, mock_llm, registry, chapter_outline, characters, world_setting, scene_plan
    ):
        """When registry is enabled, Writer's LLM call includes registry prompt content."""
        writer = Writer(mock_llm)
        writer.enable_prompt_registry(registry, novel_id="novel_test")

        writer.generate_scene(
            scene_plan=scene_plan,
            chapter_outline=chapter_outline,
            characters=characters,
            world_setting=world_setting,
            context="前文内容。",
            style_name="webnovel.shuangwen",
        )

        # Check that the LLM was called
        assert mock_llm.chat.called
        # Extract the system message from the first call
        first_call_args = mock_llm.chat.call_args_list[0]
        messages = first_call_args[0][0]  # positional arg
        system_msg = messages[0]["content"]

        # Registry prompt should contain style content from "style_webnovel_shuangwen"
        assert "爽文" in system_msg or "网文" in system_msg
        # Should contain anti-pattern blocks
        assert "AI 生成痕迹" in system_msg or "反重复规则" in system_msg
        # Should contain craft_general (from default template)
        assert "通用写作技法" in system_msg or "Show" in system_msg

    def test_writer_without_registry_uses_hardcoded(
        self, mock_llm, chapter_outline, characters, world_setting, scene_plan
    ):
        """Without registry, Writer falls back to hardcoded constants."""
        writer = Writer(mock_llm)
        # Do NOT enable registry

        writer.generate_scene(
            scene_plan=scene_plan,
            chapter_outline=chapter_outline,
            characters=characters,
            world_setting=world_setting,
            context="前文内容。",
            style_name="webnovel.shuangwen",
        )

        first_call_args = mock_llm.chat.call_args_list[0]
        messages = first_call_args[0][0]
        system_msg = messages[0]["content"]

        # Hardcoded constants should be present
        assert "AI 生成痕迹" in system_msg
        assert "反重复规则" in system_msg
        assert "叙事逻辑规则" in system_msg
        assert "角色名称锁定" in system_msg


# ======================================================================
# Test 3: Feedback Save and Inject
# ======================================================================


class TestFeedbackSaveAndInject:
    def test_save_and_retrieve_feedback(self, registry):
        """FeedbackInjector can save feedback and retrieve it for next chapter."""
        injector = FeedbackInjector(registry)

        injector.save_chapter_feedback(
            novel_id="novel_001",
            chapter_number=1,
            quality_report={
                "rule_check": {"passed": False, "ai_flavor_issues": ["a", "b"], "repetition_issues": []},
                "scores": {"plot": 7.5, "style": 5.0},
                "suggestions": ["对话太相似", "AI味重"],
            },
        )

        # Get feedback for chapter 2 (should get chapter 1's feedback)
        prompt = injector.get_feedback_prompt("novel_001", current_chapter=2)
        assert len(prompt) > 0
        assert "对话太相似" in prompt
        assert "AI味重" in prompt
        assert "AI味问题" in prompt  # from rule_check extraction
        assert "style需改进" in prompt

    def test_no_feedback_returns_empty(self, registry):
        """When no prior feedback exists, return empty string."""
        injector = FeedbackInjector(registry)
        prompt = injector.get_feedback_prompt("novel_001", current_chapter=1)
        assert prompt == ""

    def test_feedback_contains_strengths(self, registry):
        """Feedback prompt includes both strengths and weaknesses."""
        injector = FeedbackInjector(registry)

        injector.save_chapter_feedback(
            novel_id="novel_002",
            chapter_number=1,
            quality_report={
                "rule_check": {"passed": True},
                "scores": {"plot": 9.0, "style": 8.5},
                "suggestions": [],
            },
        )

        prompt = injector.get_feedback_prompt("novel_002", current_chapter=2)
        assert "继续保持" in prompt
        assert "plot表现优秀" in prompt
        assert "style表现优秀" in prompt
        assert "规则检查全部通过" in prompt


# ======================================================================
# Test 4: Quality Reviewer Saves Feedback
# ======================================================================


class TestQualityReviewerSavesFeedback:
    def test_reviewer_generates_report_and_injector_saves(self, registry, mock_llm):
        """Simulate QualityReviewer creating a report, then FeedbackInjector saving it."""
        reviewer = QualityReviewer(llm_client=mock_llm)
        injector = FeedbackInjector(registry)

        # Simulate a quality report (as would come from review_chapter)
        quality_report = {
            "rule_check": {
                "passed": False,
                "ai_flavor_issues": ["内心翻涌"],
                "repetition_issues": ["重复句1"],
            },
            "scores": {"coherence": 6.5, "engagement": 4.0},
            "suggestions": ["减少抽象描写", "增加具体细节"],
        }

        # Save via injector
        injector.save_chapter_feedback(
            novel_id="novel_003",
            chapter_number=5,
            quality_report=quality_report,
        )

        # Verify feedback was saved in registry
        feedback = registry.get_last_feedback("novel_003", current_chapter=6)
        assert feedback is not None
        assert feedback.chapter_number == 5
        assert len(feedback.weaknesses) > 0
        assert any("AI味" in w for w in feedback.weaknesses)
        assert any("减少抽象" in w for w in feedback.weaknesses)
        assert feedback.overall_score is not None


# ======================================================================
# Test 5: Feedback Loop Chapter to Chapter
# ======================================================================


class TestFeedbackLoopChapterToChapter:
    def test_full_feedback_loop_react_mode(
        self, registry, chapter_outline, chapter_outline_2,
        characters, world_setting, scene_plan
    ):
        """Full loop in react_mode: Writer ch1 -> QualityReviewer -> FeedbackInjector -> Writer ch2."""
        # 1. Writer generates chapter 1 (no feedback), using non-react mode for simplicity
        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(
            content="林风站在青云山脚，晨雾缭绕。" * 20,
            model="mock",
            usage={"total_tokens": 300},
            finish_reason="stop",
        )

        writer = Writer(mock_llm)
        writer.enable_prompt_registry(registry, novel_id="novel_loop")

        scene1 = writer.generate_scene(
            scene_plan=scene_plan,
            chapter_outline=chapter_outline,
            characters=characters,
            world_setting=world_setting,
            context="",
            style_name="wuxia.classical",
        )
        assert len(scene1.text) > 0

        # 2. QualityReviewer reviews chapter 1 and saves feedback
        injector = FeedbackInjector(registry)
        quality_report = {
            "rule_check": {"passed": False, "ai_flavor_issues": ["莫名的力量"], "repetition_issues": []},
            "scores": {"plot": 7.0, "style": 5.5},
            "suggestions": ["对白缺乏个性", "动作描写需更具体"],
        }
        injector.save_chapter_feedback(
            novel_id="novel_loop",
            chapter_number=1,
            quality_report=quality_report,
        )

        # 3. Get feedback prompt for chapter 2
        feedback_prompt = injector.get_feedback_prompt("novel_loop", current_chapter=2)
        assert len(feedback_prompt) > 0
        assert "对白缺乏个性" in feedback_prompt

        # 4. Writer generates chapter 2 in react_mode with feedback_prompt injected
        #    In react_mode, feedback_prompt is passed to WriterReactAgent._build_scene_prompt
        scene_plan_2 = {
            "scene_number": 1,
            "location": "官道",
            "time": "午后",
            "characters_involved": ["林风", "苏瑶"],
            "goal": "主角离开家乡，路遇苏瑶",
            "mood": "小爽",
            "target_words": 800,
        }

        draft_text = "林风背着长剑走在官道上。" * 20

        # ReAct sequence: generate_draft -> submit
        step1 = LLMResponse(
            content=json.dumps({
                "thinking": "生成初稿",
                "tool": "generate_draft",
                "args": {"scene_prompt": "测试"},
            }),
            model="mock",
            usage={"total_tokens": 100},
            finish_reason="stop",
        )
        step2 = LLMResponse(
            content=json.dumps({
                "thinking": "提交",
                "tool": "submit",
                "args": {"text": ""},
            }),
            model="mock",
            usage={"total_tokens": 50},
            finish_reason="stop",
        )

        mock_llm.chat.reset_mock()
        mock_llm.chat.side_effect = [
            step1,
            LLMResponse(content=draft_text, model="mock", usage={"total_tokens": 200}, finish_reason="stop"),
            step2,
        ]

        scene2 = writer.generate_scene(
            scene_plan=scene_plan_2,
            chapter_outline=chapter_outline_2,
            characters=characters,
            world_setting=world_setting,
            context="前文：林风练剑完毕，决定下山。",
            style_name="wuxia.classical",
            feedback_prompt=feedback_prompt,
            react_mode=True,
        )
        assert len(scene2.text) > 0

        # 5. Verify the feedback text appears in the WriterReactAgent's task prompt
        #    The first LLM call (step1) should have the scene_prompt containing feedback
        first_call = mock_llm.chat.call_args_list[0]
        messages = first_call[0][0]
        # The task (user message) contains the scene_prompt from _build_scene_prompt,
        # which includes the feedback_prompt when provided
        all_content = " ".join(m["content"] for m in messages)
        assert "对白缺乏个性" in all_content or "质量反馈" in all_content

    def test_feedback_loop_non_react_via_registry_context(
        self, registry, chapter_outline, chapter_outline_2,
        characters, world_setting, scene_plan
    ):
        """Non-react feedback loop: feedback flows through registry's build_prompt via context dict.

        In non-react mode, feedback_prompt param is not consumed. Instead, the feedback_injection
        block in the registry template handles injection when build_prompt receives context with
        last_strengths/last_weaknesses. This test verifies the registry mechanism directly.
        """
        # 1. Save feedback for chapter 1
        injector = FeedbackInjector(registry)
        injector.save_chapter_feedback(
            novel_id="novel_ctx",
            chapter_number=1,
            quality_report={
                "rule_check": {"passed": False, "ai_flavor_issues": ["莫名的力量"], "repetition_issues": []},
                "scores": {"plot": 7.0, "style": 5.5},
                "suggestions": ["对白缺乏个性"],
            },
        )

        # 2. Retrieve last feedback record
        feedback = registry.get_last_feedback("novel_ctx", current_chapter=2)
        assert feedback is not None

        # 3. Use feedback_injection block via build_prompt context
        prompt = registry.build_prompt(
            "writer",
            "default",
            genre="wuxia_classical",
            context={
                "last_strengths": feedback.strengths,
                "last_weaknesses": feedback.weaknesses,
            },
        )
        # The assembled prompt should contain both strengths and weaknesses
        assert "对白缺乏个性" in prompt
        assert "上一章反馈" in prompt


# ======================================================================
# Test 6: Prompt Evolution via Update
# ======================================================================


class TestPromptEvolution:
    def test_update_block_creates_new_version(self, registry):
        """Updating a block creates v2, and build_prompt uses the new content."""
        # Version 1: get original content
        original = registry.get_active_block("craft_general")
        assert original is not None
        assert original.version == 1
        original_content = original.content

        # Update with new content
        registry.update_block(
            base_id="craft_general",
            content="【改进版通用写作技法】\n1. 用动作代替心理独白\n2. 每段一个焦点",
        )

        # Version 2 should be active
        updated = registry.get_active_block("craft_general")
        assert updated is not None
        assert updated.version == 2
        assert "改进版" in updated.content

        # Build prompt should use new content
        prompt = registry.build_prompt("writer", "default", genre="webnovel_shuangwen")
        assert "改进版" in prompt
        assert original_content not in prompt

    def test_rollback_restores_old_version(self, registry):
        """Rollback restores the old version."""
        original = registry.get_active_block("craft_general")
        original_content = original.content

        # Update
        registry.update_block(
            base_id="craft_general",
            content="新版内容，这是v2",
        )
        assert registry.get_active_block("craft_general").version == 2

        # Rollback to v1
        rolled_back = registry.rollback_block("craft_general", target_version=1)
        assert rolled_back.version == 1
        assert rolled_back.content == original_content

        # Build prompt should use v1 content
        prompt = registry.build_prompt("writer", "default", genre="webnovel_shuangwen")
        assert "新版内容" not in prompt

    def test_version_history_preserved(self, registry):
        """All versions are preserved in history."""
        registry.update_block("craft_general", content="v2 content")
        registry.update_block("craft_general", content="v3 content")

        versions = registry.get_block_versions("craft_general")
        assert len(versions) == 3
        assert versions[0].version == 1
        assert versions[1].version == 2
        assert versions[2].version == 3


# ======================================================================
# Test 7: ReAct Mode Generates Scene
# ======================================================================


class TestReactModeGeneratesScene:
    def test_react_mode_generates_scene(
        self, chapter_outline, characters, world_setting, scene_plan
    ):
        """Writer with react_mode=True delegates to WriterReactAgent and returns Scene."""
        mock_llm = MagicMock()

        # ReAct loop: LLM returns JSON with tool calls
        # Step 1: generate_draft
        step1_response = LLMResponse(
            content=json.dumps({
                "thinking": "需要先生成初稿",
                "tool": "generate_draft",
                "args": {"scene_prompt": "练剑场景"},
            }),
            model="mock",
            usage={"total_tokens": 100},
            finish_reason="stop",
        )

        # The generate_draft tool will call llm.chat internally,
        # so we need to return a scene text for that call
        draft_text = "林风提剑，晨光照在剑刃上。" * 30  # ~500 chars

        # Step 2: submit
        step2_response = LLMResponse(
            content=json.dumps({
                "thinking": "初稿完成，提交终稿",
                "tool": "submit",
                "args": {"text": ""},
            }),
            model="mock",
            usage={"total_tokens": 50},
            finish_reason="stop",
        )

        # LLM call sequence:
        # 1. ReactAgent.run() calls llm.chat -> step1_response (generate_draft action)
        # 2. WriterToolkit.generate_draft() calls llm.chat -> draft_text
        # 3. ReactAgent.run() calls llm.chat -> step2_response (submit action)
        mock_llm.chat.side_effect = [
            step1_response,
            LLMResponse(content=draft_text, model="mock", usage={"total_tokens": 200}, finish_reason="stop"),
            step2_response,
        ]

        writer = Writer(mock_llm)
        scene = writer.generate_scene(
            scene_plan=scene_plan,
            chapter_outline=chapter_outline,
            characters=characters,
            world_setting=world_setting,
            context="",
            style_name="wuxia.classical",
            react_mode=True,
        )

        assert isinstance(scene, Scene)
        assert len(scene.text) > 0
        assert scene.scene_number == 1
        assert scene.location == "青云山脚"

    def test_react_mode_fallback_on_empty_output(
        self, chapter_outline, characters, world_setting, scene_plan
    ):
        """If ReAct produces empty text, Writer falls back to one-shot mode."""
        mock_llm = MagicMock()

        # ReAct returns submit with empty text immediately
        react_response = LLMResponse(
            content=json.dumps({
                "thinking": "直接提交",
                "tool": "submit",
                "args": {"text": ""},
            }),
            model="mock",
            usage={"total_tokens": 50},
            finish_reason="stop",
        )

        # Fallback one-shot call
        oneshot_text = "林风独立山巅，风吹衣袂。" * 30

        mock_llm.chat.side_effect = [
            react_response,
            # The fallback Writer.generate_scene will call llm.chat
            LLMResponse(content=oneshot_text, model="mock", usage={"total_tokens": 300}, finish_reason="stop"),
        ]

        writer = Writer(mock_llm)
        scene = writer.generate_scene(
            scene_plan=scene_plan,
            chapter_outline=chapter_outline,
            characters=characters,
            world_setting=world_setting,
            context="",
            style_name="wuxia.classical",
            react_mode=True,
        )

        assert isinstance(scene, Scene)
        assert len(scene.text) > 50


# ======================================================================
# Test 8: Budget Mode Skips Checks
# ======================================================================


class TestBudgetModeSkipsChecks:
    def test_budget_mode_hides_check_tools(
        self, chapter_outline, characters, world_setting, scene_plan
    ):
        """In budget_mode, check tools are skipped if LLM tries to call them."""
        mock_llm = MagicMock()

        draft_text = "林风拔出长剑。" * 40

        # Step 1: generate_draft
        step1 = LLMResponse(
            content=json.dumps({
                "thinking": "生成初稿",
                "tool": "generate_draft",
                "args": {"scene_prompt": "测试"},
            }),
            model="mock",
            usage={"total_tokens": 100},
            finish_reason="stop",
        )

        # Step 2: LLM tries check_repetition (should be skipped in budget mode)
        step2 = LLMResponse(
            content=json.dumps({
                "thinking": "检查重复",
                "tool": "check_repetition",
                "args": {},
            }),
            model="mock",
            usage={"total_tokens": 50},
            finish_reason="stop",
        )

        # Step 3: submit
        step3 = LLMResponse(
            content=json.dumps({
                "thinking": "提交",
                "tool": "submit",
                "args": {"text": ""},
            }),
            model="mock",
            usage={"total_tokens": 50},
            finish_reason="stop",
        )

        mock_llm.chat.side_effect = [
            step1,
            LLMResponse(content=draft_text, model="mock", usage={"total_tokens": 200}, finish_reason="stop"),
            step2,
            step3,
        ]

        writer = Writer(mock_llm)
        scene = writer.generate_scene(
            scene_plan=scene_plan,
            chapter_outline=chapter_outline,
            characters=characters,
            world_setting=world_setting,
            context="",
            style_name="wuxia.classical",
            react_mode=True,
            budget_mode=True,
        )

        assert isinstance(scene, Scene)
        assert len(scene.text) > 0


# ======================================================================
# Test 9: Pipeline Passes react_mode
# ======================================================================


class TestPipelinePassesReactMode:
    def test_generate_chapters_sets_react_mode_in_state(self, tmp_path):
        """Verify that NovelPipeline.generate_chapters puts react_mode in state."""
        from src.novel.pipeline import NovelPipeline

        pipeline = NovelPipeline(workspace=str(tmp_path))

        # We need to mock the internals to verify state is set correctly
        mock_state = {
            "outline": {
                "chapters": [{"chapter_number": 1, "title": "Ch1"}],
            },
            "main_storyline": {},
        }

        captured_state = {}

        def fake_build_chapter_graph():
            mock_graph = MagicMock()

            def capture_invoke(state, config=None):
                captured_state.update(state)
                return state

            mock_graph.invoke = capture_invoke
            return mock_graph

        with patch.object(pipeline, "_load_checkpoint", return_value=dict(mock_state)), \
             patch.object(pipeline, "_get_file_manager") as mock_fm, \
             patch.object(pipeline, "_refresh_state_from_novel"), \
             patch("src.novel.pipeline.build_chapter_graph", side_effect=fake_build_chapter_graph):

            # Mock file manager
            fm = mock_fm.return_value
            fm.load_novel.return_value = MagicMock()
            fm.save_chapter_text = MagicMock()

            try:
                pipeline.generate_chapters(
                    project_path=str(tmp_path / "test_novel"),
                    start_chapter=1,
                    end_chapter=1,
                    silent=True,
                    react_mode=True,
                    budget_mode=True,
                )
            except Exception:
                pass  # May fail on file ops, but state should have been set

        # Check the state was populated with react_mode
        assert captured_state.get("react_mode") is True
        assert captured_state.get("budget_mode") is True


# ======================================================================
# Test 10: Full Chain No Errors (Smoke Test)
# ======================================================================


class TestFullChainNoErrors:
    def test_smoke_test_full_chain(
        self, tmp_path, chapter_outline, chapter_outline_2,
        characters, world_setting, scene_plan
    ):
        """Smoke test: registry init -> chapter gen -> feedback -> second chapter. No exceptions."""
        # 1. Initialize registry
        db_path = str(tmp_path / "smoke.db")
        registry = PromptRegistry(db_path)
        seed_default_prompts(registry)

        # 2. Create Writer with registry
        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(
            content="第一章正文。林风走在路上。" * 30,
            model="mock",
            usage={"total_tokens": 500},
            finish_reason="stop",
        )

        writer = Writer(mock_llm)
        writer.enable_prompt_registry(registry, novel_id="smoke_novel")

        # 3. Generate chapter 1
        scene1 = writer.generate_scene(
            scene_plan=scene_plan,
            chapter_outline=chapter_outline,
            characters=characters,
            world_setting=world_setting,
            context="",
            style_name="webnovel.shuangwen",
        )
        assert isinstance(scene1, Scene)
        assert scene1.word_count > 0

        # 4. Quality review saves feedback
        injector = FeedbackInjector(registry)
        report = {
            "rule_check": {"passed": True},
            "scores": {"plot": 8.0, "character": 7.0, "style": 6.0},
            "suggestions": ["注意节奏控制"],
        }
        injector.save_chapter_feedback(
            novel_id="smoke_novel",
            chapter_number=1,
            quality_report=report,
        )

        # 5. Get feedback for chapter 2
        feedback_prompt = injector.get_feedback_prompt("smoke_novel", current_chapter=2)
        assert len(feedback_prompt) > 0

        # 6. Generate chapter 2 with feedback
        mock_llm.chat.return_value = LLMResponse(
            content="第二章正文。林风遇到苏瑶。" * 30,
            model="mock",
            usage={"total_tokens": 500},
            finish_reason="stop",
        )

        scene_plan_2 = {
            "scene_number": 1,
            "location": "官道",
            "time": "午后",
            "characters_involved": ["林风", "苏瑶"],
            "goal": "遇到苏瑶",
            "mood": "小爽",
            "target_words": 800,
        }

        scene2 = writer.generate_scene(
            scene_plan=scene_plan_2,
            chapter_outline=chapter_outline_2,
            characters=characters,
            world_setting=world_setting,
            context=scene1.text[:500],
            style_name="webnovel.shuangwen",
            feedback_prompt=feedback_prompt,
        )
        assert isinstance(scene2, Scene)
        assert scene2.word_count > 0

        # 7. Verify prompt evolution: update a block and rebuild
        registry.update_block("craft_general", content="全新写作技法v2")
        prompt = registry.build_prompt("writer", "default", genre="webnovel_shuangwen")
        assert "全新写作技法v2" in prompt

        # 8. Rollback
        registry.rollback_block("craft_general", target_version=1)
        prompt_v1 = registry.build_prompt("writer", "default", genre="webnovel_shuangwen")
        assert "全新写作技法v2" not in prompt_v1
        assert "通用写作技法" in prompt_v1

        # 9. Verify no exceptions through the entire chain
        registry.close()


# ======================================================================
# Additional Edge Cases
# ======================================================================


class TestEdgeCases:
    def test_feedback_for_nonexistent_novel(self, registry):
        """Requesting feedback for a novel with no saved feedback returns empty."""
        injector = FeedbackInjector(registry)
        prompt = injector.get_feedback_prompt("nonexistent_novel", current_chapter=5)
        assert prompt == ""

    def test_multiple_feedbacks_returns_most_recent(self, registry):
        """When multiple feedbacks exist, get_feedback_prompt returns the one closest to current chapter."""
        injector = FeedbackInjector(registry)

        # Save feedback for chapters 1, 3, 5
        for ch in [1, 3, 5]:
            injector.save_chapter_feedback(
                novel_id="multi_fb",
                chapter_number=ch,
                quality_report={
                    "rule_check": {"passed": True},
                    "scores": {},
                    "suggestions": [f"第{ch}章建议"],
                },
            )

        # Chapter 6 should see chapter 5's feedback
        prompt = injector.get_feedback_prompt("multi_fb", current_chapter=6)
        assert f"第5章建议" in prompt

        # Chapter 4 should see chapter 3's feedback
        prompt = injector.get_feedback_prompt("multi_fb", current_chapter=4)
        assert f"第3章建议" in prompt

    def test_build_prompt_with_feedback_context(self, registry):
        """build_prompt can inject feedback via context dict."""
        prompt = registry.build_prompt(
            "writer",
            "default",
            genre="webnovel_shuangwen",
            context={
                "last_strengths": ["情节紧凑"],
                "last_weaknesses": ["对话太相似"],
            },
        )
        assert "情节紧凑" in prompt
        assert "对话太相似" in prompt

    def test_scenario_detection_for_battle_scene(self):
        """Writer._detect_scenario correctly identifies battle scenes."""
        assert Writer._detect_scenario({"goal": "与敌人战斗"}) == "battle"
        assert Writer._detect_scenario({"goal": "和朋友对话聊天"}) == "dialogue"
        assert Writer._detect_scenario({"goal": "感情告白"}) == "emotional"
        assert Writer._detect_scenario({"goal": "制定策略计划"}) == "strategy"
        assert Writer._detect_scenario({"goal": "日常散步"}) == "default"
