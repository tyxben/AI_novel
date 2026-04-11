"""Style Bible generation service.

Generates a per-project StyleBible document at novel creation time
(one LLM call) and provides migration support for existing projects.

Text-analysis helpers (sentence length, dialogue ratio, sensory density)
are pure functions and reusable by both the generator and the checker.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from src.novel.models.narrative_control import StyleBible

log = logging.getLogger("novel.style_bible")

# ---------------------------------------------------------------------------
# Pure text analysis helpers (zero LLM cost)
# ---------------------------------------------------------------------------

# Chinese sentence terminators
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\n]+")

# Dialogue quote pairs
_DIALOGUE_RE = re.compile(
    r'["\u201c][^"\u201d]*["\u201d]|[\u300c][^\u300d]*[\u300d]'
)

# Sensory descriptor keywords
_SENSORY_KEYWORDS: list[str] = [
    "味", "气味", "气息", "臭", "香", "腥",
    "声", "声音", "响", "鸣", "吼", "啸", "嗡",
    "光", "光芒", "光线", "亮", "暗", "闪",
    "冷", "热", "温", "凉", "烫", "寒",
    "湿", "潮", "干燥",
    "痛", "酸", "麻", "刺",
    "滑", "粗糙", "柔软", "坚硬",
]


def compute_avg_sentence_length(text: str) -> float:
    """Average Chinese sentence length in chars.

    Splits by 。！？ and newlines. Returns 0.0 for empty text.
    """
    if not text or not text.strip():
        return 0.0
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if not sentences:
        return 0.0
    total_chars = sum(len(s) for s in sentences)
    return total_chars / len(sentences)


def compute_dialogue_ratio(text: str) -> float:
    """Fraction of text that is inside dialogue quotes.

    Handles Chinese "" and 「」 quotes.
    Returns 0.0 for empty text.
    """
    if not text or not text.strip():
        return 0.0
    matches = _DIALOGUE_RE.findall(text)
    dialogue_chars = sum(len(m) for m in matches)
    return min(dialogue_chars / max(len(text), 1), 1.0)


def compute_sensory_density(text: str) -> float:
    """Count sensory descriptor keywords per 1000 chars.

    Uses a keyword list covering taste, smell, sound, light, temperature,
    pain, and texture.  Returns 0.0 for empty text.
    """
    if not text or not text.strip():
        return 0.0
    count = 0
    for kw in _SENSORY_KEYWORDS:
        count += text.count(kw)
    text_length = len(text)
    if text_length == 0:
        return 0.0
    return count / (text_length / 1000.0)


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_GENERATE_BIBLE_SYSTEM = """你是风格定义专家，负责为小说项目生成精确的风格圣经。

你的任务：
1. 基于题材、主题和风格预设，生成量化的风格目标（句长范围、对话占比等）
2. 创作 2-3 段范例文本（每段 ~200 字），体现该风格的典型特征
3. 列出该风格下的禁用模式（避免 AI 味过重、不符合风格的写法）

输出格式：JSON
"""

_GENERATE_BIBLE_USER = """
## 项目信息
- 题材：{genre}
- 主题：{theme}
- 风格预设：{style_name}
- 预设约束：{style_constraints}

## 任务
生成风格圣经，包含：

1. **quantitative_targets**（量化目标，字典）：
   - avg_sentence_length: 平均句长范围 [min, max]（字数）
   - dialogue_ratio: 对话占比范围 [min, max]（0.0-1.0）
   - paragraph_length: 段落平均句数范围 [min, max]
   - sensory_density: 感官描述密度范围 [min, max]（次/千字）
   - exclamation_ratio: 感叹句占比范围 [min, max]（0.0-1.0）

2. **voice_description**（文风描述，50字以内）：
   简洁描述该风格的核心特征，如"短句快节奏，对话密集，避免长段心理独白"

3. **exemplar_paragraphs**（范例段落，列表，2-3 段）：
   每段 ~200 字，体现该风格的典型写法。必须符合题材和主题。

