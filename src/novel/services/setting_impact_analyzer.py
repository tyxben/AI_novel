"""设定修改影响分析服务"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger("novel.setting_impact")

_IMPACT_SYSTEM_PROMPT = """你是一位专业的小说编辑，擅长分析设定修改对已有章节的影响。
你需要对比修改前后的设定差异，然后检查已写的章节摘要，找出与新设定矛盾的地方。"""

_IMPACT_USER_PROMPT = """## 设定修改

**修改字段**: {field}

**修改前**:
{old_value}

**修改后**:
{new_value}

## 已写章节摘要

{chapters_summary}

## 任务

请分析这次设定修改对已写章节的影响。找出所有与新设定产生矛盾的章节。

以 JSON 格式返回：
{{
  "affected_chapters": [受影响的章节号列表],
  "conflicts": [
    {{
      "chapter_number": 章节号,
      "conflict_text": "章节中与新设定矛盾的具体内容",
      "reason": "为什么这段内容与新设定矛盾",
      "suggested_fix": "建议如何修改这段内容"
    }}
  ],
  "severity": "low|medium|high",
  "summary": "影响评估总结（一句话）"
}}

如果没有冲突，返回空的 affected_chapters 和 conflicts。"""


class SettingImpactAnalyzer:
    """设定修改影响分析。

    配合 FileManager（dict-based API）和 LLM client 使用。
    novel_data 是 FileManager.load_novel() 返回的 dict。
    """

    def __init__(self, llm_client: Any, file_manager: Any) -> None:
        self._llm = llm_client
        self._fm = file_manager

    def _generate_chapters_summary(
        self, novel_id: str, novel_data: dict
    ) -> str:
        """生成已写章节的摘要文本（供 LLM 分析用）。

        使用大纲中的 chapter_summary/goal + 章节文本前 150 字，
        限制 token 消耗。最多 40 章。
        """
        current_chapter = novel_data.get("current_chapter", 0)
        outline = novel_data.get("outline", {})
        outline_chapters = {
            co["chapter_number"]: co
            for co in outline.get("chapters", [])
            if isinstance(co, dict) and "chapter_number" in co
        }

        lines: list[str] = []
        for ch_num in range(1, current_chapter + 1):
            co = outline_chapters.get(ch_num, {})
            text = self._fm.load_chapter_text(novel_id, ch_num)

            title = co.get("title", f"第{ch_num}章")
            goal = co.get("goal", "")
            summary = co.get("chapter_summary", "")
            preview = text[:150] if text else ""

            lines.append(
                f"### 第{ch_num}章: {title}\n"
                f"- 目标: {goal}\n"
                f"- 摘要: {summary}\n"
                f"- 开头: {preview}...\n"
            )

            if ch_num >= 40:
                lines.append(
                    f"... (共 {current_chapter} 章，仅显示前40章)"
                )
                break

        return "\n".join(lines) if lines else "（暂无已写章节）"

    def analyze_impact(
        self,
        novel_id: str,
        novel_data: dict,
        modified_field: str,
        old_value: str,
        new_value: str,
    ) -> dict:
        """分析设定修改对已写章节的影响。

        Args:
            novel_id: 小说 ID
            novel_data: Novel dict（FileManager.load_novel 返回值）
            modified_field: 修改的字段名（如 "world_setting", "characters"）
            old_value: 修改前的值（JSON 字符串或纯文本摘要）
            new_value: 修改后的值

        Returns:
            影响评估结果 dict（与 SettingImpact 字段对齐）
        """
        current_chapter = novel_data.get("current_chapter", 0)

        if current_chapter == 0:
            return {
                "modified_field": modified_field,
                "old_summary": old_value[:200],
                "new_summary": new_value[:200],
                "affected_chapters": [],
                "conflicts": [],
                "severity": "low",
                "summary": "尚未写任何章节，无需评估影响。",
            }

        chapters_summary = self._generate_chapters_summary(
            novel_id, novel_data
        )

        messages = [
            {"role": "system", "content": _IMPACT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _IMPACT_USER_PROMPT.format(
                    field=modified_field,
                    old_value=old_value[:2000],
                    new_value=new_value[:2000],
                    chapters_summary=chapters_summary,
                ),
            },
        ]

        try:
            response = self._llm.chat(
                messages, temperature=0.3, json_mode=True, max_tokens=2048
            )
            raw = response.content
        except Exception as e:
            log.warning("影响评估 LLM 调用失败: %s", e)
            return {
                "modified_field": modified_field,
                "old_summary": old_value[:200],
                "new_summary": new_value[:200],
                "affected_chapters": [],
                "conflicts": [],
                "severity": "low",
                "summary": f"AI 分析失败: {e}",
            }

        return self._parse_impact(
            raw, modified_field, old_value, new_value, current_chapter
        )

    def _parse_impact(
        self,
        raw: str,
        field: str,
        old_val: str,
        new_val: str,
        max_chapter: int,
    ) -> dict:
        """解析 LLM 返回的影响评估 JSON。"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}

        if not isinstance(data, dict):
            data = {}

        affected = data.get("affected_chapters", [])
        if not isinstance(affected, list):
            affected = []
        # 过滤非法章节号
        affected = [
            ch
            for ch in affected
            if isinstance(ch, int) and 1 <= ch <= max_chapter
        ]

        conflicts: list[dict] = []
        for c in data.get("conflicts", []):
            if (
                isinstance(c, dict)
                and c.get("chapter_number")
                and c.get("reason")
            ):
                ch_num = c["chapter_number"]
                if isinstance(ch_num, int) and 1 <= ch_num <= max_chapter:
                    conflicts.append(
                        {
                            "chapter_number": ch_num,
                            "conflict_text": str(
                                c.get("conflict_text", "")
                            )[:500],
                            "reason": str(c.get("reason", ""))[:500],
                            "suggested_fix": str(
                                c.get("suggested_fix", "")
                            )[:500],
                        }
                    )

        severity = data.get("severity", "medium")
        if severity not in ("low", "medium", "high"):
            severity = "medium"

        return {
            "modified_field": field,
            "old_summary": old_val[:200],
            "new_summary": new_val[:200],
            "affected_chapters": affected,
            "conflicts": conflicts,
            "severity": severity,
            "summary": str(data.get("summary", ""))[:500],
        }
