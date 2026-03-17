"""设计编排器 - 阶段4：为每页分配布局、配色、装饰元素"""

from __future__ import annotations

import logging
import random
import re
from typing import Any

from src.agents.utils import extract_json_obj
from src.llm import LLMClient, create_llm_client
from src.ppt.models import (
    ColorScheme,
    DecorationSpec,
    FontSpec,
    ImageOrientation,
    ImageRequest,
    LayoutType,
    SlideContent,
    SlideDesign,
    SlideOutline,
    ThemeConfig,
)

log = logging.getLogger("ppt")


# ---------------------------------------------------------------------------
# 布局 -> 装饰规则映射
# ---------------------------------------------------------------------------

def _decoration_for_layout(
    layout: LayoutType, theme: ThemeConfig
) -> DecorationSpec:
    """根据布局类型分配装饰元素。

    规则：
    - title_hero: 底部渐变色块
    - section_divider: 居中细线 + 渐变背景
    - 内容页（text_left_image_right / image_left_text_right / bullet_with_icons）:
        左侧彩色竖线 (accent color)
    - quote_page: 大引号装饰（用矩形色块模拟）
    - data_highlight: 背景圆形色块
    - closing: 底部渐变
    - 其它: 使用主题默认装饰
    """
    colors = theme.colors

    if layout == LayoutType.TITLE_HERO:
        return DecorationSpec(
            has_background_shape=True,
            shape_type="gradient",
            shape_color=colors.primary,
            shape_opacity=0.25,
        )

    if layout == LayoutType.SECTION_DIVIDER:
        return DecorationSpec(
            has_divider=True,
            divider_color=colors.accent,
            divider_width=3,
            has_background_shape=True,
            shape_type="gradient",
            shape_color=colors.primary,
            shape_opacity=0.1,
        )

    if layout in (
        LayoutType.TEXT_LEFT_IMAGE_RIGHT,
        LayoutType.IMAGE_LEFT_TEXT_RIGHT,
        LayoutType.BULLET_WITH_ICONS,
    ):
        return DecorationSpec(
            has_divider=True,
            divider_color=colors.accent,
            divider_width=2,
        )

    if layout == LayoutType.QUOTE_PAGE:
        return DecorationSpec(
            has_background_shape=True,
            shape_type="rectangle",
            shape_color=colors.secondary,
            shape_opacity=0.15,
        )

    if layout == LayoutType.DATA_HIGHLIGHT:
        return DecorationSpec(
            has_background_shape=True,
            shape_type="circle",
            shape_color=colors.accent,
            shape_opacity=0.12,
        )

    if layout == LayoutType.CLOSING:
        return DecorationSpec(
            has_background_shape=True,
            shape_type="gradient",
            shape_color=colors.primary,
            shape_opacity=0.2,
        )

    if layout == LayoutType.TIMELINE:
        return DecorationSpec(
            has_divider=True,
            divider_color=colors.secondary,
            divider_width=2,
        )

    if layout == LayoutType.COMPARISON:
        return DecorationSpec(
            has_divider=True,
            divider_color=colors.secondary,
            divider_width=1,
        )

    if layout == LayoutType.THREE_COLUMNS:
        return DecorationSpec(
            has_divider=True,
            divider_color=colors.secondary,
            divider_width=1,
        )

    # full_image_overlay 和其它：使用主题默认
    return theme.decoration_defaults.model_copy()


# ---------------------------------------------------------------------------
# 布局 -> 图片方向映射
# ---------------------------------------------------------------------------

_LAYOUT_IMAGE_ORIENTATION: dict[LayoutType, ImageOrientation] = {
    LayoutType.TITLE_HERO: ImageOrientation.LANDSCAPE,
    LayoutType.FULL_IMAGE_OVERLAY: ImageOrientation.LANDSCAPE,
    LayoutType.TEXT_LEFT_IMAGE_RIGHT: ImageOrientation.PORTRAIT,
    LayoutType.IMAGE_LEFT_TEXT_RIGHT: ImageOrientation.PORTRAIT,
    LayoutType.CLOSING: ImageOrientation.LANDSCAPE,
}


# ---------------------------------------------------------------------------
# 主题风格 -> 图片风格后缀
# ---------------------------------------------------------------------------

_THEME_IMAGE_STYLE: dict[str, str] = {
    "modern": "minimalist, clean background, modern flat design, high quality, 4K",
    "business": "professional photography style, corporate office, clean, high quality",
    "creative": "vibrant colors, artistic illustration, hand-drawn style, creative",
    "tech": "dark background, neon accents, futuristic, digital art, sci-fi aesthetic",
    "education": "cartoon illustration, friendly, colorful, educational diagram, clean",
}


