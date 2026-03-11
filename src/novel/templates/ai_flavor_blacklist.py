"""AI 味短语黑名单

收录在 AI 生成中文小说中高频出现的模式化短语，
用于检测和消除 AI 味。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 黑名单数据（按类别分组）
# ---------------------------------------------------------------------------

_BLACKLIST_BY_CATEGORY: dict[str, list[str]] = {
    "情感类": [
        "内心翻涌",
        "心中涌起一股",
        "莫名的情绪",
        "一股暖流涌上心头",
        "心头一颤",
        "心中五味杂陈",
        "一股复杂的情绪",
        "心中泛起涟漪",
        "内心深处的某根弦被拨动",
        "眼眶不由得湿润",
        "莫名的感动",
        "百感交集",
        "心如刀绞",
        "一股酸涩涌上鼻尖",
    ],
    "动作类": [
        "嘴角勾起一抹",
        "嘴角微微上扬",
        "眼神一凛",
        "眉头微蹙",
        "不由自主地攥紧了拳头",
        "身形一闪",
        "嘴角挂着一丝",
        "目光如炬",
        "眼中闪过一丝",
        "微微眯起双眼",
        "下意识地握紧",
        "浑身一震",
    ],
    "描写类": [
        "莫名的力量",
        "一股无形的威压",
        "仿佛时间在这一刻静止",
        "空气仿佛凝固",
        "一股令人窒息的气息",
        "如同潮水般涌来",
        "宛如天神降世",
        "恍若隔世",
        "犹如一道闪电划过脑海",
        "周围的空气都变得凝重起来",
        "仿佛整个世界都安静了",
        "弥漫着一股淡淡的",
    ],
    "转折类": [
        "然而他并不知道",
        "殊不知",
        "却不曾想",
        "谁也没有想到",
        "命运的齿轮开始转动",
        "一切都将发生改变",
        "故事才刚刚开始",
        "这一切只是开始",
        "真正的考验还在后面",
        "好戏才刚刚开始",
        "一场风暴正在酝酿",
        "暗流涌动",
    ],
}

# 扁平化的完整列表（缓存）
_FLAT_BLACKLIST: list[str] | None = None


def _build_flat_list() -> list[str]:
    """构建扁平化黑名单列表。"""
    global _FLAT_BLACKLIST  # noqa: PLW0603
    if _FLAT_BLACKLIST is None:
        result: list[str] = []
        for phrases in _BLACKLIST_BY_CATEGORY.values():
            result.extend(phrases)
        _FLAT_BLACKLIST = result
    return _FLAT_BLACKLIST


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def get_blacklist() -> list[str]:
    """返回完整的 AI 味短语黑名单列表。

    Returns:
        包含所有黑名单短语的列表（至少 50 个）
    """
    return list(_build_flat_list())


def check_ai_flavor(text: str) -> list[tuple[str, int]]:
    """检测文本中命中的 AI 味短语。

    Args:
        text: 要检查的文本

    Returns:
        命中结果列表，每个元素为 (短语, 首次出现位置)。
        按出现位置升序排列。
    """
    if not text:
        return []

    hits: list[tuple[str, int]] = []
    blacklist = _build_flat_list()

    for phrase in blacklist:
        pos = text.find(phrase)
        if pos != -1:
            hits.append((phrase, pos))

    # 按出现位置排序
    hits.sort(key=lambda x: x[1])
    return hits
