"""Tests for src/scriptplan/ module"""
import json
import pytest
from unittest.mock import MagicMock

from src.scriptplan.models import (
    AssetType, MotionType, ScriptSegment, SegmentPurpose,
    VideoIdea, VideoScript, VoiceParams,
)
from src.scriptplan.idea_planner import IdeaPlanner
from src.scriptplan.script_planner import ScriptPlanner
from src.scriptplan.asset_strategy import AssetStrategy


# Helper: 创建 mock LLM
def make_mock_llm(response_content: str):
    from src.llm.llm_client import LLMResponse
    mock = MagicMock()
    mock.chat.return_value = LLMResponse(
        content=response_content,
        model="test-model",
        usage=None,
    )
    return mock


class TestModels:
    """测试数据模型"""

    def test_video_idea_defaults(self):
        idea = VideoIdea(video_type="悬疑反转")
        assert idea.target_duration == 45
        assert idea.segment_count == 6

    def test_script_segment_defaults(self):
        seg = ScriptSegment(
            id=1,
            purpose=SegmentPurpose.HOOK,
            voiceover="测试旁白",
            visual="测试画面",
        )
        assert seg.duration_sec == 3.0
        assert seg.asset_type == AssetType.IMAGE
        assert seg.motion == MotionType.STATIC

    def test_video_script_compute_duration(self):
        script = VideoScript(
            title="测试",
            theme="测试",
            hook="钩子",
            tone="悬疑",
            segments=[
                ScriptSegment(id=1, purpose=SegmentPurpose.HOOK, voiceover="a", visual="b", duration_sec=3.0),
                ScriptSegment(id=2, purpose=SegmentPurpose.DEVELOP, voiceover="c", visual="d", duration_sec=5.0),
            ],
        )
        total = script.compute_duration()
        assert total == 8.0
        assert script.total_duration == 8.0

    def test_voice_params_defaults(self):
        vp = VoiceParams()
        assert vp.speed == "+0%"
        assert vp.emotion == "neutral"
        assert vp.pause_before == 0.0

    def test_segment_purpose_enum(self):
        assert SegmentPurpose.HOOK.value == "hook"
        assert SegmentPurpose.TWIST.value == "twist"

    def test_motion_type_enum(self):
        assert MotionType.PUSH_IN.value == "push_in"
        assert MotionType.REVEAL.value == "reveal"

    def test_asset_type_enum(self):
        assert AssetType.IMAGE.value == "image"
        assert AssetType.IMAGE2VIDEO.value == "image2video"

    def test_script_segment_serialization(self):
        seg = ScriptSegment(
            id=1, purpose=SegmentPurpose.HOOK,
            voiceover="旁白", visual="画面",
        )
        data = seg.model_dump()
        assert data["id"] == 1
        assert data["purpose"] == "hook"
        restored = ScriptSegment(**data)
        assert restored.voiceover == "旁白"

    def test_video_script_json_roundtrip(self):
        script = VideoScript(
            title="测试", theme="主题", hook="钩子", tone="悬疑",
            segments=[
                ScriptSegment(id=1, purpose=SegmentPurpose.HOOK, voiceover="a", visual="b"),
            ],
        )
        json_str = script.model_dump_json()
        restored = VideoScript.model_validate_json(json_str)
        assert restored.title == "测试"
        assert len(restored.segments) == 1


