"""DEPRECATED — AI 味短语黑名单已停用。

Phase 0 架构重构：硬编码黑名单被砍。AI 味检测将在 Phase 1 由
StyleProfile（按项目学习的风格画像）接管，不再依赖全局短语列表。

保留本模块仅为向后兼容：老代码路径（例如 ``quality_check_tool``）
仍会 import ``check_ai_flavor`` / ``get_blacklist``。当前实现直接
返回空结果，相当于"暂不检测"。

TODO(phase-1): StyleProfile 接管后删除本文件及所有引用。
"""

from __future__ import annotations


def get_blacklist() -> list[str]:
    """返回空黑名单。

    历史版本返回 50+ 条硬编码短语；已废弃。
    """
    return []


def check_ai_flavor(text: str) -> list[tuple[str, int]]:
    """始终返回空命中列表。

    历史版本扫描全局黑名单短语；现在不做任何检测，等待
    Phase 1 StyleProfile 接管。

    Args:
        text: 要检查的文本（忽略）。

    Returns:
        始终为空列表。
    """
    return []
