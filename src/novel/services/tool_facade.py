"""NovelToolFacade — MCP / CLI / agent_chat 三层共享的工具层 facade。

Phase 4 架构重构（2026-04）的核心实现。

职责
----
将 ``ProjectArchitect`` / ``VolumeDirector`` / ``ChapterPlanner`` 已有的
``propose_*`` / ``accept_into`` / ``regenerate_section`` 方法暴露为统一的
三段式 API（propose / accept / regenerate），让 MCP 工具、CLI 子命令和
agent_chat 三层共用同一套业务逻辑。

不可违反的设计原则（Phase 4 文档 §1）
-----------------------------------
1. **propose 不入库** — ``propose_*`` 返回 :class:`ProposalEnvelope`，不写
   ``novel.json``。
2. **accept 幂等** — 同一 ``proposal_id`` 重复 ``accept`` 不产生副作用
   （检查 ``novel_data["_meta"]["last_accepted_proposal_id"]``）。
3. **三层同底** — 只在本模块写业务逻辑，MCP/CLI/agent_chat 层只做参数
   适配与结果格式化。
4. **facade 不持有 LLM** — facade 负责加载/保存项目、调 Agent、包装结果；
   LLM 实例在每次调用时按 ``novel.json -> config.llm`` 重新创建。
5. **SYNC only** — 与 LLMClient / Agent 接口保持同步。

数据结构对齐
------------
- :class:`ProposalEnvelope` / :class:`AcceptResult` 为 facade 层统一包装，
  不侵入 Agent 已定型的 Proposal dataclass。
- ``accept_proposal`` 通过 ``_apply_proposal`` 分派到各 Proposal 的
  ``accept_into(novel)`` / ``accept(volume)``。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.llm.llm_client import create_llm_client
from src.novel.agents.chapter_planner import ChapterPlanner
from src.novel.agents.project_architect import (
    ArcsProposal,
    CharactersProposal,
    MainOutlineProposal,
    ProjectArchitect,
    ProjectSetupProposal,
    SynopsisProposal,
    VolumeBreakdownProposal,
    WorldProposal,
)
from src.novel.agents.volume_director import VolumeDirector, VolumeOutlineProposal
from src.novel.models.character import CharacterProfile
from src.novel.models.world import WorldSetting
from src.novel.storage.file_manager import FileManager

log = logging.getLogger("novel.tool_facade")


# ---------------------------------------------------------------------------
# Public wrappers
# ---------------------------------------------------------------------------


@dataclass
class ProposalEnvelope:
    """工具层统一返回包装（不同于 Agent 的 ``*Proposal`` dataclass）。

    所有 ``propose_*`` / ``regenerate_section`` 返回此对象；调用方可直接
    ``to_dict()`` 序列化给 MCP / CLI / agent_chat。
    """

    proposal_id: str = field(default_factory=lambda: str(uuid4()))
    proposal_type: str = ""
    project_path: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "project_path": self.project_path,
            "data": self.data,
            "decisions": list(self.decisions),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "created_at": self.created_at,
        }


@dataclass
class AcceptResult:
    """``accept_proposal`` 的统一返回。"""

    status: str = "accepted"  # "accepted" | "already_accepted" | "failed"
    proposal_id: str = ""
    proposal_type: str = ""
    changelog_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
        }
        if self.changelog_id:
            result["changelog_id"] = self.changelog_id
        if self.error:
            result["error"] = self.error
        return result


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class NovelToolFacade:
    """工具层统一 facade —— MCP / CLI / agent_chat 共享此类。

    Args:
        workspace: 项目 workspace 目录（通常 ``"workspace"``）。
    """

    # 允许的 regenerate section 名（与 ProjectArchitect.regenerate_section 对齐）
    _PA_REGEN_SECTIONS = frozenset({
        "synopsis",
        "characters",
        "world_setting",
        "story_arcs",
        "volume_breakdown",
        "main_outline",
    })

    # 明确不支持 regenerate 的实体（需重新 propose）
    _NO_REGEN_SECTIONS = frozenset({"project_setup", "chapter_brief"})

    def __init__(self, workspace: str = "workspace") -> None:
        self.workspace = workspace
        self._fm = FileManager(workspace)

    # ==================================================================
    # propose 系列
    # ==================================================================

    def propose_project_setup(
        self,
        inspiration: str,
        hints: dict[str, Any] | None = None,
    ) -> ProposalEnvelope:
        """立项阶段草案 —— 不需要 ``project_path``（项目尚未建）。"""
        try:
            llm = self._create_llm_from_cfg({})
            architect = ProjectArchitect(llm)
            proposal = architect.propose_project_setup(inspiration, hints=hints)
            return ProposalEnvelope(
                proposal_type="project_setup",
                project_path="",
                data=proposal.to_dict(),
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("propose_project_setup failed: %s", exc)
            return ProposalEnvelope(
                proposal_type="project_setup",
                project_path="",
                errors=[{"message": str(exc)}],
            )

    def propose_synopsis(self, project_path: str) -> ProposalEnvelope:
        def _run(novel_data: dict) -> ProposalEnvelope:
            architect = self._make_project_architect(novel_data)
            meta = self._build_meta(novel_data)
            proposal = architect.propose_synopsis(meta)
            return ProposalEnvelope(
                proposal_type="synopsis",
                project_path=project_path,
                data=proposal.to_dict(),
            )

        return self._wrap_propose(project_path, "synopsis", _run)

    def propose_main_outline(
        self,
        project_path: str,
        custom_ideas: str | None = None,
    ) -> ProposalEnvelope:
        def _run(novel_data: dict) -> ProposalEnvelope:
            architect = self._make_project_architect(novel_data)
            genre = novel_data.get("genre", "")
            theme = novel_data.get("theme", "")
            target_words = int(novel_data.get("target_words") or 0)
            template_name = novel_data.get("template", "") or ""
            style_name = novel_data.get("style_name", "") or ""
            proposal: MainOutlineProposal = architect.propose_main_outline(
                genre=genre,
                theme=theme,
                target_words=target_words,
                template_name=template_name,
                style_name=style_name,
                custom_ideas=custom_ideas,
            )
            return ProposalEnvelope(
                proposal_type="main_outline",
                project_path=project_path,
                data=proposal.to_dict(),
                decisions=list(proposal.decisions or []),
                errors=list(proposal.errors or []),
            )

        return self._wrap_propose(project_path, "main_outline", _run)

    def propose_characters(
        self,
        project_path: str,
        synopsis: str | None = None,
    ) -> ProposalEnvelope:
        """facade 的 ``characters`` 映射到 ``ProjectArchitect.propose_main_characters``。"""

        def _run(novel_data: dict) -> ProposalEnvelope:
            architect = self._make_project_architect(novel_data)
            meta = self._build_meta(novel_data)
            syn = synopsis if synopsis is not None else str(
                novel_data.get("synopsis", "") or ""
            )
            proposal = architect.propose_main_characters(meta, synopsis=syn)
            return ProposalEnvelope(
                proposal_type="characters",
                project_path=project_path,
                data=proposal.to_dict(),
            )

        return self._wrap_propose(project_path, "characters", _run)

    def propose_world_setting(
        self,
        project_path: str,
        synopsis: str | None = None,
    ) -> ProposalEnvelope:
        def _run(novel_data: dict) -> ProposalEnvelope:
            architect = self._make_project_architect(novel_data)
            meta = self._build_meta(novel_data)
            syn = synopsis if synopsis is not None else str(
                novel_data.get("synopsis", "") or ""
            )
            proposal = architect.propose_world_setting(meta, synopsis=syn)
            return ProposalEnvelope(
                proposal_type="world_setting",
                project_path=project_path,
                data=proposal.to_dict(),
            )

        return self._wrap_propose(project_path, "world_setting", _run)

    def propose_story_arcs(self, project_path: str) -> ProposalEnvelope:
        def _run(novel_data: dict) -> ProposalEnvelope:
            architect = self._make_project_architect(novel_data)
            meta = self._build_meta(novel_data, include_outline=True)
            synopsis = str(novel_data.get("synopsis", "") or "")
            characters = novel_data.get("characters") or []
            world = novel_data.get("world_setting") or {}
            proposal = architect.propose_story_arcs(
                meta, synopsis, characters=characters, world=world
            )
            return ProposalEnvelope(
                proposal_type="story_arcs",
                project_path=project_path,
                data=proposal.to_dict(),
            )

        return self._wrap_propose(project_path, "story_arcs", _run)

    def propose_volume_breakdown(
        self,
        project_path: str,
        synopsis: str | None = None,
    ) -> ProposalEnvelope:
        def _run(novel_data: dict) -> ProposalEnvelope:
            architect = self._make_project_architect(novel_data)
            meta = self._build_meta(novel_data)
            syn = synopsis if synopsis is not None else str(
                novel_data.get("synopsis", "") or ""
            )
            arcs = novel_data.get("story_arcs") or []
            proposal = architect.propose_volume_breakdown(meta, syn, arcs=arcs)
            return ProposalEnvelope(
                proposal_type="volume_breakdown",
                project_path=project_path,
                data=proposal.to_dict(),
            )

        return self._wrap_propose(project_path, "volume_breakdown", _run)

    def propose_volume_outline(
        self,
        project_path: str,
        volume_number: int,
    ) -> ProposalEnvelope:
        def _run(novel_data: dict) -> ProposalEnvelope:
            director = self._make_volume_director(novel_data)
            proposal: VolumeOutlineProposal = director.propose_volume_outline(
                novel=novel_data, volume_number=volume_number
            )
            return ProposalEnvelope(
                proposal_type="volume_outline",
                project_path=project_path,
                data=proposal.to_dict(),
            )

        return self._wrap_propose(project_path, "volume_outline", _run)

    def propose_chapter_brief(
        self,
        project_path: str,
        chapter_number: int,
    ) -> ProposalEnvelope:
        def _run(novel_data: dict) -> ProposalEnvelope:
            planner = self._make_chapter_planner(novel_data)
            # 从 outline 找到 chapter_number 对应的 outline dict
            outline = novel_data.get("outline") or {}
            ch_outlines = (
                outline.get("chapters") if isinstance(outline, dict) else None
            ) or []
            target_outline = next(
                (
                    c
                    for c in ch_outlines
                    if isinstance(c, dict)
                    and int(c.get("chapter_number", 0) or 0) == chapter_number
                ),
                None,
            )
            # 推断 volume_number：scan outline.volumes[].chapters
            volume_number = 1
            for vol in (outline.get("volumes") or []):
                if isinstance(vol, dict) and chapter_number in (
                    vol.get("chapters") or []
                ):
                    volume_number = int(vol.get("volume_number", 1) or 1)
                    break
            proposal = planner.propose_chapter_brief(
                novel=novel_data,
                volume_number=volume_number,
                chapter_number=chapter_number,
                chapter_outline=target_outline,
            )
            return ProposalEnvelope(
                proposal_type="chapter_brief",
                project_path=project_path,
                data=proposal.model_dump(),
                warnings=list(proposal.warnings or []),
            )

        return self._wrap_propose(project_path, "chapter_brief", _run)

    # ==================================================================
    # accept
    # ==================================================================

    def accept_proposal(
        self,
        project_path: str,
        proposal_id: str,
        proposal_type: str,
        data: dict,
    ) -> AcceptResult:
        """确认落盘一个 ``propose_*`` 返回的草案。

        幂等：同一 ``proposal_id`` 重复调用时立即返回
        ``status="already_accepted"``，不再写盘。

        Raises:
            ValueError: 未知 ``proposal_type`` / ``project_setup`` 走特殊分支。
        """
        if proposal_type == "project_setup":
            # project_setup 暂不支持 accept（需要立项建目录，语义比其它 type 重），
            # 留待 E2/E3 决策后接入；此处直接返回 failed，避免误写。
            return AcceptResult(
                status="failed",
                proposal_id=proposal_id,
                proposal_type=proposal_type,
                error=(
                    "accept_project_setup 尚未实现 —— 立项阶段请直接走"
                    " pipeline.create_novel 或等待 Phase 4 后续任务接入"
                ),
            )

        try:
            novel_id = self._extract_novel_id(project_path)
        except ValueError as exc:
            return AcceptResult(
                status="failed",
                proposal_id=proposal_id,
                proposal_type=proposal_type,
                error=str(exc),
            )

        novel_data = self._fm.load_novel(novel_id)
        if novel_data is None:
            return AcceptResult(
                status="failed",
                proposal_id=proposal_id,
                proposal_type=proposal_type,
                error=f"项目不存在: {project_path}",
            )

        # 幂等检查
        existing = (novel_data.get("_meta") or {}).get("last_accepted_proposal_id")
        if existing == proposal_id:
            return AcceptResult(
                status="already_accepted",
                proposal_id=proposal_id,
                proposal_type=proposal_type,
            )

        # Dispatch — 未知 proposal_type 抛 ValueError
        try:
            self._apply_proposal(novel_data, proposal_type, data)
        except ValueError:
            # 未知 proposal_type / 结构不合法 — 统一抛 ValueError 由 caller 处理
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("accept_proposal[%s] failed: %s", proposal_type, exc)
            return AcceptResult(
                status="failed",
                proposal_id=proposal_id,
                proposal_type=proposal_type,
                error=str(exc),
            )

        # 记录幂等标记
        meta = novel_data.setdefault("_meta", {})
        if not isinstance(meta, dict):
            # 极端情况：meta 字段被外部污染成非 dict — 重建
            meta = {}
            novel_data["_meta"] = meta
        meta["last_accepted_proposal_id"] = proposal_id
        meta["last_accepted_at"] = datetime.now(timezone.utc).isoformat()
        meta["last_accepted_type"] = proposal_type

        # 持久化 — save 失败不得传播异常破坏 AcceptResult 契约。
        # 内存副本虽已被 _apply_proposal 修改，但 novel_data 是 load 出来的
        # in-memory 副本，未 save → 下次 accept 会重新 load 干净状态。
        try:
            self._fm.save_novel(novel_id, novel_data)
        except Exception as exc:  # noqa: BLE001
            log.exception("accept_proposal[%s] save_novel failed: %s",
                          proposal_type, exc)
            return AcceptResult(
                status="failed",
                proposal_id=proposal_id,
                proposal_type=proposal_type,
                error=f"save failed: {exc}",
            )

        return AcceptResult(
            status="accepted",
            proposal_id=proposal_id,
            proposal_type=proposal_type,
        )

    # ==================================================================
    # regenerate
    # ==================================================================

    def regenerate_section(
        self,
        project_path: str,
        section: str,
        hints: str = "",
        volume_number: int | None = None,
    ) -> ProposalEnvelope:
        """对骨架段落按 ``hints`` 重新生成草案。

        Args:
            project_path: 项目路径。
            section: ``synopsis`` / ``characters`` / ``world_setting`` /
                ``story_arcs`` / ``volume_breakdown`` / ``main_outline`` /
                ``volume_outline``。
            hints: 作者对"哪里不满意/想要什么"的自然语言提示。
            volume_number: 仅 ``volume_outline`` 使用。

        Raises:
            ValueError: section 在 ``_NO_REGEN_SECTIONS`` 中（需重新 propose）；
                或 section 未识别。
        """
        if section in self._NO_REGEN_SECTIONS:
            raise ValueError(
                f"section {section!r} 不支持 regenerate，请重新 propose"
            )

        if section == "volume_outline":
            if volume_number is None:
                raise ValueError("regenerate_section volume_outline 需要 volume_number")

            def _run_vol(novel_data: dict) -> ProposalEnvelope:
                director = self._make_volume_director(novel_data)
                # VolumeDirector.propose_volume_outline 在 E3 任务中会加 hints=...
                # 此处总是传 hints=，当前若 signature 不支持则 fallback 到无 hints。
                try:
                    proposal = director.propose_volume_outline(
                        novel=novel_data,
                        volume_number=volume_number,
                        hints=hints,  # type: ignore[call-arg]
                    )
                except TypeError:
                    # E3 未上线时的兼容：忽略 hints
                    proposal = director.propose_volume_outline(
                        novel=novel_data,
                        volume_number=volume_number,
                    )
                return ProposalEnvelope(
                    proposal_type="volume_outline",
                    project_path=project_path,
                    data=proposal.to_dict(),
                    warnings=(
                        ["volume_outline hints ignored (signature pre-E3)"]
                        if hints
                        else []
                    ),
                )

            return self._wrap_propose(project_path, "volume_outline", _run_vol)

        if section not in self._PA_REGEN_SECTIONS:
            raise ValueError(f"未知 section: {section!r}")

        # ProjectArchitect.regenerate_section 只认以下字面量：
        # synopsis / characters / world / arcs / volume_breakdown
        # facade 层用户侧名字 → architect section 名
        pa_section_map = {
            "synopsis": "synopsis",
            "characters": "characters",
            "world_setting": "world",
            "story_arcs": "arcs",
            "volume_breakdown": "volume_breakdown",
            # main_outline 走 propose_main_outline(custom_ideas=hints) 而非 regenerate
        }

        def _run_pa(novel_data: dict) -> ProposalEnvelope:
            architect = self._make_project_architect(novel_data)

            if section == "main_outline":
                # 特殊路径：PA.regenerate_section 不支持 main_outline。
                genre = novel_data.get("genre", "")
                theme = novel_data.get("theme", "")
                target_words = int(novel_data.get("target_words") or 0)
                template_name = novel_data.get("template", "") or ""
                style_name = novel_data.get("style_name", "") or ""
                proposal = architect.propose_main_outline(
                    genre=genre,
                    theme=theme,
                    target_words=target_words,
                    template_name=template_name,
                    style_name=style_name,
                    custom_ideas=hints or None,
                )
                return ProposalEnvelope(
                    proposal_type="main_outline",
                    project_path=project_path,
                    data=proposal.to_dict(),
                    decisions=list(proposal.decisions or []),
                    errors=list(proposal.errors or []),
                )

            pa_section = pa_section_map[section]
            current_spine = {
                "meta": self._build_meta(novel_data, include_outline=True),
                "synopsis": novel_data.get("synopsis", ""),
                "characters": novel_data.get("characters") or [],
                "world": novel_data.get("world_setting") or {},
                "arcs": novel_data.get("story_arcs") or [],
            }
            proposal = architect.regenerate_section(
                section=pa_section,  # type: ignore[arg-type]
                current_spine=current_spine,
                hints=hints or "",
            )
            if not hasattr(proposal, "to_dict"):
                raise TypeError(
                    "regenerate_section returned non-proposal: "
                    f"{type(proposal).__name__}"
                )
            return ProposalEnvelope(
                proposal_type=section,
                project_path=project_path,
                data=proposal.to_dict(),
            )

        return self._wrap_propose(project_path, section, _run_pa)

    # ==================================================================
    # Internal helpers
    # ==================================================================

    @staticmethod
    def _extract_novel_id(project_path: str) -> str:
        """从 ``project_path`` 提取 ``novel_id``（最后一个目录名）。"""
        p = (project_path or "").strip()
        if not p:
            raise ValueError("project_path 为空")
        # 去掉末尾的斜杠以免 Path.name 返回空
        # pathlib.Path 处理 "foo/" 会返回 "foo"（PurePath.name 定义如此）。
        name = Path(p).name
        if not name or name in (".", ".."):
            raise ValueError(f"非法 project_path: {project_path}")
        if "/" in name or "\\" in name:
            raise ValueError(f"非法 project_path: {project_path}")
        return name

    def _wrap_propose(
        self,
        project_path: str,
        proposal_type: str,
        runner: Any,
    ) -> ProposalEnvelope:
        """统一：novel_id 解析 + load_novel 校验 + 异常 → errors 包装。"""
        try:
            novel_id = self._extract_novel_id(project_path)
        except ValueError as exc:
            return ProposalEnvelope(
                proposal_type=proposal_type,
                project_path=project_path,
                errors=[{"message": str(exc)}],
            )

        novel_data = self._fm.load_novel(novel_id)
        if novel_data is None:
            return ProposalEnvelope(
                proposal_type=proposal_type,
                project_path=project_path,
                errors=[{"message": f"项目不存在: {project_path}"}],
            )

        try:
            return runner(novel_data)
        except TypeError:
            # TypeError 代表工具层/Agent 契约错误（如 regenerate 返回非
            # Proposal 对象），属于编程 bug 而非业务失败，必须向上传播让
            # caller 能在测试/CI 里直接暴露。
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("propose_%s failed: %s", proposal_type, exc)
            return ProposalEnvelope(
                proposal_type=proposal_type,
                project_path=project_path,
                errors=[{"message": str(exc)}],
            )

    # --- Agent factories --------------------------------------------------

    def _make_project_architect(self, novel_data: dict) -> ProjectArchitect:
        llm = self._create_llm_from_cfg(
            (novel_data.get("config") or {}).get("llm") or {}
        )
        return ProjectArchitect(llm)

    def _make_volume_director(self, novel_data: dict) -> VolumeDirector:
        llm = self._create_llm_from_cfg(
            (novel_data.get("config") or {}).get("llm") or {}
        )
        return VolumeDirector(llm, workspace=self.workspace)

    def _make_chapter_planner(self, novel_data: dict) -> ChapterPlanner:
        llm = self._create_llm_from_cfg(
            (novel_data.get("config") or {}).get("llm") or {}
        )
        return ChapterPlanner(llm)

    @staticmethod
    def _create_llm_from_cfg(llm_cfg: dict) -> Any:
        """Wrap ``create_llm_client`` so tests can patch a single seam."""
        return create_llm_client(llm_cfg)

    @staticmethod
    def _build_meta(novel_data: dict, include_outline: bool = False) -> dict:
        """从 novel.json 构造 Agent 需要的 ``meta`` dict（含 genre/theme 等）。"""
        meta: dict[str, Any] = {
            "genre": novel_data.get("genre", ""),
            "theme": novel_data.get("theme", ""),
            "target_words": int(novel_data.get("target_words") or 0),
            "style_name": novel_data.get("style_name", ""),
            "target_length_class": novel_data.get("target_length_class", ""),
            "narrative_template": novel_data.get("template", ""),
            "custom_ideas": novel_data.get("custom_style_reference") or "",
        }
        if include_outline:
            outline = novel_data.get("outline")
            if isinstance(outline, dict):
                meta["outline"] = outline
        return meta

    # --- accept dispatcher -----------------------------------------------

    def _apply_proposal(
        self,
        novel_data: dict,
        proposal_type: str,
        data: dict,
    ) -> None:
        """把 ``data`` 按 ``proposal_type`` 写入 ``novel_data`` (in-place)。

        Raises:
            ValueError: 未知 ``proposal_type`` / 结构字段缺失。
        """
        if not isinstance(data, dict):
            raise ValueError(f"data 必须是 dict，实际为 {type(data).__name__}")

        if proposal_type == "synopsis":
            SynopsisProposal(
                synopsis=str(data.get("synopsis", "") or ""),
                main_storyline=dict(data.get("main_storyline") or {}),
            ).accept_into(novel_data)
            return

        if proposal_type == "characters":
            raw_chars = data.get("characters") or []
            if not isinstance(raw_chars, list):
                raise ValueError("characters.data.characters 必须是 list")
            profiles: list[CharacterProfile] = []
            invalid: list[str] = []
            total = len(raw_chars)
            for idx, c in enumerate(raw_chars):
                if not isinstance(c, dict):
                    invalid.append(
                        f"[{idx}] 非 dict ({type(c).__name__})"
                    )
                    continue
                try:
                    profiles.append(CharacterProfile(**c))
                except Exception as exc:  # noqa: BLE001
                    invalid.append(f"[{idx}] {exc}")
            if invalid:
                # 严格模式：任一 profile 非法即整批拒绝，避免 accept_into
                # 覆盖写入时丢失已有角色或落盘残缺集合。
                raise ValueError(
                    f"{len(invalid)}/{total} character profiles 非法: "
                    + "; ".join(invalid)
                )
            CharactersProposal(characters=profiles).accept_into(novel_data)
            return

        if proposal_type == "world_setting":
            world_dict = data.get("world_setting")
            if not isinstance(world_dict, dict):
                raise ValueError("world_setting.data.world_setting 必须是 dict")
            try:
                world = WorldSetting(**world_dict)
            except Exception as exc:
                raise ValueError(f"world_setting 数据非法: {exc}") from exc
            WorldProposal(world=world).accept_into(novel_data)
            return

        if proposal_type == "story_arcs":
            arcs = data.get("arcs") or []
            if not isinstance(arcs, list):
                raise ValueError("story_arcs.data.arcs 必须是 list")
            ArcsProposal(arcs=list(arcs)).accept_into(novel_data)
            return

        if proposal_type == "volume_breakdown":
            volumes = data.get("volumes") or []
            if not isinstance(volumes, list):
                raise ValueError("volume_breakdown.data.volumes 必须是 list")
            VolumeBreakdownProposal(volumes=list(volumes)).accept_into(novel_data)
            return

        if proposal_type == "main_outline":
            kwargs = {
                k: data[k] for k in ("outline", "template", "style_name") if k in data
            }
            if "style_bible" in data:
                kwargs["style_bible"] = data.get("style_bible")
            if "total_chapters" in data:
                kwargs["total_chapters"] = int(data.get("total_chapters") or 0)
            MainOutlineProposal(**kwargs).accept_into(novel_data)
            return

        if proposal_type == "volume_outline":
            volume_number = int(data.get("volume_number") or 0)
            if volume_number <= 0:
                raise ValueError("volume_outline.data.volume_number 必须为正整数")
            outline = novel_data.setdefault("outline", {})
            if not isinstance(outline, dict):
                raise ValueError("novel.outline 结构异常，无法写入 volume_outline")
            volumes = outline.setdefault("volumes", []) or []
            if not isinstance(volumes, list):
                raise ValueError("novel.outline.volumes 结构异常")
            # 查找对应卷 dict
            target_idx = None
            for i, v in enumerate(volumes):
                if (
                    isinstance(v, dict)
                    and int(v.get("volume_number", 0) or 0) == volume_number
                ):
                    target_idx = i
                    break
            if target_idx is None:
                # 不存在则追加一个壳
                volumes.append({
                    "volume_number": volume_number,
                    "title": data.get("title", f"第{volume_number}卷"),
                    "core_conflict": "",
                    "resolution": "",
                    "chapters": list(data.get("chapter_numbers") or []),
                })
                target_idx = len(volumes) - 1
            vol_dict = volumes[target_idx]
            # dict merge：把 proposal 的字段直接写回（保留已存在的字段）
            vol_dict["volume_number"] = volume_number
            if data.get("title"):
                vol_dict["title"] = data["title"]
            if data.get("volume_goal"):
                vol_dict["volume_goal"] = data["volume_goal"]
            if data.get("chapter_numbers"):
                vol_dict["chapters"] = list(data["chapter_numbers"])
                vol_dict["volume_outline"] = list(data["chapter_numbers"])
            if data.get("chapter_type_dist"):
                vol_dict["chapter_type_dist"] = dict(data["chapter_type_dist"])
            if data.get("foreshadowing_plan"):
                vol_dict["foreshadowing_plan"] = dict(data["foreshadowing_plan"])
            if data.get("chapter_outlines"):
                # 把章节大纲 merge 到 outline.chapters
                ch_outlines = outline.setdefault("chapters", [])
                if not isinstance(ch_outlines, list):
                    ch_outlines = []
                    outline["chapters"] = ch_outlines
                existing_by_num = {
                    int(c.get("chapter_number", 0) or 0): i
                    for i, c in enumerate(ch_outlines)
                    if isinstance(c, dict)
                }
                for co in data["chapter_outlines"]:
                    if not isinstance(co, dict):
                        continue
                    num = int(co.get("chapter_number", 0) or 0)
                    if num in existing_by_num:
                        ch_outlines[existing_by_num[num]] = co
                    else:
                        ch_outlines.append(co)
                ch_outlines.sort(
                    key=lambda c: int(c.get("chapter_number", 0) or 0)
                )
            outline["volumes"] = volumes
            novel_data["outline"] = outline
            return

        if proposal_type == "chapter_brief":
            brief_dict = data.get("brief") or data.get("chapter_brief") or {}
            if not isinstance(brief_dict, dict):
                raise ValueError("chapter_brief.data.brief 必须是 dict")
            chapter_number = int(
                brief_dict.get("chapter_number")
                or data.get("chapter_number")
                or 0
            )
            if chapter_number <= 0:
                raise ValueError("chapter_brief.chapter_number 必须为正整数")
            outline = novel_data.setdefault("outline", {})
            if not isinstance(outline, dict):
                raise ValueError("novel.outline 结构异常，无法写入 chapter_brief")
            ch_outlines = outline.setdefault("chapters", []) or []
            if not isinstance(ch_outlines, list):
                raise ValueError("novel.outline.chapters 结构异常")
            target = None
            for c in ch_outlines:
                if (
                    isinstance(c, dict)
                    and int(c.get("chapter_number", 0) or 0) == chapter_number
                ):
                    target = c
                    break
            if target is None:
                raise ValueError(
                    f"chapter_brief 找不到对应章节 {chapter_number}，请先写 main_outline"
                )
            # Merge：legacy chapter_brief dict 字段覆盖写入
            legacy = dict(target.get("chapter_brief") or {})
            # 把 canonical ChapterBrief 字段转成 legacy 形状
            legacy.update({
                "main_conflict": brief_dict.get("goal") or legacy.get("main_conflict", ""),
                "payoff": brief_dict.get("tone_notes") or legacy.get("payoff", ""),
                "foreshadowing_collect": list(
                    brief_dict.get("must_collect_foreshadowings") or []
                ) or legacy.get("foreshadowing_collect", []),
                "end_hook_type": brief_dict.get("end_hook_type")
                or legacy.get("end_hook_type", ""),
            })
            target["chapter_brief"] = legacy
            return

        raise ValueError(f"未知 proposal_type: {proposal_type!r}")


__all__ = [
    "AcceptResult",
    "NovelToolFacade",
    "ProposalEnvelope",
]
