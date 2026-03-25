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
