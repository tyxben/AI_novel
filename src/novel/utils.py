"""小说模块工具函数"""

from __future__ import annotations

import json
import re
from typing import Any


def count_words(text: str) -> int:
    """统计中文文本字数。

    计算规则：
    - 中文字符每个算 1 字
    - 英文单词每个算 1 字
    - 数字序列每段算 1 字
    - 标点符号不计入

    Args:
        text: 输入文本

    Returns:
        字数统计结果
    """
    if not text:
        return 0

    count = 0

    # 匹配中文字符（CJK统一汉字）
    chinese_chars = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text)
    count += len(chinese_chars)

    # 移除中文字符后，统计英文单词和数字
    text_no_chinese = re.sub(r"[\u4e00-\u9fff\u3400-\u4dbf]", " ", text)
    words = re.findall(r"[a-zA-Z]+|[0-9]+", text_no_chinese)
    count += len(words)

    return count


def truncate_text(text: str, max_chars: int) -> str:
    """截断文本到指定字符数，在句子边界处截断。

    优先在句号、感叹号、问号处截断，避免截断到半个句子。

    Args:
        text: 输入文本
        max_chars: 最大字符数，必须 >= 0

    Returns:
        截断后的文本（可能附加省略号）
    """
    if max_chars < 0:
        raise ValueError(f"max_chars 必须 >= 0，收到 {max_chars}")

    if not text or len(text) <= max_chars:
        return text

    if max_chars == 0:
        return ""

    # 在 max_chars 范围内寻找最后一个句子结束符
    truncated = text[:max_chars]
    sentence_ends = re.compile(r"[。！？!?\.\n]")

    last_end = -1
    for m in sentence_ends.finditer(truncated):
        last_end = m.end()

    if last_end > max_chars // 3:
        # 在合理位置找到了句子结束符
        return text[:last_end]

    # 没有找到合适的句子结束符，硬截断并添加省略号
    return truncated + "..."


def extract_json_from_llm(response: str) -> dict[str, Any]:
    """从 LLM 响应中提取 JSON 对象。

    支持以下格式：
    - 纯 JSON 字符串
    - Markdown 代码块中的 JSON (```json ... ```)
    - 混合了前后文本的 JSON

    Args:
        response: LLM 的原始响应文本

    Returns:
        解析后的字典

    Raises:
        ValueError: 无法从响应中提取有效 JSON
    """
    if not response or not response.strip():
        raise ValueError("空响应，无法提取 JSON")

    text = response.strip()

    # 1. 尝试直接解析
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 2. 尝试从 markdown 代码块中提取
    code_block_pattern = re.compile(
        r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL
    )
    match = code_block_pattern.search(text)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 3. 尝试找到第一个 { 和最后一个 } 之间的内容
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从响应中提取有效 JSON: {text[:200]}...")
