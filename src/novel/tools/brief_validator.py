"""BriefValidator — checks if a generated chapter fulfilled its chapter_brief task list.

Called by QualityReviewer after chapter generation. Uses LLM to evaluate
whether the chapter text satisfies each item in the chapter_brief.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.novel.models.validation import BriefFulfillmentReport, BriefItemResult
from src.novel.utils import extract_json_from_llm

log = logging.getLogger("novel.tools")

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_VALIDATION_SYSTEM = """\
你是一位专业的网文质量审查员。你的任务是验证章节内容是否完成了大纲中规定的任务。

任务：
1. 阅读章节内容和任务书（chapter_brief）
2. 逐项检查是否完成
3. 给出明确的通过/失败判断

返回严格的 JSON 格式（不要添加任何额外文字）：
{
  "main_conflict_fulfilled": true/false,
  "payoff_delivered": true/false,
  "character_arc_step_taken": true/false,
  "foreshadowing_planted": [true, false, ...],
  "foreshadowing_collected": [true, true, ...],
  "end_hook_present": true/false,
  "item_results": [
    {
      "item_name": "main_conflict",
      "expected": "预期内容",
      "fulfilled": true,
      "evidence": "章节中的证据文本",
      "reason": "通过/失败原因"
    }
  ],
  "unfulfilled_items": ["item1", "item2"],
  "overall_pass": true/false
}
"""

_VALIDATION_USER = """\
## 章节任务书
{brief_formatted}

## 章节正文（仅检查是否完成任务，不评价文笔）
{chapter_text}

