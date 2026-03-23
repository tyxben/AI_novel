"""PPT 幻灯片图片智能代理 -- 搜图/AI生图/背景生成"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from src.ppt.models import ImageOrientation, LayoutType, SlideSpec

log = logging.getLogger("ppt")

try:
    from src.imagegen.image_generator import create_image_generator

    _HAS_IMAGEGEN = True
except ImportError:
    _HAS_IMAGEGEN = False

# 需要配图的布局类型
_IMAGE_LAYOUTS = frozenset(
    {
        LayoutType.FULL_IMAGE_OVERLAY,
        LayoutType.TEXT_LEFT_IMAGE_RIGHT,
        LayoutType.IMAGE_LEFT_TEXT_RIGHT,
    }
)

# 适合生成抽象背景的布局
_BACKGROUND_LAYOUTS = frozenset(
    {
        LayoutType.TITLE_HERO,
        LayoutType.CLOSING,
        LayoutType.DATA_HIGHLIGHT,
    }
)

# ImageOrientation -> (width, height)
_ORIENTATION_SIZES: dict[ImageOrientation, tuple[int, int]] = {
    ImageOrientation.LANDSCAPE: (1024, 576),
    ImageOrientation.PORTRAIT: (576, 1024),
    ImageOrientation.SQUARE: (768, 768),
}


class ImageAgent:
    """图片智能代理 - 为幻灯片自动搜索或生成配图"""

    def __init__(
        self,
        config: dict,
        workspace: str = "workspace",
        mode: Literal["search", "generate", "auto"] = "auto",
    ):
        self.config = config
        self.workspace = Path(workspace)
        self.mode = mode

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def get_image(self, slide_spec: SlideSpec, project_id: str) -> str | None:
        """为幻灯片获取配图。

        Args:
            slide_spec: 完整页面规格。
            project_id: 项目 ID，用于确定图片存储路径。

        Returns:
            生成/下载的图片文件路径，失败返回 None。
        """
        if not self._needs_image(slide_spec):
            return None

        strategy = self._decide_strategy(slide_spec)

        if strategy == "generate":
            return self._generate_image(slide_spec, project_id)
        elif strategy == "background":
            return self._generate_background(slide_spec, project_id)
        elif strategy == "search":
            return self._search_image(slide_spec, project_id)

        return None

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _needs_image(self, slide_spec: SlideSpec) -> bool:
        """判断幻灯片是否需要配图。"""
        # 有显式的 image_request -> 需要
        if slide_spec.image_request is not None:
            return True
        # 布局要求配图
        if slide_spec.design.layout in _IMAGE_LAYOUTS:
            return True
        # 标记了 needs_image
        if slide_spec.needs_image:
            return True
        # 适合背景的布局也视为需要
        if slide_spec.design.layout in _BACKGROUND_LAYOUTS:
            return True
        return False

    def _decide_strategy(self, slide_spec: SlideSpec) -> str:
        """决定配图策略。

        Returns:
            "search" | "generate" | "background" | "none"
        """
        layout = slide_spec.design.layout

        # 标题页 / 结束页 / 数据高亮 -> 抽象背景
        if layout in _BACKGROUND_LAYOUTS:
            return "background"

        # 其他内容页，根据 mode 决定
        if self.mode == "generate":
            return "generate"
        elif self.mode == "search":
            return "search"
        else:
            # auto 模式：默认生成（搜索尚未完整实现）
            return "generate"

    def _generate_image(
        self, slide_spec: SlideSpec, project_id: str
    ) -> str | None:
        """AI 生成内容配图。"""
        if not _HAS_IMAGEGEN:
            log.error("图片生成模块未安装，跳过生图")
            return None

        if slide_spec.image_request is None:
            log.warning(
                "Slide %d 需要配图但缺少 image_request，跳过",
                slide_spec.page_number,
            )
            return None

        prompt = slide_spec.image_request.prompt
        orientation = slide_spec.image_request.size
        width, height = _ORIENTATION_SIZES.get(
            orientation, (1024, 576)
        )

        gen_config = {**self.config, "width": width, "height": height}

        try:
            generator = create_image_generator(gen_config)
            image = generator.generate(prompt=prompt)
        except Exception:
            log.error(
                "Slide %d 图片生成失败", slide_spec.page_number, exc_info=True
            )
            return None

        # 保存图片
        filename = f"slide_{slide_spec.page_number:03d}.png"
        save_dir = self.workspace / "ppt" / project_id / "images"
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / filename

        try:
            image.save(str(save_path))
        except Exception:
            log.error(
                "Slide %d 图片保存失败: %s",
                slide_spec.page_number,
                save_path,
                exc_info=True,
            )
            return None

        log.info(
            "Slide %d 生成配图: %s", slide_spec.page_number, save_path
        )
        return str(save_path)

    def _generate_background(
        self, slide_spec: SlideSpec, project_id: str
    ) -> str | None:
        """生成抽象背景图。"""
        if not _HAS_IMAGEGEN:
            log.error("图片生成模块未安装，跳过背景生成")
            return None

        colors = slide_spec.design.colors
        prompt = (
            f"Abstract background, gradient blend of {colors.primary} "
            f"and {colors.secondary}, soft geometric shapes, "
            f"minimalist, clean, 4K"
        )

        width, height = 768, 432
        gen_config = {**self.config, "width": width, "height": height}

        try:
            generator = create_image_generator(gen_config)
            image = generator.generate(prompt=prompt)
        except Exception:
            log.error(
                "Slide %d 背景生成失败",
                slide_spec.page_number,
                exc_info=True,
            )
            return None

        filename = f"bg_slide_{slide_spec.page_number:03d}.png"
        save_dir = self.workspace / "ppt" / project_id / "images"
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / filename

        try:
            image.save(str(save_path))
        except Exception:
            log.error(
                "Slide %d 背景保存失败: %s",
                slide_spec.page_number,
                save_path,
                exc_info=True,
            )
            return None

        log.info(
            "Slide %d 生成背景: %s", slide_spec.page_number, save_path
        )
        return str(save_path)

    def _search_image(
        self, slide_spec: SlideSpec, project_id: str
    ) -> str | None:
        """从网络搜索图片（P2 占位实现，回退到 AI 生图）。"""
        log.warning(
            "图片搜索功能尚未实现，Slide %d 回退到 AI 生图",
            slide_spec.page_number,
        )
        return self._generate_image(slide_spec, project_id)
