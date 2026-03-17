"""深度内容提取器 - 阶段1.5：从文档中提取结构化信息供后续阶段使用。

在 DocumentAnalyzer（主题/受众/风格分析）和 OutlineGenerator 之间运行。
输出结构化的 ContentMap，包含：核心论点、支撑论据、关键数据、引用金句、段落归属。
"""

from __future__ import annotations

import logging
import re

from src.agents.utils import extract_json_obj
from src.llm.llm_client import LLMClient, create_llm_client
from src.ppt.models import ContentBlock, ContentMap

log = logging.getLogger("ppt")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 送给 LLM 的文本最大字符数（约 12k tokens for 中文）
_MAX_INPUT_CHARS = 24000

# 内容块数量范围
_MIN_BLOCKS = 4
_MAX_BLOCKS = 20

_SYSTEM_PROMPT = """\
你是一位资深内容分析师。你的任务是从文档中提取结构化信息，为 PPT 制作做准备。

分析步骤：
1. 通读全文，找到核心论点（document_thesis）
2. 识别文档的逻辑结构：论点 → 论据 → 数据/案例
3. 将文档拆分为独立的内容块（content_blocks），每块是一个可以独立展示的信息单元
4. 为每个内容块评估重要性（1-5分）
5. 提取所有具体数据点（数字、百分比、对比数据）
6. 提取所有值得引用的金句

关键原则：
- 每个内容块的 summary 必须包含具体事实和数据，不能是空泛描述
- source_text 要保留原文关键段落，供后续文案创作参考
- 内容块数量应该在 8-20 个之间（对应一份 10-15 页 PPT 的内容需求）
- importance >= 4 的内容块是核心内容，必须在 PPT 中展示
- importance <= 2 的内容块可以放在 speaker_notes 中

请以 JSON 格式返回，严格遵循以下结构：
{
  "document_thesis": "全文核心论点（一句话）",
  "content_blocks": [
    {
      "block_id": "b1",
      "block_type": "thesis|argument|data|quote|example|conclusion",
      "title": "内容块标题（10-15字）",
      "summary": "核心内容摘要（50-100字，保留关键数据和事实）",
      "source_text": "原文关键段落片段",
      "importance": 5
    }
  ],
  "logical_flow": ["b1", "b2", "b3"],
  "key_data_points": ["市场规模5.2万亿", "增长率30%"],
  "key_quotes": ["值得引用的金句原文"]
}

注意：
- block_type 必须是以下之一：thesis, argument, data, quote, example, conclusion
- importance 必须是 1-5 之间的整数
- content_blocks 至少包含 4 个，最多 20 个
- logical_flow 必须包含所有 block_id，按建议展示顺序排列
- key_data_points 提取文档中所有具体数字和百分比
- key_quotes 提取文档中有影响力的原句
"""

# 有效的 block_type 值
_VALID_BLOCK_TYPES = frozenset(
    {"thesis", "argument", "data", "quote", "example", "conclusion"}
)


