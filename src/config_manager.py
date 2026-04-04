"""配置管理 - 加载和验证 YAML 配置"""

from pathlib import Path
from typing import Any
import yaml


_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    path = Path(path) if path else _DEFAULT_CONFIG
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError(
            f"配置文件内容无效（期望字典，得到 {type(cfg).__name__}）: {path}"
        )
    _validate(cfg)
    return cfg


def _validate(cfg: dict) -> None:
    required_sections = ["segmenter", "promptgen", "imagegen", "tts", "video"]
    for sec in required_sections:
        if sec not in cfg:
            raise ValueError(f"配置缺少必要字段: {sec}")

    res = cfg["video"].get("resolution")
    if not (isinstance(res, list) and len(res) == 2):
        raise ValueError("video.resolution 必须是 [width, height]")

    # agent 配置（可选）
    agent_cfg = cfg.get("agent")
    if agent_cfg is not None:
        if not isinstance(agent_cfg, dict):
            raise ValueError("agent 配置必须是字典")
        _validate_agent(agent_cfg)


def _validate_agent(agent_cfg: dict) -> None:
    """验证 agent 配置子字段。"""
    qc = agent_cfg.get("quality_check")
    if qc is not None:
        if not isinstance(qc, dict):
            raise ValueError("agent.quality_check 必须是字典")

        threshold = qc.get("threshold")
        if threshold is not None:
            if not isinstance(threshold, (int, float)) or not (0 <= threshold <= 10):
                raise ValueError("agent.quality_check.threshold 必须在 0-10 之间")

        max_retries = qc.get("max_retries")
        if max_retries is not None:
            if not isinstance(max_retries, int) or not (0 <= max_retries <= 10):
                raise ValueError("agent.quality_check.max_retries 必须是 0-10 的整数")

        vision_provider = qc.get("vision_provider")
        if vision_provider is not None and vision_provider not in ("openai", "gemini"):
            raise ValueError("agent.quality_check.vision_provider 必须是 openai 或 gemini")

    decisions = agent_cfg.get("decisions")
    if decisions is not None:
        if not isinstance(decisions, dict):
            raise ValueError("agent.decisions 必须是字典")

    budget = agent_cfg.get("budget_mode")
    if budget is not None:
        if not isinstance(budget, dict):
            raise ValueError("agent.budget_mode 必须是字典")

        _budget_bool_fields = [
            "disable_quality_check",
            "use_cheap_llm",
            "simple_emotion_analysis",
        ]
        for field in _budget_bool_fields:
            val = budget.get(field)
            if val is not None and not isinstance(val, bool):
                raise ValueError(
                    f"agent.budget_mode.{field} 必须是布尔值"
                )
