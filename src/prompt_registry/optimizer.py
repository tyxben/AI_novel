"""Prompt Optimizer -- LLM-powered automatic prompt improvement."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.llm.llm_client import LLMClient
from src.prompt_registry.quality_tracker import QualityTracker
from src.prompt_registry.registry import PromptRegistry

log = logging.getLogger("prompt_registry.optimizer")


class PromptOptimizer:
    """Uses LLM to automatically generate improved versions of low-scoring prompt blocks."""

    def __init__(self, registry: PromptRegistry, llm: LLMClient):
        self.registry = registry
        self.llm = llm
        self.tracker = QualityTracker(registry)

    def generate_improved_block(self, base_id: str) -> dict[str, Any]:
        """Generate an improved version of a prompt block using LLM.

        The improved block is created as a new version with active=False (pending review).

        Returns: {
            "block_id": str,  # new block's ID
            "base_id": str,
            "old_version": int,
            "new_version": int,
            "old_content": str,
            "new_content": str,
            "improvement_rationale": str,
        }
        """
        current = self.registry.get_active_block(base_id)
        if current is None:
            raise ValueError(f"No active block found for base_id '{base_id}'")

        weaknesses = self.tracker.get_block_weaknesses(base_id, limit=10)
        stats = self.tracker.get_block_statistics(base_id)

        prompt = self._build_optimization_prompt(current.content, weaknesses, stats)

        resp = self.llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.4,
            json_mode=True,
            max_tokens=4096,
        )

        try:
            result = json.loads(resp.content)
            new_content = result.get("improved_prompt", "")
            rationale = result.get("rationale", "")
        except (json.JSONDecodeError, AttributeError):
            # Try to extract content directly
            new_content = resp.content.strip()
            rationale = "LLM returned non-JSON response"

        if not new_content or len(new_content) < 20:
            raise ValueError("LLM failed to generate improved prompt")

        # Create new version (inactive -- pending review)
        new_block = self.registry.create_block(
            base_id=base_id,
            block_type=current.block_type,
            content=new_content,
            agent=current.agent,
            genre=current.genre,
            scene_type=current.scene_type,
            metadata={
                **current.metadata,
                "optimization_rationale": rationale,
                "optimization_source_version": current.version,
                "optimization_weaknesses": weaknesses[:5],
                "pending_review": True,
            },
        )

        # The create_block auto-activates the new version.
        # We need to revert: deactivate new, reactivate old.
        self._set_pending_review(new_block.block_id, current.block_id)

        return {
            "block_id": new_block.block_id,
            "base_id": base_id,
            "old_version": current.version,
            "new_version": new_block.version,
            "old_content": current.content,
            "new_content": new_content,
            "improvement_rationale": rationale,
        }

    def _set_pending_review(self, new_block_id: str, old_block_id: str) -> None:
        """Set the new block to inactive (pending review) and reactivate the old one."""
        from datetime import datetime

        now = datetime.now().isoformat()
        with self.registry._transaction() as cur:
            cur.execute(
                "UPDATE prompt_blocks SET active = 0, updated_at = ? WHERE block_id = ?",
                (now, new_block_id),
            )
            cur.execute(
                "UPDATE prompt_blocks SET active = 1, updated_at = ? WHERE block_id = ?",
                (now, old_block_id),
            )

    def approve_improved_block(self, block_id: str) -> dict[str, Any]:
        """Approve a pending improved block -- activate it, deactivate old version.

        Returns the approved block info.
        """
        from datetime import datetime

        now = datetime.now().isoformat()

        # Get the block to approve
        with self.registry._lock:
            assert self.registry._conn is not None
            cur = self.registry._conn.cursor()
            cur.execute(
                "SELECT * FROM prompt_blocks WHERE block_id = ?", (block_id,)
            )
            row = cur.fetchone()

        if row is None:
            raise ValueError(f"Block '{block_id}' not found")

        base_id = row["base_id"]

        # Deactivate all versions, then activate the approved one
        with self.registry._transaction() as cur:
            cur.execute(
                "UPDATE prompt_blocks SET active = 0, updated_at = ? WHERE base_id = ?",
                (now, base_id),
            )
            cur.execute(
                "UPDATE prompt_blocks SET active = 1, updated_at = ? WHERE block_id = ?",
                (now, block_id),
            )
            # Clear pending_review from metadata
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            metadata.pop("pending_review", None)
            metadata["approved_at"] = now
            cur.execute(
                "UPDATE prompt_blocks SET metadata = ?, needs_optimization = 0 WHERE block_id = ?",
                (json.dumps(metadata, ensure_ascii=False), block_id),
            )

        return {
            "block_id": block_id,
            "base_id": base_id,
            "status": "approved",
            "version": row["version"],
        }

    def reject_improved_block(
        self, block_id: str, reason: str = ""
    ) -> dict[str, Any]:
        """Reject a pending improved block -- mark it as rejected."""
        from datetime import datetime

        now = datetime.now().isoformat()

        with self.registry._lock:
            assert self.registry._conn is not None
            cur = self.registry._conn.cursor()
            cur.execute(
                "SELECT * FROM prompt_blocks WHERE block_id = ?", (block_id,)
            )
            row = cur.fetchone()

        if row is None:
            raise ValueError(f"Block '{block_id}' not found")

        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        metadata["rejected"] = True
        metadata["rejected_at"] = now
        metadata["rejection_reason"] = reason
        metadata.pop("pending_review", None)

        with self.registry._transaction() as cur:
            cur.execute(
                "UPDATE prompt_blocks SET metadata = ?, updated_at = ? WHERE block_id = ?",
                (json.dumps(metadata, ensure_ascii=False), now, block_id),
            )

        return {
            "block_id": block_id,
            "base_id": row["base_id"],
            "status": "rejected",
            "reason": reason,
        }

    def optimize_all_candidates(
        self,
        threshold: float = 6.0,
        min_usage: int = 10,
        max_candidates: int = 5,
    ) -> list[dict[str, Any]]:
        """Find all low-scoring blocks and generate improvements for each.

        Returns list of optimization results.
        """
        candidates = self.tracker.get_optimization_candidates(threshold, min_usage)
        results: list[dict[str, Any]] = []
        for candidate in candidates[:max_candidates]:
            try:
                result = self.generate_improved_block(candidate["base_id"])
                results.append(result)
            except Exception as e:
                log.warning(
                    "Failed to optimize block %s: %s", candidate["base_id"], e
                )
                results.append(
                    {
                        "base_id": candidate["base_id"],
                        "error": str(e),
                    }
                )
        return results

    def _build_optimization_prompt(
        self, current_content: str, weaknesses: list[str], stats: dict
    ) -> str:
        """Build the LLM prompt for generating an improved version."""
        weakness_text = (
            "\n".join(f"- {w}" for w in weaknesses)
            if weaknesses
            else "（无具体问题记录）"
        )

        return f"""你是一位 prompt 工程专家。请改进以下用于 AI 小说写作的 prompt block。

## 当前 prompt
```
{current_content}
```

## 质量统计
- 平均评分：{stats.get('avg_score', '无数据')}/10
- 使用次数：{stats.get('usage_count', 0)}
- 评分趋势：{stats.get('score_trend', '未知')}

## 历史问题反馈
{weakness_text}

## 改进要求
1. 保持原有功能意图不变
2. 针对历史问题做针对性改进
3. 指令要具体、可执行，避免空泛要求
4. 用正面指导代替禁止性表述（"这样写" 优于 "不要那样写"）
5. 长度与原 prompt 相当（±30%）

请返回 JSON：
{{"improved_prompt": "改进后的完整 prompt 内容", "rationale": "改进说明（简要）"}}"""
