"""Pipeline 防御性测试 - 覆盖空配置、资源清理、断点恢复、畸形输入等边界。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import yaml

# ---------------------------------------------------------------------------
# 被测模块
# ---------------------------------------------------------------------------
from src.config_manager import load_config
from src.checkpoint import Checkpoint

# Pipeline 需要延迟导入以避免 mock 问题，在各测试中 patch 依赖后再用


# ===========================================================================
# 1. Empty / Invalid YAML config (Bug #1 fix verification)
# ===========================================================================

class TestLoadConfigInvalidYAML:
    """验证 load_config 对空文件/非字典 YAML 的处理。"""

    def test_empty_yaml_raises_value_error(self, tmp_path: Path):
        """空 YAML 文件应抛出 ValueError（而非 TypeError）。"""
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match="配置文件内容无效"):
            load_config(cfg_file)

    def test_yaml_with_only_comment_raises_value_error(self, tmp_path: Path):
        """YAML 仅含注释 → safe_load 返回 None → ValueError。"""
        cfg_file = tmp_path / "comment_only.yaml"
        cfg_file.write_text("# This is just a comment\n# Nothing else\n", encoding="utf-8")

        with pytest.raises(ValueError, match="配置文件内容无效.*NoneType"):
            load_config(cfg_file)

    def test_yaml_with_list_raises_value_error(self, tmp_path: Path):
        """YAML 顶层是列表而非字典 → ValueError。"""
        cfg_file = tmp_path / "list.yaml"
        cfg_file.write_text("- item1\n- item2\n", encoding="utf-8")

        with pytest.raises(ValueError, match="配置文件内容无效.*list"):
            load_config(cfg_file)

    def test_yaml_with_none_required_sections_raises(self, tmp_path: Path):
        """YAML 是字典但缺少所有必须字段 → ValueError。"""
        cfg_file = tmp_path / "partial.yaml"
        cfg_file.write_text(
            yaml.dump({"segmenter": None, "promptgen": None}),
            encoding="utf-8",
        )
        # 缺少 imagegen / tts / video → _validate raises
        with pytest.raises(ValueError, match="配置缺少必要字段"):
            load_config(cfg_file)

    def test_nonexistent_config_raises_file_not_found(self, tmp_path: Path):
        """不存在的配置文件 → FileNotFoundError。"""
        with pytest.raises(FileNotFoundError, match="配置文件不存在"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_yaml_scalar_string_raises_value_error(self, tmp_path: Path):
        """YAML 顶层是纯字符串 → ValueError。"""
        cfg_file = tmp_path / "scalar.yaml"
        cfg_file.write_text("just a string\n", encoding="utf-8")

        with pytest.raises(ValueError, match="配置文件内容无效.*str"):
            load_config(cfg_file)

    def test_yaml_with_integer_raises_value_error(self, tmp_path: Path):
        """YAML 顶层是整数 → ValueError。"""
        cfg_file = tmp_path / "integer.yaml"
        cfg_file.write_text("42\n", encoding="utf-8")

        with pytest.raises(ValueError, match="配置文件内容无效.*int"):
            load_config(cfg_file)


# ===========================================================================
# 2. Audio / SRT mismatch on resume (Bug #3 fix verification)
# ===========================================================================

class TestLoadAudioSrtMismatch:
    """验证 _load_audio_srt 在文件数不匹配时的错误消息。"""

    def _make_pipeline(self, tmp_path: Path) -> "Pipeline":
        """创建一个最小 Pipeline 实例（只需要 audio_dir / srt_dir）。"""
        from src.pipeline import Pipeline

        # 创建输入文件
        input_file = tmp_path / "test.txt"
        input_file.write_text("测试内容", encoding="utf-8")

        # 创建最小有效配置
        cfg = _make_minimal_config()
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        p = Pipeline(input_file=input_file, config_path=cfg_file,
                     workspace=tmp_path / "ws")
        return p

    def test_audio_more_than_srt_raises_runtime_error(self, tmp_path: Path):
        """10 个音频、8 个字幕 → RuntimeError 带明确数字。"""
        p = self._make_pipeline(tmp_path)
        for i in range(10):
            (p.audio_dir / f"{i:04d}.mp3").write_bytes(b"fake")
        for i in range(8):
            (p.srt_dir / f"{i:04d}.srt").write_text("fake", encoding="utf-8")

        with pytest.raises(RuntimeError, match=r"音频文件数 \(10\) 与字幕文件数 \(8\)"):
            p._load_audio_srt()

    def test_zero_audio_five_srt_raises_runtime_error(self, tmp_path: Path):
        """0 个音频、5 个字幕 → RuntimeError。"""
        p = self._make_pipeline(tmp_path)
        for i in range(5):
            (p.srt_dir / f"{i:04d}.srt").write_text("fake", encoding="utf-8")

        with pytest.raises(RuntimeError, match=r"音频文件数 \(0\) 与字幕文件数 \(5\)"):
            p._load_audio_srt()

    def test_srt_more_than_audio_raises_runtime_error(self, tmp_path: Path):
        """3 个音频、7 个字幕 → RuntimeError。"""
        p = self._make_pipeline(tmp_path)
        for i in range(3):
            (p.audio_dir / f"{i:04d}.mp3").write_bytes(b"fake")
        for i in range(7):
            (p.srt_dir / f"{i:04d}.srt").write_text("fake", encoding="utf-8")

        with pytest.raises(RuntimeError, match=r"音频文件数 \(3\) 与字幕文件数 \(7\)"):
            p._load_audio_srt()

    def test_matching_counts_succeeds(self, tmp_path: Path):
        """数量一致时正常返回。"""
        p = self._make_pipeline(tmp_path)
        for i in range(5):
            (p.audio_dir / f"{i:04d}.mp3").write_bytes(b"fake")
            (p.srt_dir / f"{i:04d}.srt").write_text("fake", encoding="utf-8")

        result = p._load_audio_srt()
        assert len(result) == 5
        for item in result:
            assert "audio" in item
            assert "srt" in item

    def test_both_empty_returns_empty_list(self, tmp_path: Path):
        """两边都是 0 个文件 → 返回空列表（不报错）。"""
        p = self._make_pipeline(tmp_path)
        result = p._load_audio_srt()
        assert result == []


# ===========================================================================
# 3. Video generator resource cleanup (Bug #2 fix verification)
# ===========================================================================

class TestVideoGenResourceCleanup:
    """验证 _stage_videogen 中 gen.close() 在异常时仍被调用。"""

    def test_close_called_on_generate_exception(self, tmp_path: Path):
        """gen.generate() 抛异常 → gen.close() 仍被调用。"""
        from src.pipeline import Pipeline

        input_file = tmp_path / "test.txt"
        input_file.write_text("测试内容", encoding="utf-8")

        cfg = _make_minimal_config()
        cfg["videogen"] = {"backend": "kling", "use_image_as_first_frame": False}
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        p = Pipeline(input_file=input_file, config_path=cfg_file,
                     workspace=tmp_path / "ws")

        mock_gen = MagicMock()
        mock_gen.generate.side_effect = RuntimeError("GPU out of memory")

        mock_prompt_gen = MagicMock()
        mock_prompt_gen.generate_video_prompt.return_value = "test prompt"

        segments = [{"text": "第一段"}, {"text": "第二段"}]
        images = [tmp_path / "0.png", tmp_path / "1.png"]

        with patch("src.pipeline.create_video_generator", return_value=mock_gen), \
             patch("src.pipeline.PromptGenerator", return_value=mock_prompt_gen):
            with pytest.raises(RuntimeError, match="GPU out of memory"):
                p._stage_videogen(segments, images)

        # 关键断言: close() 即使异常也必须被调用
        mock_gen.close.assert_called_once()

    def test_close_called_on_successful_run(self, tmp_path: Path):
        """gen.generate() 成功 → gen.close() 仍然被调用。"""
        from src.pipeline import Pipeline

        input_file = tmp_path / "test.txt"
        input_file.write_text("测试内容", encoding="utf-8")

        cfg = _make_minimal_config()
        cfg["videogen"] = {"backend": "kling", "use_image_as_first_frame": False}
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        p = Pipeline(input_file=input_file, config_path=cfg_file,
                     workspace=tmp_path / "ws")

        # 模拟生成结果
        fake_video = tmp_path / "fake_video.mp4"
        fake_video.write_bytes(b"fake video data")

        mock_result = MagicMock()
        mock_result.video_path = fake_video

        mock_gen = MagicMock()
        mock_gen.generate.return_value = mock_result

        mock_prompt_gen = MagicMock()
        mock_prompt_gen.generate_video_prompt.return_value = "test prompt"

        segments = [{"text": "第一段"}]
        images = [tmp_path / "0.png"]

        with patch("src.pipeline.create_video_generator", return_value=mock_gen), \
             patch("src.pipeline.PromptGenerator", return_value=mock_prompt_gen):
            result = p._stage_videogen(segments, images)

        mock_gen.close.assert_called_once()
        assert len(result) == 1

    def test_close_called_when_exception_in_middle(self, tmp_path: Path):
        """多段生成中第二段失败 → close() 仍被调用，第一段结果已写入。"""
        from src.pipeline import Pipeline

        input_file = tmp_path / "test.txt"
        input_file.write_text("测试内容", encoding="utf-8")

        cfg = _make_minimal_config()
        cfg["videogen"] = {"backend": "kling", "use_image_as_first_frame": False}
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        p = Pipeline(input_file=input_file, config_path=cfg_file,
                     workspace=tmp_path / "ws")

        fake_video = tmp_path / "fake_video.mp4"
        fake_video.write_bytes(b"fake video data")
        mock_result = MagicMock()
        mock_result.video_path = fake_video

        mock_gen = MagicMock()
        # 第一段成功，第二段失败
        mock_gen.generate.side_effect = [mock_result, RuntimeError("API timeout")]

        mock_prompt_gen = MagicMock()
        mock_prompt_gen.generate_video_prompt.return_value = "test prompt"

        segments = [{"text": "第一段"}, {"text": "第二段"}]
        images = [tmp_path / "0.png", tmp_path / "1.png"]

        with patch("src.pipeline.create_video_generator", return_value=mock_gen), \
             patch("src.pipeline.PromptGenerator", return_value=mock_prompt_gen):
            with pytest.raises(RuntimeError, match="API timeout"):
                p._stage_videogen(segments, images)

        mock_gen.close.assert_called_once()
        # 第一段的视频文件应已被写入
        assert (p.video_clip_dir / "0000.mp4").exists()


# ===========================================================================
# 4. Checkpoint robustness
# ===========================================================================

class TestCheckpointRobustness:
    """断点续传的鲁棒性测试。"""

    def test_load_corrupted_json_raises(self, tmp_path: Path):
        """损坏的 JSON 文件 → json.JSONDecodeError。"""
        ckpt_file = tmp_path / "checkpoint.json"
        ckpt_file.write_text("{this is not valid json!!", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            Checkpoint(tmp_path)

    def test_load_valid_but_empty_json_object(self, tmp_path: Path):
        """空 JSON 对象 {} → 缺少 stages 键 → is_done 抛 KeyError。

        注意: Checkpoint._load() 只在文件不存在时初始化默认结构，
        已存在的文件会原样加载。缺少 "stages" 键会导致 KeyError。
        """
        ckpt_file = tmp_path / "checkpoint.json"
        ckpt_file.write_text("{}", encoding="utf-8")

        ckpt = Checkpoint(tmp_path)
        with pytest.raises(KeyError, match="stages"):
            ckpt.is_done("segment")
        # total_segments 使用 .get() 所以安全
        assert ckpt.total_segments() == 0

    def test_load_json_missing_segments_field(self, tmp_path: Path):
        """JSON 有 stages 但没有 segments → total_segments 返回 0。"""
        ckpt_file = tmp_path / "checkpoint.json"
        ckpt_file.write_text(
            json.dumps({"stages": {"segment": {"done": True}}}),
            encoding="utf-8",
        )

        ckpt = Checkpoint(tmp_path)
        assert ckpt.is_done("segment") is True
        assert ckpt.total_segments() == 0

    def test_load_json_missing_stages_field(self, tmp_path: Path):
        """JSON 有 segments 但没有 stages → is_done 抛 KeyError。

        Checkpoint.is_done 使用 self.data["stages"] 硬引用，
        缺少该键时抛出 KeyError。total_segments 使用 .get() 安全。
        """
        ckpt_file = tmp_path / "checkpoint.json"
        ckpt_file.write_text(
            json.dumps({"segments": [{"text": "a"}]}),
            encoding="utf-8",
        )

        ckpt = Checkpoint(tmp_path)
        with pytest.raises(KeyError, match="stages"):
            ckpt.is_done("segment")
        assert ckpt.total_segments() == 1

    def test_rapid_sequential_saves(self, tmp_path: Path):
        """快速连续保存不应损坏文件（模拟并发写入场景）。"""
        ckpt = Checkpoint(tmp_path)

        for i in range(50):
            ckpt.update_segment(i, "text", f"/path/to/{i:04d}.txt")

        # 重新加载确认完整性
        ckpt2 = Checkpoint(tmp_path)
        assert ckpt2.total_segments() == 50
        assert ckpt2.get_segment_status(0) == {"text": "/path/to/0000.txt"}
        assert ckpt2.get_segment_status(49) == {"text": "/path/to/0049.txt"}

    def test_mark_done_then_reload(self, tmp_path: Path):
        """mark_done 后重新加载，状态应持久化。"""
        ckpt = Checkpoint(tmp_path)
        ckpt.mark_done("segment", {"count": 10})
        ckpt.mark_done("prompt")

        ckpt2 = Checkpoint(tmp_path)
        assert ckpt2.is_done("segment") is True
        assert ckpt2.is_done("prompt") is True
        assert ckpt2.is_done("image") is False
        assert ckpt2.data["stages"]["segment"]["count"] == 10

    def test_update_segment_extends_list(self, tmp_path: Path):
        """update_segment(5, ...) 应自动扩展 segments 列表到 6 个元素。"""
        ckpt = Checkpoint(tmp_path)
        ckpt.update_segment(5, "image", "/path/to/img.png")

        assert len(ckpt.data["segments"]) == 6
        assert ckpt.data["segments"][5] == {"image": "/path/to/img.png"}
        # 中间的空槽应是空字典
        for i in range(5):
            assert ckpt.data["segments"][i] == {}

    def test_get_segment_status_out_of_range(self, tmp_path: Path):
        """请求不存在的 segment index → 返回空字典。"""
        ckpt = Checkpoint(tmp_path)
        assert ckpt.get_segment_status(999) == {}

    def test_no_checkpoint_file_fresh_start(self, tmp_path: Path):
        """不存在 checkpoint.json → 全新状态。"""
        ckpt = Checkpoint(tmp_path)
        assert ckpt.data == {"stages": {}, "segments": []}
        assert ckpt.is_done("segment") is False

    def test_atomic_write_no_partial_file_on_error(self, tmp_path: Path):
        """模拟写入失败时不留下损坏的 checkpoint 文件。"""
        ckpt = Checkpoint(tmp_path)
        ckpt.mark_done("segment")

        # 现在模拟 tmp.write_text 失败
        original_write_text = Path.write_text

        def failing_write(self_path, *args, **kwargs):
            if str(self_path).endswith(".tmp"):
                raise OSError("Disk full")
            return original_write_text(self_path, *args, **kwargs)

        with patch.object(Path, "write_text", failing_write):
            with pytest.raises(OSError, match="Disk full"):
                ckpt.mark_done("prompt")

        # 原始 checkpoint 应保持不变（segment done, prompt 未写入）
        ckpt2 = Checkpoint(tmp_path)
        assert ckpt2.is_done("segment") is True
        assert ckpt2.is_done("prompt") is False


# ===========================================================================
# 5. Pipeline with missing / malformed input
# ===========================================================================

class TestPipelineMalformedInput:
    """Pipeline 构造函数对输入文件异常的处理。"""

    def test_nonexistent_input_file(self, tmp_path: Path):
        """不存在的输入文件 → FileNotFoundError。"""
        from src.pipeline import Pipeline

        cfg = _make_minimal_config()
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        with pytest.raises(FileNotFoundError, match="输入文件不存在"):
            Pipeline(input_file=tmp_path / "no_such_file.txt",
                     config_path=cfg_file, workspace=tmp_path / "ws")

    def test_empty_input_file_segment_produces_no_output(self, tmp_path: Path):
        """空输入文件 → 分段阶段应产生空列表或适当处理。"""
        from src.pipeline import Pipeline

        input_file = tmp_path / "empty.txt"
        input_file.write_text("", encoding="utf-8")

        cfg = _make_minimal_config()
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        p = Pipeline(input_file=input_file, config_path=cfg_file,
                     workspace=tmp_path / "ws")

        # 使用 mock segmenter 返回空列表
        mock_segmenter = MagicMock()
        mock_segmenter.segment.return_value = []

        with patch("src.pipeline.create_segmenter", return_value=mock_segmenter):
            segments = p._stage_segment()

        assert segments == []
        mock_segmenter.segment.assert_called_once_with("")

    def test_binary_input_file_encoding_error(self, tmp_path: Path):
        """二进制文件 → read_text 可能抛 UnicodeDecodeError。"""
        from src.pipeline import Pipeline

        input_file = tmp_path / "binary.txt"
        input_file.write_bytes(b"\x80\x81\x82\xff\xfe\x00\x01")

        cfg = _make_minimal_config()
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        p = Pipeline(input_file=input_file, config_path=cfg_file,
                     workspace=tmp_path / "ws")

        # _stage_segment 调用 read_text(encoding="utf-8") → UnicodeDecodeError
        with pytest.raises(UnicodeDecodeError):
            p._stage_segment()

    def test_pipeline_creates_workspace_directories(self, tmp_path: Path):
        """Pipeline 初始化时应自动创建所有子目录。"""
        from src.pipeline import Pipeline

        input_file = tmp_path / "test.txt"
        input_file.write_text("测试", encoding="utf-8")

        cfg = _make_minimal_config()
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        ws = tmp_path / "new_workspace"
        p = Pipeline(input_file=input_file, config_path=cfg_file,
                     workspace=ws)

        expected_dirs = [
            ws / "test" / "segments",
            ws / "test" / "images",
            ws / "test" / "audio",
            ws / "test" / "subtitles",
            ws / "test" / "videos",
        ]
        for d in expected_dirs:
            assert d.is_dir(), f"目录未创建: {d}"

    def test_pipeline_with_config_override(self, tmp_path: Path):
        """config 参数应合并覆盖文件配置。"""
        from src.pipeline import Pipeline

        input_file = tmp_path / "test.txt"
        input_file.write_text("测试", encoding="utf-8")

        cfg = _make_minimal_config()
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        override = {"tts": {"voice": "zh-CN-XiaoyiNeural"}}
        p = Pipeline(input_file=input_file, config_path=cfg_file,
                     workspace=tmp_path / "ws", config=override)

        assert p.cfg["tts"]["voice"] == "zh-CN-XiaoyiNeural"
        # 原始字段应保留
        assert "segmenter" in p.cfg

    def test_pipeline_videogen_not_enabled_by_default(self, tmp_path: Path):
        """默认配置无 videogen → _videogen_enabled = False。"""
        from src.pipeline import Pipeline

        input_file = tmp_path / "test.txt"
        input_file.write_text("测试", encoding="utf-8")

        cfg = _make_minimal_config()
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        p = Pipeline(input_file=input_file, config_path=cfg_file,
                     workspace=tmp_path / "ws")

        assert p._videogen_enabled is False

    def test_pipeline_videogen_enabled_with_backend(self, tmp_path: Path):
        """配置有 videogen.backend → _videogen_enabled = True。"""
        from src.pipeline import Pipeline

        input_file = tmp_path / "test.txt"
        input_file.write_text("测试", encoding="utf-8")

        cfg = _make_minimal_config()
        cfg["videogen"] = {"backend": "kling"}
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        p = Pipeline(input_file=input_file, config_path=cfg_file,
                     workspace=tmp_path / "ws")

        assert p._videogen_enabled is True

    def test_pipeline_videogen_empty_backend_not_enabled(self, tmp_path: Path):
        """videogen.backend 为空字符串 → _videogen_enabled = False。"""
        from src.pipeline import Pipeline

        input_file = tmp_path / "test.txt"
        input_file.write_text("测试", encoding="utf-8")

        cfg = _make_minimal_config()
        cfg["videogen"] = {"backend": ""}
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        p = Pipeline(input_file=input_file, config_path=cfg_file,
                     workspace=tmp_path / "ws")

        assert p._videogen_enabled is False


# ===========================================================================
# Helpers
# ===========================================================================

def _make_minimal_config() -> dict:
    """构造通过 _validate 的最小合法配置。"""
    return {
        "segmenter": {"method": "simple", "max_chars": 200},
        "promptgen": {},
        "imagegen": {"backend": "siliconflow"},
        "tts": {"voice": "zh-CN-XiaoxiaoNeural"},
        "video": {"resolution": [1024, 1792]},
    }
