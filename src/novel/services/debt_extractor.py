"""Extract narrative debts from generated chapters.

Uses a combination of rule-based regex patterns and optional LLM analysis
to identify promises, unresolved tensions, and pending actions that create
narrative obligations for future chapters.

Example::

    extractor = DebtExtractor(llm_client=my_llm)
    result = extractor.extract_from_chapter(
        chapter_text="他发誓一定要为师父报仇...",
        chapter_number=5,
        method="hybrid",
    )
    print(result["debts"])
"""

from __future__ import annotations

import json
import logging
import re
from uuid import uuid4

log = logging.getLogger("novel.services")


# ---------------------------------------------------------------
# Regex patterns for rule-based extraction
# ---------------------------------------------------------------

# Pattern group 1: Explicit promises / vows
_PROMISE_PATTERNS = [
    (r"一定要.{2,30}", "promise"),
    (r"必须.{2,30}", "promise"),
    (r"答应.{2,30}", "promise"),
    (r"发誓.{2,30}", "promise"),
    (r"承诺.{2,30}", "promise"),
]

# Pattern group 2: Unresolved mysteries / tension
_UNRESOLVED_PATTERNS = [
    (r"究竟.{2,20}", "unresolved"),
    (r"到底.{2,20}", "unresolved"),
    (r"谜团.{2,20}", "unresolved"),
    (r"秘密.{2,20}", "unresolved"),
    (r"真相.{2,20}", "unresolved"),
]

# Pattern group 3: Pending actions (character left but didn't arrive)
_ACTION_PATTERNS = [
    (r"出发.{0,10}(前往|去|赶往)", "action"),
    (r"赶往.{2,20}", "action"),
    (r"前去.{2,20}", "action"),
    (r"启程.{2,20}", "action"),
    (r"(转身|起身|迈步).{0,10}(离开|前往|走向)", "action"),
    (r"准备(去|做|开始).{2,20}", "action"),
]

# Pattern group 4: Emotional debts
_EMOTIONAL_PATTERNS = [
    (r"心中一痛.{0,20}", "emotional"),
    (r"泪水.{2,20}", "emotional"),
    (r"仇恨.{2,20}", "emotional"),
    (r"誓言.{2,20}", "emotional"),
]


# ---------------------------------------------------------------
# LLM prompt templates
# ---------------------------------------------------------------

_EXTRACTION_SYSTEM = """\
你是一位专业的网文叙事顾问。你的任务是从章节内容中识别出所有需要后续解决的叙事债务（narrative debts）。

叙事债务包括：
1. 角色明确的承诺或计划（"我会..."/"明天我..."/"下次..."）
2. 引入但未解决的冲突（打斗被打断、悬念未揭晓）
3. 对读者的暗示（"这件事的后果，他还不知道..."）
4. 未完成的角色行动（"他转身离开，准备去..."）
5. 情感未解决（"她心中的疑惑更深了..."）

返回严格的 JSON 格式（不要添加任何额外文字）：
{
  "debts": [
    {
      "type": "must_pay_next 或 pay_within_3 或 long_tail_payoff",
      "description": "具体债务描述",
      "character_pending_actions": ["角色需要做的事"],
      "emotional_debt": "情感债务描述或null",
      "target_chapter": null,
      "urgency_level": "normal 或 high 或 critical"
    }
  ]
}
"""

_EXTRACTION_USER = """\
## 章节正文
{chapter_text}

请识别出所有需要后续解决的叙事债务。
"""


# ---------------------------------------------------------------
# Mapping from pattern category to debt type / urgency
# ---------------------------------------------------------------

_CATEGORY_MAPPING = {
    "promise": ("pay_within_3", "normal"),
    "unresolved": ("long_tail_payoff", "normal"),
    "action": ("must_pay_next", "high"),
    "emotional": ("long_tail_payoff", "normal"),
}


