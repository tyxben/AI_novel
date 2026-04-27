"""post_writer — chapter-level post-processing graph node.

Sits between ``writer`` and ``reviewer`` in the chapter generation graph::

    chapter_planner → writer → post_writer → reviewer → state_writeback

Responsibility (B 阶段瘦身, 2026-04-27)：
* Writer 在 generate_scene 内部已对每个场景做 per-scene sanitize / dedup /
  name-check（write loop 的内置步骤）。
* writer_node 现在返回 raw joined chapter text（B 阶段已删 generate_chapter
  末尾的 ``_sanitize_chapter_text(full_text)`` 冗余调用）。
* 本节点跑 chapter-level ``sanitize_chapter_text`` 兜底过滤——绝大多数情况
  下是无操作（per-scene 已干净），但作为防御纵深，挡住任何场景间拼接边界
  上漏出的 UI 残片。

Pure transform：本节点不调 LLM、不持任何状态、不读 disk，只过文本。

设计决定：
* 不做 dedup_paragraphs：那是 intra-chapter 场景间去重，已在
  ``Writer.generate_chapter`` 写循环里做。chapter-level 拿 joined 文本回头
  做段间去重会把正常的"主角先想 X，后又想 X 但有进展"这种合法呼应误删。
* 不做 check_character_names：那是 per-scene 即时报警 + 占位符替换，错过
  时机就只是 log warn 没意义；放到 graph 节点不增价值。
* 不做 trim_to_hard_cap：硬截是写入侧 (write_scene / rewrite_chapter /
  polish_chapter) 的字数控制三件套之一，与 max_tokens / soft_max_chars 协同
  生效；放到 graph 节点会破坏字数控制语义。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.novel.agents.state import Decision, NovelState
from src.novel.tools.writer_postprocess import sanitize_chapter_text

log = logging.getLogger("novel")


def post_writer_node(state: NovelState) -> dict[str, Any]:
    """LangGraph node: chapter-level post-processing (sanitize 兜底).

    Args:
        state: 必须含 ``current_chapter_text``（writer 节点的产出）。

    Returns:
        Dict with ``current_chapter_text`` 替换为 sanitized 版本，外加
        ``decisions`` / ``completed_nodes``。
    """
    decisions: list[Decision] = []

    chapter_text = state.get("current_chapter_text")
    if not chapter_text:
        # Writer 失败或还没跑：直接放行，让下游 reviewer 自行处理
        return {
            "decisions": [
                {
                    "agent": "PostWriter",
                    "step": "skip",
                    "decision": "无 current_chapter_text，跳过 post-processing",
                    "reason": "writer 节点未产出文本",
                    "data": None,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "completed_nodes": ["post_writer"],
        }

    cleaned = sanitize_chapter_text(chapter_text)
    if cleaned != chapter_text:
        delta = len(chapter_text) - len(cleaned)
        log.info(
            "[post_writer] chapter sanitize: %d 字 → %d 字 (delta=%d)",
            len(chapter_text), len(cleaned), delta,
        )
        decisions.append({
            "agent": "PostWriter",
            "step": "sanitize",
            "decision": "chapter-level UI 元素清洗",
            "reason": f"原文 {len(chapter_text)} 字 → 清洗后 {len(cleaned)} 字",
            "data": {"delta_chars": delta},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "current_chapter_text": cleaned,
        "decisions": decisions,
        "completed_nodes": ["post_writer"],
    }
