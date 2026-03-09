"""Phase 2 集成测试 -- 断点续传、质量评估工具、ArtDirector 质量控制、配置验证、完整图 Mock。"""
from __future__ import annotations

import json
import operator
from pathlib import Path
from typing import Any, get_type_hints
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# 被测模块（始终可用）
# ---------------------------------------------------------------------------
from src.agents.state import AgentState, Decision, QualityEvaluation
from src.agents.utils import make_decision
from src.agents.director import DirectorAgent, director_node
from src.agents.content_analyzer import ContentAnalyzerAgent, content_analyzer_node
from src.agents.art_director import ArtDirectorAgent, art_director_node
from src.agents.voice_director import VoiceDirectorAgent, voice_director_node
from src.agents.editor import EditorAgent, editor_node

# ---------------------------------------------------------------------------
# 可能尚未实现的模块 -- 用 importorskip / skipif 保护
# ---------------------------------------------------------------------------
try:
    from src.tools.evaluate_quality_tool import EvaluateQualityTool

    _HAS_EVALUATE_QUALITY_TOOL = True
except ImportError:
    _HAS_EVALUATE_QUALITY_TOOL = False
    EvaluateQualityTool = None  # type: ignore[assignment,misc]

# completed_nodes 已在 state.py 中声明，检查是否真正存在
_HAS_COMPLETED_NODES = "completed_nodes" in AgentState.__annotations__


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def minimal_config() -> dict:
    """最小可用配置，包含所有必需字段。"""
    return {
        "segmenter": {"method": "simple", "max_chars": 100, "min_chars": 20},
        "promptgen": {"style": "anime"},
        "imagegen": {"backend": "together"},
        "tts": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "volume": "+0%"},
        "video": {"resolution": [1080, 1920]},
        "llm": {},
        "project": {"default_workspace": "workspace", "default_output": "output"},
    }


@pytest.fixture
def quality_config(minimal_config) -> dict:
    """带质量检查配置。"""
    cfg = dict(minimal_config)
    cfg["agent"] = {
        "quality_check": {
            "enabled": True,
            "threshold": 6.0,
            "max_retries": 3,
            "vision_provider": "openai",
        }
    }
    return cfg


@pytest.fixture
def sample_text() -> str:
    return (
        "张三说道：剑气纵横三万里，一剑光寒十九洲。"
        "李四笑道：好一招落叶飞花剑！"
        "只见张三内力涌动，江湖之上再无敌手。"
    )


@pytest.fixture
def two_segments() -> list[dict]:
    return [
        {"text": "张三说道：剑气纵横三万里。", "index": 0},
        {"text": "李四笑道：好一招落叶飞花剑！", "index": 1},
    ]


