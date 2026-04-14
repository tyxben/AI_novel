"""小说项目 v1 → v2 迁移脚本。

v2 引入版本化设定字段：
  - 角色 (novel.characters[])
  - 章节大纲 (novel.outline.chapters[])
  - （可选）世界观 (novel.world_setting)

每个实体补齐缺失的：
  - effective_from_chapter: 默认 1
  - deprecated_at_chapter:  默认 None（永久有效）
  - version:                默认 1

运行：
    python scripts/migrate_novel_v1_to_v2.py             # 默认 workspace
    python scripts/migrate_novel_v1_to_v2.py --workspace ./my_ws
    python scripts/migrate_novel_v1_to_v2.py --dry-run   # 不写盘

幂等：多次运行结果相同。若已是 v2 数据则原样保留，不新增备份。
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("migrate")

_VERSION_DEFAULTS = {
    "effective_from_chapter": 1,
    "deprecated_at_chapter": None,
    "version": 1,
}


@dataclass
class MigrationStats:
    projects_scanned: int = 0
    projects_migrated: int = 0
    projects_already_v2: int = 0
    characters_updated: int = 0
    outlines_updated: int = 0
    world_updated: int = 0
    errors: list[str] = field(default_factory=list)


def _needs_version_fields(entity: dict[str, Any]) -> bool:
    """True 当 entity 缺少任一 v2 版本字段。"""
    return any(k not in entity for k in _VERSION_DEFAULTS)


def _apply_defaults(entity: dict[str, Any]) -> bool:
    """为 entity 补齐缺失的版本字段；返回是否实际修改。"""
    changed = False
    for k, default in _VERSION_DEFAULTS.items():
        if k not in entity:
            entity[k] = default
            changed = True
    return changed


def migrate_novel(
    novel_path: Path,
    dry_run: bool = False,
    stats: MigrationStats | None = None,
) -> bool:
    """迁移单个 novel.json；返回 True 表示确实发生了修改。

    失败时将错误记录到 stats.errors 并返回 False；不抛异常。
    """
    stats = stats or MigrationStats()
    try:
        with open(novel_path, encoding="utf-8") as f:
            novel = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        stats.errors.append(f"{novel_path}: 读取失败 {exc}")
        return False

    modified = False

    for char in novel.get("characters", []) or []:
        if isinstance(char, dict) and _apply_defaults(char):
            stats.characters_updated += 1
            modified = True

    outline = novel.get("outline", {})
    if isinstance(outline, dict):
        for ch in outline.get("chapters", []) or []:
            if isinstance(ch, dict) and _apply_defaults(ch):
                stats.outlines_updated += 1
                modified = True

    ws = novel.get("world_setting")
    if isinstance(ws, dict) and _needs_version_fields(ws):
        if _apply_defaults(ws):
            stats.world_updated += 1
            modified = True

    if not modified:
        return False

    if dry_run:
        return True

    # 备份 v1 原始文件（仅首次；若已存在同名备份则跳过）
    backup_path = novel_path.with_name(novel_path.stem + ".v1.json")
    if not backup_path.exists():
        shutil.copy2(novel_path, backup_path)

    # 写回
    with open(novel_path, "w", encoding="utf-8") as f:
        json.dump(novel, f, ensure_ascii=False, indent=2)

    return True


def migrate_workspace(
    workspace: str | Path, dry_run: bool = False
) -> MigrationStats:
    """遍历 workspace/novels/*/novel.json 并迁移每一个。"""
    ws = Path(workspace)
    novels_root = ws / "novels"
    stats = MigrationStats()

    if not novels_root.is_dir():
        stats.errors.append(f"novels 目录不存在: {novels_root}")
        return stats

    for novel_dir in sorted(novels_root.iterdir()):
        if not novel_dir.is_dir():
            continue
        novel_json = novel_dir / "novel.json"
        if not novel_json.exists():
            continue
        stats.projects_scanned += 1

        changed = migrate_novel(novel_json, dry_run=dry_run, stats=stats)
        if changed:
            stats.projects_migrated += 1
        else:
            # 非错误：数据已是 v2
            if novel_dir.name not in {
                e.split(":", 1)[0] for e in stats.errors
            }:
                stats.projects_already_v2 += 1

    return stats


def _print_stats(stats: MigrationStats, dry_run: bool) -> None:
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"{prefix}扫描项目: {stats.projects_scanned}")
    print(f"{prefix}已迁移:   {stats.projects_migrated}")
    print(f"{prefix}已是 v2:  {stats.projects_already_v2}")
    print(f"{prefix}角色字段补齐: {stats.characters_updated}")
    print(f"{prefix}章节大纲字段补齐: {stats.outlines_updated}")
    print(f"{prefix}世界观字段补齐: {stats.world_updated}")
    if stats.errors:
        print(f"{prefix}错误: {len(stats.errors)}")
        for e in stats.errors:
            print(f"  - {e}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        default="workspace",
        help="workspace 根目录（包含 novels/ 子目录），默认 workspace",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只检测不写盘",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stats = migrate_workspace(args.workspace, dry_run=args.dry_run)
    _print_stats(stats, args.dry_run)
    return 0 if not stats.errors else 1


if __name__ == "__main__":
    sys.exit(main())
