"""风格分析工具 - 纯规则驱动，不依赖 LLM。

提供文本风格特征提取与对比能力，用于 StyleKeeper Agent。
"""

from __future__ import annotations

import re

from src.novel.models.quality import StyleMetrics

# ---------------------------------------------------------------------------
# 古典中文用词列表（用于 classical_word_ratio 计算）
# ---------------------------------------------------------------------------

_CLASSICAL_WORDS: list[str] = [
    "然则",
    "岂非",
    "何故",
    "且慢",
    "罢了",
    "不曾",
    "亦",
    "甚",
    "莫非",
    "尚且",
    "犹如",
    "且看",
    "遂",
    "皆",
    "乃",
    "兀自",
    "只道",
    "须知",
    "却是",
    "倒也",
    "端的",
    "好生",
    "休要",
    "怎地",
    "那厢",
    "这厢",
    "正是",
    "只见",
    "但见",
    "却说",
]

# ---------------------------------------------------------------------------
# 描写性词汇关键词（用于 description_ratio 估算）
# ---------------------------------------------------------------------------

_DESCRIPTION_MARKERS: list[str] = [
    "阳光",
    "月光",
    "夜色",
    "风",
    "雨",
    "雪",
    "花",
    "草",
    "树",
    "山",
    "水",
    "天空",
    "大地",
    "寂静",
    "沉默",
    "空气",
    "气氛",
    "色彩",
    "光芒",
    "光线",
    "温度",
    "声音",
    "远处",
    "近处",
    "周围",
    "四周",
    "笼罩",
    "弥漫",
    "飘荡",
    "回荡",
]

# ---------------------------------------------------------------------------
# 第一人称代词
# ---------------------------------------------------------------------------

_FIRST_PERSON_WORDS: list[str] = ["我", "咱", "俺", "本人", "在下", "小生", "老子", "本座"]

# ---------------------------------------------------------------------------
# 句子切分正则
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\.\n]+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n|\n")

# 中文对话正则：匹配中文引号 "" 或 「」 内容
_DIALOGUE_RE = re.compile(r'["\u201c][^"\u201d]*["\u201d]|[\u300c][^\u300d]*[\u300d]')


# ---------------------------------------------------------------------------
# StyleAnalysisTool
# ---------------------------------------------------------------------------


