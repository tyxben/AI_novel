"""小说项目 v2 → v3 迁移脚本（Phase 1-B 数据模型升级）。

v3 引入：
  - ``ChapterOutline.chapter_type``      默认 "buildup"（setup/buildup/climax/resolution/interlude）
  - ``ChapterOutline.target_words``      默认复制自 ``estimated_words``（缺失则 None）
  - ``Volume.volume_goal``               默认 ""
  - ``Volume.volume_outline``            默认复制自 ``chapters`` 冗余备份
  - ``Volume.settlement``                默认 None
  - ``Volume.chapter_type_dist``         默认 {}

运行：
    python scripts/migrate_novel_v2_to_v3.py             # 默认 workspace
    python scripts/migrate_novel_v2_to_v3.py --workspace ./my_ws
    python scripts/migrate_novel_v2_to_v3.py --dry-run   # 不写盘

幂等：多次运行结果相同；已是 v3 则原样保留（不新增备份）。
首次迁移时会落 ``novel.v2.json`` 备份（若不存在）。
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

log = logging.getLogger("migrate_v3")

_CHAPTER_TYPE_DEFAULT = "buildup"

# 对应 ChapterOutline 新增的字段名
_OUTLINE_NEW_FIELDS = ("chapter_type", "target_words")
# 对应 Volume 新增的字段名（default_factory 的默认值单独处理）
_VOLUME_NEW_FIELDS = (
    "volume_goal",
    "volume_outline",
    "settlement",
    "chapter_type_dist",
)


@dataclass
class MigrationStats:
    projects_scanned: int = 0
    projects_migrated: int = 0
    projects_already_v3: int = 0
    chapter_outlines_updated: int = 0
    volumes_updated: int = 0
    errors: list[str] = field(default_factory=list)


def _apply_chapter_outline_defaults(ch: dict[str, Any]) -> bool:
    """为 outline.chapters[i] 补齐 v3 字段；返回是否实际修改。"""
    changed = False
    if "chapter_type" not in ch:
        ch["chapter_type"] = _CHAPTER_TYPE_DEFAULT
        changed = True
    if "target_words" not in ch:
        # 首次迁移：优先沿用 estimated_words，避免打断已有字数控制
        est = ch.get("estimated_words")
        if isinstance(est, int) and 500 <= est <= 10000:
            ch["target_words"] = est
        else:
            ch["target_words"] = None
        changed = True
    return changed


def _apply_volume_defaults(vol: dict[str, Any]) -> bool:
    """为 novel.volumes[i] 补齐 v3 字段；返回是否实际修改。"""
    changed = False
    if "volume_goal" not in vol:
        vol["volume_goal"] = ""
        changed = True
    if "volume_outline" not in vol:
        # 冗余于 chapters（兼容读路径）
        chapters = vol.get("chapters")
        vol["volume_outline"] = list(chapters) if isinstance(chapters, list) else []
        changed = True
    if "settlement" not in vol:
        vol["settlement"] = None
        changed = True
    if "chapter_type_dist" not in vol:
        vol["chapter_type_dist"] = {}
        changed = True
    return changed


def _needs_v3_migration(novel: dict[str, Any]) -> bool:
    """True 表示 novel 中至少有一处字段缺失，需要迁移。"""
    outline = novel.get("outline")
    if isinstance(outline, dict):
        for ch in outline.get("chapters", []) or []:
            if isinstance(ch, dict) and any(
                k not in ch for k in _OUTLINE_NEW_FIELDS
            ):
                return True
    for vol in novel.get("volumes", []) or []:
        if isinstance(vol, dict) and any(
            k not in vol for k in _VOLUME_NEW_FIELDS
        ):
            return True
    return False


def migrate_novel(
    novel_path: Path,
    dry_run: bool = False,
    stats: MigrationStats | None = None,
) -> bool:
    """迁移单个 novel.json；返回 True 表示实际修改了文件（或 dry-run 下会修改）。"""
    stats = stats or MigrationStats()
    try:
        with open(novel_path, encoding="utf-8") as f:
            novel = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        stats.errors.append(f"{novel_path}: 读取失败 {exc}")
        return False

    modified = False

    outline = novel.get("outline")
    if isinstance(outline, dict):
        for ch in outline.get("chapters", []) or []:
            if isinstance(ch, dict) and _apply_chapter_outline_defaults(ch):
                stats.chapter_outlines_updated += 1
                modified = True

    for vol in novel.get("volumes", []) or []:
        if isinstance(vol, dict) and _apply_volume_defaults(vol):
            stats.volumes_updated += 1
            modified = True

    if not modified:
        return False

    if dry_run:
        return True

    # 备份 v2 原始文件（仅首次）
    backup_path = novel_path.with_name(novel_path.stem + ".v2.json")
    if not backup_path.exists():
        shutil.copy2(novel_path, backup_path)

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
            stats.projects_already_v3 += 1

    return stats


def _print_stats(stats: MigrationStats, dry_run: bool) -> None:
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"{prefix}扫描项目: {stats.projects_scanned}")
    print(f"{prefix}已迁移:   {stats.projects_migrated}")
    print(f"{prefix}已是 v3:  {stats.projects_already_v3}")
    print(f"{prefix}章节大纲字段补齐: {stats.chapter_outlines_updated}")
    print(f"{prefix}卷字段补齐:       {stats.volumes_updated}")
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
