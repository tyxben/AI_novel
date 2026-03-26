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

# Max tool-call iterations to prevent infinite loops
MAX_ITERATIONS = 8


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
        from src.novel.pipeline import NovelPipeline
        pipe = NovelPipeline(workspace=self.workspace)
        result = pipe.apply_feedback(
            project_path=self._project_path,
            feedback_text=feedback_text,
            chapter_number=chapter_number,
            dry_run=False,
        )
        return {
            "status": "completed",
            "chapters_rewritten": result.get("chapters_rewritten", []),
            "feedback_type": result.get("feedback_type", ""),
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


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def run_agent_chat(
    workspace: str,
    novel_id: str,
    message: str,
    context_chapters: list[int] | None = None,
    history: list[dict] | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict:
    """Run the agent chat loop.

    1. Build system prompt with tool descriptions and novel context
    2. Send user message to LLM
    3. If LLM wants to call a tool, execute it and feed result back
    4. Repeat until LLM gives a final reply or max iterations reached

    Args:
        history: Previous conversation turns as [{"role": "user"|"assistant", "content": "..."}].
                 Used for multi-turn conversations.
    """
    from src.llm.llm_client import create_llm_client

    llm = create_llm_client({})
    executor = AgentToolExecutor(workspace, novel_id)

    # Get basic novel info for context
    novel_info = executor.execute("get_novel_info", {})

    system_prompt = f"""你是一个AI小说助手 Agent。用户会用自然语言告诉你要做什么，你需要自主判断调用哪些工具来完成任务。

## 当前小说信息
{json.dumps(novel_info, ensure_ascii=False, indent=2)}

## 可用工具
{_tools_description()}

## 工作方式
1. 分析用户的请求，理解他们想要做什么
2. 决定需要调用哪些工具（可以多步调用）
3. 每一步调用一个工具，查看结果后决定下一步
4. 完成所有操作后，用 reply_to_user 工具总结结果

## 回复格式
每次回复必须是一个 JSON 对象，包含你要调用的工具：
{{"tool": "工具名", "args": {{参数对象}}}}

如果你需要先思考，可以用：
{{"thinking": "你的思考过程", "tool": "工具名", "args": {{参数对象}}}}

当所有操作完成后，必须调用 reply_to_user 来总结：
{{"tool": "reply_to_user", "args": {{"message": "总结内容"}}}}
"""

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

    for i in range(MAX_ITERATIONS):
        if progress_callback:
            progress_callback(
                0.1 + (i / MAX_ITERATIONS) * 0.8,
                f"Agent 思考中... (步骤 {i + 1})"
            )

        response = llm.chat(
            messages=messages,
            temperature=0.2,
            json_mode=True,
            max_tokens=2048,
        )

        # Parse agent response
        try:
            agent_action = json.loads(response.content)
        except json.JSONDecodeError:
            # If not valid JSON, treat as final reply
            final_reply = response.content
            break

        thinking = agent_action.get("thinking", "")
        tool_name = agent_action.get("tool", "")
        tool_args = agent_action.get("args", {})

        if not tool_name:
            final_reply = response.content
            break

        log.info("Agent step %d: %s(%s)", i + 1, tool_name, tool_args)

        # Execute tool
        if progress_callback:
            tool_label = {
                "read_chapter": "读取章节",
                "edit_setting": "修改设定",
                "rewrite_chapter": "重写章节",
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
            }.get(tool_name, tool_name)
            progress_callback(
                0.1 + (i / MAX_ITERATIONS) * 0.8,
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
            "content": f"[工具结果] {tool_name}: {json.dumps(tool_result, ensure_ascii=False)[:2000]}",
        })

    if not final_reply and conversation_log:
        final_reply = "操作已完成。"

    return {
        "reply": final_reply,
        "steps": conversation_log,
        "total_steps": len(conversation_log),
        "model": getattr(llm, "model", "unknown"),
    }
