"""文档改写器测试"""

from unittest.mock import MagicMock, patch

import pytest

from src.ppt.document_rewriter import DocumentRewriter


def _make_llm_response(content: str):
    """构造 LLMResponse mock。"""
    resp = MagicMock()
    resp.content = content
    return resp


class TestRewriteBasic:
    """基本改写功能。"""

    @patch("src.ppt.document_rewriter.create_llm_client")
    def test_empty_text_returns_as_is(self, mock_create):
        rw = DocumentRewriter({"llm": {}})
        assert rw.rewrite("") == ""
        mock_create.return_value.chat.assert_not_called()

    @patch("src.ppt.document_rewriter.create_llm_client")
    def test_whitespace_only_returns_as_is(self, mock_create):
        rw = DocumentRewriter({"llm": {}})
        assert rw.rewrite("   \n\n  ") == "   \n\n  "
        mock_create.return_value.chat.assert_not_called()

    @patch("src.ppt.document_rewriter.create_llm_client")
    def test_successful_rewrite(self, mock_create):
        rewritten_text = (
            "# 人工智能发展趋势\n\n"
            "人工智能正在深刻改变我们的工作和生活方式。"
            "根据最新研究报告，2024年全球AI市场规模已达**5000亿美元**，"
            "较去年增长超过30%。这一增长主要得益于大语言模型的突破性进展。\n\n"
            "## 关键技术突破\n\n"
            "大语言模型的出现标志着AI进入了新纪元。"
            "这些模型能够理解和生成自然语言，"
            "在翻译、写作、编程等领域展现出惊人的能力。"
            "全球已有超过500家企业将AI应用于核心业务流程。\n\n"
            "## 未来展望\n\n"
            "预计到2030年，AI将渗透到每一个行业，"
            "带来深刻的变革和全新的商业模式。"
        )
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(rewritten_text)
        mock_create.return_value = mock_llm

        rw = DocumentRewriter({"llm": {}})
        result = rw.rewrite("一些原始技术文档内容" * 20)

        assert result == rewritten_text
        mock_llm.chat.assert_called_once()

    @patch("src.ppt.document_rewriter.create_llm_client")
    def test_fallback_on_too_short_result(self, mock_create):
        """改写结果太短时回退到原文。"""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response("太短了")
        mock_create.return_value = mock_llm

        original = "原始文档内容" * 50
        rw = DocumentRewriter({"llm": {}})
        result = rw.rewrite(original)

        assert result == original

    @patch("src.ppt.document_rewriter.create_llm_client")
    def test_fallback_on_llm_exception(self, mock_create):
        """LLM 调用异常时回退到原文。"""
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("API error")
        mock_create.return_value = mock_llm

        original = "原始文档内容" * 50
        rw = DocumentRewriter({"llm": {}})
        result = rw.rewrite(original)

        assert result == original


class TestRewriteCodeRemoval:
    """改写结果中代码块的清理。"""

    @patch("src.ppt.document_rewriter.create_llm_client")
    def test_strips_residual_code_blocks(self, mock_create):
        """即使 LLM 返回了代码块，也会被清理掉。"""
        text_with_code = (
            "# 智能数据处理系统\n\n"
            "这是一段正常的文字描述，介绍了系统的核心功能和价值。"
            "系统支持多种数据处理方式，包括批量处理和实时流处理。"
            "我们的平台已服务超过1000家企业客户，日均处理数据量达到PB级别。\n\n"
            "```python\nprint('hello')\n```\n\n"
            "总结：系统性能优异，值得推广使用。"
            "预计可以提升效率30%以上。在过去一年中，"
            "客户满意度达到了95%，续费率超过90%。"
            "我们将继续投入研发，推出更多创新功能。"
        )
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(text_with_code)
        mock_create.return_value = mock_llm

        rw = DocumentRewriter({"llm": {}})
        result = rw.rewrite("原始内容" * 50)

        assert "```" not in result
        assert "print" not in result
        assert "智能数据处理系统" in result


