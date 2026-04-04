"""Defensive tests for LLM backends and TTS engine.

Covers:
1. Ollama SDK compatibility (dict vs dataclass response formats)
2. TTS event-loop safety (Bug #12 fix)
3. LLM error handling (rate limits, invalid JSON, empty responses)
4. LLM response parsing edge cases (whitespace, markdown-wrapped JSON)
"""

import asyncio
import concurrent.futures
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.llm.llm_client import LLMResponse


# ======================================================================
# 1. Ollama SDK compatibility (Bug #6 fix verification)
# ======================================================================


class TestOllamaSDKCompatibility:
    """Verify OllamaBackend handles both old dict and new dataclass responses."""

    def _make_backend(self):
        """Create an OllamaBackend with a mocked client."""
        with patch.dict("sys.modules", {"ollama": MagicMock(), "httpx": MagicMock()}):
            from src.llm.ollama_backend import OllamaBackend

            backend = OllamaBackend({"model": "test-model", "host": "http://localhost:11434"})
        return backend

    def test_response_as_plain_dict_old_sdk(self):
        """Old SDK returns a plain dict with nested message dict."""
        backend = self._make_backend()
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": "hello"},
            "prompt_eval_count": 10,
            "eval_count": 5,
            "done_reason": "stop",
        }
        backend._client = mock_client

        result = backend.chat([{"role": "user", "content": "hi"}])

        assert isinstance(result, LLMResponse)
        assert result.content == "hello"
        assert result.model == "test-model"
        assert result.usage is not None
        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 5
        assert result.usage["total_tokens"] == 15
        assert result.finish_reason == "stop"

    def test_response_as_dataclass_new_sdk(self):
        """New SDK (v0.2+) returns an object with attributes."""
        backend = self._make_backend()
        mock_client = MagicMock()

        # Build a dataclass-like response object
        msg_obj = SimpleNamespace(content="hello from new sdk")
        response_obj = SimpleNamespace(
            message=msg_obj,
            prompt_eval_count=20,
            eval_count=12,
            done_reason="stop",
        )
        mock_client.chat.return_value = response_obj
        backend._client = mock_client

        result = backend.chat([{"role": "user", "content": "hi"}])

        assert isinstance(result, LLMResponse)
        assert result.content == "hello from new sdk"
        assert result.model == "test-model"
        assert result.usage is not None
        assert result.usage["prompt_tokens"] == 20
        assert result.usage["completion_tokens"] == 12
        assert result.usage["total_tokens"] == 32
        assert result.finish_reason == "stop"

    def test_response_missing_optional_fields_dict(self):
        """Dict response with no usage info (prompt_eval_count missing)."""
        backend = self._make_backend()
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": "no usage info"},
            "done_reason": "stop",
        }
        backend._client = mock_client

        result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.content == "no usage info"
        assert result.usage is None
        assert result.finish_reason == "stop"

    def test_response_missing_optional_fields_dataclass(self):
        """Dataclass response with no usage info."""
        backend = self._make_backend()
        mock_client = MagicMock()

        msg_obj = SimpleNamespace(content="no usage dataclass")
        response_obj = SimpleNamespace(
            message=msg_obj,
            prompt_eval_count=None,
            eval_count=None,
            done_reason="length",
        )
        mock_client.chat.return_value = response_obj
        backend._client = mock_client

        result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.content == "no usage dataclass"
        assert result.usage is None
        assert result.finish_reason == "length"

    def test_response_empty_content_dict(self):
        """Dict response with empty content string."""
        backend = self._make_backend()
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": ""},
            "prompt_eval_count": 5,
            "eval_count": 0,
            "done_reason": "stop",
        }
        backend._client = mock_client

        result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.content == ""
        assert result.usage is not None

    def test_response_empty_content_dataclass(self):
        """Dataclass response with empty content."""
        backend = self._make_backend()
        mock_client = MagicMock()

        msg_obj = SimpleNamespace(content="")
        response_obj = SimpleNamespace(
            message=msg_obj,
            prompt_eval_count=3,
            eval_count=0,
            done_reason="stop",
        )
        mock_client.chat.return_value = response_obj
        backend._client = mock_client

        result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.content == ""

    def test_response_missing_message_key_dict(self):
        """Dict response missing the 'message' key entirely."""
        backend = self._make_backend()
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "done_reason": "stop",
        }
        backend._client = mock_client

        result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.content == ""

    def test_response_missing_message_attr_dataclass(self):
        """Dataclass response with message=None."""
        backend = self._make_backend()
        mock_client = MagicMock()

        response_obj = SimpleNamespace(
            message=None,
            prompt_eval_count=None,
            eval_count=None,
            done_reason=None,
        )
        mock_client.chat.return_value = response_obj
        backend._client = mock_client

        result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.content == ""

    def test_ollama_api_failure_raises_runtime_error(self):
        """Ollama client raising an exception is wrapped in RuntimeError."""
        backend = self._make_backend()
        mock_client = MagicMock()
        mock_client.chat.side_effect = ConnectionError("Connection refused")
        backend._client = mock_client

        with pytest.raises(RuntimeError, match="Ollama API 调用失败"):
            backend.chat([{"role": "user", "content": "hi"}])

    def test_json_mode_passes_format(self):
        """json_mode=True should pass format='json' to the client."""
        backend = self._make_backend()
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": '{"key": "value"}'},
            "done_reason": "stop",
        }
        backend._client = mock_client

        backend.chat([{"role": "user", "content": "hi"}], json_mode=True)

        call_kwargs = mock_client.chat.call_args[1]
        assert call_kwargs["format"] == "json"

    def test_max_tokens_passed_as_num_predict(self):
        """max_tokens should be passed as options.num_predict."""
        backend = self._make_backend()
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": "limited"},
            "done_reason": "length",
        }
        backend._client = mock_client

        backend.chat([{"role": "user", "content": "hi"}], max_tokens=100)

        call_kwargs = mock_client.chat.call_args[1]
        assert call_kwargs["options"]["num_predict"] == 100


