# PPT HTML-First 渲染方案技术设计

## 1. 系统架构

### 1.1 整体流程

```
Pipeline 前半段（保持不变）
    ↓
SlideSpec 列表 + ThemeConfig
    ↓
┌─────────────────────────────────────────┐
│  HTMLRenderer                           │
│  - 读取 SlideSpec 列表                   │
│  - 应用主题样式                          │
│  - 生成 HTML 文件（所有页面）             │
└─────────────────────────────────────────┘
    ↓
HTML 文件（workspace/ppt/{project_id}/preview.html）
    ↓
┌─────────────────────────────────────────┐
│  Gradio Web UI (gr.HTML)                │
│  - 显示当前页                            │
│  - 翻页控制（prev/next/slider）          │
└─────────────────────────────────────────┘
    ↓
用户确认
    ↓
┌─────────────────────────────────────────┐
│  HTMLToPPTXConverter                    │
│  - Playwright 渲染每页 HTML → PNG        │
│  - BeautifulSoup 提取文字层              │
│  - python-pptx 组装 PPTX                 │
└─────────────────────────────────────────┘
    ↓
PPTX 文件（workspace/ppt/{project_id}/output.pptx）
```

### 1.2 模块职责

| 模块 | 文件路径 | 职责 | 依赖 |
|------|----------|------|------|
| HTMLRenderer | `src/ppt/html_renderer.py` | SlideSpec → HTML | jinja2, models |
| HTMLToPPTXConverter | `src/ppt/html_to_pptx.py` | HTML → PPTX | playwright, python-pptx, beautifulsoup4 |
| ImageAgent | `src/ppt/image_agent.py` | 搜图/生图/背景 | imagegen, WebSearch |
| HTMLTemplateManager | `src/ppt/html_templates/` | HTML 布局模板 | jinja2 |
| TaskWorker (更新) | `src/task_queue/workers.py` | 后台任务调度 | HTMLRenderer, Converter |
| Web UI (更新) | `web.py` | 预览/导出界面 | gradio |

### 1.3 数据流

```python
# 阶段 1-7（现有流程）
DocumentAnalysis → ContentMap → PresentationPlan
  → SlideOutline → SlideContent → SlideDesign
  → list[SlideSpec]

# 阶段 8：配图生成（新增 ImageAgent）
SlideSpec + ImageAgent → image_path

# 阶段 9：HTML 渲染（新）
list[SlideSpec] + ThemeConfig
  → HTMLRenderer.render()
  → preview.html

# 阶段 10：PPTX 导出（新）
preview.html
  → HTMLToPPTXConverter.convert()
  → output.pptx
```

## 2. 核心模块设计

### 2.1 HTMLRenderer

#### 2.1.1 接口定义

