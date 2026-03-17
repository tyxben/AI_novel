"""文档分析器测试"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.ppt.document_analyzer import DocumentAnalyzer, _MAX_INPUT_CHARS
from src.ppt.models import Audience, DocumentAnalysis, DocumentType, Tone


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_llm_response(data: dict) -> LLMResponse:
    """构造 LLM 响应。"""
    return LLMResponse(content=json.dumps(data, ensure_ascii=False), model="test")


def _valid_analysis_json() -> dict:
    """返回一个合法的分析 JSON。"""
    return {
        "theme": "2024年AI技术发展趋势报告",
        "doc_type": "tech_share",
        "audience": "technical",
        "tone": "professional",
        "key_points": [
            "大模型参数规模持续增长",
            "多模态融合成为趋势",
            "AI 应用落地加速",
            "开源社区推动创新",
        ],
        "has_sections": True,
        "has_data": True,
        "has_quotes": False,
        "suggested_pages": 15,
    }


@pytest.fixture()
def analyzer():
    """创建 mock LLM 的 DocumentAnalyzer。"""
    with patch("src.ppt.document_analyzer.create_llm_client") as mock_create:
        mock_llm = MagicMock()
        mock_create.return_value = mock_llm
        da = DocumentAnalyzer({"llm": {}})
        da._mock_llm = mock_llm  # 方便测试中设置返回值
        yield da


# ---------------------------------------------------------------------------
# 正常流程
# ---------------------------------------------------------------------------


class TestAnalyzeHappyPath:
    """测试正常分析流程。"""

    def test_basic_analysis(self, analyzer: DocumentAnalyzer):
        """基本分析：LLM 返回合法 JSON。"""
        analyzer._mock_llm.chat.return_value = _make_llm_response(
            _valid_analysis_json()
        )

        text = "这是一篇关于 AI 技术发展的长文档。" * 50
        result = analyzer.analyze(text)

        assert isinstance(result, DocumentAnalysis)
        assert result.theme == "2024年AI技术发展趋势报告"
        assert result.doc_type == DocumentType.TECH_SHARE
        assert result.audience == Audience.TECHNICAL
        assert result.tone == Tone.PROFESSIONAL
        assert len(result.key_points) == 4
        assert result.has_data is True
        assert result.has_quotes is False
        assert result.estimated_pages == 15

    def test_suggested_pages_mapped_to_estimated(self, analyzer: DocumentAnalyzer):
        """suggested_pages 字段正确映射到 estimated_pages。"""
        data = _valid_analysis_json()
        data["suggested_pages"] = 20
        analyzer._mock_llm.chat.return_value = _make_llm_response(data)

        result = analyzer.analyze("这是一段足够长的测试文档。" * 20)
        assert result.estimated_pages == 20

    def test_business_report(self, analyzer: DocumentAnalyzer):
        """商务报告类型文档分析。"""
        data = _valid_analysis_json()
        data["doc_type"] = "business_report"
        data["audience"] = "business"
        data["tone"] = "professional"
        analyzer._mock_llm.chat.return_value = _make_llm_response(data)

        result = analyzer.analyze("本季度销售报告：总营收增长 30%，超出预期。" * 30)
        assert result.doc_type == DocumentType.BUSINESS_REPORT
        assert result.audience == Audience.BUSINESS

    def test_creative_pitch(self, analyzer: DocumentAnalyzer):
        """创意提案类型文档分析。"""
        data = _valid_analysis_json()
        data["doc_type"] = "creative_pitch"
        data["audience"] = "creative"
        data["tone"] = "creative"
        analyzer._mock_llm.chat.return_value = _make_llm_response(data)

        result = analyzer.analyze("我们的创意方案是打造一个全新的品牌形象。" * 30)
        assert result.doc_type == DocumentType.CREATIVE_PITCH
        assert result.audience == Audience.CREATIVE
        assert result.tone == Tone.CREATIVE


# ---------------------------------------------------------------------------
# 文本预处理
# ---------------------------------------------------------------------------


class TestPreprocess:
    """测试文本预处理。"""

    def test_long_text_truncated(self, analyzer: DocumentAnalyzer):
        """超长文本被截断。"""
        long_text = "这是一段很长的文字。" * 10000
        assert len(long_text) > _MAX_INPUT_CHARS

        analyzer._mock_llm.chat.return_value = _make_llm_response(
            _valid_analysis_json()
        )
        analyzer.analyze(long_text)

        # 验证发送给 LLM 的文本被截断了
        call_args = analyzer._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]  # messages[1]["content"]
        # 用户消息中的文档文本应不超过 _MAX_INPUT_CHARS + prompt前缀
        assert len(user_msg) < _MAX_INPUT_CHARS + 500

    def test_multiple_blank_lines_collapsed(self, analyzer: DocumentAnalyzer):
        """多个连续空行被折叠。"""
        text = "第一段\n\n\n\n\n第二段\n\n\n第三段"
        cleaned = analyzer._preprocess(text)
        assert "\n\n\n" not in cleaned
        assert "第一段" in cleaned
        assert "第二段" in cleaned

    def test_control_chars_removed(self, analyzer: DocumentAnalyzer):
        """不可见控制字符被移除。"""
        text = "正常文字\x00\x01\x02隐藏字符\x7f结尾"
        cleaned = analyzer._preprocess(text)
        assert "\x00" not in cleaned
        assert "\x01" not in cleaned
        assert "\x7f" not in cleaned
        assert "正常文字" in cleaned
        assert "隐藏字符" in cleaned

    def test_short_text_raises(self, analyzer: DocumentAnalyzer):
        """过短文本抛出 ValueError。"""
        with pytest.raises(ValueError, match="过短"):
            analyzer.analyze("太短了")

    def test_empty_text_raises(self, analyzer: DocumentAnalyzer):
        """空文本抛出 ValueError。"""
        with pytest.raises(ValueError, match="过短"):
            analyzer.analyze("")

    def test_whitespace_only_raises(self, analyzer: DocumentAnalyzer):
        """纯空白文本抛出 ValueError。"""
        with pytest.raises(ValueError, match="过短"):
            analyzer.analyze("   \n\n\t  ")


# ---------------------------------------------------------------------------
# JSON 解析失败降级
# ---------------------------------------------------------------------------


class TestFallback:
    """测试 LLM 返回垃圾时的降级处理。"""

    def test_garbage_json_falls_back(self, analyzer: DocumentAnalyzer):
        """LLM 返回非 JSON 文本时使用 fallback。"""
        analyzer._mock_llm.chat.return_value = LLMResponse(
            content="这不是JSON，我只是在聊天。", model="test"
        )

        text = "这是一篇关于市场分析的文档，包含大量数据和图表。" * 20
        result = analyzer.analyze(text)

        assert isinstance(result, DocumentAnalysis)
        assert result.doc_type == DocumentType.OTHER
        assert result.audience == Audience.GENERAL
        assert result.tone == Tone.PROFESSIONAL
        assert len(result.key_points) >= 1

    def test_partial_json_handled(self, analyzer: DocumentAnalyzer):
        """LLM 返回不完整 JSON 时降级。"""
        analyzer._mock_llm.chat.return_value = LLMResponse(
            content='{"theme": "测试"', model="test"  # 不完整 JSON
        )

        text = "关于人工智能的报告，包含最新研究数据。" * 20
        result = analyzer.analyze(text)
        assert isinstance(result, DocumentAnalysis)

    def test_missing_key_fields_handled(self, analyzer: DocumentAnalyzer):
        """LLM 返回缺少关键字段的 JSON 时降级。"""
        incomplete = {"theme": "测试主题"}  # 缺少其他必填字段
        analyzer._mock_llm.chat.return_value = _make_llm_response(incomplete)

        text = "这是一份测试文档内容。" * 20
        result = analyzer.analyze(text)
        assert isinstance(result, DocumentAnalysis)

    def test_invalid_enum_values_use_defaults(self, analyzer: DocumentAnalyzer):
        """LLM 返回无效枚举值时使用默认值。"""
        data = _valid_analysis_json()
        data["doc_type"] = "invalid_type"
        data["audience"] = "aliens"
        data["tone"] = "angry"
        analyzer._mock_llm.chat.return_value = _make_llm_response(data)

        result = analyzer.analyze("正常的文档内容用于测试。" * 20)
        assert result.doc_type == DocumentType.OTHER
        assert result.audience == Audience.GENERAL
        assert result.tone == Tone.PROFESSIONAL

    def test_pages_out_of_range_clamped(self, analyzer: DocumentAnalyzer):
        """建议页数超出范围时被钳制。"""
        data = _valid_analysis_json()
        data["suggested_pages"] = 100  # 超出上限
        analyzer._mock_llm.chat.return_value = _make_llm_response(data)

        result = analyzer.analyze("测试文档。" * 30)
        assert 5 <= result.estimated_pages <= 50

    def test_pages_too_low_clamped(self, analyzer: DocumentAnalyzer):
        """建议页数过低时被钳制到最低 5。"""
        data = _valid_analysis_json()
        data["suggested_pages"] = 1
        analyzer._mock_llm.chat.return_value = _make_llm_response(data)

        result = analyzer.analyze("测试文档。" * 30)
        assert result.estimated_pages >= 5

    def test_empty_key_points_fallback(self, analyzer: DocumentAnalyzer):
        """key_points 为空时使用 fallback 提取。"""
        data = _valid_analysis_json()
        data["key_points"] = []
        analyzer._mock_llm.chat.return_value = _make_llm_response(data)

        text = "第一个重要观点是关于技术创新。\n第二个重要观点是关于市场趋势。\n" * 10
        result = analyzer.analyze(text)
        assert len(result.key_points) >= 1


# ---------------------------------------------------------------------------
# Fallback 分析质量
# ---------------------------------------------------------------------------


class TestFallbackQuality:
    """测试 fallback 分析的质量。"""

    def test_short_doc_gets_fewer_pages(self, analyzer: DocumentAnalyzer):
        """短文档 fallback 建议较少页数。"""
        analyzer._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )
        text = "短文档内容。" * 50  # ~300 chars
        result = analyzer.analyze(text)
        assert result.estimated_pages <= 12

    def test_long_doc_gets_more_pages(self, analyzer: DocumentAnalyzer):
        """长文档 fallback 建议较多页数。"""
        analyzer._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )
        text = "长文档内容包含很多细节和数据分析。" * 1000  # ~16000 chars
        result = analyzer.analyze(text)
        assert result.estimated_pages >= 12

    def test_markdown_sections_detected(self, analyzer: DocumentAnalyzer):
        """fallback 能检测 markdown 章节。"""
        analyzer._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )
        text = "# 标题\n\n正文内容很长很详细。\n\n## 子标题\n\n更多内容。" * 10
        result = analyzer.analyze(text)
        assert result.has_sections is True

    def test_data_detected_in_fallback(self, analyzer: DocumentAnalyzer):
        """fallback 能检测数据内容。"""
        analyzer._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )
        text = "销售额增长了30%，利润率达到12.5%。总营收500亿元。" * 10
        result = analyzer.analyze(text)
        assert result.has_data is True

    def test_quotes_detected_in_fallback(self, analyzer: DocumentAnalyzer):
        """fallback 能检测引用内容。"""
        analyzer._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )
        text = '正如乔布斯所说：\u201c活着就是为了改变世界。\u201d这句话影响了很多人。' * 10
        result = analyzer.analyze(text)
        assert result.has_quotes is True


# ---------------------------------------------------------------------------
# LLM 调用参数
# ---------------------------------------------------------------------------


class TestLLMCallParams:
    """测试 LLM 调用参数正确性。"""

    def test_json_mode_enabled(self, analyzer: DocumentAnalyzer):
        """确认使用 json_mode=True。"""
        analyzer._mock_llm.chat.return_value = _make_llm_response(
            _valid_analysis_json()
        )
        analyzer.analyze("测试文档内容。" * 20)

        call_kwargs = analyzer._mock_llm.chat.call_args
        assert call_kwargs[1].get("json_mode") is True or (
            len(call_kwargs[0]) > 2 and call_kwargs[0][2] is True
        )

    def test_system_prompt_present(self, analyzer: DocumentAnalyzer):
        """确认包含 system prompt。"""
        analyzer._mock_llm.chat.return_value = _make_llm_response(
            _valid_analysis_json()
        )
        analyzer.analyze("测试文档内容。" * 20)

        messages = analyzer._mock_llm.chat.call_args[0][0]
        assert messages[0]["role"] == "system"
        assert "演讲教练" in messages[0]["content"]
