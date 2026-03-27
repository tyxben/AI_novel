"""FeedbackAnalyzer - 读者反馈分析 Agent

负责：
1. 分类反馈类型（角色/节奏/伏笔/对话/情节/风格）
2. 确定影响范围（哪些章节需要直接修改，哪些需要传播调整）
3. 生成逐章重写指令

三步诊断链：
  diagnose → locate_evidence → plan_fix
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from src.novel.agents.state import Decision
from src.novel.utils import extract_json_from_llm

log = logging.getLogger("novel")

_VALID_PROBLEM_TYPES = {
    "character",
    "pacing",
    "plot_hole",
    "dialogue",
    "style",
    "foreshadowing",
    "other",
}

_VALID_SEVERITIES = {"low", "medium", "high"}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _make_decision(
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    """创建 FeedbackAnalyzer 的决策记录。"""
    return Decision(
        agent="FeedbackAnalyzer",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _keyword_search(text: str, keywords: list[str]) -> list[dict]:
    """在文本中按关键词搜索，返回匹配的段落信息。

    Returns:
        list of {"paragraph_index": int, "text_excerpt": str, "keyword": str}
    """
    if not text or not keywords:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    results = []
    seen_indices: set[int] = set()

    for kw in keywords:
        if not kw:
            continue
        for idx, para in enumerate(paragraphs):
            if idx in seen_indices:
                continue
            if kw in para:
                results.append(
                    {
                        "paragraph_index": idx,
                        "text_excerpt": para[:300],
                        "keyword": kw,
                    }
                )
                seen_indices.add(idx)

    return results


# ---------------------------------------------------------------------------
# FeedbackAnalyzer Agent
# ---------------------------------------------------------------------------


class FeedbackAnalyzer:
    """读者反馈分析器"""

    def __init__(self, llm_client: Any) -> None:
        self.llm = llm_client

    # -----------------------------------------------------------------------
    # Step 1: diagnose — 理解反馈在说什么
    # -----------------------------------------------------------------------

    def diagnose(
        self,
        feedback_text: str,
        chapter_number: int | None,
    ) -> dict:
        """理解反馈，分类问题并提炼核心诊断。

        Args:
            feedback_text: 读者反馈原文
            chapter_number: 反馈针对的章节号（None=全局）

        Returns:
            dict with keys: problem_type, severity, diagnosis, search_keywords
        """
        target_hint = (
            f"读者反馈针对第{chapter_number}章"
            if chapter_number
            else "读者给出的全局反馈"
        )

        prompt = f"""{target_hint}：
「{feedback_text}」

请诊断这条反馈，返回 JSON：
{{
    "problem_type": "character|pacing|plot_hole|dialogue|style|foreshadowing|other",
    "severity": "low|medium|high",
    "diagnosis": "将模糊反馈翻译成具体的问题描述（1-2句话）",
    "search_keywords": ["用于在正文中搜索相关段落的关键词列表，3-6个关键词"]
}}

