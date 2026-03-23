# PPT HTML-First 渲染方案任务清单

## 任务依赖关系

```
M1: HTML 渲染器
  ├─ T1.1: 模板目录结构
  ├─ T1.2: base.html 框架
  ├─ T1.3: 12种布局模板
  ├─ T1.4: HTMLRenderer 类
  └─ T1.5: 单元测试

M2: PPTX 转换器
  ├─ T2.1: HTMLToPPTXConverter 类
  ├─ T2.2: Playwright 截图逻辑
  ├─ T2.3: 文字层提取
  ├─ T2.4: PPTX 组装
  └─ T2.5: 单元测试

M3: 图片 Agent (可并行)
  ├─ T3.1: ImageAgent 基础框架
  ├─ T3.2: AI 生图模式
  ├─ T3.3: 搜图模式
  ├─ T3.4: 背景生成
  └─ T3.5: 单元测试

M4: Web UI 集成 (依赖 M1)
  ├─ T4.1: 启用按钮
  ├─ T4.2: HTML 预览组件
  ├─ T4.3: 翻页控制
  ├─ T4.4: 导出按钮
  └─ T4.5: 事件绑定

M5: 任务队列集成 (依赖 M1, M2)
  ├─ T5.1: ppt_render_html 任务
  ├─ T5.2: ppt_export 任务
  ├─ T5.3: 修改 _run_ppt_continue
  └─ T5.4: FileManager 扩展

M6: 测试与文档
  ├─ T6.1: 集成测试
  ├─ T6.2: E2E 测试
  ├─ T6.3: 性能测试
  └─ T6.4: 文档更新
```

---

## M1: HTML 渲染器（P0，核心功能）

### T1.1: 创建模板目录结构
**优先级**: P0
**预计工时**: 0.5h
**依赖**: 无

**任务内容**:
- [ ] 创建目录 `src/ppt/html_templates/`
- [ ] 创建空白模板文件（13 个）:
  - [ ] `base.html` — 文档框架
  - [ ] `title_hero.html`
  - [ ] `section_divider.html`
  - [ ] `text_left_image_right.html`
  - [ ] `image_left_text_right.html`
  - [ ] `full_image_overlay.html`
  - [ ] `three_columns.html`
  - [ ] `quote_page.html`
  - [ ] `data_highlight.html`
  - [ ] `timeline.html`
  - [ ] `bullet_with_icons.html`
  - [ ] `comparison.html`
  - [ ] `closing.html`

**验收标准**:
- 所有模板文件存在
- 目录结构符合 Jinja2 约定

---

### T1.2: 实现 base.html 文档框架
**优先级**: P0
**预计工时**: 2h
**依赖**: T1.1

**任务内容**:
- [ ] 编写 `base.html` 模板:
  - [ ] `<html>` / `<head>` / `<body>` 结构
  - [ ] CSS variables 定义（`--color-primary` 等）
  - [ ] 全局样式（字体 / 布局 / reset.css）
  - [ ] 幻灯片容器 `<div id="slide-container">`
  - [ ] 翻页控制 UI（上一页/下一页按钮 + 页码显示）
  - [ ] 插入 `{{ css|safe }}` 和 `{{ js|safe }}` 占位符
- [ ] 编写翻页控制 JavaScript:
  - [ ] `showSlide(n)` 函数
  - [ ] `nextSlide()` / `prevSlide()` 函数
  - [ ] 键盘导航（ArrowLeft / ArrowRight）
  - [ ] 页码信息更新

**验收标准**:
- 在浏览器中打开 base.html（手动插入测试内容），翻页功能正常
- CSS 变量正确应用
- 键盘导航正常工作

---

### T1.3: 实现 12 种布局模板
**优先级**: P0
**预计工时**: 8h（每个布局约 40 分钟）
**依赖**: T1.2

**任务内容**（每个布局独立子任务）:

#### T1.3.1: title_hero.html（封面页）
- [ ] 标题居中（大号字体）
- [ ] 副标题（可选）
- [ ] 底部渐变装饰（`design.decoration.has_background_shape`）
- [ ] 响应式布局（垂直居中）

#### T1.3.2: section_divider.html（章节分隔页）
- [ ] 标题居中
- [ ] 顶部/底部分割线（`design.decoration.divider_color`）
- [ ] 背景渐变（`design.decoration.shape_color`）

