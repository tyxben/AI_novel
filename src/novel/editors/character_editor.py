"""角色编辑器 — 增删改角色，维护关系网引用"""

from __future__ import annotations

import copy
from uuid import uuid4

from src.novel.editors.base import BaseEditor
from src.novel.models.character import CharacterProfile


class CharacterEditor(BaseEditor):
    """角色实体编辑器。"""

    def apply(
        self,
        novel_data: dict,
        change: dict,
    ) -> tuple[dict | None, dict]:
        change_type = change.get("change_type")

        if change_type == "add":
            return self._add_character(novel_data, change)
        elif change_type == "update":
            return self._update_character(novel_data, change)
        elif change_type == "delete":
            return self._delete_character(novel_data, change)
        else:
            raise ValueError(f"不支持的 change_type: {change_type}")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _add_character(
        self,
        novel_data: dict,
        change: dict,
    ) -> tuple[None, dict]:
        """添加角色。"""
        new_char = dict(change.get("data", {}))

        # 1. 自动生成 UUID
        if "character_id" not in new_char:
            new_char["character_id"] = str(uuid4())

        # 2. 设置版本字段
        self._add_version_fields(new_char, change)

        # 3. Pydantic 验证 + 规范化（确保类型正确）
        validated = CharacterProfile.model_validate(new_char)
        new_char = validated.model_dump()

        # 4. 追加到 characters 列表
        novel_data.setdefault("characters", []).append(new_char)

        return None, new_char

    def _update_character(
        self,
        novel_data: dict,
        change: dict,
    ) -> tuple[dict, dict]:
        """更新角色（原地合并）。"""
        char_id = change.get("entity_id")
        if not char_id:
            raise ValueError("update 操作必须提供 entity_id")

        chars = novel_data.get("characters", [])

        for i, c in enumerate(chars):
            if c.get("character_id") == char_id:
                old_char = copy.deepcopy(c)

                # 合并更新：仅覆盖 data 中提供的字段
                update_data = change.get("data", {})
                for key, value in update_data.items():
                    c[key] = value

                # 更新版本字段
                self._add_version_fields(c, change)

                # Pydantic 验证更新后的数据
                CharacterProfile.model_validate(c)

                return old_char, c

        raise ValueError(f"角色不存在: {char_id}")

    def _delete_character(
        self,
        novel_data: dict,
        change: dict,
    ) -> tuple[dict, dict]:
        """软删除角色：设置 status + deprecated_at_chapter。"""
        char_id = change.get("entity_id")
        if not char_id:
            raise ValueError("delete 操作必须提供 entity_id")

        chars = novel_data.get("characters", [])

        for c in chars:
            if c.get("character_id") == char_id:
                old_char = copy.deepcopy(c)

                # 软删除（可通过 change.data.status 自定义，默认 retired）
                c["status"] = change.get("data", {}).get("status", "retired")
                effective_from = change.get("effective_from_chapter")
                if effective_from is not None:
                    self._deprecate_old_version(c, effective_from)
                self._add_version_fields(c, change)

                return old_char, c

        raise ValueError(f"角色不存在: {char_id}")
