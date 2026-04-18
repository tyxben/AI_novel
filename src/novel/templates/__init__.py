"""小说模板和预设 - 统一导出"""

# ai_flavor_blacklist 已废弃（Phase 0 架构重构），但保留 import 以维持老调用路径可用。
# TODO(phase-1): StyleProfile 接管后删除下面这一行及 ai_flavor_blacklist.py。
from src.novel.templates.ai_flavor_blacklist import check_ai_flavor, get_blacklist
from src.novel.templates.outline_templates import get_template, list_templates
from src.novel.templates.rhythm_templates import get_rhythm
from src.novel.templates.style_presets import get_style, list_styles

__all__ = [
    "get_template",
    "list_templates",
    "get_style",
    "list_styles",
    "get_rhythm",
    # Deprecated — will be removed in Phase 1:
    "get_blacklist",
    "check_ai_flavor",
]
