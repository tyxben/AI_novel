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
    {
        "name": "rebuild_narrative",
        "description": "从已有章节重建叙事控制数据（债务、故事弧线）。适用于写了一半但没有叙事控制数据的小说。",
        "parameters": {
            "method": {
                "type": "string",
                "description": "提取方法: rule_based(纯规则快速), llm(AI分析精准), hybrid(混合推荐)",
                "default": "hybrid",
                "optional": True,
            },
        },
    },
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
        "description": "规划接下来几章的大纲（不生成正文）。生成标题、目标、关键事件、要收/埋的伏笔，供用户审核后再写作。",
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

    def execute(self, tool_name: str, args: dict) -> dict:
        """Execute a tool and return the result dict."""
        method = getattr(self, f"_tool_{tool_name}", None)
        if not method:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return method(**args)
        except Exception as e:
            log.exception("Tool %s failed", tool_name)
            return {"error": str(e)}

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

        Returns ObligationTracker instance, or None if the database
        cannot be initialized.
        """
        try:
            from src.novel.services.obligation_tracker import ObligationTracker
            from src.novel.storage.structured_db import StructuredDB

            db_path = Path(self._project_path) / "memory.db"
            if not db_path.exists():
                # Novel created before narrative features — use in-memory
                return ObligationTracker(db=None)
            db = StructuredDB(db_path)
            return ObligationTracker(db=db)
        except Exception as exc:
            log.warning("Failed to load ObligationTracker: %s", exc)
            return None

    def _get_structured_db(self):
        """Load StructuredDB for the current novel, or None."""
        try:
            from src.novel.storage.structured_db import StructuredDB

            db_path = Path(self._project_path) / "memory.db"
            if not db_path.exists():
                return None
            return StructuredDB(db_path)
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
            tracker.mark_debt_fulfilled(debt_id, chapter_num=0, note="Agent Chat 手动标记")
            return {"status": "fulfilled", "debt_id": debt_id}

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

    def _tool_rebuild_narrative(self, method: str = "hybrid") -> dict:
        from src.novel.services.narrative_rebuild import NarrativeRebuildService

        # Create LLM client for hybrid/llm methods
        llm = None
        if method != "rule_based":
            try:
                from src.llm.llm_client import create_llm_client

                llm = create_llm_client({})
            except Exception:
                pass

        service = NarrativeRebuildService(
            self._project_path, llm_client=llm
        )
        try:
            result = service.rebuild_all(method=method)
        finally:
            service.close()
        return result

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
{{"reply": "我检查了14-18章，发现以下问题：\\n1. 第15章和第16章开头场景高度重复（都是矿场发灵石）...\\n2. 苏晚照在前12章提到过3次但至今未正式出场...\\n\\n建议：\\n- 重写第15-16章，避免重复...\\n- 第19章可以安排苏晚照正式出场..."}}

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
                "rebuild_narrative": "重建叙事数据",
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
        for s in last_steps:
            tool = s.get("tool", "")
            result = s.get("result", {})
            if isinstance(result, dict):
                # Extract key info from tool results
                if result.get("error"):
                    summary_parts.append(f"- {tool}: 出错 — {result['error']}")
                elif tool == "read_chapter":
                    summary_parts.append(f"- 已读取第{result.get('chapter_number', '?')}章 ({result.get('word_count', '?')}字)")
                elif tool == "get_narrative_debts":
                    stats = result.get("statistics", {})
                    summary_parts.append(f"- 叙事债务: {stats.get('pending_count', 0)}个待处理, {stats.get('overdue_count', 0)}个逾期")
                else:
                    summary_parts.append(f"- {tool}: 已执行")
        if summary_parts:
            final_reply = "执行了以下操作但未完成完整分析（达到步骤上限）：\n" + "\n".join(summary_parts) + "\n\n请再发一条消息让我继续分析。"
        else:
            final_reply = "操作未完成，请再试一次或换个方式描述你的需求。"

    return {
        "reply": final_reply,
        "steps": conversation_log,
        "total_steps": len(conversation_log),
        "model": getattr(llm, "model", "unknown"),
    }
