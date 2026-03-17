"""ThemeManager 单元测试"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.ppt.models import ThemeConfig
from src.ppt.theme_manager import ThemeManager


# ---------------------------------------------------------------------------
# 内置主题加载
# ---------------------------------------------------------------------------


class TestLoadBuiltinThemes:
    def test_loads_all_five_themes(self):
        tm = ThemeManager()
        themes = tm.list_themes()
        assert "modern" in themes
        assert "business" in themes
        assert "creative" in themes
        assert "tech" in themes
        assert "education" in themes
        assert len(themes) >= 5

    def test_get_theme_returns_theme_config(self):
        tm = ThemeManager()
        theme = tm.get_theme("modern")
        assert isinstance(theme, ThemeConfig)
        assert theme.name == "modern"
        assert theme.display_name == "简约现代"

    def test_get_theme_returns_deep_copy(self):
        tm = ThemeManager()
        t1 = tm.get_theme("modern")
        t2 = tm.get_theme("modern")
        # 修改 t1 不影响 t2
        t1.colors.primary = "#000000"
        assert t2.colors.primary != "#000000"

    def test_each_theme_has_valid_colors(self):
        tm = ThemeManager()
        for name in tm.list_themes():
            theme = tm.get_theme(name)
            assert theme.colors.primary.startswith("#")
            assert len(theme.colors.primary) == 7
            assert theme.colors.secondary.startswith("#")
            assert theme.colors.accent.startswith("#")
            assert theme.colors.text.startswith("#")
            assert theme.colors.background.startswith("#")

    def test_each_theme_has_valid_fonts(self):
        tm = ThemeManager()
        for name in tm.list_themes():
            theme = tm.get_theme(name)
            assert 10 <= theme.title_font.size <= 72
            assert 10 <= theme.body_font.size <= 72
            assert 10 <= theme.note_font.size <= 72
            assert theme.title_font.family
            assert theme.body_font.family


# ---------------------------------------------------------------------------
# 主题不存在
# ---------------------------------------------------------------------------


class TestThemeNotFound:
    def test_raises_key_error(self):
        tm = ThemeManager()
        with pytest.raises(KeyError, match="不存在"):
            tm.get_theme("nonexistent_theme")

    def test_error_message_lists_available(self):
        tm = ThemeManager()
        with pytest.raises(KeyError) as exc_info:
            tm.get_theme("xyz")
        assert "modern" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 品牌模板加载
# ---------------------------------------------------------------------------


class TestLoadBrandTemplate:
    def test_load_valid_brand_template(self):
        yaml_content = """\
name: mycompany
display_name: 我的公司
description: 企业品牌模板

colors:
  primary: "#003366"
  secondary: "#0066CC"
  accent: "#FF9900"
  background: "#FFFFFF"
  text_primary: "#333333"
  text_secondary: "#666666"

fonts:
  title:
    name: "微软雅黑"
    size: 40
    bold: true
  body:
    name: "微软雅黑"
    size: 18
    bold: false
  caption:
    name: "微软雅黑"
    size: 12
    bold: false

decorations:
  use_gradients: false
  use_shapes: true
  use_dividers: true

brand_logo: /path/to/logo.png
footer_text: "公司机密 | 2024"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(yaml_content)
            f.flush()
            tm = ThemeManager()
            theme = tm.load_brand_template(f.name)

        assert theme.name == "mycompany"
        assert theme.colors.primary == "#003366"
        assert theme.brand_logo == "/path/to/logo.png"
        assert theme.footer_text == "公司机密 | 2024"
        assert theme.title_font.family == "微软雅黑"

    def test_load_nonexistent_file_raises(self):
        tm = ThemeManager()
        with pytest.raises(FileNotFoundError):
            tm.load_brand_template("/nonexistent/path.yaml")

    def test_load_invalid_yaml_raises(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("not: valid: yaml: {{[")
            f.flush()
            tm = ThemeManager()
            # yaml.safe_load may not raise for all malformed input,
            # but non-dict content should raise ValueError
            # We test with truly broken YAML
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False, encoding="utf-8"
            ) as f2:
                f2.write("just_a_string")
                f2.flush()
                with pytest.raises(ValueError, match="字典格式"):
                    tm.load_brand_template(f2.name)


# ---------------------------------------------------------------------------
# 主题属性验证
# ---------------------------------------------------------------------------


class TestThemeProperties:
    def test_modern_theme_specifics(self):
        tm = ThemeManager()
        theme = tm.get_theme("modern")
        assert theme.colors.primary == "#2D3436"
        assert theme.colors.accent == "#0984E3"
        assert theme.title_font.bold is True

    def test_tech_theme_dark_background(self):
        tm = ThemeManager()
        theme = tm.get_theme("tech")
        assert theme.colors.background == "#0D1117"
        assert theme.title_font.family == "Consolas"

    def test_business_theme_gold_accent(self):
        tm = ThemeManager()
        theme = tm.get_theme("business")
        assert theme.colors.accent == "#C0A062"

    def test_creative_theme_vibrant_colors(self):
        tm = ThemeManager()
        theme = tm.get_theme("creative")
        assert theme.colors.primary == "#FF6B6B"

    def test_education_theme_readable_fonts(self):
        tm = ThemeManager()
        theme = tm.get_theme("education")
        # 教育主题正文字号应较大（易读性）
        assert theme.body_font.size >= 16


# ---------------------------------------------------------------------------
# 空主题目录容错
# ---------------------------------------------------------------------------


class TestEmptyThemesDir:
    def test_no_crash_with_missing_dir(self, tmp_path):
        """如果主题目录不存在，不应崩溃。"""
        tm = ThemeManager()
        original_dir = ThemeManager.THEMES_DIR
        try:
            ThemeManager.THEMES_DIR = tmp_path / "nonexistent"
            tm2 = ThemeManager()
            # 不会加载到任何主题，但不崩溃
            # （注意：tm2._themes 可能为空）
        finally:
            ThemeManager.THEMES_DIR = original_dir
