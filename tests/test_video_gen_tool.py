"""VideoGenTool 与 ArtDirector 视频生成测试。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.tools.video_gen_tool import VideoGenTool
from src.agents.art_director import ArtDirectorAgent, art_director_node
from src.agents.utils import make_decision


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def videogen_config() -> dict:
    """包含 videogen 配置的完整配置字典。"""
    return {
        "llm": {"provider": "openai"},
        "imagegen": {"backend": "siliconflow"},
        "videogen": {"backend": "kling", "duration": 5, "use_image_as_first_frame": True},
        "agent": {"quality_check": {"enabled": False}},
        "promptgen": {},
        "tts": {},
    }


@pytest.fixture
def config_no_video() -> dict:
    """不含 videogen 的配置。"""
    return {
        "llm": {"provider": "openai"},
        "imagegen": {"backend": "siliconflow"},
        "agent": {"quality_check": {"enabled": False}},
        "promptgen": {},
        "tts": {},
    }


# ===========================================================================
# VideoGenTool 测试
# ===========================================================================


class TestVideoGenTool:
    """VideoGenTool 单元测试。"""

    def test_lazy_init(self, videogen_config: dict) -> None:
        """生成器在首次 run() 前不应被创建。"""
        tool = VideoGenTool(videogen_config)
        assert tool._gen is None

    @patch("src.tools.video_gen_tool.shutil.copy2")
    def test_run_generates_video(
        self, mock_copy2: MagicMock, videogen_config: dict, tmp_path: Path
    ) -> None:
        """run() 应调用 generate 并将结果拷贝到 output_path。"""
        fake_video_path = tmp_path / "generated.mp4"
        fake_video_path.write_bytes(b"fake-video-data")

        mock_gen = MagicMock()
        mock_result = MagicMock()
        mock_result.video_path = fake_video_path
        mock_gen.generate.return_value = mock_result

        with patch(
            "src.videogen.video_generator.create_video_generator",
            return_value=mock_gen,
        ):
            tool = VideoGenTool(videogen_config)
            out = tmp_path / "output" / "clip.mp4"
            result = tool.run("a warrior fights", out)

        assert result == out
        mock_gen.generate.assert_called_once_with(
            prompt="a warrior fights", image_path=None, duration=5
        )
        mock_copy2.assert_called_once_with(str(fake_video_path), str(out))

    @patch("src.tools.video_gen_tool.shutil.copy2")
    def test_run_with_image_path(
        self, mock_copy2: MagicMock, videogen_config: dict, tmp_path: Path
    ) -> None:
        """run() 传入 image_path 时应将其转发给 generate。"""
        fake_video_path = tmp_path / "gen.mp4"
        fake_video_path.write_bytes(b"fake")

        mock_gen = MagicMock()
        mock_result = MagicMock()
        mock_result.video_path = fake_video_path
        mock_gen.generate.return_value = mock_result

        img = tmp_path / "frame.png"
        img.write_bytes(b"fake-image")

        with patch(
            "src.videogen.video_generator.create_video_generator",
            return_value=mock_gen,
        ):
            tool = VideoGenTool(videogen_config)
            out = tmp_path / "clip.mp4"
            tool.run("scene prompt", out, image_path=img)

        mock_gen.generate.assert_called_once_with(
            prompt="scene prompt", image_path=img, duration=5
        )

    def test_close_releases_resource(self, videogen_config: dict) -> None:
        """close() 应调用底层生成器的 close() 并置空 _gen。"""
        tool = VideoGenTool(videogen_config)
        mock_gen = MagicMock()
        tool._gen = mock_gen

        tool.close()

        mock_gen.close.assert_called_once()
        assert tool._gen is None

    def test_close_idempotent(self, videogen_config: dict) -> None:
        """连续调用 close() 两次不应报错。"""
        tool = VideoGenTool(videogen_config)
        mock_gen = MagicMock()
        tool._gen = mock_gen

        tool.close()
        tool.close()  # 第二次不应抛出异常

        mock_gen.close.assert_called_once()


# ===========================================================================
# ArtDirector 视频生成测试
# ===========================================================================


class TestArtDirectorVideoGeneration:
    """ArtDirector 视频片段生成相关测试。"""

    def _make_state(
        self, config: dict, tmp_path: Path, video_enabled: bool
    ) -> dict:
        """构建最小 AgentState 用于 art_director_node。"""
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        return {
            "config": config,
            "workspace": str(ws),
            "budget_mode": False,
            "segments": [
                {"text": "剑气纵横三万里"},
                {"text": "一剑光寒十九洲"},
            ],
            "full_text": None,
            "suggested_style": "wuxia",
            "pipeline_plan": {"video_enabled": video_enabled},
            "decisions": [],
        }

    @patch("src.agents.art_director.ImageGenTool")
    @patch("src.agents.art_director.PromptGenTool")
    def test_art_director_video_disabled(
        self,
        MockPromptGen: MagicMock,
        MockImageGen: MagicMock,
        config_no_video: dict,
        tmp_path: Path,
    ) -> None:
        """video_enabled=False 时，结果不应包含 video_clips 键。"""
        # 配置 mock
        mock_prompt_inst = MockPromptGen.return_value
        mock_prompt_inst.run.return_value = "a vivid scene"

        mock_image_inst = MockImageGen.return_value
        mock_image_inst.run.return_value = None  # 图片工具无返回值

        state = self._make_state(config_no_video, tmp_path, video_enabled=False)

        # 为图片文件创建假文件（image_gen.run 的 side_effect）
        def fake_image_gen(prompt, out_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"fake-png")

        mock_image_inst.run.side_effect = fake_image_gen

        result = art_director_node(state)

        assert "video_clips" not in result
        assert "images" in result
        assert len(result["images"]) == 2

    @patch("src.agents.art_director.ImageGenTool")
    @patch("src.agents.art_director.PromptGenTool")
    def test_art_director_video_enabled(
        self,
        MockPromptGen: MagicMock,
        MockImageGen: MagicMock,
        videogen_config: dict,
        tmp_path: Path,
    ) -> None:
        """video_enabled=True + videogen 配置存在时，结果应包含 video_clips 列表。"""
        mock_prompt_inst = MockPromptGen.return_value
        mock_prompt_inst.run.return_value = "a vivid scene"
        mock_prompt_inst.run_video_prompt.return_value = "dynamic sword fight"

        mock_image_inst = MockImageGen.return_value

        def fake_image_gen(prompt, out_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"fake-png")

        mock_image_inst.run.side_effect = fake_image_gen

        state = self._make_state(videogen_config, tmp_path, video_enabled=True)

        # Mock VideoGenTool 的 run 和 close
        mock_video_tool = MagicMock()

        def fake_video_run(prompt, out_path, image_path=None):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"fake-mp4")
            return out_path

        mock_video_tool.run.side_effect = fake_video_run

        with patch.object(
            ArtDirectorAgent, "video_gen", new_callable=PropertyMock, return_value=mock_video_tool
        ):
            result = art_director_node(state)

        assert "video_clips" in result
        assert len(result["video_clips"]) == 2
        for clip in result["video_clips"]:
            assert clip.endswith(".mp4")
        mock_video_tool.close.assert_called_once()

    @patch("src.agents.art_director.ImageGenTool")
    @patch("src.agents.art_director.PromptGenTool")
    def test_art_director_video_uses_image_as_first_frame(
        self,
        MockPromptGen: MagicMock,
        MockImageGen: MagicMock,
        videogen_config: dict,
        tmp_path: Path,
    ) -> None:
        """use_image_as_first_frame=True 时，应将生成的图片路径传给视频生成。"""
        mock_prompt_inst = MockPromptGen.return_value
        mock_prompt_inst.run.return_value = "scene prompt"
        mock_prompt_inst.run_video_prompt.return_value = "video prompt"

        mock_image_inst = MockImageGen.return_value
        generated_images: list[Path] = []

        def fake_image_gen(prompt, out_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"fake-png")
            generated_images.append(out_path)

        mock_image_inst.run.side_effect = fake_image_gen

        state = self._make_state(videogen_config, tmp_path, video_enabled=True)
        # 只用一个段落简化断言
        state["segments"] = [{"text": "剑气纵横三万里"}]

        mock_video_tool = MagicMock()

        def fake_video_run(prompt, out_path, image_path=None):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"fake-mp4")
            return out_path

        mock_video_tool.run.side_effect = fake_video_run

        with patch.object(
            ArtDirectorAgent, "video_gen", new_callable=PropertyMock, return_value=mock_video_tool
        ):
            result = art_director_node(state)

        # 验证 video_gen.run 被调用时传入了图片路径
        assert mock_video_tool.run.call_count == 1
        call_args = mock_video_tool.run.call_args
        # image_path 参数应该是生成的图片路径
        passed_image_path = call_args[1].get("image_path") if call_args[1] else call_args[0][2] if len(call_args[0]) > 2 else None
        assert passed_image_path is not None
        assert str(passed_image_path) == str(generated_images[0])
