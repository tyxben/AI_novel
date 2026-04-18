"""小说模板和预设 - 统一导出"""

from src.novel.templates.outline_templates import get_template, list_templates
from src.novel.templates.rhythm_templates import get_rhythm
from src.novel.templates.style_presets import get_style, list_styles

__all__ = [
    "get_template",
    "list_templates",
    "get_style",
    "list_styles",
    "get_rhythm",
]
