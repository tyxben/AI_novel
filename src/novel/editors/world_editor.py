"""世界观编辑器 — 更新世界设定（合并式）"""

from __future__ import annotations

import copy

from src.novel.editors.base import BaseEditor
from src.novel.models.world import WorldSetting


class WorldSettingEditor(BaseEditor):
    """世界观设定编辑器。"""

    def apply(
        self,
        novel_data: dict,
        change: dict,
    ) -> tuple[dict | None, dict]:
        change_type = change.get("change_type")

        if change_type == "update":
            return self._update_world_setting(novel_data, change)
        else:
            raise ValueError(
                f"WorldSettingEditor 不支持的 change_type: {change_type}"
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _update_world_setting(
        self,
        novel_data: dict,
        change: dict,
    ) -> tuple[dict, dict]:
        """合并更新 world_setting 字段。

        支持更新 rules, terms, power_system, era, location 等子字段。
        对于 dict 类型子字段（如 terms）做递归合并，
        对于 list 类型子字段（如 rules）做替换。
        """
        ws = novel_data.get("world_setting")
        if ws is None:
            raise ValueError("novel_data 中缺少 world_setting")

        old_ws = copy.deepcopy(ws)

        data = change.get("data", {})
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(ws.get(key), dict):
                # 递归合并 dict（如 terms）
                ws[key].update(value)
            else:
                ws[key] = value

        # 更新版本字段
        self._add_version_fields(ws, change)

        # Pydantic 验证
        WorldSetting.model_validate(ws)

        return old_ws, ws
