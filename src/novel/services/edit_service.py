"""核心编辑服务 — 统一编辑入口。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.llm.llm_client import LLMClient, create_llm_client
from src.novel.editors.character_editor import CharacterEditor
from src.novel.editors.outline_editor import OutlineEditor
from src.novel.editors.world_editor import WorldSettingEditor
from src.novel.services.changelog_manager import ChangeLogManager
from src.novel.services.intent_parser import IntentParser
from src.novel.storage.file_manager import FileManager

log = logging.getLogger("novel")


@dataclass
class EditResult:
    """编辑操作结果。"""

    change_id: str
    status: str  # "success" | "failed" | "preview"
    change_type: str  # "add" | "update" | "delete"
    entity_type: str  # "character" | "outline" | "world_setting"
    entity_id: str | None = None
    old_value: dict | None = None
    new_value: dict | None = None
    effective_from_chapter: int | None = None
    reasoning: str = ""
    error: str | None = None


class NovelEditService:
    """统一编辑入口，协调意图解析、编辑器、存储。"""

    def __init__(
        self,
        workspace: str = "workspace",
        llm_client: LLMClient | None = None,
        changelog_manager: ChangeLogManager | None = None,
    ):
        self.file_manager = FileManager(workspace)
        self._llm_client = llm_client
        self._changelog_manager = changelog_manager
        self._editors: dict[str, Any] = {
            "character": CharacterEditor(),
            "outline": OutlineEditor(),
            "world_setting": WorldSettingEditor(),
        }

    def edit(
        self,
        project_path: str,
        instruction: str | None = None,
        structured_change: dict | None = None,
        effective_from_chapter: int | None = None,
        dry_run: bool = False,
    ) -> EditResult:
        """编辑小说设定。

        支持两种输入：
        1. instruction (自然语言) -- 通过 IntentParser 解析
        2. structured_change (结构化 dict) -- 直接使用

        流程：
        1. 加载 novel.json
        2. 如果是自然语言，调用 IntentParser 解析
        3. 推断 effective_from_chapter（如果未指定）
        4. 如果 dry_run，返回预览结果
        5. 备份 novel.json
        6. 调用对应编辑器 apply()
        7. 保存 novel.json
        8. 记录变更日志
        9. 返回 EditResult
        """
        change_id = str(uuid4())
        change: dict = {}

        try:
            # 1. 提取 novel_id
            novel_id = self._extract_novel_id(project_path)

            # 2. 加载 novel.json
            novel_data = self.file_manager.load_novel(novel_id)
            if novel_data is None:
                return EditResult(
                    change_id=change_id,
                    status="failed",
                    change_type="",
                    entity_type="",
                    error=f"小说项目不存在: {novel_id}",
                )

            # 3. 获取结构化变更
            if instruction is not None:
                change = self._parse_instruction(
                    instruction, novel_data, effective_from_chapter
                )
            elif structured_change is not None:
                change = dict(structured_change)
            else:
                return EditResult(
                    change_id=change_id,
                    status="failed",
                    change_type="",
                    entity_type="",
                    error="必须提供 instruction 或 structured_change",
                )

            # 4. 推断 effective_from_chapter
            effective_from = self._resolve_effective_from(
                change, effective_from_chapter, novel_data
            )
            change["effective_from_chapter"] = effective_from

            # 5. 获取编辑器
            entity_type = change.get("entity_type", "")
            change_type = change.get("change_type", "")
            entity_id = change.get("entity_id")
            reasoning = change.get("reasoning", "")

            editor = self._editors.get(entity_type)
            if editor is None:
                return EditResult(
                    change_id=change_id,
                    status="failed",
                    change_type=change_type,
                    entity_type=entity_type,
                    error=f"不支持的 entity_type: {entity_type}",
                )

            # 6. dry_run 模式：预览但不修改
            if dry_run:
                return EditResult(
                    change_id=change_id,
                    status="preview",
                    change_type=change_type,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    effective_from_chapter=effective_from,
                    reasoning=reasoning,
                )

            # 7. 备份
            self.file_manager.save_backup(novel_id)

            # 8. 调用编辑器
            old_value, new_value = editor.apply(novel_data, change)

            # 9. 保存 novel.json
            self.file_manager.save_novel(novel_id, novel_data)

            # 10. 提取 entity_id（add 操作后可能从 new_value 获取）
            if entity_id is None and new_value is not None:
                entity_id = new_value.get("character_id")

            # 11. 记录变更日志
            entry = {
                "change_id": change_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "change_type": change_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "instruction": instruction,
                "effective_from_chapter": effective_from,
                "old_value": old_value,
                "new_value": new_value,
            }
            self.file_manager.save_change_log(novel_id, entry)

            # 12. 记录到 ChangeLogManager（如果已注入）
            if self._changelog_manager is not None:
                try:
                    desc = instruction or f"{change_type} {entity_type}"
                    self._changelog_manager.record(
                        novel_id=novel_id,
                        change_type=f"{change_type}_{entity_type}",
                        entity_type=entity_type,
                        description=desc,
                        old_value=old_value,
                        new_value=new_value,
                        entity_id=entity_id,
                        effective_from_chapter=effective_from,
                        author="user" if instruction else "ai",
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("ChangeLogManager 记录失败: %s", exc)

            return EditResult(
                change_id=change_id,
                status="success",
                change_type=change_type,
                entity_type=entity_type,
                entity_id=entity_id,
                old_value=old_value,
                new_value=new_value,
                effective_from_chapter=effective_from,
                reasoning=reasoning,
            )

        except Exception as exc:
            log.exception("编辑操作失败: %s", exc)
            return EditResult(
                change_id=change_id,
                status="failed",
                change_type=change.get("change_type", ""),
                entity_type=change.get("entity_type", ""),
                error=str(exc),
            )

    def get_history(
        self,
        project_path: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """查询变更历史。

        Args:
            project_path: 项目路径
            limit: 返回的最大条数

        Returns:
            变更日志列表（按时间倒序）
        """
        novel_id = self._extract_novel_id(project_path)
        return self.file_manager.list_change_logs(novel_id, limit)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_novel_id(project_path: str) -> str:
        """从项目路径提取 novel_id（最后一个目录名）。

        Args:
            project_path: 如 "workspace/novels/novel_xxx" 或绝对路径

        Returns:
            novel_id 字符串

        Raises:
            ValueError: 路径不合法（含路径穿越等）
        """
        name = Path(project_path).name
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            raise ValueError(f"非法项目路径: {project_path}")
        return name

    def _parse_instruction(
        self,
        instruction: str,
        novel_data: dict,
        effective_from_chapter: int | None,
    ) -> dict:
        """调用 IntentParser 解析自然语言指令。"""
        if self._llm_client:
            llm = self._llm_client
        else:
            llm_config = novel_data.get("config", {}).get("llm", {})
            llm = create_llm_client(llm_config)
        parser = IntentParser(llm)

        novel_context = self._build_novel_context(novel_data)
        return parser.parse(instruction, novel_context, effective_from_chapter)

    @staticmethod
    def _build_novel_context(novel_data: dict) -> dict:
        """从 novel_data 构建 IntentParser 需要的上下文。"""
        return {
            "genre": novel_data.get("genre", ""),
            "characters": novel_data.get("characters", []),
            "current_chapter": novel_data.get("current_chapter", 0),
        }

    @staticmethod
    def _resolve_effective_from(
        change: dict,
        explicit_value: int | None,
        novel_data: dict,
    ) -> int:
        """推断 effective_from_chapter。

        优先级：
        1. 调用方显式传入的 effective_from_chapter
        2. change 中 IntentParser 已解析出的值
        3. 默认为 current_chapter + 1（下一章生效）
        """
        if explicit_value is not None:
            return explicit_value

        from_change = change.get("effective_from_chapter")
        if from_change is not None:
            return from_change

        return novel_data.get("current_chapter", 0) + 1
