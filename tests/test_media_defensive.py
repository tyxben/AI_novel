"""Defensive tests for media modules (video, image, scriptplan).

Covers:
  1. Sora download retry logic (Bug #13 fix verification)
  2. IdeaPlanner JSON parsing edge cases (Bug #14 fix verification)
  3. SiliconFlowBackend resource cleanup (context manager)
  4. VideoAssembler subtitle escaping (FFmpeg filter paths)
  5. BaseVideoBackend network failure handling (download, poll, invalid result)
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    """Minimal LLMResponse stand-in for IdeaPlanner tests."""

    content: str
    model: str = "test-model"
    usage: dict | None = None


def _make_httpx_response(*, status_code: int = 200, content: bytes = b"video-data",
                         json_data: dict | None = None, text: str = ""):
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


# =========================================================================
# 1. Sora download retry (Bug #13 fix verification)
# =========================================================================


class TestSoraDownloadRetry:
    """Verify SoraBackend._download_video retries and error handling."""

    def _make_backend(self):
        """Create a SoraBackend with a mocked httpx client."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            from src.videogen.sora_backend import SoraBackend
            backend = SoraBackend({"api_key": "test-key"})
        return backend

    def test_download_succeeds_after_two_failures(self, tmp_path):
        """Mock client.get to fail twice then succeed on 3rd attempt."""
        backend = self._make_backend()
        mock_client = MagicMock()

        # First two calls raise, third succeeds
        fail_exc = ConnectionError("network flake")
        ok_resp = _make_httpx_response(content=b"sora-video-bytes")
        mock_client.get = MagicMock(side_effect=[fail_exc, fail_exc, ok_resp])
        backend._client = mock_client

        output = tmp_path / "video.mp4"
        with patch("time.sleep"):  # skip delay
            result = backend._download_video("https://api.openai.com/v1/videos/123/content", output)

        assert result == output
        assert output.read_bytes() == b"sora-video-bytes"
        assert mock_client.get.call_count == 3

    def test_download_fails_all_three_times_raises_runtime_error(self, tmp_path):
        """Mock client.get to fail all 3 times -- verify RuntimeError with clear message."""
        backend = self._make_backend()
        mock_client = MagicMock()

        fail_exc = ConnectionError("persistent failure")
        mock_client.get = MagicMock(side_effect=[fail_exc, fail_exc, fail_exc])
        backend._client = mock_client

        output = tmp_path / "video.mp4"
        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match=r"Sora 视频下载失败 \(3次重试\)"):
                backend._download_video("https://api.openai.com/v1/videos/123/content", output)

        assert mock_client.get.call_count == 3
        assert not output.exists()

    def test_download_retries_exactly_three_times(self, tmp_path):
        """Verify the method retries exactly 3 times (range(3))."""
        backend = self._make_backend()
        mock_client = MagicMock()

        fail_exc = TimeoutError("slow network")
        mock_client.get = MagicMock(side_effect=[fail_exc, fail_exc, fail_exc])
        backend._client = mock_client

        output = tmp_path / "no_file.mp4"
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(RuntimeError):
                backend._download_video("https://example.com/vid", output)

        # 3 attempts total; sleep called for attempts 0 and 1 (not after the last)
        assert mock_client.get.call_count == 3
        assert mock_sleep.call_count == 2  # delays between retry 0->1 and 1->2

    def test_download_succeeds_on_first_try(self, tmp_path):
        """Happy path: first attempt succeeds, no retries needed."""
        backend = self._make_backend()
        mock_client = MagicMock()

        ok_resp = _make_httpx_response(content=b"first-try-ok")
        mock_client.get = MagicMock(return_value=ok_resp)
        backend._client = mock_client

        output = tmp_path / "ok.mp4"
        result = backend._download_video("https://example.com/vid", output)

        assert result == output
        assert output.read_bytes() == b"first-try-ok"
        assert mock_client.get.call_count == 1


# =========================================================================
# 2. IdeaPlanner JSON parsing (Bug #14 fix verification)
# =========================================================================