诊断要求：
1. problem_type 精准分类
2. diagnosis 要把模糊反馈翻译成具体诊断，例如"主角不对劲"→"主角行为与前期性格设定不一致，具体表现可能是决策逻辑变化"
3. search_keywords 选能在正文中定位问题段落的关键词（角色名、场景词、动作词等）"""

        response = self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "你是一位资深小说编辑。请精准诊断读者反馈的核心问题。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            json_mode=True,
            max_tokens=1024,
        )

        try:
            data = extract_json_from_llm(response.content)
        except (ValueError, AttributeError) as exc:
            log.warning("诊断 LLM 返回无法解析: %s", exc)
            return {
                "problem_type": "other",
                "severity": "medium",
                "diagnosis": feedback_text,
                "search_keywords": [],
            }

        # Validate
        if data.get("problem_type") not in _VALID_PROBLEM_TYPES:
            data["problem_type"] = "other"
        if data.get("severity") not in _VALID_SEVERITIES:
            data["severity"] = "medium"
        if not isinstance(data.get("diagnosis"), str) or not data["diagnosis"]:
            data["diagnosis"] = feedback_text
        if not isinstance(data.get("search_keywords"), list):
            data["search_keywords"] = []
        # Ensure all keywords are strings
        data["search_keywords"] = [
            str(kw) for kw in data["search_keywords"] if kw
        ]

        return data

    # -----------------------------------------------------------------------
    # Step 2: locate_evidence — 在正文中找证据
    # -----------------------------------------------------------------------

    def locate_evidence(
        self,
        diagnosis: dict,
        chapter_texts: dict[int, str],
        chapter_number: int | None,
    ) -> list[dict]:
        """在正文中查找与诊断相关的证据段落。

        Args:
            diagnosis: diagnose() 的返回结果
            chapter_texts: {章节号: 正文} 字典
            chapter_number: 反馈针对的章节号

        Returns:
            list of {"chapter": int, "paragraph_index": int,
                     "text_excerpt": str, "issue": str}
        """
        if not chapter_texts:
            return []

        keywords = diagnosis.get("search_keywords", [])
        if not keywords:
            return []

        # Determine which chapters to search: target chapter first, then neighbors
        search_order: list[int] = []
        if chapter_number and chapter_number in chapter_texts:
            search_order.append(chapter_number)
        # Add adjacent chapters
        for ch_num in sorted(chapter_texts.keys()):
            if ch_num not in search_order:
                search_order.append(ch_num)

        # Keyword search across chapters
        candidates: list[dict] = []
        for ch_num in search_order:
            text = chapter_texts[ch_num]
            matches = _keyword_search(text, keywords)
            for m in matches:
                candidates.append(
                    {
                        "chapter": ch_num,
                        "paragraph_index": m["paragraph_index"],
                        "text_excerpt": m["text_excerpt"],
                        "keyword": m["keyword"],
                    }
                )

        if not candidates:
            return []

        # Cap candidates for LLM verification
        candidates = candidates[:10]

        # Use LLM to verify which candidates are actually problematic
        diagnosis_text = diagnosis.get("diagnosis", "")
        problem_type = diagnosis.get("problem_type", "other")

        candidates_desc = "\n".join(
            f"[{i}] 第{c['chapter']}章 段落{c['paragraph_index']}: "
            f"「{c['text_excerpt'][:150]}」"
            for i, c in enumerate(candidates)
        )

        prompt = f"""问题诊断：{diagnosis_text}
问题类型：{problem_type}

以下是从正文中找到的候选段落，请判断哪些确实存在上述问题：

{candidates_desc}

返回 JSON：
{{
    "evidence": [
        {{
            "index": 候选段落编号,
            "issue": "该段落具体存在什么问题（1句话）"
        }}
    ]
}}

如果没有段落真的有问题，返回 {{"evidence": []}}"""

        response = self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "你是一位资深小说编辑。请严格判断哪些段落确实存在问题，不要过度诊断。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            json_mode=True,
            max_tokens=1024,
        )

        try:
            result = extract_json_from_llm(response.content)
        except (ValueError, AttributeError) as exc:
            log.warning("证据验证 LLM 返回无法解析: %s", exc)
            return []

        evidence_list = result.get("evidence", [])
        if not isinstance(evidence_list, list):
            return []

        verified: list[dict] = []
        for ev in evidence_list:
            if not isinstance(ev, dict):
                continue
            idx = ev.get("index")
            if not isinstance(idx, (int, float)):
                continue
            idx = int(idx)
            if 0 <= idx < len(candidates):
                c = candidates[idx]
                verified.append(
                    {
                        "chapter": c["chapter"],
                        "paragraph_index": c["paragraph_index"],
                        "text_excerpt": c["text_excerpt"],
                        "issue": ev.get("issue", ""),
                    }
                )

        return verified

    # -----------------------------------------------------------------------
    # Step 3: plan_fix — 基于证据制定精准修改方案
    # -----------------------------------------------------------------------

    def plan_fix(
        self,
        diagnosis: dict,
        evidence: list[dict],
        outline_chapters: list[dict],
    ) -> dict:
        """基于诊断和证据，生成精准的逐章修改方案。

        Args:
            diagnosis: diagnose() 的返回结果
            evidence: locate_evidence() 的返回结果
            outline_chapters: 大纲章节列表

        Returns:
            dict compatible with analyze() output format:
                feedback_type, severity, target_chapters,
                propagation_chapters, rewrite_instructions, summary
        """
        if not evidence:
            # No evidence found — return minimal result
            return {
                "feedback_type": diagnosis.get("problem_type", "other"),
                "severity": diagnosis.get("severity", "medium"),
                "target_chapters": [],
                "propagation_chapters": [],
                "rewrite_instructions": {},
                "character_changes": None,
                "summary": f"诊断: {diagnosis.get('diagnosis', '')}，但未在正文中找到确切证据",
            }

        # Build evidence description for LLM
        evidence_desc = "\n".join(
            f"- 第{ev['chapter']}章 段落{ev['paragraph_index']}: "
            f"「{ev['text_excerpt'][:150]}」→ 问题: {ev['issue']}"
            for ev in evidence
        )

        affected_chapters = sorted(set(ev["chapter"] for ev in evidence))
        total = len(outline_chapters)

        chapters_summary = "\n".join(
            f"第{ch['chapter_number']}章「{ch.get('title', '')}」: {ch.get('goal', '')}"
            for ch in outline_chapters[:50]
        )

        prompt = f"""问题诊断：{diagnosis.get('diagnosis', '')}
