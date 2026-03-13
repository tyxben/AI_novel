"""大纲模板定义

提供四种标准大纲模板：
- cyclic_upgrade: 循环升级模板，适合玄幻/都市/系统流
- multi_thread: 多线交织模板，适合群像/宫斗/悬疑
- classic_four_act: 经典四幕模板，适合武侠/仙侠/文学
- scifi_crisis: 科幻危机模板，适合硬科幻/末日/太空歌剧
"""

from __future__ import annotations

from src.novel.models.novel import OutlineTemplate

# ---------------------------------------------------------------------------
# 模板定义
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, OutlineTemplate] = {
    "cyclic_upgrade": OutlineTemplate(
        name="cyclic_upgrade",
        description=(
            "循环升级结构：以主角不断突破瓶颈为主线，"
            "每卷遵循「蓄力 -> 冲突 -> 爆发 -> 收获」的循环。"
            "适合玄幻修仙、都市系统流、游戏异界等题材。"
            "节奏紧凑，爽点密集，单卷自成小高潮。"
        ),
        act_count=3,
        default_chapters_per_volume=30,
    ),
    "multi_thread": OutlineTemplate(
        name="multi_thread",
        description=(
            "多线交织结构：多条情节线并行推进，定期交汇产生冲突。"
            "适合群像戏、宫斗权谋、悬疑推理、史诗奇幻等题材。"
            "需要精心管理各线节奏，在交汇点制造最大张力。"
        ),
        act_count=4,
        default_chapters_per_volume=25,
    ),
    "classic_four_act": OutlineTemplate(
        name="classic_four_act",
        description=(
            "经典四幕结构：起（铺垫世界与人物）、承（矛盾激化发展）、"
            "转（核心反转与高潮）、合（收束与余韵）。"
            "适合武侠、仙侠、传统文学、言情等注重情感弧光的题材。"
            "结构稳健，叙事完整，适合中长篇。"
        ),
        act_count=4,
        default_chapters_per_volume=20,
    ),
    "scifi_crisis": OutlineTemplate(
        name="scifi_crisis",
        description=(
            "科幻危机结构：危机开场 → 探索真相 → 绝境突围 → 代价与启示。"
            "适合硬科幻、末日科幻、太空歌剧等题材。"
            "开场即危机，节奏紧凑，概念揭示穿插在行动中。"
        ),
        act_count=4,
        default_chapters_per_volume=15,
    ),
}

# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def get_template(name: str) -> OutlineTemplate:
    """根据名称获取大纲模板。

    Args:
        name: 模板名称，支持 cyclic_upgrade / multi_thread / classic_four_act

    Returns:
        OutlineTemplate 实例

    Raises:
        KeyError: 模板名称不存在
    """
    if name not in _TEMPLATES:
        available = ", ".join(sorted(_TEMPLATES.keys()))
        raise KeyError(f"未知模板 '{name}'，可用模板: {available}")
    return _TEMPLATES[name].model_copy()


def list_templates() -> list[OutlineTemplate]:
    """返回所有可用大纲模板列表。"""
    return [t.model_copy() for t in _TEMPLATES.values()]