#### T1.3.3: text_left_image_right.html
- [ ] 左侧：标题 + 要点列表（`content.bullet_points`）
- [ ] 右侧：图片（`<img src="{{ image_path }}">` 或占位块）
- [ ] 左侧彩色竖线装饰（`design.decoration.divider_color`）
- [ ] 布局比例 5:5

#### T1.3.4: image_left_text_right.html
- [ ] 左侧：图片
- [ ] 右侧：标题 + 要点列表
- [ ] 布局比例 5:5

#### T1.3.5: full_image_overlay.html
- [ ] 全屏背景图片
- [ ] 标题叠加（白色文字 + 半透明黑色背景）
- [ ] 文字位置：底部或居中

#### T1.3.6: three_columns.html
- [ ] 三栏布局（`content.columns`）
- [ ] 每栏：图标（可选）+ 标题 + 描述
- [ ] 栏间分割线

#### T1.3.7: quote_page.html
- [ ] 大号引用文字（`content.quote`）
- [ ] 引用来源（`content.quote_author`）
- [ ] 左侧大引号装饰（CSS `::before`）
- [ ] 背景矩形装饰（`design.decoration.shape_color`）

#### T1.3.8: data_highlight.html
- [ ] 中央大号数据（`content.data_value`）
- [ ] 数据标签（`content.data_label`）
- [ ] 数据描述（`content.data_description`）
- [ ] 圆形背景装饰（`design.decoration.shape_color`）

#### T1.3.9: timeline.html
- [ ] 横向时间线（`content.steps`）
- [ ] 每个节点：圆点 + 标签 + 描述
- [ ] 连接线（CSS `::after`）

#### T1.3.10: bullet_with_icons.html
- [ ] 图标要点列表（`content.icon_items`）
- [ ] 每条：图标（Font Awesome 或 emoji）+ 文字
- [ ] 图标颜色使用 `design.colors.accent`

#### T1.3.11: comparison.html
- [ ] 左右对比布局
- [ ] 左栏：标题（`content.left_title`）+ 要点（`content.left_items`）
- [ ] 右栏：标题（`content.right_title`）+ 要点（`content.right_items`）
- [ ] 中间分割线

#### T1.3.12: closing.html
- [ ] 标题（如"谢谢"）
- [ ] 联系信息（`content.contact_info`）
- [ ] 底部渐变装饰

**验收标准**（每个布局）:
- 模板语法正确（Jinja2）
- 样式美观，符合设计规范
- 在浏览器中手动测试（插入 Mock 数据）
- 图片缺失时显示占位色块

---

### T1.4: 实现 HTMLRenderer 类
**优先级**: P0
**预计工时**: 4h
**依赖**: T1.3

**任务内容**:
- [ ] 创建文件 `src/ppt/html_renderer.py`
- [ ] 实现 `HTMLRenderer` 类:
  - [ ] `__init__(theme: ThemeConfig)`
  - [ ] `render(slides: list[SlideSpec], output_path: str) -> str`
  - [ ] `_render_slide(slide: SlideSpec) -> str`
  - [ ] `_get_layout_template(layout: LayoutType)`
  - [ ] `_assemble_document(slide_htmls: list[str]) -> str`
  - [ ] `_generate_css() -> str`
  - [ ] `_generate_js() -> str`
  - [ ] `_setup_templates()`
- [ ] 添加 Jinja2 自定义过滤器:
  - [ ] `escape_html` — HTML 转义
  - [ ] `format_color` — 颜色格式化（如添加 alpha 通道）
- [ ] 错误处理:
  - [ ] 模板缺失 → raise FileNotFoundError
  - [ ] 图片路径不存在 → 显示占位块
- [ ] 日志记录:
  - [ ] 记录渲染开始/完成
  - [ ] 记录模板加载失败

**验收标准**:
- 可渲染完整 HTML 文件（包含多页幻灯片）
- HTML 文件在浏览器中正常显示
- 翻页功能正常
- 主题样式正确应用

---

### T1.5: HTML 渲染器单元测试
**优先级**: P0
**预计工时**: 3h
**依赖**: T1.4

**任务内容**:
- [ ] 创建 `tests/ppt/test_html_renderer.py`
- [ ] 测试用例:
  - [ ] `test_init_renderer` — 初始化渲染器
  - [ ] `test_render_single_slide_title_hero` — 渲染封面页
  - [ ] `test_render_single_slide_text_left_image_right` — 渲染内容页
  - [ ] `test_render_multiple_slides` — 渲染多页
  - [ ] `test_generate_css` — 生成 CSS
  - [ ] `test_generate_js` — 生成 JS
  - [ ] `test_missing_template` — 模板缺失处理
  - [ ] `test_missing_image` — 图片缺失处理
  - [ ] `test_theme_colors_applied` — 主题颜色应用
  - [ ] `test_html_escape` — HTML 转义