class TestIdeaPlanner:
    """测试 IdeaPlanner"""

    def test_plan_returns_video_idea(self):
        mock_llm = make_mock_llm(json.dumps({
            "video_type": "悬疑反转",
            "target_duration": 45,
            "segment_count": 6,
            "rhythm": "3秒钩子+3段推进+1段反转+1段收尾",
            "twist_type": "身份反转",
            "ending_type": "评论钩子",
            "tone": "悬疑",
        }))

        planner = IdeaPlanner(mock_llm)
        idea = planner.plan("外卖员送餐到废弃医院")

        assert isinstance(idea, VideoIdea)
        assert idea.video_type == "悬疑反转"
        assert idea.segment_count == 6
        assert idea.tone == "悬疑"

    def test_plan_clamps_segment_count(self):
        """段数应该限制在 4-10 之间"""
        mock_llm = make_mock_llm(json.dumps({
            "video_type": "测试",
            "segment_count": 100,  # 超大
        }))

        planner = IdeaPlanner(mock_llm)
        idea = planner.plan("测试")
        assert idea.segment_count <= 10

    def test_plan_with_custom_duration(self):
        mock_llm = make_mock_llm(json.dumps({
            "video_type": "情感共鸣",
            "target_duration": 60,
            "segment_count": 8,
        }))

        planner = IdeaPlanner(mock_llm)
        idea = planner.plan("测试", target_duration=60)
        mock_llm.chat.assert_called_once()
        # 确认 prompt 中包含目标时长
        call_args = mock_llm.chat.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        assert "60" in messages[1]["content"]

    def test_plan_handles_invalid_json(self):
        """LLM 返回非 JSON 时应返回默认方案"""
        mock_llm = make_mock_llm("这不是JSON")
        planner = IdeaPlanner(mock_llm)
        idea = planner.plan("测试")
        assert isinstance(idea, VideoIdea)
        assert idea.video_type  # 应该有默认值


class TestScriptPlanner:
    """测试 ScriptPlanner"""

    def _make_idea(self):
        return VideoIdea(
            video_type="悬疑反转",
            target_duration=45,
            segment_count=5,
            rhythm="3秒钩子+2段推进+1段反转+1段收尾",
            twist_type="身份反转",
            ending_type="评论钩子",
            tone="悬疑",
        )

    def test_plan_returns_video_script(self):
        response = json.dumps({
            "title": "废弃医院的外卖",
            "theme": "深夜外卖的恐怖经历",
            "hook": "凌晨三点，他接到一单废弃医院的外卖",
            "segments": [
                {"id": 1, "purpose": "hook", "voiceover": "凌晨三点", "visual": "空街道", "duration_sec": 3},
                {"id": 2, "purpose": "setup", "voiceover": "收货人", "visual": "手机屏幕", "duration_sec": 3},
                {"id": 3, "purpose": "develop", "voiceover": "走进去", "visual": "医院走廊", "duration_sec": 4},
                {"id": 4, "purpose": "twist", "voiceover": "反转", "visual": "真相", "duration_sec": 4},
                {"id": 5, "purpose": "ending", "voiceover": "结尾", "visual": "离开", "duration_sec": 3},
            ],
            "ending_hook": "如果是你，你会敲门吗？",
        })
        mock_llm = make_mock_llm(response)

        planner = ScriptPlanner(mock_llm)
        script = planner.plan(self._make_idea(), "外卖员送餐到废弃医院")

        assert isinstance(script, VideoScript)
        assert script.title == "废弃医院的外卖"
        assert len(script.segments) == 5
        assert script.segments[0].purpose == SegmentPurpose.HOOK
        assert script.segments[3].purpose == SegmentPurpose.TWIST

    def test_plan_assigns_voice_params(self):
        """不同用途的段落应有不同的默认语音参数"""
        response = json.dumps({
            "title": "测试",
            "theme": "测试",
            "hook": "钩子",
            "segments": [
                {"id": 1, "purpose": "hook", "voiceover": "a", "visual": "b", "duration_sec": 3},
                {"id": 2, "purpose": "twist", "voiceover": "c", "visual": "d", "duration_sec": 4},
            ],
            "ending_hook": "",
        })
        mock_llm = make_mock_llm(response)
        planner = ScriptPlanner(mock_llm)
        script = planner.plan(self._make_idea(), "测试")

        # hook段语速应该稍快
        assert script.segments[0].voice_params.speed == "+5%"
        # twist段应有前置停顿
        assert script.segments[1].voice_params.pause_before == 0.5

    def test_plan_handles_invalid_purpose(self):
        """无效的 purpose 应该 fallback 到 develop"""
        response = json.dumps({
            "title": "测试",
            "theme": "测试",
            "hook": "钩子",
            "segments": [
                {"id": 1, "purpose": "invalid_purpose", "voiceover": "a", "visual": "b"},
            ],
            "ending_hook": "",
        })
        mock_llm = make_mock_llm(response)
        planner = ScriptPlanner(mock_llm)
        script = planner.plan(self._make_idea(), "测试")
        assert script.segments[0].purpose == SegmentPurpose.DEVELOP

    def test_plan_handles_markdown_json(self):
        """应该能处理 markdown 代码块包裹的 JSON"""
        response = '```json\n{"title": "测试", "theme": "t", "hook": "h", "segments": [], "ending_hook": ""}\n```'
        mock_llm = make_mock_llm(response)
        planner = ScriptPlanner(mock_llm)
        script = planner.plan(self._make_idea(), "测试")
        assert script.title == "测试"


