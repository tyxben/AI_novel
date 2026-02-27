"""LLM 分段器 - 基于 LLM 的智能文本分段（支持多后端）"""

import json
import logging

from src.segmenter.text_segmenter import TextSegmenter

log = logging.getLogger("novel")

_SYSTEM_PROMPT = """\
你是一个专业的短视频文案分段助手。你的任务是将小说文本拆分成适合短视频旁白的片段。

规则:
1. 每个片段 50-200 个字符
2. 保持完整句子，不要在句子中间断开
3. 每个片段应该是一个完整的叙事单元（一个场景、一个动作、一段对话等）
4. 保留原文，不要修改、删减或添加任何内容
5. 返回一个 JSON 数组，数组中每个元素是一个字符串片段

输出格式（仅输出 JSON，不要包含其他内容）:
["片段1", "片段2", "片段3"]
"""

# 单次 API 调用处理的最大字符数（避免 token 超限）
_CHUNK_SIZE = 3000


class LLMSegmenter(TextSegmenter):
    """基于 LLM 的智能文本分段器（支持多后端）。

    使用大语言模型理解上下文后进行分段，效果优于规则方法。
    支持 OpenAI、DeepSeek、Gemini、Ollama 等后端。
    当 API 调用失败时自动回退到 SimpleSegmenter。
    """

    def __init__(self, config: dict) -> None:
        self._llm_config = config.get("llm", {})
        self.temperature: float = self._llm_config.get("temperature", 0.3)
        self.max_chars: int = config.get("max_chars", 200)
        self.min_chars: int = config.get("min_chars", 50)
        self._config = config
        self._llm_client = None

    def _get_llm_client(self):
        """创建或返回缓存的 LLM 客户端实例。"""
        if self._llm_client is None:
            from src.llm import create_llm_client

            self._llm_client = create_llm_client(self._llm_config)
        return self._llm_client

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def segment(self, text: str) -> list[dict]:
        """使用 LLM 将文本拆分为多个片段。

        如果文本过长，会分块调用 API 后合并结果。
        API 调用失败时自动回退到 SimpleSegmenter。

        Args:
            text: 待分段的完整文本。

        Returns:
            分段结果列表，每个元素为 {"text": str, "index": int}。
        """
        if not text or not text.strip():
            return []

        try:
            chunks = self._split_into_chunks(text)
            all_segments: list[str] = []

            for chunk in chunks:
                segments = self._call_api(chunk)
                all_segments.extend(segments)

            if not all_segments:
                log.warning("LLM 返回空结果，回退到简单分段")
                return self._fallback(text)

            return [{"text": seg, "index": idx} for idx, seg in enumerate(all_segments)]

        except Exception as e:
            log.warning("LLM 分段失败 (%s)，回退到简单分段", e)
            return self._fallback(text)

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _call_api(self, text: str) -> list[str]:
        """调用 LLM API 进行分段。

        Args:
            text: 单个文本块。

        Returns:
            分段后的字符串列表。
        """
        client = self._get_llm_client()
        response = client.chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=self.temperature,
            json_mode=True,
        )

        content = response.content
        if not content:
            return []

        parsed = json.loads(content)

        # 兼容多种返回格式:
        #   1. 纯数组 ["段1", "段2"]
        #   2. {"segments": ["段1", "段2"]}  — 值为 list
        #   3. {"片段1": "段1", "片段2": "段2"} — 值为 str
        if isinstance(parsed, list):
            segments = parsed
        elif isinstance(parsed, dict):
            # 优先找值为 list 的字段
            list_val = next(
                (v for v in parsed.values() if isinstance(v, list)),
                None,
            )
            if list_val is not None:
                segments = list_val
            else:
                # 所有值都是字符串时，按 key 排序取 values
                segments = list(parsed.values())
        else:
            return []

        # 过滤空字符串并确保全部为字符串类型
        return [str(s).strip() for s in segments if str(s).strip()]

    @staticmethod
    def _split_into_chunks(text: str) -> list[str]:
        """将长文本按段落边界拆分为不超过 _CHUNK_SIZE 的块。

        Args:
            text: 完整文本。

        Returns:
            文本块列表。
        """
        text = text.strip()
        if len(text) <= _CHUNK_SIZE:
            return [text]

        paragraphs = text.split("\n")
        chunks: list[str] = []
        current = ""

        for para in paragraphs:
            if current and len(current) + len(para) + 1 > _CHUNK_SIZE:
                chunks.append(current.strip())
                current = para
            else:
                current = current + "\n" + para if current else para

        if current.strip():
            chunks.append(current.strip())

        return chunks

    def _fallback(self, text: str) -> list[dict]:
        """回退到简单分段器。

        Args:
            text: 待分段的完整文本。

        Returns:
            分段结果列表。
        """
        from src.segmenter.simple_segmenter import SimpleSegmenter
        return SimpleSegmenter(self._config).segment(text)