- [ ] Mock 数据准备:
  - [ ] `fixtures/sample_theme.yaml`
  - [ ] `fixtures/sample_slides.json`

**验收标准**:
- 测试覆盖率 ≥80%
- 所有测试通过
- 边界情况覆盖（空要点 / 长标题 / 缺失字段）

---

## M2: PPTX 转换器（P0，核心功能）

### T2.1: 实现 HTMLToPPTXConverter 基础框架
**优先级**: P0
**预计工时**: 2h
**依赖**: 无

**任务内容**:
- [ ] 创建文件 `src/ppt/html_to_pptx.py`
- [ ] 实现 `HTMLToPPTXConverter` 类框架:
  - [ ] `__init__(workspace, extract_text)`
  - [ ] `convert(html_path, output_path, progress_callback) -> str`
  - [ ] `_capture_screenshots(...)` — 占位（返回空列表）
  - [ ] `_extract_text_layers(...)` — 占位（返回空列表）
  - [ ] `_assemble_pptx(...)` — 占位（创建空 PPTX）
  - [ ] `_cleanup_screenshots(...)`
- [ ] 添加依赖检查:
  - [ ] Playwright 导入检查（lazy import）
  - [ ] BeautifulSoup4 导入检查
  - [ ] 未安装时抛出友好的 ImportError

**验收标准**:
- 类可实例化
- 未安装依赖时报错信息正确
- `convert()` 方法可调用（虽然功能未实现）

---

### T2.2: 实现 Playwright 截图逻辑
**优先级**: P0
**预计工时**: 4h
**依赖**: T2.1

**任务内容**:
- [ ] 实现 `_capture_screenshots()` 方法:
  - [ ] 启动 Playwright chromium 浏览器（headless=True）
  - [ ] 设置 viewport: 1280x720
  - [ ] 加载 HTML 文件（`file://...`）
  - [ ] 等待页面加载完成（`wait_for_load_state("networkidle")`）
  - [ ] 循环截图每一页:
    - [ ] 调用 `page.evaluate(f"showSlide({i})")`
    - [ ] 等待 500ms（动画完成）
    - [ ] 截图 `.slide` 元素 → PNG
  - [ ] 保存到临时目录（`workspace/ppt/temp_screenshots/`）
  - [ ] 关闭浏览器
- [ ] 错误处理:
  - [ ] 浏览器启动失败 → 提示安装 chromium
  - [ ] 截图超时（10 秒）→ 跳过该页
  - [ ] 页面元素未找到 → raise RuntimeError
- [ ] 进度回调:
  - [ ] 每截图一页，调用 `progress_callback(i+1, total, message)`

**验收标准**:
- 可成功截图 HTML 文件（手动准备测试 HTML）
- PNG 文件尺寸正确（1280x720）
- 超时处理正常
- 进度回调正常触发

---

### T2.3: 实现文字层提取
**优先级**: P1
**预计工时**: 2h
**依赖**: T2.1

**任务内容**:
- [ ] 实现 `_extract_text_layers()` 方法:
  - [ ] 用 BeautifulSoup 解析 HTML
  - [ ] 查找所有 `.slide` 元素
  - [ ] 提取每页文本:
    - [ ] 标题（`h1`）
    - [ ] 副标题（`.subtitle`）
    - [ ] 要点（`li`）
    - [ ] 段落（`p`）
  - [ ] 组装为 Markdown 格式:
    ```
    # 标题
    ## 副标题
    - 要点1
    - 要点2
    段落文本
    ```
- [ ] 错误处理:
  - [ ] BeautifulSoup 未安装 → 返回空列表
  - [ ] HTML 解析失败 → 记录警告，返回空列表

**验收标准**:
- 可正确提取 HTML 中的文本
- Markdown 格式正确
- 特殊字符（引号/尖括号）正确转义

---

### T2.4: 实现 PPTX 组装
**优先级**: P0
**预计工时**: 3h
**依赖**: T2.2, T2.3

**任务内容**:
- [ ] 实现 `_assemble_pptx()` 方法:
  - [ ] 创建空白演示文稿（`Presentation()`）
  - [ ] 设置幻灯片尺寸（16:9，1280x720）
  - [ ] 使用空白布局（`slide_layouts[6]`）
  - [ ] 循环插入每页:
    - [ ] 添加空白页（`prs.slides.add_slide(blank_layout)`）
    - [ ] 插入 PNG 全屏图片（`add_picture(...)`）
      - left=0, top=0
      - width=prs.slide_width
      - height=prs.slide_height
    - [ ] 添加 notes（如果有文字层）
  - [ ] 保存 PPTX 文件
