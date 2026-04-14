"""版本化设定查询辅助 —— 根据章节号定位"当时有效"的实体版本。

当角色、世界观等实体有多条记录（每条带 effective_from_chapter /
deprecated_at_chapter）时，可用这些函数查询任意章节 N 上下文应使用
哪一条记录。适用于：
  - PlotPlanner / Writer 在生成章节 N 时读到正确的角色版本
  - UI / MCP 工具回溯历史时显示彼时的设定

实体版本字段约定（与编辑器 base.py 保持一致）：
  - effective_from_chapter: int | None  生效起始章节（含）。None = 始终生效
  - deprecated_at_chapter:  int | None  失效起始章节（不含）。None = 永久有效
  - version:                int          单调递增版本号，冲突时用作 tie-breaker
"""

from __future__ import annotations

from typing import Iterable


def is_effective_at(entry: dict, chapter_num: int) -> bool:
    """判断实体记录在 chapter_num 上是否有效。

    规则：
      - effective_from_chapter <= chapter_num（None 视为无下界）
      - deprecated_at_chapter > chapter_num（None 视为无上界）
    """
    effective_from = entry.get("effective_from_chapter")
    deprecated_at = entry.get("deprecated_at_chapter")

    if effective_from is not None and chapter_num < effective_from:
        return False
    if deprecated_at is not None and chapter_num >= deprecated_at:
        return False
    return True


def get_setting_at_chapter(
    entries: Iterable[dict],
    entity_id: str,
    chapter_num: int,
    *,
    id_field: str = "character_id",
) -> dict | None:
    """返回 entity_id 在第 chapter_num 章时生效的那一条记录。

    Args:
        entries: 实体记录集合（如 ``novel_data["characters"]``）。
        entity_id: 要查询的实体 ID。
        chapter_num: 目标章节号（整数，>=1）。
        id_field: entries 中用于匹配的 ID 字段名，默认 ``character_id``。

    Returns:
        匹配的实体 dict；若没有任何记录在该章节生效则返回 None。

    多版本冲突时按以下顺序打破平局：
      1. ``effective_from_chapter`` 更大的（更近的那一版）
      2. ``version`` 更大的
    """
    if chapter_num < 1:
        raise ValueError(f"chapter_num 必须 >= 1，收到 {chapter_num}")

    matches: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get(id_field) != entity_id:
            continue
        if is_effective_at(entry, chapter_num):
            matches.append(entry)

    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    def _sort_key(e: dict) -> tuple[int, int]:
        eff = e.get("effective_from_chapter")
        ver = e.get("version", 0)
        return (eff if eff is not None else -1, ver if isinstance(ver, int) else 0)

    matches.sort(key=_sort_key, reverse=True)
    return matches[0]


def list_settings_at_chapter(
    entries: Iterable[dict],
    chapter_num: int,
    *,
    id_field: str = "character_id",
) -> list[dict]:
    """返回 entries 中在第 chapter_num 章时所有生效的记录。

    对每个 ``id_field`` 值，只返回该章节上的一个有效版本（按
    get_setting_at_chapter 的 tie-breaker 规则选取）。没有 id_field
    的记录按全局维度处理（返回所有生效记录，不去重）。
    """
    if chapter_num < 1:
        raise ValueError(f"chapter_num 必须 >= 1，收到 {chapter_num}")

    seen_ids: set = set()
    results: list[dict] = []
    no_id_entries: list[dict] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not is_effective_at(entry, chapter_num):
            continue
        eid = entry.get(id_field)
        if eid is None:
            no_id_entries.append(entry)
            continue
        if eid in seen_ids:
            continue
        # 多版本解析
        resolved = get_setting_at_chapter(
            entries, eid, chapter_num, id_field=id_field
        )
        if resolved is not None:
            results.append(resolved)
            seen_ids.add(eid)

    results.extend(no_id_entries)
    return results


def get_chapter_outline_at(
    chapters: Iterable[dict], chapter_number: int
) -> dict | None:
    """从 outline.chapters 中取出 chapter_number 对应的那一条。

    outline 的版本语义稍有不同：chapter_number 本身就是唯一键，一般
    不存在同章节多版本并存（更新是原地 merge）。此函数存在是为了
    对齐调用方式，避免手写线性查找。
    """
    for entry in chapters:
        if isinstance(entry, dict) and entry.get("chapter_number") == chapter_number:
            return entry
    return None