# ======================================================================
# 2. TTS in event loop (Bug #12 fix verification)
# ======================================================================


class TestTTSEventLoopSafety:
    """Verify TTSEngine.synthesize works both inside and outside running event loops."""

    def _make_engine(self):
        from src.tts.tts_engine import TTSEngine

        return TTSEngine({"voice": "zh-CN-YunxiNeural", "rate": "+0%", "volume": "+0%"})

    @patch("src.tts.tts_engine.TTSEngine._synthesize_async")
    def test_synthesize_no_event_loop(self, mock_async, tmp_path):
        """synthesize() works normally when no event loop is running."""
        output_path = tmp_path / "test.mp3"
        mock_async.return_value = (output_path, [{"offset": 0.0, "duration": 1.0, "text": "hello"}])

        engine = self._make_engine()
        result_path, boundaries = engine.synthesize("hello world", output_path)

        assert result_path == output_path
        assert len(boundaries) == 1
        assert boundaries[0]["text"] == "hello"
        mock_async.assert_called_once_with("hello world", output_path)

    def test_synthesize_inside_running_event_loop(self, tmp_path):
        """synthesize() should not crash when called from within a running event loop.

        This verifies the Bug #12 fix: uses ThreadPoolExecutor to avoid
        'asyncio.run() cannot be called from a running event loop'.
        """
        output_path = tmp_path / "test_loop.mp3"

        engine = self._make_engine()

        # Hold the result from the thread
        result_holder = {}
        error_holder = {}

        async def fake_synthesize_async(text, path):
            """A fake async synth that returns immediately."""
            return (path, [{"offset": 0.0, "duration": 0.5, "text": "loop"}])

        def run_in_loop():
            """Run synthesize inside an active asyncio event loop via a thread."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def wrapper():
                # Now we're inside a running loop; synthesize should detect this
                # and use ThreadPoolExecutor internally
                with patch.object(engine, "_synthesize_async", side_effect=fake_synthesize_async):
                    path, bounds = engine.synthesize("test text", output_path)
                    result_holder["path"] = path
                    result_holder["boundaries"] = bounds

            try:
                loop.run_until_complete(wrapper())
            except Exception as e:
                error_holder["error"] = e
            finally:
                loop.close()

        thread = threading.Thread(target=run_in_loop)
        thread.start()
        thread.join(timeout=10)

        assert "error" not in error_holder, f"synthesize crashed inside event loop: {error_holder.get('error')}"
        assert result_holder.get("path") == output_path
        assert len(result_holder.get("boundaries", [])) == 1
        assert result_holder["boundaries"][0]["text"] == "loop"

    def test_synthesize_empty_text_generates_silent_placeholder(self, tmp_path):
        """Empty text should produce a silent MP3 placeholder, not crash."""
        engine = self._make_engine()
        output_path = tmp_path / "silent.mp3"

        result_path, boundaries = engine.synthesize("", output_path)

        assert result_path == output_path
        assert boundaries == []
        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_synthesize_none_text_generates_silent_placeholder(self, tmp_path):
        """None text (after coercion) should produce a silent placeholder."""
        engine = self._make_engine()
        output_path = tmp_path / "silent_none.mp3"

        result_path, boundaries = engine.synthesize(None, output_path)

        assert result_path == output_path
        assert boundaries == []
        assert output_path.exists()

    def test_synthesize_whitespace_only_generates_silent_placeholder(self, tmp_path):
        """Whitespace-only text should be treated as empty."""
        engine = self._make_engine()
        output_path = tmp_path / "silent_ws.mp3"

        result_path, boundaries = engine.synthesize("   \n\t  ", output_path)

        assert result_path == output_path
        assert boundaries == []
        assert output_path.exists()

    @patch("src.tts.tts_engine.TTSEngine._synthesize_async")
    def test_synthesize_creates_parent_directories(self, mock_async, tmp_path):
        """Output path parent directories are created automatically."""
        nested_path = tmp_path / "deep" / "nested" / "dir" / "audio.mp3"
        mock_async.return_value = (nested_path, [])

        engine = self._make_engine()
        engine.synthesize("test", nested_path)

        assert nested_path.parent.exists()

    @patch("src.tts.tts_engine.TTSEngine._synthesize_async")
    def test_synthesize_propagates_exception(self, mock_async, tmp_path):
        """Exceptions from async synthesis propagate correctly."""
        output_path = tmp_path / "fail.mp3"
        mock_async.side_effect = RuntimeError("edge-tts 未返回任何音频数据")

        engine = self._make_engine()
        with pytest.raises(RuntimeError, match="edge-tts 未返回任何音频数据"):
            engine.synthesize("hello", output_path)


# ======================================================================
# 3. LLM error handling
# ======================================================================


class TestOpenAIBackendErrorHandling:
    """Test OpenAI backend error handling for various API failures."""

    def _make_backend(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            from src.llm.openai_backend import OpenAIBackend

            backend = OpenAIBackend({"model": "gpt-4o-mini", "api_key": "test-key"})
        return backend

    def test_rate_limit_error_429(self):
        """Rate limit (429) should be wrapped in RuntimeError."""
        backend = self._make_backend()
        mock_client = MagicMock()

        # Simulate OpenAI RateLimitError
        rate_limit_exc = Exception("Error code: 429 - Rate limit exceeded")
        mock_client.chat.completions.create.side_effect = rate_limit_exc
        backend._client = mock_client

        with pytest.raises(RuntimeError, match="OpenAI API 调用失败"):
            backend.chat([{"role": "user", "content": "hi"}])

    def test_api_timeout_error(self):
        """API timeout should be wrapped in RuntimeError."""
        backend = self._make_backend()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = TimeoutError("Request timed out")
        backend._client = mock_client

        with pytest.raises(RuntimeError, match="OpenAI API 调用失败"):
            backend.chat([{"role": "user", "content": "hi"}])

    def test_empty_response_content(self):
        """Empty content in response should return empty string, not crash."""
        backend = self._make_backend()
        mock_client = MagicMock()

        mock_choice = MagicMock()
        mock_choice.message.content = None  # OpenAI can return None
        mock_choice.finish_reason = "stop"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 0
        mock_response.usage.total_tokens = 5
        mock_client.chat.completions.create.return_value = mock_response
        backend._client = mock_client

        result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.content == ""
        assert result.finish_reason == "stop"

    def test_max_tokens_uses_correct_param_for_gpt4(self):
        """GPT-4 models should use max_tokens parameter."""
        backend = self._make_backend()
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "ok"
        mock_choice.finish_reason = "length"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "gpt-4o-mini"
        mock_response.usage = None
        mock_client.chat.completions.create.return_value = mock_response
        backend._client = mock_client

        result = backend.chat(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
        )

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 100
        assert "max_completion_tokens" not in call_kwargs
        assert result.finish_reason == "length"

    def test_max_tokens_uses_max_completion_tokens_for_gpt5(self):
        """GPT-5+ models should use max_completion_tokens parameter."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            from src.llm.openai_backend import OpenAIBackend

            backend = OpenAIBackend({"model": "gpt-5", "api_key": "test-key"})

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "ok"
        mock_choice.finish_reason = "stop"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "gpt-5"
        mock_response.usage = None
        mock_client.chat.completions.create.return_value = mock_response
        backend._client = mock_client

        backend.chat([{"role": "user", "content": "hi"}], max_tokens=200)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_completion_tokens"] == 200
        assert "max_tokens" not in call_kwargs

    def test_max_tokens_uses_max_completion_tokens_for_o3(self):
        """o3 models should use max_completion_tokens parameter."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            from src.llm.openai_backend import OpenAIBackend

            backend = OpenAIBackend({"model": "o3-mini", "api_key": "test-key"})

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "ok"
        mock_choice.finish_reason = "stop"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "o3-mini"
        mock_response.usage = None
        mock_client.chat.completions.create.return_value = mock_response
        backend._client = mock_client

        backend.chat([{"role": "user", "content": "hi"}], max_tokens=150)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_completion_tokens"] == 150
        assert "max_tokens" not in call_kwargs

    def test_no_usage_in_response(self):
        """Response with usage=None should set usage to None in LLMResponse."""
        backend = self._make_backend()
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "hello"
        mock_choice.finish_reason = "stop"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "gpt-4o-mini"
        mock_response.usage = None
        mock_client.chat.completions.create.return_value = mock_response
        backend._client = mock_client

        result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.usage is None


class TestGeminiBackendErrorHandling:
    """Test Gemini backend error handling.

    The Gemini backend does `from google.genai import types` inside chat(),
    so we must inject a mock `google.genai.types` module into sys.modules
    to intercept the types used for Content, Part, and GenerateContentConfig.
    """

    def _make_backend(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            from src.llm.gemini_backend import GeminiBackend

            backend = GeminiBackend({"model": "gemini-2.0-flash-lite", "api_key": "test-key"})
        return backend

    def _build_mock_types(self):
        """Build a mock types module that mimics google.genai.types."""
        mock_types = MagicMock()
        # Content and Part just need to be callable and return something
        mock_types.Content.side_effect = lambda **kw: SimpleNamespace(**kw)
        mock_types.Part.side_effect = lambda **kw: SimpleNamespace(**kw)
        mock_types.GenerateContentConfig.side_effect = lambda **kw: SimpleNamespace(**kw)
        return mock_types

    def _patch_genai_types(self, mock_types):
        """Return a context manager that patches google.genai.types in sys.modules."""
        # We need google, google.genai, and google.genai.types all present
        mock_google = MagicMock()
        mock_genai = MagicMock()
        mock_genai.types = mock_types
        mock_google.genai = mock_genai
        return patch.dict("sys.modules", {
            "google": mock_google,
            "google.genai": mock_genai,
            "google.genai.types": mock_types,
        })

    def test_api_failure_raises_runtime_error(self):
        """Gemini API failure should be wrapped in RuntimeError."""
        backend = self._make_backend()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Invalid API key")
        backend._client = mock_client

        mock_types = self._build_mock_types()
        with self._patch_genai_types(mock_types):
            with pytest.raises(RuntimeError, match="Gemini API 调用失败"):
                backend.chat([{"role": "user", "content": "hi"}])

    def test_response_text_raises_valueerror_safety_filter(self):
        """When response.text raises ValueError (safety filter), fallback to candidates."""
        backend = self._make_backend()
        mock_client = MagicMock()

        mock_response = MagicMock()
        # response.text raises ValueError (content blocked by safety filter)
        type(mock_response).text = PropertyMock(side_effect=ValueError("No content"))
        # But candidates have content
        mock_part = MagicMock()
        mock_part.text = "fallback content"
        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_candidate.finish_reason = "STOP"
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = None

        mock_client.models.generate_content.return_value = mock_response
        backend._client = mock_client

        mock_types = self._build_mock_types()
        with self._patch_genai_types(mock_types):
            result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.content == "fallback content"
        assert result.finish_reason == "stop"

    def test_empty_response_text(self):
        """Empty response text should return empty string."""
        backend = self._make_backend()
        mock_client = MagicMock()

        mock_response = MagicMock()
        type(mock_response).text = PropertyMock(return_value="")
        mock_response.usage_metadata = None
        mock_response.candidates = []
        mock_client.models.generate_content.return_value = mock_response
        backend._client = mock_client

        mock_types = self._build_mock_types()
        with self._patch_genai_types(mock_types):
            result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.content == ""
        assert result.finish_reason is None

    def test_response_none_text(self):
        """response.text returning None should be coerced to empty string."""
        backend = self._make_backend()
        mock_client = MagicMock()

        mock_response = MagicMock()
        type(mock_response).text = PropertyMock(return_value=None)
        mock_response.usage_metadata = None
        mock_response.candidates = []
        mock_client.models.generate_content.return_value = mock_response
        backend._client = mock_client

        mock_types = self._build_mock_types()
        with self._patch_genai_types(mock_types):
            result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.content == ""

    def test_max_tokens_finish_reason(self):
        """MAX_TOKENS in finish_reason should map to 'length'."""
        backend = self._make_backend()
        mock_client = MagicMock()

        mock_response = MagicMock()
        type(mock_response).text = PropertyMock(return_value="truncated")
        mock_response.usage_metadata = None
        mock_candidate = MagicMock()
        mock_candidate.finish_reason = "MAX_TOKENS"
        mock_response.candidates = [mock_candidate]
        mock_client.models.generate_content.return_value = mock_response
        backend._client = mock_client

        mock_types = self._build_mock_types()
        with self._patch_genai_types(mock_types):
            result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.finish_reason == "length"
        assert result.content == "truncated"

    def test_usage_metadata_parsed(self):
        """Usage metadata should be correctly extracted."""
        backend = self._make_backend()
        mock_client = MagicMock()

        mock_response = MagicMock()
        type(mock_response).text = PropertyMock(return_value="hello")
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 5
        mock_response.usage_metadata.total_token_count = 15
        mock_response.candidates = []
        mock_client.models.generate_content.return_value = mock_response
        backend._client = mock_client

        mock_types = self._build_mock_types()
        with self._patch_genai_types(mock_types):
            result = backend.chat([{"role": "user", "content": "hi"}])

        assert result.usage == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    def test_system_messages_separated(self):
        """System messages should be extracted to system_instruction."""
        backend = self._make_backend()
        mock_client = MagicMock()

        mock_response = MagicMock()
        type(mock_response).text = PropertyMock(return_value="response")
        mock_response.usage_metadata = None
        mock_response.candidates = []
        mock_client.models.generate_content.return_value = mock_response
        backend._client = mock_client

        # Track what GenerateContentConfig receives
        config_calls = []

        mock_types = self._build_mock_types()
        original_side_effect = mock_types.GenerateContentConfig.side_effect

        def capture_config(**kwargs):
            config_calls.append(kwargs)
            return original_side_effect(**kwargs)

        mock_types.GenerateContentConfig.side_effect = capture_config

        with self._patch_genai_types(mock_types):
            backend.chat([
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "hi"},
            ])

        # Verify GenerateContentConfig was called with system_instruction
        assert len(config_calls) == 1
        assert config_calls[0]["system_instruction"] == "You are helpful"


# ======================================================================
# 4. LLM response parsing edge cases
# ======================================================================


class TestLLMResponseParsingEdgeCases:
    """Test edge cases in LLM response content parsing."""

    def test_response_containing_only_whitespace(self):
        """Response with only whitespace should be preserved as-is."""
        response = LLMResponse(content="   \n\t  ", model="test", usage=None)
        assert response.content == "   \n\t  "
        # Downstream code should handle stripping; the response preserves raw content

    def test_response_with_markdown_wrapped_json(self):
        """Verify that markdown-wrapped JSON in content is stored as-is.

        The backend should not try to parse or unwrap it;
        that is the responsibility of the caller using extract_json_obj/array.
        """
        markdown_json = '```json\n{"key": "value"}\n```'
        response = LLMResponse(content=markdown_json, model="test", usage=None)
        assert response.content == markdown_json
        assert "```json" in response.content

    def test_json_mode_but_response_not_valid_json_openai(self):
        """OpenAI json_mode=True but API returns non-JSON (edge case).

        The backend does not validate JSON; it passes content through.
        Caller is responsible for parsing.
        """
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            from src.llm.openai_backend import OpenAIBackend

            backend = OpenAIBackend({"model": "gpt-4o-mini", "api_key": "test-key"})

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "This is not valid JSON at all"
        mock_choice.finish_reason = "stop"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "gpt-4o-mini"
        mock_response.usage = None
        mock_client.chat.completions.create.return_value = mock_response
        backend._client = mock_client

        result = backend.chat(
            [{"role": "user", "content": "give me json"}],
            json_mode=True,
        )

        # Backend should pass through the raw content without validation
        assert result.content == "This is not valid JSON at all"

        # Verify json_mode was actually passed to the API
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["response_format"] == {"type": "json_object"}

    def test_json_mode_ollama_passes_format_json(self):
        """Ollama json_mode=True should pass format='json'."""
        with patch.dict("sys.modules", {"ollama": MagicMock(), "httpx": MagicMock()}):
            from src.llm.ollama_backend import OllamaBackend

            backend = OllamaBackend({"model": "test-model"})

        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": "not json either"},
            "done_reason": "stop",
        }
        backend._client = mock_client

        result = backend.chat(
            [{"role": "user", "content": "json pls"}],
            json_mode=True,
        )

        assert result.content == "not json either"
        call_kwargs = mock_client.chat.call_args[1]
        assert call_kwargs["format"] == "json"

    def test_json_mode_gemini_sets_response_mime_type(self):
        """Gemini json_mode=True should set response_mime_type."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            from src.llm.gemini_backend import GeminiBackend

            backend = GeminiBackend({"model": "gemini-2.0-flash-lite", "api_key": "test-key"})

        mock_client = MagicMock()
        mock_response = MagicMock()
        type(mock_response).text = PropertyMock(return_value='{"valid": true}')
        mock_response.usage_metadata = None
        mock_response.candidates = []
        mock_client.models.generate_content.return_value = mock_response
        backend._client = mock_client

        # Track GenerateContentConfig calls
        config_calls = []

        mock_types = MagicMock()
        mock_types.Content.side_effect = lambda **kw: SimpleNamespace(**kw)
        mock_types.Part.side_effect = lambda **kw: SimpleNamespace(**kw)

        def capture_config(**kwargs):
            config_calls.append(kwargs)
            return SimpleNamespace(**kwargs)

        mock_types.GenerateContentConfig.side_effect = capture_config

        mock_google = MagicMock()
        mock_genai = MagicMock()
        mock_genai.types = mock_types
        mock_google.genai = mock_genai

        with patch.dict("sys.modules", {
            "google": mock_google,
            "google.genai": mock_genai,
            "google.genai.types": mock_types,
        }):
            result = backend.chat(
                [{"role": "user", "content": "json pls"}],
                json_mode=True,
            )

        assert result.content == '{"valid": true}'
        assert len(config_calls) == 1
        assert config_calls[0]["response_mime_type"] == "application/json"

    def test_llm_response_dataclass_fields(self):
        """LLMResponse dataclass has all expected fields with correct defaults."""
        response = LLMResponse(content="test", model="test-model")
        assert response.content == "test"
        assert response.model == "test-model"
        assert response.usage is None
        assert response.finish_reason is None

    def test_llm_response_with_all_fields(self):
        """LLMResponse with all fields populated."""
        usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        response = LLMResponse(
            content="hello",
            model="gpt-4",
            usage=usage,
            finish_reason="stop",
        )
        assert response.content == "hello"
        assert response.model == "gpt-4"
        assert response.usage["total_tokens"] == 30
        assert response.finish_reason == "stop"