- [ ] 进度回调:
  - [ ] 每组装一页，调用 `progress_callback(i+1, total, message)`

**验收标准**:
- 生成的 PPTX 文件可在 PowerPoint 打开
- 每页包含全屏 PNG 图片
- notes 区域包含文字层（如果启用）
- 文件大小合理（<50MB for 20 pages）

---

### T2.5: PPTX 转换器单元测试
**优先级**: P0
**预计工时**: 3h
**依赖**: T2.4

**任务内容**:
- [ ] 创建 `tests/ppt/test_html_to_pptx.py`
- [ ] 准备测试 fixtures:
  - [ ] `fixtures/sample_preview.html` — 包含 3 页幻灯片
  - [ ] `fixtures/expected_screenshots/` — 预期截图（可选）
- [ ] 测试用例:
  - [ ] `test_init_converter` — 初始化
  - [ ] `test_playwright_not_installed` — Playwright 缺失
  - [ ] `test_capture_screenshots` — 截图功能
  - [ ] `test_extract_text_layers` — 文字提取
  - [ ] `test_assemble_pptx` — PPTX 组装
  - [ ] `test_convert_full_pipeline` — 完整流程
  - [ ] `test_screenshot_timeout` — 截图超时
  - [ ] `test_cleanup_screenshots` — 清理临时文件
- [ ] Mock Playwright（可选，避免真实浏览器启动）

**验收标准**:
- 测试覆盖率 ≥70%
- 所有测试通过
- 真实环境测试（安装 Playwright）通过

---

## M3: 图片 Agent（P1，增强功能）

### T3.1: 实现 ImageAgent 基础框架
**优先级**: P1
**预计工时**: 1.5h
**依赖**: 无

**任务内容**:
- [ ] 创建文件 `src/ppt/image_agent.py`
- [ ] 实现 `ImageAgent` 类框架:
  - [ ] `__init__(config, workspace, mode)`
  - [ ] `get_image(slide_spec, project_id) -> str | None`
  - [ ] `_needs_image(slide_spec) -> bool`
  - [ ] `_decide_strategy(slide_spec) -> str`
  - [ ] `_search_image(...)` — 占位
  - [ ] `_generate_image(...)` — 占位
  - [ ] `_generate_background(...)` — 占位
- [ ] 添加日志记录

**验收标准**:
- 类可实例化
- `get_image()` 可调用（返回 None）
- `_needs_image()` 逻辑正确

---

### T3.2: 实现 AI 生图模式
**优先级**: P1
**预计工时**: 2h
**依赖**: T3.1

**任务内容**:
- [ ] 实现 `_generate_image()` 方法:
  - [ ] 从 `slide_spec.image_request` 获取 prompt 和 size
  - [ ] 根据 orientation 设置尺寸:
    - landscape: 1024x576
    - portrait: 576x1024
    - square: 768x768
  - [ ] 调用 `create_image_generator(config)` 生成图片
  - [ ] 保存到 `workspace/ppt/{project_id}/images/slide_XXX.png`
- [ ] 错误处理:
  - [ ] 生成失败 → 记录日志，返回 None
  - [ ] 超时（60 秒）→ 返回 None

**验收标准**:
- 可成功生成图片（使用 SiliconFlow 后端）
- 图片尺寸正确
- 失败时返回 None，不抛异常

---

### T3.3: 实现搜图模式
**优先级**: P2（暂缓，优先 AI 生图）
**预计工时**: 4h
**依赖**: T3.1

**任务内容**:
- [ ] 实现 `_search_image()` 方法:
  - [ ] 提取关键词（从 `content.title` 或 LLM 生成）
  - [ ] 调用 WebSearch 工具（需集成 ToolSearch）
  - [ ] 提取搜索结果中的图片 URL
  - [ ] 下载图片（超时 10 秒）
  - [ ] 验证图片格式（JPEG/PNG/WebP）和尺寸（≥512px）
  - [ ] 保存到本地
- [ ] 版权处理:
  - [ ] 记录图片来源 URL 到 `image_metadata.json`
- [ ] 错误处理:
  - [ ] 搜索无结果 → fallback 到 AI 生图
  - [ ] 下载失败 → fallback 到 AI 生图

