"""Novel Agent Chat — tool-calling agent that autonomously executes novel operations.

Works like Claude Code: the user sends a natural language message, the agent
interprets it, decides which tools to call, executes them, and returns results.
Supports multi-step reasoning with a tool loop.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("novel.agent_chat")

# Default max tool-call iterations (can be overridden by config.yaml agent_chat.max_iterations)
_DEFAULT_MAX_ITERATIONS = 20


# ---------------------------------------------------------------------------
# Tool definitions (for LLM function-calling)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "read_chapter",
        "description": "读取指定章节的全文内容和元数据",
        "parameters": {
            "chapter_number": {"type": "integer", "description": "章节号"}
        },
    },
    {
        "name": "edit_setting",
        "description": "用自然语言指令修改小说设定（角色、世界观、大纲等）",
        "parameters": {
            "instruction": {"type": "string", "description": "修改指令，如'把主角年龄改为25岁'"},
            "effective_from_chapter": {"type": "integer", "description": "从哪一章开始生效（可选）", "optional": True},
        },
    },
    {
        "name": "rewrite_chapter",
        "description": "根据反馈重写指定章节",
        "parameters": {
            "feedback_text": {"type": "string", "description": "重写指令/反馈"},
            "chapter_number": {"type": "integer", "description": "要重写的章节号"},
        },
    },
    {
        "name": "generate_chapters",
        "description": "生成新章节（调用完整 pipeline：情节规划→正文生成→一致性检查→质量审核）。生成需要一定时间，每章约30-60秒。",
        "parameters": {
            "num_chapters": {"type": "integer", "description": "要生成的章节数量（默认1）", "optional": True},
            "start_chapter": {"type": "integer", "description": "起始章节号（默认从最后一章之后开始）", "optional": True},
        },
    },
    {
        "name": "resize_novel",
        "description": "调整小说总章节数（扩容或缩减）",
        "parameters": {
            "new_total": {"type": "integer", "description": "新的目标总章节数"},
        },
    },
    {
        "name": "publish_chapters",
        "description": "标记章节为已发布或取消发布",
        "parameters": {
            "chapters": {"type": "array", "description": "章节号列表，如 [1,2,3]"},
            "published": {"type": "boolean", "description": "true=标记发布，false=取消发布"},
        },
    },
    {
        "name": "proofread_chapter",
        "description": "AI校对指定章节，检查错别字、语法、标点等问题",
        "parameters": {
            "chapter_number": {"type": "integer", "description": "章节号"},
        },
    },
    {
        "name": "get_novel_info",
        "description": "获取小说的基本信息（标题、状态、章节数、角色列表等）",
        "parameters": {},
    },
    {
        "name": "search_chapters",
        "description": "在所有章节中搜索包含关键词的内容",
        "parameters": {
            "keyword": {"type": "string", "description": "搜索关键词"},
        },
    },
    {
        "name": "reply_to_user",
        "description": "直接回复用户（不执行任何操作），用于回答问题或给出建议",
        "parameters": {
            "message": {"type": "string", "description": "回复内容"},
        },
    },
    {
        "name": "get_narrative_debts",
        "description": "查看叙事债务（未兑现的承诺、悬念、伏笔等），可按状态筛选",
        "parameters": {
            "status": {"type": "string", "description": "筛选状态: all/pending/overdue/fulfilled（默认 all）", "optional": True},
            "chapter": {"type": "integer", "description": "查看特定章节相关的债务（可选）", "optional": True},
        },
    },
    {
        "name": "manage_debt",
        "description": "管理叙事债务：标记为已兑现、调整优先级、添加新债务",
        "parameters": {
            "action": {"type": "string", "description": "操作: fulfill/add/escalate"},
            "debt_id": {"type": "string", "description": "债务ID（fulfill/escalate时需要）", "optional": True},
            "chapter_number": {"type": "integer", "description": "债务兑现的章节号（fulfill时需要，不填则自动取当前章节）", "optional": True},
            "description": {"type": "string", "description": "债务描述（add时需要）", "optional": True},
            "source_chapter": {"type": "integer", "description": "来源章节号（add时需要）", "optional": True},
            "debt_type": {"type": "string", "description": "债务类型: must_pay_next/pay_within_3/long_tail_payoff（add时需要）", "optional": True},
        },
    },
    {
        "name": "get_story_arcs",
        "description": "查看故事弧线（StoryUnit），了解每个弧线的起止章节、阶段和状态",
        "parameters": {
            "volume": {"type": "integer", "description": "查看特定卷的弧线（可选）", "optional": True},
        },
    },
    {
        "name": "get_chapter_brief",
        "description": "查看章节任务书和完成度验证",
        "parameters": {
            "chapter_number": {"type": "integer", "description": "章节号"},
        },
    },
    {
        "name": "get_knowledge_graph",
        "description": "查看知识图谱中的角色关系网络",
        "parameters": {
            "character": {"type": "string", "description": "查看特定角色的关系（可选，不填返回全部）", "optional": True},
        },
    },
    {
        "name": "get_narrative_overview",
        "description": "获取叙事控制总览：待处理债务数、弧线进度、最近章节质量",
        "parameters": {},
    },
    # NOTE: "rebuild_narrative" tool removed with NarrativeRebuildService
    # (architecture-rework-2026 Phase 0). 叙事控制数据的重建路径将在
    # Phase 2/3 合并入 Verifier + LedgerStore 后以新形态回归。
    {
        "name": "get_volume_settlement",
        "description": "查看当前卷的收束状态 — 哪些债务必须在本卷解决，哪些可延续",
        "parameters": {
            "chapter_number": {"type": "integer", "description": "当前章节号"},
        },
    },
    {
        "name": "get_arc_status",
        "description": "查看所有故事弧线的当前阶段和推进状态",
        "parameters": {},
    },
    {
        "name": "plan_chapters",
        "description": "[DEPRECATED] Use propose_chapter_brief instead. 规划接下来几章的大纲（不生成正文）。生成标题、目标、关键事件、要收/埋的伏笔，供用户审核后再写作。",
        "parameters": {
            "num_chapters": {"type": "integer", "description": "要规划的章节数量（默认4）", "optional": True},
            "start_chapter": {"type": "integer", "description": "起始章节号（默认从最后一章之后开始）", "optional": True},
        },
    },
    {
        "name": "rename_chapter",
        "description": "修改章节标题（不会改动正文内容）",
        "parameters": {
            "chapter_number": {"type": "integer", "description": "章节号"},
            "new_title": {"type": "string", "description": "新标题"},
        },
    },
    {
        "name": "get_change_history",
        "description": "查看小说设定的变更历史（按时间倒序），可按变更类型过滤",
        "parameters": {
            "limit": {"type": "integer", "description": "返回最大条数（默认20）", "optional": True},
            "change_type": {"type": "string", "description": "按类型过滤: add/update/delete/rollback（可选）", "optional": True},
        },
    },
    {
        "name": "rollback_change",
        "description": "回滚指定的设定变更，恢复到变更前状态。若有后续依赖变更会拒绝，需 force=true 才能强制回滚。",
        "parameters": {
            "change_id": {"type": "string", "description": "要回滚的 change_id（从 get_change_history 获得）"},
            "force": {"type": "boolean", "description": "true=绕过依赖检查强制回滚（默认 false）", "optional": True},
        },
    },
    {
        "name": "analyze_change_impact",
        "description": "纯规则分析编辑操作对后续章节的影响（不调 LLM、不实际修改）。用于在 edit_setting 之前评估风险。",
        "parameters": {
            "change_type": {"type": "string", "description": "变更类型: add_character/modify_character/delete_character/modify_outline/modify_world"},
            "entity_type": {"type": "string", "description": "实体类型: character/outline/world"},
            "effective_from_chapter": {"type": "integer", "description": "变更生效起始章节（>=1）"},
            "entity_id": {"type": "string", "description": "实体 ID（角色 character_id 或章节号字符串）", "optional": True},
            "details": {"type": "object", "description": "变更详情字典（可选，例如 {'name':'柳青鸾'}）", "optional": True},
        },
    },
    {
        "name": "batch_edit_settings",
        "description": "批量应用多条结构化设定变更，每条独立 changelog 与回滚粒度。失败默认不影响其他，可选 stop_on_failure。",
        "parameters": {
            "changes": {"type": "array", "description": "结构化变更列表，每项包含 change_type/entity_type/entity_id/old_value/new_value/effective_from_chapter 等字段"},
            "dry_run": {"type": "boolean", "description": "true=只预览不写盘（默认 false）", "optional": True},
            "stop_on_failure": {"type": "boolean", "description": "true=遇首个失败即停止后续（默认 false）", "optional": True},
        },
    },
    {
        "name": "get_foreshadowing_graph",
        "description": "查看伏笔图谱：总数/已回收/待回收/即将遗忘统计，并列出 pending 伏笔（按遗忘风险排序）",
        "parameters": {
            "current_chapter": {"type": "integer", "description": "当前章节号（不填则从 novel.json 取 current_chapter）", "optional": True},
            "threshold": {"type": "integer", "description": "遗忘阈值（默认 10）", "optional": True},
        },
    },
    {
        "name": "get_health_dashboard",
        "description": "查看小说健康度仪表盘：综合得分 + 伏笔/里程碑/角色/实体/债务五维指标，并附可读报告",
        "parameters": {},
    },
    {
        "name": "verify_chapter",
        "description": "对已落盘章节跑硬约束验证：债务兑现/伏笔回收/禁用词/字数偏离。零 LLM 成本。",
        "parameters": {
            "chapter_number": {"type": "integer", "description": "章节号"},
            "target_words": {"type": "integer", "description": "目标字数（不填则跳过长度检查）", "optional": True},
            "extra_banned": {"type": "array", "description": "额外禁用词（叠加到全局 AI 黑名单上）", "optional": True},
        },
    },
    {
        "name": "critique_chapter",
        "description": "对已落盘章节调 Reviewer 做结构化批评（LLM + Ledger + StyleProfile）：返回 strengths / issues / specific_revisions / style_overuse_hits / consistency_flags。不修改正文。",
        "parameters": {
            "chapter_number": {"type": "integer", "description": "章节号"},
        },
    },
    {
        "name": "review_chapter",
        "description": "critique_chapter 的别名（Phase 2-β 重构后规范命名）。对已落盘章节跑 Reviewer 得 CritiqueResult，不修改正文。",
        "parameters": {
            "chapter_number": {"type": "integer", "description": "章节号"},
        },
    },
    {
        "name": "refine_chapter",
        "description": (
            "对已落盘章节出一份审阅报告（单轮，不改正文）：跑 sanitize + verifier + "
            "critic，返回 RefineReport（硬约束报告 + 软质量报告 + recommended_action）。"
            "作者读报告后若决定重写，请显式调用 rewrite_chapter 工具；本工具自身"
            "不会修改任何章节文件。"
        ),
        "parameters": {
            "chapter_number": {"type": "integer", "description": "章节号"},
            "enable_critic": {"type": "boolean", "description": "是否跑 critic 阶段（默认 true，关闭可省 LLM）", "optional": True},
        },
    },
    {
        "name": "get_reflexion_log",
        "description": "查看跨章反思日志（每章写完 AI 自动写的 lesson）。用户可见 AI '学到了什么'。",
        "parameters": {
            "start_chapter": {"type": "integer", "description": "起始章节号（含），不填从第1章", "optional": True},
            "end_chapter": {"type": "integer", "description": "结束章节号（含），不填到最后", "optional": True},
        },
    },
    # ------------------------------------------------------------------
    # Phase 4 三段式 propose / accept / regenerate 工具
    # ------------------------------------------------------------------
    {
        "name": "propose_project_setup",
        "description": "为一句灵感生成立项草案（genre/theme/style/target_words 等，不落盘）。返回 proposal JSON 供用户审阅。",
        "parameters": {
            "inspiration": {"type": "string", "description": "灵感文本，如 '少年修炼逆天改命'"},
            "hints": {"type": "object", "description": "可选覆盖字段 {genre/theme/target_words/style_name/narrative_template/target_length_class}", "optional": True},
        },
    },
    {
        "name": "propose_synopsis",
        "description": "为当前小说项目生成主线故事骨架草案（3-5 句 + 结构化 main_storyline），不落盘。",
        "parameters": {},
    },
    {
        "name": "propose_main_outline",
        "description": "为当前小说项目生成三层大纲草案（outline + style_name + style_bible），不落盘。",
        "parameters": {
            "custom_ideas": {"type": "string", "description": "作者额外要求（可选）", "optional": True},
        },
    },
    {
        "name": "propose_characters",
        "description": "为当前小说项目生成主角 + 核心配角草案，不落盘。",
        "parameters": {
            "synopsis": {"type": "string", "description": "可选上下文 synopsis（默认从 novel.json 读）", "optional": True},
        },
    },
    {
        "name": "propose_world_setting",
        "description": "为当前小说项目生成世界观 + 力量体系草案，不落盘。",
        "parameters": {
            "synopsis": {"type": "string", "description": "可选上下文 synopsis", "optional": True},
        },
    },
    {
        "name": "propose_story_arcs",
        "description": "为当前小说项目生成跨卷大弧线草案，不落盘。",
        "parameters": {},
    },
    {
        "name": "propose_volume_breakdown",
        "description": "为当前小说项目生成全书卷骨架草案，不落盘。",
        "parameters": {
            "synopsis": {"type": "string", "description": "可选上下文 synopsis", "optional": True},
        },
    },
    {
        "name": "propose_volume_outline",
        "description": "为指定卷生成单卷 N 章细纲草案（含 chapter_type 分布 + 伏笔规划），不落盘。",
        "parameters": {
            "volume_number": {"type": "integer", "description": "要规划的卷号（从 1 开始）"},
        },
    },
    {
        "name": "propose_chapter_brief",
        "description": "为指定章节从 Ledger 实时重建 chapter_brief 草案（不落盘）。替代 [DEPRECATED] plan_chapters。",
        "parameters": {
            "chapter_number": {"type": "integer", "description": "章节号"},
        },
    },
    {
        "name": "accept_proposal",
        "description": "确认落盘一个 propose_* 返回的草案到 novel.json。幂等：同 proposal_id 重复 accept 返回 already_accepted。",
        "parameters": {
            "proposal_id": {"type": "string", "description": "propose_* 返回的 proposal_id"},
            "proposal_type": {"type": "string", "description": "类型: project_setup/synopsis/main_outline/characters/world_setting/story_arcs/volume_breakdown/volume_outline/chapter_brief"},
            "data": {"type": "object", "description": "草案数据（可被用户编辑后回传）"},
        },
    },
    {
        "name": "regenerate_section",
        "description": "对不满意的骨架段落重新生成草案（同 propose_* 但带作者 hints）。返回新 proposal_id。",
        "parameters": {
            "section": {"type": "string", "description": "段落: synopsis/characters/world_setting/story_arcs/volume_breakdown/main_outline/volume_outline"},
            "hints": {"type": "string", "description": "哪里不满意、想要什么"},
            "volume_number": {"type": "integer", "description": "卷号（仅 volume_outline 需要）", "optional": True},
        },
    },
]


def _tools_description() -> str:
    """Format tools for the system prompt."""
    lines = []
    for t in TOOLS:
        params = ", ".join(
            f'{k}: {v["type"]}' + (" (可选)" if v.get("optional") else "")
            for k, v in t.get("parameters", {}).items()
        )
        lines.append(f'- {t["name"]}({params}): {t["description"]}')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

class AgentToolExecutor:
    """Executes tool calls against the novel pipeline."""

    def __init__(self, workspace: str, novel_id: str):
        self.workspace = workspace
        self.novel_id = novel_id
        self._project_path = str(Path(workspace) / "novels" / novel_id)
        self._cached_structured_db: Any = None

    def execute(self, tool_name: str, args: dict) -> dict:
        """Execute a tool and return the result dict.

        Retries once on transient errors (network, API failures).
        """
        method = getattr(self, f"_tool_{tool_name}", None)
        if not method:
            return {"error": f"Unknown tool: {tool_name}"}

        last_err = None
        for attempt in range(2):  # 1 retry
            try:
                return method(**args)
            except Exception as e:
                last_err = e
                err_msg = str(e).lower()
                is_transient = any(k in err_msg for k in (
                    "connection", "timeout", "rate", "503", "502", "429",
                    "network", "reset", "refused",
                ))
                if attempt == 0 and is_transient:
                    import time
                    log.warning("Tool %s transient error, retrying: %s", tool_name, e)
                    time.sleep(2)
                    continue
                log.exception("Tool %s failed", tool_name)
                return {"error": str(e)}
        log.exception("Tool %s failed after retry", tool_name)
        return {"error": str(last_err)}

    def close(self) -> None:
        """Release cached resources (e.g. SQLite connections)."""
        if self._cached_structured_db is not None:
            try:
                self._cached_structured_db.close()
            except Exception:
                pass
            self._cached_structured_db = None

    def _tool_read_chapter(self, chapter_number: int) -> dict:
        from src.novel.storage.file_manager import FileManager
        fm = FileManager(self.workspace)
        ch = fm.load_chapter(self.novel_id, chapter_number)
        if not ch:
            return {"error": f"章节 {chapter_number} 不存在"}
        text = ch.get("full_text", "")
        if not text:
            text = fm.load_chapter_text(self.novel_id, chapter_number) or ""
        return {
            "chapter_number": chapter_number,
            "title": ch.get("title", ""),
            "word_count": ch.get("word_count", 0),
            "text": text[:3000],  # Limit for context
            "text_truncated": len(text) > 3000,
        }

    def _tool_edit_setting(self, instruction: str, effective_from_chapter: int | None = None) -> dict:
        from src.novel.services.edit_service import NovelEditService
        svc = NovelEditService(workspace=self.workspace)
        result = svc.edit(
            project_path=self._project_path,
            instruction=instruction,
            effective_from_chapter=effective_from_chapter,
        )
        return {
            "status": result.status,
            "change_type": result.change_type,
            "entity_type": result.entity_type,
            "old_value": str(result.old_value)[:500] if result.old_value else None,
            "new_value": str(result.new_value)[:500] if result.new_value else None,
            "reasoning": result.reasoning,
        }

    def _tool_rewrite_chapter(self, feedback_text: str, chapter_number: int) -> dict:
        # Guard: refuse to rewrite published chapters
        from src.novel.storage.file_manager import FileManager
        fm = FileManager(self.workspace)
        novel_data = fm.load_novel(self.novel_id)
        if novel_data:
            published = set(novel_data.get("published_chapters", []))
            if chapter_number in published:
                return {
                    "error": f"第{chapter_number}章已发布，不能自动重写。"
                    "如需修改已发布章节，请先取消发布（publish_chapters），或手动编辑。",
                    "status": "refused",
                    "reason": "chapter_published",
                }

        from src.novel.pipeline import NovelPipeline
        pipe = NovelPipeline(workspace=self.workspace)
        result = pipe.apply_feedback(
            project_path=self._project_path,
            feedback_text=feedback_text,
            chapter_number=chapter_number,
            dry_run=False,
        )
        analysis = result.get("analysis", {})
        return {
            "status": "completed",
            "chapters_rewritten": result.get("rewritten_chapters", []),
            "feedback_type": analysis.get("feedback_type", ""),
        }

    def _tool_generate_chapters(self, num_chapters: int = 1, start_chapter: int | None = None) -> dict:
        """Generate new chapters using the full pipeline."""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        # Cap num_chapters to prevent very long runs
        num_chapters = max(1, min(num_chapters, 10))

        pipe = NovelPipeline(workspace=self.workspace)
        fm = FileManager(self.workspace)

        # Auto-detect start chapter
        if start_chapter is None:
            completed = fm.list_chapters(self.novel_id)
            start_chapter = (max(completed) + 1) if completed else 1

        end_chapter = start_chapter + num_chapters - 1

        try:
            result = pipe.generate_chapters(
                project_path=self._project_path,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                silent=True,
            )

            generated = result.get("chapters_generated", [])
            errors = result.get("errors", [])

            summary: dict[str, Any] = {
                "success": True,
                "chapters_generated": generated,
                "total_generated": len(generated),
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
            }

            if errors:
                summary["warnings"] = [e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in errors[:3]]

            # Include brief quality info if available
            debt_stats = result.get("debt_statistics")
            if debt_stats:
                summary["debt_statistics"] = debt_stats

            return summary
        except Exception as exc:
            return {
                "success": False,
                "error": f"章节生成失败: {exc}",
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
            }

    def _tool_resize_novel(self, new_total: int) -> dict:
        from src.novel.pipeline import NovelPipeline
        pipe = NovelPipeline(workspace=self.workspace)
        return pipe.resize_novel(self._project_path, new_total)

    def _tool_publish_chapters(self, chapters: list, published: bool = True) -> dict:
        from src.novel.storage.file_manager import FileManager
        fm = FileManager(self.workspace)
        data = fm.load_novel(self.novel_id)
        if not data:
            return {"error": f"小说不存在: {self.novel_id}"}
        pub_set = set(data.get("published_chapters", []))
        for ch in chapters:
            if published:
                pub_set.add(ch)
            else:
                pub_set.discard(ch)
        data["published_chapters"] = sorted(pub_set)
        fm.save_novel(self.novel_id, data)
        return {"published_chapters": data["published_chapters"]}

    def _tool_proofread_chapter(self, chapter_number: int) -> dict:
        from src.novel.pipeline import NovelPipeline
        pipe = NovelPipeline(workspace=self.workspace)
        result = pipe.proofread_chapter(self._project_path, chapter_number)
        # proofread_chapter returns list[dict] directly, not a dict with "issues" key
        issues = result if isinstance(result, list) else result.get("issues", [])
        return {
            "chapter_number": chapter_number,
            "total_issues": len(issues),
            "issues": issues[:10],  # Limit
        }

    def _tool_get_novel_info(self) -> dict:
        from src.novel.storage.file_manager import FileManager
        fm = FileManager(self.workspace)
        data = fm.load_novel(self.novel_id)
        if not data:
            return {"error": f"小说不存在: {self.novel_id}"}
        outline = data.get("outline", {})
        chapters = outline.get("chapters", [])
        characters = data.get("characters", [])
        return {
            "title": data.get("title", ""),
            "genre": data.get("genre", ""),
            "status": data.get("status", ""),
            "total_chapters": len(chapters),
            "current_chapter": data.get("current_chapter", 0),
            "target_words": data.get("target_words", 0),
            "published_chapters": data.get("published_chapters", []),
            "characters": [{"name": c.get("name"), "role": c.get("role")} for c in characters[:15]],
            "synopsis": data.get("synopsis", "")[:500],
        }

    def _tool_search_chapters(self, keyword: str) -> dict:
        from src.novel.storage.file_manager import FileManager
        fm = FileManager(self.workspace)
        results = []
        chapters_dir = Path(self.workspace) / "novels" / self.novel_id / "chapters"
        if chapters_dir.exists():
            for p in sorted(chapters_dir.glob("chapter_*.json")):
                try:
                    ch = json.loads(p.read_text(encoding="utf-8"))
                    text = ch.get("full_text", "")
                    if not text:
                        txt_path = p.with_suffix(".txt")
                        if txt_path.exists():
                            text = txt_path.read_text(encoding="utf-8")
                    if keyword in text:
                        # Find context around keyword
                        idx = text.index(keyword)
                        start = max(0, idx - 50)
                        end = min(len(text), idx + len(keyword) + 50)
                        num = int(p.stem.split("_")[1])
                        results.append({
                            "chapter_number": num,
                            "title": ch.get("title", ""),
                            "context": f"...{text[start:end]}...",
                        })
                except Exception:
                    continue
        return {"keyword": keyword, "matches": results[:20]}

    def _tool_reply_to_user(self, message: str) -> dict:
        return {"reply": message}

    # ------------------------------------------------------------------
    # Narrative control helpers
    # ------------------------------------------------------------------

    def _get_obligation_tracker(self):
        """Load or create an ObligationTracker for the current novel.

        Uses the cached StructuredDB to avoid leaking SQLite connections.

        Returns ObligationTracker instance, or None if the database
        cannot be initialized.
        """
        try:
            from src.novel.services.obligation_tracker import ObligationTracker

            db = self._get_structured_db()
            if db is None:
                # Novel created before narrative features — use in-memory
                return ObligationTracker(db=None)
            return ObligationTracker(db=db)
        except Exception as exc:
            log.warning("Failed to load ObligationTracker: %s", exc)
            return None

    def _get_structured_db(self):
        """Load StructuredDB for the current novel, or None.

        Caches the instance on self to avoid creating (and leaking) a new
        SQLite connection on every call.
        """
        if self._cached_structured_db is not None:
            return self._cached_structured_db
        try:
            from src.novel.storage.structured_db import StructuredDB

            db_path = Path(self._project_path) / "memory.db"
            if not db_path.exists():
                return None
            self._cached_structured_db = StructuredDB(db_path)
            return self._cached_structured_db
        except Exception as exc:
            log.warning("Failed to load StructuredDB: %s", exc)
            return None

    def _get_outline(self) -> dict:
        """Load outline dict from novel.json."""
        try:
            novel_json = Path(self._project_path) / "novel.json"
            if novel_json.exists():
                data = json.loads(novel_json.read_text("utf-8"))
                return data.get("outline", {})
        except Exception as exc:
            log.warning("Failed to load outline: %s", exc)
        return {}

    def _get_knowledge_graph(self):
        """Load KnowledgeGraph for the current novel, or empty one."""
        try:
            from src.novel.storage.knowledge_graph import KnowledgeGraph

            graph_json = Path(self._project_path) / "graph.json"
            graph_pkl = Path(self._project_path) / "graph.pkl"
            if graph_json.exists():
                return KnowledgeGraph.load(str(graph_json))
            elif graph_pkl.exists():
                return KnowledgeGraph.load(str(graph_pkl))
            return KnowledgeGraph()
        except Exception as exc:
            log.warning("Failed to load KnowledgeGraph: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Narrative control tools
    # ------------------------------------------------------------------

    def _tool_get_narrative_debts(self, status: str = "all", chapter: int | None = None) -> dict:
        tracker = self._get_obligation_tracker()
        if tracker is None:
            return {"error": "叙事债务系统未初始化", "debts": []}

        # Get all debts — use query_debts on DB, or iterate mem store
        if tracker._mem_store is not None:
            all_debts = list(tracker._mem_store.values())
        elif tracker.db is not None:
            all_debts = tracker.db.query_debts()
        else:
            all_debts = []

        # Filter by status
        if status != "all":
            all_debts = [d for d in all_debts if d.get("status") == status]

        # Filter by chapter (source or target)
        if chapter is not None:
            filtered = []
            for d in all_debts:
                if d.get("source_chapter") == chapter:
                    filtered.append(d)
                elif d.get("target_chapter") == chapter:
                    filtered.append(d)
            all_debts = filtered

        stats = tracker.get_debt_statistics()

        # Truncate for LLM context — serialize-safe copy
        safe_debts = []
        for d in all_debts[:20]:
            safe_debts.append({
                "debt_id": d.get("debt_id", ""),
                "source_chapter": d.get("source_chapter"),
                "type": d.get("type", ""),
                "description": str(d.get("description", ""))[:200],
                "status": d.get("status", ""),
                "urgency_level": d.get("urgency_level", "normal"),
                "target_chapter": d.get("target_chapter"),
            })

        return {
            "total": len(all_debts),
            "statistics": stats,
            "debts": safe_debts,
        }

    def _tool_manage_debt(
        self,
        action: str,
        debt_id: str | None = None,
        chapter_number: int | None = None,
        description: str | None = None,
        source_chapter: int | None = None,
        debt_type: str | None = None,
    ) -> dict:
        tracker = self._get_obligation_tracker()
        if tracker is None:
            return {"error": "叙事债务系统未初始化"}

        if action == "fulfill":
            if not debt_id:
                return {"error": "fulfill 操作需要 debt_id"}
            # Resolve chapter number: explicit arg > novel current_chapter > 0
            ch_num = chapter_number
            if ch_num is None:
                try:
                    novel_json = Path(self._project_path) / "novel.json"
                    if novel_json.exists():
                        data = json.loads(novel_json.read_text("utf-8"))
                        ch_num = data.get("current_chapter", 0)
                except Exception:
                    ch_num = 0
            if ch_num is None:
                ch_num = 0
            tracker.mark_debt_fulfilled(debt_id, chapter_num=ch_num, note="Agent Chat 手动标记")
            return {"status": "fulfilled", "debt_id": debt_id, "chapter_num": ch_num}

        elif action == "add":
            if not description or source_chapter is None:
                return {"error": "add 操作需要 description 和 source_chapter"}
            import uuid
            new_id = f"debt_{source_chapter}_chat_{uuid.uuid4().hex[:8]}"
            tracker.add_debt(
                debt_id=new_id,
                source_chapter=source_chapter,
                debt_type=debt_type or "pay_within_3",
                description=description,
            )
            return {"status": "added", "debt_id": new_id, "description": description}

        elif action == "escalate":
            if not debt_id:
                return {"error": "escalate 操作需要 debt_id"}
            # Escalate by re-running escalation for a high chapter number
            # to trigger overdue detection
            escalated = tracker.escalate_debts(current_chapter=9999)
            return {"status": "escalated", "total_escalated": escalated}

        else:
            return {"error": f"未知操作: {action}，支持: fulfill/add/escalate"}

    def _tool_get_story_arcs(self, volume: int | None = None) -> dict:
        db = self._get_structured_db()

        arcs: list[dict] = []

        # Try DB first
        if db is not None:
            try:
                volume_id = str(volume) if volume is not None else None
                rows = db.query_story_units(volume_id=volume_id)
                for row in rows:
                    chapters_raw = row.get("chapters", "[]")
                    if isinstance(chapters_raw, str):
                        try:
                            chapters_list = json.loads(chapters_raw)
                        except (json.JSONDecodeError, TypeError):
                            chapters_list = []
                    else:
                        chapters_list = chapters_raw
                    arcs.append({
                        "arc_id": row.get("arc_id", ""),
                        "volume_id": row.get("volume_id", ""),
                        "name": row.get("name", ""),
                        "chapters": chapters_list,
                        "phase": row.get("phase", ""),
                        "status": row.get("status", ""),
                        "completion_rate": row.get("completion_rate", 0.0),
                        "hook": str(row.get("hook", ""))[:100],
                        "residual_question": str(row.get("residual_question", ""))[:100],
                    })
            except Exception as exc:
                log.warning("Failed to query story_units from DB: %s", exc)

        # Also try arcs.json file
        if not arcs:
            arcs_path = Path(self._project_path) / "arcs.json"
            if arcs_path.exists():
                try:
                    with open(arcs_path, encoding="utf-8") as f:
                        file_arcs = json.load(f)
                    if isinstance(file_arcs, list):
                        for arc in file_arcs:
                            if volume is not None:
                                vol_id = arc.get("volume_id")
                                if vol_id is not None and int(vol_id) != volume:
                                    continue
                            arcs.append({
                                "arc_id": arc.get("arc_id", ""),
                                "volume_id": arc.get("volume_id", ""),
                                "name": arc.get("name", ""),
                                "chapters": arc.get("chapters", []),
                                "phase": arc.get("phase", ""),
                                "status": arc.get("status", ""),
                                "completion_rate": arc.get("completion_rate", 0.0),
                                "hook": str(arc.get("hook", ""))[:100],
                                "residual_question": str(arc.get("residual_question", ""))[:100],
                            })
                except Exception as exc:
                    log.warning("Failed to load arcs.json: %s", exc)

        # Also check novel outline for story_units
        if not arcs:
            from src.novel.storage.file_manager import FileManager
            fm = FileManager(self.workspace)
            novel_data = fm.load_novel(self.novel_id)
            if novel_data:
                outline = novel_data.get("outline", {})
                story_units = outline.get("story_units", [])
                for su in story_units:
                    if volume is not None:
                        vol = su.get("volume_id")
                        if vol is not None and int(vol) != volume:
                            continue
                    arcs.append({
                        "arc_id": su.get("arc_id", ""),
                        "volume_id": su.get("volume_id", ""),
                        "name": su.get("name", ""),
                        "chapters": su.get("chapters", []),
                        "phase": su.get("phase", ""),
                        "status": su.get("status", "planning"),
                        "completion_rate": su.get("completion_rate", 0.0),
                        "hook": str(su.get("hook", ""))[:100],
                        "residual_question": str(su.get("residual_question", ""))[:100],
                    })

        return {
            "total": len(arcs),
            "arcs": arcs[:20],  # Limit for context
        }

    def _tool_get_chapter_brief(self, chapter_number: int) -> dict:
        from src.novel.storage.file_manager import FileManager
        fm = FileManager(self.workspace)
        novel_data = fm.load_novel(self.novel_id)
        if not novel_data:
            return {"error": "小说不存在"}

        outline = novel_data.get("outline", {})
        chapters_outline = outline.get("chapters", [])

        # Find chapter brief in outline
        chapter_brief = None
        chapter_outline = None
        for ch in chapters_outline:
            if ch.get("chapter_number") == chapter_number:
                chapter_outline = ch
                chapter_brief = ch.get("chapter_brief", {})
                break

        if chapter_outline is None:
            return {"error": f"章节 {chapter_number} 不在大纲中"}

        result: dict = {
            "chapter_number": chapter_number,
            "title": chapter_outline.get("title", ""),
            "chapter_brief": chapter_brief or {},
        }

        # If chapter text exists, try to validate
        ch_data = fm.load_chapter(self.novel_id, chapter_number)
        if ch_data and chapter_brief:
            text = ch_data.get("full_text", "")
            if not text:
                text = fm.load_chapter_text(self.novel_id, chapter_number) or ""
            if text:
                result["has_text"] = True
                result["word_count"] = len(text)
                # Simple check without LLM — just report brief items
                brief_items = []
                for key, val in chapter_brief.items():
                    if val:
                        brief_items.append({"item": key, "expected": str(val)[:200]})
                result["brief_items"] = brief_items
            else:
                result["has_text"] = False
        else:
            result["has_text"] = ch_data is not None

        return result

    def _tool_get_knowledge_graph(self, character: str | None = None) -> dict:
        kg = self._get_knowledge_graph()
        if kg is None:
            return {"error": "知识图谱未初始化", "nodes": [], "edges": []}

        if character:
            # Find the character node by name
            char_id = None
            for node_id, attrs in kg.graph.nodes(data=True):
                if attrs.get("name") == character or node_id == character:
                    char_id = node_id
                    break

            if char_id is None:
                return {
                    "error": f"未找到角色: {character}",
                    "nodes": [],
                    "edges": [],
                }

            # Get relationships for this character
            rels = kg.get_relationships(char_id)
            node_attrs = kg.get_node(char_id) or {}

            # Collect related nodes
            related_ids = set()
            for r in rels:
                related_ids.add(r.get("source", ""))
                related_ids.add(r.get("target", ""))
            related_ids.discard(char_id)

            nodes = [{"id": char_id, **node_attrs}]
            for rid in list(related_ids)[:20]:
                n = kg.get_node(rid)
                if n:
                    nodes.append({"id": rid, **n})

            edges = []
            for r in rels[:20]:
                edges.append({
                    "source": r.get("source", ""),
                    "target": r.get("target", ""),
                    "type": r.get("type", ""),
                    "intensity": r.get("intensity", 0),
                    "chapter": r.get("chapter", 0),
                })

            return {
                "character": character,
                "nodes": nodes,
                "edges": edges,
            }

        # Return full graph summary
        all_characters = kg.get_nodes_by_type("character")
        all_factions = kg.get_nodes_by_type("faction")
        all_locations = kg.get_nodes_by_type("location")

        # Collect all edges
        edges = []
        for u, v, _key, data in kg.graph.edges(data=True, keys=True):
            edges.append({
                "source": u,
                "target": v,
                "type": data.get("type", data.get("edge_type", "")),
                "chapter": data.get("chapter", 0),
            })

        return {
            "characters": [{"id": c["id"], "name": c.get("name", "")} for c in all_characters[:30]],
            "factions": [{"id": f["id"], "name": f.get("name", "")} for f in all_factions[:10]],
            "locations": [{"id": loc["id"], "name": loc.get("name", "")} for loc in all_locations[:10]],
            "total_edges": len(edges),
            "edges": edges[:30],
        }

    def _tool_get_narrative_overview(self) -> dict:
        overview: dict = {}

        # 1. Debt statistics
        tracker = self._get_obligation_tracker()
        if tracker is not None:
            stats = tracker.get_debt_statistics()
            overview["debt_statistics"] = stats
        else:
            overview["debt_statistics"] = {
                "pending_count": 0, "fulfilled_count": 0,
                "overdue_count": 0, "abandoned_count": 0,
            }

        # 2. Arc progress
        arcs_result = self._tool_get_story_arcs()
        arcs = arcs_result.get("arcs", [])
        if arcs:
            completed = sum(1 for a in arcs if a.get("status") == "completed")
            in_progress = sum(1 for a in arcs if a.get("status") in ("active", "in_progress"))
            planning = sum(1 for a in arcs if a.get("status") == "planning")
            overview["arc_progress"] = {
                "total": len(arcs),
                "completed": completed,
                "in_progress": in_progress,
                "planning": planning,
            }
        else:
            overview["arc_progress"] = {"total": 0, "completed": 0, "in_progress": 0, "planning": 0}

        # 3. Novel basic info
        from src.novel.storage.file_manager import FileManager
        fm = FileManager(self.workspace)
        novel_data = fm.load_novel(self.novel_id)
        if novel_data:
            outline = novel_data.get("outline", {})
            total_chapters = len(outline.get("chapters", []))
            current_chapter = novel_data.get("current_chapter", 0)
            overview["novel_progress"] = {
                "current_chapter": current_chapter,
                "total_chapters": total_chapters,
                "completion_pct": round(current_chapter / total_chapters * 100, 1) if total_chapters else 0,
            }
        else:
            overview["novel_progress"] = {"current_chapter": 0, "total_chapters": 0, "completion_pct": 0}

        # 4. Knowledge graph summary
        kg = self._get_knowledge_graph()
        if kg is not None:
            overview["knowledge_graph"] = {
                "total_nodes": kg.graph.number_of_nodes(),
                "total_edges": kg.graph.number_of_edges(),
                "characters": len(kg.get_nodes_by_type("character")),
            }
        else:
            overview["knowledge_graph"] = {"total_nodes": 0, "total_edges": 0, "characters": 0}

        return overview

    # NOTE: _tool_rebuild_narrative removed with NarrativeRebuildService
    # (architecture-rework-2026 Phase 0). See registry comment above.

    def _tool_get_volume_settlement(self, chapter_number: int = 1) -> dict:
        from src.novel.services.volume_settlement import VolumeSettlement

        db = self._get_structured_db()
        outline = self._get_outline()
        vs = VolumeSettlement(db=db, outline=outline)
        result = vs.get_settlement_brief(chapter_number)
        # Ensure JSON-serializable
        return json.loads(json.dumps(result, ensure_ascii=False, default=str))

    def _tool_get_arc_status(self) -> dict:
        from src.novel.services.volume_settlement import VolumeSettlement

        db = self._get_structured_db()
        outline = self._get_outline()
        vs = VolumeSettlement(db=db, outline=outline)
        arcs = vs._get_active_arcs()
        # Parse chapters JSON for display
        for arc in arcs:
            if isinstance(arc.get("chapters"), str):
                try:
                    arc["chapters"] = json.loads(arc["chapters"])
                except (json.JSONDecodeError, TypeError):
                    arc["chapters"] = []
        return {"total": len(arcs), "arcs": arcs[:20]}

    def _tool_plan_chapters(self, num_chapters: int = 4, start_chapter: int | None = None) -> dict:
        """Plan chapter outlines without generating text."""
        from src.novel.pipeline import NovelPipeline
        from src.novel.storage.file_manager import FileManager

        pipe = NovelPipeline(workspace=self.workspace)
        fm = FileManager(self.workspace)

        if start_chapter is None:
            completed = fm.list_chapters(self.novel_id)
            start_chapter = (max(completed) + 1) if completed else 1

        end_chapter = start_chapter + min(num_chapters, 10) - 1
        project_path = str(Path(self.workspace) / "novels" / self.novel_id)

        try:
            return pipe.plan_chapters(
                project_path=project_path,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )
        except Exception as exc:
            return {"error": f"大纲规划失败: {exc}"}

    def _tool_rename_chapter(self, chapter_number: int, new_title: str) -> dict:
        """Rename a chapter's title without touching its content."""
        from src.novel.storage.file_manager import FileManager

        novel_dir = Path(self.workspace) / "novels" / self.novel_id
        json_path = novel_dir / "chapters" / f"chapter_{chapter_number:03d}.json"

        if not json_path.exists():
            return {"error": f"第{chapter_number}章不存在"}

        # Update title in chapter json
        data = json.loads(json_path.read_text(encoding="utf-8"))
        old_title = data.get("title", f"第{chapter_number}章")
        data["title"] = new_title
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Also update outline if it exists
        try:
            fm = FileManager(self.workspace)
            novel_data = fm.load_novel(self.novel_id) or {}
            outline = novel_data.get("outline", {})
            for ch in outline.get("chapters", []):
                if ch.get("chapter_number") == chapter_number:
                    ch["title"] = new_title
                    break
            fm.save_novel(self.novel_id, novel_data)
        except Exception:
            pass

        return {
            "success": True,
            "chapter_number": chapter_number,
            "old_title": old_title,
            "new_title": new_title,
        }

    # ------------------------------------------------------------------
    # Smart-editor extras (changelog / rollback / impact / batch)
    # ------------------------------------------------------------------

    def _tool_get_change_history(
        self, limit: int = 20, change_type: str | None = None
    ) -> dict:
        from src.novel.services.edit_service import NovelEditService

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(limit, 100))

        svc = NovelEditService(workspace=self.workspace)
        entries = svc.get_history(
            project_path=self._project_path,
            limit=limit,
            change_type=change_type,
        )

        # Truncate large value blobs for LLM context
        safe = []
        for e in entries:
            safe.append({
                "change_id": e.get("change_id", ""),
                "timestamp": e.get("timestamp", ""),
                "change_type": e.get("change_type", ""),
                "entity_type": e.get("entity_type", ""),
                "entity_id": e.get("entity_id"),
                "instruction": (e.get("instruction") or "")[:200] if e.get("instruction") else None,
                "effective_from_chapter": e.get("effective_from_chapter"),
                "reverted_change_id": e.get("reverted_change_id"),
                "old_value_preview": str(e.get("old_value"))[:200] if e.get("old_value") is not None else None,
                "new_value_preview": str(e.get("new_value"))[:200] if e.get("new_value") is not None else None,
            })
        return {"total": len(safe), "changes": safe}

    def _tool_rollback_change(self, change_id: str, force: bool = False) -> dict:
        from src.novel.services.edit_service import NovelEditService

        if not change_id or not isinstance(change_id, str):
            return {"error": "change_id 必填"}

        svc = NovelEditService(workspace=self.workspace)
        result = svc.rollback(
            project_path=self._project_path,
            change_id=change_id,
            force=bool(force),
        )
        # H1: rollback 改了 novel.json 与 changelog；丢弃缓存的 SQLite 句柄
        # 防止后续工具读到陈旧的角色快照/债务状态
        if result.status == "success":
            self.close()
        return {
            "status": result.status,
            "rollback_change_id": result.change_id,
            "reverted_change_id": change_id,
            "entity_type": result.entity_type,
            "entity_id": result.entity_id,
            "error": result.error,
            "reasoning": result.reasoning,
        }

    def _tool_analyze_change_impact(
        self,
        change_type: str,
        entity_type: str,
        effective_from_chapter: int,
        entity_id: str | None = None,
        details: dict | None = None,
    ) -> dict:
        from src.novel.services.impact_analyzer import (
            ChangeRequest,
            ImpactAnalyzer,
        )
        from src.novel.storage.file_manager import FileManager

        try:
            effective_from_chapter = int(effective_from_chapter)
        except (TypeError, ValueError):
            return {"error": "effective_from_chapter 必须是 >=1 的整数"}
        if effective_from_chapter < 1:
            return {"error": "effective_from_chapter 必须 >=1"}

        fm = FileManager(self.workspace)
        novel_data = fm.load_novel(self.novel_id)
        if novel_data is None:
            return {"error": f"小说不存在: {self.novel_id}"}

        try:
            req = ChangeRequest(
                change_type=change_type,
                entity_type=entity_type,
                entity_id=entity_id,
                effective_from_chapter=effective_from_chapter,
                details=details or {},
            )
        except Exception as exc:
            return {"error": f"参数无效: {exc}"}

        result = ImpactAnalyzer().analyze(novel_data, req)
        return {
            "severity": result.severity,
            "summary": result.summary,
            "affected_chapters": result.affected_chapters[:30],
            "conflicts": result.conflicts[:20],
            "warnings": result.warnings[:20],
        }

    # H3: 单次批量编辑的 payload 体积上限（64 KB JSON），防止 LLM 误塞 MB 级数据
    _BATCH_EDIT_MAX_PAYLOAD_BYTES = 64 * 1024

    def _tool_batch_edit_settings(
        self,
        changes: list,
        dry_run: bool = False,
        stop_on_failure: bool = False,
    ) -> dict:
        from src.novel.services.edit_service import NovelEditService

        if not isinstance(changes, list) or not changes:
            return {"error": "changes 必须是非空列表"}
        # Cap to avoid runaway tool calls
        if len(changes) > 50:
            return {"error": f"changes 数量超过上限 50（实际 {len(changes)}）"}
        # H3: payload 体积上限
        try:
            payload_bytes = len(
                json.dumps(changes, ensure_ascii=False).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            return {"error": f"changes 不是合法 JSON 结构: {exc}"}
        if payload_bytes > self._BATCH_EDIT_MAX_PAYLOAD_BYTES:
            return {
                "error": (
                    f"changes 体积 {payload_bytes} 字节超过上限 "
                    f"{self._BATCH_EDIT_MAX_PAYLOAD_BYTES}"
                )
            }

        svc = NovelEditService(workspace=self.workspace)
        results = svc.batch_edit(
            project_path=self._project_path,
            changes=changes,
            dry_run=bool(dry_run),
            stop_on_failure=bool(stop_on_failure),
        )

        # H2: summary 动态聚合所有出现过的状态，避免 EditResult 扩展新状态时漏报
        summary: dict[str, int] = {}
        items = []
        for r in results:
            summary[r.status] = summary.get(r.status, 0) + 1
            items.append({
                "change_id": r.change_id,
                "status": r.status,
                "change_type": r.change_type,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "effective_from_chapter": r.effective_from_chapter,
                "error": r.error,
            })

        success_count = summary.get("success", 0)
        failed_count = summary.get("failed", 0)
        partial_failure = success_count > 0 and failed_count > 0

        # H1: 真实落盘且至少有一条成功 → 丢弃 SQLite 缓存
        if not dry_run and success_count > 0:
            self.close()

        return {
            "dry_run": bool(dry_run),
            "total": len(results),
            "summary": summary,
            "partial_failure": partial_failure,
            "results": items,
        }

    def _tool_get_foreshadowing_graph(
        self, current_chapter: int | None = None, threshold: int = 10
    ) -> dict:
        try:
            threshold = int(threshold)
        except (TypeError, ValueError):
            threshold = 10
        threshold = max(1, threshold)

        # Resolve current_chapter from novel.json if not given
        if current_chapter is None:
            try:
                novel_json = Path(self._project_path) / "novel.json"
                if novel_json.exists():
                    data = json.loads(novel_json.read_text("utf-8"))
                    current_chapter = int(data.get("current_chapter", 0) or 0)
            except Exception:
                current_chapter = 0
        try:
            current_chapter = int(current_chapter or 0)
        except (TypeError, ValueError):
            current_chapter = 0
        # H3: 拒绝负数章节，避免 is_forgotten 计算异常
        current_chapter = max(0, current_chapter)

        graph = self._get_knowledge_graph()
        if graph is None:
            return {"error": "知识图谱未初始化", "stats": {}, "pending": []}

        try:
            stats = graph.get_foreshadowing_stats()
        except Exception as exc:
            log.warning("get_foreshadowing_stats failed: %s", exc)
            stats = {}

        pending: list[dict] = []
        try:
            raw_pending = graph.get_pending_foreshadowings(current_chapter)
            for f in raw_pending[:30]:
                pending.append({
                    "foreshadowing_id": f.get("foreshadowing_id", ""),
                    "content": str(f.get("content", ""))[:200],
                    "planted_chapter": f.get("planted_chapter"),
                    "target_chapter": f.get("target_chapter"),
                    "chapters_since_plant": f.get("chapters_since_plant"),
                    "last_mentioned_chapter": f.get("last_mentioned_chapter"),
                    "is_forgotten": bool(f.get("is_forgotten")),
                })
        except Exception as exc:
            log.warning("get_pending_foreshadowings failed: %s", exc)

        forgotten_count = sum(1 for f in pending if f["is_forgotten"])
        return {
            "current_chapter": current_chapter,
            "threshold": threshold,
            "stats": stats,
            "forgotten_in_pending": forgotten_count,
            "pending": pending,
        }

    # H4: 健康度仪表盘只对 LLM 暴露顶层指标，避免下钻明细把 token 吃光
    _HEALTH_TOPLEVEL_KEYS = (
        "overall_health_score",
        "foreshadowing_collection_rate",
        "foreshadowing_total",
        "foreshadowing_collected",
        "foreshadowing_forgotten",
        "milestone_completion_rate",
        "milestone_total",
        "milestone_completed",
        "milestone_overdue",
        "character_coverage",
        "character_total",
        "character_active",
        "entity_consistency_score",
        "entity_conflict_count",
        "debt_health",
        "debt_total",
        "debt_overdue",
    )

    # ------------------------------------------------------------------
    # Self-Refine / Reflexion tools
    # ------------------------------------------------------------------

    def _load_chapter_text(self, chapter_number: int) -> str | None:
        from src.novel.storage.file_manager import FileManager

        fm = FileManager(self.workspace)
        ch = fm.load_chapter(self.novel_id, chapter_number) or {}
        text = ch.get("full_text") or ""
        if not text:
            text = fm.load_chapter_text(self.novel_id, chapter_number) or ""
        return text or None

    def _llm_for_critic(self):
        """构造 critic/refine/reflexion 用的 LLM 客户端。"""
        from src.llm.llm_client import create_llm_client

        # 复用 novel.json 的 config，drop 掉 stale provider 用 auto-detect
        try:
            novel_json = Path(self._project_path) / "novel.json"
            if novel_json.exists():
                cfg = json.loads(novel_json.read_text("utf-8"))
                llm_cfg = (cfg.get("config", {}) or {}).get("llm", {}) or {}
            else:
                llm_cfg = {}
        except Exception:
            llm_cfg = {}
        return create_llm_client(llm_cfg)

    def _global_banned_phrases(self) -> list[str]:
        """读 ``NovelConfig.quality.ai_flavor_hard_ban``（**只取硬禁**）。

        软观察 watchlist 不参与 verifier，由 Reviewer 按场景判断。
        优先 ``config.yaml`` 用户配置；不可用时回退 schema 默认。
        """
        from src.novel.config import NovelConfig, load_novel_config

        try:
            cfg = load_novel_config(config_path="config.yaml")
        except Exception:
            cfg = NovelConfig()
        hard = list(cfg.quality.ai_flavor_hard_ban or [])
        if not hard:
            # 用户显式清空过 → 用 schema 默认，工具才有意义
            hard = list(NovelConfig().quality.ai_flavor_hard_ban)
        # 去重保留顺序
        seen: set[str] = set()
        result: list[str] = []
        for p in hard:
            if p and p not in seen:
                result.append(p)
                seen.add(p)
        return result

    def _global_watchlist(self) -> dict[str, int]:
        """读 ``NovelConfig.quality.ai_flavor_watchlist``。供 critic 用。"""
        from src.novel.config import NovelConfig, load_novel_config

        try:
            cfg = load_novel_config(config_path="config.yaml")
        except Exception:
            cfg = NovelConfig()
        wl = dict(cfg.quality.ai_flavor_watchlist or {})
        if not wl:
            wl = dict(NovelConfig().quality.ai_flavor_watchlist)
        return wl

    def _tool_verify_chapter(
        self,
        chapter_number: int,
        target_words: int | None = None,
        extra_banned: list | None = None,
    ) -> dict:
        from src.novel.services.chapter_verifier import ChapterVerifier

        text = self._load_chapter_text(chapter_number)
        if text is None:
            return {"error": f"章节 {chapter_number} 不存在或为空"}

        banned = list(self._global_banned_phrases())
        if extra_banned and isinstance(extra_banned, list):
            banned += [str(p) for p in extra_banned if p]

        # 查本章应兑现的债务和应回收的伏笔
        debts: list[dict] = []
        try:
            tracker = self._get_obligation_tracker()
            if tracker is not None:
                source = (
                    list(tracker._mem_store.values())
                    if tracker._mem_store is not None
                    else (tracker.db.query_debts() if tracker.db else [])
                )
                debts = [
                    d for d in source
                    if d.get("status") in ("pending", "overdue")
                    and (
                        d.get("source_chapter", 0) <= chapter_number
                    )
                ][:5]
        except Exception as exc:
            log.warning("verify_chapter: load debts failed: %s", exc)

        forsh: list[dict] = []
        try:
            graph = self._get_knowledge_graph()
            if graph is not None:
                forsh = [
                    f for f in graph.get_pending_foreshadowings(chapter_number)
                    if f.get("is_forgotten")
                ][:5]
        except Exception as exc:
            log.warning("verify_chapter: load foreshadowings failed: %s", exc)

        report = ChapterVerifier().verify(
            text,
            must_fulfill_debts=debts,
            must_collect_foreshadowings=forsh,
            banned_phrases=banned,
            target_words=target_words,
        )
        return {
            "chapter_number": chapter_number,
            "passed": report.passed,
            "word_count": report.word_count,
            "high_severity_count": report.high_severity_count,
            "failures": [
                {
                    "rule": f.rule,
                    "severity": f.severity,
                    "detail": f.detail[:300],
                }
                for f in report.failures[:20]
            ],
            "checked": {
                "debts": len(debts),
                "foreshadowings": len(forsh),
                "banned_phrases": len(banned),
                "target_words": target_words,
            },
        }

    def _tool_critique_chapter(self, chapter_number: int) -> dict:
        from src.novel.agents.reviewer import Reviewer
        from src.novel.storage.file_manager import FileManager

        text = self._load_chapter_text(chapter_number)
        if text is None:
            return {"error": f"章节 {chapter_number} 不存在或为空"}

        fm = FileManager(self.workspace)
        novel_data = fm.load_novel(self.novel_id) or {}
        outline_chs = (novel_data.get("outline") or {}).get("chapters") or []
        ch_outline = next(
            (c for c in outline_chs if c.get("chapter_number") == chapter_number),
            {},
        )
        prev_text = self._load_chapter_text(chapter_number - 1) or ""

        try:
            llm = self._llm_for_critic()
        except Exception as exc:
            return {"error": f"无可用 LLM: {exc}"}

        watchlist = self._global_watchlist()
        reviewer = Reviewer(llm, watchlist=watchlist or None)
        result = reviewer.review(
            text,
            chapter_number=chapter_number,
            chapter_title=ch_outline.get("title", ""),
            chapter_goal=ch_outline.get("goal", ""),
            previous_tail=prev_text[-500:] if prev_text else "",
        )
        return {
            "chapter_number": chapter_number,
            "need_rewrite": result.need_rewrite,
            "needs_refine": result.needs_refine,
            "high_severity_count": result.high_severity_count,
            "medium_severity_count": result.medium_severity_count,
            "strengths": result.strengths[:5],
            "issues": [
                {
                    "type": i.type,
                    "severity": i.severity,
                    "quote": i.quote,
                    "reason": i.reason,
                }
                for i in result.issues[:10]
            ],
            "specific_revisions": [
                {"target": r.target, "suggestion": r.suggestion}
                for r in result.specific_revisions[:8]
            ],
            "style_overuse_hits": result.style_overuse_hits[:15],
            "consistency_flags": [f.model_dump() for f in result.consistency_flags[:10]],
            "overall_assessment": result.overall_assessment[:500],
        }

    # Alias: new canonical name per Phase 2-β design
    def _tool_review_chapter(self, chapter_number: int) -> dict:
        return self._tool_critique_chapter(chapter_number)

    def _tool_refine_chapter(
        self,
        chapter_number: int,
        enable_critic: bool = True,
        **_legacy: Any,  # swallow deprecated max_verify_retries / max_refine_iters
    ) -> dict:
        """单轮审阅工具（Phase 0 档 4b：零自动重写）。

        出一份 ``RefineReport``（verifier + critic 结构化报告），**不改章节正文、
        不落盘**。作者读完报告若决定重写，显式调用 ``rewrite_chapter`` 工具。
        """
        from src.novel.agents.reviewer import Reviewer
        from src.novel.services.chapter_verifier import ChapterVerifier
        from src.novel.services.refine_loop import RefineConfig, run_refine_loop
        from src.novel.storage.file_manager import FileManager

        text = self._load_chapter_text(chapter_number)
        if text is None:
            return {"error": f"章节 {chapter_number} 不存在或为空"}

        fm = FileManager(self.workspace)
        novel_data = fm.load_novel(self.novel_id) or {}
        # 即使是单轮只读报告，发布章节我们也拒绝产生建议（保持既有契约）
        if chapter_number in set(novel_data.get("published_chapters") or []):
            return {
                "error": f"第{chapter_number}章已发布，不能 refine。请先取消发布。",
                "status": "refused",
            }

        outline_chs = (novel_data.get("outline") or {}).get("chapters") or []
        ch_outline = next(
            (c for c in outline_chs if c.get("chapter_number") == chapter_number),
            {},
        )
        prev_text = self._load_chapter_text(chapter_number - 1) or ""

        # critic 需要 LLM；verifier 不用。enable_critic=False 时允许缺失 LLM。
        llm = None
        if enable_critic:
            try:
                llm = self._llm_for_critic()
            except Exception as exc:
                return {"error": f"无可用 LLM: {exc}"}

        def _draft_fn() -> str:
            return text

        # Gather verify constraints (same as verify_chapter)
        banned = self._global_banned_phrases()
        debts: list[dict] = []
        try:
            tracker = self._get_obligation_tracker()
            if tracker is not None:
                source = (
                    list(tracker._mem_store.values())
                    if tracker._mem_store is not None
                    else (tracker.db.query_debts() if tracker.db else [])
                )
                debts = [
                    d for d in source
                    if d.get("status") in ("pending", "overdue")
                    and d.get("source_chapter", 0) <= chapter_number
                ][:3]
        except Exception:
            pass
        forsh: list[dict] = []
        try:
            graph = self._get_knowledge_graph()
            if graph is not None:
                forsh = [
                    f for f in graph.get_pending_foreshadowings(chapter_number)
                    if f.get("is_forgotten")
                ][:3]
        except Exception:
            pass

        watchlist = self._global_watchlist()
        critic = (
            Reviewer(llm, watchlist=watchlist or None)
            if (enable_critic and llm is not None)
            else None
        )
        config = RefineConfig(enable_critic=bool(enable_critic and critic is not None))

        trace = run_refine_loop(
            draft_fn=_draft_fn,
            verifier=ChapterVerifier(),
            critic=critic,
            must_fulfill_debts=debts,
            must_collect_foreshadowings=forsh,
            banned_phrases=banned,
            target_words=ch_outline.get("estimated_words"),
            prev_chapter_text=prev_text,
            chapter_number=chapter_number,
            chapter_title=ch_outline.get("title", ""),
            chapter_goal=ch_outline.get("goal", ""),
            config=config,
        )

        report = trace.report
        report_dict = report.model_dump() if report is not None else {}

        # 不落盘。保留几个高频字段便于调用者直接读取，不再有 refine_iterations
        # 概念（单轮固定，字段保留为 1 兼容老前端）。
        return {
            "chapter_number": chapter_number,
            "changed": False,
            "before_words": len(text),
            "after_words": len(text),
            "verify_passed": trace.verify_passed,
            "critic_passed": trace.critic_passed,
            "refine_iterations": 1,  # 兼容字段：单轮固定 1，不再代表重写次数
            "verify_attempts": len(trace.verify_attempts),
            "critique_attempts": len(trace.critique_attempts),
            "sanitize_actions": trace.sanitize_actions,
            "opening_duplicate_flagged": trace.opening_duplicate_flagged,
            "total_llm_calls": trace.total_llm_calls,
            "notes": trace.notes[-5:],
            "report": report_dict,
            "recommended_action": report_dict.get("recommended_action", "accept"),
        }

    def _tool_get_reflexion_log(
        self, start_chapter: int | None = None, end_chapter: int | None = None
    ) -> dict:
        from src.novel.services.reflexion_memory import ReflexionMemory

        memory = ReflexionMemory(self._project_path)
        all_entries = memory.get_all()

        if start_chapter is not None:
            try:
                start = int(start_chapter)
                all_entries = [e for e in all_entries if e.chapter_number >= start]
            except (TypeError, ValueError):
                pass
        if end_chapter is not None:
            try:
                end = int(end_chapter)
                all_entries = [e for e in all_entries if e.chapter_number <= end]
            except (TypeError, ValueError):
                pass

        return {
            "total": len(all_entries),
            "entries": [
                {
                    "chapter_number": e.chapter_number,
                    "chapter_type": e.chapter_type,
                    "what_worked": e.what_worked,
                    "what_failed": e.what_failed,
                    "lesson": e.lesson,
                    "next_action": e.next_action,
                    "user_edited": e.user_edited,
                    "created_at": e.created_at,
                }
                for e in all_entries[:50]
            ],
        }

    def _tool_get_health_dashboard(self) -> dict:
        from src.novel.pipeline import NovelPipeline

        pipe = NovelPipeline(workspace=self.workspace)
        try:
            report = pipe.get_health_report(self._project_path)
        except Exception as exc:
            return {"error": f"健康度计算失败: {exc}"}

        metrics = report.get("metrics", {}) or {}
        text = report.get("report", "") or ""

        # H4: 白名单顶层指标；其余下钻明细折叠
        top = {k: metrics[k] for k in self._HEALTH_TOPLEVEL_KEYS if k in metrics}
        details_truncated = any(k not in self._HEALTH_TOPLEVEL_KEYS for k in metrics)

        return {
            "overall_health_score": metrics.get("overall_health_score"),
            "metrics": top,
            "details_truncated": details_truncated,
            "report": text[:2000],
        }

    # ------------------------------------------------------------------
    # Phase 4 三段式 propose / accept / regenerate 工具
    # ------------------------------------------------------------------

    def _get_tool_facade(self):
        """Create a ``NovelToolFacade`` bound to this executor's workspace.

        Imported lazily so tests can patch the symbol in this module's
        namespace before facade module is loaded.
        """
        from src.novel.services.tool_facade import NovelToolFacade

        return NovelToolFacade(workspace=self.workspace)

    def _envelope_to_dict(self, envelope: Any) -> dict:
        """Normalize a ProposalEnvelope-like object to a dict for the LLM."""
        if isinstance(envelope, dict):
            return envelope
        to_dict = getattr(envelope, "to_dict", None)
        if callable(to_dict):
            result = to_dict()
            if isinstance(result, dict):
                return result
        # Last-resort fallback — never raise
        return {"error": "invalid envelope", "raw": str(envelope)[:500]}

    def _tool_propose_project_setup(
        self, inspiration: str, hints: dict | None = None
    ) -> dict:
        facade = self._get_tool_facade()
        envelope = facade.propose_project_setup(
            inspiration=inspiration, hints=hints
        )
        return self._envelope_to_dict(envelope)

    def _tool_propose_synopsis(self) -> dict:
        facade = self._get_tool_facade()
        envelope = facade.propose_synopsis(project_path=self._project_path)
        return self._envelope_to_dict(envelope)

    def _tool_propose_main_outline(
        self, custom_ideas: str | None = None
    ) -> dict:
        facade = self._get_tool_facade()
        envelope = facade.propose_main_outline(
            project_path=self._project_path, custom_ideas=custom_ideas
        )
        return self._envelope_to_dict(envelope)

    def _tool_propose_characters(self, synopsis: str | None = None) -> dict:
        facade = self._get_tool_facade()
        envelope = facade.propose_characters(
            project_path=self._project_path, synopsis=synopsis
        )
        return self._envelope_to_dict(envelope)

    def _tool_propose_world_setting(
        self, synopsis: str | None = None
    ) -> dict:
        facade = self._get_tool_facade()
        envelope = facade.propose_world_setting(
            project_path=self._project_path, synopsis=synopsis
        )
        return self._envelope_to_dict(envelope)

    def _tool_propose_story_arcs(self) -> dict:
        facade = self._get_tool_facade()
        envelope = facade.propose_story_arcs(project_path=self._project_path)
        return self._envelope_to_dict(envelope)

    def _tool_propose_volume_breakdown(
        self, synopsis: str | None = None
    ) -> dict:
        facade = self._get_tool_facade()
        envelope = facade.propose_volume_breakdown(
            project_path=self._project_path, synopsis=synopsis
        )
        return self._envelope_to_dict(envelope)

    def _tool_propose_volume_outline(self, volume_number: int) -> dict:
        facade = self._get_tool_facade()
        envelope = facade.propose_volume_outline(
            project_path=self._project_path, volume_number=int(volume_number)
        )
        return self._envelope_to_dict(envelope)

    def _tool_propose_chapter_brief(self, chapter_number: int) -> dict:
        facade = self._get_tool_facade()
        envelope = facade.propose_chapter_brief(
            project_path=self._project_path, chapter_number=int(chapter_number)
        )
        return self._envelope_to_dict(envelope)

    def _tool_accept_proposal(
        self,
        proposal_id: str,
        proposal_type: str,
        data: dict,
    ) -> dict:
        if not proposal_id or not isinstance(proposal_id, str):
            return {"error": "proposal_id 必填"}
        if not proposal_type or not isinstance(proposal_type, str):
            return {"error": "proposal_type 必填"}
        if not isinstance(data, dict):
            return {"error": "data 必须是 dict"}

        facade = self._get_tool_facade()
        result = facade.accept_proposal(
            project_path=self._project_path,
            proposal_id=proposal_id,
            proposal_type=proposal_type,
            data=data,
        )
        return self._envelope_to_dict(result)

    def _tool_regenerate_section(
        self,
        section: str,
        hints: str = "",
        volume_number: int | None = None,
    ) -> dict:
        if not section or not isinstance(section, str):
            return {"error": "section 必填"}
        facade = self._get_tool_facade()
        envelope = facade.regenerate_section(
            project_path=self._project_path,
            section=section,
            hints=hints or "",
            volume_number=(
                int(volume_number) if volume_number is not None else None
            ),
        )
        return self._envelope_to_dict(envelope)


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def _extract_working_memory(messages: list[dict], user_query: str) -> str:
    """Extract brief working memory from conversation context.

    Summarises the current user goal and recent tool interactions so the
    agent keeps context across turns.
    """
    recent_tools: list[str] = []
    for msg in messages[-6:]:
        content = msg.get("content", "")
        if "工具结果" in content or "tool" in content.lower():
            recent_tools.append(content[:200])

    memory_parts = [f"当前用户目标：{user_query[:200]}"]
    if recent_tools:
        memory_parts.append(f"最近工具调用：{'; '.join(recent_tools[-3:])}")

    return "\n".join(memory_parts)


def run_agent_chat(
    workspace: str,
    novel_id: str,
    message: str,
    context_chapters: list[int] | None = None,
    history: list[dict] | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    session_id: str = "",
    db: Any = None,
) -> dict:
    """Run the agent chat loop.

    1. Build system prompt with tool descriptions and novel context
    2. Send user message to LLM
    3. If LLM wants to call a tool, execute it and feed result back
    4. Repeat until LLM gives a final reply or max iterations reached

    Args:
        history: Previous conversation turns as [{"role": "user"|"assistant", "content": "..."}].
                 Used for multi-turn conversations.
        session_id: Conversation session ID for auto-restoring history from DB.
        db: StructuredDB instance for loading persisted conversation messages.
    """
    from src.llm.llm_client import create_llm_client

    # ------------------------------------------------------------------
    # Auto-restore conversation history from DB
    # ------------------------------------------------------------------
    if session_id and db and len(history or []) < 3:
        try:
            db_messages = db.get_conversation_messages(session_id)
            # Convert DB messages to history format, keep last 20
            db_history: list[dict] = []
            for msg in db_messages[-20:]:
                db_history.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })
            # Merge: DB history + explicit history (dedup by content)
            seen: set[tuple[str, int]] = set()
            merged: list[dict] = []
            for h in db_history + (history or []):
                # Normalize role: DB uses "agent", API uses "assistant"
                role = h.get("role", "")
                if role == "agent":
                    role = "assistant"
                content = h.get("content", "")
                key = (role, hash(content))
                if key not in seen:
                    seen.add(key)
                    merged.append({"role": role, "content": content})
            history = merged[-20:]  # Keep last 20

            # Avoid duplicating the current user message: novel_routes.py
            # saves it to DB before calling us, so the DB history already
            # contains it.  Remove the trailing user message if it matches
            # the current request so line 957 below can add it cleanly.
            if history and history[-1].get("role") == "user":
                last_content = history[-1].get("content", "")
                if last_content == message or last_content == message.strip():
                    history = history[:-1]
        except Exception:
            pass  # Fallback to explicit history

    llm = create_llm_client({})
    executor = AgentToolExecutor(workspace, novel_id)
    try:
        return _run_agent_chat_inner(
            executor, llm, workspace, novel_id, message,
            context_chapters, history, progress_callback,
        )
    finally:
        executor.close()


