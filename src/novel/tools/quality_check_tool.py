"""质量检查工具 - 规则硬指标 + LLM 评分。

三层质量检查体系：
1. 规则硬指标（零成本，rule_check）
2. LLM 对比式评估（pairwise_compare）
3. LLM 绝对打分（evaluate_chapter）
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.novel.models.quality import (
    PairwiseResult,
    QualityReport,
    RuleCheckResult,
)
from src.novel.templates.ai_flavor_blacklist import check_ai_flavor

log = logging.getLogger("novel")

# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\.\n]+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n|\n")
_DIALOGUE_RE = re.compile(r'["\u201c]([^"\u201d]*)["\u201d]|[\u300c]([^\u300d]*)[\u300d]')
# 对话标签正则：X说、X道、X喊道 等
_DIALOGUE_TAG_RE = re.compile(
    r'(?:^|[。！？!?\n])([^\n""\u201c\u201d]{1,10}?)(?:说|道|喊道|笑道|冷笑道|叹道|怒道|低声道|高声道|冷声道)'
)


def _split_sentences(text: str) -> list[str]:
    """将文本切分为句子列表。"""
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _split_paragraphs(text: str) -> list[str]:
    """将文本切分为段落列表。"""
    return [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]


def _char_jaccard(a: str, b: str) -> float:
    """基于字符集合的 Jaccard 相似度。"""
    set_a = set(a)
    set_b = set(b)
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _detect_repetition(sentences: list[str], window: int = 3, threshold: float = 0.8) -> list[str]:
    """检测连续相似句子。

    Args:
        sentences: 句子列表
        window: 滑动窗口大小
        threshold: 相似度阈值

    Returns:
        重复问题描述列表
    """
    issues: list[str] = []
    for i in range(len(sentences) - 1):
        for j in range(i + 1, min(i + window, len(sentences))):
            sim = _char_jaccard(sentences[i], sentences[j])
            if sim >= threshold:
                issues.append(
                    f"句子重复（相似度{sim:.0%}）: "
                    f"'{sentences[i][:30]}...' 与 '{sentences[j][:30]}...'"
                )
    return issues


def _extract_json_obj(text: str | None) -> dict | None:
    """从 LLM 输出中稳健提取 JSON 对象。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# QualityCheckTool
# ---------------------------------------------------------------------------