**验收标准**:
- 可成功搜索并下载图片
- Fallback 逻辑正常
- 元数据记录正确

---

### T3.4: 实现背景生成
**优先级**: P1
**预计工时**: 2h
**依赖**: T3.2

**任务内容**:
- [ ] 实现 `_generate_background()` 方法:
  - [ ] 构造抽象背景 prompt:
    ```
    Abstract background, gradient blend of {primary} and {secondary},
    soft geometric shapes, minimalist, clean, 4K
    ```
  - [ ] 生成低分辨率背景（768x432）
  - [ ] 保存到 `workspace/ppt/{project_id}/images/bg_slide_XXX.png`
- [ ] 降级策略:
  - [ ] 生成失败 → 返回 None（用 CSS 纯色）

**验收标准**:
- 可生成抽象背景图片
- 图片质量满足背景需求（不需要高清）

---

### T3.5: 图片 Agent 单元测试
**优先级**: P1
**预计工时**: 2h
**依赖**: T3.2, T3.4

**任务内容**:
- [ ] 创建 `tests/ppt/test_image_agent.py`
- [ ] 测试用例:
  - [ ] `test_init_agent`
  - [ ] `test_needs_image_true` — 需要图片
  - [ ] `test_needs_image_false` — 不需要图片
  - [ ] `test_decide_strategy_generate` — 策略选择
  - [ ] `test_generate_image_success` — AI 生图成功
  - [ ] `test_generate_image_failure` — AI 生图失败
  - [ ] `test_generate_background` — 背景生成
- [ ] Mock imagegen 后端（避免真实 API 调用）

**验收标准**:
- 测试覆盖率 ≥70%
- 所有测试通过
- Mock 策略合理

---

## M4: Web UI 集成（P0）

### T4.1: 启用 PPT Tab 按钮
**优先级**: P0
**预计工时**: 1h
**依赖**: 无

**任务内容**:
- [ ] 修改 `web.py`，删除"开发中"警告横幅:
  ```python
  # 删除或注释掉这段代码
  # gr.HTML('<div style="...">🚧 该功能正在开发中 🚧</div>')
  ```
- [ ] 启用按钮:
  - [ ] `ppt_outline_btn.update(interactive=True, value="生成大纲")`
  - [ ] `ppt_confirm_btn.update(interactive=True, value="确认并生成 PPT")`
  - [ ] `ppt_new_btn.update(interactive=True)`

**验收标准**:
- 警告横幅消失
- 按钮可点击

---

### T4.2: 添加 HTML 预览组件
**优先级**: P0
**预计工时**: 2h
**依赖**: T4.1

**任务内容**:
- [ ] 在 PPT Tab 右侧添加预览区域:
  ```python
  with gr.Group(visible=False) as ppt_preview_group:
      gr.Markdown("### 预览")
      ppt_preview_html = gr.HTML(value="<p>等待生成...</p>")
  ```
- [ ] 添加状态存储:
  - [ ] `ppt_html_path_state = gr.State("")` — 存储 HTML 路径
  - [ ] `ppt_current_page_state = gr.State(1)` — 当前页码
  - [ ] `ppt_total_pages_state = gr.State(1)` — 总页数

**验收标准**:
- 预览区域显示（初始隐藏）
- State 组件创建成功

---

### T4.3: 实现翻页控制
**优先级**: P0
**预计工时**: 3h
**依赖**: T4.2

**任务内容**:
- [ ] 添加翻页控制组件:
  ```python
  with gr.Row():
      ppt_prev_btn = gr.Button("⬅ 上一页", size="sm")
      ppt_page_slider = gr.Slider(label="页码", minimum=1, maximum=20, step=1, value=1)
      ppt_next_btn = gr.Button("下一页 ➡", size="sm")
  ppt_page_info = gr.Textbox(label="当前页", value="1 / 20", interactive=False)
  ```
- [ ] 实现翻页逻辑:
  ```python
  def _on_ppt_page_change(page_num: int, html_path: str, total_pages: int):
      # 方案1：重新加载 HTML，插入 JS 切换到第 N 页
      # 方案2：用 iframe + URL fragment (#page=N)

      # 采用方案1（简单）
      html_content = Path(html_path).read_text(encoding="utf-8")
      html_with_js = html_content.replace(
          "showSlide(0);",
          f"showSlide({page_num - 1});"
      )
      return gr.update(value=html_with_js), f"{page_num} / {total_pages}"
  ```