class TestAssetStrategy:
    """测试 AssetStrategy"""

    def _make_script(self, purposes=None):
        if purposes is None:
            purposes = ["hook", "setup", "develop", "twist", "ending"]
        segments = [
            ScriptSegment(
                id=i + 1,
                purpose=SegmentPurpose(p),
                voiceover=f"segment {i + 1}",
                visual=f"visual {i + 1}",
            )
            for i, p in enumerate(purposes)
        ]
        return VideoScript(
            title="测试", theme="测试", hook="钩子", tone="悬疑",
            segments=segments,
        )

    def test_free_budget_all_images(self):
        """free 预算应该全部用静图"""
        strategy = AssetStrategy()
        script = strategy.assign(self._make_script(), budget="free")
        for seg in script.segments:
            assert seg.asset_type == AssetType.IMAGE

    def test_low_budget_limited_i2v(self):
        """low 预算应该最多2段图生视频"""
        strategy = AssetStrategy()
        script = strategy.assign(self._make_script(), budget="low")
        i2v_count = sum(1 for s in script.segments if s.asset_type == AssetType.IMAGE2VIDEO)
        assert i2v_count <= 2

    def test_high_budget_uses_video(self):
        """high 预算应该使用更多动态素材"""
        strategy = AssetStrategy()
        script = strategy.assign(self._make_script(), budget="high")
        dynamic_count = sum(
            1 for s in script.segments
            if s.asset_type in (AssetType.IMAGE2VIDEO, AssetType.VIDEO)
        )
        assert dynamic_count > 0

    def test_hook_and_twist_get_priority(self):
        """hook 和 twist 段应该优先获得动态素材"""
        strategy = AssetStrategy()
        script = strategy.assign(self._make_script(), budget="low")

        # 在 low 预算下，i2v 名额应该优先给 hook 和 twist
        hook_seg = next(s for s in script.segments if s.purpose == SegmentPurpose.HOOK)
        twist_seg = next(s for s in script.segments if s.purpose == SegmentPurpose.TWIST)

        # hook 或 twist 至少有一个获得了 i2v
        dynamic = (
            hook_seg.asset_type == AssetType.IMAGE2VIDEO
            or twist_seg.asset_type == AssetType.IMAGE2VIDEO
        )
        assert dynamic

    def test_static_image_gets_motion(self):
        """静图段的 hook/twist 应该被分配动态镜头"""
        strategy = AssetStrategy()
        script = strategy.assign(self._make_script(), budget="free")

        hook_seg = next(s for s in script.segments if s.purpose == SegmentPurpose.HOOK)
        # hook段即使是静图也应该有 push_in 效果
        assert hook_seg.motion != MotionType.STATIC

    def test_unknown_budget_falls_back(self):
        """未知预算档位应该 fallback 到 low"""
        strategy = AssetStrategy()
        script = strategy.assign(self._make_script(), budget="unknown_budget")
        # 不应该报错
        assert all(s.asset_type is not None for s in script.segments)


class TestDirectorPipeline:
    """测试 DirectorPipeline 基本结构"""

    def test_import(self):
        """能正常导入"""
        from src.director_pipeline import DirectorPipeline
        assert DirectorPipeline is not None

    def test_init_creates_workspace(self, tmp_path):
        """初始化应创建工作目录"""
        from src.director_pipeline import DirectorPipeline
        ws = tmp_path / "test_workspace"
        pipeline = DirectorPipeline(
            workspace=str(ws),
            config={"llm": {}, "tts": {}, "imagegen": {"backend": "together"}, "video": {"resolution": [1080, 1920]}},
        )
        assert ws.exists()
