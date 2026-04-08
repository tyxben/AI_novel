"""Hook generator — produces strong chapter-end suspense for network novels."""
from __future__ import annotations
from typing import Any
import logging
import re

log = logging.getLogger("novel.services.hook_generator")


# Hook quality indicators (good chapter endings)
_STRONG_HOOK_PATTERNS = [
    re.compile(r"[？?！!]\s*$"),  # ends with question or exclamation
    re.compile(r"(突然|忽然|猛然|骤然)[^。]*[。！？]\s*$"),  # sudden event at end
    re.compile(r"(?:就在这时|与此同时|可就在|然而)[^。]*[。！？]\s*$"),  # interrupting moment
    re.compile(r"[^。]{0,30}(?:不见了|消失了|没了|断了)[。！？]\s*$"),  # something gone
    re.compile(r"[\u2026\u22ef]{2,}\s*$"),  # ellipsis
]

# Weak ending indicators (boring chapter endings)
_WEAK_ENDING_PATTERNS = [
    re.compile(r"(?:睡|休息|休整|安歇)[^。]{0,20}[。]\s*$"),  # ends with rest
    re.compile(r"(?:于是|就这样|这样|然后)[^。]{0,30}[。]\s*$"),  # narrative summary
    re.compile(r"[^。]*(?:吃|喝|吃饭|喝酒|聊天)[^。]*[。]\s*$"),  # mundane activity
]


class HookGenerator:
    """Generates and evaluates chapter-end hooks (悬念结尾)."""

    def __init__(self, llm_client=None) -> None:
        self.llm = llm_client

    def evaluate(self, chapter_text: str) -> dict[str, Any]:
        """Score the quality of a chapter's ending hook.

        Returns a dict with:
            - score: 0-10 quality score
            - hook_type: detected type (question, sudden, mystery, weak, none)
            - last_sentence: the actual ending text
            - issues: list of problems
            - needs_improvement: bool
        """
        if not chapter_text:
            return {
                "score": 0,
                "hook_type": "none",
                "last_sentence": "",
                "issues": ["chapter is empty"],
                "needs_improvement": True,
            }

        # Extract last 200 chars for analysis
        tail = chapter_text.strip()[-300:]
        last_paragraph = tail.split("\n")[-1] if "\n" in tail else tail
        last_paragraph = last_paragraph.strip()

        result = {
            "last_sentence": last_paragraph[-100:],
            "issues": [],
        }

        # Score against strong hook patterns
        score = 5  # baseline
        hook_type = "neutral"

        for pattern in _STRONG_HOOK_PATTERNS:
            if pattern.search(last_paragraph):
                score += 2
                if "突然" in last_paragraph or "忽然" in last_paragraph:
                    hook_type = "sudden_event"
                elif "？" in last_paragraph[-3:] or "?" in last_paragraph[-3:]:
                    hook_type = "question"
                elif "就在这时" in last_paragraph or "与此同时" in last_paragraph:
                    hook_type = "interrupting"
                elif "..." in last_paragraph[-5:] or "…" in last_paragraph[-5:]:
                    hook_type = "ellipsis_mystery"
                else:
                    hook_type = "strong"
                break

        # Penalize weak endings
        for pattern in _WEAK_ENDING_PATTERNS:
            if pattern.search(last_paragraph):
                score -= 3
                hook_type = "weak"
                result["issues"].append("结尾过于平淡，缺乏悬念")
                break

        # Check for explicit suspense words
        suspense_words = ["危机", "威胁", "敌人", "陷阱", "暗影", "黑影", "杀机"]
        if any(w in last_paragraph for w in suspense_words):
            score += 1

        # Cap score
        score = max(0, min(10, score))

        result["score"] = score
        result["hook_type"] = hook_type
        result["needs_improvement"] = score < 6

        return result

    def generate_hook(
        self,
        chapter_text: str,
        chapter_number: int,
        chapter_goal: str,
        next_chapter_hint: str = "",
    ) -> str | None:
        """Use LLM to generate a stronger ending paragraph for the chapter.

        Returns the new ending text, or None if generation fails.
        """
        if not self.llm:
            log.warning("HookGenerator: LLM not configured, skipping")
            return None

        if not chapter_text or len(chapter_text) < 200:
            return None

        # Take last 800 chars as context for LLM
        context = chapter_text[-800:]

        prompt = f"""你是一位网文悬念结尾专家。给定一段章节末尾内容，请重写最后一段（约 50-150 字），让悬念更强、读者更想看下一章。

要求：
1. 保持时空、人物、情节连贯
2. 用以下技巧之一制造悬念：
   - 突然出现的威胁/人物
   - 一个未回答的问题
   - 一个被打断的关键动作
   - 一个意外的发现
3. 不要生硬，要自然
4. 只输出新的最后一段，不要解释

章节号: 第{chapter_number}章
章节目标: {chapter_goal}
{f"下一章提示: {next_chapter_hint}" if next_chapter_hint else ""}

当前章节末尾：
{context}

请输出重写后的最后一段："""

        try:
            response = self.llm.chat(
                messages=[
                    {"role": "system", "content": "你是一位专业网文写手，擅长制造章节末尾悬念。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.85,
                max_tokens=400,
            )
            new_ending = response.content.strip() if response.content else ""
            if not new_ending or len(new_ending) < 20:
                return None
            return new_ending
        except Exception as exc:
            log.warning("HookGenerator LLM call failed: %s", exc)
            return None

    def replace_ending(self, chapter_text: str, new_ending: str) -> str:
        """Replace the last paragraph of chapter_text with new_ending.

        Tries to find a clean paragraph break to splice at.
        """
        if not chapter_text or not new_ending:
            return chapter_text

        # Find last paragraph break in the last 500 chars
        tail_start = max(0, len(chapter_text) - 500)
        tail = chapter_text[tail_start:]

        # Find the last \n\n
        last_break = tail.rfind("\n\n")
        if last_break >= 0:
            splice_point = tail_start + last_break + 2
            return chapter_text[:splice_point] + new_ending.strip()

        # Fallback: replace last 150 chars
        return chapter_text[:-150].rstrip() + "\n\n" + new_ending.strip()
