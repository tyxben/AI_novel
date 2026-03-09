"""Agent 架构严格测试 — 覆盖边界条件、错误路径、状态一致性与回归。"""
from __future__ import annotations

import json
import operator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 被测模块
# ---------------------------------------------------------------------------
from src.agents.state import AgentState, Decision, QualityEvaluation
from src.agents.utils import (
    make_decision,
    save_decisions_to_file,
    load_decisions_from_file,
    extract_json_obj,
    extract_json_array,
)
from src.agents.director import DirectorAgent, director_node
from src.agents.content_analyzer import (
    ContentAnalyzerAgent,
    content_analyzer_node,
)
from src.agents.art_director import ArtDirectorAgent, art_director_node
from src.agents.voice_director import (
    VoiceDirectorAgent,
    voice_director_node,
    EMOTION_TTS_PARAMS,
)
from src.agents.editor import editor_node
from src.tools.segment_tool import SegmentTool
from src.tools.prompt_gen_tool import PromptGenTool
from src.tools.image_gen_tool import ImageGenTool
from src.tools.tts_tool import TTSTool
from src.tools.video_assemble_tool import VideoAssembleTool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_config() -> dict:
    """最小可用配置，包含所有必需字段。"""
    return {
        "segmenter": {"method": "simple", "max_chars": 100, "min_chars": 20},
        "promptgen": {},
        "imagegen": {"backend": "together"},
        "tts": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "volume": "+0%"},
        "video": {"resolution": [1080, 1920]},
        "llm": {},
        "project": {"default_workspace": "workspace", "default_output": "output"},
    }


@pytest.fixture
def sample_text() -> str:
    """包含对话的武侠风格短文本。"""
    return (
        "张三说道：剑气纵横三万里，一剑光寒十九洲。"
        "李四笑道：好一招落叶飞花剑！"
        "只见张三内力涌动，江湖之上再无敌手。"
    )


@pytest.fixture
def long_text() -> str:
    """超长文本（> 500 字），触发 analysis_needed=True。"""
    return "这是一段修炼小说。灵气充沛的宗门内，弟子们正在渡劫修炼。" * 50


@pytest.fixture
def base_state(minimal_config, sample_text, tmp_path) -> dict:
    """供节点函数使用的基础 state dict。"""
    return {
        "input_file": str(tmp_path / "novel.txt"),
        "config": minimal_config,
        "workspace": str(tmp_path / "ws"),
        "mode": "agent",
        "budget_mode": False,
        "resume": False,
        "full_text": sample_text,
        "genre": None,
        "era": None,
        "characters": None,
        "suggested_style": None,
        "segments": [],
        "prompts": [],
        "images": [],
        "video_clips": None,
        "audio_files": [],
        "srt_files": [],
        "final_video": None,
        "quality_scores": [],
        "retry_counts": {},
        "decisions": [],
        "errors": [],
        "pipeline_plan": None,
    }


# ===================================================================
# TestAgentState
# ===================================================================
class TestAgentState:
    """AgentState TypedDict 结构与 Annotated reducer 验证。"""

    def test_decisions_field_has_add_reducer(self):
        """decisions 字段应使用 operator.add 作为 reducer。"""
        from typing import get_type_hints
        hints = get_type_hints(AgentState, include_extras=True)
        ann = hints["decisions"]
        assert hasattr(ann, "__metadata__"), "decisions should be Annotated"
        assert operator.add in ann.__metadata__

    def test_errors_field_has_add_reducer(self):
        """errors 字段应使用 operator.add 作为 reducer。"""
        from typing import get_type_hints
        hints = get_type_hints(AgentState, include_extras=True)
        ann = hints["errors"]
        assert hasattr(ann, "__metadata__")
        assert operator.add in ann.__metadata__

    def test_decision_typeddict_fields(self):
        """Decision 应包含 agent/step/decision/reason/data/timestamp。"""
        expected = {"agent", "step", "decision", "reason", "data", "timestamp"}
        assert set(Decision.__annotations__.keys()) == expected

    def test_quality_evaluation_fields(self):
        """QualityEvaluation 应包含评分维度字段。"""
        expected = {"score", "composition", "clarity", "text_match", "color",
                    "consistency", "feedback", "passed"}
        assert set(QualityEvaluation.__annotations__.keys()) == expected

    def test_agent_state_total_false(self):
        """AgentState total=False，允许部分字段缺失。"""
        # 可以创建空的 AgentState
        state = AgentState()
        assert isinstance(state, dict)

    def test_state_can_hold_arbitrary_subsets(self):
        """只传入部分字段不应报错。"""
        state = AgentState(full_text="hello", decisions=[])
        assert state["full_text"] == "hello"
        assert state["decisions"] == []