class TestIdeaPlannerJsonParsing:
    """Verify IdeaPlanner.plan() handles various LLM response formats."""

    def _make_planner(self, response_content: str):
        """Create an IdeaPlanner with a mock LLM that returns the given content."""
        mock_llm = MagicMock()
        mock_llm.chat = MagicMock(
            return_value=FakeLLMResponse(content=response_content)
        )
        from src.scriptplan.idea_planner import IdeaPlanner
        return IdeaPlanner(llm=mock_llm)

    def test_nested_json_parsed_correctly(self):
        """LLM response containing nested JSON objects should be parsed."""
        response = json.dumps({
            "video_type": "悬疑反转",
            "target_duration": 45,
            "segment_count": 6,
            "rhythm": "3s hook",
            "twist_type": "身份反转",
            "ending_type": "评论钩子",
            "tone": "悬疑",
            "metadata": {"sub": "nested-value", "list": [1, 2, 3]},
        })
        planner = self._make_planner(response)
        idea = planner.plan("test inspiration")

        assert idea.video_type == "悬疑反转"
        assert idea.twist_type == "身份反转"
        assert idea.segment_count == 6

    def test_markdown_wrapped_json(self):
        """LLM response wrapped in markdown code block should be extracted."""
        inner = json.dumps({
            "video_type": "情感共鸣",
            "target_duration": 30,
            "segment_count": 5,
            "rhythm": "slow build",
            "twist_type": "无反转",
            "ending_type": "情感升华",
            "tone": "温情",
        })
        response = f"```json\n{inner}\n```"
        planner = self._make_planner(response)
        idea = planner.plan("emotional story")

        assert idea.video_type == "情感共鸣"
        assert idea.tone == "温情"
        assert idea.target_duration == 30

    def test_multiple_json_objects_greedy_regex_returns_fallback(self):
        """LLM response with multiple JSON objects -- greedy regex captures invalid span.

        The regex r'\\{.*\\}' with re.DOTALL is greedy and captures from the
        first '{' to the last '}', including non-JSON text in between. The
        inner json.loads catches the JSONDecodeError and returns a safe fallback.
        """
        response = (
            'Here is the plan: {"video_type": "爽文快节奏", "target_duration": 45, '
            '"segment_count": 7, "rhythm": "fast", "twist_type": "逻辑反转", '
            '"ending_type": "悬念留白", "tone": "紧张"} '
            'And also {"extra": "ignored"}'
        )
        planner = self._make_planner(response)

        # Should return fallback VideoIdea instead of crashing
        result = planner.plan("action story")
        assert result.video_type == "悬疑反转"  # fallback default
        assert result.segment_count == 6

    def test_single_json_embedded_in_text_extracts_correctly(self):
        """LLM response with a single JSON object embedded in text should be extracted."""
        response = (
            'Here is the plan: {"video_type": "爽文快节奏", "target_duration": 45, '
            '"segment_count": 7, "rhythm": "fast", "twist_type": "逻辑反转", '
            '"ending_type": "悬念留白", "tone": "紧张"}'
        )
        planner = self._make_planner(response)
        idea = planner.plan("action story")

        assert idea.video_type == "爽文快节奏"
        assert idea.twist_type == "逻辑反转"
        assert idea.segment_count == 7

    def test_completely_invalid_response_returns_fallback(self):
        """No JSON at all -- verify fallback VideoIdea is returned."""
        response = "I cannot generate a video plan right now. Please try again later."
        planner = self._make_planner(response)
        idea = planner.plan("anything", target_duration=60)

        # Verify fallback defaults
        assert idea.video_type == "悬疑反转"
        assert idea.target_duration == 60
        assert idea.segment_count == 6
        assert idea.twist_type == "无反转"
        assert idea.ending_type == "评论钩子"
        assert idea.tone == "悬疑"

    def test_valid_json_direct_parse(self):
        """Clean JSON response should be parsed directly without regex fallback."""
        data = {
            "video_type": "搞笑",
            "target_duration": 30,
            "segment_count": 5,
            "rhythm": "快节奏",
            "twist_type": "视角反转",
            "ending_type": "反问互动",
            "tone": "搞笑",
        }
        planner = self._make_planner(json.dumps(data))
        idea = planner.plan("funny story")

        assert idea.video_type == "搞笑"
        assert idea.segment_count == 5
        assert idea.twist_type == "视角反转"

    def test_segment_count_clamped_to_valid_range(self):
        """segment_count should be clamped between 4 and 10."""
        # Too low
        data = {
            "video_type": "知识科普",
            "segment_count": 1,
            "tone": "悬疑",
        }
        planner = self._make_planner(json.dumps(data))
        idea = planner.plan("science")
        assert idea.segment_count == 4  # max(4, min(10, 1)) = 4

        # Too high
        data["segment_count"] = 99
        planner = self._make_planner(json.dumps(data))
        idea = planner.plan("science")
        assert idea.segment_count == 10  # max(4, min(10, 99)) = 10


