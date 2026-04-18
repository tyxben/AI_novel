"""ChapterCritic — 结构化 LLM 章节批评（Self-Refine 的"批评"角色）。

不同于 QualityReviewer 的打分模式，ChapterCritic 输出**可执行的修改建议**：
- strengths: 章节做得好的点（保留）
- issues: 具体问题（按 severity 分级）
- specific_revisions: 段落级修改建议（喂给 Writer.refine）

LLM 调用，需要 ``LLMClient``。
失败时返回空 ``CritiqueResult``（不抛异常），上层据此跳过本轮 refine。
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.llm.llm_client import LLMClient
from src.novel.utils.json_extract import extract_json_obj

log = logging.getLogger("novel.critic")


# ---------------------------------------------------------------------------
# Result schema
# ---------------------------------------------------------------------------

IssueType = Literal[
    "pacing",
    "characterization",
    "world_consistency",
    "dialogue",
    "trope_overuse",
    "transition",
    "logic",
    "other",
]

Severity = Literal["low", "medium", "high"]


class Issue(BaseModel):
    """单条具体问题。"""

    type: IssueType = "other"
    severity: Severity = "medium"
    quote: str = Field(default="", description="原文引用片段（≤80字）")
    reason: str = Field(default="", description="问题描述")

    @field_validator("quote")
    @classmethod
    def _trim_quote(cls, v: str) -> str:
        return (v or "")[:200]


class Revision(BaseModel):
    """具体修改建议。"""

    target: str = Field(default="", description="原文引用片段（≤80字）")
    suggestion: str = Field(default="", description="建议改成什么样")

    @field_validator("target", "suggestion")
    @classmethod
    def _trim(cls, v: str) -> str:
        return (v or "")[:300]


class CritiqueResult(BaseModel):
    """ChapterCritic 输出。"""

    strengths: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    specific_revisions: list[Revision] = Field(default_factory=list)
    overall_assessment: str = Field(default="", description="≤200 字总评")
    raw_response: str = Field(default="", exclude=True)

    @property
    def high_severity_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "high")

    @property
    def medium_severity_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "medium")

    @property
    def needs_refine(self) -> bool:
        """LLM 判断本轮是否需要再 refine：有 high 或 ≥2 medium。"""
        return self.high_severity_count > 0 or self.medium_severity_count >= 2

    def to_writer_prompt(self) -> str:
        """格式化成给 Writer.refine 用的提示。"""
        if not self.issues and not self.specific_revisions:
            return ""
        lines = ["## 编辑批注（请按下列建议精修，保留 strengths 部分）"]
        if self.strengths:
            lines.append("\n### 保留的优点")
            for s in self.strengths[:5]:
                lines.append(f"- {s}")
        if self.issues:
            lines.append("\n### 待修问题")
            for i in self.issues:
                tag = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(i.severity, "•")
                quote = f"「{i.quote}」" if i.quote else ""
                lines.append(f"- {tag} [{i.type}] {quote} {i.reason}")
        if self.specific_revisions:
            lines.append("\n### 具体改写建议")
            for r in self.specific_revisions[:8]:
                target = f"原: {r.target}" if r.target else ""
                lines.append(f"- {target}\n  改: {r.suggestion}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ChapterCritic agent
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT_TEMPLATE = """你是一位资深小说编辑，正在给一本中文长篇小说做结构化审稿。

你的任务是给出**可执行的修改建议**，不是泛泛打分。

审稿维度：
- pacing（节奏）：拖沓、信息堆叠、转场生硬
- characterization（人物）：动机不清、性格漂移、配角脸谱化
- world_consistency（世界观）：与已建立设定矛盾、突然引入无铺垫的新元素
- dialogue（对话）：所有人语气雷同、独白过长、对白不推进剧情
- trope_overuse（套路化表达）：**根据场景判断**是否滥用，不要机械数次数。
  下面是观察名单（不是禁用名单）：{watchlist_block}
  判断准则：
    · 单次出现 + 场景匹配（如"瞳孔骤缩"用在惊愕反转处）→ 不算 issue
    · 同一短语在本章 ≥3 次，或用在不需要强烈情绪的场景 → 标 issue
    · 全章弥漫"黑眸/凛冽/睥睨"等武侠套话堆砌 → 标 high
- transition（衔接）：与上章脱节、首句重复、悬念断裂
- logic（逻辑）：情节矛盾、时间线错乱、动作不合理