```python
# src/ppt/html_renderer.py

from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from src.ppt.models import SlideSpec, ThemeConfig, LayoutType

class HTMLRenderer:
    """HTML 幻灯片渲染器"""

    def __init__(self, theme: ThemeConfig):
        """
        Args:
            theme: 主题配置
        """
        self.theme = theme
        self.template_env = self._setup_templates()

    def render(
        self,
        slides: list[SlideSpec],
        output_path: str | Path
    ) -> str:
        """渲染所有幻灯片为单个 HTML 文件

        Args:
            slides: 幻灯片规格列表
            output_path: 输出 HTML 文件路径

        Returns:
            HTML 文件路径（字符串）
        """
        # 1. 生成每页 HTML（调用布局模板）
        slide_htmls = []
        for slide in slides:
            html = self._render_slide(slide)
            slide_htmls.append(html)

        # 2. 组装完整 HTML 文档
        full_html = self._assemble_document(slide_htmls)

        # 3. 写入文件
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(full_html, encoding="utf-8")

        return str(output_path)

    def _render_slide(self, slide: SlideSpec) -> str:
        """渲染单页幻灯片

        Returns:
            <section class="slide">...</section> HTML 字符串
        """
        layout_template = self._get_layout_template(slide.design.layout)

        # 准备模板变量
        context = {
            "page_number": slide.page_number,
            "content": slide.content.model_dump(),
            "design": slide.design.model_dump(),
            "theme": self.theme.model_dump(),
            "image_path": slide.image_path,
        }

        return layout_template.render(**context)

    def _get_layout_template(self, layout: LayoutType):
        """获取布局模板"""
        template_name = f"{layout.value}.html"
        return self.template_env.get_template(template_name)

    def _assemble_document(self, slide_htmls: list[str]) -> str:
        """组装完整 HTML 文档（含 CSS/JS）"""
        base_template = self.template_env.get_template("base.html")

        return base_template.render(
            slides=slide_htmls,
            total_pages=len(slide_htmls),
            theme=self.theme.model_dump(),
            css=self._generate_css(),
            js=self._generate_js(),
        )

    def _generate_css(self) -> str:
        """生成全局 CSS（主题样式 + 布局样式）"""
        return f"""
        :root {{
            --color-primary: {self.theme.colors.primary};
            --color-secondary: {self.theme.colors.secondary};
            --color-accent: {self.theme.colors.accent};
            --color-text: {self.theme.colors.text};
            --color-background: {self.theme.colors.background};

            --font-title: '{self.theme.title_font.family}';
            --font-body: '{self.theme.body_font.family}';
            --font-note: '{self.theme.note_font.family}';
        }}

        /* 幻灯片容器 */
        .slide {{
            width: 1280px;
            height: 720px;
            background: var(--color-background);
            position: relative;
            overflow: hidden;
            page-break-after: always;
        }}

        /* 标题样式 */
        .slide h1 {{
            font-family: var(--font-title);
            font-size: {self.theme.title_font.size}px;
            font-weight: {'bold' if self.theme.title_font.bold else 'normal'};
            color: {self.theme.title_font.color};
            margin: 0;
        }}

        /* 正文样式 */
        .slide p, .slide li {{
            font-family: var(--font-body);
            font-size: {self.theme.body_font.size}px;
            color: {self.theme.body_font.color};
            line-height: 1.6;
        }}

        /* ... 更多全局样式 ... */
        """

    def _generate_js(self) -> str:
        """生成翻页控制 JavaScript"""
        return """
        let currentPage = 0;
        const slides = document.querySelectorAll('.slide');
        const totalPages = slides.length;

        function showSlide(n) {
            slides.forEach((slide, i) => {
                slide.style.display = (i === n) ? 'block' : 'none';
            });
            currentPage = n;
            updatePageInfo();
        }

        function nextSlide() {
            if (currentPage < totalPages - 1) {
                showSlide(currentPage + 1);
            }
        }

        function prevSlide() {
            if (currentPage > 0) {
                showSlide(currentPage - 1);
            }
        }

        function updatePageInfo() {
            document.getElementById('page-info').textContent =
                `${currentPage + 1} / ${totalPages}`;
        }

        // 键盘导航
        document.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowRight') nextSlide();
            if (e.key === 'ArrowLeft') prevSlide();
        });

        // 初始化
        showSlide(0);
        """

    def _setup_templates(self):
        """初始化 Jinja2 模板环境"""
        template_dir = Path(__file__).parent / "html_templates"
        env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True,  # 防止 XSS
        )
        # 添加自定义过滤器
        env.filters['escape_html'] = lambda s: (
            s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;')
             .replace('"', '&quot;')
             .replace("'", '&#39;')
        )
        return env
```

#### 2.1.2 HTML 模板结构

```
src/ppt/html_templates/
├── base.html                 # 文档框架（<html>, <head>, <body>）
├── title_hero.html           # 封面页布局
├── section_divider.html      # 章节分隔页
├── text_left_image_right.html
├── image_left_text_right.html
├── full_image_overlay.html
├── three_columns.html
├── quote_page.html
├── data_highlight.html
├── timeline.html
├── bullet_with_icons.html
├── comparison.html
└── closing.html
```

**base.html 示例**：
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PPT 预览</title>
    <style>
        {{ css|safe }}
    </style>
</head>
<body>
    <div id="slide-container">
        {% for slide_html in slides %}
        {{ slide_html|safe }}
        {% endfor %}
    </div>

    <div id="controls">
        <button onclick="prevSlide()">⬅ 上一页</button>
        <span id="page-info"></span>
        <button onclick="nextSlide()">下一页 ➡</button>
    </div>

    <script>
        {{ js|safe }}
    </script>
</body>
</html>
```

**title_hero.html 示例**：
```html
<section class="slide slide-title-hero" data-page="{{ page_number }}">
    {% if design.decoration.has_background_shape %}
    <div class="bg-decoration" style="
        background: linear-gradient(135deg,
            {{ theme.colors.primary }}00,
            {{ theme.colors.primary }}40);
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 40%;
        z-index: 0;
    "></div>
    {% endif %}

    <div class="content-wrapper" style="
        position: relative;
        z-index: 1;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        height: 100%;
        padding: {{ design.padding.top }}px {{ design.padding.right }}px
                 {{ design.padding.bottom }}px {{ design.padding.left }}px;
    ">
        <h1 style="
            font-size: {{ design.title_font.size }}px;
            color: {{ design.title_font.color }};
            font-weight: {{ 'bold' if design.title_font.bold else 'normal' }};
            margin-bottom: 20px;
        ">{{ content.title|escape_html }}</h1>

        {% if content.subtitle %}
        <p class="subtitle" style="
            font-size: {{ design.body_font.size }}px;
            color: {{ design.body_font.color }};
        ">{{ content.subtitle|escape_html }}</p>
        {% endif %}
    </div>
