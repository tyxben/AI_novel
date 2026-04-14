"""变更历史管理 -- 记录和查询小说编辑的所有变更。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.novel.models.changelog import ChangeLogEntry

log = logging.getLogger("novel")


class ChangeLogManager:
    """管理变更历史，持久化到 JSON 文件。

    存储位置: {workspace}/changelog.json
    格式: JSON 数组，每个元素是一条 ChangeLogEntry 的序列化。
    """

    def __init__(self, workspace: str) -> None:
        """初始化变更历史管理器。

        Args:
            workspace: 小说项目的根目录路径（如 workspace/novels/novel_xxx）。
        """
        self._workspace = Path(workspace)
        self._changelog_path = self._workspace / "changelog.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        novel_id: str,
        change_type: str,
        entity_type: str,
        description: str,
        old_value: Optional[dict[str, Any]] = None,
        new_value: Optional[dict[str, Any]] = None,
        entity_id: Optional[str] = None,
        effective_from_chapter: int = 1,
        author: str = "ai",
    ) -> ChangeLogEntry:
        """记录一条变更。

        Args:
            novel_id: 小说 ID。
            change_type: 变更类型，如 "add_character"、"modify_outline" 等。
            entity_type: 实体类型，如 "character"、"outline"、"world"。
            description: 变更描述。
            old_value: 变更前的快照。
            new_value: 变更后的快照。
            entity_id: 实体 ID（可选）。
            effective_from_chapter: 生效起始章节，默认 1。
            author: 操作者，"ai" 或 "user"。

        Returns:
            创建的 ChangeLogEntry。
        """
        entry = ChangeLogEntry(
            novel_id=novel_id,
            change_type=change_type,
            entity_type=entity_type,
            description=description,
            old_value=old_value,
            new_value=new_value,
            entity_id=entity_id,
            effective_from_chapter=effective_from_chapter,
            author=author,
        )

        entries = self._load_all()
        entries.append(entry)
        self._save_all(entries)

        return entry

    def list_changes(
        self,
        novel_id: str,
        limit: int = 50,
        change_type: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> list[ChangeLogEntry]:
        """查询变更历史，支持过滤。

        返回按时间倒序排列的变更列表。

        Args:
            novel_id: 小说 ID。
            limit: 返回的最大条数，默认 50。
            change_type: 按变更类型过滤（可选）。
            entity_type: 按实体类型过滤（可选）。

        Returns:
            满足条件的 ChangeLogEntry 列表（倒序）。
        """
        entries = self._load_all()

        # 过滤
        filtered = [e for e in entries if e.novel_id == novel_id]
        if change_type is not None:
            filtered = [e for e in filtered if e.change_type == change_type]
        if entity_type is not None:
            filtered = [e for e in filtered if e.entity_type == entity_type]

        # 按时间倒序
        filtered.sort(key=lambda e: e.timestamp, reverse=True)

        return filtered[:limit]

    def get(self, change_id: str) -> Optional[ChangeLogEntry]:
        """获取单条变更记录。

        Args:
            change_id: 变更 ID。

        Returns:
            ChangeLogEntry 或 None（不存在时）。
        """
        entries = self._load_all()
        for entry in entries:
            if entry.change_id == change_id:
                return entry
        return None

    def get_changes_since(
        self, novel_id: str, since: datetime
    ) -> list[ChangeLogEntry]:
        """获取某时间点后的所有变更。

        Args:
            novel_id: 小说 ID。
            since: 起始时间（不含该时间点本身）。

        Returns:
            满足条件的 ChangeLogEntry 列表（按时间倒序）。
        """
        entries = self._load_all()
        filtered = [
            e for e in entries
            if e.novel_id == novel_id and e.timestamp > since
        ]
        filtered.sort(key=lambda e: e.timestamp, reverse=True)
        return filtered

    def get_changes_for_entity(
        self, novel_id: str, entity_id: str
    ) -> list[ChangeLogEntry]:
        """获取某实体的所有变更历史。

        Args:
            novel_id: 小说 ID。
            entity_id: 实体 ID。

        Returns:
            满足条件的 ChangeLogEntry 列表（按时间倒序）。
        """
        entries = self._load_all()
        filtered = [
            e for e in entries
            if e.novel_id == novel_id and e.entity_id == entity_id
        ]
        filtered.sort(key=lambda e: e.timestamp, reverse=True)
        return filtered

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_all(self) -> list[ChangeLogEntry]:
        """从 JSON 文件加载所有变更记录。"""
        if not self._changelog_path.exists():
            return []

        try:
            with open(self._changelog_path, encoding="utf-8") as f:
                raw_list = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("读取 changelog.json 失败: %s", exc)
            return []

        entries: list[ChangeLogEntry] = []
        for raw in raw_list:
            try:
                entries.append(ChangeLogEntry.model_validate(raw))
            except Exception as exc:  # noqa: BLE001
                log.warning("跳过无效变更记录: %s", exc)
        return entries

    def _save_all(self, entries: list[ChangeLogEntry]) -> None:
        """将所有变更记录保存到 JSON 文件。"""
        self._workspace.mkdir(parents=True, exist_ok=True)
        data = [
            json.loads(e.model_dump_json())
            for e in entries
        ]
        with open(self._changelog_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