请验证上述任务是否在正文中完成。
"""


# ---------------------------------------------------------------------------
# BriefValidator
# ---------------------------------------------------------------------------


class BriefValidator:
    """Validate chapter text against its chapter_brief specifications.

    Uses LLM to evaluate whether each item in the chapter_brief was fulfilled
    by the generated chapter text.  Returns a ``BriefFulfillmentReport`` with
    per-item results, a pass rate, and suggested debts for unfulfilled items.

    Example::

        from src.novel.tools.brief_validator import BriefValidator

        validator = BriefValidator(llm_client)
        report = validator.validate_chapter(
            chapter_text="主角与反派展开了激烈的战斗...",
            chapter_brief={"main_conflict": "主角与反派首次正面冲突", "payoff": "获得秘籍"},
            chapter_number=5,
        )
        print(report.overall_pass)   # True / False
        print(report.pass_rate)      # 0.0 - 1.0
        print(report.unfulfilled_items)  # ["payoff"]

    Args:
        llm_client: LLMClient instance (has ``.chat()`` method).
    """

    def __init__(self, llm_client: Any) -> None:
        self.llm = llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_chapter(
        self,
        chapter_text: str,
        chapter_brief: dict,
        chapter_number: int = 1,
    ) -> dict:
        """Validate whether chapter fulfills its brief.

        Args:
            chapter_text: The generated chapter full text.
            chapter_brief: Dict with keys like ``main_conflict``, ``payoff``,
                ``character_arc_step``, ``foreshadowing_plant``,
                ``foreshadowing_collect``, ``end_hook_type``.
            chapter_number: For logging/reporting.

        Returns:
            dict with:
                - ``chapter_number``: int
                - ``overall_pass``: bool
                - ``pass_rate``: float (0.0–1.0)
                - ``item_results``: list[dict] — each has item_name, expected,
                  fulfilled (bool), evidence, reason
                - ``unfulfilled_items``: list[str] — names of unfulfilled items
                - ``suggested_debts``: list[dict] — debts to create for
                  unfulfilled mandatory items
        """
        # Handle empty/missing brief — skip LLM call
        if not chapter_brief or all(not v for v in chapter_brief.values()):
            log.warning("章节任务书为空，跳过验证（默认通过）")
            return {
                "chapter_number": chapter_number,
                "overall_pass": True,
                "pass_rate": 1.0,
                "item_results": [],
                "unfulfilled_items": [],
                "suggested_debts": [],
            }

        # Format brief items into readable bullet points
        brief_lines = self._format_brief(chapter_brief)

        if not brief_lines:
            log.warning("章节任务书无有效字段，跳过验证（默认通过）")
            return {
                "chapter_number": chapter_number,
                "overall_pass": True,
                "pass_rate": 1.0,
                "item_results": [],
                "unfulfilled_items": [],
                "suggested_debts": [],
            }

        brief_formatted = "\n".join(brief_lines)

        # Truncate chapter text for token efficiency
        chapter_excerpt = chapter_text[:3000]
        if len(chapter_text) > 3000:
            chapter_excerpt += "\n\n（章节过长，已截取前 3000 字符）"

        user_msg = _VALIDATION_USER.format(
            brief_formatted=brief_formatted,
            chapter_text=chapter_excerpt,
        )

        messages = [
            {"role": "system", "content": _VALIDATION_SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        try:
            response = self.llm.chat(
                messages, temperature=0.2, json_mode=True, max_tokens=2048
            )
            parsed = self._parse_response(response.content)

            # Build item_results list
            item_results = []
            for item in parsed.get("item_results", []):
                item_results.append({
                    "item_name": item.get("item_name", ""),
                    "expected": item.get("expected", ""),
                    "fulfilled": bool(item.get("fulfilled", True)),
                    "evidence": item.get("evidence"),
                    "reason": item.get("reason"),
                })

            unfulfilled_items = parsed.get("unfulfilled_items", [])

            # Calculate pass_rate from item_results
            if item_results:
                total_items = len(item_results)
                passed_items = sum(1 for it in item_results if it["fulfilled"])
                pass_rate = passed_items / total_items
            else:
                pass_rate = 1.0

            overall_pass = parsed.get("overall_pass", True)

            # Generate suggested debts for unfulfilled mandatory items
            suggested_debts = self._generate_suggested_debts(
                chapter_brief, parsed, chapter_number
            )

            log.info(
                "章节任务书验证完成 (第%d章): 总体通过=%s, 通过率=%.2f, 未完成=%s",
                chapter_number, overall_pass, pass_rate, unfulfilled_items,
            )

            return {
                "chapter_number": chapter_number,
                "overall_pass": overall_pass,
                "pass_rate": pass_rate,
                "item_results": item_results,
                "unfulfilled_items": unfulfilled_items,
                "suggested_debts": suggested_debts,
            }

        except Exception as exc:
            log.error("章节任务书验证失败 (第%d章): %s", chapter_number, exc)
            # Return permissive default on error
            return {
                "chapter_number": chapter_number,
                "overall_pass": True,
                "pass_rate": 1.0,
                "item_results": [],
                "unfulfilled_items": [f"验证失败: {exc!s}"],
                "suggested_debts": [],
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _format_brief(self, chapter_brief: dict) -> list[str]:
        """Format chapter_brief dict into readable bullet points for LLM.

        Args:
            chapter_brief: The chapter brief dictionary.

        Returns:
            List of formatted strings; empty if no valid fields found.
        """
        lines: list[str] = []

        if chapter_brief.get("main_conflict"):
            lines.append(f"- 主冲突：{chapter_brief['main_conflict']}")
        if chapter_brief.get("payoff"):
            lines.append(f"- 本章爽点/回报：{chapter_brief['payoff']}")
        if chapter_brief.get("character_arc_step"):
            lines.append(f"- 角色弧线推进：{chapter_brief['character_arc_step']}")

        plant_list = chapter_brief.get("foreshadowing_plant", [])
        if isinstance(plant_list, str):
            plant_list = [plant_list]
        if plant_list:
            lines.append(f"- 需要埋设的伏笔：{'、'.join(plant_list)}")

        collect_list = chapter_brief.get("foreshadowing_collect", [])
        if isinstance(collect_list, str):
            collect_list = [collect_list]
        if collect_list:
            lines.append(f"- 需要回收的伏笔：{'、'.join(collect_list)}")

        if chapter_brief.get("end_hook_type"):
            lines.append(f"- 章尾钩子类型：{chapter_brief['end_hook_type']}")

        return lines

    def _parse_response(self, content: str) -> dict:
        """Parse LLM response into a dict, with robust fallback.

        First tries ``extract_json_from_llm``, then falls back to manual
        brace extraction via ``json.loads``.

        Args:
            content: Raw LLM response text.

        Returns:
            Parsed dict.  Returns empty dict if all parsing fails.
        """
        # Primary: use the shared utility
        try:
            return extract_json_from_llm(content)
        except (ValueError, TypeError):
            pass

        # Fallback: try raw json.loads
        try:
            result = json.loads(content)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, TypeError):
            pass

        # Last resort: find first { ... last }
        start = content.find("{") if content else -1
        end = content.rfind("}") if content else -1
        if start >= 0 and end > start:
            try:
                result = json.loads(content[start : end + 1])
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        log.warning("无法解析 BriefValidator LLM 响应: %s", content[:200])
        return {}

    def _generate_suggested_debts(
        self, chapter_brief: dict, parsed: dict, chapter_number: int
    ) -> list[dict]:
        """Generate suggested debts for unfulfilled mandatory items.

        Args:
            chapter_brief: Original chapter brief dict.
            parsed: Parsed LLM response dict.
            chapter_number: Source chapter number.

        Returns:
            List of debt suggestion dicts.
        """
        debts: list[dict] = []

        if not parsed.get("main_conflict_fulfilled", True):
            debts.append({
                "type": "must_pay_next",
                "description": (
                    f"第{chapter_number}章未完成: main_conflict — "
                    f"{chapter_brief.get('main_conflict', '未指定')}"
                ),
                "urgency_level": "high",
            })

        if not parsed.get("payoff_delivered", True) and chapter_brief.get("payoff"):
            debts.append({
                "type": "must_pay_next",
                "description": (
                    f"第{chapter_number}章未完成: payoff — "
                    f"{chapter_brief.get('payoff', '未指定')}"
                ),
                "urgency_level": "high",
            })

        if not parsed.get("character_arc_step_taken", True) and chapter_brief.get("character_arc_step"):
            debts.append({
                "type": "pay_within_3",
                "description": (
                    f"第{chapter_number}章未完成: character_arc_step — "
                    f"{chapter_brief.get('character_arc_step', '未指定')}"
                ),
                "urgency_level": "normal",
            })

        if not parsed.get("end_hook_present", True) and chapter_brief.get("end_hook_type"):
            debts.append({
                "type": "pay_within_3",
                "description": (
                    f"第{chapter_number}章未完成: end_hook_type — "
                    f"{chapter_brief.get('end_hook_type', '未指定')}"
                ),
                "urgency_level": "normal",
            })

        # Check foreshadowing items
        planted_results = parsed.get("foreshadowing_planted", [])
        plant_list = chapter_brief.get("foreshadowing_plant", [])
        if isinstance(plant_list, str):
            plant_list = [plant_list]
        for i, planted in enumerate(planted_results):
            if not planted and i < len(plant_list):
                debts.append({
                    "type": "pay_within_3",
                    "description": (
                        f"第{chapter_number}章未完成: foreshadowing_plant — "
                        f"{plant_list[i]}"
                    ),
                    "urgency_level": "normal",
                })

        collected_results = parsed.get("foreshadowing_collected", [])
        collect_list = chapter_brief.get("foreshadowing_collect", [])
        if isinstance(collect_list, str):
            collect_list = [collect_list]
        for i, collected in enumerate(collected_results):
            if not collected and i < len(collect_list):
                debts.append({
                    "type": "must_pay_next",
                    "description": (
                        f"第{chapter_number}章未完成: foreshadowing_collect — "
                        f"{collect_list[i]}"
                    ),
                    "urgency_level": "high",
                })

        return debts