class DebtExtractor:
    """Extract narrative debts from chapter text using rules and/or LLM.

    Args:
        llm_client: An ``LLMClient`` instance, or ``None`` to disable
            LLM-based extraction (rule-based only).
    """

    def __init__(self, llm_client=None) -> None:
        self.llm = llm_client

    def extract_from_chapter(
        self,
        chapter_text: str,
        chapter_number: int,
        method: str = "hybrid",
    ) -> dict:
        """Extract debts from a chapter.

        Args:
            chapter_text: The generated chapter content.
            chapter_number: Chapter number (used as ``source_chapter``).
            method: One of ``"rule_based"``, ``"llm"``, or ``"hybrid"``.

        Returns:
            Dict with keys:

            - ``debts``: list of debt dicts, each containing ``debt_id``,
              ``source_chapter``, ``type``, ``description``,
              ``urgency_level``, and optionally ``character_pending_actions``
              and ``emotional_debt``.
            - ``method``: The actual method used.
            - ``confidence``: Float 0.0-1.0 indicating extraction quality.
        """
        if method == "rule_based":
            debts = self._extract_rule_based(chapter_text, chapter_number)
            return {
                "debts": debts,
                "method": "rule_based",
                "confidence": 0.6,
            }

        if method == "llm":
            if self.llm:
                debts = self._extract_llm(chapter_text, chapter_number)
                return {
                    "debts": debts,
                    "method": "llm",
                    "confidence": 0.9 if debts else 0.0,
                }
            log.warning("LLM 不可用，回退到规则提取")
            debts = self._extract_rule_based(chapter_text, chapter_number)
            return {
                "debts": debts,
                "method": "rule_based",
                "confidence": 0.6,
            }

        # hybrid: combine rule-based and LLM results
        rule_debts = self._extract_rule_based(chapter_text, chapter_number)

        if self.llm:
            llm_debts = self._extract_llm(chapter_text, chapter_number)
            # LLM results have priority; add non-duplicate rule results
            combined = llm_debts + [
                d for d in rule_debts
                if not any(self._is_similar(d, ld) for ld in llm_debts)
            ]
            combined = self._deduplicate_debts(combined)
            return {
                "debts": combined,
                "method": "hybrid",
                "confidence": 0.85,
            }

        return {
            "debts": rule_debts,
            "method": "rule_based",
            "confidence": 0.6,
        }

    # ------------------------------------------------------------------
    # Rule-based extraction
    # ------------------------------------------------------------------

    def _extract_rule_based(
        self, chapter_text: str, chapter_number: int
    ) -> list[dict]:
        """Use regex patterns to find promises, unresolved tension, etc.

        Args:
            chapter_text: Full chapter text.
            chapter_number: Source chapter number.

        Returns:
            List of debt dicts.
        """
        debts: list[dict] = []
        idx = 0

        all_patterns = (
            _PROMISE_PATTERNS
            + _UNRESOLVED_PATTERNS
            + _ACTION_PATTERNS
            + _EMOTIONAL_PATTERNS
        )

        for pattern_str, category in all_patterns:
            matches = re.finditer(pattern_str, chapter_text)
            for match in matches:
                text = match.group(0)
                debt_type, urgency = _CATEGORY_MAPPING[category]

                debt: dict = {
                    "debt_id": f"debt_{chapter_number}_{idx}_{uuid4().hex[:6]}",
                    "source_chapter": chapter_number,
                    "type": debt_type,
                    "description": _make_description(category, text),
                    "urgency_level": urgency,
                }

                if category == "action":
                    debt["character_pending_actions"] = [text]
                if category == "emotional":
                    debt["emotional_debt"] = text

                debts.append(debt)
                idx += 1

        debts = self._deduplicate_debts(debts)
        log.info("规则提取识别到 %d 个债务 (第%d章)", len(debts), chapter_number)
        return debts

    # ------------------------------------------------------------------
    # LLM-based extraction
    # ------------------------------------------------------------------

    def _extract_llm(
        self, chapter_text: str, chapter_number: int
    ) -> list[dict]:
        """Use LLM to extract debts from chapter text.

        Sends a truncated chapter (max 3000 chars) to the LLM with a
        structured extraction prompt, then parses the JSON response.

        Args:
            chapter_text: Full chapter text.
            chapter_number: Source chapter number.

        Returns:
            List of debt dicts.
        """
        if not self.llm:
            return []

        # Truncate to 3000 chars
        excerpt = chapter_text[:3000]
        if len(chapter_text) > 3000:
            excerpt += "\n\n（章节过长，已截取前 3000 字符）"

        user_msg = _EXTRACTION_USER.format(chapter_text=excerpt)
        messages = [
            {"role": "system", "content": _EXTRACTION_SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        try:
            response = self.llm.chat(
                messages,
                temperature=0.3,
                json_mode=True,
                max_tokens=2048,
            )
            parsed = _parse_json_response(response.content)
            raw_debts = parsed.get("debts", [])

            debts: list[dict] = []
            for i, raw in enumerate(raw_debts):
                debt_type = raw.get("type", "pay_within_3")
                # Validate type
                if debt_type not in (
                    "must_pay_next", "pay_within_3", "long_tail_payoff"
                ):
                    debt_type = "pay_within_3"

                urgency = raw.get("urgency_level", "normal")
                if urgency not in ("normal", "high", "critical"):
                    urgency = "normal"

                debt: dict = {
                    "debt_id": (
                        f"debt_{chapter_number}_{i}_{uuid4().hex[:6]}"
                    ),
                    "source_chapter": chapter_number,
                    "type": debt_type,
                    "description": raw.get("description", "未描述"),
                    "urgency_level": urgency,
                }

                actions = raw.get("character_pending_actions")
                if actions:
                    debt["character_pending_actions"] = actions

                emotional = raw.get("emotional_debt")
                if emotional:
                    debt["emotional_debt"] = emotional

                target = raw.get("target_chapter")
                if target is not None:
                    debt["target_chapter"] = target

                debts.append(debt)

            log.info(
                "LLM 提取识别到 %d 个债务 (第%d章)",
                len(debts), chapter_number,
            )
            return debts

        except Exception as exc:
            log.error("LLM 债务提取失败 (第%d章): %s", chapter_number, exc)
            return []

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def _is_similar(debt1: dict, debt2: dict) -> bool:
        """Check if two debts are similar based on description overlap.

        Two debts are considered similar if they have the same type
        and their descriptions share more than 50% of their words
        (Jaccard similarity).

        Args:
            debt1: First debt dict.
            debt2: Second debt dict.

        Returns:
            ``True`` if the debts are similar enough to be duplicates.
        """
        if debt1.get("type") != debt2.get("type"):
            return False

        desc1 = set(debt1.get("description", ""))
        desc2 = set(debt2.get("description", ""))

        if not desc1 or not desc2:
            return False

        # For Chinese text, character-level overlap is more meaningful
        overlap = len(desc1 & desc2)
        union = len(desc1 | desc2)
        similarity = overlap / union if union > 0 else 0
        return similarity > 0.5

    @staticmethod
    def _deduplicate_debts(debts: list[dict]) -> list[dict]:
        """Remove duplicate/similar debts.

        Keeps the first occurrence when duplicates are detected.

        Args:
            debts: List of debt dicts, possibly with duplicates.

        Returns:
            Deduplicated list.
        """
        unique: list[dict] = []
        for debt in debts:
            if not any(
                DebtExtractor._is_similar(debt, u) for u in unique
            ):
                unique.append(debt)
        return unique


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _make_description(category: str, matched_text: str) -> str:
    """Build a human-readable description from pattern category and match."""
    labels = {
        "promise": "角色承诺",
        "unresolved": "悬念未解",
        "action": "待完成动作",
        "emotional": "情感未了",
    }
    label = labels.get(category, "叙事债务")
    return f"{label}: {matched_text}"


def _parse_json_response(text: str) -> dict:
    """Parse JSON from an LLM response, handling markdown code blocks."""
    if not text or not text.strip():
        return {}

    text = text.strip()

    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try markdown code block
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if code_block:
        try:
            result = json.loads(code_block.group(1).strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Try to find first { ... } block
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            result = json.loads(text[brace_start:brace_end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    log.warning("无法从LLM响应中解析JSON: %s", text[:200])
    return {}