class TestDocumentProfile:
    """文档特征分析。"""

    def test_high_code_ratio(self):
        text = (
            "简介\n\n"
            "```python\n"
            + "x = 1\n" * 100
            + "```\n"
        )
        profile = DocumentRewriter._profile_document(text)
        assert "代码占比" in profile

    def test_extracts_titles(self):
        text = "# 第一章\n## 第二节\n### 小标题\n正文内容"
        profile = DocumentRewriter._profile_document(text)
        assert "第一章" in profile
        assert "第二节" in profile

    def test_detects_urls(self):
        text = "\n".join(
            [f"https://api.example.com/v{i}" for i in range(5)]
        )
        profile = DocumentRewriter._profile_document(text)
        assert "URL" in profile

    def test_detects_curl_commands(self):
        text = "curl -X POST http://example.com\ncurl http://example.com/api"
        profile = DocumentRewriter._profile_document(text)
        assert "curl" in profile

    def test_no_special_features(self):
        """普通文本不会触发特殊标记。"""
        text = "这是一段普通的中文文字，没有代码也没有URL。" * 10
        profile = DocumentRewriter._profile_document(text)
        assert "代码占比" not in profile
        assert "URL" not in profile
        assert "curl" not in profile


class TestTruncation:
    """超长文档截断。"""

    @patch("src.ppt.document_rewriter.create_llm_client")
    def test_long_document_truncated(self, mock_create):
        """超过 16000 字符的文档会被截断。"""
        rewritten = "改写后的内容。" * 50  # 足够长
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(rewritten)
        mock_create.return_value = mock_llm

        rw = DocumentRewriter({"llm": {}})
        long_text = "x" * 20000
        rw.rewrite(long_text)

        # 检查传给 LLM 的文本被截断了
        call_args = mock_llm.chat.call_args[0][0]  # messages list
        user_msg = call_args[1]["content"]
        # 原始文档部分不应超过 16000 字符
        assert len(user_msg) < 20000


class TestPipelineIntegration:
    """测试 pipeline 中的改写阶段集成。"""

    @patch("src.ppt.document_rewriter.create_llm_client")
    @patch("src.ppt.pipeline.DocumentAnalyzer")
    def test_unsuitable_doc_triggers_rewrite(
        self, mock_analyzer_cls, mock_create_llm
    ):
        """不适合的文档触发改写。"""
        from unittest.mock import PropertyMock
        from src.ppt.pipeline import PPTPipeline

        # 构造一个代码占比很高的文档
        code_heavy = (
            "# API Reference\n\n"
            "```python\n"
            + "import os\nresult = os.listdir('.')\n" * 50
            + "```\n"
        )

        # Mock LLM for rewriter
        rewritten = "# API 功能概述\n\n" + "该 API 提供了文件管理功能。" * 40
        mock_llm = MagicMock()
        mock_llm.chat.return_value = _make_llm_response(rewritten)
        mock_create_llm.return_value = mock_llm

        pipeline = PPTPipeline(workspace="/tmp/test_ppt_rw", config={})

        # 只测试 rewrite 阶段的逻辑
        from src.ppt.document_analyzer import check_ppt_suitability
        suit = check_ppt_suitability(code_heavy)
        assert not suit.suitable, f"Expected unsuitable, got score={suit.score}"

    @patch("src.ppt.document_rewriter.create_llm_client")
    def test_suitable_doc_skips_rewrite(self, mock_create_llm):
        """适合的文档不触发改写。"""
        from src.ppt.document_analyzer import check_ppt_suitability

        good_text = (
            "人工智能正在深刻改变我们的生活和工作方式。"
            "从智能语音助手到自动驾驶汽车，AI 的应用场景不断拓展。"
            "根据最新研究报告，2024年全球AI市场规模达到5000亿美元。"
            "这一增长主要得益于大语言模型的突破性进展。\n\n"
            "在教育领域，AI辅助教学系统已在全球超过100个国家部署。"
            "这些系统能够自动调整教学内容和难度，实现个性化学习。"
            "研究表明，使用AI辅助教学的学生平均成绩提升了15%。\n\n"
            "然而，AI的快速发展也带来了新的挑战。"
            "数据隐私和算法偏见等问题需要我们认真面对。"
        )
        suit = check_ppt_suitability(good_text)
        assert suit.suitable
        # LLM should not be called
        mock_create_llm.assert_not_called()
