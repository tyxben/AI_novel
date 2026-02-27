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
