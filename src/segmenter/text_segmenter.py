"""文本分段 - 抽象基类与工厂函数"""

from abc import ABC, abstractmethod


class TextSegmenter(ABC):
    """文本分段器抽象基类。

    所有分段器实现必须继承此类并实现 segment 方法。
    """

    @abstractmethod
    def segment(self, text: str) -> list[dict]:
        """将文本拆分为多个片段。

        Args:
            text: 待分段的完整文本。

        Returns:
            分段结果列表，每个元素为 {"text": str, "index": int}。
        """
        ...


def create_segmenter(config: dict) -> TextSegmenter:
    """根据配置创建对应的分段器实例。

    Args:
        config: 分段器配置字典，至少包含 method 字段。
            method="simple" -> SimpleSegmenter (默认)
            method="llm"    -> LLMSegmenter

    Returns:
        TextSegmenter 实例。
    """
    method = config.get("method", "simple")

    if method == "llm":
        from src.segmenter.llm_segmenter import LLMSegmenter
        return LLMSegmenter(config)
    else:
        from src.segmenter.simple_segmenter import SimpleSegmenter
        return SimpleSegmenter(config)