# ===================================================================
# TestDecisionUtils
# ===================================================================
class TestDecisionUtils:
    """make_decision、save/load、JSON 提取工具函数。"""

    def test_make_decision_basic(self):
        """make_decision 应返回包含所有字段的 Decision。"""
        d = make_decision("TestAgent", "test_step", "did_thing", "because")
        assert d["agent"] == "TestAgent"
        assert d["step"] == "test_step"
        assert d["decision"] == "did_thing"
        assert d["reason"] == "because"
        assert d["data"] is None
        assert "timestamp" in d

    def test_make_decision_with_data(self):
        """make_decision 应正确附带 data 字典。"""
        d = make_decision("A", "s", "d", "r", data={"key": 42})
        assert d["data"] == {"key": 42}

    def test_make_decision_timestamp_is_iso(self):
        """timestamp 应为 ISO 8601 格式。"""
        d = make_decision("A", "s", "d", "r")
        from datetime import datetime
        # 应能解析
        datetime.fromisoformat(d["timestamp"])

    def test_save_and_load_decisions(self, tmp_path):
        """save 后 load 应返回相同数据。"""
        decisions = [
            make_decision("A", "1", "d1", "r1"),
            make_decision("B", "2", "d2", "r2", data={"x": 1}),
        ]
        state = {"decisions": decisions}
        filepath = tmp_path / "decisions.json"
        save_decisions_to_file(state, filepath)

        loaded = load_decisions_from_file(filepath)
        assert len(loaded) == 2
        assert loaded[0]["agent"] == "A"
        assert loaded[1]["data"] == {"x": 1}

    def test_save_decisions_creates_parent_dirs(self, tmp_path):
        """保存时应自动创建父目录。"""
        filepath = tmp_path / "sub" / "dir" / "decisions.json"
        save_decisions_to_file({"decisions": []}, filepath)
        assert filepath.exists()

    def test_save_decisions_empty_state(self, tmp_path):
        """state 中无 decisions 字段时保存空列表。"""
        filepath = tmp_path / "d.json"
        save_decisions_to_file({}, filepath)
        loaded = load_decisions_from_file(filepath)
        assert loaded == []

    def test_load_decisions_missing_file(self, tmp_path):
        """文件不存在时返回空列表。"""
        result = load_decisions_from_file(tmp_path / "nonexistent.json")
        assert result == []

    def test_load_decisions_corrupted_json(self, tmp_path):
        """JSON 格式错误时返回空列表，不抛异常。"""
        filepath = tmp_path / "bad.json"
        filepath.write_text("{not valid json!!!", encoding="utf-8")
        result = load_decisions_from_file(filepath)
        assert result == []

    def test_load_decisions_non_list_json(self, tmp_path):
        """JSON 文件是对象而非数组时返回空列表。"""
        filepath = tmp_path / "obj.json"
        filepath.write_text('{"agent": "test"}', encoding="utf-8")
        result = load_decisions_from_file(filepath)
        assert result == []

    # --- extract_json_obj ---

    def test_extract_json_obj_pure_json(self):
        """纯 JSON 字符串直接解析。"""
        result = extract_json_obj('{"a": 1, "b": "hello"}')
        assert result == {"a": 1, "b": "hello"}

    def test_extract_json_obj_with_surrounding_text(self):
        """JSON 对象前后有文字时仍能提取。"""
        text = 'Here is the result: {"genre": "武侠", "era": "古代"} end.'
        result = extract_json_obj(text)
        assert result is not None
        assert result["genre"] == "武侠"

    def test_extract_json_obj_garbage(self):
        """完全无法解析时返回 None。"""
        assert extract_json_obj("this is not json at all") is None

    def test_extract_json_obj_empty_string(self):
        """空字符串返回 None。"""
        assert extract_json_obj("") is None

    def test_extract_json_obj_none_input(self):
        """None 输入安全返回 None。"""
        assert extract_json_obj(None) is None

    def test_extract_json_obj_nested(self):
        """嵌套 JSON 对象能正确提取。"""
        text = '```json\n{"a": {"b": [1, 2]}, "c": true}\n```'
        result = extract_json_obj(text)
        assert result == {"a": {"b": [1, 2]}, "c": True}

    def test_extract_json_obj_malformed_braces(self):
        """不匹配的花括号返回 None。"""
        assert extract_json_obj("{broken json") is None

    # --- extract_json_array ---

    def test_extract_json_array_pure(self):
        """纯 JSON 数组直接解析。"""
        result = extract_json_array('[{"name": "张三"}, {"name": "李四"}]')
        assert len(result) == 2
        assert result[0]["name"] == "张三"

    def test_extract_json_array_with_wrapper(self):
        """数组前后有文字时仍能提取。"""
        text = 'Characters: [{"name": "A"}] done'
        result = extract_json_array(text)
        assert result is not None
        assert len(result) == 1

    def test_extract_json_array_garbage(self):
        """无数组时返回 None。"""
        assert extract_json_array("no array here") is None

    def test_extract_json_array_none_input(self):
        """None 输入安全返回 None。"""
        assert extract_json_array(None) is None

    def test_extract_json_array_empty_array(self):
        """空数组返回空列表。"""
        result = extract_json_array("[]")
        assert result == []


