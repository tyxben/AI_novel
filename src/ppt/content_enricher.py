"""内容增强器 -- 通过联网搜索/LLM知识补充文档内容

三级增强策略：
- Level 0 (none): 仅文档内容，不做增强
- Level 1 (llm): 利用 LLM 自身知识补充背景数据和行业信息
- Level 2 (web): 联网搜索补充最新数据和事实
"""

from __future__ import annotations

import logging
from enum import Enum

from src.llm import LLMClient, create_llm_client
from src.ppt.models import ContentBlock, ContentMap

log = logging.getLogger("ppt")


class EnrichLevel(str, Enum):
    NONE = "none"  # No enrichment
    LLM = "llm"  # LLM knowledge only (free, fast)
    WEB = "web"  # Web search + LLM (most comprehensive)


class ContentEnricher:
    """分析文档内容缺口，通过联网搜索或LLM知识进行补充增强。"""

    def __init__(self, config: dict):
        self.llm: LLMClient = create_llm_client(config.get("llm", {}))
        self.level = EnrichLevel(
            config.get("ppt", {}).get("enrich_level", "llm")
        )

    def enrich(
        self,
        content_map: ContentMap,
        document_text: str = "",
        deck_type: str | None = None,
    ) -> ContentMap:
        """增强 ContentMap，补充缺失的数据和背景信息。

        Args:
            content_map: 已提取的文档内容结构
            document_text: 原始文档文本（用于上下文参考）
            deck_type: PPT 类型字符串（如 "business_report"），用于覆盖默认增强级别

        Returns:
            增强后的 ContentMap（原有内容 + 补充内容）
        """
        # Determine effective enrich level, allowing deck_type strategy to
        # override the config default (but not an explicit user override).
        effective_level = self.level
        if deck_type is not None:
            try:
                from src.ppt.deck_strategies import get_strategy
                from src.ppt.models import DeckType

                strategy = get_strategy(DeckType(deck_type))
                default = strategy.get("default_enrich_level", "llm")
                # Strategy default overrides config ONLY if config is the default
                if self.level == EnrichLevel.LLM:
                    effective_level = EnrichLevel(default)
            except (ImportError, KeyError, ValueError):
                pass

        if effective_level == EnrichLevel.NONE:
            return content_map

        # Step 1: Identify knowledge gaps
        gaps = self._identify_gaps(content_map)
        if not gaps:
            log.info("文档内容完整，无需补充")
            return content_map

        # Step 2: Research to fill gaps
        if effective_level == EnrichLevel.WEB:
            supplementary = self._web_research(gaps, content_map)
        else:  # LLM level
            supplementary = self._llm_research(gaps, content_map)

        if not supplementary:
            return content_map

        # Step 3: Merge supplementary blocks into content_map
        return self._merge(content_map, supplementary)

    def _identify_gaps(self, content_map: ContentMap) -> list[dict]:
        """让 LLM 分析内容缺口。

        Returns:
            list of dicts, each with keys:
            topic, gap_type, search_query, description
        """
        from src.agents.utils import extract_json_array

        # Build a summary of existing content
        blocks_summary = "\n".join(
            f"- [{b.block_type}] {b.title}: {b.summary}"
            for b in content_map.content_blocks
        )

        system_msg = (
            "你是一位资深内容策略师。分析以下文档的内容结构，"
            "找出制作 PPT 时缺失的关键信息。\n\n"
            "缺口类型：\n"
            "- missing_data: 缺少具体数据（市场规模、增长率、用户量等）\n"
            "- missing_context: 缺少行业背景、竞品对比、发展趋势\n"
            "- missing_evidence: 缺少支撑论据、案例、专家观点\n\n"
            "只找最重要的3-5个缺口。如果文档信息已经很充分，返回空数组。\n"
            "对每个缺口，生成一个精准的搜索查询"
            "（中文或英文，选择更可能找到结果的语言）。"
        )

        data_points_str = (
            ", ".join(content_map.key_data_points)
            if content_map.key_data_points
            else "无"
        )
        user_msg = (
            f"## 文档核心论点\n{content_map.document_thesis}\n\n"
            f"## 已有内容块\n{blocks_summary}\n\n"
            f"## 已有数据点\n{data_points_str}\n\n"
            "请分析内容缺口，返回 JSON 数组：\n"
            '[{"topic": "缺口主题", "gap_type": "missing_data", '
            '"search_query": "搜索关键词", '
            '"description": "为什么需要这个信息"}]'
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        response = self.llm.chat(
            messages, temperature=0.3, json_mode=True, max_tokens=1024
        )

        gaps = extract_json_array(response.content)
        if gaps is None:
            return []

        # Validate and limit to 5
        valid_gaps = []
        for g in gaps[:5]:
            if isinstance(g, dict) and g.get("search_query"):
                valid_gaps.append(g)
        return valid_gaps

    def _web_research(
        self, gaps: list[dict], content_map: ContentMap
    ) -> list[ContentBlock]:
        """通过网络搜索填补内容缺口。"""
        supplementary: list[ContentBlock] = []
        next_id = len(content_map.content_blocks) + 1

        for gap in gaps:
            query = gap.get("search_query", "")
            if not query:
                continue

            # Try web search
            search_results = self._search_web(query)
            if not search_results:
                # Fallback to LLM knowledge
                block = self._llm_fill_gap(gap, content_map, next_id)
                if block:
                    supplementary.append(block)
                    next_id += 1
                continue

            # Let LLM extract useful info from search results
            block = self._extract_from_search(gap, search_results, next_id)
            if block:
                supplementary.append(block)
                next_id += 1

        return supplementary

    def _search_web(self, query: str) -> list[dict]:
        """Execute web search. Returns list of {title, snippet, url}.

        Uses duckduckgo_search if available, otherwise returns empty list.
        """
        try:
            from duckduckgo_search import DDGS

            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=5):
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                            "url": r.get("href", ""),
                        }
                    )
            return results
        except ImportError:
            log.warning(
                "duckduckgo_search 未安装，跳过网络搜索。"
                "安装: pip install duckduckgo_search"
            )
            return []
        except Exception:
            log.warning("网络搜索失败", exc_info=True)
            return []

    def _extract_from_search(
        self,
        gap: dict,
        search_results: list[dict],
        block_id: int,
    ) -> ContentBlock | None:
        """Let LLM extract useful info from search results into a
        ContentBlock."""
        from src.agents.utils import extract_json_obj

        results_text = "\n\n".join(
            f"**{r['title']}**\n{r['snippet']}\n来源: {r['url']}"
            for r in search_results
        )

        system_msg = (
            "你是一位数据分析师。从以下搜索结果中提取与主题相关的关键信息。\n"
            "要求：\n"
            "1. 只提取有具体数据、事实、或专家观点的信息\n"
            "2. 必须标注信息来源\n"
            "3. 如果搜索结果中没有有用信息，返回 null\n"
            "4. summary 控制在50-100字\n"
            "5. source_text 保留原始搜索摘要作为引用来源"
        )

        user_msg = (
            f"## 需要补充的信息\n"
            f"主题: {gap.get('topic', '')}\n"
            f"描述: {gap.get('description', '')}\n\n"
            f"## 搜索结果\n{results_text}\n\n"
            "返回 JSON：\n"
            '{"title": "信息标题", "summary": "提取的关键信息'
            '（50-100字，含具体数据）", '
            '"source_text": "原始搜索摘要 + 来源URL"}\n'
            "如果没有有用信息，返回: null"
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        response = self.llm.chat(
            messages, temperature=0.2, json_mode=True, max_tokens=512
        )

        data = extract_json_obj(response.content)
        if not data or not data.get("title"):
            return None

        return ContentBlock(
            block_id=f"ext_{block_id}",
            block_type=_gap_type_to_block_type(gap.get("gap_type", "")),
            title=str(data.get("title", "")),
            summary=str(data.get("summary", "")),
            source_text=str(data.get("source_text", "")),
            importance=3,  # External data is supplementary, importance 3
            is_external=True,
        )

    def _llm_research(
        self, gaps: list[dict], content_map: ContentMap
    ) -> list[ContentBlock]:
        """Use LLM's own knowledge to fill content gaps (no web search)."""
        supplementary: list[ContentBlock] = []
        next_id = len(content_map.content_blocks) + 1

        for gap in gaps:
            block = self._llm_fill_gap(gap, content_map, next_id)
            if block:
                supplementary.append(block)
                next_id += 1

        return supplementary

    def _llm_fill_gap(
        self,
        gap: dict,
        content_map: ContentMap,
        block_id: int,
    ) -> ContentBlock | None:
        """Use LLM knowledge to fill a single gap."""
        from src.agents.utils import extract_json_obj

        system_msg = (
            "你是一位行业专家。根据文档主题，提供补充信息。\n"
            "要求：\n"
            "1. 只提供你确信正确的事实和数据\n"
            "2. 如果不确定，宁可不提供也不要编造\n"
            "3. 标注数据的大致时间范围（如'2024年数据'）\n"
            "4. summary 控制在50-100字，包含具体数据\n"
            "5. source_text 写'基于公开行业数据'或类似标注"
        )

        user_msg = (
            f"文档主题: {content_map.document_thesis}\n\n"
            f"需要补充的信息:\n"
            f"- 主题: {gap.get('topic', '')}\n"
            f"- 类型: {gap.get('gap_type', '')}\n"
            f"- 说明: {gap.get('description', '')}\n\n"
            "返回 JSON：\n"
            '{"title": "信息标题", "summary": "补充信息'
            '（50-100字，含具体数据）", '
            '"source_text": "信息来源标注"}\n'
            "如果你不确定，返回: null"
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        response = self.llm.chat(
            messages, temperature=0.3, json_mode=True, max_tokens=512
        )

        data = extract_json_obj(response.content)
        if not data or not data.get("title"):
            return None

        return ContentBlock(
            block_id=f"ext_{block_id}",
            block_type=_gap_type_to_block_type(gap.get("gap_type", "")),
            title=str(data.get("title", "")),
            summary=str(data.get("summary", "")),
            source_text=str(data.get("source_text", "")),
            importance=3,
            is_external=True,
        )

    @staticmethod
    def _merge(
        content_map: ContentMap, supplementary: list[ContentBlock]
    ) -> ContentMap:
        """Merge supplementary blocks into the ContentMap.

        Caps external blocks to max 3 to avoid overwhelming original content.
        """
        # Cap: max 3 total external blocks (including any already in content_map)
        existing_external = sum(
            1 for b in content_map.content_blocks if b.is_external
        )
        max_new = max(0, 3 - existing_external)
        supplementary = supplementary[:max_new]
        merged_blocks = list(content_map.content_blocks) + supplementary

        # Also add any data from supplementary to key_data_points
        new_data_points = list(content_map.key_data_points)
        for block in supplementary:
            if block.block_type == "data" and block.summary:
                new_data_points.append(block.summary)

        return ContentMap(
            document_thesis=content_map.document_thesis,
            content_blocks=merged_blocks,
            logical_flow=list(content_map.logical_flow)
            + [b.block_id for b in supplementary],
            key_data_points=new_data_points,
            key_quotes=list(content_map.key_quotes),
        )


def _gap_type_to_block_type(gap_type: str) -> str:
    """Map gap type to content block type."""
    mapping = {
        "missing_data": "data",
        "missing_context": "argument",
        "missing_evidence": "example",
    }
    return mapping.get(gap_type, "argument")