</section>
```

### 2.2 HTMLToPPTXConverter

#### 2.2.1 接口定义

```python
# src/ppt/html_to_pptx.py

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches

# Lazy import (可选依赖)
try:
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


class HTMLToPPTXConverter:
    """HTML 幻灯片转 PPTX"""

    def __init__(
        self,
        workspace: str = "workspace",
        extract_text: bool = True,
    ):
        """
        Args:
            workspace: 工作目录
            extract_text: 是否提取文字层到 notes
        """
        if not _HAS_PLAYWRIGHT:
            raise ImportError(
                "需要安装 Playwright:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )

        self.workspace = Path(workspace)
        self.extract_text = extract_text and _HAS_BS4

    def convert(
        self,
        html_path: str | Path,
        output_path: str | Path,
        progress_callback=None,
    ) -> str:
        """将 HTML 幻灯片转换为 PPTX

        Args:
            html_path: HTML 文件路径
            output_path: 输出 PPTX 路径
            progress_callback: 进度回调 fn(page_num, total, message)

        Returns:
            PPTX 文件路径
        """
        html_path = Path(html_path)
        output_path = Path(output_path)

        # 1. 解析 HTML，获取页面数量
        html_content = html_path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html_content, "html.parser") if _HAS_BS4 else None
        slides = soup.find_all("section", class_="slide") if soup else []
        total_pages = len(slides)

        if total_pages == 0:
            raise ValueError("HTML 文件中未找到幻灯片（.slide）")

        # 2. 创建临时截图目录
        screenshots_dir = self.workspace / "ppt" / "temp_screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        # 3. 用 Playwright 截图每页
        screenshot_paths = self._capture_screenshots(
            html_path,
            screenshots_dir,
            total_pages,
            progress_callback,
        )

        # 4. 提取文字层（可选）
        text_layers = []
        if self.extract_text and soup:
            text_layers = self._extract_text_layers(slides)

        # 5. 组装 PPTX
        pptx_path = self._assemble_pptx(
            screenshot_paths,
            text_layers,
            output_path,
            progress_callback,
        )

        # 6. 清理临时文件
        self._cleanup_screenshots(screenshots_dir)

        return str(pptx_path)

    def _capture_screenshots(
        self,
        html_path: Path,
        output_dir: Path,
        total_pages: int,
        progress_callback,
    ) -> list[Path]:
        """用 Playwright 截图每页幻灯片

        Returns:
            截图文件路径列表
        """
        screenshot_paths = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 720})

            # 加载 HTML
            page.goto(f"file://{html_path.resolve()}")
            page.wait_for_load_state("networkidle")

            # 截图每一页
            for i in range(total_pages):
                if progress_callback:
                    progress_callback(
                        i + 1, total_pages,
                        f"正在截图第 {i+1}/{total_pages} 页..."
                    )

                # 切换到第 i 页
                page.evaluate(f"showSlide({i})")
                page.wait_for_timeout(500)  # 等待动画完成

                # 截图
                screenshot_path = output_dir / f"slide_{i+1:03d}.png"
                slide_element = page.query_selector(".slide")
                if slide_element:
                    slide_element.screenshot(path=str(screenshot_path))
                    screenshot_paths.append(screenshot_path)
                else:
                    raise RuntimeError(f"第 {i+1} 页元素未找到")

            browser.close()

        return screenshot_paths

    def _extract_text_layers(self, slides) -> list[str]:
        """从 HTML 中提取每页的文字内容

        Args:
            slides: BeautifulSoup 解析的 <section> 列表

        Returns:
            每页的文本摘要列表
        """
        text_layers = []

        for slide in slides:
            texts = []

            # 提取标题
            h1 = slide.find("h1")
            if h1:
                texts.append(f"# {h1.get_text(strip=True)}")

            # 提取副标题
            subtitle = slide.find(class_="subtitle")
            if subtitle:
                texts.append(f"## {subtitle.get_text(strip=True)}")

            # 提取要点
            bullets = slide.find_all("li")
            for li in bullets:
                texts.append(f"- {li.get_text(strip=True)}")

            # 提取段落
            paragraphs = slide.find_all("p")
            for p in paragraphs:
                if "subtitle" not in (p.get("class") or []):
                    texts.append(p.get_text(strip=True))

            text_layers.append("\n".join(texts))

        return text_layers

    def _assemble_pptx(
        self,
        screenshot_paths: list[Path],
        text_layers: list[str],
        output_path: Path,
        progress_callback,
    ) -> Path:
        """组装 PPTX 文件

        Args:
            screenshot_paths: 截图路径列表
            text_layers: 文字层列表
            output_path: 输出路径

        Returns:
            PPTX 文件路径
        """
        prs = Presentation()
        prs.slide_width = Inches(13.333)  # 16:9
        prs.slide_height = Inches(7.5)

        blank_layout = prs.slide_layouts[6]  # 空白布局

        for i, screenshot_path in enumerate(screenshot_paths):
            if progress_callback:
                progress_callback(
                    i + 1, len(screenshot_paths),
                    f"正在组装第 {i+1}/{len(screenshot_paths)} 页..."
                )

            # 添加空白页
            slide = prs.slides.add_slide(blank_layout)

            # 插入截图（全屏）
            slide.shapes.add_picture(
                str(screenshot_path),
                left=0, top=0,
                width=prs.slide_width,
                height=prs.slide_height,
            )

            # 添加文字层到 notes（可选）
            if text_layers and i < len(text_layers):
                notes_slide = slide.notes_slide
                notes_slide.notes_text_frame.text = text_layers[i]

        # 保存
        output_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(output_path))

        return output_path

    def _cleanup_screenshots(self, screenshots_dir: Path):
        """清理临时截图"""
        if screenshots_dir.exists():
            for png in screenshots_dir.glob("*.png"):
                png.unlink()
            screenshots_dir.rmdir()
