"""核心编辑服务 — 统一编辑入口。"""

from __future__ import annotations

import copy
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
from src.novel.services.impact_analyzer import (
    ChangeRequest,
    ImpactAnalyzer,
    ImpactResult,
)
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
    impact_report: dict | None = None


class NovelEditService:
    """统一编辑入口，协调意图解析、编辑器、存储。"""

    def __init__(
        self,
        workspace: str = "workspace",
        llm_client: LLMClient | None = None,
        changelog_manager: ChangeLogManager | None = None,
        impact_analyzer: ImpactAnalyzer | None = None,
    ):
        self.file_manager = FileManager(workspace)
        self._llm_client = llm_client
        self._changelog_manager = changelog_manager
        self._impact_analyzer = impact_analyzer or ImpactAnalyzer()
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

            # 5b. 影响分析（非阻塞，失败仅记录 warning）
            impact_report = self._run_impact_analysis(novel_data, change)

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
                    impact_report=impact_report,
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
                impact_report=impact_report,
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

    def batch_edit(
        self,
        project_path: str,
        changes: list[dict],
        dry_run: bool = False,
        stop_on_failure: bool = False,
    ) -> list[EditResult]:
        """批量应用多条 structured_change。

        每条 change 独立调用 ``edit()``，失败的条目不影响其他条目（除非
        ``stop_on_failure=True``）。每次成功修改都会产生独立的备份 +
        独立的 changelog 条目，保证回滚粒度。

        Args:
            project_path: 项目路径。
            changes: 结构化变更列表，每项格式同 ``edit(structured_change=...)``。
            dry_run: 若为 True，所有条目走预览路径，不写盘。
            stop_on_failure: 若为 True，遇到首个 failed 立即停止后续条目。

        Returns:
            长度等于 len(changes) 的 EditResult 列表；若提前停止，剩余位
            会被填充 status="skipped" 的占位 EditResult。
        """
        results: list[EditResult] = []
        stopped = False

        for i, change in enumerate(changes):
            if stopped:
                results.append(
                    EditResult(
                        change_id=str(uuid4()),
                        status="skipped",
                        change_type=change.get("change_type", ""),
                        entity_type=change.get("entity_type", ""),
                        entity_id=change.get("entity_id"),
                        error="前序变更失败已中止批处理",
                    )
                )
                continue

            if not isinstance(change, dict):
                results.append(
                    EditResult(
                        change_id=str(uuid4()),
                        status="failed",
                        change_type="",
                        entity_type="",
                        error=f"changes[{i}] 不是 dict",
                    )
                )
                if stop_on_failure:
                    stopped = True
                continue

            result = self.edit(
                project_path=project_path,
                structured_change=change,
                effective_from_chapter=change.get("effective_from_chapter"),
                dry_run=dry_run,
            )
            results.append(result)
            if stop_on_failure and result.status == "failed":
                stopped = True

        return results

    def rollback(
        self,
        project_path: str,
        change_id: str,
        force: bool = False,
    ) -> EditResult:
        """回滚指定变更，恢复实体到变更前状态。

        支持的原变更类型：
        - (add, character)      -> 从 characters 列表移除
        - (update, character)   -> 替换为 old_value（完整快照）
        - (delete, character)   -> 替换为 old_value（恢复软删除前）
        - (add, outline)        -> 从 outline.chapters 移除该 chapter_number
        - (update, outline)     -> 替换为 old_value（完整章节快照）
        - (update, world_setting) -> 替换 world_setting 为 old_value

        依赖检查：若存在后续针对同实体的变更且 ``force=False``，拒绝回滚。

        回滚本身作为一条新变更（change_type="rollback"）写入日志，
        其 ``reverted_change_id`` 字段指向被回滚的 change_id。
        """
        rollback_change_id = str(uuid4())
        try:
            novel_id = self._extract_novel_id(project_path)
            novel_data = self.file_manager.load_novel(novel_id)
            if novel_data is None:
                return EditResult(
                    change_id=rollback_change_id,
                    status="failed",
                    change_type="rollback",
                    entity_type="",
                    error=f"小说项目不存在: {novel_id}",
                )

            target = self._find_change_log(novel_id, change_id)
            if target is None:
                return EditResult(
                    change_id=rollback_change_id,
                    status="failed",
                    change_type="rollback",
                    entity_type="",
                    error=f"变更不存在: {change_id}",
                )

            if target.get("change_type") == "rollback":
                return EditResult(
                    change_id=rollback_change_id,
                    status="failed",
                    change_type="rollback",
                    entity_type=target.get("entity_type", ""),
                    error="不支持回滚 rollback 变更本身",
                )

            # 依赖检查
            dependents = self._find_dependent_changes(novel_id, target)
            if dependents and not force:
                dep_ids = [d.get("change_id", "?") for d in dependents]
                return EditResult(
                    change_id=rollback_change_id,
                    status="failed",
                    change_type="rollback",
                    entity_type=target.get("entity_type", ""),
                    entity_id=target.get("entity_id"),
                    error=(
                        f"存在 {len(dependents)} 个后续变更依赖此实体: "
                        f"{', '.join(dep_ids[:5])}；请先回滚它们或使用 force=True"
                    ),
                )

            # 备份
            self.file_manager.save_backup(novel_id)

            # 反向应用
            self._apply_reverse(novel_data, target)

            # 保存
            self.file_manager.save_novel(novel_id, novel_data)

            old_val = target.get("old_value")
            new_val = target.get("new_value")

            entry = {
                "change_id": rollback_change_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "change_type": "rollback",
                "entity_type": target.get("entity_type", ""),
                "entity_id": target.get("entity_id"),
                "reverted_change_id": change_id,
                "instruction": None,
                "effective_from_chapter": target.get("effective_from_chapter"),
                # 回滚前的状态即目标变更的新值；回滚后即旧值
                "old_value": new_val,
                "new_value": old_val,
            }
            self.file_manager.save_change_log(novel_id, entry)

            if self._changelog_manager is not None:
                try:
                    self._changelog_manager.record(
                        novel_id=novel_id,
                        change_type="rollback",
                        entity_type=target.get("entity_type", ""),
                        description=f"回滚变更 {change_id}",
                        old_value=new_val,
                        new_value=old_val,
                        entity_id=target.get("entity_id"),
                        effective_from_chapter=(
                            target.get("effective_from_chapter") or 1
                        ),
                        author="user",
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("ChangeLogManager 记录回滚失败: %s", exc)

            return EditResult(
                change_id=rollback_change_id,
                status="success",
                change_type="rollback",
                entity_type=target.get("entity_type", ""),
                entity_id=target.get("entity_id"),
                old_value=new_val,
                new_value=old_val,
                effective_from_chapter=target.get("effective_from_chapter"),
                reasoning=f"回滚变更 {change_id}",
            )

        except Exception as exc:
            log.exception("回滚失败: %s", exc)
            return EditResult(
                change_id=rollback_change_id,
                status="failed",
                change_type="rollback",
                entity_type="",
                error=str(exc),
            )

    def get_history(
        self,
        project_path: str,
        limit: int = 20,
        change_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """查询变更历史。

        Args:
            project_path: 项目路径
            limit: 返回的最大条数
            change_type: 按变更类型过滤（精确或后缀匹配），在截断前应用

        Returns:
            变更日志列表（按时间倒序）
        """
        novel_id = self._extract_novel_id(project_path)
        return self.file_manager.list_change_logs(
            novel_id, limit, change_type=change_type
        )

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

    # ------------------------------------------------------------------
    # Impact analysis integration
    # ------------------------------------------------------------------

    # Map editor-layer (change_type, entity_type) -> ImpactAnalyzer.ChangeRequest.change_type
    _IMPACT_CHANGE_TYPE_MAP: dict[tuple[str, str], str] = {
        ("add", "character"): "add_character",
        ("update", "character"): "modify_character",
        ("delete", "character"): "delete_character",
        ("add", "outline"): "modify_outline",
        ("update", "outline"): "modify_outline",
        ("delete", "outline"): "modify_outline",
        ("add", "world_setting"): "modify_world",
        ("update", "world_setting"): "modify_world",
        ("delete", "world_setting"): "modify_world",
    }

    # Map editor entity_type -> ImpactAnalyzer entity_type
    _IMPACT_ENTITY_TYPE_MAP: dict[str, str] = {
        "character": "character",
        "outline": "outline",
        "world_setting": "world",
    }

    def _run_impact_analysis(
        self,
        novel_data: dict,
        change: dict,
    ) -> dict | None:
        """调用 ImpactAnalyzer，返回 dict 序列化结果；失败仅 warning 不阻塞。"""
        try:
            request = self._build_change_request(change)
            if request is None:
                return None
            result: ImpactResult = self._impact_analyzer.analyze(
                novel_data, request
            )
            return result.model_dump()
        except Exception as exc:  # noqa: BLE001
            log.warning("ImpactAnalyzer 分析失败: %s", exc)
            return None

    def _build_change_request(self, change: dict) -> ChangeRequest | None:
        """把内部 change dict 转换为 ImpactAnalyzer.ChangeRequest。

        不支持的 change_type/entity_type 返回 None（由调用方跳过）。
        """
        entity_type = change.get("entity_type", "")
        change_type = change.get("change_type", "")

        mapped_change_type = self._IMPACT_CHANGE_TYPE_MAP.get(
            (change_type, entity_type)
        )
        mapped_entity_type = self._IMPACT_ENTITY_TYPE_MAP.get(entity_type)
        if mapped_change_type is None or mapped_entity_type is None:
            return None

        effective_from = change.get("effective_from_chapter", 1) or 1
        effective_from = max(1, int(effective_from))

        details = dict(change.get("data") or {})

        return ChangeRequest(
            change_type=mapped_change_type,
            entity_type=mapped_entity_type,
            entity_id=change.get("entity_id"),
            effective_from_chapter=effective_from,
            details=details,
        )

    # ------------------------------------------------------------------
    # Rollback helpers
    # ------------------------------------------------------------------

    def _find_change_log(
        self, novel_id: str, change_id: str
    ) -> dict[str, Any] | None:
        """在 changelogs/ 中查找指定 change_id 的日志条目。"""
        logs = self.file_manager.list_change_logs(novel_id, limit=10_000)
        for entry in logs:
            if entry.get("change_id") == change_id:
                return entry
        return None

    def _find_dependent_changes(
        self, novel_id: str, target: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """查找在 target 之后、针对同一实体的变更。"""
        logs = self.file_manager.list_change_logs(novel_id, limit=10_000)
        target_id = target.get("change_id")
        target_ts = target.get("timestamp", "")
        entity_type = target.get("entity_type")

        # 决定如何识别"同一实体"
        target_entity_id = target.get("entity_id")
        target_chapter = self._extract_chapter_number(target)

        deps: list[dict[str, Any]] = []
        for entry in logs:
            if entry.get("change_id") == target_id:
                continue
            if entry.get("timestamp", "") <= target_ts:
                continue
            if entry.get("entity_type") != entity_type:
                continue

            # 匹配规则
            if entity_type == "character":
                if target_entity_id and (
                    entry.get("entity_id") == target_entity_id
                ):
                    deps.append(entry)
            elif entity_type == "outline":
                ch = self._extract_chapter_number(entry)
                if target_chapter is not None and ch == target_chapter:
                    deps.append(entry)
            elif entity_type == "world_setting":
                deps.append(entry)

        return deps

    @staticmethod
    def _extract_chapter_number(entry: dict[str, Any]) -> int | None:
        """从日志条目中抽取 chapter_number（outline 用）。"""
        for key in ("new_value", "old_value"):
            val = entry.get(key)
            if isinstance(val, dict) and "chapter_number" in val:
                return val["chapter_number"]
        return None

    def _apply_reverse(
        self, novel_data: dict, target: dict[str, Any]
    ) -> None:
        """根据 target 变更记录反向修改 novel_data。

        直接操作实体列表/字段，不经过 editor.apply() 的 Pydantic 校验，
        因为 old_value 已是之前校验过的完整快照。
        """
        change_type = target.get("change_type", "")
        entity_type = target.get("entity_type", "")
        old_val = target.get("old_value")
        new_val = target.get("new_value")

        if entity_type == "character":
            chars = novel_data.setdefault("characters", [])
            if change_type == "add":
                # 移除 new_val 对应的 character
                if not isinstance(new_val, dict):
                    raise ValueError("add_character 日志缺少 new_value")
                char_id = new_val.get("character_id")
                novel_data["characters"] = [
                    c for c in chars if c.get("character_id") != char_id
                ]
            elif change_type in ("update", "delete"):
                if not isinstance(old_val, dict):
                    raise ValueError(
                        f"{change_type}_character 日志缺少 old_value"
                    )
                char_id = old_val.get("character_id")
                restored = copy.deepcopy(old_val)
                replaced = False
                for i, c in enumerate(chars):
                    if c.get("character_id") == char_id:
                        chars[i] = restored
                        replaced = True
                        break
                if not replaced:
                    # 目标角色已不存在（可能被别的逻辑移除），直接追加恢复
                    chars.append(restored)
            else:
                raise ValueError(
                    f"不支持回滚 character 变更类型: {change_type}"
                )

        elif entity_type == "outline":
            outline = novel_data.setdefault("outline", {})
            chapters = outline.setdefault("chapters", [])
            if change_type == "add":
                if not isinstance(new_val, dict):
                    raise ValueError("add_outline 日志缺少 new_value")
                ch_num = new_val.get("chapter_number")
                outline["chapters"] = [
                    c for c in chapters if c.get("chapter_number") != ch_num
                ]
            elif change_type == "update":
                if not isinstance(old_val, dict):
                    raise ValueError("update_outline 日志缺少 old_value")
                ch_num = old_val.get("chapter_number")
                restored = copy.deepcopy(old_val)
                replaced = False
                for i, c in enumerate(chapters):
                    if c.get("chapter_number") == ch_num:
                        chapters[i] = restored
                        replaced = True
                        break
                if not replaced:
                    chapters.append(restored)
                    chapters.sort(key=lambda c: c.get("chapter_number", 0))
            else:
                raise ValueError(
                    f"不支持回滚 outline 变更类型: {change_type}"
                )

        elif entity_type == "world_setting":
            if change_type != "update":
                raise ValueError(
                    f"不支持回滚 world_setting 变更类型: {change_type}"
                )
            if not isinstance(old_val, dict):
                raise ValueError("update_world_setting 日志缺少 old_value")
            novel_data["world_setting"] = copy.deepcopy(old_val)

        else:
            raise ValueError(f"不支持回滚的实体类型: {entity_type}")

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