class StyleAnalysisTool:
    """纯规则驱动的风格分析工具，不依赖 LLM。"""

    def analyze(self, text: str) -> StyleMetrics:
        """分析文本风格特征，返回 StyleMetrics。

        Args:
            text: 待分析文本

        Returns:
            StyleMetrics 实例
        """
        if not text or not text.strip():
            return StyleMetrics(
                avg_sentence_length=0.0,
                dialogue_ratio=0.0,
                exclamation_ratio=0.0,
                paragraph_length=0.0,
                classical_word_ratio=0.0,
                description_ratio=0.0,
                first_person_ratio=0.0,
            )

        text = text.strip()

        # --- 句子分割 ---
        sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
        sentence_count = max(len(sentences), 1)

        # avg_sentence_length: 平均每句字符数
        total_sentence_chars = sum(len(s) for s in sentences)
        avg_sentence_length = total_sentence_chars / sentence_count

        # --- 对话占比 ---
        dialogue_matches = _DIALOGUE_RE.findall(text)
        dialogue_chars = sum(len(d) for d in dialogue_matches)
        dialogue_ratio = min(dialogue_chars / max(len(text), 1), 1.0)

        # --- 感叹句占比 ---
        # Count exclamation marks in original text (they are consumed by split)
        exclamation_count = text.count("！") + text.count("!")
        exclamation_ratio = min(exclamation_count / sentence_count, 1.0)

        # --- 段落平均长度 ---
        paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
        paragraph_count = max(len(paragraphs), 1)
        total_para_chars = sum(len(p) for p in paragraphs)
        paragraph_length = total_para_chars / paragraph_count

        # --- 古典用词占比 ---
        classical_count = 0
        for word in _CLASSICAL_WORDS:
            classical_count += text.count(word)
        # 以总字数为基准
        total_chars = max(len(text), 1)
        classical_word_ratio = min(classical_count / (total_chars / 10), 1.0)

        # --- 描写占比（基于关键词密度） ---
        desc_sentence_count = 0
        for s in sentences:
            for marker in _DESCRIPTION_MARKERS:
                if marker in s:
                    desc_sentence_count += 1
                    break
        description_ratio = desc_sentence_count / sentence_count

        # --- 第一人称占比 ---
        first_person_count = 0
        for s in sentences:
            for fp in _FIRST_PERSON_WORDS:
                if fp in s:
                    first_person_count += 1
                    break
        first_person_ratio = first_person_count / sentence_count

        return StyleMetrics(
            avg_sentence_length=round(avg_sentence_length, 2),
            dialogue_ratio=round(dialogue_ratio, 4),
            exclamation_ratio=round(exclamation_ratio, 4),
            paragraph_length=round(paragraph_length, 2),
            classical_word_ratio=round(classical_word_ratio, 4),
            description_ratio=round(description_ratio, 4),
            first_person_ratio=round(first_person_ratio, 4),
        )

    def compare(
        self,
        metrics: StyleMetrics,
        reference: StyleMetrics,
        tolerances: dict[str, float] | None = None,
    ) -> tuple[float, list[str]]:
        """比较两组 StyleMetrics，返回 (相似度分数, 偏差描述列表)。

        Args:
            metrics: 待检查文本的风格指标
            reference: 参考风格指标
            tolerances: 每个字段的容差字典，默认使用内置容差

        Returns:
            (similarity_score, deviations):
            - similarity_score: 0.0 ~ 1.0
            - deviations: 偏差描述列表
        """
        default_tolerances: dict[str, float] = {
            "avg_sentence_length": 10.0,
            "dialogue_ratio": 0.15,
            "exclamation_ratio": 0.10,
            "paragraph_length": 80.0,
            "classical_word_ratio": 0.10,
            "description_ratio": 0.15,
            "first_person_ratio": 0.20,
        }
        tol = {**default_tolerances, **(tolerances or {})}

        _FIELD_NAMES: dict[str, str] = {
            "avg_sentence_length": "平均句长",
            "dialogue_ratio": "对话占比",
            "exclamation_ratio": "感叹句占比",
            "paragraph_length": "段落平均长度",
            "classical_word_ratio": "古风用词占比",
            "description_ratio": "描写占比",
            "first_person_ratio": "第一人称占比",
        }

        compare_fields = [
            "avg_sentence_length",
            "dialogue_ratio",
            "exclamation_ratio",
            "paragraph_length",
        ]
        # 可选字段仅在参考值非 None 时参与比较
        for optional_field in ("classical_word_ratio", "description_ratio", "first_person_ratio"):
            ref_val = getattr(reference, optional_field, None)
            cur_val = getattr(metrics, optional_field, None)
            if ref_val is not None and cur_val is not None:
                compare_fields.append(optional_field)

        if not compare_fields:
            return 1.0, []

        total_score = 0.0
        deviations: list[str] = []

        for field in compare_fields:
            cur = getattr(metrics, field) or 0.0
            ref = getattr(reference, field) or 0.0
            tolerance = tol.get(field, 0.15)

            diff = abs(cur - ref)
            if tolerance > 0:
                field_score = max(0.0, 1.0 - diff / tolerance)
            else:
                field_score = 1.0 if diff == 0 else 0.0

            total_score += field_score

            # 超过容差一半就报告偏差
            if diff > tolerance * 0.5:
                name = _FIELD_NAMES.get(field, field)
                direction = "偏高" if cur > ref else "偏低"
                deviations.append(
                    f"{name}{direction}（当前={cur:.2f}，参考={ref:.2f}）"
                )

        similarity = total_score / len(compare_fields)
        return round(similarity, 4), deviations