```

### 2.3 ImageAgent

#### 2.3.1 接口定义

```python
# src/ppt/image_agent.py

from pathlib import Path
from typing import Literal
import logging

from src.ppt.models import SlideSpec, ThemeConfig, ImageRequest
from src.imagegen.image_generator import create_image_generator

# Lazy imports (可选依赖)
try:
    from src.tools import ToolSearch
    _HAS_WEBSEARCH = True
except ImportError:
    _HAS_WEBSEARCH = False

log = logging.getLogger("ppt")


class ImageAgent:
    """图片智能代理 - 搜图/生图/背景"""

    def __init__(
        self,
        config: dict,
        workspace: str = "workspace",
        mode: Literal["search", "generate", "auto"] = "auto",
    ):
        """
        Args:
            config: 项目配置（包含 imagegen 子键）
            workspace: 工作目录
            mode: 配图模式
              - search: 优先搜图
              - generate: 优先 AI 生图
              - auto: 根据场景自动选择
        """
        self.config = config
        self.workspace = Path(workspace)
        self.mode = mode

    def get_image(
        self,
        slide_spec: SlideSpec,
        project_id: str,
    ) -> str | None:
        """为幻灯片获取配图

        Args:
            slide_spec: 幻灯片规格
            project_id: 项目 ID

        Returns:
            图片路径（成功）或 None（失败/不需要图片）
        """
        # 1. 判断是否需要图片
        if not self._needs_image(slide_spec):
            return None

        # 2. 确定配图策略
        strategy = self._decide_strategy(slide_spec)

        # 3. 执行配图
        if strategy == "search":
            return self._search_image(slide_spec, project_id)
        elif strategy == "generate":
            return self._generate_image(slide_spec, project_id)
        elif strategy == "background":
            return self._generate_background(slide_spec, project_id)
        else:
            return None

    def _needs_image(self, slide_spec: SlideSpec) -> bool:
        """判断是否需要配图"""
        # 有明确 image_request
        if slide_spec.image_request:
            return True

        # 某些布局必须有图
        from src.ppt.models import LayoutType
        must_have_image = {
            LayoutType.FULL_IMAGE_OVERLAY,
            LayoutType.TEXT_LEFT_IMAGE_RIGHT,
            LayoutType.IMAGE_LEFT_TEXT_RIGHT,
        }
        if slide_spec.design.layout in must_have_image:
            return True

        return False

    def _decide_strategy(self, slide_spec: SlideSpec) -> str:
        """决定配图策略

        Returns:
            "search" | "generate" | "background" | "none"
        """
        layout = slide_spec.design.layout

        # 封面/结尾页 → 背景
        from src.ppt.models import LayoutType
        if layout in (LayoutType.TITLE_HERO, LayoutType.CLOSING):
            return "background"

        # 数据高亮 → 抽象背景
        if layout == LayoutType.DATA_HIGHLIGHT:
            return "background"

        # 其他内容页 → 根据 mode
        if self.mode == "search" and _HAS_WEBSEARCH:
            return "search"
        elif self.mode == "generate":
            return "generate"
        elif self.mode == "auto":
            # 自动策略：产品/技术主题用 AI 生图，其他搜图
            prompt = slide_spec.image_request.prompt if slide_spec.image_request else ""
            if any(kw in prompt.lower() for kw in ["product", "interface", "ui", "mockup"]):
                return "generate"
            else:
                return "search" if _HAS_WEBSEARCH else "generate"

        return "none"

    def _search_image(self, slide_spec: SlideSpec, project_id: str) -> str | None:
        """从 Web 搜索图片

        Returns:
            下载后的本地路径 或 None
        """
        if not _HAS_WEBSEARCH:
            log.warning("WebSearch 工具不可用，fallback 到 AI 生图")
            return self._generate_image(slide_spec, project_id)

        try:
            # 提取关键词（简化版，实际可用 LLM 生成）
            keywords = slide_spec.content.title

            # TODO: 调用 WebSearch 工具
            # search_results = ToolSearch().search(
            #     query=f"{keywords} high quality image",
            #     result_type="images",
            # )

            # TODO: 下载第一张图片
            # image_url = search_results[0]["url"]
            # image_path = self._download_image(image_url, project_id, slide_spec.page_number)

            # 暂时返回 None（待实现）
            log.warning("搜图功能待实现，fallback 到 AI 生图")
            return self._generate_image(slide_spec, project_id)

        except Exception as e:
            log.error(f"搜图失败: {e}，fallback 到 AI 生图")
            return self._generate_image(slide_spec, project_id)

    def _generate_image(self, slide_spec: SlideSpec, project_id: str) -> str | None:
        """AI 生成图片"""
        if not slide_spec.image_request:
            log.warning(f"第 {slide_spec.page_number} 页缺少 image_request，跳过")
            return None

        try:
            # 获取尺寸
            orientation = slide_spec.image_request.size
            if orientation.value == "landscape":
                width, height = 1024, 576
            elif orientation.value == "portrait":
                width, height = 576, 1024
            else:
                width, height = 768, 768

            # 配置生成器
            img_config = dict(self.config.get("imagegen", {}))
            img_config["width"] = width
            img_config["height"] = height

            generator = create_image_generator(img_config)
            image = generator.generate(prompt=slide_spec.image_request.prompt)

            # 保存
            save_path = (
                self.workspace / "ppt" / project_id / "images"
                / f"slide_{slide_spec.page_number:03d}.png"
            )
            save_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(save_path))

            log.info(f"第 {slide_spec.page_number} 页图片生成成功: {save_path}")
            return str(save_path)

        except Exception as e:
            log.error(f"第 {slide_spec.page_number} 页图片生成失败: {e}")
            return None

    def _generate_background(
        self,
        slide_spec: SlideSpec,
        project_id: str
    ) -> str | None:
        """生成背景图

        策略：
        1. 纯色/渐变 → 不需要实际图片（CSS 实现）
        2. 抽象图案 → AI 生成低分辨率背景（512x512）
        """
        # 简化处理：用 AI 生成抽象背景
        try:
            # 构造抽象背景 prompt
            theme_colors = slide_spec.design.colors
            prompt = (
                f"Abstract background, gradient blend of colors "
                f"{theme_colors.primary} and {theme_colors.secondary}, "
                f"soft geometric shapes, minimalist, clean, 4K"
            )

            # 生成低分辨率背景
            img_config = dict(self.config.get("imagegen", {}))
            img_config["width"] = 768
            img_config["height"] = 432

            generator = create_image_generator(img_config)
            image = generator.generate(prompt=prompt)

            # 保存
            save_path = (
                self.workspace / "ppt" / project_id / "images"
                / f"bg_slide_{slide_spec.page_number:03d}.png"
            )
            save_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(save_path))

            log.info(f"第 {slide_spec.page_number} 页背景生成成功")
            return str(save_path)

        except Exception as e:
            log.error(f"背景生成失败: {e}")
            # 降级：不生成图片，用 CSS 纯色
            return None
