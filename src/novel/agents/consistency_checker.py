"""ConsistencyChecker - 一致性检查官 Agent

负责：
1. 从章节文本提取关键事实
2. 执行三层混合一致性检查（SQLite / NetworkX / Vector）
3. 对模糊矛盾进行 LLM 裁决
4. 生成一致性报告

所有方法均为同步（SYNC），与 LLMClient.chat() 保持一致。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.novel.agents.state import Decision, NovelState
from src.novel.tools.consistency_tool import ConsistencyTool

log = logging.getLogger("novel")


def _make_decision(
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    """创建 ConsistencyChecker 的决策记录。"""
    return Decision(
        agent="ConsistencyChecker",
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


class ConsistencyChecker:
    """一致性检查官 Agent

    通过 ConsistencyTool 执行三层矛盾检测，
    对 confidence 在 [0.4, 0.8) 区间的模糊矛盾进行 LLM 裁决。
    """

    LLM_JUDGE_THRESHOLD_LOW = 0.4
    LLM_JUDGE_THRESHOLD_HIGH = 0.8

    def __init__(self, llm_client: Any) -> None:
        self.llm = llm_client
        self.tool = ConsistencyTool(llm_client)

    def check_chapter(
        self,
        chapter_text: str,
        chapter_number: int,
        memory: Any,
    ) -> dict[str, Any]:
        """完整一致性检查流程。

        步骤：
        1. 从章节文本提取事实
        2. 执行三层一致性检查
        3. 对模糊矛盾进行 LLM 裁决
        4. 汇总报告

        Args:
            chapter_text: 章节文本
            chapter_number: 章节号
            memory: NovelMemory 实例

        Returns:
            dict 包含:
            - facts: 提取的事实列表
            - contradictions: 确认的矛盾列表
            - dismissed: 被排除的假矛盾列表
            - passed: 是否通过一致性检查
        """
        # Step 1: 提取事实
        facts = self.tool.extract_facts(chapter_text, chapter_number)
        log.info("第%d章事实提取完成: %d 个事实", chapter_number, len(facts))

        # Step 2: 三层检查
        raw_contradictions = self.tool.check_consistency(facts, memory)
        log.info(
            "第%d章三层检查完成: %d 个潜在矛盾",
            chapter_number,
            len(raw_contradictions),
        )

        # Step 3: LLM 裁决模糊矛盾
        confirmed: list[dict] = []
        dismissed: list[dict] = []

        for contradiction in raw_contradictions:
            confidence = contradiction.get("confidence", 0)

            if confidence >= self.LLM_JUDGE_THRESHOLD_HIGH:
                # 高 confidence 直接确认
                confirmed.append(contradiction)
            elif confidence >= self.LLM_JUDGE_THRESHOLD_LOW:
                # 模糊区间，LLM 裁决
                is_real, reason = self.tool.service.llm_judge(contradiction)
                if is_real:
                    contradiction["llm_judgment"] = reason
                    contradiction["confidence"] = max(
                        confidence, 0.8
                    )
                    confirmed.append(contradiction)
                else:
                    contradiction["dismissed_reason"] = reason
                    dismissed.append(contradiction)
            else:
                # 低 confidence 直接排除
                dismissed.append(contradiction)

        passed = len(confirmed) == 0

        return {
            "facts": [f.model_dump() for f in facts],
            "contradictions": confirmed,
            "dismissed": dismissed,
            "passed": passed,
            "chapter_number": chapter_number,
        }


# ---------------------------------------------------------------------------
# LangGraph 节点函数
# ---------------------------------------------------------------------------


def consistency_checker_node(state: NovelState) -> dict[str, Any]:
    """LangGraph 节点：ConsistencyChecker。

    检查当前章节草稿的一致性。

    从 state 中读取:
    - current_chapter_text: 当前章节文本
    - current_chapter: 当前章节号
    - config.llm: LLM 配置

    更新 state:
    - current_chapter_quality: 添加一致性检查结果
    - decisions: 添加决策记录
    - errors: 添加错误信息（如有）
    - completed_nodes: 添加 "consistency_checker"
    """
    from src.llm.llm_client import create_llm_client

    decisions: list[Decision] = []
    errors: list[dict] = []

    chapter_text = state.get("current_chapter_text", "")
    chapter_number = state.get("current_chapter", 0)

    if not chapter_text:
        errors.append(
            {
                "agent": "ConsistencyChecker",
                "message": "当前章节文本为空，无法检查一致性",
            }
        )
        return {
            "errors": errors,
            "completed_nodes": ["consistency_checker"],
        }

    # 省 token：前3章跳过完整一致性检查（还没有足够上下文产生矛盾）
    # 之后每3章做一次完整检查，其余章节仅标记通过
    if chapter_number <= 3 or (chapter_number > 3 and chapter_number % 3 != 0):
        log.info("第%d章跳过完整一致性检查（省 token）", chapter_number)
        existing_quality = state.get("current_chapter_quality") or {}
        return {
            "current_chapter_quality": {
                **existing_quality,
                "consistency_check": {"passed": True, "contradictions": [], "skipped": True},
            },
            "decisions": [_make_decision(
                step="skip_check",
                decision="跳过完整检查",
                reason=f"第{chapter_number}章：降频策略",
            )],
            "errors": [],
            "completed_nodes": ["consistency_checker"],
        }

    # 每9章做一次完整 LLM 检查，其余用 BM25 轻量检查
    use_bm25 = chapter_number % 9 != 0

    # ---- BM25 lightweight check (no LLM needed) ----
    if use_bm25:
        bm25_report = _bm25_check(state, chapter_text, chapter_number)
        decisions.append(
            _make_decision(
                step="bm25_check",
                decision="通过" if bm25_report["passed"] else "发现潜在矛盾",
                reason=f"BM25 轻量检查，{len(bm25_report['contradictions'])} 个潜在矛盾",
                data={"contradictions_count": len(bm25_report["contradictions"])},
            )
        )
        existing_quality = state.get("current_chapter_quality") or {}
        return {
            "current_chapter_quality": {
                **existing_quality,
                "consistency_check": bm25_report,
            },
            "decisions": decisions,
            "errors": errors,
            "completed_nodes": ["consistency_checker"],
        }

    # ---- Full LLM check (every 9th chapter) ----

    # 初始化 LLM
    llm_config = state.get("config", {}).get("llm", {})
    try:
        llm = create_llm_client(llm_config)
    except Exception as exc:
        errors.append(
            {
                "agent": "ConsistencyChecker",
                "message": f"LLM 初始化失败: {exc}",
            }
        )
        return {
            "errors": errors,
            "completed_nodes": ["consistency_checker"],
        }

    checker = ConsistencyChecker(llm)

    # 初始化 NovelMemory（简化：从 state 的 workspace 获取）
    novel_id = state.get("novel_id", "unknown")
    workspace = state.get("workspace", "/tmp")

    try:
        from src.novel.storage.novel_memory import NovelMemory

        memory = NovelMemory(novel_id, workspace)
    except Exception as exc:
        log.warning("记忆系统初始化失败，使用空检查: %s", exc)
        errors.append(
            {
                "agent": "ConsistencyChecker",
                "message": f"记忆系统初始化失败: {exc}",
            }
        )
        return {
            "errors": errors,
            "completed_nodes": ["consistency_checker"],
        }

    # 执行检查
    try:
        report = checker.check_chapter(chapter_text, chapter_number, memory)
        decisions.append(
            _make_decision(
                step="check_chapter",
                decision="通过" if report["passed"] else "发现矛盾",
                reason=f"提取{len(report['facts'])}个事实，发现{len(report['contradictions'])}个矛盾",
                data={
                    "contradictions_count": len(report["contradictions"]),
                    "dismissed_count": len(report["dismissed"]),
                },
            )
        )
    except Exception as exc:
        log.error("一致性检查失败: %s", exc)
        errors.append(
            {
                "agent": "ConsistencyChecker",
                "message": f"一致性检查失败: {exc}",
            }
        )
        return {
            "decisions": decisions,
            "errors": errors,
            "completed_nodes": ["consistency_checker"],
        }
    finally:
        try:
            memory.close()
        except Exception:
            pass

    # 合并质量信息
    existing_quality = state.get("current_chapter_quality") or {}
    updated_quality = {
        **existing_quality,
        "consistency_check": {
            "passed": report["passed"],
            "contradictions": report["contradictions"],
            "facts_count": len(report["facts"]),
        },
    }

    return {
        "current_chapter_quality": updated_quality,
        "decisions": decisions,
        "errors": errors,
        "completed_nodes": ["consistency_checker"],
    }


def _bm25_check(
    state: NovelState,
    chapter_text: str,
    chapter_number: int,
) -> dict[str, Any]:
    """BM25-based lightweight consistency check (no LLM).

    Builds a BM25 index from previous chapters, then for each character
    queries relevant passages and does simple rule-based contradiction
    detection (e.g. "X died" vs "X appeared").

    Returns a dict compatible with the consistency_check quality shape.
    """
    from src.novel.tools.bm25_retriever import BM25Retriever

    retriever = BM25Retriever()

    # Load previous chapters from state
    chapters_text: dict[int, str] = state.get("chapters_text") or {}
    for ch_num in sorted(chapters_text):
        if ch_num < chapter_number:
            retriever.add_chapter(ch_num, chapters_text[ch_num])

    # Also index the current chapter
    retriever.add_chapter(chapter_number, chapter_text)

    # Extract character names from state
    characters: list[dict] = state.get("characters") or []
    char_names = [c.get("name", "") for c in characters if c.get("name")]

    contradictions: list[dict[str, Any]] = []

    # Death / disappearance keywords that signal permanent state
    _DEATH_KEYWORDS = ("死", "亡", "殒命", "丧命", "身亡", "去世", "陨落")
    _ALIVE_KEYWORDS = ("出现", "说道", "笑道", "走", "拿", "站", "坐")

    for name in char_names:
        passages = retriever.query_by_entity(name, top_k=10)
        death_refs: list[dict] = []
        alive_refs: list[dict] = []

        for p in passages:
            text = p["text"]
            if name not in text:
                continue
            if any(kw in text for kw in _DEATH_KEYWORDS):
                death_refs.append(p)
            if any(kw in text for kw in _ALIVE_KEYWORDS):
                alive_refs.append(p)

        # If a character has death references in earlier chapters
        # but alive references in later chapters -> potential contradiction
        for d_ref in death_refs:
            for a_ref in alive_refs:
                if a_ref["chapter"] > d_ref["chapter"]:
                    contradictions.append({
                        "layer": "bm25",
                        "character": name,
                        "fact": {
                            "chapter": a_ref["chapter"],
                            "content": a_ref["text"][:100],
                        },
                        "conflicting_fact": {
                            "chapter": d_ref["chapter"],
                            "content": d_ref["text"][:100],
                        },
                        "confidence": 0.5,
                        "reason": f"{name}在第{d_ref['chapter']}章疑似死亡，但在第{a_ref['chapter']}章再次出现",
                    })

    return {
        "passed": len(contradictions) == 0,
        "contradictions": contradictions,
        "method": "bm25",
    }