问题类型：{diagnosis.get('problem_type', 'other')}
严重度：{diagnosis.get('severity', 'medium')}

【正文中的证据】
{evidence_desc}

【章节结构】
{chapters_summary}

基于以上证据，制定精准修改方案，返回 JSON：
{{
    "target_chapters": [需要直接修改的章节号],
    "propagation_chapters": [下游需要微调的章节号],
    "rewrite_instructions": {{
        "章节号": "基于证据的具体修改指令，必须引用具体文本片段"
    }},
    "character_changes": [如需修改角色设定，列出修改项] 或 null,
    "summary": "一句话概括修改方案"
}}

要求：
1. rewrite_instructions 必须引用证据中的具体文本
2. 修改指令要可操作，说清楚改什么、怎么改
3. target_chapters 只包含有证据支持的章节"""

        response = self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "你是一位资深小说编辑。请基于证据制定精准的修改方案，不要过度修改。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            json_mode=True,
            max_tokens=2048,
        )

        try:
            data = extract_json_from_llm(response.content)
        except (ValueError, AttributeError) as exc:
            log.warning("修改方案 LLM 返回无法解析: %s", exc)
            # Fallback: generate instructions from evidence directly
            instructions = {}
            for ev in evidence:
                ch_key = str(ev["chapter"])
                if ch_key not in instructions:
                    instructions[ch_key] = (
                        f"修改段落{ev['paragraph_index']}附近: "
                        f"「{ev['text_excerpt'][:100]}」— {ev['issue']}"
                    )
                else:
                    instructions[ch_key] += (
                        f"; 以及段落{ev['paragraph_index']}附近: "
                        f"「{ev['text_excerpt'][:100]}」— {ev['issue']}"
                    )
            return {
                "feedback_type": diagnosis.get("problem_type", "other"),
                "severity": diagnosis.get("severity", "medium"),
                "target_chapters": affected_chapters,
                "propagation_chapters": [],
                "rewrite_instructions": instructions,
                "character_changes": None,
                "summary": f"基于{len(evidence)}条证据生成修改方案（LLM解析失败，使用回退方案）",
            }

        # Validate
        data["feedback_type"] = diagnosis.get("problem_type", "other")
        data["severity"] = diagnosis.get("severity", "medium")

        data["target_chapters"] = [
            int(ch)
            for ch in data.get("target_chapters", [])
            if isinstance(ch, (int, float)) and 1 <= int(ch) <= total
        ]
        data["propagation_chapters"] = [
            int(ch)
            for ch in data.get("propagation_chapters", [])
            if isinstance(ch, (int, float)) and 1 <= int(ch) <= total
        ]

        raw_instructions = data.get("rewrite_instructions", {})
        data["rewrite_instructions"] = {
            str(int(k)): v
            for k, v in raw_instructions.items()
            if str(k).isdigit() and 1 <= int(k) <= total
        }

        if "summary" not in data:
            data["summary"] = f"基于{len(evidence)}条证据制定修改方案"

        return data

    # -----------------------------------------------------------------------
    # analyze — 主入口（保持签名兼容）
    # -----------------------------------------------------------------------

    def analyze(
        self,
        feedback_text: str,
        chapter_number: int | None,
        outline_chapters: list[dict],
        characters: list[dict],
        max_propagation: int = 10,
    ) -> dict:
        """分析反馈，返回 FeedbackAnalysis 格式的字典。

        内部使用三步诊断链：diagnose → 增强 prompt → 生成方案。
        locate_evidence 和 plan_fix 需要正文，由 pipeline 层调用。

        Args:
            feedback_text: 读者反馈原文
            chapter_number: 反馈针对的章节号（None=全局）
            outline_chapters: 大纲章节列表 [{chapter_number, title, goal, involved_characters, ...}]
            characters: 角色列表 [{name, ...}]
            max_propagation: 最大传播章节数

        Returns:
            dict with keys: feedback_type, severity, target_chapters,
                propagation_chapters, rewrite_instructions, summary,
                diagnosis (new — 诊断结果)
        """
        # Step 1: 诊断
        diagnosis = self.diagnose(feedback_text, chapter_number)

        # Build context about the novel structure
        chapters_summary = "\n".join(
            f"第{ch['chapter_number']}章「{ch.get('title', '')}」: {ch.get('goal', '')} "
            f"[角色: {', '.join(ch.get('involved_characters', []))}]"
            for ch in outline_chapters[:50]  # cap at 50
        )

        char_names = ", ".join(c.get("name", "?") for c in characters[:20])

        target_hint = (
            f"读者反馈针对第{chapter_number}章"
            if chapter_number
            else "读者给出的全局反馈"
        )

        # Step 2: 用诊断结果增强 prompt，生成修改方案
        prompt = f"""{target_hint}：