```

### 2.4 任务队列集成

#### 2.4.1 新增任务

```python
# src/task_queue/workers.py (新增部分)

def _run_ppt_render_html(params: dict, progress_cb) -> dict:
    """渲染 HTML 预览"""
    from src.ppt.html_renderer import HTMLRenderer
    from src.ppt.pipeline import PPTPipeline
    from src.ppt.theme_manager import ThemeManager

    pipeline = PPTPipeline(
        workspace=params.get("workspace", "workspace"),
        config=params.get("config", {}),
    )

    project_id = params["project_id"]
    theme_name = params.get("theme", "modern")

    # 加载 checkpoint，获取 SlideSpec 列表
    ckpt = pipeline.file_manager.load_checkpoint(project_id)
    if not ckpt:
        raise ValueError(f"项目 {project_id} checkpoint 不存在")

    data = ckpt.get("data", ckpt)
    stages = data.get("stages", {})

    # 重建 SlideSpec
    outlines = [SlideOutline(**d) for d in stages["outline"]["data"]]
    contents = [SlideContent(**d) for d in stages["content"]["data"]]
    designs = [SlideDesign(**d) for d in stages["design"]["data"]]

    slides = []
    for outline, content, design in zip(outlines, contents, designs):
        slide = SlideSpec(
            page_number=outline.page_number,
            content=content,
            design=design,
            needs_image=outline.needs_image,
        )
        slides.append(slide)

    # 渲染 HTML
    theme_mgr = ThemeManager()
    theme = theme_mgr.get_theme(theme_name)

    renderer = HTMLRenderer(theme)
    html_path = renderer.render(
        slides,
        output_path=pipeline.file_manager.get_html_path(project_id),
    )

    progress_cb(1.0, "HTML 预览生成完成")

    return {"html_path": html_path}


