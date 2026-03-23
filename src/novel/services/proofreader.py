"""AI 校对服务 - 检查标点、语法、错别字、用词问题"""
import json
import logging
import re
from typing import Any

from src.novel.models.refinement import ProofreadingIssue, ProofreadingIssueType

log = logging.getLogger("novel.proofreader")

# 校对系统提示词
_SYSTEM_PROMPT = """你是一位专业的中文校对编辑。你的任务是检查文本中的语言问题，包括：
1. 标点错误：引号不配对、句号逗号使用不当、中英文标点混用等
2. 语法问题：语句不通顺、主谓不搭配、缺少主语等
3. 错别字：同音字错用、形近字错用等
4. 用词不当：词语搭配不合理、用词重复等
5. 冗余：重复的词语、不必要的修饰等

【重要】你只检查语言层面的问题，不评判内容质量、情节逻辑、人物塑造等。
【重要】每个问题必须给出具体的原文片段和修正建议。原文片段必须是文本中能精确匹配到的原始文字。"""

_USER_PROMPT = """请检查以下文本中的语言问题，以JSON格式返回。

文本：
---
{text}
---

返回格式（JSON数组）：
[
  {{
    "issue_type": "punctuation|grammar|typo|word_choice|redundancy",
    "original": "原文中有问题的片段（必须能在原文中精确匹配）",
    "correction": "修正后的片段",
    "explanation": "简要说明问题"
  }}
]

如果没有问题，返回空数组 []。最多返回30条问题。"""


class Proofreader:
    """AI 校对服务"""

    def __init__(self, llm_client: Any) -> None:
        """
        Args:
            llm_client: LLM 客户端，需有 chat(messages, ...) -> LLMResponse 方法
        """
        self._llm = llm_client

    def proofread(self, text: str) -> list[ProofreadingIssue]:
        """对文本进行 AI 校对，返回问题列表。

        Args:
            text: 待校对的文本

        Returns:
            校对问题列表
        """
        if not text or not text.strip():
            return []

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _USER_PROMPT.format(text=text)},
        ]

        try:
            response = self._llm.chat(
                messages, temperature=0.3, json_mode=True, max_tokens=2048
            )
            raw = response.content
        except Exception as e:
            log.warning("AI 校对 LLM 调用失败: %s", e)
            return []

        return self._parse_issues(raw, text)

    def _parse_issues(
        self, raw: str, source_text: str
    ) -> list[ProofreadingIssue]:
        """解析 LLM 返回的 JSON，过滤无法匹配的问题。"""
        # 提取 JSON 数组
        try:
            # 尝试直接解析
            data = json.loads(raw)
        except json.JSONDecodeError:
            # 尝试从文本中提取 JSON 数组
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    log.warning("无法解析校对结果 JSON")
                    return []
            else:
                log.warning("校对结果中未找到 JSON 数组")
                return []

        if not isinstance(data, list):
            log.warning("校对结果不是数组: %s", type(data))
            return []

        issues: list[ProofreadingIssue] = []
        valid_types = {t.value for t in ProofreadingIssueType}

        for item in data[:30]:  # 最多30条
            if not isinstance(item, dict):
                continue

            issue_type = item.get("issue_type", "")
            original = item.get("original", "").strip()
            correction = item.get("correction", "").strip()
            explanation = item.get("explanation", "").strip()

            # 跳过无效条目
            if not original or not correction:
                continue
            if original == correction:
                continue
            if issue_type not in valid_types:
                issue_type = "grammar"  # fallback

            # 验证 original 在源文本中存在
            if original not in source_text:
                log.debug("校对问题原文不匹配，跳过: %s", original[:50])
                continue

            issues.append(
                ProofreadingIssue(
                    issue_type=ProofreadingIssueType(issue_type),
                    original=original,
                    correction=correction,
                    explanation=explanation,
                )
            )

        return issues

    @staticmethod
    def apply_fixes(
        text: str,
        issues: list[ProofreadingIssue],
        selected_indices: list[int],
    ) -> tuple[str, list[str]]:
        """应用选中的校对修正。

        Args:
            text: 原文本
            issues: 完整问题列表
            selected_indices: 用户选中的问题索引列表

        Returns:
            (修正后的文本, 失败的修正描述列表)
        """
        if not selected_indices:
            return text, []

        failures: list[str] = []
        # 收集要应用的修正，按在文本中出现的位置从后往前排序，避免位置偏移
        fixes: list[tuple[int, str, str]] = []
        for idx in selected_indices:
            if 0 <= idx < len(issues):
                issue = issues[idx]
                pos = text.find(issue.original)
                if pos >= 0:
                    fixes.append((pos, issue.original, issue.correction))
                else:
                    failures.append(
                        f"[{idx}] 原文不匹配: {issue.original[:30]}..."
                    )

        # 从后往前应用，避免位置偏移
        fixes.sort(key=lambda x: x[0], reverse=True)
        for pos, original, correction in fixes:
            text = text[:pos] + correction + text[pos + len(original) :]

        return text, failures