class ContentExtractor:
    """深度内容提取器 -- 从文档中提取结构化信息供后续阶段使用。

    在 DocumentAnalyzer（主题/受众/风格分析）和 OutlineGenerator 之间运行。
    输出结构化的 ContentMap，包含：核心论点、支撑论据、关键数据、引用金句、段落归属。
    """

    def __init__(self, config: dict):
        """创建 LLM client。

        Args:
            config: 项目配置字典，需包含 llm 配置段。
        """
        self._llm: LLMClient = create_llm_client(config.get("llm", {}))

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def extract(self, text: str) -> ContentMap:
        """从文档中提取结构化内容地图。

        流程：
        1. 预处理文本（截断到 max_tokens 限制内）
        2. 调用 LLM 提取结构化信息（json_mode=True）
        3. 解析 JSON 返回 ContentMap
        4. LLM 失败时降级为规则提取

        Args:
            text: 原始文档文本。

        Returns:
            ContentMap 对象。
        """
        cleaned = self._preprocess(text)
        if not cleaned:
            return self._empty_content_map()

        raw_json = self._call_llm(cleaned)
        return self._parse_result(raw_json, cleaned)

    # ------------------------------------------------------------------
    # 内部方法：预处理
    # ------------------------------------------------------------------

    def _preprocess(self, text: str) -> str:
        """预处理文本：清理无关字符，截断到最大长度。"""
        # 移除连续空白行（保留单个换行）
        cleaned = re.sub(r"\n{3,}", "\n\n", text)
        # 移除行内多余空白
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        # 移除不可见控制字符（保留换行和制表符）
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)
        cleaned = cleaned.strip()

        # 截断到最大长度
        if len(cleaned) > _MAX_INPUT_CHARS:
            truncated = cleaned[:_MAX_INPUT_CHARS]
            last_period = max(
                truncated.rfind("\u3002"),
                truncated.rfind("\uff01"),
                truncated.rfind("\uff1f"),
                truncated.rfind("\n"),
            )
            if last_period > _MAX_INPUT_CHARS * 0.8:
                truncated = truncated[: last_period + 1]
            cleaned = truncated

        return cleaned

    # ------------------------------------------------------------------
    # 内部方法：LLM 调用
    # ------------------------------------------------------------------

    def _call_llm(self, text: str) -> dict | None:
        """调用 LLM 提取结构化内容，返回解析后的 JSON 字典。"""
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"请从以下文档中提取结构化内容：\n\n{text}",
            },
        ]

        try:
            response = self._llm.chat(
                messages,
                temperature=0.3,
                json_mode=True,
                max_tokens=4096,
            )
            return extract_json_obj(response.content)
        except Exception as e:
            log.warning("LLM 内容提取调用失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 内部方法：解析结果
    # ------------------------------------------------------------------

    def _parse_result(self, raw: dict | None, text: str) -> ContentMap:
        """将 LLM 返回的 JSON 解析为 ContentMap，含降级处理。"""
        if raw is None:
            log.warning("LLM 返回无效 JSON，使用 fallback 规则提取")
            return self._fallback_extract(text)

        try:
            return self._build_content_map(raw, text)
        except Exception as e:
            log.warning("解析 LLM 内容提取结果失败: %s，使用 fallback", e)
            return self._fallback_extract(text)

    def _build_content_map(self, raw: dict, text: str) -> ContentMap:
        """从 LLM 返回的字典构建 ContentMap。"""
        # 解析 document_thesis
        thesis = str(raw.get("document_thesis", "")).strip()
        if not thesis:
            thesis = text[:100].replace("\n", " ").strip()

        # 解析 content_blocks
        raw_blocks = raw.get("content_blocks", [])
        if not isinstance(raw_blocks, list):
            raw_blocks = []

        blocks: list[ContentBlock] = []
        for i, rb in enumerate(raw_blocks):
            if not isinstance(rb, dict):
                continue
            block = self._parse_single_block(rb, i)
            if block is not None:
                blocks.append(block)

        # 块数量不足时补充 fallback
        if len(blocks) < _MIN_BLOCKS:
            log.warning(
                "LLM 仅返回 %d 个内容块，不足 %d，使用 fallback",
                len(blocks),
                _MIN_BLOCKS,
            )
            return self._fallback_extract(text)

        # 截断过多的块
        if len(blocks) > _MAX_BLOCKS:
            blocks = blocks[:_MAX_BLOCKS]

        # 解析 logical_flow
        raw_flow = raw.get("logical_flow", [])
        if not isinstance(raw_flow, list):
            raw_flow = []
        block_ids = {b.block_id for b in blocks}
        logical_flow = [str(f) for f in raw_flow if str(f) in block_ids]
        # 补全缺失的 block_id
        for b in blocks:
            if b.block_id not in logical_flow:
                logical_flow.append(b.block_id)

        # 解析 key_data_points
        raw_data = raw.get("key_data_points", [])
        key_data_points = (
            [str(d) for d in raw_data if d]
            if isinstance(raw_data, list)
            else []
        )

        # 解析 key_quotes
        raw_quotes = raw.get("key_quotes", [])
        key_quotes = (
            [str(q) for q in raw_quotes if q]
            if isinstance(raw_quotes, list)
            else []
        )

        return ContentMap(
            document_thesis=thesis,
            content_blocks=blocks,
            logical_flow=logical_flow,
            key_data_points=key_data_points,
            key_quotes=key_quotes,
        )

    def _parse_single_block(self, rb: dict, index: int) -> ContentBlock | None:
        """解析单个内容块，返回 None 表示跳过。"""
        block_id = str(rb.get("block_id", f"b{index + 1}"))
        block_type = str(rb.get("block_type", "argument"))
        if block_type not in _VALID_BLOCK_TYPES:
            block_type = "argument"

        title = str(rb.get("title", "")).strip()
        summary = str(rb.get("summary", "")).strip()
        source_text = str(rb.get("source_text", "")).strip()

        # 必须有标题和摘要
        if not title or not summary:
            return None

        importance = rb.get("importance", 3)
        if not isinstance(importance, int) or importance < 1:
            importance = 1
        elif importance > 5:
            importance = 5

        return ContentBlock(
            block_id=block_id,
            block_type=block_type,
            title=title,
            summary=summary,
            source_text=source_text or summary,
            importance=importance,
        )

    # ------------------------------------------------------------------
    # 内部方法：降级提取（规则方案）
    # ------------------------------------------------------------------

    def _fallback_extract(self, text: str) -> ContentMap:
        """当 LLM 失败时的规则降级提取。

        策略：
        1. 按段落拆分文本
        2. 用关键词/正则识别数据、引用
        3. 每个有意义的段落生成一个 ContentBlock
        """
        paragraphs = self._split_paragraphs(text)

        blocks: list[ContentBlock] = []
        data_points: list[str] = []
        quotes: list[str] = []

        for i, para in enumerate(paragraphs):
            if len(blocks) >= _MAX_BLOCKS:
                break

            block_type = self._detect_block_type(para, i, len(paragraphs))
            importance = self._estimate_importance(para, i, len(paragraphs))

            blocks.append(
                ContentBlock(
                    block_id=f"b{i + 1}",
                    block_type=block_type,
                    title=self._generate_title(para),
                    summary=para[:200] if len(para) > 200 else para,
                    source_text=para[:500] if len(para) > 500 else para,
                    importance=importance,
                )
            )

            # 提取数据点
            data_points.extend(self._extract_data_points(para))

            # 提取引用
            quotes.extend(self._extract_quotes(para))

        # 至少保证一个块
        if not blocks:
            blocks.append(
                ContentBlock(
                    block_id="b1",
                    block_type="thesis",
                    title="文档内容",
                    summary=text[:200] if text else "空文档",
                    source_text=text[:500] if text else "",
                    importance=3,
                )
            )

        thesis = blocks[0].summary[:100] if blocks else "文档内容待分析"
        logical_flow = [b.block_id for b in blocks]

        return ContentMap(
            document_thesis=thesis,
            content_blocks=blocks,
            logical_flow=logical_flow,
            key_data_points=data_points[:20],
            key_quotes=quotes[:10],
        )

    def _split_paragraphs(self, text: str) -> list[str]:
        """将文本按段落拆分，过滤过短段落。"""
        # 按双换行或 markdown 标题拆分
        raw_parts = re.split(r"\n{2,}|(?=\n#{1,3}\s)", text)
        paragraphs: list[str] = []
        for part in raw_parts:
            cleaned = part.strip()
            # 过滤过短的段落（少于 20 字）
            if len(cleaned) >= 20:
                paragraphs.append(cleaned)

        return paragraphs

    def _detect_block_type(self, para: str, index: int, total: int) -> str:
        """基于规则检测段落的内容类型。"""
        # 第一段通常是论点
        if index == 0:
            return "thesis"

        # 最后一段通常是结论
        if index == total - 1:
            return "conclusion"

        # 含大量数字 -> data
        numbers = re.findall(r"\d+[%\uff05]|\d+\.\d+|\d{3,}", para)
        if len(numbers) >= 2:
            return "data"

        # 含引号 -> quote
        if re.search(r'[\u201c\u201d\u300c\u300d""]', para):
            return "quote"

        # 含"例如"/"比如"/"案例" -> example
        if re.search(r"例如|比如|案例|举例", para):
            return "example"

        return "argument"

    def _estimate_importance(self, para: str, index: int, total: int) -> int:
        """基于规则估算段落重要性。"""
        score = 3  # 默认中等

        # 首段和末段较重要
        if index == 0 or index == total - 1:
            score = 4

        # 含数据的段落较重要
        if re.search(r"\d+[%\uff05]|\d+\.\d+", para):
            score = min(score + 1, 5)

        # 过短段落不太重要
        if len(para) < 50:
            score = max(score - 1, 1)

        # 含强调关键词
        if re.search(r"核心|关键|重要|必须|首先|最|突破", para):
            score = min(score + 1, 5)

        return score

    def _generate_title(self, para: str) -> str:
        """从段落生成简短标题。"""
        # 如果段落以 markdown 标题开头，提取标题
        md_match = re.match(r"^#{1,3}\s+(.+?)$", para, re.MULTILINE)
        if md_match:
            title = md_match.group(1).strip()
            return title[:30] if len(title) > 30 else title

        # 取第一行/第一句
        first_line = para.split("\n")[0].strip()
        # 取第一个句号前的内容
        sentence_end = re.search(r"[\u3002\uff01\uff1f.!?]", first_line)
        if sentence_end and sentence_end.start() > 5:
            title = first_line[: sentence_end.start()]
        else:
            title = first_line

        # 截断
        if len(title) > 30:
            title = title[:27] + "..."
        return title

    @staticmethod
    def _extract_data_points(text: str) -> list[str]:
        """从文本中提取数据点（数字+上下文）。"""
        data_points: list[str] = []

        # 匹配带单位的数字
        patterns = [
            r"[\u4e00-\u9fff]*\d+(?:\.\d+)?[%\uff05][\u4e00-\u9fff]*",
            r"[\u4e00-\u9fff]*\d+(?:\.\d+)?[\u4e07\u4ebf\u5146][\u4e00-\u9fff]*",
            r"[\u4e00-\u9fff]*\d+(?:\.\d+)?[\u5143\u7f8e\u5143][\u4e00-\u9fff]*",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            for m in matches:
                clean = m.strip()
                if len(clean) >= 3:
                    data_points.append(clean)

        return data_points

    @staticmethod
    def _extract_quotes(text: str) -> list[str]:
        """从文本中提取引用/金句。"""
        quotes: list[str] = []

        # 中文引号
        cn_quotes = re.findall(r"\u201c([^\u201d]{5,100})\u201d", text)
        quotes.extend(cn_quotes)

        # 书名号引用
        book_quotes = re.findall(r"\u300c([^\u300d]{5,100})\u300d", text)
        quotes.extend(book_quotes)

        return quotes

    def _empty_content_map(self) -> ContentMap:
        """返回空文档的最小 ContentMap。"""
        return ContentMap(
            document_thesis="空文档",
            content_blocks=[
                ContentBlock(
                    block_id="b1",
                    block_type="thesis",
                    title="空文档",
                    summary="文档内容为空",
                    source_text="",
                    importance=1,
                )
            ],
            logical_flow=["b1"],
            key_data_points=[],
            key_quotes=[],
        )
