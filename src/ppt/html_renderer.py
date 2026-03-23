"""PPT HTML 渲染器 — 将 SlideSpec 列表渲染为可预览的 HTML 文件。

HTML-first approach: 先生成 HTML 幻灯片预览，再转换为 PPTX。
"""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from src.ppt.models import LayoutType, SlideSpec, ThemeConfig

logger = logging.getLogger("ppt")

# Layout enum value → template filename mapping
_LAYOUT_TEMPLATE_MAP: dict[LayoutType, str] = {
    LayoutType.TITLE_HERO: "title_hero.html",
    LayoutType.SECTION_DIVIDER: "section_divider.html",
    LayoutType.TEXT_LEFT_IMAGE_RIGHT: "text_left_image_right.html",
    LayoutType.IMAGE_LEFT_TEXT_RIGHT: "image_left_text_right.html",
    LayoutType.FULL_IMAGE_OVERLAY: "full_image_overlay.html",
    LayoutType.THREE_COLUMNS: "three_columns.html",
    LayoutType.QUOTE_PAGE: "quote_page.html",
    LayoutType.DATA_HIGHLIGHT: "data_highlight.html",
    LayoutType.TIMELINE: "timeline.html",
    LayoutType.BULLET_WITH_ICONS: "bullet_with_icons.html",
    LayoutType.COMPARISON: "comparison.html",
    LayoutType.CLOSING: "closing.html",
}

_TEMPLATE_DIR = Path(__file__).parent / "html_templates"


class HTMLRenderer:
    """将 SlideSpec 列表渲染为 HTML 幻灯片预览文件。

    用法::

        renderer = HTMLRenderer(theme)
        output = renderer.render(slides, "output/preview.html")
    """

    def __init__(self, theme: ThemeConfig) -> None:
        self.theme = theme
        self.env = self._setup_templates()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(self, slides: list[SlideSpec], output_path: str | Path) -> str:
        """渲染所有幻灯片并写入 HTML 文件。

        Args:
            slides: 幻灯片规格列表
            output_path: 输出 HTML 文件路径

        Returns:
            输出文件的绝对路径字符串
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        slide_htmls = [self._render_slide(slide) for slide in slides]
        html = self._assemble_document(slide_htmls)

        output_path.write_text(html, encoding="utf-8")
        logger.info("HTML preview rendered: %s (%d slides)", output_path, len(slides))
        return str(output_path.resolve())

    # ------------------------------------------------------------------
    # Internal: slide rendering
    # ------------------------------------------------------------------

    def _render_slide(self, slide: SlideSpec) -> str:
        """渲染单个幻灯片为 HTML 片段。"""
        template = self._get_layout_template(slide.design.layout)
        context = {
            "page_number": slide.page_number,
            "content": slide.content.model_dump(),
            "design": slide.design.model_dump(),
            "theme": self.theme.model_dump(),
            "image_path": slide.image_path,
        }
        return template.render(**context)

    def _get_layout_template(self, layout: LayoutType):
        """根据布局类型获取对应的 Jinja2 模板。"""
        filename = _LAYOUT_TEMPLATE_MAP.get(layout)
        if filename is None:
            raise FileNotFoundError(
                f"No template mapping for layout: {layout.value}"
            )
        try:
            return self.env.get_template(filename)
        except TemplateNotFound:
            raise FileNotFoundError(
                f"Template file not found: {filename}"
            )

    # ------------------------------------------------------------------
    # Internal: document assembly
    # ------------------------------------------------------------------

    def _assemble_document(self, slide_htmls: list[str]) -> str:
        """将幻灯片 HTML 片段组装为完整文档。"""
        base = self.env.get_template("base.html")
        return base.render(
            css=self._generate_css(),
            js=self._generate_js(),
            slides=slide_htmls,
        )

    def _generate_css(self) -> str:
        """生成全局 CSS 样式（含主题色 CSS 变量）。"""
        colors = self.theme.colors
        title_font = self.theme.title_font
        body_font = self.theme.body_font

        return f"""
/* CSS Variables from theme */
:root {{
    --color-primary: {colors.primary};
    --color-secondary: {colors.secondary};
    --color-accent: {colors.accent};
    --color-text: {colors.text};
    --color-background: {colors.background};
    --font-title: '{title_font.family}', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    --font-body: '{body_font.family}', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}}

/* Reset */
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}

body {{
    background: #f0f0f0;
    font-family: var(--font-body);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 20px;
}}

/* Slide container */
.slide-container {{
    width: 1280px;
    height: 720px;
    position: relative;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
    border-radius: 4px;
    overflow: hidden;
    background: #FFFFFF;
}}

/* Individual slide */
.slide {{
    width: 1280px;
    height: 720px;
    position: absolute;
    top: 0;
    left: 0;
    display: none;
    overflow: hidden;
}}

.slide.active {{
    display: block;
}}

/* Navigation */
.navigation {{
    display: flex;
    align-items: center;
    gap: 24px;
    margin-top: 20px;
    user-select: none;
}}

.nav-btn {{
    padding: 10px 24px;
    font-size: 14px;
    font-family: var(--font-body);
    color: #FFFFFF;
    background: var(--color-primary);
    border: none;
    border-radius: 6px;
    cursor: pointer;
    transition: opacity 0.2s;
}}

.nav-btn:hover {{
    opacity: 0.85;
}}

.page-info {{
    font-family: var(--font-body);
    font-size: 14px;
    color: #666;
    min-width: 60px;
    text-align: center;
}}
"""

    def _generate_js(self) -> str:
        """生成幻灯片导航 JavaScript。"""
        return """
var currentSlide = 0;

function showSlide(n) {
    var slides = document.querySelectorAll('.slide');
    if (slides.length === 0) return;
    if (n < 0) n = 0;
    if (n >= slides.length) n = slides.length - 1;
    for (var i = 0; i < slides.length; i++) {
        slides[i].classList.remove('active');
    }
    slides[n].classList.add('active');
    currentSlide = n;
    var info = document.getElementById('pageInfo');
    if (info) {
        info.textContent = (n + 1) + ' / ' + slides.length;
    }
}

function nextSlide() {
    showSlide(currentSlide + 1);
}

function prevSlide() {
    showSlide(currentSlide - 1);
}

document.addEventListener('keydown', function(e) {
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        nextSlide();
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        prevSlide();
    }
});

showSlide(0);
"""

    # ------------------------------------------------------------------
    # Internal: template setup
    # ------------------------------------------------------------------

    def _setup_templates(self) -> Environment:
        """创建 Jinja2 环境，加载 HTML 模板目录。"""
        if not _TEMPLATE_DIR.is_dir():
            raise FileNotFoundError(
                f"Template directory not found: {_TEMPLATE_DIR}"
            )
        return Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