class DesignOrchestrator:
    """为每页分配设计方案：配色、字体、装饰元素、图片需求"""

    def __init__(self, config: dict, theme_config: ThemeConfig):
        """初始化设计编排器。

        Args:
            config: 项目配置字典，需包含 ``llm`` 子键。
            theme_config: 主题配置对象。
        """
        self.llm: LLMClient = create_llm_client(config.get("llm", {}))
        self.theme = theme_config

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def orchestrate(
        self,
        contents: list[SlideContent],
        outlines: list[SlideOutline],
    ) -> list[SlideDesign]:
        """为每页生成设计方案。

        流程：
        1. 根据主题确定基础配色和字体
        2. 为每页分配具体装饰元素
        3. 生成图片需求
        4. 确保全篇视觉一致性

        Args:
            contents: 每页内容列表。
            outlines: 每页大纲列表（与 contents 等长）。

        Returns:
            与 *contents* 等长的 ``SlideDesign`` 列表。
            每个 SlideDesign 的 ``image_request`` 属性将在需要图片的页面中填充
            （作为返回值的附带信息，通过 ``get_image_requests`` 方法获取）。
        """
        designs: list[SlideDesign] = []
        self._image_requests: list[ImageRequest] = []

        for content, outline in zip(contents, outlines):
            layout = outline.layout
            decoration = self._assign_decorations(layout, self.theme)

            design = SlideDesign(
                layout=layout,
                colors=self.theme.colors.model_copy(),
                title_font=self.theme.title_font.model_copy(),
                body_font=self.theme.body_font.model_copy(),
                note_font=self.theme.note_font.model_copy(),
                decoration=decoration,
                padding={"left": 80, "right": 80, "top": 60, "bottom": 60},
            )

            # 图片需求
            if outline.needs_image:
                img_req = self._generate_image_prompt(
                    content, outline, self.theme
                )
                if img_req is not None:
                    self._image_requests.append(img_req)

            designs.append(design)

        # 视觉一致性检查
        designs = self._ensure_visual_consistency(designs)
        return designs

    def get_image_requests(self) -> list[ImageRequest]:
        """获取所有图片生成请求（调用 orchestrate 后可用）。"""
        return list(self._image_requests)

    # ------------------------------------------------------------------
    # 图片 prompt 生成
    # ------------------------------------------------------------------

    def _generate_image_prompt(
        self,
        content: SlideContent,
        outline: SlideOutline,
        theme: ThemeConfig,
    ) -> ImageRequest | None:
        """生成图片 prompt。

        - prompt 必须是英文
        - 包含风格描述（与主题一致）
        - 具体而非泛化
        - 指定方向
        """
        # 收集内容关键信息
        keywords_parts = [content.title]
        if content.bullet_points:
            keywords_parts.extend(content.bullet_points[:3])
        if content.body_text:
            keywords_parts.append(content.body_text)
        keywords = " ".join(keywords_parts)

        # 风格后缀
        style_suffix = _THEME_IMAGE_STYLE.get(
            theme.name, _THEME_IMAGE_STYLE["modern"]
        )

        # 方向
        orientation = _LAYOUT_IMAGE_ORIENTATION.get(
            outline.layout, ImageOrientation.LANDSCAPE
        )

        system_msg = (
            "You are an expert at writing image generation prompts. "
            "Given slide content in Chinese, write a detailed English prompt "
            "for generating a relevant illustration. "
            "The prompt should be 30-80 words, specific and visual. "
            "Do NOT use generic terms like 'business image'. "
            "Include composition, color palette, and style details. "
            "Return ONLY the prompt text, no explanation."
        )

        user_msg = (
            f"Slide title: {content.title}\n"
            f"Content keywords: {keywords}\n"
            f"Theme style: {theme.name}\n"
            f"Color palette: primary {theme.colors.primary}, "
            f"secondary {theme.colors.secondary}, "
            f"accent {theme.colors.accent}\n"
            f"Image orientation: {orientation.value}\n"
            f"Style suffix to include: {style_suffix}\n"
            f"\nWrite the image prompt:"
        )

        try:
            response = self.llm.chat(
                [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.6,
                max_tokens=200,
            )
            prompt_text = response.content.strip().strip('"').strip("'")
        except Exception:
            log.exception(
                "第%d页图片 prompt 生成失败，使用默认",
                outline.page_number,
            )
            prompt_text = (
                f"Abstract illustration related to {content.title}, "
                f"{style_suffix}"
            )

        # 确保非空
        if not prompt_text:
            prompt_text = (
                f"Abstract illustration related to {content.title}, "
                f"{style_suffix}"
            )

        return ImageRequest(
            page_number=outline.page_number,
            prompt=prompt_text,
            size=orientation,
            style=theme.name,
        )

    # ------------------------------------------------------------------
    # 装饰元素分配
    # ------------------------------------------------------------------

    def _assign_decorations(
        self, layout_type: LayoutType, theme: ThemeConfig
    ) -> DecorationSpec:
        """根据布局类型分配装饰元素（代理到模块级函数）。"""
        return _decoration_for_layout(layout_type, theme)

    # ------------------------------------------------------------------
    # 视觉一致性
    # ------------------------------------------------------------------

    def _ensure_visual_consistency(
        self, designs: list[SlideDesign]
    ) -> list[SlideDesign]:
        """确保全篇视觉一致：配色不超出主题色板，字体不混用。

        检查并强制修正：
        1. 所有页面使用相同的 ColorScheme
        2. 所有页面使用相同的字体家族
        3. 每页最多2个装饰元素（divider + background_shape）
        """
        base_colors = self.theme.colors
        title_family = self.theme.title_font.family
        body_family = self.theme.body_font.family

        for design in designs:
            # 强制统一配色
            design.colors = base_colors.model_copy()

            # 强制统一字体家族（保留大小和粗细差异）
            design.title_font.family = title_family
            design.body_font.family = body_family
            design.note_font.family = body_family

            # 检查装饰元素数量：最多2个
            deco = design.decoration
            decoration_count = int(deco.has_divider) + int(
                deco.has_background_shape
            )
            if decoration_count > 2:
                # 不太可能超过2，但作为安全措施
                log.warning(
                    "页面装饰元素过多（%d个），强制限制", decoration_count
                )

            # 验证装饰颜色在主题色板内
            valid_colors = {
                base_colors.primary,
                base_colors.secondary,
                base_colors.accent,
                base_colors.text,
                base_colors.background,
            }
            if (
                deco.divider_color
                and deco.divider_color not in valid_colors
            ):
                deco.divider_color = base_colors.accent
            if (
                deco.shape_color
                and deco.shape_color not in valid_colors
            ):
                deco.shape_color = base_colors.primary

        return designs