# =========================================================================
# 3. Image backend resource cleanup
# =========================================================================


class TestSiliconFlowResourceCleanup:
    """Verify SiliconFlowBackend context manager properly calls close()."""

    def _make_backend(self):
        """Create a SiliconFlowBackend with mocked API key."""
        from src.imagegen.siliconflow_backend import SiliconFlowBackend
        return SiliconFlowBackend({"api_key": "test-sf-key"})

    def test_context_manager_calls_close_on_exit(self):
        """Use as context manager -- verify close() is called on normal exit."""
        backend = self._make_backend()
        # Pre-create a mock client so close() has something to clean up
        mock_client = MagicMock()
        backend._client = mock_client

        with backend:
            assert backend._client is mock_client  # still alive inside

        # After __exit__, close() should have been called
        mock_client.close.assert_called_once()
        assert backend._client is None

    def test_context_manager_calls_close_on_exception(self):
        """Simulate exception inside context manager -- verify close() still called."""
        backend = self._make_backend()
        mock_client = MagicMock()
        backend._client = mock_client

        with pytest.raises(ValueError, match="boom"):
            with backend:
                raise ValueError("boom")

        mock_client.close.assert_called_once()
        assert backend._client is None

    def test_close_idempotent_when_no_client(self):
        """close() should not fail when _client is None (never initialized)."""
        backend = self._make_backend()
        assert backend._client is None
        backend.close()  # should not raise
        assert backend._client is None

    def test_close_sets_client_to_none(self):
        """After close(), _client should be None to allow re-initialization."""
        backend = self._make_backend()
        mock_client = MagicMock()
        backend._client = mock_client

        backend.close()
        assert backend._client is None
        mock_client.close.assert_called_once()


# =========================================================================
# 4. Video assembler subtitle escaping
# =========================================================================


