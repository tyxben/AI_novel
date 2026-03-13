"""节奏模板定义

按题材提供默认节奏曲线（MoodTag 序列），
控制章节情绪的起伏节奏。
"""

from __future__ import annotations

from src.novel.models.chapter import MoodTag

# ---------------------------------------------------------------------------
# 节奏模板数据
#
# 每个模板是一个 MoodTag 序列模式，代表一卷中章节的情绪走向。
# 实际使用时会根据 volume_length 进行插值/裁剪。
# ---------------------------------------------------------------------------

_RHYTHM_PATTERNS: dict[str, list[MoodTag]] = {
    # 玄幻修仙：蓄力为主，定期小爽，卷末大爽
    "玄幻": [
        MoodTag.BUILDUP,
        MoodTag.BUILDUP,
        MoodTag.SMALL_WIN,
        MoodTag.BUILDUP,
        MoodTag.DAILY,
        MoodTag.BUILDUP,
        MoodTag.SMALL_WIN,
        MoodTag.BUILDUP,
        MoodTag.TWIST,
        MoodTag.BIG_WIN,
    ],
    # 都市：日常铺垫多，穿插打脸爽点
    "都市": [
        MoodTag.DAILY,
        MoodTag.BUILDUP,
        MoodTag.SMALL_WIN,
        MoodTag.DAILY,
        MoodTag.BUILDUP,
        MoodTag.BUILDUP,
        MoodTag.SMALL_WIN,
        MoodTag.TWIST,
        MoodTag.BUILDUP,
        MoodTag.BIG_WIN,
    ],
    # 武侠：张弛有度，虐心与爽感交替
    "武侠": [
        MoodTag.BUILDUP,
        MoodTag.BUILDUP,
        MoodTag.SMALL_WIN,
        MoodTag.TRANSITION,
        MoodTag.HEARTBREAK,
        MoodTag.BUILDUP,
        MoodTag.BUILDUP,
        MoodTag.TWIST,
        MoodTag.BIG_WIN,
        MoodTag.TRANSITION,
    ],
    # 言情：以情感波动为主线
    "言情": [
        MoodTag.DAILY,
        MoodTag.BUILDUP,
        MoodTag.SMALL_WIN,
        MoodTag.DAILY,
        MoodTag.HEARTBREAK,
        MoodTag.BUILDUP,
        MoodTag.TWIST,
        MoodTag.BUILDUP,
        MoodTag.SMALL_WIN,
        MoodTag.BIG_WIN,
    ],
    # 悬疑：层层铺垫，反转密集
    "悬疑": [
        MoodTag.BUILDUP,
        MoodTag.BUILDUP,
        MoodTag.BUILDUP,
        MoodTag.TWIST,
        MoodTag.BUILDUP,
        MoodTag.SMALL_WIN,
        MoodTag.BUILDUP,
        MoodTag.TWIST,
        MoodTag.BUILDUP,
        MoodTag.BIG_WIN,
    ],
    # 科幻：开场即危机，紧凑推进，概念揭示穿插在行动中
    "科幻": [
        MoodTag.TWIST,
        MoodTag.BUILDUP,
        MoodTag.SMALL_WIN,
        MoodTag.TRANSITION,
        MoodTag.TWIST,
        MoodTag.BUILDUP,
        MoodTag.HEARTBREAK,
        MoodTag.BUILDUP,
        MoodTag.BIG_WIN,
        MoodTag.TWIST,
    ],
    # 仙侠：修炼-历劫-突破的循环
    "仙侠": [
        MoodTag.BUILDUP,
        MoodTag.BUILDUP,
        MoodTag.SMALL_WIN,
        MoodTag.BUILDUP,
        MoodTag.HEARTBREAK,
        MoodTag.BUILDUP,
        MoodTag.BUILDUP,
        MoodTag.SMALL_WIN,
        MoodTag.TWIST,
        MoodTag.BIG_WIN,
    ],
}

# 默认模式（未匹配到题材时使用）
_DEFAULT_PATTERN: list[MoodTag] = [
    MoodTag.BUILDUP,
    MoodTag.BUILDUP,
    MoodTag.SMALL_WIN,
    MoodTag.BUILDUP,
    MoodTag.TRANSITION,
    MoodTag.BUILDUP,
    MoodTag.SMALL_WIN,
    MoodTag.TWIST,
    MoodTag.BUILDUP,
    MoodTag.BIG_WIN,
]

# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def get_rhythm(genre: str, volume_length: int) -> list[MoodTag]:
    """根据题材和卷长度生成节奏序列。

    将模板模式插值/裁剪到 volume_length 长度。

    Args:
        genre: 题材名称，如 "玄幻" / "都市" / "武侠" 等
        volume_length: 该卷章节数量，必须 >= 1

    Returns:
        长度等于 volume_length 的 MoodTag 列表

    Raises:
        ValueError: volume_length < 1 时抛出
    """
    if volume_length < 1:
        raise ValueError(f"volume_length 必须 >= 1，收到 {volume_length}")

    pattern = _RHYTHM_PATTERNS.get(genre, _DEFAULT_PATTERN)
    pattern_len = len(pattern)

    if volume_length == pattern_len:
        return list(pattern)

    if volume_length < pattern_len:
        # 等间距采样，始终保留首尾
        if volume_length == 1:
            return [pattern[-1]]
        indices = [
            round(i * (pattern_len - 1) / (volume_length - 1))
            for i in range(volume_length)
        ]
        return [pattern[idx] for idx in indices]

    # volume_length > pattern_len: 线性插值拉伸
    result: list[MoodTag] = []
    for i in range(volume_length):
        # 映射到模板中的浮点位置
        pos = i * (pattern_len - 1) / (volume_length - 1)
        idx = min(round(pos), pattern_len - 1)
        result.append(pattern[idx])
    return result
