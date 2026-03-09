from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agents.state import Decision


def make_decision(
    agent: str,
    step: str,
    decision: str,
    reason: str,
    data: dict[str, Any] | None = None,
) -> Decision:
    """创建一条决策记录。不修改 state，返回 Decision 供节点收集后一并返回。"""
    return Decision(
        agent=agent,
        step=step,
        decision=decision,
        reason=reason,
        data=data,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def save_decisions_to_file(state: dict, filepath: str | Path) -> None:
    """将 state 中的决策日志保存为 JSON 文件。"""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    decisions = state.get("decisions", [])
    filepath.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")


def load_decisions_from_file(filepath: str | Path) -> list[dict]:
    """从 JSON 文件加载决策日志。"""
    filepath = Path(filepath)
    if not filepath.exists():
        return []
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return data


def extract_json_obj(text: str | None) -> dict | None:
    """从 LLM 输出中稳健提取 JSON 对象（支持嵌套）。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def extract_json_array(text: str | None) -> list | None:
    """从 LLM 输出中稳健提取 JSON 数组。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None