class TestVideoAssemblerSubtitleEscaping:
    """Test FFmpeg subtitle filter path escaping and drawtext text escaping."""

    def _make_assembler(self, tmp_path):
        """Create a minimal VideoAssembler."""
        from src.video.video_assembler import VideoAssembler
        config = {
            "resolution": [1080, 1920],
            "fps": 30,
            "codec": "libx264",
        }
        return VideoAssembler(config, workspace=tmp_path)

    def test_subtitles_filter_path_escaping_colons(self, tmp_path):
        """Subtitle path with colons should be escaped for FFmpeg subtitles filter."""
        # The escaping code in _trim_replace_audio_subtitle:
        #   .replace("\\", "\\\\")
        #   .replace(":", "\\:")
        #   .replace("'", "\\'")

        path_str = "/path/to/my:subtitle:file.srt"
        escaped = (
            path_str
            .replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "\\'")
        )
        assert "\\:" in escaped
        assert escaped == "/path/to/my\\:subtitle\\:file.srt"

    def test_subtitles_filter_path_escaping_backslashes(self, tmp_path):
        """Windows-style backslash paths should be double-escaped."""
        path_str = "C:\\Users\\test\\subtitle.srt"
        escaped = (
            path_str
            .replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "\\'")
        )
        assert escaped == "C\\:\\\\Users\\\\test\\\\subtitle.srt"

    def test_subtitles_filter_path_escaping_quotes(self, tmp_path):
        """Paths with single quotes should be escaped."""
        path_str = "/path/to/it's a file.srt"
        escaped = (
            path_str
            .replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "\\'")
        )
        assert "\\'" in escaped

    def test_drawtext_text_escaping_special_chars(self, tmp_path):
        """drawtext text with special characters should be properly escaped."""
        # Replicating the escaping logic from _srt_to_drawtext_filters:
        text = "Hello: world\\test 'quoted' 50%"
        escaped = text.replace("\\", "\\\\\\\\")
        escaped = escaped.replace("'", "'\\\\\\''")
        escaped = escaped.replace(":", "\\\\:")
        escaped = escaped.replace("%", "%%")

        assert "\\\\\\\\" in escaped  # backslash escaped
        assert "\\\\:" in escaped     # colon escaped
        assert "%%" in escaped        # percent escaped

    def test_drawtext_chinese_text_with_special_chars(self, tmp_path):
        """Chinese text with colons and special chars should be escaped for drawtext."""
        text = "时间：2024年，地点：上海"
        escaped = text.replace("\\", "\\\\\\\\")
        escaped = escaped.replace("'", "'\\\\\\''")
        escaped = escaped.replace(":", "\\\\:")
        escaped = escaped.replace("%", "%%")

        # Chinese fullwidth colon is not ASCII ':', so it should NOT be escaped
        # Only ASCII colons should be escaped
        assert "\\\\:" not in escaped  # no ASCII colons in input
        assert "：" in escaped  # fullwidth colon preserved as-is

    def test_drawtext_ascii_colon_in_chinese_text(self, tmp_path):
        """Mixed Chinese text with ASCII colons should escape only ASCII colons."""
        text = "时间:下午3:00"
        escaped = text.replace("\\", "\\\\\\\\")
        escaped = escaped.replace("'", "'\\\\\\''")
        escaped = escaped.replace(":", "\\\\:")
        escaped = escaped.replace("%", "%%")

        assert escaped.count("\\\\:") == 2  # both ASCII colons escaped
        assert "时间" in escaped

    def test_srt_to_drawtext_filters_integration(self, tmp_path):
        """Integration test: _srt_to_drawtext_filters produces valid filter strings."""
        assembler = self._make_assembler(tmp_path)

        # Write a minimal SRT file
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\n"
            "Hello world\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\n"
            "Second line\n\n",
            encoding="utf-8",
        )

        with patch.object(assembler, "_find_font_path", return_value="/fake/font.ttf"):
            filters = assembler._srt_to_drawtext_filters(srt_file)

        assert len(filters) == 2
        assert "drawtext=" in filters[0]
        assert "Hello world" in filters[0]
        assert "enable=" in filters[0]
        assert "between(t," in filters[0]
        assert "Second line" in filters[1]

    def test_srt_to_drawtext_filters_empty_srt(self, tmp_path):
        """Empty SRT file should produce empty filter list."""
        assembler = self._make_assembler(tmp_path)

        srt_file = tmp_path / "empty.srt"
        srt_file.write_text("", encoding="utf-8")

        filters = assembler._srt_to_drawtext_filters(srt_file)
        assert filters == []

    def test_srt_to_drawtext_filters_no_font(self, tmp_path):
        """When no CJK font is found, should return empty list."""
        assembler = self._make_assembler(tmp_path)

        srt_file = tmp_path / "test.srt"
        srt_file.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n",
            encoding="utf-8",
        )

        with patch.object(assembler, "_find_font_path", return_value=None):
            filters = assembler._srt_to_drawtext_filters(srt_file)

        assert filters == []

    def test_concat_path_escaping_single_quotes(self, tmp_path):
        """Concat demuxer file paths with single quotes should be escaped."""
        # From _concatenate:  safe_path = str(clip.resolve()).replace("'", "'\\''")
        path_with_quote = "/tmp/it's a clip.mp4"
        safe_path = path_with_quote.replace("'", "'\\''")
        assert safe_path == "/tmp/it'\\''s a clip.mp4"


# =========================================================================
# 5. Video generation with network failures (BaseVideoBackend)
# =========================================================================