def _run_agent_chat_inner(
    executor: AgentToolExecutor,
    llm: Any,
    workspace: str,
    novel_id: str,
    message: str,
    context_chapters: list[int] | None,
    history: list[dict] | None,
    progress_callback: Callable[[float, str], None] | None,
) -> dict:
    """Inner implementation of run_agent_chat (separated for cleanup)."""
    # Get basic novel info for context
    novel_info = executor.execute("get_novel_info", {})

    system_prompt = f"""你是一个专业的AI小说创作助手。你的任务是帮助用户分析、修改和改进他们的小说。

## 核心原则
- **主动分析**：不要只说"已完成"，要给出具体的分析结果、发现的问题、改进建议
- **有理有据**：引用具体章节号、角色名、情节点来支撑你的判断
- **讨论互动**：当用户的需求有多种处理方式时，列出选项让用户选择
- **专业建议**：从叙事结构、角色发展、伏笔回收、节奏控制等角度给出专业意见

## 当前小说信息
{json.dumps(novel_info, ensure_ascii=False, indent=2)}

## 可用工具
{_tools_description()}

## 工作方式
1. 仔细分析用户的请求，理解他们的真正需求
2. 调用工具收集必要信息（可多步调用）
3. 基于收集到的信息进行深入分析
4. 用 reply_to_user 给出**详细的分析报告和具体建议**

## 回复格式（必须返回 JSON）
你的每次回复必须是合法的 JSON 对象。有两种格式可选：

### 方式一：直接回复（讨论/分析/回答问题时优先使用）
当你已有足够信息回答用户，或用户只是想讨论：
{{"reply": "你的详细回复内容（支持 markdown 格式）"}}

### 方式二：调用工具（需要获取数据或执行操作时）
{{"thinking": "为什么需要这个工具", "tool": "工具名", "args": {{参数}}}}

### 工作流程
1. 如果用户问的问题你已经能回答（基于已知信息和对话历史），直接用方式一回复
2. 如果需要更多数据（读章节、查债务等），先用方式二获取，再用方式一给出分析
3. 如果用户要求执行操作（重写、生成章节等），先用方式一确认方案，用户同意后再用方式二执行

### 回复质量要求
- 讨论型问题：给出分析 + 判断 + 建议选项，让用户参与决策
- 分析型请求：列出具体发现 + 数据支撑 + 改进方案
- 执行型请求：先说明计划，执行后说明结果和影响
- 永远不要只说"操作已完成"——告诉用户你做了什么、发现了什么、建议什么

示例好回复（直接回复模式）：
{{"reply": "我检查了相关章节，发现以下问题：\\n1. 第X章和第Y章开头场景高度重复...\\n2. 某重要角色在前若干章被多次提及但至今未正式出场...\\n\\n建议：\\n- 重写X-Y章，避免重复...\\n- 安排该角色在合适章节正式出场..."}}

示例好回复（工具调用模式）：
{{"thinking": "用户想了解第15章的问题，需要先读取章节内容", "tool": "read_chapter", "args": {{"chapter_number": 15}}}}
"""

    # Add working memory if we have conversation history
    if history and len(history) > 2:
        working_mem = _extract_working_memory(
            [{"role": h.get("role", "user"), "content": h.get("content", "")} for h in history],
            message,
        )
        system_prompt += f"\n\n【工作记忆 — 当前会话上下文】\n{working_mem}\n"

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
    ]

    # Inject previous conversation history for multi-turn support
    if history:
        for turn in history[-10:]:  # Keep last 10 turns to control context size
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "agent" or role == "assistant":
                messages.append({"role": "assistant", "content": content})
            else:
                messages.append({"role": "user", "content": content})

    # Add current user message
    messages.append({"role": "user", "content": message})

    # Add context chapters if provided
    if context_chapters:
        for ch_num in context_chapters[:3]:
            ch_data = executor.execute("read_chapter", {"chapter_number": ch_num})
            if "error" not in ch_data:
                messages.append({
                    "role": "user",
                    "content": f"[参考章节 {ch_num}]: {ch_data.get('text', '')[:1500]}",
                })

    conversation_log: list[dict] = []
    final_reply = ""

    # Read max_iterations from config (fallback to default)
    max_iterations = _DEFAULT_MAX_ITERATIONS
    try:
        import yaml
        from pathlib import Path
        config_path = Path(workspace).parent / "config.yaml"
        if not config_path.exists():
            config_path = Path("config.yaml")
        if config_path.exists():
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            max_iterations = cfg.get("agent_chat", {}).get("max_iterations", _DEFAULT_MAX_ITERATIONS)
    except Exception:
        pass

    for i in range(max_iterations):
        if progress_callback:
            progress_callback(
                0.1 + (i / max_iterations) * 0.8,
                f"Agent 思考中... (步骤 {i + 1})"
            )

        # Smart truncation: warn Agent when approaching step limit
        if i >= max_iterations - 2 and not final_reply:
            remaining = max_iterations - i
            messages.append({
                "role": "user",
                "content": f"[系统提示：你只剩{remaining}步就达到步骤上限。请立即用 {{\"reply\": \"...\"}} 给出你目前的分析和结论，不要再调用工具。如果分析尚未完成，先总结已有发现，告诉用户可以继续追问。]",
            })

        response = llm.chat(
            messages=messages,
            temperature=0.3,
            json_mode=True,
            max_tokens=4096,
        )

        # Parse agent response
        try:
            agent_action = json.loads(response.content)
        except json.JSONDecodeError:
            # Non-JSON response — treat as direct reply (natural conversation)
            final_reply = response.content
            break

        # Direct reply — Agent chose to respond without tools
        direct_reply = agent_action.get("reply")
        if direct_reply and not agent_action.get("tool"):
            final_reply = direct_reply
            conversation_log.append({
                "step": i + 1,
                "thinking": agent_action.get("thinking", ""),
                "tool": "direct_reply",
                "args": {},
                "result": {"reply": direct_reply},
            })
            break

        thinking = agent_action.get("thinking", "")
        tool_name = agent_action.get("tool", "")
        tool_args = agent_action.get("args", {})

        if not tool_name:
            # Fallback: no tool and no reply field — treat raw content as reply
            final_reply = response.content
            break

        log.info("Agent step %d: %s(%s)", i + 1, tool_name, tool_args)

        # Execute tool
        if progress_callback:
            tool_label = {
                "read_chapter": "读取章节",
                "edit_setting": "修改设定",
                "rewrite_chapter": "重写章节",
                "generate_chapters": "生成章节",
                "resize_novel": "调整章节数",
                "publish_chapters": "标记发布",
                "proofread_chapter": "校对章节",
                "get_novel_info": "获取信息",
                "search_chapters": "搜索内容",
                "reply_to_user": "回复用户",
                "get_narrative_debts": "查看叙事债务",
                "manage_debt": "管理债务",
                "get_story_arcs": "查看故事弧线",
                "get_chapter_brief": "查看章节任务书",
                "get_knowledge_graph": "查看知识图谱",
                "get_narrative_overview": "叙事总览",
                "get_volume_settlement": "查看卷末收束",
                "get_arc_status": "查看弧线状态",
                "plan_chapters": "规划大纲",
                "rename_chapter": "修改标题",
            }.get(tool_name, tool_name)
            progress_callback(
                0.1 + (i / max_iterations) * 0.8,
                f"执行: {tool_label}..."
            )

        tool_result = executor.execute(tool_name, tool_args)

        # Log the step
        step = {
            "step": i + 1,
            "thinking": thinking,
            "tool": tool_name,
            "args": tool_args,
            "result": tool_result,
        }
        conversation_log.append(step)

        # Check if this is the final reply
        if tool_name == "reply_to_user":
            final_reply = tool_result.get("reply", "")
            break

        # Feed tool result back to LLM
        messages.append({"role": "assistant", "content": response.content})
        messages.append({
            "role": "user",
            "content": f"[工具结果] {tool_name}: {json.dumps(tool_result, ensure_ascii=False)[:4000]}",
        })

    if not final_reply and conversation_log:
        # Agent reached max iterations without calling reply_to_user.
        # Synthesize a reply from the last tool results instead of a generic message.
        last_steps = conversation_log[-3:]
        summary_parts = []
        has_errors = False
        for s in last_steps:
            tool = s.get("tool", "")
            result = s.get("result", {})
            if isinstance(result, dict):
                if result.get("error"):
                    has_errors = True
                    summary_parts.append(f"- {tool}: 失败 — {result['error'][:200]}")
                elif tool == "read_chapter":
                    summary_parts.append(f"- 已读取第{result.get('chapter_number', '?')}章 ({result.get('word_count', '?')}字)")
                elif tool == "rewrite_chapter":
                    chs = result.get("chapters_rewritten", [])
                    summary_parts.append(f"- 已重写章节: {chs}" if chs else "- 重写完成")
                elif tool == "generate_chapters":
                    chs = result.get("chapters_generated", [])
                    summary_parts.append(f"- 已生成章节: {chs}" if chs else "- 生成完成")
                elif tool == "edit_setting":
                    summary_parts.append(f"- 已修改设定: {result.get('change_type', '?')} ({result.get('entity_type', '?')})")
                elif tool == "get_narrative_debts":
                    stats = result.get("statistics", {})
                    summary_parts.append(f"- 叙事债务: {stats.get('pending_count', 0)}个待处理, {stats.get('overdue_count', 0)}个逾期")
                else:
                    summary_parts.append(f"- {tool}: 已执行")
        if summary_parts:
            header = "执行了以下操作但未完成完整分析（达到步骤上限）：\n"
            footer = "\n\n如有失败操作，可能是网络波动，请再试一次。" if has_errors else "\n\n请再发一条消息让我继续分析。"
            final_reply = header + "\n".join(summary_parts) + footer
        else:
            final_reply = "操作未完成，请再试一次或换个方式描述你的需求。"

    return {
        "reply": final_reply,
        "steps": conversation_log,
        "total_steps": len(conversation_log),
        "model": getattr(llm, "model", "unknown"),
    }
