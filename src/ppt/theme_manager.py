"""主题管理器 - 加载和应用主题配置"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from src.ppt.models import (
    ColorScheme,
    DecorationSpec,
    FontSpec,
    ThemeConfig,
)

log = logging.getLogger("ppt")


class ThemeManager:
    """主题管理器，加载和应用主题配置。

    内置主题以 YAML 文件形式存放在 ``src/ppt/themes/`` 目录下。
    """

    THEMES_DIR: Path = Path(__file__).parent / "themes"

    def __init__(self) -> None:
        self._themes: dict[str, ThemeConfig] = {}
        self._load_builtin_themes()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def get_theme(self, name: str) -> ThemeConfig:
        """获取主题配置。

        Args:
            name: 主题名称（如 ``modern``、``business``）。

        Returns:
            对应的 ``ThemeConfig`` 对象。

        Raises:
            KeyError: 主题不存在时抛出。
        """
        if name not in self._themes:
            available = ", ".join(sorted(self._themes.keys()))
            raise KeyError(
                f"主题 '{name}' 不存在，可用主题: {available}"
            )
        return self._themes[name].model_copy(deep=True)

    def list_themes(self) -> list[str]:
        """列出可用主题名称。"""
        return sorted(self._themes.keys())

    def load_brand_template(self, template_path: str) -> ThemeConfig:
        """从企业品牌模板文件加载主题配置。

        品牌模板 YAML 格式与内置主题相同，额外支持 ``brand_logo`` 和
        ``footer_text`` 字段。

        Args:
            template_path: YAML 文件路径。

        Returns:
            ThemeConfig 对象。

        Raises:
            FileNotFoundError: 文件不存在。
            ValueError: YAML 解析或转换失败。
        """
        path = Path(template_path)
        if not path.exists():
            raise FileNotFoundError(f"品牌模板文件不存在: {template_path}")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"品牌模板 YAML 解析失败: {exc}") from exc
        return self._yaml_to_theme_config(raw)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _load_builtin_themes(self) -> None:
        """加载 themes/ 目录下的 YAML 主题文件。"""
        if not self.THEMES_DIR.is_dir():
            log.warning("主题目录不存在: %s", self.THEMES_DIR)
            return
        for yaml_path in sorted(self.THEMES_DIR.glob("*.yaml")):
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                theme = self._yaml_to_theme_config(raw)
                self._themes[theme.name] = theme
                log.debug("加载主题: %s (%s)", theme.name, theme.display_name)
            except Exception:
                log.exception("加载主题文件失败: %s", yaml_path)

    @staticmethod
    def _yaml_to_theme_config(raw: dict[str, Any]) -> ThemeConfig:
        """将 YAML 原始字典转换为 ThemeConfig。

        YAML 结构（见 themes/*.yaml）与 ThemeConfig 的字段名不完全对应，
        此方法负责映射和填充默认值。
        """
        if not isinstance(raw, dict):
            raise ValueError("主题配置必须是字典格式")

        name = raw.get("name", "unnamed")
        display_name = raw.get("display_name", name)
        description = raw.get("description", "")

        # --- 颜色 ---
        colors_raw = raw.get("colors", {})
        colors = ColorScheme(
            primary=colors_raw.get("primary", "#2D3436"),
            secondary=colors_raw.get("secondary", "#636E72"),
            accent=colors_raw.get("accent", "#0984E3"),
            text=colors_raw.get("text_primary", "#2D3436"),
            background=colors_raw.get("background", "#FFFFFF"),
        )

        # --- 字体 ---
        fonts_raw = raw.get("fonts", {})
        title_raw = fonts_raw.get("title", {})
        body_raw = fonts_raw.get("body", {})
        caption_raw = fonts_raw.get("caption", {})

        title_font = FontSpec(
            size=min(title_raw.get("size", 44), 72),
            bold=title_raw.get("bold", True),
            color=colors.primary,
            family=title_raw.get("name", "Arial"),
        )
        body_font = FontSpec(
            size=min(body_raw.get("size", 20), 72),
            bold=body_raw.get("bold", False),
            color=colors.text,
            family=body_raw.get("name", "Arial"),
        )
        note_font = FontSpec(
            size=min(caption_raw.get("size", 14), 72),
            bold=caption_raw.get("bold", False),
            color=colors_raw.get("text_secondary", "#757575"),
            family=caption_raw.get("name", "Arial"),
        )

        # --- 装饰默认值 ---
        deco_raw = raw.get("decorations", {})
        decoration_defaults = DecorationSpec(
            has_divider=deco_raw.get("use_dividers", False),
            divider_color=colors.accent if deco_raw.get("use_dividers") else None,
            divider_width=2,
            has_background_shape=deco_raw.get("use_shapes", False),
            shape_type="gradient" if deco_raw.get("use_gradients") else "rectangle",
            shape_color=colors.primary if deco_raw.get("use_shapes") else None,
            shape_opacity=0.1,
        )

        # --- 品牌信息（可选） ---
        brand_logo = raw.get("brand_logo") or raw.get("brand", {}).get("logo")
        footer_text = raw.get("footer_text") or raw.get("footer", {}).get("text")

        return ThemeConfig(
            name=name,
            display_name=display_name,
            description=description,
            colors=colors,
            title_font=title_font,
            body_font=body_font,
            note_font=note_font,
            decoration_defaults=decoration_defaults,
            brand_logo=brand_logo,
            footer_text=footer_text,
        )
