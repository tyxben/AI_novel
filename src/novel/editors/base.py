"""编辑器抽象基类"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone


class BaseEditor(ABC):
    """编辑器基类 — 定义通用接口和版本管理辅助方法。"""

    @abstractmethod
    def apply(
        self,
        novel_data: dict,
        change: dict,
    ) -> tuple[dict | None, dict]:
        """应用变更到 novel_data（原地修改）。

        Args:
            novel_data: 当前小说数据（直接修改）
            change: 变更描述 dict，包含：
                - change_type: "add" | "update" | "delete"
                - entity_type: "character" | "outline" | "world_setting"
                - data: 变更数据
                - entity_id: 实体ID（update/delete 时需要）
                - effective_from_chapter: 生效章节

        Returns:
            (old_value, new_value) 元组，old_value 为 None 表示新增
        """
        ...

    # ------------------------------------------------------------------
    # 版本管理辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _add_version_fields(entity: dict, change: dict) -> None:
        """为实体添加/更新版本字段。"""
        entity["effective_from_chapter"] = change.get("effective_from_chapter")
        entity["version"] = entity.get("version", 0) + 1
        entity["updated_at"] = datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _deprecate_old_version(entity: dict, effective_from: int) -> None:
        """标记旧版本为过期。"""
        entity["deprecated_at_chapter"] = effective_from