- [ ] 绑定事件:
  - [ ] `ppt_prev_btn.click(...)` — page_num - 1
  - [ ] `ppt_next_btn.click(...)` — page_num + 1
  - [ ] `ppt_page_slider.change(...)` — 直接跳转

**验收标准**:
- 点击上一页/下一页，预览更新
- Slider 拖动，预览同步
- 页码信息正确显示

---

### T4.4: 添加导出按钮
**优先级**: P0
**预计工时**: 2h
**依赖**: T4.2

**任务内容**:
- [ ] 添加导出按钮:
  ```python
  with gr.Row():
      ppt_export_btn = gr.Button("导出 PPTX", variant="primary", size="lg")
      ppt_download_file = gr.File(label="下载 PPTX", visible=False)
  ```
- [ ] 实现导出逻辑:
  ```python
  def _on_ppt_export_click(project_id: str, html_path: str):
      from src.task_queue.client import TaskQueueClient

      client = TaskQueueClient()
      task_id = client.submit_task(
          task_type="ppt_export",
          params={
              "project_id": project_id,
              "html_path": html_path,
              "extract_text": True,
          }
      )
      return task_id, "PPTX 导出中..."
  ```
- [ ] 轮询任务状态（复用现有 poll_timer）
- [ ] 任务完成时显示下载按钮:
  ```python
  def _on_ppt_export_complete(task: dict):
      pptx_path = task["result"]["output_path"]
      return {
          ppt_download_file: gr.update(value=pptx_path, visible=True),
          ppt_status_box: gr.update(value="PPTX 导出完成！"),
      }
  ```

**验收标准**:
- 点击导出按钮，任务提交成功
- 进度显示正常
- 任务完成后显示下载按钮
- 可下载 .pptx 文件

---

### T4.5: 事件绑定与状态管理
**优先级**: P0
**预计工时**: 2h
**依赖**: T4.3, T4.4

**任务内容**:
- [ ] 绑定"确认并生成 PPT"按钮:
  ```python
  ppt_confirm_btn.click(
      _on_ppt_confirm_submit,
      inputs=[...],  # 编辑后的大纲
      outputs=[ppt_status_box, ppt_task_id_state],
  )
  ```
- [ ] 任务完成时显示预览:
  ```python
  def _on_ppt_continue_complete(task: dict):
      html_path = task["result"]["html_path"]
      total_pages = task["result"]["total_pages"]  # 从 checkpoint 读取

      # 加载第 1 页
      html_content = Path(html_path).read_text(encoding="utf-8")

      return {
          ppt_preview_html: gr.update(value=html_content),
          ppt_preview_group: gr.update(visible=True),
          ppt_html_path_state: html_path,
          ppt_total_pages_state: total_pages,
          ppt_page_slider: gr.update(maximum=total_pages, value=1),
          ppt_page_info: gr.update(value=f"1 / {total_pages}"),
      }
  ```
- [ ] 修改 poll_timer 逻辑，增加 `ppt_export` 任务监听

**验收标准**:
- 大纲确认后自动显示预览
- 预览区域正确初始化（第 1 页）
- 导出完成后自动显示下载按钮

---

## M5: 任务队列集成（P0）

### T5.1: 实现 ppt_render_html 任务
**优先级**: P0
**预计工时**: 2h
**依赖**: M1（HTMLRenderer 完成）

**任务内容**:
- [ ] 修改 `src/task_queue/workers.py`，添加任务处理函数:
  ```python
  def _run_ppt_render_html(params: dict, progress_cb) -> dict:
      from src.ppt.html_renderer import HTMLRenderer
      from src.ppt.pipeline import PPTPipeline
      from src.ppt.theme_manager import ThemeManager

      # 加载 checkpoint，重建 SlideSpec 列表
      # 调用 HTMLRenderer.render()
      # 返回 html_path
  ```
- [ ] 在 `_route_task()` 中添加路由:
  ```python
  "ppt_render_html": _run_ppt_render_html,
  ```
- [ ] 添加进度回调

**验收标准**:
- 任务可提交并成功执行
- 返回正确的 html_path
- 进度回调正常

---

### T5.2: 实现 ppt_export 任务
**优先级**: P0
**预计工时**: 2h
**依赖**: M2（HTMLToPPTXConverter 完成）

**任务内容**:
- [ ] 修改 `src/task_queue/workers.py`，添加任务处理函数:
  ```python
  def _run_ppt_export(params: dict, progress_cb) -> dict:
      from src.ppt.html_to_pptx import HTMLToPPTXConverter

      def ppt_progress(page_num, total, message):
          progress_cb(page_num / total, message)

      converter = HTMLToPPTXConverter(...)
      output_path = converter.convert(...)

      return {"output_path": output_path}
  ```
