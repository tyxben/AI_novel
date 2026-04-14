"""LLM 输出 JSON 提取工具 — 统一实现。

本模块合并了 `src/novel/` 下多处重复的 `_extract_json_obj` / `_extract_json_array`
实现，提供两个稳健的 JSON 提取函数：

- ``extract_json_obj``: 从 LLM 输出中提取首个 JSON 对象
- ``extract_json_array``: 从 LLM 输出中提取 JSON 数组（支持常见 wrapper key 解包）

设计要点：
- ``extract_json_obj`` 只返回 dict，拒绝顶层为数组的 JSON
- ``extract_json_array`` 支持通过 ``unwrap_keys`` 解包 ``{"key": [...]}`` 结构，
  默认覆盖 novel 模块中所有已知 wrapper key
- 同时支持原始 JSON、markdown ```json 代码块``` 包裹、嵌入在普通文本中 3 种形态
- 任何无法解析的输入（None / 空字符串 / 垃圾文本）返回 ``None``
"""

from __future__ import annotations

import json
import re
from typing import Iterable

# 默认 unwrap keys — 覆盖 novel 模块中所有历史实现出现过的 wrapper key
# 顺序影响解包优先级：先匹配常用泛化 key，再匹配领域特定 key
_DEFAULT_UNWRAP_KEYS: tuple[str, ...] = (
    "items",
    "list",
    "results",
    "data",
    "details",
    "entries",
    "characters",
    "foreshadowings",
    "facts",
)

# 匹配 markdown code block: ```json ... ``` 或 ``` ... ```
_CODE_BLOCK_RE = re.compile(
    r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)


def _try_parse(text: str) -> object | None:
    """Attempt to json.loads a string, returning None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _extract_from_code_block(text: str) -> object | None:
    """尝试从 markdown ``` 代码块中提取并解析 JSON。

    返回解析后的 Python 对象（dict / list / 其他），失败则返回 None。
    """
    match = _CODE_BLOCK_RE.search(text)
    if not match:
        return None
    candidate = match.group(1).strip()
    if not candidate:
        return None
    return _try_parse(candidate)


def extract_json_obj(content: str | None) -> dict | None:
    """从 LLM 输出中稳健提取首个 JSON 对象。

    支持的输入形态：
    - 原始 JSON 字符串：``{"key": "value"}``
    - Markdown 代码块包裹：` ```json\n{...}\n``` `
    - 嵌入在普通文本中：``前缀 {"key": "value"} 后缀``

    Args:
        content: LLM 返回文本，允许 ``None`` / 空字符串。

    Returns:
        解析成功且顶层为 dict 时返回该 dict，否则返回 ``None``。
        （若顶层为 JSON 数组，亦返回 ``None`` — 用 ``extract_json_array`` 处理数组）
    """
    if not content or not isinstance(content, str):
        return None

    text = content.strip()
    if not text:
        return None

    # 1) 直接解析
    parsed = _try_parse(text)
    if isinstance(parsed, dict):
        return parsed

    # 2) markdown 代码块
    block = _extract_from_code_block(text)
    if isinstance(block, dict):
        return block

    # 3) 在文本中定位第一个 { 和最后一个 }，尝试解析它们之间的片段
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        parsed = _try_parse(candidate)
        if isinstance(parsed, dict):
            return parsed

    return None


def extract_json_array(
    content: str | None,
    unwrap_keys: Iterable[str] | None = None,
) -> list | None:
    """从 LLM 输出中稳健提取 JSON 数组。

    支持的输入形态：
    - 原始 JSON 数组：``[1, 2, 3]``
    - Wrapper 对象：``{"items": [...]}`` / ``{"characters": [...]}`` 等
    - Markdown 代码块：` ```json\n[...]\n``` `
    - 嵌入在普通文本中：``前缀 [1, 2] 后缀``

    Args:
        content: LLM 返回文本，允许 ``None`` / 空字符串。
        unwrap_keys: 当顶层为 dict 时，按顺序尝试这些 key 的值；若为 ``None``
            使用默认 wrapper key 列表 (items / list / results / data / details
            / entries / characters / foreshadowings / facts)。传入空列表则不
            解包任何 key。

    Returns:
        解析成功且最终得到 list 时返回该 list，否则返回 ``None``。
    """
    if not content or not isinstance(content, str):
        return None

    text = content.strip()
    if not text:
        return None

    keys: tuple[str, ...]
    if unwrap_keys is None:
        keys = _DEFAULT_UNWRAP_KEYS
    else:
        keys = tuple(unwrap_keys)

    def _unwrap_dict(obj: object) -> list | None:
        """若 obj 是 dict 且某个 unwrap_key 对应 list，返回该 list。"""
        if not isinstance(obj, dict):
            return None
        for key in keys:
            val = obj.get(key)
            if isinstance(val, list):
                return val
        return None

    # 1) 直接解析
    #    若 text 本身是合法 JSON，我们就相信它：
    #    - list  -> 直接返回
    #    - dict  -> 尝试 unwrap，成功返回 list，失败返回 None（不再扫描子串）
    #    只有当 text 根本不是合法 JSON 时，才进入后续的启发式提取。
    parsed = _try_parse(text)
    if parsed is not None:
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return _unwrap_dict(parsed)
        # 顶层是 scalar（数字/字符串/bool/None）— 无法得到数组
        return None

    # 2) markdown 代码块
    block = _extract_from_code_block(text)
    if block is not None:
        if isinstance(block, list):
            return block
        if isinstance(block, dict):
            return _unwrap_dict(block)
        return None

    # 3) 嵌入的对象：先尝试用 extract_json_obj 提取对象，再从中解包
    obj_from_text = extract_json_obj(text)
    unwrapped = _unwrap_dict(obj_from_text)
    if unwrapped is not None:
        return unwrapped

    # 4) 嵌入的数组：定位 [ ... ] 并解析
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        parsed = _try_parse(candidate)
        if isinstance(parsed, list):
            return parsed

    return None


__all__ = ["extract_json_obj", "extract_json_array"]