# ======================================================================
# 5. Factory function edge cases
# ======================================================================


class TestCreateLLMClient:
    """Test create_llm_client factory with various configurations."""

    def test_unknown_provider_raises_value_error(self):
        """Unknown provider name should raise ValueError."""
        from src.llm.llm_client import create_llm_client

        with pytest.raises(ValueError, match="未知的 LLM provider"):
            create_llm_client({"provider": "nonexistent"})

    def test_openai_missing_api_key_raises_runtime_error(self):
        """OpenAI provider without API key should raise RuntimeError."""
        from src.llm.llm_client import create_llm_client

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="未找到 API Key"):
                create_llm_client({"provider": "openai"})

    def test_gemini_missing_api_key_raises_runtime_error(self):
        """Gemini provider without API key should raise RuntimeError."""
        from src.llm.llm_client import create_llm_client

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="未找到 Gemini API Key"):
                create_llm_client({"provider": "gemini"})

    def test_auto_detection_no_provider_available(self):
        """Auto detection with no providers should raise RuntimeError."""
        from src.llm.llm_client import create_llm_client

        # Patch _detect_provider directly rather than the internal urllib import
        with patch("src.llm.llm_client._detect_provider", side_effect=RuntimeError("未找到可用的 LLM provider")):
            with pytest.raises(RuntimeError, match="未找到可用的 LLM provider"):
                create_llm_client({"provider": "auto"})

    def test_ollama_provider_creates_backend(self):
        """Ollama provider should create OllamaBackend."""
        from src.llm.llm_client import create_llm_client
        from src.llm.ollama_backend import OllamaBackend

        with patch.dict("sys.modules", {"ollama": MagicMock(), "httpx": MagicMock()}):
            client = create_llm_client({"provider": "ollama", "model": "llama3"})

        assert isinstance(client, OllamaBackend)
        assert client._model == "llama3"