- [ ] 在 `_route_task()` 中添加路由:
  ```python
  "ppt_export": _run_ppt_export,
  ```
- [ ] 添加进度回调（截图进度 + 组装进度）

**验收标准**:
- 任务可提交并成功执行
- 返回正确的 pptx_path
- 进度精确显示（如"第 5 / 20 页"）

---

### T5.3: 修改 _run_ppt_continue 任务
**优先级**: P0
**预计工时**: 1.5h
**依赖**: M1

**任务内容**:
- [ ] 修改 `_run_ppt_continue()` 函数:
  ```python
  # 原代码：
  # renderer = PPTRenderer(theme_config)
  # renderer.render(slides)
  # final_output = renderer.save(...)

  # 新代码：
  from src.ppt.html_renderer import HTMLRenderer

  renderer = HTMLRenderer(theme_config)
  html_path = renderer.render(
      slides,
      output_path=pipeline.file_manager.get_html_path(project_id)
  )

  # 更新 checkpoint
  checkpoint["status"] = "html_rendered"
  checkpoint["html_path"] = html_path

  return {"html_path": html_path, "project_id": project_id}
  ```
- [ ] 测试断点续传（resume 功能）

**验收标准**:
- 现有流程不受影响
- 返回 html_path 而非 pptx_path
- 断点续传正常

---

### T5.4: 扩展 FileManager
**优先级**: P0
**预计工时**: 0.5h
**依赖**: 无

**任务内容**:
- [ ] 修改 `src/ppt/file_manager.py`，添加方法:
  ```python
  def get_html_path(self, project_id: str) -> Path:
      """获取 HTML 预览文件路径"""
      return self.projects_dir / project_id / "preview.html"

  def get_screenshot_dir(self, project_id: str) -> Path:
      """获取截图临时目录"""
      return self.projects_dir / project_id / "screenshots"
  ```

**验收标准**:
- 方法可正常调用
- 返回路径正确

---

## M6: 测试与文档（P0）

### T6.1: 集成测试
**优先级**: P0
**预计工时**: 3h
**依赖**: M1, M2, M5

**任务内容**:
- [ ] 创建 `tests/ppt/test_integration.py`
- [ ] 测试用例:
  - [ ] `test_full_pipeline_topic_mode` — 完整流程（主题模式）
    - 生成大纲 → 编辑 → 确认 → HTML 预览 → PPTX 导出
  - [ ] `test_full_pipeline_document_mode` — 完整流程（文档模式）
  - [ ] `test_resume_from_checkpoint` — 断点续传
  - [ ] `test_quality_check_integration` — 质量检查集成
- [ ] 准备测试数据:
  - [ ] `fixtures/sample_topic.txt`
  - [ ] `fixtures/sample_document.txt`

**验收标准**:
- 所有集成测试通过
- 覆盖主要流程路径

---

### T6.2: E2E 测试（手动）
**优先级**: P0
**预计工时**: 2h
**依赖**: M4

**任务内容**:
- [ ] 启动 Web UI（`python web.py`）
- [ ] 测试场景 1：主题模式
  - [ ] 输入主题："2024年Q3季度业绩汇报"
  - [ ] 选择场景："季度汇报"
  - [ ] 点击"生成大纲"
  - [ ] 编辑大纲（修改第 3 页布局）
  - [ ] 点击"确认并生成 PPT"
  - [ ] 检查 HTML 预览显示
  - [ ] 翻页测试（上一页/下一页/slider）
  - [ ] 点击"导出 PPTX"
  - [ ] 下载 .pptx 文件，用 PowerPoint 打开验证
- [ ] 测试场景 2：文档模式
  - [ ] 上传文档（`tests/fixtures/sample_document.txt`）
  - [ ] 重复上述流程
- [ ] 测试场景 3：错误处理
  - [ ] 未安装 Playwright → 显示友好提示
  - [ ] 图片生成失败 → 占位块显示
  - [ ] 网络断开 → 任务失败提示

**验收标准**:
- 所有场景通过
- 无明显 UI 错误
- 错误提示友好

---

### T6.3: 性能测试
**优先级**: P1
**预计工时**: 2h
**依赖**: M1, M2

