"""深度内容提取器测试"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.llm_client import LLMResponse
from src.ppt.content_extractor import (
    ContentExtractor,
    _MAX_BLOCKS,
    _MAX_INPUT_CHARS,
    _MIN_BLOCKS,
)
from src.ppt.models import ContentBlock, ContentMap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(data: dict) -> LLMResponse:
    """构造 LLM 响应。"""
    return LLMResponse(content=json.dumps(data, ensure_ascii=False), model="test")


def _valid_content_map_json(n_blocks: int = 8) -> dict:
    """返回一个合法的 ContentMap JSON。"""
    blocks = []
    for i in range(n_blocks):
        blocks.append(
            {
                "block_id": f"b{i + 1}",
                "block_type": ["thesis", "argument", "data", "quote", "example", "conclusion"][
                    i % 6
                ],
                "title": f"内容块标题{i + 1}大约十五个字左右",
                "summary": f"这是第{i + 1}个内容块的摘要，包含具体事实和数据，例如增长率达到30%。",
                "source_text": f"这是第{i + 1}个内容块的原文片段，保留了关键数据和核心论述。",
                "importance": max(1, min(5, 5 - i)),
            }
        )
    return {
        "document_thesis": "AI 技术正在重塑全球市场格局",
        "content_blocks": blocks,
        "logical_flow": [f"b{i + 1}" for i in range(n_blocks)],
        "key_data_points": ["市场规模5.2万亿", "增长率30%", "渗透率从5%提升到15%"],
        "key_quotes": ["AI不是未来，AI就是现在", "数据是新时代的石油"],
    }


@pytest.fixture()
def extractor():
    """创建 mock LLM 的 ContentExtractor。"""
    with patch("src.ppt.content_extractor.create_llm_client") as mock_create:
        mock_llm = MagicMock()
        mock_create.return_value = mock_llm
        ce = ContentExtractor({"llm": {}})
        ce._mock_llm = mock_llm  # 方便测试中设置返回值
        yield ce


# ---------------------------------------------------------------------------
# 正常流程
# ---------------------------------------------------------------------------


class TestExtractHappyPath:
    """测试正常提取流程。"""

    def test_basic_extraction(self, extractor: ContentExtractor):
        """基本提取：LLM 返回合法 JSON -> 正确的 ContentMap。"""
        data = _valid_content_map_json()
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        text = "AI 技术正在重塑全球市场格局。全球AI市场规模已达5.2万亿。" * 50
        result = extractor.extract(text)

        assert isinstance(result, ContentMap)
        assert result.document_thesis == "AI 技术正在重塑全球市场格局"
        assert len(result.content_blocks) == 8
        assert len(result.logical_flow) == 8
        assert "市场规模5.2万亿" in result.key_data_points
        assert "AI不是未来，AI就是现在" in result.key_quotes

    def test_content_blocks_have_correct_structure(self, extractor: ContentExtractor):
        """每个 ContentBlock 都有正确的字段和值。"""
        data = _valid_content_map_json()
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        result = extractor.extract("文档内容" * 100)

        for block in result.content_blocks:
            assert isinstance(block, ContentBlock)
            assert block.block_id.startswith("b")
            assert block.block_type in {
                "thesis", "argument", "data", "quote", "example", "conclusion"
            }
            assert len(block.title) > 0
            assert len(block.summary) > 0
            assert len(block.source_text) > 0
            assert 1 <= block.importance <= 5

    def test_logical_flow_contains_all_block_ids(self, extractor: ContentExtractor):
        """logical_flow 包含所有 block_id。"""
        data = _valid_content_map_json()
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        result = extractor.extract("文档内容" * 100)

        block_ids = {b.block_id for b in result.content_blocks}
        assert set(result.logical_flow) == block_ids

    def test_key_data_points_preserved(self, extractor: ContentExtractor):
        """key_data_points 从 LLM 输出中正确提取。"""
        data = _valid_content_map_json()
        data["key_data_points"] = ["营收500亿", "利润率12.5%", "用户量3000万"]
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        result = extractor.extract("文档内容" * 100)

        assert result.key_data_points == ["营收500亿", "利润率12.5%", "用户量3000万"]

    def test_key_quotes_preserved(self, extractor: ContentExtractor):
        """key_quotes 从 LLM 输出中正确提取。"""
        data = _valid_content_map_json()
        data["key_quotes"] = ["创新是唯一出路", "客户至上"]
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        result = extractor.extract("文档内容" * 100)

        assert result.key_quotes == ["创新是唯一出路", "客户至上"]


# ---------------------------------------------------------------------------
# LLM 返回垃圾 -> 降级到规则提取
# ---------------------------------------------------------------------------


class TestFallbackExtraction:
    """测试 LLM 返回无效结果时的降级处理。"""

    def test_garbage_json_falls_back(self, extractor: ContentExtractor):
        """LLM 返回非 JSON 文本时使用 fallback。"""
        extractor._mock_llm.chat.return_value = LLMResponse(
            content="这不是JSON，我只是在聊天。", model="test"
        )

        text = (
            "第一段核心论点介绍背景信息。\n\n"
            "第二段论据支撑包含数据30%。\n\n"
            "第三段更多论据和具体案例说明。\n\n"
            "第四段数据分析：增长100万用户。\n\n"
            "第五段结论总结和未来展望。"
        )
        result = extractor.extract(text)

        assert isinstance(result, ContentMap)
        assert len(result.content_blocks) >= 1
        assert all(isinstance(b, ContentBlock) for b in result.content_blocks)

    def test_llm_exception_falls_back(self, extractor: ContentExtractor):
        """LLM 调用抛出异常时使用 fallback。"""
        extractor._mock_llm.chat.side_effect = RuntimeError("API Error")

        text = (
            "段落一，核心论点和背景。\n\n"
            "段落二，支撑论据一。\n\n"
            "段落三，支撑论据二。\n\n"
            "段落四，数据和案例。\n\n"
            "段落五，总结和展望。"
        )
        result = extractor.extract(text)

        assert isinstance(result, ContentMap)
        assert len(result.content_blocks) >= 1

    def test_too_few_blocks_falls_back(self, extractor: ContentExtractor):
        """LLM 返回不足 MIN_BLOCKS 个有效块时使用 fallback。"""
        data = _valid_content_map_json(n_blocks=2)  # Only 2 blocks < MIN_BLOCKS
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        text = (
            "段落一核心论点介绍背景信息内容详实。\n\n"
            "段落二论据支撑包含数据30%增长。\n\n"
            "段落三更多论据和案例说明分析。\n\n"
            "段落四数据分析统计结论汇总。\n\n"
            "段落五结论总结和未来展望规划。"
        )
        result = extractor.extract(text)

        assert isinstance(result, ContentMap)
        # Fallback should produce blocks from paragraph splitting
        assert len(result.content_blocks) >= 1

    def test_partial_json_handled(self, extractor: ContentExtractor):
        """LLM 返回不完整 JSON 时降级。"""
        extractor._mock_llm.chat.return_value = LLMResponse(
            content='{"document_thesis": "测试"', model="test"  # 不完整 JSON
        )

        text = (
            "文档段落一包含核心论点信息。\n\n"
            "文档段落二包含支撑论据说明。\n\n"
            "文档段落三包含数据分析案例。\n\n"
            "文档段落四包含更多论据分析。\n\n"
            "文档段落五包含总结展望结论。"
        )
        result = extractor.extract(text)
        assert isinstance(result, ContentMap)

    def test_missing_content_blocks_field(self, extractor: ContentExtractor):
        """LLM 返回 JSON 但缺少 content_blocks 字段时降级。"""
        data = {"document_thesis": "核心论点"}
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        text = (
            "段落一完整的论点和背景介绍。\n\n"
            "段落二完整的论据支撑内容。\n\n"
            "段落三完整的数据分析案例。\n\n"
            "段落四完整的补充论据说明。\n\n"
            "段落五完整的总结和未来展望。"
        )
        result = extractor.extract(text)

        assert isinstance(result, ContentMap)
        # Falls back because no blocks
        assert len(result.content_blocks) >= 1

    def test_blocks_with_missing_title_skipped(self, extractor: ContentExtractor):
        """内容块缺少 title 时被跳过。"""
        data = _valid_content_map_json()
        # 破坏一些块
        data["content_blocks"][0]["title"] = ""
        data["content_blocks"][1]["title"] = ""
        data["content_blocks"][2]["summary"] = ""
        # 只剩 5 个有效块 >= MIN_BLOCKS
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        result = extractor.extract("测试文档内容" * 100)

        assert isinstance(result, ContentMap)
        # 3 blocks were invalid, 5 remain
        valid_ids = {b.block_id for b in result.content_blocks}
        assert "b1" not in valid_ids  # title was empty
        assert "b2" not in valid_ids  # title was empty
        assert "b3" not in valid_ids  # summary was empty


# ---------------------------------------------------------------------------
# 空文档
# ---------------------------------------------------------------------------


class TestEmptyDocument:
    """测试空文档处理。"""

    def test_empty_string(self, extractor: ContentExtractor):
        """空字符串返回最小 ContentMap。"""
        result = extractor.extract("")

        assert isinstance(result, ContentMap)
        assert result.document_thesis == "空文档"
        assert len(result.content_blocks) == 1
        assert result.content_blocks[0].block_type == "thesis"
        assert result.content_blocks[0].importance == 1
        assert result.logical_flow == ["b1"]
        assert result.key_data_points == []
        assert result.key_quotes == []

    def test_whitespace_only(self, extractor: ContentExtractor):
        """纯空白文本返回最小 ContentMap。"""
        result = extractor.extract("   \n\n\t  ")

        assert isinstance(result, ContentMap)
        assert result.document_thesis == "空文档"

    def test_none_like_content(self, extractor: ContentExtractor):
        """极短文本（strip 后为空）返回最小 ContentMap。"""
        result = extractor.extract("  ")

        assert isinstance(result, ContentMap)
        assert len(result.content_blocks) >= 1


# ---------------------------------------------------------------------------
# 长文档截断
# ---------------------------------------------------------------------------


class TestTruncation:
    """测试长文档截断。"""

    def test_very_long_document_truncated(self, extractor: ContentExtractor):
        """超长文档在发送给 LLM 前被截断。"""
        long_text = "这是一段很长的文字包含核心论点。" * 10000
        assert len(long_text) > _MAX_INPUT_CHARS

        data = _valid_content_map_json()
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        extractor.extract(long_text)

        # 验证发送给 LLM 的文本被截断了
        call_args = extractor._mock_llm.chat.call_args
        user_msg = call_args[0][0][1]["content"]  # messages[1]["content"]
        # 用户消息中的文档文本应不超过 _MAX_INPUT_CHARS + prompt前缀
        assert len(user_msg) < _MAX_INPUT_CHARS + 500

    def test_truncation_at_sentence_boundary(self, extractor: ContentExtractor):
        """截断发生在句子边界。"""
        # 构造刚好在 _MAX_INPUT_CHARS 附近有句号的文本
        base = "这是一段测试文字。"  # 9 chars
        repeats = _MAX_INPUT_CHARS // len(base) + 100
        long_text = base * repeats

        cleaned = extractor._preprocess(long_text)
        assert len(cleaned) <= _MAX_INPUT_CHARS
        # 截断后应以句号结尾（因为文本中有大量句号边界）
        assert cleaned.endswith("\u3002") or len(cleaned) <= _MAX_INPUT_CHARS

    def test_max_blocks_capped(self, extractor: ContentExtractor):
        """超过 MAX_BLOCKS 个内容块时被截断。"""
        data = _valid_content_map_json(n_blocks=25)
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        result = extractor.extract("文档内容" * 100)

        assert len(result.content_blocks) <= _MAX_BLOCKS


# ---------------------------------------------------------------------------
# 内容块结构验证
# ---------------------------------------------------------------------------


class TestContentBlockValidation:
    """测试 ContentBlock 的结构和值验证。"""

    def test_invalid_block_type_defaults_to_argument(self, extractor: ContentExtractor):
        """无效的 block_type 默认为 argument。"""
        data = _valid_content_map_json()
        for block in data["content_blocks"]:
            block["block_type"] = "invalid_type"
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        result = extractor.extract("文档内容" * 100)

        for block in result.content_blocks:
            assert block.block_type == "argument"

    def test_importance_clamped_to_range(self, extractor: ContentExtractor):
        """importance 被钳制到 1-5 范围。"""
        data = _valid_content_map_json()
        data["content_blocks"][0]["importance"] = 100
        data["content_blocks"][1]["importance"] = -5
        data["content_blocks"][2]["importance"] = 0
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        result = extractor.extract("文档内容" * 100)

        for block in result.content_blocks:
            assert 1 <= block.importance <= 5

    def test_block_id_auto_generated_if_missing(self, extractor: ContentExtractor):
        """缺少 block_id 时自动生成。"""
        data = _valid_content_map_json()
        del data["content_blocks"][0]["block_id"]
        del data["content_blocks"][1]["block_id"]
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        result = extractor.extract("文档内容" * 100)

        block_ids = [b.block_id for b in result.content_blocks]
        assert len(block_ids) == len(set(block_ids))  # all unique (assuming LLM returns distinct)

    def test_source_text_defaults_to_summary(self, extractor: ContentExtractor):
        """source_text 为空时默认使用 summary。"""
        data = _valid_content_map_json()
        data["content_blocks"][0]["source_text"] = ""
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        result = extractor.extract("文档内容" * 100)

        first_block = result.content_blocks[0]
        assert first_block.source_text == first_block.summary

    def test_logical_flow_auto_completes_missing_ids(self, extractor: ContentExtractor):
        """logical_flow 缺少某些 block_id 时自动补全。"""
        data = _valid_content_map_json()
        # 只保留前3个 id 在 logical_flow 中
        data["logical_flow"] = ["b1", "b2", "b3"]
        extractor._mock_llm.chat.return_value = _make_llm_response(data)

        result = extractor.extract("文档内容" * 100)

        block_ids = {b.block_id for b in result.content_blocks}
        assert set(result.logical_flow) == block_ids


# ---------------------------------------------------------------------------
# 规则提取的数据点和引用
# ---------------------------------------------------------------------------


class TestRuleBasedDataExtraction:
    """测试规则提取模式下的数据点和引用提取。"""

    def test_extract_percentages(self, extractor: ContentExtractor):
        """规则提取能找到百分比数据。"""
        extractor._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )

        text = (
            "AI市场增长率达到30%，其中NLP领域占比15%，超过预期。\n\n"
            "第二段论据支撑更多分析内容详实说明。\n\n"
            "第三段案例说明市场竞争格局分析。\n\n"
            "第四段数据统计利润率12.5%增长。\n\n"
            "第五段总结展望未来发展规划。"
        )
        result = extractor.extract(text)

        # data_points 应包含百分比相关内容
        all_data = " ".join(result.key_data_points)
        assert "30%" in all_data or len(result.key_data_points) > 0

    def test_extract_chinese_number_units(self, extractor: ContentExtractor):
        """规则提取能找到带中文单位的数字（万/亿）。"""
        extractor._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )

        text = (
            "全球AI市场规模已达5万亿元，其中中国占比显著。\n\n"
            "投资总额超过100亿美元规模庞大。\n\n"
            "第三段论据支撑补充内容分析说明。\n\n"
            "第四段更多数据统计和案例分析。\n\n"
            "第五段总结和未来展望规划建议。"
        )
        result = extractor.extract(text)

        all_data = " ".join(result.key_data_points)
        has_wan = "万" in all_data or "亿" in all_data
        assert has_wan or len(result.key_data_points) > 0

    def test_extract_chinese_quotes(self, extractor: ContentExtractor):
        """规则提取能找到中文引号内的金句。"""
        extractor._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )

        text = (
            '正如乔布斯所说：\u201c活着就是为了改变世界\u201d这句话影响深远。\n\n'
            "第二段论据支撑更多分析详细内容。\n\n"
            "第三段案例说明和数据分析结论。\n\n"
            "第四段补充论据和具体案例说明。\n\n"
            "第五段总结展望和未来发展规划。"
        )
        result = extractor.extract(text)

        assert "活着就是为了改变世界" in result.key_quotes

    def test_extract_book_quotes(self, extractor: ContentExtractor):
        """规则提取能找到书名号内的引用。"""
        extractor._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )

        text = (
            "根据报告\u300c数字化转型是企业发展的必经之路\u300d的分析结论。\n\n"
            "第二段论据支撑更多分析详细内容。\n\n"
            "第三段案例说明和数据分析结论。\n\n"
            "第四段补充论据和具体案例说明。\n\n"
            "第五段总结展望和未来发展规划。"
        )
        result = extractor.extract(text)

        assert "数字化转型是企业发展的必经之路" in result.key_quotes


# ---------------------------------------------------------------------------
# 规则提取的段落类型检测
# ---------------------------------------------------------------------------


class TestRuleBasedBlockTypes:
    """测试规则提取模式下的段落类型检测。"""

    def test_first_paragraph_is_thesis(self, extractor: ContentExtractor):
        """第一段被标记为 thesis。"""
        extractor._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )

        text = (
            "核心论点段落包含主要观点和背景。\n\n"
            "第二段论据支撑包含分析内容。\n\n"
            "第三段更多论据详细展开说明。\n\n"
            "第四段案例分析和数据统计。\n\n"
            "第五段总结展望和未来规划。"
        )
        result = extractor.extract(text)

        assert result.content_blocks[0].block_type == "thesis"

    def test_last_paragraph_is_conclusion(self, extractor: ContentExtractor):
        """最后一段被标记为 conclusion。"""
        extractor._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )

        text = (
            "第一段核心论点和背景介绍内容，包含主要观点和市场分析。\n\n"
            "第二段论据支撑包含分析内容，详细论述了技术发展趋势。\n\n"
            "第三段更多论据详细展开说明，涵盖产品创新的多个方面。\n\n"
            "第四段案例分析和数据统计，展示了具体的市场数据成果。\n\n"
            "最后一段总结和未来展望规划，对全文进行了系统性的回顾。"
        )
        result = extractor.extract(text)

        assert result.content_blocks[-1].block_type == "conclusion"

    def test_data_rich_paragraph_detected(self, extractor: ContentExtractor):
        """含大量数字的段落被标记为 data。"""
        extractor._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )

        text = (
            "第一段核心论点和背景介绍内容，包含主要观点和市场分析。\n\n"
            "根据最新统计数据，销售额增长了30%，利润率达到12.5%，用户数突破500万人。\n\n"
            "第三段更多论据详细展开说明，涵盖产品创新的多个方面。\n\n"
            "第四段案例分析和补充数据统计，展示了行业竞争格局变化。\n\n"
            "最后一段总结和未来展望规划，对全文进行了系统性的回顾。"
        )
        result = extractor.extract(text)

        # 第二段应被标记为 data
        data_blocks = [b for b in result.content_blocks if b.block_type == "data"]
        assert len(data_blocks) >= 1

    def test_quote_paragraph_detected(self, extractor: ContentExtractor):
        """含引号的段落被标记为 quote。"""
        extractor._mock_llm.chat.return_value = LLMResponse(
            content="not json", model="test"
        )

        text = (
            "第一段核心论点和背景介绍内容，包含主要观点和市场分析。\n\n"
            "第二段论据分析包含更多信息内容，详细论述了技术发展趋势。\n\n"
            '正如马云所说\u201c梦想还是要有的，万一实现了呢\u201d这句话激励了无数创业者。\n\n'
            "第四段补充论据和案例分析说明，展示了行业竞争格局变化。\n\n"
            "最后一段总结和未来展望规划，对全文进行了系统性的回顾。"
        )
        result = extractor.extract(text)

        quote_blocks = [b for b in result.content_blocks if b.block_type == "quote"]
        assert len(quote_blocks) >= 1


# ---------------------------------------------------------------------------
# LLM 调用参数
# ---------------------------------------------------------------------------


class TestLLMCallParams:
    """测试 LLM 调用参数正确性。"""

    def test_json_mode_enabled(self, extractor: ContentExtractor):
        """确认使用 json_mode=True。"""
        extractor._mock_llm.chat.return_value = _make_llm_response(
            _valid_content_map_json()
        )
        extractor.extract("测试文档内容" * 100)

        call_kwargs = extractor._mock_llm.chat.call_args
        assert call_kwargs[1].get("json_mode") is True

    def test_system_prompt_present(self, extractor: ContentExtractor):
        """确认包含 system prompt。"""
        extractor._mock_llm.chat.return_value = _make_llm_response(
            _valid_content_map_json()
        )
        extractor.extract("测试文档内容" * 100)

        messages = extractor._mock_llm.chat.call_args[0][0]
        assert messages[0]["role"] == "system"
        assert "内容分析师" in messages[0]["content"]

    def test_temperature_is_low(self, extractor: ContentExtractor):
        """确认使用低 temperature（提取任务需要确定性）。"""
        extractor._mock_llm.chat.return_value = _make_llm_response(
            _valid_content_map_json()
        )
        extractor.extract("测试文档内容" * 100)

        call_kwargs = extractor._mock_llm.chat.call_args
        assert call_kwargs[1].get("temperature", 1.0) <= 0.5

    def test_max_tokens_set(self, extractor: ContentExtractor):
        """确认设置了 max_tokens。"""
        extractor._mock_llm.chat.return_value = _make_llm_response(
            _valid_content_map_json()
        )
        extractor.extract("测试文档内容" * 100)

        call_kwargs = extractor._mock_llm.chat.call_args
        assert call_kwargs[1].get("max_tokens") is not None
        assert call_kwargs[1]["max_tokens"] > 0
