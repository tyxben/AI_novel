"""Tests for Intervention D: Writer Style Anchoring (StyleBible).

Covers:
- StyleBible model validation
- StyleBibleGenerator.generate (LLM success + fallback)
- StyleBibleGenerator.generate_from_existing_chapters (migration)
- Text analysis helpers (sentence length, dialogue ratio, sensory density)
- StyleKeeper.check_against_bible (quantitative gate)
- ContinuityService style brief injection
- QualityReviewer.should_rewrite with style bible check
- Pipeline style_bible wiring
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.novel.models.narrative_control import StyleBible


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="test-model", usage=None)


def _make_style_bible_dict() -> dict:
    """A valid style bible dict matching the webnovel.shuangwen preset."""
    return {
        "quantitative_targets": {
            "avg_sentence_length": [8, 18],
            "dialogue_ratio": [0.40, 0.60],
            "sensory_density": [0.5, 1.5],
            "exclamation_ratio": [0.05, 0.15],
        },
        "voice_description": "短句快节奏，对话密集，避免长段心理独白",
        "exemplar_paragraphs": [
            "林辰冷笑。'就凭他们？'轰！一掌拍出，三人倒飞。全场寂静。",
            "一股恐怖的气浪横扫全场，那几个嘲笑他的弟子直接被震飞出去。",
        ],
        "anti_patterns": [
            "避免'XX的XX气息'堆叠",
            "禁止超过3行的心理独白",
        ],
    }


def _make_llm_bible_json() -> str:
    """JSON that a successful LLM call would return."""
    return json.dumps({
        "quantitative_targets": {
            "avg_sentence_length": [10, 20],
            "dialogue_ratio": [0.35, 0.55],
            "sensory_density": [0.5, 2.0],
            "exclamation_ratio": [0.05, 0.12],
        },
        "voice_description": "快节奏爽文，短句为主，对话密集",
        "exemplar_paragraphs": [
            "轰！一道恐怖的气浪从林辰体内爆发而出。全场寂静。",
            "\"废物？\"林辰嘴角微扬，随手一挥。",
        ],
        "anti_patterns": [
            "避免冗长景物描写",
            "禁止说教式对话",
        ],
    }, ensure_ascii=False)


# Short sentences, high dialogue, typical shuangwen text
_SHUANGWEN_TEXT = (
    "\"你说什么？\"张三瞪大了眼。\n"
    "林辰冷笑一声。\n"
    "\"我说，滚。\"\n"
    "轰！一掌拍出。张三倒飞。\n"
    "全场寂静。没有人敢说话。\n"
    "\"还有谁？\"林辰环视四周。\n"
)

# Long sentences, low dialogue, heavy sensory descriptions
_ATMOSPHERIC_TEXT = (
    "焦油的腥臭混杂着矿泥的潮湿气息从废道口涌入，"
    "夜风裹挟着冷气穿过矿洞的缝隙，"
    "将那股刺鼻的味道送到了每个人的鼻腔之中，"
    "让人忍不住皱起了眉头。"
    "远处的火光在浓雾中若隐若现，"
    "像是一盏即将熄灭的灯笼，"
    "发出微弱的光芒照亮了周围狭窄的通道。"
    "矿道的石壁上渗出了冰冷的水珠，"
    "在火光的映照下闪烁着寒光。"
)


# ===================================================================
# 1. StyleBible Model Validation
# ===================================================================

class TestStyleBibleModel:
    def test_valid_bible(self):
        """Valid input should be accepted."""
        bible = StyleBible(**_make_style_bible_dict())
        assert bible.voice_description == "短句快节奏，对话密集，避免长段心理独白"
        assert len(bible.exemplar_paragraphs) == 2
        assert bible.quantitative_targets["avg_sentence_length"] == [8, 18]
        assert bible.volume_overrides is None
        assert bible.based_on_chapters is None

    def test_min_max_range_validation(self):
        """min > max in quantitative_targets should raise."""
        data = _make_style_bible_dict()
        data["quantitative_targets"]["avg_sentence_length"] = [20, 8]  # inverted
        with pytest.raises(ValueError, match="min.*max"):
            StyleBible(**data)

    def test_too_few_exemplars(self):
        """Less than 2 exemplar paragraphs should raise."""
        data = _make_style_bible_dict()
        data["exemplar_paragraphs"] = ["只有一段"]
        with pytest.raises(ValueError):
            StyleBible(**data)

    def test_voice_description_too_short(self):
        """Very short voice_description should raise."""
        data = _make_style_bible_dict()
        data["voice_description"] = "短"
        with pytest.raises(ValueError):
            StyleBible(**data)

    def test_serialization_roundtrip(self):
        """model_dump -> StyleBible should produce identical object."""
        bible = StyleBible(**_make_style_bible_dict())
        dumped = bible.model_dump()
        restored = StyleBible(**dumped)
        assert restored == bible

    def test_optional_fields(self):
        """volume_overrides and based_on_chapters are optional."""
        data = _make_style_bible_dict()
        data["volume_overrides"] = {1: {"dialogue_ratio": [0.5, 0.7]}}
        data["based_on_chapters"] = [1, 2, 3]
        bible = StyleBible(**data)
        assert bible.volume_overrides == {1: {"dialogue_ratio": [0.5, 0.7]}}
        assert bible.based_on_chapters == [1, 2, 3]


# ===================================================================
# 2. Text Analysis Helpers
# ===================================================================

class TestTextMetrics:
    def test_avg_sentence_length_short_sentences(self):
        from src.novel.services.style_bible_generator import compute_avg_sentence_length
        text = "你好。世界。很好。"  # 3 sentences: 2, 2, 2 chars
        result = compute_avg_sentence_length(text)
        assert 1.5 <= result <= 3.0

    def test_avg_sentence_length_empty(self):
        from src.novel.services.style_bible_generator import compute_avg_sentence_length
        assert compute_avg_sentence_length("") == 0.0
        assert compute_avg_sentence_length("   ") == 0.0

    def test_dialogue_ratio_high(self):
        from src.novel.services.style_bible_generator import compute_dialogue_ratio
        text = "\u201c你好\u201d\u201c世界\u201d"
        ratio = compute_dialogue_ratio(text)
        assert ratio > 0.5

    def test_dialogue_ratio_zero(self):
        from src.novel.services.style_bible_generator import compute_dialogue_ratio
        text = "没有任何对话的纯叙述文本。"
        ratio = compute_dialogue_ratio(text)
        assert ratio == 0.0

    def test_sensory_density(self):
        from src.novel.services.style_bible_generator import compute_sensory_density
        # 10 chars with 2 sensory words
        text = "气味很臭，声音很大，光芒刺眼。"
        density = compute_sensory_density(text)
        assert density > 0.0

    def test_sensory_density_empty(self):
        from src.novel.services.style_bible_generator import compute_sensory_density
        assert compute_sensory_density("") == 0.0


# ===================================================================
# 3. StyleBibleGenerator
# ===================================================================

class TestStyleBibleGenerator:
    def test_generate_success(self):
        """LLM returns valid JSON -> StyleBible generated."""
        from src.novel.services.style_bible_generator import StyleBibleGenerator

        llm = MagicMock()
        llm.chat.return_value = _make_llm_response(_make_llm_bible_json())

        gen = StyleBibleGenerator(llm)
        bible = gen.generate(genre="玄幻", theme="少年修炼", style_name="webnovel.shuangwen")

        assert isinstance(bible, StyleBible)
        assert bible.voice_description == "快节奏爽文，短句为主，对话密集"
        assert len(bible.exemplar_paragraphs) >= 2
        assert "avg_sentence_length" in bible.quantitative_targets
        assert bible.generated_at is not None
        llm.chat.assert_called_once()

    def test_generate_llm_failure_uses_fallback(self):
        """LLM raises exception -> fallback bible from preset."""
        from src.novel.services.style_bible_generator import StyleBibleGenerator

        llm = MagicMock()
        llm.chat.side_effect = RuntimeError("API error")

        gen = StyleBibleGenerator(llm)
        bible = gen.generate(genre="玄幻", theme="少年修炼", style_name="webnovel.shuangwen")

        assert isinstance(bible, StyleBible)
        # Fallback uses preset constraints
        assert bible.quantitative_targets["avg_sentence_length"] == [8, 18]
        assert "基于" in bible.voice_description

    def test_generate_invalid_json_uses_fallback(self):
        """LLM returns garbage JSON -> fallback."""
        from src.novel.services.style_bible_generator import StyleBibleGenerator

        llm = MagicMock()
        llm.chat.return_value = _make_llm_response("not json at all")

        gen = StyleBibleGenerator(llm)
        bible = gen.generate(genre="武侠", theme="江湖恩怨", style_name="wuxia.classical")

        assert isinstance(bible, StyleBible)
        assert bible.quantitative_targets["avg_sentence_length"] == [20, 40]

    def test_generate_invalid_style_name(self):
        """Non-existent style name -> ValueError."""
        from src.novel.services.style_bible_generator import StyleBibleGenerator

        llm = MagicMock()
        gen = StyleBibleGenerator(llm)

        with pytest.raises(ValueError, match="风格预设不存在"):
            gen.generate(genre="玄幻", theme="test", style_name="nonexistent.style")

    def test_generate_from_existing_chapters(self):
        """Migration: generate from chapter text."""
        from src.novel.services.style_bible_generator import StyleBibleGenerator

        llm = MagicMock()
        gen = StyleBibleGenerator(llm)

        chapters = [
            {"chapter_number": 1, "full_text": _SHUANGWEN_TEXT * 5},
            {"chapter_number": 2, "full_text": _SHUANGWEN_TEXT * 5},
            {"chapter_number": 3, "full_text": _SHUANGWEN_TEXT * 5},
        ]
        bible = gen.generate_from_existing_chapters(
            chapters=chapters,
            style_name="webnovel.shuangwen",
            genre="玄幻",
        )

        assert isinstance(bible, StyleBible)
        assert bible.based_on_chapters == [1, 2, 3]
        # Targets should bracket the actual metrics
        targets = bible.quantitative_targets
        assert isinstance(targets["avg_sentence_length"], list)
        assert targets["avg_sentence_length"][0] < targets["avg_sentence_length"][1]
        # No LLM call for migration
        llm.chat.assert_not_called()

    def test_generate_from_empty_chapters_raises(self):
        """Migration with empty chapters -> ValueError."""
        from src.novel.services.style_bible_generator import StyleBibleGenerator

        llm = MagicMock()
        gen = StyleBibleGenerator(llm)

        with pytest.raises(ValueError, match="No chapters"):
            gen.generate_from_existing_chapters(
                chapters=[], style_name="webnovel.shuangwen", genre="玄幻"
            )


# ===================================================================
# 4. StyleKeeper.check_against_bible — REMOVED (Phase 2-β)
# ===================================================================
# The StyleKeeper agent has been merged into Reviewer. The
# `check_against_bible` quantitative gate no longer exists — style bible
# compliance is now surfaced through Reviewer issues (via style_overuse_hits
# + LLM critique). If a regression harness is needed, see
# tests/novel/agents/test_reviewer.py.

@pytest.mark.skip(reason="StyleKeeper removed in Phase 2-β merge into Reviewer")
class TestStyleKeeperBibleCheck:
    def test_text_within_range_passes(self):
        """Text matching target ranges -> passed=True."""
        from src.novel.agents.style_keeper import StyleKeeper

        keeper = StyleKeeper(llm_client=None)
        # Build a bible whose targets match the shuangwen text's actual metrics
        # (short sentences ~4-5 chars, moderate dialogue ~28%)
        bible = _make_style_bible_dict()
        bible["quantitative_targets"]["avg_sentence_length"] = [3, 10]
        bible["quantitative_targets"]["dialogue_ratio"] = [0.10, 0.50]
        bible["quantitative_targets"]["sensory_density"] = [0.0, 50.0]

        need_rewrite, report = keeper.check_against_bible(
            text=_SHUANGWEN_TEXT,
            style_bible=bible,
        )
        assert need_rewrite is False
        assert report["deviations"] == []
        assert report["need_rewrite"] is False

    def test_long_sentences_trigger_rewrite(self):
        """Sentence length 50% over target -> need_rewrite=True."""
        from src.novel.agents.style_keeper import StyleKeeper

        keeper = StyleKeeper(llm_client=None)
        bible = _make_style_bible_dict()
        # atmospheric text has very long sentences
        need_rewrite, report = keeper.check_against_bible(
            text=_ATMOSPHERIC_TEXT,
            style_bible=bible,
        )
        assert need_rewrite is True
        deviations = report["deviations"]
        assert any("句长" in d for d in deviations)

    def test_low_dialogue_triggers_rewrite(self):
        """Dialogue ratio 20pp below target -> need_rewrite=True."""
        from src.novel.agents.style_keeper import StyleKeeper

        keeper = StyleKeeper(llm_client=None)
        bible = _make_style_bible_dict()
        # Bible targets dialogue [0.40, 0.60]; atmospheric text has nearly 0
        need_rewrite, report = keeper.check_against_bible(
            text=_ATMOSPHERIC_TEXT,
            style_bible=bible,
        )
        assert need_rewrite is True
        deviations = report["deviations"]
        assert any("对话占比" in d for d in deviations)

    def test_high_sensory_density_triggers_rewrite(self):
        """Sensory density > 2x target max -> need_rewrite=True."""
        from src.novel.agents.style_keeper import StyleKeeper

        keeper = StyleKeeper(llm_client=None)
        bible = _make_style_bible_dict()
        bible["quantitative_targets"]["sensory_density"] = [0.1, 0.5]  # very tight

        # Create text with lots of sensory words
        sensory_text = "气味很浓。光芒刺眼。声音震耳。冷气逼人。热气蒸腾。" * 20
        need_rewrite, report = keeper.check_against_bible(
            text=sensory_text,
            style_bible=bible,
        )
        assert need_rewrite is True
        deviations = report["deviations"]
        assert any("感官" in d for d in deviations)

    def test_all_metrics_in_range(self):
        """When all metrics match -> passed=True, no deviations."""
        from src.novel.agents.style_keeper import StyleKeeper

        keeper = StyleKeeper(llm_client=None)
        # Set wide ranges that should pass for any reasonable text
        bible = _make_style_bible_dict()
        bible["quantitative_targets"] = {
            "avg_sentence_length": [1, 100],
            "dialogue_ratio": [0.0, 1.0],
            "sensory_density": [0.0, 100.0],
        }
        need_rewrite, report = keeper.check_against_bible(
            text=_SHUANGWEN_TEXT,
            style_bible=bible,
        )
        assert need_rewrite is False
        assert report["deviations"] == []

    def test_volume_overrides_applied(self):
        """Volume overrides should replace base targets."""
        from src.novel.agents.style_keeper import StyleKeeper

        keeper = StyleKeeper(llm_client=None)
        bible = _make_style_bible_dict()
        # Base: dialogue [0.40, 0.60]
        # Volume 2 override: dialogue [0.0, 1.0] (very permissive)
        bible["volume_overrides"] = {"2": {"dialogue_ratio": [0.0, 1.0]}}

        # Atmospheric text has low dialogue, would fail base check
        need_rewrite_base, _ = keeper.check_against_bible(
            text=_ATMOSPHERIC_TEXT,
            style_bible=bible,
            current_volume=None,
        )

        need_rewrite_v2, _ = keeper.check_against_bible(
            text=_ATMOSPHERIC_TEXT,
            style_bible=bible,
            current_volume=2,
        )

        # With volume 2 override, dialogue check should be permissive
        # (the sentence length check may still trigger though)
        # We only verify that the override changes the result for dialogue
        assert need_rewrite_base is True  # base fails (dialogue too low)

    def test_report_includes_metrics(self):
        """Report should include measured metrics."""
        from src.novel.agents.style_keeper import StyleKeeper

        keeper = StyleKeeper(llm_client=None)
        bible = _make_style_bible_dict()
        _, report = keeper.check_against_bible(
            text=_SHUANGWEN_TEXT,
            style_bible=bible,
        )
        assert "metrics" in report
        assert "avg_sentence_length" in report["metrics"]
        assert "dialogue_ratio" in report["metrics"]
        assert "sensory_density" in report["metrics"]


# ===================================================================
# 5. ContinuityService Style Brief Injection
# ===================================================================

class TestContinuityServiceStyleBrief:
    def test_style_brief_injected_when_bible_provided(self):
        """format_for_prompt includes style section when style_bible is in brief."""
        from src.novel.services.continuity_service import ContinuityService

        svc = ContinuityService()
        bible = _make_style_bible_dict()
        brief = svc.generate_brief(
            chapter_number=5,
            style_bible=bible,
            current_volume=1,
        )

        assert brief["style_brief"] is not None
        targets = brief["style_brief"]["quantitative_targets"]
        assert targets["avg_sentence_length"] == [8, 18]

        # Format and check output
        prompt = svc.format_for_prompt(brief)
        assert "风格锚定要求" in prompt
        assert "句长" in prompt
        assert "对话占比" in prompt
        assert "风格示范" in prompt

    def test_no_crash_without_bible(self):
        """No style_bible -> no crash, no style section."""
        from src.novel.services.continuity_service import ContinuityService

        svc = ContinuityService()
        brief = svc.generate_brief(chapter_number=5)
        assert brief.get("style_brief") is None
        prompt = svc.format_for_prompt(brief)
        assert "风格锚定要求" not in prompt

    def test_volume_override_in_style_brief(self):
        """Volume override replaces base targets in style_brief."""
        from src.novel.services.continuity_service import ContinuityService

        svc = ContinuityService()
        bible = _make_style_bible_dict()
        bible["volume_overrides"] = {"2": {"dialogue_ratio": [0.50, 0.70]}}
        brief = svc.generate_brief(
            chapter_number=30,
            style_bible=bible,
            current_volume=2,
        )
        targets = brief["style_brief"]["quantitative_targets"]
        assert targets["dialogue_ratio"] == [0.50, 0.70]

    def test_prompt_length_under_500_chars(self):
        """Style prompt section should be under 500 chars."""
        from src.novel.services.continuity_service import ContinuityService

        svc = ContinuityService()
        bible = _make_style_bible_dict()
        brief = svc.generate_brief(
            chapter_number=5,
            style_bible=bible,
        )
        prompt = svc.format_for_prompt(brief)
        # The style section is a subset of the full prompt
        # Extract just the style section
        if "风格锚定要求" in prompt:
            idx = prompt.index("风格锚定要求")
            style_section = prompt[idx:]
            # Should be reasonable length
            assert len(style_section) < 800  # generous limit including exemplars

    def test_anti_patterns_in_prompt(self):
        """Anti-patterns should appear in formatted prompt."""
        from src.novel.services.continuity_service import ContinuityService

        svc = ContinuityService()
        bible = _make_style_bible_dict()
        brief = svc.generate_brief(chapter_number=5, style_bible=bible)
        prompt = svc.format_for_prompt(brief)
        assert "禁止模式" in prompt
        assert "气息" in prompt  # from anti_patterns


# ===================================================================
# 6. QualityReviewer.should_rewrite with Style Bible — REMOVED (Phase 2-β)
# ===================================================================
# QualityReviewer merged into Reviewer; `should_rewrite` is replaced by
# `CritiqueResult.need_rewrite` (information label only; never triggers
# auto-rewrite). See tests/novel/agents/test_reviewer.py.

@pytest.mark.skip(reason="QualityReviewer removed in Phase 2-β merge into Reviewer")
class TestQualityReviewerStyleBible:
    def test_style_bible_need_rewrite_forces_rewrite(self):
        """style_bible_check.need_rewrite=True -> should_rewrite returns True."""
        from src.novel.agents.quality_reviewer import QualityReviewer

        reviewer = QualityReviewer()
        report = {
            "rule_check": {"passed": True},
            "scores": {"plot_coherence": 8.0, "writing_quality": 8.0},
            "retention_scores": {},
            "need_rewrite": False,
            "style_bible_check": {
                "need_rewrite": True,
                "deviations": ["句长超标 +50%"],
            },
        }
        assert reviewer.should_rewrite(report, threshold=6.0) is True

    def test_no_style_bible_check_no_effect(self):
        """Without style_bible_check, should_rewrite uses standard logic."""
        from src.novel.agents.quality_reviewer import QualityReviewer

        reviewer = QualityReviewer()
        report = {
            "rule_check": {"passed": True},
            "scores": {"plot_coherence": 8.0},
            "retention_scores": {},
            "need_rewrite": False,
        }
        assert reviewer.should_rewrite(report) is False

    def test_style_bible_passed_no_forced_rewrite(self):
        """style_bible_check.need_rewrite=False -> no forced rewrite."""
        from src.novel.agents.quality_reviewer import QualityReviewer

        reviewer = QualityReviewer()
        report = {
            "rule_check": {"passed": True},
            "scores": {"plot_coherence": 8.0},
            "retention_scores": {},
            "need_rewrite": False,
            "style_bible_check": {
                "need_rewrite": False,
                "deviations": [],
            },
        }
        assert reviewer.should_rewrite(report) is False


# ===================================================================
# 7. Pipeline Wiring
# ===================================================================

class TestPipelineStyleBibleWiring:
    def test_refresh_state_loads_style_bible(self):
        """_refresh_state_from_novel should load style_bible."""
        from src.novel.pipeline import NovelPipeline

        state = {"style_name": "old"}
        novel_data = {
            "style_name": "webnovel.shuangwen",
            "style_bible": _make_style_bible_dict(),
        }
        NovelPipeline._refresh_state_from_novel(state, novel_data)
        assert state["style_bible"] == _make_style_bible_dict()

    def test_refresh_state_no_bible(self):
        """_refresh_state_from_novel without style_bible -> no crash."""
        from src.novel.pipeline import NovelPipeline

        state = {"style_name": "old"}
        novel_data = {"style_name": "webnovel.shuangwen"}
        NovelPipeline._refresh_state_from_novel(state, novel_data)
        assert "style_bible" not in state

    def test_chapter_to_volume(self):
        """_chapter_to_volume should identify volume from outline."""
        from src.novel.pipeline import NovelPipeline

        outline = {
            "volumes": [
                {"volume_number": 1, "start_chapter": 1, "end_chapter": 25},
                {"volume_number": 2, "start_chapter": 26, "end_chapter": 50},
            ],
        }
        assert NovelPipeline._chapter_to_volume(5, outline) == 1
        assert NovelPipeline._chapter_to_volume(30, outline) == 2
        assert NovelPipeline._chapter_to_volume(60, outline) is None

    def test_chapter_to_volume_no_volumes(self):
        """_chapter_to_volume with no volumes -> None."""
        from src.novel.pipeline import NovelPipeline

        assert NovelPipeline._chapter_to_volume(5, {}) is None
        assert NovelPipeline._chapter_to_volume(5, {"volumes": []}) is None


# ===================================================================
# 8. style_keeper_node integration — REMOVED (Phase 2-β)
# ===================================================================
# style_keeper_node no longer exists — the chapter graph runs a single
# reviewer_node (tests/novel/agents/test_reviewer.py covers the wire-up).

@pytest.mark.skip(reason="style_keeper_node removed in Phase 2-β merge into Reviewer")
class TestStyleKeeperNode:
    def test_node_with_style_bible(self):
        """style_keeper_node should call check_against_bible when bible present."""
        from src.novel.agents.style_keeper import style_keeper_node

        state = {
            "current_chapter_text": _SHUANGWEN_TEXT,
            "style_name": "webnovel.shuangwen",
            "style_bible": _make_style_bible_dict(),
            "current_volume": 1,
            "current_chapter_quality": {},
            "config": {},
        }
        result = style_keeper_node(state)
        quality = result["current_chapter_quality"]
        assert "style_need_rewrite" in quality
        assert "style_bible_deviations" in quality
        assert isinstance(quality["style_need_rewrite"], bool)

    def test_node_without_style_bible(self):
        """style_keeper_node should work without style_bible."""
        from src.novel.agents.style_keeper import style_keeper_node

        state = {
            "current_chapter_text": _SHUANGWEN_TEXT,
            "style_name": "webnovel.shuangwen",
            "current_chapter_quality": {},
            "config": {},
        }
        result = style_keeper_node(state)
        quality = result["current_chapter_quality"]
        # Should have metrics but bible check defaults to False
        assert quality.get("style_need_rewrite", False) is False


# ===================================================================
# 9. Checkpoint round-trip
# ===================================================================

class TestCheckpointRoundTrip:
    def test_style_bible_survives_json_roundtrip(self):
        """StyleBible should survive JSON serialization."""
        bible = StyleBible(**_make_style_bible_dict())
        dumped = bible.model_dump()
        json_str = json.dumps(dumped, ensure_ascii=False)
        restored_dict = json.loads(json_str)
        restored = StyleBible(**restored_dict)
        assert restored.voice_description == bible.voice_description
        assert restored.quantitative_targets == bible.quantitative_targets
        assert restored.exemplar_paragraphs == bible.exemplar_paragraphs


# ===================================================================
# 10. ProjectArchitect.propose_main_outline style bible generation
#     (Phase 3-B3：从 novel_director_node 迁入)
# ===================================================================

class TestProjectArchitectMainOutlineStyleBible:
    def test_propose_main_outline_generates_style_bible(self):
        """ProjectArchitect.propose_main_outline 产出 MainOutlineProposal 应带 style_bible。"""
        from src.novel.agents.project_architect import ProjectArchitect

        llm_response_outline = _make_llm_response(json.dumps({
            "title": "测试小说",
            "acts": [{"act_name": "第一幕", "description": "开端"}],
            "volumes": [{
                "volume_number": 1,
                "volume_title": "卷一",
                "theme": "测试",
                "start_chapter": 1,
                "end_chapter": 5,
            }],
            "chapters": [
                {"chapter_number": i, "title": f"第{i}章", "goal": f"目标{i}",
                 "key_events": [f"事件{i}"], "mood": "紧张",
                 "involved_characters": ["主角"]}
                for i in range(1, 6)
            ],
            "main_storyline": {
                "protagonist_goal": "成为强者",
                "core_conflict": "敌人",
                "character_arc": "成长",
                "stakes": "生死",
                "theme_statement": "坚持",
            },
        }, ensure_ascii=False))

        llm_response_bible = _make_llm_response(_make_llm_bible_json())

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [llm_response_outline, llm_response_bible]

        architect = ProjectArchitect(mock_llm)
        proposal = architect.propose_main_outline(
            genre="玄幻",
            theme="修炼",
            target_words=10000,
        )

        assert proposal.style_bible is not None
        assert proposal.template
        assert proposal.style_name
