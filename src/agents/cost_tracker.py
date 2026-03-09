"""LLM API 费用追踪器 — 记录各模型调用次数与 token 用量，计算费用。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 价格常量  (单位: 美元 / 1M tokens, 或 美元 / 次)
# ---------------------------------------------------------------------------

# (input_price_per_1m, output_price_per_1m)  —  token 计费模型
TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-vision": (2.50, 10.00),
    "deepseek-chat": (0.14, 0.28),
    "gemini-2.0-flash": (0.0, 0.0),
}

# 按次计费模型  (单价 / 次)
PER_CALL_PRICES: dict[str, float] = {
    "together-flux": 0.003,
    "siliconflow-flux": 0.002,
    "edge-tts": 0.0,
}


# ---------------------------------------------------------------------------
# 单条调用记录
# ---------------------------------------------------------------------------

@dataclass
class CallRecord:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    count: int = 1
    cost: float = 0.0


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------

class CostTracker:
    """追踪 LLM / 图片 / TTS 等 API 调用费用。"""

    def __init__(self) -> None:
        self._records: list[CallRecord] = []

    # ------------------------------------------------------------------
    # 记录
    # ------------------------------------------------------------------

    def add_call(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        count: int = 1,
    ) -> None:
        """记录一次 API 调用。未知模型按 0 费用处理并打印警告。

        对于 token 计费模型（如 gpt-4o），费用根据 input/output_tokens 计算，
        count 仅用于统计调用次数。
        对于按次计费模型（如 together-flux），费用 = 单价 × count。
        """
        # 负数视为 0
        input_tokens = max(input_tokens, 0)
        output_tokens = max(output_tokens, 0)
        count = max(count, 0)

        cost = self._calc_cost(model, input_tokens, output_tokens, count)
        self._records.append(
            CallRecord(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                count=count,
                cost=cost,
            )
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def total_cost(self) -> float:
        """返回累计总费用（美元）。"""
        return sum(r.cost for r in self._records)

    def get_breakdown(self) -> dict[str, float]:
        """按模型汇总费用。"""
        breakdown: dict[str, float] = {}
        for r in self._records:
            breakdown[r.model] = breakdown.get(r.model, 0.0) + r.cost
        return breakdown

    def get_summary(self) -> dict[str, Any]:
        """完整摘要: 总费用、分模型费用、调用次数。"""
        call_counts: dict[str, int] = {}
        for r in self._records:
            call_counts[r.model] = call_counts.get(r.model, 0) + r.count
        return {
            "total_cost": self.total_cost(),
            "breakdown": self.get_breakdown(),
            "call_counts": call_counts,
        }

    def to_dict(self) -> dict[str, Any]:
        """可序列化的字典，适合写入 JSON。"""
        return {
            "total_cost": self.total_cost(),
            "breakdown": self.get_breakdown(),
            "records": [
                {
                    "model": r.model,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "count": r.count,
                    "cost": r.cost,
                }
                for r in self._records
            ],
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_cost(
        model: str,
        input_tokens: int,
        output_tokens: int,
        count: int,
    ) -> float:
        """根据模型价格表计算单次调用费用。"""
        if model in TOKEN_PRICES:
            inp_price, out_price = TOKEN_PRICES[model]
            return (input_tokens * inp_price + output_tokens * out_price) / 1_000_000

        if model in PER_CALL_PRICES:
            return PER_CALL_PRICES[model] * count

        logger.warning("未知模型 '%s'，费用按 0 计算", model)
        return 0.0