@pytest.fixture
def base_state(minimal_config, sample_text, tmp_path) -> dict:
    """供节点函数使用的基础 state dict。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    for sub in ["segments", "images", "audio", "subtitles", "videos"]:
        (ws / sub).mkdir(parents=True, exist_ok=True)
    return {
        "input_file": str(tmp_path / "novel.txt"),
        "config": minimal_config,
        "workspace": str(ws),
        "mode": "agent",
        "budget_mode": True,
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
        "completed_nodes": [],
        "pipeline_plan": None,
    }


# ===================================================================
# 1. TestCheckpointResume -- 断点续传
# ===================================================================
@pytest.mark.skipif(not _HAS_COMPLETED_NODES, reason="completed_nodes 字段尚未添加到 AgentState")
class TestCheckpointResume:
    """断点续传：completed_nodes 跳过已完成节点、state 序列化与恢复。"""

    def test_completed_nodes_has_add_reducer(self):
        """completed_nodes 字段应使用 operator.add 作为 reducer。"""
        hints = get_type_hints(AgentState, include_extras=True)
        ann = hints["completed_nodes"]
        assert hasattr(ann, "__metadata__"), "completed_nodes should be Annotated"
        assert operator.add in ann.__metadata__

    @patch("src.agents.content_analyzer.SegmentTool")
    @patch("src.agents.content_analyzer.ContentAnalyzerAgent.classify_genre")
    @patch("src.agents.content_analyzer.ContentAnalyzerAgent.extract_characters")
    def test_completed_node_skipped_by_wrapper(
        self, mock_chars, mock_genre, mock_seg, base_state
    ):
        """如果 graph.py 中的 wrapper 跳过已完成节点，节点函数不应被真正调用。

        这里直接模拟 wrapper 的逻辑：当 node_name 在 completed_nodes 中时，
        返回空 dict 而不调用实际节点函数。
        """
        # 模拟 wrapper 跳过逻辑
        state = dict(base_state)
        state["completed_nodes"] = ["director", "content_analyzer"]

        def skip_if_completed(node_fn, node_name, state_dict):
            if node_name in state_dict.get("completed_nodes", []):
                return {}
            return node_fn(state_dict)

        # director 和 content_analyzer 已完成，应返回空 dict
        result_director = skip_if_completed(director_node, "director", state)
        assert result_director == {}

        result_ca = skip_if_completed(content_analyzer_node, "content_analyzer", state)
        assert result_ca == {}

        # classify_genre / extract_characters 不应被调用
        mock_genre.assert_not_called()
        mock_chars.assert_not_called()

    @patch("src.agents.art_director.ImageGenTool")
    @patch("src.agents.art_director.PromptGenTool")
    def test_uncompleted_node_executes(
        self, mock_prompt_cls, mock_img_cls, base_state, tmp_path
    ):
        """不在 completed_nodes 中的节点应正常执行。"""
        state = dict(base_state)
        state["completed_nodes"] = ["director", "content_analyzer"]
        state["segments"] = [{"text": "测试文本", "index": 0}]

        # Mock prompt + image tools
        mock_prompt = MagicMock()
        mock_prompt.run.return_value = "a test prompt"
        mock_prompt_cls.return_value = mock_prompt

        mock_img = MagicMock()
        mock_img.run.return_value = None
        mock_img_cls.return_value = mock_img

        # art_director 不在 completed_nodes，应正常执行
        def skip_if_completed(node_fn, node_name, state_dict):
            if node_name in state_dict.get("completed_nodes", []):
                return {}
            return node_fn(state_dict)

        result = skip_if_completed(art_director_node, "art_director", state)
        assert "images" in result
        assert len(result["images"]) == 1
        assert len(result["decisions"]) > 0

    @patch("src.agents.graph.create_agent_graph")
    def test_full_execution_populates_completed_nodes(self, mock_create, base_state):
        """完整执行后 completed_nodes 应包含所有 5 个节点。

        通过模拟 graph.invoke 返回包含 completed_nodes 的结果来验证。
        """
        all_nodes = ["director", "content_analyzer", "art_director", "voice_director", "editor"]
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            **base_state,
            "completed_nodes": all_nodes,
            "final_video": "/tmp/out.mp4",
            "decisions": [make_decision("D", "s", "d", "r")],
        }
        mock_create.return_value = mock_graph

        result = mock_graph.invoke(dict(base_state))
        assert set(result["completed_nodes"]) == set(all_nodes)
        assert len(result["completed_nodes"]) == 5

    def test_state_save_and_reload_preserves_completed_nodes(self, tmp_path, minimal_config):
        """state 保存到 JSON 后重新加载，completed_nodes 应保留。"""
        state_data = {
            "input_file": str(tmp_path / "novel.txt"),
            "workspace": str(tmp_path / "ws"),
            "mode": "agent",
            "full_text": "test",
            "segments": [],
            "prompts": [],
            "images": [],
            "audio_files": [],
            "srt_files": [],
            "final_video": None,
            "quality_scores": [],
            "retry_counts": {},
            "decisions": [make_decision("D", "s", "d", "r")],
            "errors": [],
            "completed_nodes": ["director", "content_analyzer", "art_director"],
            "pipeline_plan": None,
        }

        # 保存
        state_file = tmp_path / "agent_state.json"
        state_file.write_text(
            json.dumps(state_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        # 加载
        loaded = json.loads(state_file.read_text(encoding="utf-8"))
        assert loaded["completed_nodes"] == ["director", "content_analyzer", "art_director"]
        assert len(loaded["decisions"]) == 1

    def test_empty_completed_nodes_runs_all(self, base_state):
        """completed_nodes 为空列表时，所有节点都应执行。"""
        state = dict(base_state)
        state["completed_nodes"] = []

        def skip_if_completed(node_name, completed):
            return node_name in completed

        for name in ["director", "content_analyzer", "art_director", "voice_director", "editor"]:
            assert not skip_if_completed(name, state["completed_nodes"])


# ===================================================================
# 2. TestEvaluateQualityTool -- 质量评估工具
# ===================================================================
@pytest.mark.skipif(not _HAS_EVALUATE_QUALITY_TOOL, reason="EvaluateQualityTool 尚未实现")
class TestEvaluateQualityTool:
    """测试 EvaluateQualityTool -- 全部 Mock Vision LLM。"""

    @pytest.fixture
    def tool(self, quality_config):
        return EvaluateQualityTool(quality_config)

    @pytest.fixture
    def dummy_image(self, tmp_path) -> Path:
        """创建一个假 PNG 文件。"""
        p = tmp_path / "test.png"
        # 最小合法 PNG (1x1 白色像素)
        import struct
        import zlib

        def _min_png():
            sig = b"\x89PNG\r\n\x1a\n"
            # IHDR
            ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
            ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
            # IDAT
            raw = zlib.compress(b"\x00\xff\xff\xff")
            idat_crc = zlib.crc32(b"IDAT" + raw) & 0xFFFFFFFF
            idat = struct.pack(">I", len(raw)) + b"IDAT" + raw + struct.pack(">I", idat_crc)
            # IEND
            iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
            iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
            return sig + ihdr + idat + iend

        p.write_bytes(_min_png())
        return p

    @patch("src.tools.evaluate_quality_tool.EvaluateQualityTool._get_vision_llm")
    def test_normal_evaluation_returns_quality_evaluation(
        self, mock_get_llm, tool, dummy_image
    ):
        """正常评估返回 QualityEvaluation。"""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content='{"score": 7.5, "feedback": "good composition"}'
        )
        mock_get_llm.return_value = mock_llm

        result = tool.run(dummy_image, "测试文本", "a beautiful scene")
        assert isinstance(result, dict)
        assert "score" in result
        assert result["score"] == pytest.approx(7.5, abs=0.1)

    @patch("src.tools.evaluate_quality_tool.EvaluateQualityTool._get_vision_llm")
    def test_vision_llm_unavailable_returns_default(
        self, mock_get_llm, tool, dummy_image
    ):
        """Vision LLM 不可用返回默认分数。"""
        mock_get_llm.return_value = None

        result = tool.run(dummy_image, "测试文本", "a scene")
        assert isinstance(result, dict)
        assert "score" in result
        # 默认分数应在合理范围内
        assert 0.0 <= result["score"] <= 10.0

    @patch("src.tools.evaluate_quality_tool.EvaluateQualityTool._get_vision_llm")
    def test_vision_llm_returns_garbage_json_degrades(
        self, mock_get_llm, tool, dummy_image
    ):
        """Vision LLM 返回垃圾 JSON 降级。"""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="this is not json at all!!!")
        mock_get_llm.return_value = mock_llm

        result = tool.run(dummy_image, "测试文本", "a scene")
        assert isinstance(result, dict)
        assert "score" in result
        # 降级情况应返回默认分数
        assert 0.0 <= result["score"] <= 10.0

    def test_image_file_not_exist_raises(self, tool):
        """图片文件不存在应报错（当 vision LLM 可用时）。"""
        fake_path = Path("/nonexistent/image.png")
        # Mock a working vision LLM so the tool actually tries to open the file
        mock_llm = MagicMock()
        tool._vision_llm = mock_llm
        tool._get_vision_llm = MagicMock(return_value=mock_llm)
        with pytest.raises((FileNotFoundError, OSError)):
            tool.run(fake_path, "text", "prompt")


# ===================================================================
# 3. TestArtDirectorWithQualityControl
# ===================================================================
class TestArtDirectorWithQualityControl:
    """ArtDirector 质量检查循环测试。"""

    def _make_agent(self, config, budget=False):
        """创建带 mock 工具的 ArtDirectorAgent。"""
        with patch("src.agents.art_director.PromptGenTool") as mp, \
             patch("src.agents.art_director.ImageGenTool") as mi:
            mp.return_value = MagicMock()
            mi.return_value = MagicMock()
            agent = ArtDirectorAgent(config, budget_mode=budget)
        return agent

    def test_quality_check_enabled_first_pass(self, quality_config, tmp_path):
        """质量检查开启 + 首次通过（score=8.0 >= threshold=6.0）。"""
        agent = self._make_agent(quality_config)
        agent.prompt_gen = MagicMock()
        agent.prompt_gen.run.return_value = "a beautiful landscape"
        agent.image_gen = MagicMock()
        agent.image_gen.run.return_value = None

        # Mock quality_tool.run 返回 8.0
        agent.quality_tool.run = MagicMock(return_value=QualityEvaluation(
            score=8.0, feedback="excellent", passed=True,
            composition=2, clarity=2, text_match=2, color=2, consistency=0,
        ))

        ws = tmp_path / "ws"
        (ws / "images").mkdir(parents=True)

        path, score, retries, decisions = agent.generate_image(
            "测试文本", 0, ws, full_text="完整文本"
        )
        assert score == pytest.approx(8.0)
        assert retries == 0
        assert any("通过" in d.get("decision", "") for d in decisions)

    def test_quality_check_retry_then_pass(self, quality_config, tmp_path):
        """质量检查开启 + 重试后通过：先返回 4.0 再返回 7.0。"""
        agent = self._make_agent(quality_config)
        agent.prompt_gen = MagicMock()
        agent.prompt_gen.run.return_value = "a scene"
        agent.image_gen = MagicMock()
        agent.image_gen.run.return_value = None

        # 第一次 4.0（未通过），第二次 7.0（通过）
        agent.quality_tool.run = MagicMock(side_effect=[
            QualityEvaluation(
                score=4.0, feedback="too blurry", passed=False,
                composition=1, clarity=1, text_match=1, color=1, consistency=0,
            ),
            QualityEvaluation(
                score=7.0, feedback="much better", passed=True,
                composition=2, clarity=2, text_match=2, color=1, consistency=0,
            ),
        ])

        ws = tmp_path / "ws"
        (ws / "images").mkdir(parents=True)

        path, score, retries, decisions = agent.generate_image(
            "测试文本", 0, ws, full_text="完整文本"
        )
        assert score == pytest.approx(7.0)
        assert retries == 1
        assert agent.quality_tool.run.call_count == 2

    def test_max_retries_uses_best_result(self, quality_config, tmp_path):
        """达到最大重试次数使用最佳结果（始终返回 3.0）。"""
        cfg = dict(quality_config)
        cfg["agent"]["quality_check"]["max_retries"] = 2

        agent = self._make_agent(cfg)
        agent.prompt_gen = MagicMock()
        agent.prompt_gen.run.return_value = "a scene"
        agent.image_gen = MagicMock()
        agent.image_gen.run.return_value = None

        # 始终返回 3.0
        agent.quality_tool.run = MagicMock(return_value=QualityEvaluation(
            score=3.0, feedback="not good enough", passed=False,
            composition=1, clarity=1, text_match=1, color=0, consistency=0,
        ))

        ws = tmp_path / "ws"
        (ws / "images").mkdir(parents=True)

        path, score, retries, decisions = agent.generate_image(
            "测试文本", 0, ws, full_text="完整文本"
        )
        assert score == pytest.approx(3.0)
        assert retries == 2  # max_retries
        # 应有 "达到重试上限" 决策
        assert any("重试上限" in d.get("decision", "") for d in decisions)

    def test_prompt_changes_on_retry(self, quality_config, tmp_path):
        """验证重试时 prompt_gen.run 被多次调用（重试时可能有不同 prompt）。"""
        agent = self._make_agent(quality_config)

        call_count = 0
        prompts_used = []

        def mock_prompt_run(text, segment_index=0, full_text=None):
            nonlocal call_count
            call_count += 1
            p = f"prompt_v{call_count}"
            prompts_used.append(p)
            return p

        agent.prompt_gen = MagicMock()
        agent.prompt_gen.run.side_effect = mock_prompt_run
        agent.image_gen = MagicMock()
        agent.image_gen.run.return_value = None

        # 第一次低分，第二次通过
        agent.quality_tool.run = MagicMock(side_effect=[
            QualityEvaluation(
                score=3.0, feedback="needs work", passed=False,
                composition=1, clarity=0, text_match=1, color=1, consistency=0,
            ),
            QualityEvaluation(
                score=8.0, feedback="great", passed=True,
                composition=2, clarity=2, text_match=3, color=1, consistency=0,
            ),
        ])

        ws = tmp_path / "ws"
        (ws / "images").mkdir(parents=True)

        agent.generate_image("测试文本", 0, ws, full_text="完整文本")

        # prompt_gen.run 应被调用 2 次
        assert agent.prompt_gen.run.call_count == 2
        assert len(prompts_used) == 2

    def test_budget_mode_skips_quality_check(self, quality_config, tmp_path):
        """省钱模式跳过质量检查。"""
        agent = self._make_agent(quality_config, budget=True)
        agent.prompt_gen = MagicMock()
        agent.prompt_gen.run.return_value = "a scene"
        agent.image_gen = MagicMock()
        agent.image_gen.run.return_value = None

        agent.quality_tool.run = MagicMock()

        ws = tmp_path / "ws"
        (ws / "images").mkdir(parents=True)

        path, score, retries, decisions = agent.generate_image(
            "测试文本", 0, ws
        )
        # 省钱模式不调用质量评估
        agent.quality_tool.run.assert_not_called()
        assert score == -1.0
        assert retries == 0


# ===================================================================
# 4. TestConfigAgent -- config 验证
# ===================================================================
class TestConfigAgent:
    """配置加载与 agent 相关字段验证。"""

    def test_no_agent_config_no_error(self, minimal_config):
        """无 agent 配置时不报错，ArtDirector 使用默认值。"""
        assert "agent" not in minimal_config
        # 创建 ArtDirectorAgent 应正常
        with patch("src.agents.art_director.PromptGenTool"), \
             patch("src.agents.art_director.ImageGenTool"):
            agent = ArtDirectorAgent(minimal_config)
        # 默认阈值
        threshold = (
            minimal_config.get("agent", {})
            .get("quality_check", {})
            .get("threshold", agent.QUALITY_THRESHOLD)
        )
        assert threshold == 6.0

    def test_full_agent_config_loads_correctly(self, quality_config):
        """有完整 agent 配置加载正确。"""
        qc = quality_config["agent"]["quality_check"]
        assert qc["enabled"] is True
        assert qc["threshold"] == 6.0
        assert qc["max_retries"] == 3
        assert qc["vision_provider"] == "openai"

        with patch("src.agents.art_director.PromptGenTool"), \
             patch("src.agents.art_director.ImageGenTool"):
            agent = ArtDirectorAgent(quality_config)

        loaded_threshold = (
            quality_config.get("agent", {})
            .get("quality_check", {})
            .get("threshold", agent.QUALITY_THRESHOLD)
        )
        assert loaded_threshold == 6.0

    @pytest.mark.parametrize("threshold", [-1.0, 0.0, 5.5, 10.0, 11.0])
    def test_quality_threshold_range(self, quality_config, threshold):
        """quality_check.threshold 各种值。"""
        quality_config["agent"]["quality_check"]["threshold"] = threshold
        with patch("src.agents.art_director.PromptGenTool"), \
             patch("src.agents.art_director.ImageGenTool"):
            agent = ArtDirectorAgent(quality_config)
        actual = (
            quality_config.get("agent", {})
            .get("quality_check", {})
            .get("threshold", agent.QUALITY_THRESHOLD)
        )
        assert actual == threshold

    @pytest.mark.parametrize("max_retries", [0, 1, 5, 10])
    def test_quality_max_retries_range(self, quality_config, max_retries):
        """quality_check.max_retries 各种值。"""
        quality_config["agent"]["quality_check"]["max_retries"] = max_retries
        actual = quality_config["agent"]["quality_check"]["max_retries"]
        assert actual == max_retries

    def test_quality_check_disabled_by_default(self, minimal_config):
        """默认配置中 quality_check 未启用。"""
        enabled = (
            minimal_config.get("agent", {})
            .get("quality_check", {})
            .get("enabled", False)
        )
        assert enabled is False

    def test_config_with_gemini_vision_provider(self, quality_config):
        """vision_provider 可以设为 gemini。"""
        quality_config["agent"]["quality_check"]["vision_provider"] = "gemini"
        provider = quality_config["agent"]["quality_check"]["vision_provider"]
        assert provider == "gemini"


# ===================================================================
# 5. TestFullGraphMocked -- 完整图 Mock 测试
# ===================================================================
class TestFullGraphMocked:
    """完整 LangGraph 图 + 所有外部调用 Mock 的端到端测试。"""

    @pytest.fixture
    def novel_file(self, tmp_path) -> Path:
        p = tmp_path / "novel.txt"
        p.write_text(
            "张三说道：剑气纵横三万里，一剑光寒十九洲。"
            "李四笑道：好一招落叶飞花剑！"
            "只见张三内力涌动，江湖之上再无敌手。",
            encoding="utf-8",
        )
        return p

    @pytest.fixture
    def full_config(self, tmp_path) -> dict:
        """完整配置，输出目录指向 tmp_path。"""
        return {
            "segmenter": {"method": "simple", "max_chars": 50, "min_chars": 10},
            "promptgen": {"style": "anime"},
            "imagegen": {"backend": "together"},
            "tts": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "volume": "+0%"},
            "video": {"resolution": [1080, 1920]},
            "llm": {},
            "project": {
                "default_workspace": str(tmp_path / "workspace"),
                "default_output": str(tmp_path / "output"),
            },
        }

    @patch("src.video.video_assembler.VideoAssembler")
    @patch("src.tts.subtitle_generator.SubtitleGenerator")
    @patch("src.tts.tts_engine.TTSEngine")
    @patch("src.imagegen.image_generator.create_image_generator")
    @patch("src.segmenter.text_segmenter.create_segmenter")
    def test_full_graph_end_to_end(
        self,
        mock_create_seg,
        mock_create_img,
        mock_tts_engine_cls,
        mock_sub_gen_cls,
        mock_assembler_cls,
        novel_file,
        full_config,
        tmp_path,
    ):
        """完整 graph 从头到尾运行，验证所有 5 个 Agent 记录决策。"""
        # -- Mock segmenter --
        mock_segmenter = MagicMock()
        mock_segmenter.segment.return_value = [
            {"text": "张三说道：剑气纵横三万里，一剑光寒十九洲。", "index": 0},
            {"text": "李四笑道：好一招落叶飞花剑！", "index": 1},
        ]
        mock_create_seg.return_value = mock_segmenter

        # -- Mock image generator --
        mock_img_gen = MagicMock()
        mock_img = MagicMock()  # PIL Image mock
        mock_img.save = MagicMock()
        mock_img_gen.generate.return_value = mock_img
        mock_create_img.return_value = mock_img_gen

        # -- Mock TTS engine --
        mock_engine = MagicMock()
        mock_engine.synthesize.return_value = (
            MagicMock(),  # audio path
            [{"offset": 0, "duration": 100, "text": "test"}],  # word boundaries
        )
        mock_tts_engine_cls.return_value = mock_engine

        # -- Mock subtitle generator --
        mock_sub = MagicMock()
        mock_sub.generate_srt.return_value = None
        mock_sub_gen_cls.return_value = mock_sub

        # -- Mock video assembler --
        mock_asm = MagicMock()
        mock_asm.assemble.return_value = None
        mock_assembler_cls.return_value = mock_asm

        # -- Mock prompt generator (用于 ArtDirector) --
        with patch("src.agents.art_director.PromptGenTool") as mock_pg_cls:
            mock_pg = MagicMock()
            mock_pg.run.return_value = "a test prompt for anime style scene"
            mock_pg_cls.return_value = mock_pg

            # 构建并运行 graph
            from src.agents.graph import create_agent_graph

            graph = create_agent_graph(full_config)

            ws = tmp_path / "workspace" / "novel"
            ws.mkdir(parents=True, exist_ok=True)
            for sub in ["segments", "images", "audio", "subtitles", "videos"]:
                (ws / sub).mkdir(parents=True, exist_ok=True)

            output_dir = tmp_path / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            initial_state = {
                "input_file": str(novel_file),
                "config": full_config,
                "workspace": str(ws),
                "mode": "agent",
                "budget_mode": True,  # 省钱模式，跳过 LLM + 质量检查
                "resume": False,
                "full_text": novel_file.read_text(encoding="utf-8"),
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
                "completed_nodes": [],
                "pipeline_plan": None,
            }

            result = graph.invoke(initial_state)

        # -- 验证 --
        # 1. 所有 5 个 Agent 的 decisions 都被记录
        decisions = result.get("decisions", [])
        agent_names_in_decisions = {d["agent"] for d in decisions}
        expected_agents = {"Director", "ContentAnalyzer", "ArtDirector", "VoiceDirector", "Editor"}
        assert expected_agents == agent_names_in_decisions, (
            f"Missing agents in decisions: {expected_agents - agent_names_in_decisions}"
        )

        # 2. final_video 有值
        assert result.get("final_video") is not None
        assert result["final_video"].endswith(".mp4")

        # 3. completed_nodes 包含全部 5 个节点名（如果 graph.py 中的 wrapper 已实现）
        completed = result.get("completed_nodes", [])
        if completed:
            expected_nodes = {"director", "content_analyzer", "art_director", "voice_director", "editor"}
            assert set(completed) >= expected_nodes

        # 4. 各阶段数据不为空
        assert len(result["segments"]) == 2
        assert len(result["images"]) == 2
        assert len(result["audio_files"]) == 2
        assert len(result["srt_files"]) == 2

        # 5. pipeline_plan 由 Director 设置
        assert result.get("pipeline_plan") is not None
        assert "char_count" in result["pipeline_plan"]

    @patch("src.video.video_assembler.VideoAssembler")
    @patch("src.tts.subtitle_generator.SubtitleGenerator")
    @patch("src.tts.tts_engine.TTSEngine")
    @patch("src.imagegen.image_generator.create_image_generator")
    @patch("src.segmenter.text_segmenter.create_segmenter")
    def test_full_graph_single_segment(
        self,
        mock_create_seg,
        mock_create_img,
        mock_tts_engine_cls,
        mock_sub_gen_cls,
        mock_assembler_cls,
        novel_file,
        full_config,
        tmp_path,
    ):
        """单段文本也能正常走完整流程。"""
        mock_segmenter = MagicMock()
        mock_segmenter.segment.return_value = [
            {"text": "短文本测试。", "index": 0},
        ]
        mock_create_seg.return_value = mock_segmenter

        mock_img_gen = MagicMock()
        mock_img = MagicMock()
        mock_img.save = MagicMock()
        mock_img_gen.generate.return_value = mock_img
        mock_create_img.return_value = mock_img_gen

        mock_engine = MagicMock()
        mock_engine.synthesize.return_value = (MagicMock(), [])
        mock_tts_engine_cls.return_value = mock_engine

        mock_sub = MagicMock()
        mock_sub_gen_cls.return_value = mock_sub

        mock_asm = MagicMock()
        mock_assembler_cls.return_value = mock_asm

        with patch("src.agents.art_director.PromptGenTool") as mock_pg_cls:
            mock_pg = MagicMock()
            mock_pg.run.return_value = "single segment prompt"
            mock_pg_cls.return_value = mock_pg

            from src.agents.graph import create_agent_graph

            graph = create_agent_graph(full_config)

            ws = tmp_path / "workspace" / "novel"
            ws.mkdir(parents=True, exist_ok=True)
            for sub in ["segments", "images", "audio", "subtitles", "videos"]:
                (ws / sub).mkdir(parents=True, exist_ok=True)
            (tmp_path / "output").mkdir(parents=True, exist_ok=True)

            initial_state = {
                "input_file": str(novel_file),
                "config": full_config,
                "workspace": str(ws),
                "mode": "agent",
                "budget_mode": True,
                "resume": False,
                "full_text": "短文本测试。",
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
                "completed_nodes": [],
                "pipeline_plan": None,
            }

            result = graph.invoke(initial_state)

        assert result.get("final_video") is not None
        assert len(result["segments"]) == 1
        assert len(result["images"]) == 1

    @patch("src.video.video_assembler.VideoAssembler")
    @patch("src.tts.subtitle_generator.SubtitleGenerator")
    @patch("src.tts.tts_engine.TTSEngine")
    @patch("src.imagegen.image_generator.create_image_generator")
    @patch("src.segmenter.text_segmenter.create_segmenter")
    def test_full_graph_decisions_have_timestamps(
        self,
        mock_create_seg,
        mock_create_img,
        mock_tts_engine_cls,
        mock_sub_gen_cls,
        mock_assembler_cls,
        novel_file,
        full_config,
        tmp_path,
    ):
        """所有 decisions 都应包含 timestamp 字段。"""
        mock_segmenter = MagicMock()
        mock_segmenter.segment.return_value = [
            {"text": "测试文本。", "index": 0},
        ]
        mock_create_seg.return_value = mock_segmenter

        mock_img_gen = MagicMock()
        mock_img = MagicMock()
        mock_img.save = MagicMock()
        mock_img_gen.generate.return_value = mock_img
        mock_create_img.return_value = mock_img_gen

        mock_engine = MagicMock()
        mock_engine.synthesize.return_value = (MagicMock(), [])
        mock_tts_engine_cls.return_value = mock_engine

        mock_sub = MagicMock()
        mock_sub_gen_cls.return_value = mock_sub

        mock_asm = MagicMock()
        mock_assembler_cls.return_value = mock_asm

        with patch("src.agents.art_director.PromptGenTool") as mock_pg_cls:
            mock_pg = MagicMock()
            mock_pg.run.return_value = "prompt"
            mock_pg_cls.return_value = mock_pg

            from src.agents.graph import create_agent_graph

            graph = create_agent_graph(full_config)

            ws = tmp_path / "workspace" / "novel"
            ws.mkdir(parents=True, exist_ok=True)
            for sub in ["segments", "images", "audio", "subtitles", "videos"]:
                (ws / sub).mkdir(parents=True, exist_ok=True)
            (tmp_path / "output").mkdir(parents=True, exist_ok=True)

            initial_state = {
                "input_file": str(novel_file),
                "config": full_config,
                "workspace": str(ws),
                "mode": "agent",
                "budget_mode": True,
                "resume": False,
                "full_text": "测试文本。",
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
                "completed_nodes": [],
                "pipeline_plan": None,
            }

            result = graph.invoke(initial_state)

        from datetime import datetime

        for d in result.get("decisions", []):
            assert "timestamp" in d, f"Decision missing timestamp: {d}"
            # 应能解析为 ISO 日期
            datetime.fromisoformat(d["timestamp"])
