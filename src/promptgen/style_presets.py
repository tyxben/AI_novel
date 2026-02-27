"""风格预设 - Stable Diffusion 图片生成的风格关键词库"""

from pathlib import Path
from typing import Any

import yaml


# YAML 预设目录
_PRESETS_DIR = Path(__file__).resolve().parent.parent.parent / "presets" / "styles"

# 内建预设（当 YAML 文件缺失时的后备方案）
_BUILTIN_PRESETS: dict[str, dict[str, str]] = {
    "chinese_ink": {
        "positive": (
            "chinese ink painting, traditional art, elegant, "
            "flowing brushstrokes, mountain and water, silk texture"
        ),
        "negative": "photo, 3d render, cartoon, deformed, blurry, watermark, text",
        "prefix": "masterpiece ink painting of",
    },
    "anime": {
        "positive": (
            "anime style, detailed, vibrant colors, studio ghibli inspired, "
            "cel shading, beautiful scenery"
        ),
        "negative": "photo, 3d render, realistic, deformed, blurry, watermark, text, ugly",
        "prefix": "beautiful anime illustration of",
    },
    "realistic": {
        "positive": (
            "photorealistic, 8k, detailed, cinematic lighting, "
            "sharp focus, professional photography"
        ),
        "negative": "cartoon, anime, painting, drawing, deformed, blurry, watermark, text, ugly",
        "prefix": "cinematic photo of",
    },
    "watercolor": {
        "positive": (
            "watercolor painting, soft colors, artistic, dreamy, "
            "delicate, wet on wet technique"
        ),
        "negative": "photo, 3d render, cartoon, deformed, blurry, watermark, text, harsh lines",
        "prefix": "exquisite watercolor painting of",
    },
    "cyberpunk": {
        "positive": (
            "cyberpunk, neon lights, futuristic city, dark atmosphere, "
            "rain, holographic, high tech low life"
        ),
        "negative": "nature, countryside, bright, cheerful, deformed, blurry, watermark, text",
        "prefix": "cyberpunk scene of",
    },
}

# 运行时缓存（首次访问时加载）
_cache: dict[str, dict[str, str]] | None = None


def _load_presets() -> dict[str, dict[str, str]]:
    """从 YAML 文件加载预设，回退到内建预设。"""
    global _cache
    if _cache is not None:
        return _cache

    presets: dict[str, dict[str, str]] = {}

    # 先载入内建预设作为基础
    for name, preset in _BUILTIN_PRESETS.items():
        presets[name] = dict(preset)

    # 尝试从 YAML 文件覆盖/扩展
    if _PRESETS_DIR.is_dir():
        for yaml_file in _PRESETS_DIR.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data: dict[str, Any] = yaml.safe_load(f) or {}
                name = data.get("name", yaml_file.stem)
                presets[name] = {
                    "positive": str(data.get("positive", "")),
                    "negative": str(data.get("negative", "")),
                    "prefix": str(data.get("prefix", "")),
                }
            except Exception:
                # YAML 解析失败时跳过，保留内建预设
                continue

    _cache = presets
    return _cache


def get_preset(name: str) -> dict[str, str]:
    """获取指定名称的风格预设。

    Args:
        name: 预设名称（如 "chinese_ink", "anime" 等）。

    Returns:
        包含 positive / negative / prefix 三个键的字典。

    Raises:
        KeyError: 预设名称不存在。
    """
    presets = _load_presets()
    if name not in presets:
        available = ", ".join(sorted(presets.keys()))
        raise KeyError(f"未知风格预设 '{name}'，可选: {available}")
    return dict(presets[name])


def list_presets() -> list[str]:
    """列出所有可用预设的名称。

    Returns:
        预设名称列表，按字母排序。
    """
    return sorted(_load_presets().keys())