def _run_ppt_export(params: dict, progress_cb) -> dict:
    """导出 PPTX"""
    from src.ppt.html_to_pptx import HTMLToPPTXConverter
    from src.ppt.pipeline import PPTPipeline

    pipeline = PPTPipeline(
        workspace=params.get("workspace", "workspace"),
        config=params.get("config", {}),
    )

    project_id = params["project_id"]
    html_path = params["html_path"]

    def ppt_progress(page_num, total, message):
        progress = page_num / total
        progress_cb(progress, message)

    converter = HTMLToPPTXConverter(
        workspace=params.get("workspace", "workspace"),
        extract_text=params.get("extract_text", True),
    )

    output_path = converter.convert(
        html_path,
        output_path=pipeline.file_manager.get_output_path(project_id),
        progress_callback=ppt_progress,
    )

    return {"output_path": output_path}


# 修改现有任务
def _run_ppt_continue(params: dict, progress_cb) -> dict:
    """Continue PPT generation from a user-edited outline."""
    from src.ppt.pipeline import PPTPipeline
    from src.ppt.models import EditableOutline

    pipeline = PPTPipeline(
        workspace=params.get("workspace", "workspace"),
        config=params.get("config", {}),
    )

    def ppt_progress(stage, progress, message):
        progress_cb(progress, message)

    edited_outline = EditableOutline(**params["edited_outline"])

    # ========== 修改点：调用 HTML 渲染器而非 PPTRenderer ==========
    from src.ppt.html_renderer import HTMLRenderer
    from src.ppt.theme_manager import ThemeManager

    # ... (前半段流程不变，生成 SlideSpec 列表)

    # 渲染 HTML 而非 PPTX
    theme_mgr = ThemeManager()
    theme = theme_mgr.get_theme(params.get("theme", "modern"))
    renderer = HTMLRenderer(theme)
    html_path = renderer.render(
        slides,
        output_path=pipeline.file_manager.get_html_path(params["project_id"]),
    )

    # 更新 checkpoint
    checkpoint = {
        "project_id": params["project_id"],
        "status": "html_rendered",
        "html_path": html_path,
    }
    pipeline._save_checkpoint(params["project_id"], checkpoint)

    progress_cb(1.0, "HTML 预览生成完成！")

    return {
        "html_path": html_path,
        "project_id": params["project_id"],
    }
```

#### 2.4.2 FileManager 扩展

```python
# src/ppt/file_manager.py (新增方法)

class FileManager:
    # ... 现有方法 ...

    def get_html_path(self, project_id: str) -> Path:
        """获取 HTML 预览文件路径"""
        return self.projects_dir / project_id / "preview.html"

    def get_screenshot_dir(self, project_id: str) -> Path:
        """获取截图临时目录"""
        return self.projects_dir / project_id / "screenshots"
```

### 2.5 Web UI 集成

#### 2.5.1 新增组件

```python
# web.py (PPT Tab 部分修改)

# ========== 新增：HTML 预览区域 ==========
with gr.Group(visible=False) as ppt_preview_group:
    gr.Markdown("### 预览")

    # HTML 预览（当前页）
    ppt_preview_html = gr.HTML(
        value="<p>等待生成...</p>",
        elem_classes="ppt-preview",
    )

    # 翻页控制
    with gr.Row():
        ppt_prev_btn = gr.Button("⬅ 上一页", size="sm")
        ppt_page_slider = gr.Slider(
            label="页码",
            minimum=1,
            maximum=20,
            step=1,
            value=1,
            interactive=True,
        )
        ppt_next_btn = gr.Button("下一页 ➡", size="sm")

    ppt_page_info = gr.Textbox(
        label="当前页",
        value="1 / 20",
        interactive=False,
    )

    # 导出按钮
    with gr.Row():
        ppt_export_btn = gr.Button(
            "导出 PPTX",
            variant="primary",
            size="lg",
        )
        ppt_download_file = gr.File(
            label="下载 PPTX",
            visible=False,
        )


# ========== 事件处理 ==========

