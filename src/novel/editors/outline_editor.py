"""大纲编辑器 — 章节大纲的增/改操作"""

from __future__ import annotations

import copy

from src.novel.editors.base import BaseEditor
from src.novel.models.novel import ChapterOutline


class OutlineEditor(BaseEditor):
    """大纲实体编辑器。"""

    def apply(
        self,
        novel_data: dict,
        change: dict,
    ) -> tuple[dict | None, dict]:
        change_type = change.get("change_type")

        if change_type == "add":
            return self._add_chapter_outline(novel_data, change)
        elif change_type == "update":
            return self._edit_chapter_outline(novel_data, change)
        else:
            raise ValueError(
                f"OutlineEditor 不支持的 change_type: {change_type}"
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _edit_chapter_outline(
        self,
        novel_data: dict,
        change: dict,
    ) -> tuple[dict, dict]:
        """修改已有章节大纲。"""
        data = change.get("data", {})
        ch_num = data.get("chapter_number")
        if ch_num is None:
            raise ValueError("update 操作的 data 必须包含 chapter_number")

        outline = novel_data.get("outline", {})
        chapters = outline.get("chapters", [])

        for i, ch in enumerate(chapters):
            if ch.get("chapter_number") == ch_num:
                old_ch = copy.deepcopy(ch)

                # 合并更新
                for key, value in data.items():
                    ch[key] = value

                self._add_version_fields(ch, change)

                # Pydantic 验证
                ChapterOutline.model_validate(ch)

                return old_ch, ch

        raise ValueError(f"章节大纲不存在: chapter_number={ch_num}")

    def _add_chapter_outline(
        self,
        novel_data: dict,
        change: dict,
    ) -> tuple[None, dict]:
        """在 outline.chapters 中插入新章节大纲。"""
        data = dict(change.get("data", {}))

        # 设置版本字段
        self._add_version_fields(data, change)

        # Pydantic 验证
        ChapterOutline.model_validate(data)

        # 插入到 outline.chapters
        outline = novel_data.setdefault("outline", {})
        chapters = outline.setdefault("chapters", [])
        chapters.append(data)

        # 按 chapter_number 排序
        chapters.sort(key=lambda c: c.get("chapter_number", 0))

        return None, data