class QualityCheckTool:
    """质量检查工具，支持规则硬指标和 LLM 评分。"""

    def __init__(self, llm_client: Any | None = None):
        """
        Args:
            llm_client: 可选的 LLM 客户端。rule_check 不需要，pairwise_compare
                        和 evaluate_chapter 需要。
        """
        self.llm = llm_client

    # ------------------------------------------------------------------
    # Layer 1: 规则硬指标（零成本）
    # ------------------------------------------------------------------

    def rule_check(
        self,
        chapter_text: str,
        characters: list[dict] | None = None,
    ) -> RuleCheckResult:
        """规则硬指标检查。

        检查项：
        - 重复句检测
        - 对话标签一致性
        - 段落长度异常
        - AI 味短语
        - 对话区分度

        Args:
            chapter_text: 章节文本
            characters: 角色列表（可选，用于对话标签检查）

        Returns:
            RuleCheckResult 实例
        """
        if not chapter_text or not chapter_text.strip():
            return RuleCheckResult(passed=True)

        sentences = _split_sentences(chapter_text)
        paragraphs = _split_paragraphs(chapter_text)

        # 1. 重复句检测
        repetition_issues = _detect_repetition(sentences)

        # 2. 对话标签一致性
        dialogue_tag_issues = self._check_dialogue_tags(chapter_text, characters)

        # 3. 段落长度异常
        paragraph_length_issues: list[str] = []
        for i, para in enumerate(paragraphs, 1):
            if len(para) > 500:
                paragraph_length_issues.append(
                    f"第{i}段过长（{len(para)}字），建议拆分"
                )
            elif len(para) < 10 and len(paragraphs) > 1:
                paragraph_length_issues.append(
                    f"第{i}段过短（{len(para)}字）: '{para[:20]}'"
                )

        # 4. AI 味短语
        ai_hits = check_ai_flavor(chapter_text)
        ai_flavor_issues = [f"AI味短语: '{phrase}'（位置{pos}）" for phrase, pos in ai_hits]

        # 5. 对话区分度
        dialogue_distinction_issues = self._check_dialogue_distinction(chapter_text)

        # 综合判定：只有严重问题触发失败
        # 重复句 >= 3 或 AI味短语 >= 5 才算失败
        # 段落长度和对话区分度仅作为建议，不影响 passed
        critical_issues = repetition_issues + ai_flavor_issues
        passed = len(repetition_issues) < 3 and len(ai_flavor_issues) < 5

        return RuleCheckResult(
            passed=passed,
            repetition_issues=repetition_issues,
            dialogue_tag_issues=dialogue_tag_issues,
            paragraph_length_issues=paragraph_length_issues,
            ai_flavor_issues=ai_flavor_issues,
            dialogue_distinction_issues=dialogue_distinction_issues,
        )

    def _check_dialogue_tags(
        self, text: str, characters: list[dict] | None = None
    ) -> list[str]:
        """检查对话标签一致性。

        同一角色应使用一致的对话标签动词。
        """
        issues: list[str] = []
        tag_matches = _DIALOGUE_TAG_RE.findall(text)
        if not tag_matches:
            return issues

        # 收集每个角色使用的标签动词
        char_tags: dict[str, set[str]] = {}
        for match in tag_matches:
            name = match.strip()
            if not name:
                continue
            # 提取名字部分（去掉前面可能的标点等）
            name_clean = re.sub(r'^[，,、。！？!?\s]+', '', name)
            if not name_clean or len(name_clean) > 6:
                continue
            # 简单记录该角色出现过
            char_tags.setdefault(name_clean, set())

        # 如果提供了角色列表，检查是否有角色的对话标签混用
        # 当前版本只做基础检查
        return issues

    def _check_dialogue_distinction(self, text: str) -> list[str]:
        """检查不同角色的对话区分度。

        如果不同角色的对话过于相似，给出警告。
        """
        issues: list[str] = []
        # 提取所有对话内容
        dialogues: list[str] = []
        for m in _DIALOGUE_RE.finditer(text):
            content = m.group(1) or m.group(2) or ""
            content = content.strip()
            if len(content) >= 5:
                dialogues.append(content)

        # 检查相邻对话相似度
        for i in range(len(dialogues) - 1):
            sim = _char_jaccard(dialogues[i], dialogues[i + 1])
            if sim >= 0.7 and dialogues[i] != dialogues[i + 1]:
                issues.append(
                    f"相邻对话过于相似（{sim:.0%}）: "
                    f"'{dialogues[i][:20]}...' 与 '{dialogues[i+1][:20]}...'"
                )

        return issues

    # ------------------------------------------------------------------
    # Layer 1.5: 追更价值评估（LLM）
    # ------------------------------------------------------------------

    def evaluate_retention(
        self,
        chapter_text: str,
        chapter_outline: dict | None = None,
        chapter_brief: dict | None = None,
    ) -> dict[str, float]:
        """评估章节的追更价值（读者留存力）。

        用 LLM 从网文编辑视角评估 5 个维度（0-10 分）：
        - information_gain: 信息增量
        - conflict_effectiveness: 冲突有效性
        - memorable_moment: 可记忆点
        - cliffhanger_strength: 章尾钩子强度
        - protagonist_appeal: 主角魅力变化

        Args:
            chapter_text: 章节文本
            chapter_outline: 章节大纲（可选）
            chapter_brief: 章节任务书（可选，用于任务完成度评估）

        Returns:
            各维度评分字典；LLM 不可用时返回空 dict
        """
        if self.llm is None:
            return {}

        # Use chapter digest to save tokens when text is long
        from src.novel.tools.chapter_digest import create_digest

        if len(chapter_text) > 1500:
            digest = create_digest(chapter_text)
            scoring_text = digest["digest_text"]
            scoring_label = "章节摘要"
        else:
            scoring_text = chapter_text
            scoring_label = "章节正文"

        outline_info = ""
        if chapter_outline:
            outline_info = f"\n章节大纲：{json.dumps(chapter_outline, ensure_ascii=False)[:500]}"

        brief_section = ""
        if chapter_brief:
            brief_section = f"""

如果提供了章节任务书，还要评估：
- 主冲突是否清晰呈现
- 爽点/回报是否兑现
- 角色弧线是否推进
- 伏笔是否按计划处理
- 钩子是否按指定类型实现

【章节任务书】
{json.dumps(chapter_brief, ensure_ascii=False)[:800]}
"""

        prompt = f"""请从网文编辑的角度评估这章的追更价值——读者读完后是否愿意继续追下一章。
{outline_info}

【{scoring_label}】
{scoring_text[:4000]}
{brief_section}
请严格按以下 JSON 格式返回，每项 0-10 分：
{{
    "information_gain": 0-10,
    "conflict_effectiveness": 0-10,
    "memorable_moment": 0-10,
    "cliffhanger_strength": 0-10,
    "protagonist_appeal": 0-10
}}

评分标准：
- information_gain: 本章有没有信息增量（新角色/新设定/新发现/新线索），如果全章没有任何新信息给0-3分
- conflict_effectiveness: 本章冲突是否有效（不是走过场，而是真正改变了局势），如果冲突敷衍或无实质结果给0-3分
- memorable_moment: 本章有没有可记忆点（让读者印象深刻的场景/台词/画面），平淡无奇给0-3分
- cliffhanger_strength: 章尾钩子强度（是否让人想继续看下一章），没有钩子或钩子无力给0-3分
- protagonist_appeal: 主角魅力变化（本章主角有没有让读者更喜欢/更担心/更期待），主角路人感给0-3分
"""

        try:
            response = self.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一位资深网文编辑，不是文学评论家。你关心的是读者留存率——"
                            "读者读完这章后会不会追下一章。用网文编辑的标准打分，不要用纯文学标准。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                json_mode=True,
            )

            data = _extract_json_obj(response.content)
            if data is None:
                log.warning("追更评估 LLM 返回无法解析: %s", response.content[:200])
                return {}

            retention_keys = (
                "information_gain",
                "conflict_effectiveness",
                "memorable_moment",
                "cliffhanger_strength",
                "protagonist_appeal",
            )
            result: dict[str, float] = {}
            for key in retention_keys:
                val = data.get(key)
                if isinstance(val, (int, float)):
                    result[key] = max(0.0, min(10.0, float(val)))

            return result

        except Exception as exc:
            log.warning("追更评估 LLM 调用失败: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Layer 2: LLM 对比式评估
    # ------------------------------------------------------------------

    def pairwise_compare(
        self,
        version_a: str,
        version_b: str,
        criteria: str = "整体质量",
    ) -> PairwiseResult:
        """LLM 对比式评估两个版本。

        Args:
            version_a: 版本 A 文本
            version_b: 版本 B 文本
            criteria: 评估标准描述

        Returns:
            PairwiseResult(winner, reason)

        Raises:
            RuntimeError: LLM 不可用或返回无法解析
        """
        if self.llm is None:
            raise RuntimeError("LLM 客户端不可用，无法执行对比评估")

        prompt = f"""请对比以下两个版本的小说章节，根据"{criteria}"选出更优版本。

【版本 A】
{version_a[:3000]}

【版本 B】
{version_b[:3000]}

请严格按以下 JSON 格式返回：
{{"winner": "A" 或 "B" 或 "TIE", "reason": "选择理由"}}

评判标准：
1. 情节连贯性和逻辑性
2. 文笔质量和表达力
3. 角色刻画的鲜活度
4. AI味程度（越少越好）
"""

        response = self.llm.chat(
            messages=[
                {"role": "system", "content": "你是一位资深小说编辑。请客观评估两个版本的优劣。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            json_mode=True,
        )

        data = _extract_json_obj(response.content)
        if data is None:
            log.warning("对比评估 LLM 返回无法解析: %s", response.content[:200])
            return PairwiseResult(winner="TIE", reason="LLM 返回无法解析，默认平局")

        winner = data.get("winner", "TIE")
        if winner not in ("A", "B", "TIE"):
            winner = "TIE"
        reason = data.get("reason", "无详细理由")

        return PairwiseResult(winner=winner, reason=reason)

    # ------------------------------------------------------------------
    # Layer 3: LLM 绝对打分
    # ------------------------------------------------------------------

    def evaluate_chapter(
        self,
        chapter_text: str,
        chapter_outline: dict | None = None,
    ) -> QualityReport:
        """LLM 绝对打分评估章节质量。

        Args:
            chapter_text: 章节文本
            chapter_outline: 章节大纲（可选，用于判断情节偏离）

        Returns:
            QualityReport 实例
        """
        # 先做规则检查
        rule_result = self.rule_check(chapter_text)

        if self.llm is None:
            return QualityReport(
                chapter_number=1,
                rule_check=rule_result,
                scores={},
                need_rewrite=not rule_result.passed,
                rewrite_reason="规则检查未通过" if not rule_result.passed else None,
            )

        outline_info = ""
        if chapter_outline:
            outline_info = f"\n章节大纲：{json.dumps(chapter_outline, ensure_ascii=False)[:500]}"

        # Use chapter digest to save tokens when text is long
        from src.novel.tools.chapter_digest import create_digest

        if len(chapter_text) > 1500:
            digest = create_digest(chapter_text)
            scoring_text = digest["digest_text"]
            scoring_label = "章节摘要"
        else:
            scoring_text = chapter_text
            scoring_label = "章节正文"

        prompt = f"""请评估以下小说章节的质量，按四个维度打分（0-10）。
{outline_info}

【{scoring_label}】
{scoring_text[:4000]}

请根据以上{scoring_label}严格按以下 JSON 格式返回：
{{
    "plot_coherence": 0-10,
    "writing_quality": 0-10,
    "character_portrayal": 0-10,
    "ai_flavor_score": 0-10,
    "summary": "一句话总结"
}}

评分标准：
- plot_coherence: 情节连贯性（是否自圆其说，是否符合大纲）
- writing_quality: 文笔质量（语言表达、修辞、节奏）
- character_portrayal: 角色刻画（是否鲜活、是否有区分度）
- ai_flavor_score: AI味程度（10=完全无AI味，0=明显AI味）
"""

        try:
            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": "你是一位严格的小说质量评审员。请客观打分。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                json_mode=True,
            )

            data = _extract_json_obj(response.content)
            if data is None:
                log.warning("评分 LLM 返回无法解析: %s", response.content[:200])
                scores: dict[str, float] = {}
            else:
                scores = {}
                for key in ("plot_coherence", "writing_quality", "character_portrayal", "ai_flavor_score"):
                    val = data.get(key)
                    if isinstance(val, (int, float)):
                        scores[key] = max(0.0, min(10.0, float(val)))

        except Exception as exc:
            log.warning("LLM 打分失败: %s", exc)
            scores = {}

        # 判断是否需要重写
        avg_score = sum(scores.values()) / max(len(scores), 1) if scores else 0.0
        need_rewrite = not rule_result.passed or (scores and avg_score < 6.0)
        rewrite_reason = None
        if not rule_result.passed:
            rewrite_reason = "规则硬指标未通过"
        elif scores and avg_score < 6.0:
            rewrite_reason = f"LLM 评分过低（均分 {avg_score:.1f}）"

        suggestions: list[str] = []
        if rule_result.ai_flavor_issues:
            suggestions.append(f"消除 {len(rule_result.ai_flavor_issues)} 处 AI 味短语")
        if rule_result.repetition_issues:
            suggestions.append(f"修复 {len(rule_result.repetition_issues)} 处重复句")
        if rule_result.paragraph_length_issues:
            suggestions.append("调整段落长度")

        # --- 追更价值评估 ---
        retention_scores: dict[str, float] = {}
        if self.llm is not None:
            try:
                retention_scores = self.evaluate_retention(
                    chapter_text, chapter_outline
                )
            except Exception as exc:
                log.warning("追更价值评估失败: %s", exc)

        return QualityReport(
            chapter_number=1,
            rule_check=rule_result,
            scores=scores,
            retention_scores=retention_scores,
            need_rewrite=need_rewrite,
            rewrite_reason=rewrite_reason,
            suggestions=suggestions,
        )