def _on_ppt_continue_complete(task: dict):
    """大纲确认后，HTML 预览生成完成"""
    html_path = task["result"]["html_path"]

    # 读取 HTML 内容（仅读取第一页）
    html_content = Path(html_path).read_text(encoding="utf-8")

    # 简化：直接显示完整 HTML（实际应提取单页）
    # 更好的实现：用 iframe 加载 HTML，通过 URL fragment 控制页码

    return {
        ppt_preview_html: gr.update(value=html_content),
        ppt_preview_group: gr.update(visible=True),
        ppt_page_slider: gr.update(maximum=20, value=1),  # 从 checkpoint 读取实际页数
        ppt_page_info: gr.update(value="1 / 20"),
    }


def _on_ppt_page_change(page_num: int, html_path: str):
    """翻页时更新预览"""
    # 方案1（简单）：重新加载 HTML，用 JS 控制显示第 N 页
    # 方案2（优雅）：用 iframe + URL fragment (#page=N)

    # 这里采用方案1（伪代码）
    html_content = Path(html_path).read_text(encoding="utf-8")
    # 插入 JS 代码切换到第 page_num 页
    html_with_js = html_content.replace(
        "</script>",
        f"showSlide({page_num - 1});</script>",
    )

    return gr.update(value=html_with_js)


def _on_ppt_export_click(project_id: str, html_path: str):
    """点击导出 PPTX"""
    from src.task_queue.client import TaskQueueClient

    client = TaskQueueClient()
    task_id = client.submit_task(
        task_type="ppt_export",
        params={
            "project_id": project_id,
            "html_path": html_path,
            "extract_text": True,
        },
    )

    return task_id, "PPTX 导出中..."


def _on_ppt_export_complete(task: dict):
    """PPTX 导出完成"""
    pptx_path = task["result"]["output_path"]

    return {
        ppt_download_file: gr.update(value=pptx_path, visible=True),
        ppt_status_box: gr.update(value="PPTX 导出完成！"),
    }


# 绑定事件
ppt_prev_btn.click(
    _on_ppt_page_change,
    inputs=[ppt_page_slider, gr.State()],  # gr.State 存储 html_path
    outputs=[ppt_preview_html],
)

ppt_next_btn.click(
    _on_ppt_page_change,
    inputs=[ppt_page_slider, gr.State()],
    outputs=[ppt_preview_html],
)

ppt_page_slider.change(
    _on_ppt_page_change,
    inputs=[ppt_page_slider, gr.State()],
    outputs=[ppt_preview_html],
)

ppt_export_btn.click(
    _on_ppt_export_click,
    inputs=[gr.State(), gr.State()],  # project_id, html_path
    outputs=[gr.State(), ppt_status_box],
)
```

## 3. 数据模型

### 3.1 现有模型（保持不变）

- `SlideSpec` — 完整页面规格
- `SlideContent` — 页面内容
- `SlideDesign` — 设计方案
- `ThemeConfig` — 主题配置
- `ColorScheme` / `FontSpec` / `DecorationSpec` — 样式规格
- `ImageRequest` — 图片生成请求

### 3.2 新增配置字段

#### HTMLRendererConfig（可选，暂不新增，用现有 ThemeConfig）

```python
# 无需新增，复用现有模型
```

## 4. 错误处理

### 4.1 Playwright 相关

| 错误场景 | 处理策略 | 用户提示 |
|---------|---------|---------|
| Playwright 未安装 | 导入时 raise ImportError | "需要安装 Playwright..." |
| 浏览器未安装 | 启动时捕获异常 | "需要运行 playwright install chromium" |
| 截图超时 | 设置 10 秒超时，跳过该页 | "第 X 页渲染超时，已跳过" |
| 浏览器崩溃 | 捕获异常，重启浏览器 | "浏览器崩溃，正在重试..." |

### 4.2 图片相关

| 错误场景 | 处理策略 | 用户提示 |
|---------|---------|---------|
| 图片加载失败 | 显示占位色块 | HTML 中显示"图片加载失败" |
| AI 生图失败 | 重试 1 次，失败则占位 | "第 X 页配图生成失败" |
| 搜图超时 | 10 秒超时，fallback 到 AI 生图 | "搜图超时，切换为 AI 生图" |
| 下载图片格式错误 | 验证 MIME 类型，拒绝非图片 | "下载的文件非图片格式" |

### 4.3 HTML 渲染相关

| 错误场景 | 处理策略 | 用户提示 |
|---------|---------|---------|
| 模板缺失 | raise FileNotFoundError | "布局模板 X 不存在" |
| 文本溢出 | CSS ellipsis，质量检查警告 | "第 X 页文本过长" |
| 字体缺失 | Fallback 到 Arial | 自动降级，不提示 |

## 5. 性能优化

### 5.1 HTML 渲染优化

- **模板缓存**: Jinja2 默认缓存已编译模板
- **CSS 压缩**: 生产环境移除注释和空格（可选）
- **图片懒加载**: 初次只渲染第 1 页，翻页时再加载（需修改 JS）

### 5.2 PPTX 转换优化

- **并行截图**: 暂不实现（Playwright 截图已较快）
- **PNG 压缩**: 用 Pillow 压缩 PNG（质量 85%）
- **批量处理**: 每 10 页保存一次 PPTX（防止内存溢出）

### 5.3 图片生成优化

- **缓存机制**: 相同 prompt 复用已生成图片
- **预生成**: 大纲阶段就启动图片生成（后台异步）
- **降级策略**: 生图失败时用纯色占位，不阻塞流程

## 6. 测试策略

### 6.1 单元测试

```python
# tests/ppt/test_html_renderer.py