**任务内容**:
- [ ] 创建 `tests/ppt/test_performance.py`
- [ ] 测试用例:
  - [ ] `test_html_render_time_single_page` — 单页渲染 <100ms
  - [ ] `test_html_render_time_20_pages` — 20 页渲染 <2 秒
  - [ ] `test_pptx_conversion_time_20_pages` — 20 页转换 <100 秒
  - [ ] `test_html_file_size` — HTML 文件 <2MB（20 页）
  - [ ] `test_pptx_file_size` — PPTX 文件 <50MB（20 页）
- [ ] 使用 `pytest-benchmark` 或手动计时

**验收标准**:
- 所有性能指标达标
- 性能报告生成

---

### T6.4: 文档更新
**优先级**: P0
**预计工时**: 2h
**依赖**: M6.1, M6.2

**任务内容**:
- [ ] 更新 `CLAUDE.md`:
  - [ ] 添加 PPT HTML-first 方案说明
  - [ ] 更新依赖列表（playwright, beautifulsoup4）
  - [ ] 更新安装指令
- [ ] 更新 `README.md`（如果有）:
  - [ ] 添加 PPT 功能介绍
  - [ ] 添加使用示例
- [ ] 创建 `docs/ppt-html-rendering.md`（可选）:
  - [ ] 架构说明
  - [ ] 模板开发指南
  - [ ] 故障排查
- [ ] 添加代码注释（docstring）:
  - [ ] HTMLRenderer 所有公开方法
  - [ ] HTMLToPPTXConverter 所有公开方法
  - [ ] ImageAgent 所有公开方法

**验收标准**:
- CLAUDE.md 更新完整
- 代码注释符合 Google Style
- 文档无拼写错误

---

## 任务优先级总结

### P0（必须）— 核心流程
- M1: HTML 渲染器
- M2: PPTX 转换器
- M4: Web UI 集成
- M5: 任务队列集成
- M6: 测试与文档

### P1（重要）— 增强功能
- M3: 图片 Agent
- T2.3: 文字层提取

### P2（可选）— 未来优化
- T3.3: 搜图模式
- 性能优化（CSS 压缩 / 图片懒加载）

---

## 预估总工时

| 里程碑 | 总工时 | 并行度 | 实际天数（1人） |
|--------|--------|--------|----------------|
| M1: HTML 渲染器 | 18h | 低 | 2.5 天 |
| M2: PPTX 转换器 | 14h | 低 | 2 天 |
| M3: 图片 Agent | 11.5h | **可与 M1/M2 并行** | 1.5 天 |
| M4: Web UI 集成 | 10h | 依赖 M1 | 1.5 天 |
| M5: 任务队列集成 | 6h | 依赖 M1, M2 | 1 天 |
| M6: 测试与文档 | 9h | 依赖所有 | 1.5 天 |
| **总计** | **68.5h** | — | **10 天**（单人） |

**多人并行（建议）**:
- 开发者 A: M1（HTML 渲染器）
- 开发者 B: M2（PPTX 转换器）
- 开发者 C: M3（图片 Agent）
- 开发者 D: M4（Web UI）+ M5（任务队列）

**预计完成时间**: 5-7 天（4 人并行）

---

## 验收检查清单

### 功能完整性
- [ ] HTML 渲染器支持 12 种布局
- [ ] PPTX 转换器可截图并组装
- [ ] 图片 Agent 可生成配图（AI 模式）
- [ ] Web UI 预览正常（翻页功能）
- [ ] PPTX 导出正常（可下载）

### 质量标准
- [ ] 单元测试覆盖率 ≥80%（M1, M2）
- [ ] 集成测试通过（完整流程）
- [ ] E2E 测试通过（手动验证）
- [ ] 性能指标达标（见需求文档）

### 文档完整性
- [ ] CLAUDE.md 更新
- [ ] 代码注释完整
- [ ] API 文档生成（可选）

### 用户体验
- [ ] 按钮状态正确（禁用/启用）
- [ ] 进度提示清晰
- [ ] 错误提示友好
- [ ] 无明显 UI 卡顿

---

## 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| Playwright 截图性能差 | 导出慢 | 中 | 优化截图策略（减少等待时间） |
| HTML 渲染保真度低 | 与 PPTX 差异大 | 低 | 早期测试，迭代调整 CSS |
| 图片生成失败率高 | 用户体验差 | 中 | 降级策略（占位块） |
| Web UI 组件冲突 | 界面异常 | 低 | 充分测试，隔离状态 |
| 依赖安装困难（Playwright） | 用户无法使用 | 中 | 文档说明 + 友好报错 |

---

**结束**