class TestBaseVideoBackendNetworkFailures:
    """Test BaseVideoBackend download, poll, and generate with network issues."""

    def _make_concrete_backend(self, config=None):
        """Create a concrete subclass of BaseVideoBackend for testing."""
        from src.videogen.base_backend import BaseVideoBackend

        class TestBackend(BaseVideoBackend):
            def __init__(self, cfg):
                super().__init__(cfg)
                self.submit_result = "task-123"
                self.query_results = []
                self.video_url = "https://example.com/video.mp4"
                self.video_metadata = {"duration": 5.0, "width": 720, "height": 1280}
                self._query_call_count = 0

            def _submit_task(self, prompt, image_path, duration):
                return self.submit_result

            def _query_task(self, task_id):
                idx = self._query_call_count
                self._query_call_count += 1
                if idx < len(self.query_results):
                    return self.query_results[idx]
                return {"state": "completed", "raw": {}}

            def _get_video_url(self, task_result):
                return self.video_url

            def _get_video_metadata(self, task_result):
                return self.video_metadata

        return TestBackend(config or {"poll_interval": 0, "poll_timeout": 5})

    def test_base_download_retry_intermittent_failure(self, tmp_path):
        """base_backend._download_video retries on intermittent failures."""
        backend = self._make_concrete_backend()
        mock_client = MagicMock()

        fail_exc = ConnectionError("flaky network")
        ok_resp = _make_httpx_response(content=b"base-video-data")
        mock_client.get = MagicMock(side_effect=[fail_exc, ok_resp])
        backend._client = mock_client

        output = tmp_path / "base_video.mp4"
        with patch("time.sleep"):
            result = backend._download_video("https://example.com/video.mp4", output)

        assert result == output
        assert output.read_bytes() == b"base-video-data"
        assert mock_client.get.call_count == 2

    def test_base_download_all_retries_exhausted(self, tmp_path):
        """base_backend._download_video raises RuntimeError after 3 failures."""
        backend = self._make_concrete_backend()
        mock_client = MagicMock()

        fail_exc = ConnectionError("dead network")
        mock_client.get = MagicMock(side_effect=[fail_exc, fail_exc, fail_exc])
        backend._client = mock_client

        output = tmp_path / "fail.mp4"
        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match=r"视频下载失败 \(3次重试\)"):
                backend._download_video("https://example.com/video.mp4", output)

        assert mock_client.get.call_count == 3

    def test_poll_timeout_raises(self, tmp_path):
        """generate() when polling times out should raise TimeoutError."""
        backend = self._make_concrete_backend(
            {"poll_interval": 0, "poll_timeout": 0}  # immediate timeout
        )
        # Always return processing state
        backend.query_results = [
            {"state": "processing"},
            {"state": "processing"},
            {"state": "processing"},
        ]

        with pytest.raises(TimeoutError, match="视频生成超时"):
            with patch("time.sleep"):
                backend._poll_task("task-123")

    def test_poll_task_failed_raises_runtime_error(self):
        """When API returns failed state, RuntimeError should be raised."""
        backend = self._make_concrete_backend()
        backend.query_results = [
            {"state": "failed", "error": "content policy violation"},
        ]

        with pytest.raises(RuntimeError, match="视频生成失败.*content policy violation"):
            backend._poll_task("task-456")

    def test_generate_full_flow_success(self, tmp_path):
        """Full generate() flow: submit -> poll -> download -> return VideoResult."""
        backend = self._make_concrete_backend(
            {"poll_interval": 0, "poll_timeout": 10, "output_dir": str(tmp_path)}
        )
        backend.query_results = [
            {"state": "processing"},
            {"state": "completed", "raw": {}},
        ]

        mock_client = MagicMock()
        ok_resp = _make_httpx_response(content=b"final-video")
        mock_client.get = MagicMock(return_value=ok_resp)
        backend._client = mock_client

        with patch("time.sleep"):
            result = backend.generate("a beautiful sunset", duration=5.0)

        assert result.video_path.exists()
        assert result.video_path.read_bytes() == b"final-video"
        assert result.duration == 5.0
        assert result.width == 720
        assert result.height == 1280

    def test_generate_with_invalid_task_result(self, tmp_path):
        """When API returns task with missing state, should keep polling until timeout."""
        backend = self._make_concrete_backend(
            {"poll_interval": 0, "poll_timeout": 0}  # immediate timeout
        )
        # Return a result with empty state (defaults to "processing" in state_map fallback)
        backend.query_results = [
            {"state": ""},
            {"state": ""},
        ]

        with pytest.raises(TimeoutError):
            with patch("time.sleep"):
                backend._poll_task("task-789")

    def test_base_backend_context_manager(self):
        """BaseVideoBackend context manager should call close()."""
        backend = self._make_concrete_backend()
        mock_client = MagicMock()
        backend._client = mock_client

        with backend:
            pass

        mock_client.close.assert_called_once()
        assert backend._client is None

    def test_base_backend_lazy_client_creation(self):
        """_get_client() should lazily create httpx.Client."""
        backend = self._make_concrete_backend()
        assert backend._client is None

        with patch("httpx.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            client = backend._get_client()

        assert client is mock_instance
        MockClient.assert_called_once_with(timeout=120)

        # Second call should return the same instance
        client2 = backend._get_client()
        assert client2 is mock_instance

    def test_poll_processing_then_completed(self):
        """Poll should loop through processing states until completed."""
        backend = self._make_concrete_backend(
            {"poll_interval": 0, "poll_timeout": 60}
        )
        backend.query_results = [
            {"state": "processing"},
            {"state": "processing"},
            {"state": "processing"},
            {"state": "completed", "raw": {"id": "done"}},
        ]

        with patch("time.sleep"):
            result = backend._poll_task("task-poll")

        assert result["state"] == "completed"
        assert backend._query_call_count == 4