def test_render_single_slide():
    """测试单页 HTML 渲染"""
    from src.ppt.html_renderer import HTMLRenderer
    from src.ppt.models import SlideSpec, SlideContent, SlideDesign, ThemeConfig

    # Mock 数据
    slide = SlideSpec(
        page_number=1,
        content=SlideContent(title="测试标题", bullet_points=["要点1", "要点2"]),
        design=SlideDesign(...),
    )
    theme = ThemeConfig(name="modern", ...)

    renderer = HTMLRenderer(theme)
    html = renderer._render_slide(slide)

    assert "<section class=\"slide\"" in html
    assert "测试标题" in html
    assert "要点1" in html


def test_html_to_pptx_conversion():
    """测试 HTML → PPTX 转换"""
    from src.ppt.html_to_pptx import HTMLToPPTXConverter

    # Mock HTML 文件
    html_path = "tests/fixtures/sample.html"
    output_path = "tests/output/test.pptx"

    converter = HTMLToPPTXConverter()
    result_path = converter.convert(html_path, output_path)

    assert Path(result_path).exists()
    assert Path(result_path).stat().st_size > 0


def test_image_agent_generate():
    """测试图片生成"""
    from src.ppt.image_agent import ImageAgent

    # Mock 配置
    config = {"imagegen": {"backend": "siliconflow"}}
    agent = ImageAgent(config, mode="generate")

    # Mock SlideSpec
    slide = SlideSpec(...)

    image_path = agent.get_image(slide, "test_project")

    assert image_path is None or Path(image_path).exists()
```

### 6.2 集成测试

```python
# tests/ppt/test_integration.py

def test_full_pipeline_with_html():
    """测试完整流程：大纲 → HTML 预览 → PPTX 导出"""
    from src.ppt.pipeline import PPTPipeline

    pipeline = PPTPipeline()

    # 生成大纲
    project_id, outline = pipeline.generate_outline_only(
        topic="测试主题",
        audience="business",
        scenario="quarterly_review",
    )

    # 继续生成（HTML 渲染）
    html_path = pipeline.continue_from_outline(
        project_id, outline, generate_images=False,
    )

    assert Path(html_path).exists()

    # 导出 PPTX
    from src.ppt.html_to_pptx import HTMLToPPTXConverter
    converter = HTMLToPPTXConverter()
    pptx_path = converter.convert(html_path, "tests/output/test.pptx")

    assert Path(pptx_path).exists()
```

### 6.3 E2E 测试（手动）

1. 启动 Web UI
2. 生成大纲 → 编辑 → 确认
3. 检查 HTML 预览正常显示
4. 翻页测试（上一页/下一页/slider）
5. 导出 PPTX → 下载 → PowerPoint 打开验证

## 7. 部署注意事项

### 7.1 依赖安装

```bash
# 基础依赖（已有）
pip install jinja2 pyyaml pydantic python-pptx

# 新增依赖
pip install playwright beautifulsoup4

# Playwright 浏览器（需单独安装）
playwright install chromium
```

### 7.2 Docker 环境

```dockerfile
# 需在 Dockerfile 中添加
RUN apt-get update && apt-get install -y \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2

RUN pip install playwright beautifulsoup4
RUN playwright install chromium --with-deps
```

### 7.3 权限配置

- Playwright 需要读写 /tmp 目录（截图临时文件）
- workspace/ppt/{project_id}/ 目录需要写权限

## 8. 未来扩展

### 8.1 实时协作编辑（V2）
- 多用户同时编辑大纲
- WebSocket 实时同步预览

### 8.2 交互式动画（V3）
- HTML 支持 CSS 动画（fade-in / slide-in）
- 导出时保留动画（视频格式）

### 8.3 云端渲染（V4）
- 用云端浏览器截图（避免本地安装 Playwright）
- API 服务化（HTML → PPTX as a Service）