严格输出 JSON：
{{
  "strengths": ["..."],
  "issues": [
    {{"type": "pacing|characterization|...", "severity": "low|medium|high",
     "quote": "原文引用，≤80字", "reason": "问题描述"}}
  ],
  "specific_revisions": [
    {{"target": "原文引用，≤80字", "suggestion": "改成什么样"}}
  ],
  "overall_assessment": "≤200字总评"
}}

要求：
- 不要输出 JSON 之外的任何文字（不要 markdown 代码块）
- issues 至少 1 条，严重的标 high
- specific_revisions 至少 2 条，针对最严重的问题
- 引用原文要精确，不要意译
- 章节质量好就少标 issues，但 strengths 必须填
"""


def _build_system_prompt(watchlist: dict[str, int] | None) -> str:
    if not watchlist:
        block = "（本次未提供观察名单）"
    else:
        items = [f"{p}(≥{n}次需关注)" for p, n in watchlist.items()]
        block = "、".join(items)
    return _SYSTEM_PROMPT_TEMPLATE.format(watchlist_block=block)


class ChapterCritic:
    """章节批评家。结构化输出可执行修改建议。"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def critique(
        self,
        chapter_text: str,
        *,
        chapter_number: int,
        chapter_title: str = "",
        chapter_goal: str = "",
        prev_chapter_tail: str = "",
        prior_critiques: list[CritiqueResult] | None = None,
        watchlist: dict[str, int] | None = None,
    ) -> CritiqueResult:
        """对章节进行批评。

        Args:
            chapter_text: 章节正文（建议已经 sanitize 过）。
            chapter_number: 章节号。
            chapter_title: 章节标题（可选）。
            chapter_goal: 大纲里的目标（可选）。
            prev_chapter_tail: 上章末尾若干字符，用于检查衔接。
            prior_critiques: 同章节先前批评轮次的结果，用于避免重复指出已修复的问题。

        Returns:
            ``CritiqueResult``。LLM 失败时返回空对象（``raw_response`` 含错误信息）。
        """
        user_prompt = self._build_user_prompt(
            chapter_text=chapter_text,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            chapter_goal=chapter_goal,
            prev_chapter_tail=prev_chapter_tail,
            prior_critiques=prior_critiques or [],
        )
        messages = [
            {"role": "system", "content": _build_system_prompt(watchlist)},
            {"role": "user", "content": user_prompt},
        ]
        try:
            resp = self.llm.chat(
                messages,
                temperature=0.3,
                json_mode=True,
                max_tokens=2048,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("ChapterCritic LLM call failed: %s", exc)
            return CritiqueResult(
                overall_assessment="",
                raw_response=f"LLM 调用失败: {exc}",
            )

        raw = (resp.content or "").strip()
        return self._parse_response(raw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        *,
        chapter_text: str,
        chapter_number: int,
        chapter_title: str,
        chapter_goal: str,
        prev_chapter_tail: str,
        prior_critiques: list[CritiqueResult],
    ) -> str:
        parts = [f"## 第{chapter_number}章 {chapter_title}".rstrip()]
        if chapter_goal:
            parts.append(f"\n本章目标：{chapter_goal}")
        if prev_chapter_tail:
            parts.append(
                f"\n【上一章结尾节选】\n{prev_chapter_tail[:500]}"
            )
        if prior_critiques:
            past_issues = []
            for c in prior_critiques[-2:]:
                for i in c.issues:
                    past_issues.append(f"- [{i.type}/{i.severity}] {i.reason}")
            if past_issues:
                parts.append(
                    "\n【先前批注（已尝试修复，不要重复指出已解决的问题）】\n"
                    + "\n".join(past_issues[:10])
                )
        parts.append(f"\n【待审章节正文】\n{chapter_text}")
        return "\n".join(parts)

    def _parse_response(self, raw: str) -> CritiqueResult:
        if not raw:
            return CritiqueResult(raw_response="LLM 返回空响应")
        try:
            data = extract_json_obj(raw)
        except Exception as exc:  # noqa: BLE001
            log.warning("ChapterCritic JSON parse failed: %s", exc)
            return CritiqueResult(raw_response=raw)
        if not isinstance(data, dict):
            return CritiqueResult(raw_response=raw)
        try:
            result = CritiqueResult.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            log.warning("ChapterCritic schema validation failed: %s", exc)
            return CritiqueResult(raw_response=raw)
        result.raw_response = raw
        return result