「{feedback_text}」

【诊断结果】
问题类型：{diagnosis['problem_type']}
严重度：{diagnosis['severity']}
核心诊断：{diagnosis['diagnosis']}
搜索关键词：{', '.join(diagnosis.get('search_keywords', []))}

【小说章节结构】
{chapters_summary}

【主要角色】
{char_names}

基于以上诊断结果，制定修改方案，返回 JSON：
{{
    "feedback_type": "{diagnosis['problem_type']}",
    "severity": "{diagnosis['severity']}",
    "target_chapters": [需要直接修改的章节号列表],
    "propagation_chapters": [下游需要微调的章节号列表，最多{max_propagation}个],
    "rewrite_instructions": {{
        "章节号": "该章的具体修改指令（基于诊断结果）"
    }},
    "character_changes": [如需修改角色设定，列出修改项] 或 null,
    "summary": "一句话概括分析结果"
}}

分析要求：
1. target_chapters 只包含必须修改的章节（通常1-3章）
2. propagation_chapters 是受间接影响的后续章节（如角色性格改变影响后续互动）
3. rewrite_instructions 要具体可操作，紧扣诊断结果
4. 如果反馈指向全局问题（如"节奏太慢"），选择最关键的几章修改"""

        response = self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "你是一位资深小说编辑。请基于诊断结果，制定精准的修改方案。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            json_mode=True,
            max_tokens=2048,
        )

        try:
            data = extract_json_from_llm(response.content)
        except (ValueError, AttributeError) as exc:
            log.warning("反馈分析 LLM 返回无法解析: %s", exc)
            # Fallback: just rewrite the target chapter
            target = [chapter_number] if chapter_number else []
            return {
                "feedback_type": diagnosis.get("problem_type", "other"),
                "severity": diagnosis.get("severity", "medium"),
                "target_chapters": target,
                "propagation_chapters": [],
                "rewrite_instructions": (
                    {str(chapter_number): feedback_text} if chapter_number else {}
                ),
                "character_changes": None,
                "summary": "LLM 分析失败，回退到直接重写",
                "diagnosis": diagnosis,
            }

        # Validate and sanitize
        if data.get("feedback_type") not in _VALID_PROBLEM_TYPES:
            data["feedback_type"] = diagnosis.get("problem_type", "other")
        if data.get("severity") not in _VALID_SEVERITIES:
            data["severity"] = diagnosis.get("severity", "medium")

        # Ensure target_chapters are ints and within range
        total = len(outline_chapters)
        data["target_chapters"] = [
            int(ch)
            for ch in data.get("target_chapters", [])
            if isinstance(ch, (int, float)) and 1 <= int(ch) <= total
        ]
        data["propagation_chapters"] = [
            int(ch)
            for ch in data.get("propagation_chapters", [])
            if isinstance(ch, (int, float)) and 1 <= int(ch) <= total
        ][:max_propagation]

        # Ensure rewrite_instructions keys are strings of ints
        raw_instructions = data.get("rewrite_instructions", {})
        data["rewrite_instructions"] = {
            str(int(k)): v
            for k, v in raw_instructions.items()
            if str(k).isdigit()
        }

        # Attach diagnosis for downstream use
        data["diagnosis"] = diagnosis

        return data


# ---------------------------------------------------------------------------
# LangGraph 节点函数
# ---------------------------------------------------------------------------


def feedback_analyzer_node(state: dict) -> dict:
    """LangGraph 节点：FeedbackAnalyzer。

    分析待处理的读者反馈，生成重写指令和影响范围。

    从 state 中读取:
    - feedback_entries: 反馈条目列表
    - config.llm: LLM 配置
    - outline.chapters: 大纲章节列表
    - characters: 角色列表

    更新 state:
    - feedback_analysis: 反馈分析结果
    - rewrite_queue: 需要重写的章节队列
    - rewrite_instructions: 逐章重写指令
    - decisions: 添加决策记录
    - errors: 添加错误信息（如有）
    - completed_nodes: 添加 "feedback_analyzer"
    """
    from src.llm.llm_client import create_llm_client

    from src.novel.llm_utils import get_stage_llm_config

    decisions: list[Decision] = []
    errors: list[dict] = []

    feedback_entries = state.get("feedback_entries", [])
    pending = [f for f in feedback_entries if f.get("status") == "pending"]

    if not pending:
        return {
            "errors": [
                {"agent": "FeedbackAnalyzer", "message": "没有待处理的反馈"}
            ],
            "completed_nodes": ["feedback_analyzer"],
        }

    llm_config = get_stage_llm_config(state, "quality_review")
    try:
        llm = create_llm_client(llm_config)
    except Exception as exc:
        return {
            "errors": [
                {
                    "agent": "FeedbackAnalyzer",
                    "message": f"LLM 初始化失败: {exc}",
                }
            ],
            "completed_nodes": ["feedback_analyzer"],
        }

    analyzer = FeedbackAnalyzer(llm)
    outline_chapters = state.get("outline", {}).get("chapters", [])
    characters = state.get("characters", [])

    # Process the first pending feedback
    entry = pending[0]
    analysis = analyzer.analyze(
        feedback_text=entry["content"],
        chapter_number=entry.get("chapter_number"),
        outline_chapters=outline_chapters,
        characters=characters,
    )

    # Update feedback entry status
    entry["status"] = "analyzed"
    entry["feedback_type"] = analysis.get("feedback_type")

    # Build rewrite queue: target chapters first, then propagation
    rewrite_queue = sorted(
        set(
            analysis.get("target_chapters", [])
            + analysis.get("propagation_chapters", [])
        )
    )

    decisions.append(
        _make_decision(
            step="analyze_feedback",
            decision=f"反馈分析完成: {analysis.get('feedback_type', 'other')}",
            reason=analysis.get("summary", ""),
            data={
                "target_count": len(analysis.get("target_chapters", [])),
                "propagation_count": len(
                    analysis.get("propagation_chapters", [])
                ),
                "severity": analysis.get("severity"),
            },
        )
    )

    return {
        "feedback_analysis": analysis,
        "rewrite_queue": rewrite_queue,
        "rewrite_instructions": {
            int(k): v
            for k, v in analysis.get("rewrite_instructions", {}).items()
        },
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["feedback_analyzer"],
    }
