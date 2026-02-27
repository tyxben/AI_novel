"""简单分段器 - 基于规则的文本分段，无外部 API 依赖"""

import re

from src.segmenter.text_segmenter import TextSegmenter


# 中文句末标点（用于句子边界检测）
_SENTENCE_ENDINGS = re.compile(r"([。！？…]+)")


class SimpleSegmenter(TextSegmenter):
    """基于规则的文本分段器。

    分段逻辑:
      1. 按段落（双换行）拆分原始文本
      2. 将每个段落进一步拆分为完整句子
      3. 逐句合并，直到达到 max_chars 上限后切出一个片段
      4. 片段不会在句子中间断开
    """

    def __init__(self, config: dict) -> None:
        self.max_chars: int = config.get("max_chars", 200)
        self.min_chars: int = config.get("min_chars", 50)

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def segment(self, text: str) -> list[dict]:
        """将文本按规则拆分为多个片段。

        Args:
            text: 待分段的完整文本。

        Returns:
            分段结果列表，每个元素为 {"text": str, "index": int}。
        """
        if not text or not text.strip():
            return []

        sentences = self._split_to_sentences(text)
        segments = self._merge_sentences(sentences)
        return [{"text": seg, "index": idx} for idx, seg in enumerate(segments)]

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    @staticmethod
    def _split_to_sentences(text: str) -> list[str]:
        """将文本拆分为句子列表。

        先按段落（双换行）拆分，再按句末标点拆分每个段落，
        保留标点并附在对应句子末尾。
        """
        paragraphs = re.split(r"\n\s*\n", text.strip())
        sentences: list[str] = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # 用句末标点拆分，保留分隔符
            parts = _SENTENCE_ENDINGS.split(para)

            # 将标点重新粘回前一个片段：
            # split 结果形如 ["内容", "。", "内容", "！", ...]
            i = 0
            while i < len(parts):
                fragment = parts[i].strip()
                # 如果下一个元素是标点，合并到当前片段
                if i + 1 < len(parts) and _SENTENCE_ENDINGS.fullmatch(parts[i + 1]):
                    fragment += parts[i + 1]
                    i += 2
                else:
                    i += 1

                if fragment:
                    sentences.append(fragment)

        return sentences

    def _merge_sentences(self, sentences: list[str]) -> list[str]:
        """将句子列表合并为满足长度约束的片段列表。

        合并规则:
          - 逐句追加到当前缓冲区
          - 当缓冲区长度 >= max_chars 时，切出一个片段
          - 如果剩余缓冲区 < min_chars 且还有后续句子，继续追加
          - 最后一个片段若 < min_chars，合并到前一个片段
        """
        if not sentences:
            return []

        segments: list[str] = []
        buffer = ""

        for sentence in sentences:
            # 如果当前缓冲区加上新句子会超过上限，且缓冲区已有足够内容
            if buffer and len(buffer) + len(sentence) > self.max_chars and len(buffer) >= self.min_chars:
                segments.append(buffer)
                buffer = sentence
            else:
                buffer += sentence

        # 处理最后的缓冲区
        if buffer:
            # 如果最后一段太短且前面有片段，合并到前一个
            if len(buffer) < self.min_chars and segments:
                segments[-1] += buffer
            else:
                segments.append(buffer)

        return segments