4. **anti_patterns**（禁用模式，列表，3-5 项）：
   该风格下应避免的写法，如"避免'XX的XX气息'堆叠""禁止超过3行的心理独白"

输出 JSON：
{{
  "quantitative_targets": {{...}},
  "voice_description": "...",
  "exemplar_paragraphs": ["段落1", "段落2"],
  "anti_patterns": ["禁用1", "禁用2", ...]
}}
"""


# ---------------------------------------------------------------------------
# StyleBibleGenerator
# ---------------------------------------------------------------------------


class StyleBibleGenerator:
    """Generates a StyleBible for a novel project.

    Usage::

        gen = StyleBibleGenerator(llm_client)
        bible = gen.generate(genre="玄幻", theme="少年修炼", style_name="webnovel.shuangwen")
    """

    def __init__(self, llm_client: Any) -> None:
        """
        Args:
            llm_client: An LLMClient with ``chat(messages, temperature, json_mode, max_tokens)``.
        """
        self.llm = llm_client

    # ------------------------------------------------------------------
    # Primary generation (new novel)
    # ------------------------------------------------------------------

    def generate(
        self,
        genre: str,
        theme: str,
        style_name: str,
    ) -> StyleBible:
        """Generate a StyleBible for a new novel project.

        One LLM call (~300 output tokens).  Falls back to preset-based
        bible when LLM fails.

        Args:
            genre: Novel genre (e.g. "玄幻").
            theme: Novel theme / premise.
            style_name: Style preset key (e.g. "webnovel.shuangwen").

        Returns:
            A populated StyleBible instance.

        Raises:
            ValueError: If *style_name* does not exist in presets.
        """
        from src.novel.templates.style_presets import get_style

        try:
            preset = get_style(style_name)
        except KeyError as exc:
            raise ValueError(f"风格预设不存在: {style_name}") from exc

        constraints = preset.get("constraints", {})

        # Build LLM prompt
        user_prompt = _GENERATE_BIBLE_USER.format(
            genre=genre,
            theme=theme,
            style_name=style_name,
            style_constraints=json.dumps(constraints, ensure_ascii=False, indent=2),
        )

        messages = [
            {"role": "system", "content": _GENERATE_BIBLE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        # Try LLM generation
        try:
            resp = self.llm.chat(messages, temperature=0.7, json_mode=True)
            data = json.loads(resp.content)
        except Exception as exc:
            log.warning("风格圣经 LLM 生成失败，使用 fallback: %s", exc)
            return self._build_fallback_bible(constraints, style_name)

        # Parse into StyleBible
        try:
            bible = StyleBible(
                quantitative_targets=data["quantitative_targets"],
                voice_description=data["voice_description"],
                exemplar_paragraphs=data["exemplar_paragraphs"],
                anti_patterns=data.get("anti_patterns", []),
                volume_overrides=None,
                based_on_chapters=None,
                generated_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            log.warning("风格圣经解析失败，使用 fallback: %s", exc)
            bible = self._build_fallback_bible(constraints, style_name)

        log.info("风格圣经生成完成: %s", style_name)
        return bible

    # ------------------------------------------------------------------
    # Migration: generate from existing chapters
    # ------------------------------------------------------------------

    def generate_from_existing_chapters(
        self,
        chapters: list[dict],
        style_name: str,
        genre: str,
    ) -> StyleBible:
        """Generate a StyleBible based on the first N existing chapters.

        Pure text analysis sets the quantitative baselines; no LLM call
        required for the numeric targets.

        Args:
            chapters: List of chapter dicts, each must have ``full_text``
                and ``chapter_number``.
            style_name: Style preset key.
            genre: Novel genre.

        Returns:
            A StyleBible whose targets bracket the actual chapter metrics.
        """
        from src.novel.templates.style_presets import get_style

        if not chapters:
            raise ValueError("No chapters provided for migration")

        # Analyze actual metrics from each chapter
        metrics = [self._analyze_style_metrics(ch["full_text"]) for ch in chapters]

        avg_sl = sum(m["avg_sentence_length"] for m in metrics) / len(metrics)
        avg_dr = sum(m["dialogue_ratio"] for m in metrics) / len(metrics)
        avg_sd = sum(m["sensory_density"] for m in metrics) / len(metrics)

        # Build targets: actual baseline +/- ~15-20% margin
        quantitative_targets = {
            "avg_sentence_length": [
                round(avg_sl * 0.85, 1),
                round(avg_sl * 1.15, 1),
            ],
            "dialogue_ratio": [
                round(max(0.0, avg_dr - 0.10), 2),
                round(min(1.0, avg_dr + 0.10), 2),
            ],
            "sensory_density": [
                round(max(0.0, avg_sd * 0.5), 1),
                round(max(0.5, avg_sd * 1.5), 1),
            ],
            # Defaults for metrics not easily derived from text
            "exclamation_ratio": [0.03, 0.15],
        }

        # Voice description from metrics
        voice_description = (
            f"基于前{len(chapters)}章实际风格，"
            f"句长~{avg_sl:.1f}字，对话~{avg_dr:.0%}，"
            f"感官密度~{avg_sd:.1f}/千字"
        )

        # Use first 2 chapters' opening as exemplar paragraphs
        exemplar_paragraphs = [
            ch["full_text"][:300] for ch in chapters[:2] if ch.get("full_text")
        ]
        # Ensure at least 2 exemplars
        while len(exemplar_paragraphs) < 2:
            exemplar_paragraphs.append("（占位范例段落）")

        # Anti-patterns from preset
        try:
            preset = get_style(style_name)
        except KeyError:
            preset = {}
        anti_patterns = preset.get("anti_patterns", [
            "避免 AI 味过重的表达",
            "禁止生硬的说教性语言",
        ])

        bible = StyleBible(
            quantitative_targets=quantitative_targets,
            voice_description=voice_description,
            exemplar_paragraphs=exemplar_paragraphs,
            anti_patterns=anti_patterns,
            volume_overrides=None,
            based_on_chapters=[ch["chapter_number"] for ch in chapters],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        log.info(
            "基于 ch%d-%d 生成风格圣经",
            chapters[0]["chapter_number"],
            chapters[-1]["chapter_number"],
        )
        return bible

    # ------------------------------------------------------------------
    # Text analysis (pure, no LLM)
    # ------------------------------------------------------------------

    @staticmethod
    def _analyze_style_metrics(text: str) -> dict[str, float]:
        """Analyze text and return style metrics dict.

        Returns:
            Dict with keys: avg_sentence_length, dialogue_ratio, sensory_density.
        """
        return {
            "avg_sentence_length": compute_avg_sentence_length(text),
            "dialogue_ratio": compute_dialogue_ratio(text),
            "sensory_density": compute_sensory_density(text),
        }

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _build_fallback_bible(
        self,
        constraints: dict[str, Any],
        style_name: str,
    ) -> StyleBible:
        """Build a minimal StyleBible from preset constraints (no LLM)."""
        max_para = constraints.get("max_paragraph_sentences", 6)
        return StyleBible(
            quantitative_targets={
                "avg_sentence_length": constraints.get(
                    "avg_sentence_length", [12, 20]
                ),
                "dialogue_ratio": constraints.get("dialogue_ratio", [0.30, 0.50]),
                "sensory_density": [0.5, 1.5],
                "exclamation_ratio": constraints.get(
                    "exclamation_ratio", [0.03, 0.10]
                ),
                "paragraph_length": [
                    round(max_para * 0.6, 1),
                    float(max_para),
                ],
            },
            voice_description=f"基于 {style_name} 的标准风格",
            exemplar_paragraphs=[
                "（范例段落 1：LLM 生成失败，此处为占位文本。"
                "建议编辑 novel.json 中的 style_bible 字段。）",
                "（范例段落 2：LLM 生成失败，此处为占位文本。"
                "建议编辑 novel.json 中的 style_bible 字段。）",
            ],
            anti_patterns=[
                "避免 AI 味过重的表达",
                "禁止生硬的说教性语言",
            ],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