# ===================================================================
# TestDirectorAgent
# ===================================================================
class TestDirectorAgent:
    """DirectorAgent 分析任务、成本估算。"""

    def test_analyze_task_basic(self, minimal_config, sample_text):
        """正常文本应返回正确的字符数和预计段数。"""
        state = AgentState(
            full_text=sample_text, config=minimal_config, budget_mode=False
        )
        agent = DirectorAgent(minimal_config)
        result = agent.analyze_task(state)

        assert result["char_count"] == len(sample_text)
        assert result["segment_count"] >= 1
        assert isinstance(result["analysis_needed"], bool)
        assert isinstance(result["video_enabled"], bool)

    def test_analyze_task_empty_text(self, minimal_config):
        """空文本应返回 char_count=0, segment_count=1（至少1段）。"""
        state = AgentState(full_text="", config=minimal_config, budget_mode=False)
        agent = DirectorAgent(minimal_config)
        result = agent.analyze_task(state)

        assert result["char_count"] == 0
        assert result["segment_count"] == 1  # max(1, 0//100 + 1) = 1

    def test_analyze_task_budget_mode_disables_analysis(self, minimal_config, long_text):
        """budget_mode=True 时 analysis_needed 应为 False，即使文本>500字。"""
        state = AgentState(
            full_text=long_text, config=minimal_config, budget_mode=True
        )
        agent = DirectorAgent(minimal_config)
        result = agent.analyze_task(state)

        assert result["analysis_needed"] is False

    def test_analyze_task_long_text_enables_analysis(self, minimal_config, long_text):
        """非 budget 模式且文本>500字，analysis_needed=True。"""
        state = AgentState(
            full_text=long_text, config=minimal_config, budget_mode=False
        )
        agent = DirectorAgent(minimal_config)
        result = agent.analyze_task(state)

        assert result["analysis_needed"] is True

    def test_analyze_task_video_enabled_when_configured(self, minimal_config, sample_text):
        """配置 videogen.backend 时 video_enabled=True。"""
        minimal_config["videogen"] = {"backend": "kling"}
        state = AgentState(
            full_text=sample_text, config=minimal_config, budget_mode=False
        )
        agent = DirectorAgent(minimal_config)
        result = agent.analyze_task(state)

        assert result["video_enabled"] is True

    def test_analyze_task_video_disabled_by_default(self, minimal_config, sample_text):
        """无 videogen 配置时 video_enabled=False。"""
        state = AgentState(
            full_text=sample_text, config=minimal_config, budget_mode=False
        )
        agent = DirectorAgent(minimal_config)
        result = agent.analyze_task(state)

        assert result["video_enabled"] is False

    def test_analyze_task_missing_segmenter_config(self, sample_text):
        """config 缺少 segmenter 字段时使用默认 max_chars=100。"""
        config = {}
        state = AgentState(full_text=sample_text, config=config, budget_mode=False)
        agent = DirectorAgent(config)
        result = agent.analyze_task(state)

        # max_chars 默认 100
        expected = max(1, (len(sample_text) // 100) + 1)
        assert result["segment_count"] == expected

    def test_estimate_cost_budget_mode(self, minimal_config):
        """budget_mode 成本公式：n * 0.0007。"""
        agent = DirectorAgent(minimal_config)
        analysis = {"segment_count": 10}
        cost = agent.estimate_cost(analysis, budget_mode=True)
        assert cost == pytest.approx(10 * 0.0007)

    def test_estimate_cost_normal_mode(self, minimal_config):
        """非 budget 模式成本公式：n*0.0001 + n*0.01*1.5。"""
        agent = DirectorAgent(minimal_config)
        analysis = {"segment_count": 10}
        cost = agent.estimate_cost(analysis, budget_mode=False)
        expected = 10 * 0.0001 + 10 * 0.01 * 1.5
        assert cost == pytest.approx(expected)

    def test_director_node_returns_decisions(self, base_state):
        """director_node 应返回包含 decisions 列表的 dict。"""
        result = director_node(base_state)

        assert "decisions" in result
        assert len(result["decisions"]) == 2  # analyze + plan
        assert all(d["agent"] == "Director" for d in result["decisions"])

    def test_director_node_returns_pipeline_plan(self, base_state):
        """director_node 应返回 pipeline_plan。"""
        result = director_node(base_state)

        plan = result["pipeline_plan"]
        assert "char_count" in plan
        assert "segment_count" in plan
        assert "estimated_cost" in plan

    def test_director_node_missing_full_text_raises(self, base_state):
        """state 缺少 full_text 时应抛出 KeyError。"""
        del base_state["full_text"]
        with pytest.raises(KeyError):
            director_node(base_state)


# ===================================================================
# TestContentAnalyzer
# ===================================================================
class TestContentAnalyzer:
    """ContentAnalyzerAgent 规则分类、角色提取、LLM 回退。"""

    def test_classify_genre_wuxia(self, minimal_config):
        """含江湖/剑气等关键词应分类为武侠。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=True)
        result = agent.classify_genre("江湖之上剑气纵横，侠客行走天涯。")
        assert result["genre"] == "武侠"
        assert result["era"] == "古代"
        assert result["confidence"] == 0.8

    def test_classify_genre_xuanhuan(self, minimal_config):
        """含修炼/灵气等关键词应分类为玄幻。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=True)
        result = agent.classify_genre("修炼者灵气充沛，宗门弟子渡劫飞升。")
        assert result["genre"] == "玄幻"
        assert result["era"] == "架空"

    def test_classify_genre_urban(self, minimal_config):
        """含公司/手机等关键词应分类为都市。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=True)
        result = agent.classify_genre("他在公司加班后，拿起手机叫了外卖。")
        assert result["genre"] == "都市"

    def test_classify_genre_scifi(self, minimal_config):
        """含星际/AI等关键词应分类为科幻。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=True)
        result = agent.classify_genre("星际飞船穿越宇宙，AI机器人在赛博空间中运作。")
        assert result["genre"] == "科幻"

    def test_classify_genre_historical(self, minimal_config):
        """含皇上/太后等关键词应分类为历史。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=True)
        result = agent.classify_genre("皇上驾临，太后命丫鬟准备茶点。")
        assert result["genre"] == "历史"
        assert result["era"] == "古代"

    def test_classify_genre_no_match(self, minimal_config):
        """无匹配关键词时应返回 '其他'。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=True)
        result = agent.classify_genre("今天天气不错，出去走走。")
        assert result["genre"] == "其他"
        assert result["era"] == "现代"
        assert result["confidence"] == 0.5

    def test_classify_genre_empty_text(self, minimal_config):
        """空文本应返回默认分类。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=True)
        result = agent.classify_genre("")
        assert result["genre"] == "其他"

    def test_classify_genre_llm_fallback_on_garbage_json(self, minimal_config):
        """LLM 返回垃圾 JSON 时应回退到规则分类。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=False)
        mock_llm = MagicMock()
        mock_llm.chat.return_value = MagicMock(content="not valid json at all")
        agent._llm = mock_llm

        result = agent.classify_genre("修炼者灵气充沛。")
        assert result["genre"] == "玄幻"  # 规则回退

    def test_classify_genre_llm_exception_fallback(self, minimal_config):
        """LLM 抛异常时应回退到规则分类。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=False)
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("API timeout")
        agent._llm = mock_llm

        result = agent.classify_genre("江湖侠客行。")
        assert result["genre"] == "武侠"

    def test_classify_genre_llm_missing_genre_key(self, minimal_config):
        """LLM 返回的 JSON 缺少 genre 字段时应回退。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=False)
        mock_llm = MagicMock()
        mock_llm.chat.return_value = MagicMock(content='{"era": "古代"}')
        agent._llm = mock_llm

        result = agent.classify_genre("江湖侠客行。")
        assert result["genre"] == "武侠"

    def test_extract_characters_by_rules(self, minimal_config):
        """规则模式应通过对话标记（说道/笑道等）提取角色名。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=True)
        text = "张三说道：你好。李四笑道：很好。王五问道：真的吗？"
        chars = agent.extract_characters(text)
        names = [c["name"] for c in chars]
        assert "张三" in names
        assert "李四" in names
        assert "王五" in names

    def test_extract_characters_no_dialogue(self, minimal_config):
        """无对话标记时返回空列表。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=True)
        chars = agent.extract_characters("今天天气很好，适合出门散步。")
        assert chars == []

    def test_extract_characters_max_five(self, minimal_config):
        """规则模式最多返回 5 个角色。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=True)
        text = "".join(f"角色{chr(0x4e00 + i)}说道：你好。" for i in range(10))
        chars = agent.extract_characters(text)
        assert len(chars) <= 5

    def test_extract_characters_dedup(self, minimal_config):
        """同一角色多次出现应去重。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=True)
        text = "张三说道：你好。张三笑道：再见。李四问道：什么？"
        chars = agent.extract_characters(text)
        names = [c["name"] for c in chars]
        assert names.count("张三") == 1

    def test_extract_characters_llm_exception_fallback(self, minimal_config):
        """LLM 异常时回退到规则提取。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=False)
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = ConnectionError("network down")
        agent._llm = mock_llm

        chars = agent.extract_characters("张三说道：你好。")
        assert len(chars) >= 1
        assert chars[0]["name"] == "张三"

    def test_extract_characters_llm_garbage_json(self, minimal_config):
        """LLM 返回非数组 JSON 时回退。"""
        agent = ContentAnalyzerAgent(minimal_config, budget_mode=False)
        mock_llm = MagicMock()
        mock_llm.chat.return_value = MagicMock(content="I cannot help with that")
        agent._llm = mock_llm

        chars = agent.extract_characters("张三说道：你好。")
        assert isinstance(chars, list)

    def test_suggest_style_known_combos(self, minimal_config):
        """已知的 (genre, era) 组合应返回对应风格。"""
        agent = ContentAnalyzerAgent(minimal_config)
        assert agent.suggest_style("武侠", "古代") == "chinese_ink"
        assert agent.suggest_style("玄幻", "架空") == "anime"
        assert agent.suggest_style("都市", "现代") == "realistic"
        assert agent.suggest_style("科幻", "未来") == "cyberpunk"
        assert agent.suggest_style("言情", "现代") == "watercolor"

    def test_suggest_style_unknown_combo(self, minimal_config):
        """未知组合应返回默认 'anime'。"""
        agent = ContentAnalyzerAgent(minimal_config)
        assert agent.suggest_style("未知类型", "未知时代") == "anime"

    @patch("src.agents.content_analyzer.SegmentTool")
    def test_content_analyzer_node_returns_correct_keys(self, mock_seg_cls, base_state):
        """content_analyzer_node 应返回 segments/genre/era/characters/style/decisions。"""
        mock_seg_instance = MagicMock()
        mock_seg_instance.run.return_value = [{"text": "段1", "index": 0}]
        mock_seg_cls.return_value = mock_seg_instance

        base_state["budget_mode"] = True
        base_state["full_text"] = "江湖侠客行，剑气纵横。"

        result = content_analyzer_node(base_state)

        assert "segments" in result
        assert "genre" in result
        assert "era" in result
        assert "characters" in result
        assert "suggested_style" in result
        assert "decisions" in result
        assert len(result["decisions"]) == 4  # segment + classify + characters + style

    @patch("src.agents.content_analyzer.SegmentTool")
    def test_content_analyzer_node_empty_text(self, mock_seg_cls, base_state):
        """空文本分段返回空列表，但节点不应崩溃。"""
        mock_seg_instance = MagicMock()
        mock_seg_instance.run.return_value = []
        mock_seg_cls.return_value = mock_seg_instance

        base_state["budget_mode"] = True
        base_state["full_text"] = ""

        result = content_analyzer_node(base_state)

        assert result["segments"] == []
        assert result["genre"] == "其他"


# ===================================================================
# TestArtDirector
# ===================================================================
class TestArtDirector:
    """ArtDirectorAgent 图片生成与质量控制。"""

    @patch("src.agents.art_director.ImageGenTool")
    @patch("src.agents.art_director.PromptGenTool")
    def test_generate_image_no_quality_check(self, mock_prompt_cls, mock_img_cls,
                                              minimal_config, tmp_path):
        """质量检查关闭时应直接返回，不调用 vision LLM。"""
        mock_prompt = MagicMock()
        mock_prompt.run.return_value = "a painting of a warrior"
        mock_prompt_cls.return_value = mock_prompt

        mock_img = MagicMock()
        mock_img_cls.return_value = mock_img

        agent = ArtDirectorAgent(minimal_config, budget_mode=True)
        agent.prompt_gen = mock_prompt
        agent.image_gen = mock_img

        path, score, retries, decisions = agent.generate_image(
            "测试文本", 0, tmp_path
        )

        assert score == -1.0
        assert retries == 0
        assert len(decisions) == 1
        assert decisions[0]["agent"] == "ArtDirector"
        mock_img.run.assert_called_once()

    @patch("src.agents.art_director.ImageGenTool")
    @patch("src.agents.art_director.PromptGenTool")
    def test_generate_image_quality_pass_first_try(self, mock_prompt_cls, mock_img_cls,
                                                     minimal_config, tmp_path):
        """质量评估通过时不应重试。"""
        config = dict(minimal_config)
        config["agent"] = {"quality_check": {"enabled": True, "threshold": 6.0, "max_retries": 3}}

        mock_prompt = MagicMock()
        mock_prompt.run.return_value = "a painting"
        mock_img = MagicMock()

        agent = ArtDirectorAgent(config, budget_mode=False)
        agent.prompt_gen = mock_prompt
        agent.image_gen = mock_img
        # Mock quality_tool.run to return high score
        agent.quality_tool.run = MagicMock(return_value=QualityEvaluation(
            score=8.0, feedback="good", passed=True,
            composition=2, clarity=2, text_match=2, color=2, consistency=0,
        ))

        path, score, retries, decisions = agent.generate_image(
            "测试", 0, tmp_path
        )

        assert score == 8.0
        assert retries == 0
        agent.quality_tool.run.assert_called_once()

    @patch("src.agents.art_director.ImageGenTool")
    @patch("src.agents.art_director.PromptGenTool")
    def test_generate_image_quality_retry_then_pass(self, mock_prompt_cls, mock_img_cls,
                                                      minimal_config, tmp_path):
        """评分不足时重试，第二次通过。"""
        config = dict(minimal_config)
        config["agent"] = {"quality_check": {"enabled": True, "threshold": 6.0, "max_retries": 3}}

        mock_prompt = MagicMock()
        mock_prompt.run.return_value = "prompt"
        mock_img = MagicMock()

        agent = ArtDirectorAgent(config, budget_mode=False)
        agent.prompt_gen = mock_prompt
        agent.image_gen = mock_img
        # 第一次低分，第二次高分
        agent.quality_tool.run = MagicMock(side_effect=[
            QualityEvaluation(
                score=3.0, feedback="bad", passed=False,
                composition=1, clarity=1, text_match=1, color=0, consistency=0,
            ),
            QualityEvaluation(
                score=7.0, feedback="good", passed=True,
                composition=2, clarity=2, text_match=2, color=1, consistency=0,
            ),
        ])

        path, score, retries, decisions = agent.generate_image("txt", 0, tmp_path)

        assert score == 7.0
        assert retries == 1
        assert agent.quality_tool.run.call_count == 2

    @patch("src.agents.art_director.ImageGenTool")
    @patch("src.agents.art_director.PromptGenTool")
    def test_generate_image_max_retries_exhausted(self, mock_prompt_cls, mock_img_cls,
                                                    minimal_config, tmp_path):
        """达到最大重试次数后应返回最佳结果。"""
        config = dict(minimal_config)
        config["agent"] = {"quality_check": {"enabled": True, "threshold": 8.0, "max_retries": 2}}

        mock_prompt = MagicMock()
        mock_prompt.run.return_value = "prompt"
        mock_img = MagicMock()

        agent = ArtDirectorAgent(config, budget_mode=False)
        agent.prompt_gen = mock_prompt
        agent.image_gen = mock_img
        # 始终低分
        agent.quality_tool.run = MagicMock(side_effect=[
            QualityEvaluation(
                score=4.0, feedback="bad", passed=False,
                composition=1, clarity=1, text_match=1, color=1, consistency=0,
            ),
            QualityEvaluation(
                score=5.0, feedback="better", passed=False,
                composition=1, clarity=1, text_match=2, color=1, consistency=0,
            ),
            QualityEvaluation(
                score=3.0, feedback="worst", passed=False,
                composition=0, clarity=1, text_match=1, color=1, consistency=0,
            ),
        ])

        path, score, retries, decisions = agent.generate_image("txt", 0, tmp_path)

        assert score == 5.0  # best_score
        assert retries == 2

    def test_evaluate_quality_no_vision_llm(self, minimal_config, tmp_path):
        """vision LLM 不可用时返回默认 5.0 分。"""
        from src.tools.evaluate_quality_tool import EvaluateQualityTool

        tool = EvaluateQualityTool(minimal_config)
        tool._vision_llm = None
        # Force _get_vision_llm to return None
        tool._get_vision_llm = MagicMock(return_value=None)

        # Create dummy image
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        evaluation = tool.run(img_path, "text", "prompt")
        assert evaluation["score"] == 5.0
        assert "不可用" in evaluation["feedback"]

    @patch("src.agents.art_director.ImageGenTool")
    @patch("src.agents.art_director.PromptGenTool")
    def test_art_director_node_returns_correct_keys(self, mock_prompt_cls, mock_img_cls,
                                                      base_state, tmp_path):
        """art_director_node 应返回 images/quality_scores/retry_counts/decisions。"""
        base_state["segments"] = [{"text": "段1", "index": 0}]
        base_state["workspace"] = str(tmp_path)

        with patch.object(ArtDirectorAgent, "generate_image",
                          return_value=(tmp_path / "0.png", -1.0, 0, [
                              make_decision("ArtDirector", "test", "d", "r")
                          ])):
            result = art_director_node(base_state)

        assert "images" in result
        assert "quality_scores" in result
        assert "retry_counts" in result
        assert "decisions" in result
        assert len(result["images"]) == 1

    @patch("src.agents.art_director.ImageGenTool")
    @patch("src.agents.art_director.PromptGenTool")
    def test_art_director_node_empty_segments(self, mock_prompt_cls, mock_img_cls,
                                               base_state, tmp_path):
        """空 segments 列表时应返回空结果，不崩溃。"""
        base_state["segments"] = []
        base_state["workspace"] = str(tmp_path)

        result = art_director_node(base_state)

        assert result["images"] == []
        assert result["quality_scores"] == []
        # 有 start + summary decisions
        assert len(result["decisions"]) == 2


# ===================================================================
# TestVoiceDirector
# ===================================================================
class TestVoiceDirector:
    """VoiceDirectorAgent 情感分析与 TTS 参数。"""

    def test_analyze_emotion_tense(self, minimal_config):
        """含危险/杀等关键词应返回紧张。"""
        agent = VoiceDirectorAgent(minimal_config, budget_mode=True)
        assert agent.analyze_emotion("危险逼近，战斗一触即发！") == "紧张"

    def test_analyze_emotion_sad(self, minimal_config):
        """含哭/泪等关键词应返回悲伤。"""
        agent = VoiceDirectorAgent(minimal_config, budget_mode=True)
        assert agent.analyze_emotion("她流下了悲伤的泪水。") == "悲伤"

    def test_analyze_emotion_happy(self, minimal_config):
        """含笑/高兴等关键词应返回欢快。"""
        agent = VoiceDirectorAgent(minimal_config, budget_mode=True)
        assert agent.analyze_emotion("大家都很高兴，笑得合不拢嘴。") == "欢快"

    def test_analyze_emotion_excited(self, minimal_config):
        """含怒/激动等关键词应返回激动。"""
        agent = VoiceDirectorAgent(minimal_config, budget_mode=True)
        assert agent.analyze_emotion("他愤怒地吼道，激动不已！") == "激动"

    def test_analyze_emotion_calm_default(self, minimal_config):
        """无匹配关键词时返回平静。"""
        agent = VoiceDirectorAgent(minimal_config, budget_mode=True)
        assert agent.analyze_emotion("今天天气不错。") == "平静"

    def test_analyze_emotion_empty_text(self, minimal_config):
        """空文本返回平静。"""
        agent = VoiceDirectorAgent(minimal_config, budget_mode=True)
        assert agent.analyze_emotion("") == "平静"

    def test_analyze_emotion_llm_invalid_response(self, minimal_config):
        """LLM 返回无效情感时回退到规则。"""
        agent = VoiceDirectorAgent(minimal_config, budget_mode=False)
        mock_llm = MagicMock()
        mock_llm.chat.return_value = MagicMock(content="I'm not sure")
        agent._llm = mock_llm

        result = agent.analyze_emotion("危险逼近！")
        assert result == "紧张"  # 规则回退

    def test_analyze_emotion_llm_exception(self, minimal_config):
        """LLM 异常时回退到规则。"""
        agent = VoiceDirectorAgent(minimal_config, budget_mode=False)
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = TimeoutError("API timeout")
        agent._llm = mock_llm

        result = agent.analyze_emotion("她流下泪水。")
        assert result == "悲伤"

    def test_get_tts_params_known_emotions(self, minimal_config):
        """已知情感应返回对应 rate/volume。"""
        agent = VoiceDirectorAgent(minimal_config)
        for emotion, expected in EMOTION_TTS_PARAMS.items():
            params = agent.get_tts_params(emotion)
            assert params["rate"] == expected["rate"]
            assert params["volume"] == expected["volume"]

    def test_get_tts_params_unknown_emotion(self, minimal_config):
        """未知情感应返回平静参数。"""
        agent = VoiceDirectorAgent(minimal_config)
        params = agent.get_tts_params("未知情感")
        assert params == EMOTION_TTS_PARAMS["平静"]

    @patch("src.agents.voice_director.TTSTool")
    def test_voice_director_node_returns_correct_keys(self, mock_tts_cls, base_state, tmp_path):
        """voice_director_node 应返回 audio_files/srt_files/decisions。"""
        mock_tts = MagicMock()
        mock_tts_cls.return_value = mock_tts

        base_state["segments"] = [{"text": "测试段落", "index": 0}]
        base_state["workspace"] = str(tmp_path)
        base_state["budget_mode"] = True

        result = voice_director_node(base_state)

        assert "audio_files" in result
        assert "srt_files" in result
        assert "decisions" in result
        assert len(result["audio_files"]) == 1
        assert len(result["srt_files"]) == 1

    @patch("src.agents.voice_director.TTSTool")
    def test_voice_director_node_empty_segments(self, mock_tts_cls, base_state, tmp_path):
        """空 segments 时返回空列表。"""
        mock_tts_cls.return_value = MagicMock()
        base_state["segments"] = []
        base_state["workspace"] = str(tmp_path)

        result = voice_director_node(base_state)

        assert result["audio_files"] == []
        assert result["srt_files"] == []
        assert result["decisions"] == []


# ===================================================================
# TestEditorAgent
# ===================================================================
class TestEditorAgent:
    """EditorAgent 视频合成。"""

    @patch("src.agents.editor.VideoAssembleTool")
    def test_editor_node_returns_correct_keys(self, mock_vid_cls, base_state, tmp_path):
        """editor_node 应返回 final_video 和 decisions。"""
        mock_vid = MagicMock()
        mock_vid_cls.return_value = mock_vid

        base_state["workspace"] = str(tmp_path)
        base_state["images"] = [str(tmp_path / "0.png")]
        base_state["audio_files"] = [str(tmp_path / "0.mp3")]
        base_state["srt_files"] = [str(tmp_path / "0.srt")]
        base_state["input_file"] = str(tmp_path / "novel.txt")

        result = editor_node(base_state)

        assert "final_video" in result
        assert "decisions" in result
        assert len(result["decisions"]) == 2  # start + complete
        assert result["decisions"][0]["agent"] == "Editor"

    @patch("src.agents.editor.VideoAssembleTool")
    def test_editor_node_missing_images_raises(self, mock_vid_cls, base_state, tmp_path):
        """state 缺少 images 字段时应抛出 KeyError。"""
        base_state["workspace"] = str(tmp_path)
        del base_state["images"]
        base_state["audio_files"] = []
        base_state["srt_files"] = []

        with pytest.raises(KeyError):
            editor_node(base_state)

    @patch("src.agents.editor.VideoAssembleTool")
    def test_editor_node_with_video_clips(self, mock_vid_cls, base_state, tmp_path):
        """有 video_clips 时应传递给 VideoAssembleTool。"""
        mock_vid = MagicMock()
        mock_vid_cls.return_value = mock_vid

        base_state["workspace"] = str(tmp_path)
        base_state["images"] = [str(tmp_path / "0.png")]
        base_state["audio_files"] = [str(tmp_path / "0.mp3")]
        base_state["srt_files"] = [str(tmp_path / "0.srt")]
        base_state["video_clips"] = [str(tmp_path / "0.mp4")]
        base_state["input_file"] = str(tmp_path / "novel.txt")

        editor_node(base_state)

        call_kwargs = mock_vid.run.call_args
        assert call_kwargs is not None

    @patch("src.agents.editor.VideoAssembleTool")
    def test_editor_node_video_tool_exception(self, mock_vid_cls, base_state, tmp_path):
        """VideoAssembleTool.run 抛异常时应传播。"""
        mock_vid = MagicMock()
        mock_vid.run.side_effect = RuntimeError("FFmpeg failed")
        mock_vid_cls.return_value = mock_vid

        base_state["workspace"] = str(tmp_path)
        base_state["images"] = [str(tmp_path / "0.png")]
        base_state["audio_files"] = [str(tmp_path / "0.mp3")]
        base_state["srt_files"] = [str(tmp_path / "0.srt")]
        base_state["input_file"] = str(tmp_path / "novel.txt")

        # EditorAgent 初始化时已创建了 video_tool，需要 patch 实例
        with pytest.raises(RuntimeError, match="FFmpeg failed"):
            editor_node(base_state)


# ===================================================================
# TestTools
# ===================================================================
class TestTools:
    """各 Tool 封装的 config 处理与接口正确性。"""

    def test_segment_tool_default_config(self):
        """SegmentTool 无 segmenter 配置时使用默认值。"""
        tool = SegmentTool({})
        # 内部会用默认 {"method": "simple", "max_chars": 100, "min_chars": 20}
        result = tool.run("这是一段测试文本。很短的段落。")
        assert isinstance(result, list)
        # 每个元素应有 text 和 index
        if result:
            assert "text" in result[0]
            assert "index" in result[0]

    def test_segment_tool_empty_text(self):
        """空文本分段应返回空列表。"""
        tool = SegmentTool({"segmenter": {"method": "simple", "max_chars": 100, "min_chars": 20}})
        result = tool.run("")
        assert result == []

    def test_segment_tool_with_config(self):
        """SegmentTool 应使用配置中的 max_chars。"""
        config = {"segmenter": {"method": "simple", "max_chars": 50, "min_chars": 10}}
        tool = SegmentTool(config)
        text = "这是第一句话。这是第二句话。这是第三句话。这是第四句话。这是第五句话。" * 3
        result = tool.run(text)
        assert len(result) >= 2  # 应被分成多段

    def test_prompt_gen_tool_init(self, minimal_config):
        """PromptGenTool 初始化不应立即加载模块。"""
        tool = PromptGenTool(minimal_config)
        assert tool._gen is None  # 懒加载

    def test_image_gen_tool_missing_imagegen_config(self):
        """ImageGenTool 缺少 imagegen 配置时 _get_gen 应抛异常。"""
        tool = ImageGenTool({})
        with pytest.raises(KeyError):
            tool._get_gen()

    def test_tts_tool_missing_tts_config(self):
        """TTSTool 缺少 tts 配置时 _get_engine 应抛异常。"""
        tool = TTSTool({})
        with pytest.raises(KeyError):
            tool._get_engine()

    def test_video_assemble_tool_missing_video_config(self):
        """VideoAssembleTool 缺少 video 配置时 run 应抛异常。"""
        tool = VideoAssembleTool({})
        with pytest.raises(KeyError):
            tool.run([], [], Path("out.mp4"), Path("ws"))


# ===================================================================
# TestLangGraphIntegration
# ===================================================================
class TestLangGraphIntegration:
    """LangGraph 多节点 state 累积、decisions 不丢失、错误传播。"""

    def test_decisions_accumulate_across_nodes(self):
        """多个节点返回的 decisions 应通过 operator.add 正确合并。"""
        d1 = [make_decision("A", "1", "d1", "r1")]
        d2 = [make_decision("B", "2", "d2", "r2")]
        d3 = [make_decision("C", "3", "d3", "r3")]

        # 模拟 LangGraph 的 operator.add reducer
        accumulated = operator.add(operator.add(d1, d2), d3)
        assert len(accumulated) == 3
        assert accumulated[0]["agent"] == "A"
        assert accumulated[1]["agent"] == "B"
        assert accumulated[2]["agent"] == "C"

    def test_errors_accumulate_across_nodes(self):
        """多个节点返回的 errors 应通过 operator.add 正确合并。"""
        e1 = [{"error": "err1", "node": "A"}]
        e2 = [{"error": "err2", "node": "B"}]
        accumulated = operator.add(e1, e2)
        assert len(accumulated) == 2

    def test_state_fields_independent(self):
        """不同节点写入不同 state 字段时不应互相覆盖。"""
        # 模拟 director_node 输出
        director_out = {
            "pipeline_plan": {"char_count": 100},
            "decisions": [make_decision("Director", "1", "d", "r")],
        }
        # 模拟 content_analyzer_node 输出
        analyzer_out = {
            "segments": [{"text": "段1", "index": 0}],
            "genre": "武侠",
            "decisions": [make_decision("Analyzer", "2", "d", "r")],
        }

        # 合并（模拟 LangGraph 行为）
        merged = {}
        merged.update(director_out)
        # 对 decisions 用 add
        prev_decisions = merged.get("decisions", [])
        merged.update(analyzer_out)
        merged["decisions"] = prev_decisions + analyzer_out["decisions"]

        assert merged["pipeline_plan"]["char_count"] == 100
        assert merged["genre"] == "武侠"
        assert len(merged["decisions"]) == 2

    @patch("src.agents.content_analyzer.SegmentTool")
    def test_director_then_analyzer_state_flow(self, mock_seg_cls, base_state):
        """Director -> ContentAnalyzer 状态传递：pipeline_plan 应保留。"""
        # Director
        director_result = director_node(base_state)
        assert "pipeline_plan" in director_result

        # 模拟 LangGraph 将 director 输出合并到 state
        merged_state = {**base_state, **director_result}
        # decisions 应累积
        merged_state["decisions"] = base_state["decisions"] + director_result["decisions"]

        # ContentAnalyzer
        mock_seg = MagicMock()
        mock_seg.run.return_value = [{"text": "段1", "index": 0}]
        mock_seg_cls.return_value = mock_seg
        merged_state["budget_mode"] = True

        analyzer_result = content_analyzer_node(merged_state)

        # 验证两个节点的 decisions 都存在
        all_decisions = merged_state["decisions"] + analyzer_result["decisions"]
        agents_seen = {d["agent"] for d in all_decisions}
        assert "Director" in agents_seen
        assert "ContentAnalyzer" in agents_seen

    def test_empty_decisions_merge(self):
        """空 decisions 列表合并不应出错。"""
        result = operator.add([], [make_decision("A", "1", "d", "r")])
        assert len(result) == 1

    @patch("src.agents.art_director.ImageGenTool")
    @patch("src.agents.art_director.PromptGenTool")
    def test_art_director_node_propagates_exception(self, mock_prompt_cls, mock_img_cls,
                                                      base_state, tmp_path):
        """图片生成工具异常应向上传播，不被静默吞掉。"""
        mock_prompt = MagicMock()
        mock_prompt.run.side_effect = RuntimeError("prompt gen failed")
        mock_prompt_cls.return_value = mock_prompt

        base_state["segments"] = [{"text": "段1", "index": 0}]
        base_state["workspace"] = str(tmp_path)

        with pytest.raises(RuntimeError, match="prompt gen failed"):
            art_director_node(base_state)


# ===================================================================
# TestAgentPipeline
# ===================================================================
class TestAgentPipeline:
    """AgentPipeline 初始化、state 序列化、resume。"""

    @patch("src.agent_pipeline.load_config")
    def test_init_file_not_found(self, mock_load_config):
        """输入文件不存在时应抛出 FileNotFoundError。"""
        mock_load_config.return_value = {
            "segmenter": {}, "promptgen": {}, "imagegen": {},
            "tts": {}, "video": {"resolution": [1080, 1920]},
            "project": {},
        }
        with pytest.raises(FileNotFoundError, match="输入文件不存在"):
            from src.agent_pipeline import AgentPipeline
            AgentPipeline(input_file=Path("/nonexistent/file.txt"))

    @patch("src.agent_pipeline.load_config")
    def test_init_creates_workspace(self, mock_load_config, tmp_path):
        """初始化应创建工作目录及子目录。"""
        input_file = tmp_path / "novel.txt"
        input_file.write_text("测试内容", encoding="utf-8")

        mock_load_config.return_value = {
            "segmenter": {}, "promptgen": {}, "imagegen": {},
            "tts": {}, "video": {"resolution": [1080, 1920]},
            "project": {"default_workspace": str(tmp_path / "ws"), "default_output": str(tmp_path / "out")},
        }

        from src.agent_pipeline import AgentPipeline
        AgentPipeline(input_file=input_file)

        ws = tmp_path / "ws" / "novel"
        assert ws.exists()
        for sub in ["segments", "images", "audio", "subtitles", "videos"]:
            assert (ws / sub).exists()

    @patch("src.agent_pipeline.load_config")
    def test_init_state_correct_fields(self, mock_load_config, tmp_path):
        """_init_state 应正确填充所有字段。"""
        input_file = tmp_path / "novel.txt"
        input_file.write_text("测试内容", encoding="utf-8")

        mock_load_config.return_value = {
            "segmenter": {}, "promptgen": {}, "imagegen": {},
            "tts": {}, "video": {"resolution": [1080, 1920]},
            "project": {"default_workspace": str(tmp_path / "ws"), "default_output": str(tmp_path / "out")},
        }

        from src.agent_pipeline import AgentPipeline
        pipe = AgentPipeline(input_file=input_file, budget_mode=True)
        state = pipe._init_state()

        assert state["full_text"] == "测试内容"
        assert state["budget_mode"] is True
        assert state["mode"] == "agent"
        assert state["decisions"] == []
        assert state["errors"] == []
        assert state["segments"] == []

    @patch("src.agent_pipeline.load_config")
    def test_save_and_load_state(self, mock_load_config, tmp_path):
        """save_state 后 load_state 应恢复状态（config 用当前配置替换）。"""
        input_file = tmp_path / "novel.txt"
        input_file.write_text("内容", encoding="utf-8")

        cfg = {
            "segmenter": {}, "promptgen": {}, "imagegen": {},
            "tts": {}, "video": {"resolution": [1080, 1920]},
            "project": {"default_workspace": str(tmp_path / "ws"), "default_output": str(tmp_path / "out")},
        }
        mock_load_config.return_value = cfg

        from src.agent_pipeline import AgentPipeline
        pipe = AgentPipeline(input_file=input_file)

        state = pipe._init_state()
        state["genre"] = "武侠"
        state["segments"] = [{"text": "段1", "index": 0}]

        pipe._save_state(dict(state))
        loaded = pipe._load_state()

        assert loaded is not None
        assert loaded["genre"] == "武侠"
        assert len(loaded["segments"]) == 1
        # config 应为当前配置
        assert loaded["config"] is cfg

    @patch("src.agent_pipeline.load_config")
    def test_load_state_missing_file(self, mock_load_config, tmp_path):
        """state 文件不存在时 _load_state 返回 None。"""
        input_file = tmp_path / "novel.txt"
        input_file.write_text("内容", encoding="utf-8")

        mock_load_config.return_value = {
            "segmenter": {}, "promptgen": {}, "imagegen": {},
            "tts": {}, "video": {"resolution": [1080, 1920]},
            "project": {"default_workspace": str(tmp_path / "ws"), "default_output": str(tmp_path / "out")},
        }

        from src.agent_pipeline import AgentPipeline
        pipe = AgentPipeline(input_file=input_file)

        assert pipe._load_state() is None

    @patch("src.agent_pipeline.load_config")
    def test_load_state_corrupt_json(self, mock_load_config, tmp_path):
        """state 文件为损坏 JSON 时返回 None。"""
        input_file = tmp_path / "novel.txt"
        input_file.write_text("内容", encoding="utf-8")

        mock_load_config.return_value = {
            "segmenter": {}, "promptgen": {}, "imagegen": {},
            "tts": {}, "video": {"resolution": [1080, 1920]},
            "project": {"default_workspace": str(tmp_path / "ws"), "default_output": str(tmp_path / "out")},
        }

        from src.agent_pipeline import AgentPipeline
        pipe = AgentPipeline(input_file=input_file)

        # Write corrupt JSON
        pipe.state_file.write_text("{broken json", encoding="utf-8")
        assert pipe._load_state() is None

    @patch("src.agent_pipeline.load_config")
    def test_quality_threshold_override(self, mock_load_config, tmp_path):
        """quality_threshold 参数应覆盖配置。"""
        input_file = tmp_path / "novel.txt"
        input_file.write_text("内容", encoding="utf-8")

        mock_load_config.return_value = {
            "segmenter": {}, "promptgen": {}, "imagegen": {},
            "tts": {}, "video": {"resolution": [1080, 1920]},
            "project": {"default_workspace": str(tmp_path / "ws"), "default_output": str(tmp_path / "out")},
        }

        from src.agent_pipeline import AgentPipeline
        pipe = AgentPipeline(input_file=input_file, quality_threshold=7.5)

        assert pipe.cfg["agent"]["quality_check"]["threshold"] == 7.5


# ===================================================================
# TestCLI
# ===================================================================
class TestCLI:
    """CLI --mode 参数与 --budget-mode。"""

    def test_cli_group_exists(self):
        """CLI group 应为 click.Group。"""
        from main import cli
        import click
        assert isinstance(cli, click.Group)

    def test_cli_run_command_exists(self):
        """run 命令应注册在 CLI group 中。"""
        from main import cli
        assert "run" in cli.commands

    def test_cli_run_has_mode_option(self):
        """run 命令应有 --mode 选项，可选 classic/agent。"""
        from main import cli
        run_cmd = cli.commands["run"]
        mode_param = None
        for param in run_cmd.params:
            if param.name == "mode":
                mode_param = param
                break
        assert mode_param is not None
        assert mode_param.type.choices == ["classic", "agent"]
        assert mode_param.default == "classic"

    def test_cli_run_has_budget_mode_option(self):
        """run 命令应有 --budget-mode flag。"""
        from main import cli
        run_cmd = cli.commands["run"]
        budget_param = None
        for param in run_cmd.params:
            if param.name == "budget_mode":
                budget_param = param
                break
        assert budget_param is not None
        assert budget_param.is_flag is True

    def test_cli_run_has_quality_threshold_option(self):
        """run 命令应有 --quality-threshold 选项。"""
        from main import cli
        run_cmd = cli.commands["run"]
        qt_param = None
        for param in run_cmd.params:
            if param.name == "quality_threshold":
                qt_param = param
                break
        assert qt_param is not None
        assert qt_param.default is None

    def test_cli_segment_command_exists(self):
        """segment 命令应注册在 CLI group 中。"""
        from main import cli
        assert "segment" in cli.commands

    def test_cli_status_command_exists(self):
        """status 命令应注册在 CLI group 中。"""
        from main import cli
        assert "status" in cli.commands


# ===================================================================
# TestClassicModeRegression
# ===================================================================
class TestClassicModeRegression:
    """确保 classic 模式不受 agent 架构影响的回归测试。"""

    def test_pipeline_module_importable(self):
        """src.pipeline.Pipeline 应能正常导入。"""
        from src.pipeline import Pipeline
        assert Pipeline is not None

    def test_pipeline_deep_merge(self):
        """_deep_merge 应正确递归合并字典。"""
        from src.pipeline import _deep_merge
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"c": 99}, "e": 5}
        result = _deep_merge(base, override)
        assert result["a"] == 1
        assert result["b"]["c"] == 99
        assert result["b"]["d"] == 3
        assert result["e"] == 5

    def test_classic_pipeline_uses_checkpoint(self):
        """classic Pipeline 应使用 Checkpoint 而非 AgentState。"""
        import inspect
        from src.pipeline import Pipeline
        source = inspect.getsource(Pipeline)
        assert "Checkpoint" in source
        assert "AgentState" not in source

    def test_config_manager_validates_required_sections(self):
        """load_config 应验证必需配置字段。"""
        from src.config_manager import _validate
        with pytest.raises(ValueError, match="配置缺少必要字段"):
            _validate({})

    def test_config_manager_validates_resolution(self):
        """video.resolution 必须为 [width, height]。"""
        from src.config_manager import _validate
        cfg = {
            "segmenter": {}, "promptgen": {}, "imagegen": {},
            "tts": {}, "video": {"resolution": "invalid"},
        }
        with pytest.raises(ValueError, match="resolution"):
            _validate(cfg)


# ===================================================================
# TestStatusDecisions
# ===================================================================
class TestStatusDecisions:
    """status --decisions 功能测试。"""

    def test_status_has_decisions_flag(self):
        """status 命令应有 --decisions flag。"""
        from main import cli
        status_cmd = cli.commands["status"]
        dec_param = None
        for param in status_cmd.params:
            if param.name == "decisions":
                dec_param = param
                break
        assert dec_param is not None
        assert dec_param.is_flag is True

    def test_decisions_with_mock_data(self, tmp_path):
        """--decisions 应正确显示决策日志。"""
        from click.testing import CliRunner
        from main import cli

        # 创建 checkpoint 文件
        ckpt_file = tmp_path / "checkpoint.json"
        ckpt_file.write_text('{"stages": {}, "segments": []}', encoding="utf-8")

        # 创建 decisions 文件
        decisions = [
            {
                "agent": "director",
                "step": "plan",
                "decision": "执行全流程",
                "reason": "新项目无断点",
                "data": None,
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
            {
                "agent": "art_director",
                "step": "quality_check",
                "decision": "通过",
                "reason": "评分达标",
                "data": {"score": 8.5},
                "timestamp": "2026-01-01T00:01:00+00:00",
            },
            {
                "agent": "art_director",
                "step": "quality_check",
                "decision": "retry 重试",
                "reason": "评分不足",
                "data": {"score": 4.0},
                "timestamp": "2026-01-01T00:02:00+00:00",
            },
        ]
        dec_file = tmp_path / "agent_decisions.json"
        dec_file.write_text(json.dumps(decisions, ensure_ascii=False), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["status", str(tmp_path), "--decisions"])

        assert result.exit_code == 0
        assert "director" in result.output
        assert "art_director" in result.output
        assert "执行全流程" in result.output
        # Quality summary should appear
        assert "8.50" in result.output or "8.5" in result.output
        assert "4.00" in result.output or "4.0" in result.output
        # Retry stats should appear
        assert "重试" in result.output

    def test_decisions_no_file(self, tmp_path):
        """decisions 文件不存在时显示提示信息。"""
        from click.testing import CliRunner
        from main import cli

        # 创建 checkpoint 文件 (status 需要)
        ckpt_file = tmp_path / "checkpoint.json"
        ckpt_file.write_text('{"stages": {}, "segments": []}', encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["status", str(tmp_path), "--decisions"])

        assert result.exit_code == 0
        assert "未找到决策日志" in result.output

    def test_decisions_without_flag(self, tmp_path):
        """不传 --decisions 时不显示决策日志。"""
        from click.testing import CliRunner
        from main import cli

        ckpt_file = tmp_path / "checkpoint.json"
        ckpt_file.write_text('{"stages": {}, "segments": []}', encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["status", str(tmp_path)])

        assert result.exit_code == 0
        assert "决策日志" not in result.output

    def test_decision_summary_calculation(self):
        """决策摘要统计计算应正确。"""

        decisions = [
            {"agent": "a", "step": "s1", "decision": "d1", "reason": "r1",
             "data": {"score": 6.0}},
            {"agent": "a", "step": "s2", "decision": "d2", "reason": "r2",
             "data": {"score": 8.0}},
            {"agent": "b", "step": "s3", "decision": "retry 重试", "reason": "r3",
             "data": {"score": 3.0}},
        ]

        # 验证分组和统计逻辑
        from collections import defaultdict
        by_agent = defaultdict(list)
        for d in decisions:
            by_agent[d.get("agent", "unknown")].append(d)

        assert len(by_agent["a"]) == 2
        assert len(by_agent["b"]) == 1

        all_scores = []
        for d in decisions:
            data = d.get("data") or {}
            if "score" in data:
                all_scores.append(float(data["score"]))
        assert len(all_scores) == 3
        assert sum(all_scores) / len(all_scores) == pytest.approx(5.666, abs=0.01)
        assert min(all_scores) == 3.0
        assert max(all_scores) == 8.0

        retry_decisions = [
            d for d in decisions
            if "retry" in d.get("decision", "").lower()
            or "重试" in d.get("decision", "")
        ]
        assert len(retry_decisions) == 1
        assert retry_decisions[0]["agent"] == "b"
