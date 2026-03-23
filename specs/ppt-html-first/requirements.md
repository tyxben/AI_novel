# PPT HTML-First 渲染方案需求文档

## 1. 项目背景

### 1.1 现状
AI PPT 生成模块已完成后端流水线（约 10,000 行代码），包括：
- 9 阶段流水线：文档分析 → 内容提取 → 内容增强 → 演示计划 → 大纲生成 → 内容创作 → 设计编排 → 配图生成 → PPT 渲染
- 40+ Pydantic 数据模型（SlideSpec / SlideContent / SlideDesign / ColorScheme / FontSpec / DecorationSpec 等）
- 5 个视觉主题（modern / business / creative / tech / education）
- 12 种布局类型（title_hero / section_divider / text_left_image_right / data_highlight / timeline / comparison 等）
- 任务队列集成（_run_ppt_outline / _run_ppt_continue）
- Web UI 有 PPT Tab（但按钮禁用中）

### 1.2 问题
现有渲染器（`src/ppt/ppt_renderer.py`，997 行）直接用 python-pptx 拼坐标生成 PPTX：
- 布局调整困难，需要手动计算每个元素的 left / top / width / height
- 预览困难：用户无法在生成前看到最终效果
- 调试成本高：每次调整都需要重新生成完整 .pptx 文件
- 装饰元素（渐变 / 形状 / 分割线）实现复杂

### 1.3 新策略
采用 HTML-first 方案：
1. AI 生成 HTML 幻灯片（基于现有的 SlideSpec 数据）
2. 在 Gradio Web UI 中用 gr.HTML 组件预览
3. 用户确认后 HTML → PPTX 转换（Playwright 截图插入 PPTX）
4. 可选：提取文字层到 PPTX notes 区域（保持可搜索性）

## 2. 用户故事

### US-1: 快速预览生成结果
**作为** PPT 创作者
**我想要** 在生成 PPTX 之前先预览 HTML 版幻灯片
**以便于** 快速确认内容和布局是否符合预期，无需等待完整渲染

**验收标准**：
- 大纲确认后，系统生成 HTML 幻灯片（所有页面在一个文件中）
- Gradio Web UI 显示 HTML 预览区域（gr.HTML 组件）
- 支持翻页控制（上一页 / 下一页按钮）
- HTML 渲染保真度 ≥95%（与最终 PPTX 截图对比）
- 预览加载时间 <2 秒

### US-2: 编辑布局后实时反馈
**作为** PPT 创作者
**我想要** 修改大纲中的布局类型后立即看到效果
**以便于** 快速迭代设计方案

**验收标准**：
- 用户在大纲编辑器中修改布局字段
- 点击"重新生成预览"按钮后 HTML 更新
- 更新时间 <3 秒（无需重新调用 LLM）
- 保持现有内容不变，仅更新布局

### US-3: 导出高质量 PPTX
**作为** PPT 创作者
**我想要** 将确认后的 HTML 幻灯片导出为 .pptx 文件
**以便于** 在 PowerPoint / Keynote 中演示或进一步编辑

**验收标准**：
- 点击"导出 PPTX"按钮启动转换
- 每页 HTML 渲染为 1280x720 PNG（16:9 比例）
- PNG 插入 PPTX 为全屏图片（无边框 / 无压缩）
- 可选：文字层提取到 PPTX notes 区域
- 转换时间 ≤5 秒/页（20 页幻灯片 ≤100 秒）
- 输出 PPTX 文件大小 <50MB（20 页）

### US-4: 自动配图
**作为** PPT 创作者
**我想要** 系统自动为需要配图的页面搜索或生成图片
**以便于** 减少手动找图的时间

**验收标准**：
- Image Agent 分析每页内容，判断是否需要配图
- 搜图模式：从 Web 搜索提取图片 URL → 下载 → 缓存
- AI 生图模式：调用 `src/imagegen/` 统一接口生成
- 背景生成：支持纯色 / 渐变 / 纹理（CSS）+ AI 生成风景 / 抽象背景
- 图片尺寸自动适配布局（landscape: 1024x576 / portrait: 576x1024 / square: 768x768）
- 失败降级：无法获取图片时用占位色块

### US-5: 主题一致性
**作为** PPT 创作者
**我想要** 所有页面自动应用统一的主题风格
**以便于** 保持视觉专业性和一致性

**验收标准**：
- 支持现有 5 个主题（modern / business / creative / tech / education）
- HTML 渲染器读取主题 YAML 配置（colors / fonts / decorations）
- 所有页面使用相同的配色方案（primary / secondary / accent / text / background）
- 所有页面使用相同的字体家族（title_font / body_font / note_font）
- 装饰元素（divider / background_shape）样式统一

## 3. 功能需求

### FR-1: HTML 幻灯片渲染器
**优先级**: P0（必须）

**描述**：新建 `src/ppt/html_renderer.py`，替换现有 `ppt_renderer.py` 的职责。

**输入**：
- `slides: list[SlideSpec]` — 完整页面规格列表
- `theme: ThemeConfig` — 主题配置

**输出**：
- `html_path: str` — 完整 HTML 文件路径（所有幻灯片在一个文件中）

**核心功能**：
1. 渲染引擎：
   - 每页幻灯片为一个 `<section class="slide">` 元素
   - 幻灯片尺寸固定为 1280x720px（16:9 比例）
   - 支持 12 种布局的 HTML 模板（与现有布局类型一一对应）
   - CSS 实现装饰元素（渐变背景 / 分割线 / 形状）

2. 样式映射：
   - 主题配色 → CSS variables（`--color-primary`, `--color-secondary` 等）
   - 字体规格 → CSS font 属性（size / weight / color / family）
   - 装饰元素 → CSS background / border / pseudo-elements

3. 图片处理：
   - 支持本地文件路径（`<img src="file://...">` 或 base64 内联）
   - 支持远程 URL（`<img src="https://...">`)
   - 图片缺失时显示占位色块

4. 翻页控制：
   - 内置 JavaScript 实现 prev / next 按钮
   - 支持键盘导航（左/右箭头）
   - 显示当前页码 / 总页数

**非功能需求**：
- 单页渲染时间 <100ms
- HTML 文件大小 <2MB（不含 base64 图片）
- 支持 Chrome / Safari / Firefox 最新版

### FR-2: HTML → PPTX 转换器
**优先级**: P0（必须）

**描述**：新建 `src/ppt/html_to_pptx.py`，将 HTML 幻灯片转换为 PPTX 文件。

**输入**：
- `html_path: str` — HTML 文件路径
- `output_path: str` — 输出 PPTX 路径
- `extract_text: bool = True` — 是否提取文字层到 notes

**输出**：
- `pptx_path: str` — 生成的 PPTX 文件路径

**核心功能**：
1. 渲染截图：
   - 用 Playwright 加载 HTML 文件
   - 每页 `<section>` 截图为 PNG（1280x720）
   - 保存临时 PNG 文件到 workspace/ppt/{project_id}/screenshots/

2. PPTX 组装：
   - 用 python-pptx 创建空白演示文稿
   - 每页插入全屏图片（PNG）
   - 图片占满整个幻灯片（无边框 / 无留白）

3. 文字层提取（可选）：
   - 用 BeautifulSoup 解析 HTML，提取每页的文本内容
   - 写入对应 PPTX 页面的 notes 区域
   - 保持标题 / 要点 / 正文的层级结构

**依赖**：
- `playwright` — 需作为可选依赖（lazy import）
- 未安装时提示用户：`pip install playwright && playwright install chromium`

**非功能需求**：
- 转换速度 ≥0.2 页/秒（20 页 ≤100 秒）
- 输出 PPTX 文件大小 <50MB（20 页）
- 截图质量：PNG 保存质量 ≥90%

### FR-3: 图片 Agent
**优先级**: P1（重要）

**描述**：新建 `src/ppt/image_agent.py`，为幻灯片自动搜索或生成配图。

**输入**：
- `slide_spec: SlideSpec` — 单页规格
- `theme: ThemeConfig` — 主题配置
- `mode: Literal["search", "generate", "auto"]` — 配图模式

**输出**：
- `image_path: str | None` — 图片保存路径（失败返回 None）

**核心功能**：
1. 配图需求判断：
   - 根据 `slide_spec.image_request` 判断是否需要图片
   - 根据布局类型自动判断（如 FULL_IMAGE_OVERLAY 必须有图）

2. 搜图模式（mode="search"）：
   - 调用 WebSearch 工具搜索关键词
   - 提取搜索结果中的图片 URL（优先高分辨率 / 无水印）
   - 下载图片到本地（超时 10 秒）
   - 验证图片格式（JPEG / PNG / WebP）和尺寸（≥512px）

3. AI 生图模式（mode="generate"）：
   - 调用 `src/imagegen/create_image_generator()` 接口
   - 传入英文 prompt（从 `slide_spec.image_request.prompt` 获取）
   - 根据布局类型设置尺寸（landscape / portrait / square）
   - 保存生成的图片到 workspace/ppt/{project_id}/images/

4. 背景生成：
   - 纯色背景：直接用 CSS `background-color`
   - 渐变背景：CSS `linear-gradient` 或 `radial-gradient`
   - 纹理背景：CSS `repeating-linear-gradient` 或预置纹理图片
   - AI 背景：生成抽象风景 / 几何图案（低分辨率 512x512 即可）

5. 版权处理：
   - 搜图结果附带来源 URL（存入 `image_metadata.json`）
   - 可选：在 PPTX notes 中标注图片来源

**非功能需求**：
- 搜图成功率 ≥70%（对于常见主题）
- AI 生图成功率 ≥95%（依赖 imagegen 后端稳定性）
- 单张图片处理时间 <30 秒（搜图）或 <60 秒（AI 生图）
- 下载图片大小限制 <10MB

### FR-4: Web UI 更新
**优先级**: P0（必须）

**描述**：在 `web.py` 的 PPT Tab 中集成 HTML 预览和导出功能。

**核心功能**：
1. 启用按钮：
   - 移除"开发中"警告横幅
   - 启用"生成大纲"按钮（ppt_outline_btn）
   - 启用"确认并生成 PPT"按钮（ppt_confirm_btn）
   - 启用"新建"按钮（ppt_new_btn）

2. HTML 预览区域：
   - 添加 `gr.HTML()` 组件显示当前页幻灯片
   - 添加翻页控制：
     - `gr.Button("上一页")` / `gr.Button("下一页")`
     - `gr.Slider(label="页码", minimum=1, maximum=total_pages)`
   - 显示页码信息：`gr.Textbox(label="当前页", value="1 / 20")`

3. 导出按钮：
   - `gr.Button("导出 PPTX", variant="primary")`
   - 点击后提交 `ppt_export` 任务到后台队列
   - 任务完成后显示下载按钮：`gr.File(label="下载 PPTX")`

4. 状态提示：
   - 大纲生成中：显示进度条 `gr.Progress()`
   - HTML 预览生成中：显示"正在渲染预览..."
   - PPTX 导出中：显示"正在转换为 PPTX（第 X / Y 页）..."
   - 任务失败：显示错误信息 `gr.Warning()`

**交互流程**：
```
用户输入主题/文档
→ 点击"生成大纲"
→ 编辑大纲（可选）
→ 点击"确认并生成 PPT"
→ 显示 HTML 预览（可翻页）
→ 点击"导出 PPTX"
→ 下载 .pptx 文件
```

### FR-5: 任务队列集成
**优先级**: P0（必须）

**描述**：在 `src/task_queue/workers.py` 中新增 HTML 渲染和 PPTX 导出任务。

**新增任务类型**：
1. `ppt_render_html` — 渲染 HTML 预览
   - 输入：`project_id`, `theme`
   - 输出：`html_path`
   - 调用 `HTMLRenderer.render()`

2. `ppt_export` — 导出 PPTX
   - 输入：`project_id`, `html_path`, `output_path`, `extract_text`
   - 输出：`pptx_path`
   - 调用 `HTMLToPPTXConverter.convert()`

**修改现有任务**：
- `_run_ppt_continue()` — 在生成完 SlideSpec 后自动调用 HTML 渲染器（替代 PPTRenderer）

## 4. 边界情况

### BC-1: 图片加载失败
**场景**：图片 URL 无效 / 下载超时 / AI 生图失败

**处理**：
- HTML 渲染器显示占位色块（使用主题 accent 颜色）
- 占位块中显示图标 + 文字提示："图片加载失败"
- PPTX 导出时保留占位块（不留空白）

### BC-2: 文本溢出
**场景**：标题或要点过长，超出幻灯片边界

**处理**：
- HTML 使用 CSS `overflow: hidden` + `text-overflow: ellipsis`
- 鼠标悬停时显示完整文本（tooltip）
- 质量检查阶段标记为警告（现有 QualityChecker 已支持）

### BC-3: Playwright 未安装
**场景**：用户环境未安装 playwright

**处理**：
- 导入时捕获 ImportError
- 点击"导出 PPTX"时显示错误提示：
  ```
  需要安装 Playwright 才能导出 PPTX：
  pip install playwright
  playwright install chromium
  ```
- 提供降级方案：仅下载 HTML 文件

### BC-4: HTML 渲染超时
**场景**：Playwright 截图卡住 / 浏览器崩溃

**处理**：
- 设置截图超时时间（每页 10 秒）
- 超时后跳过该页，继续处理下一页
- 最终报告中标记失败的页面：`gr.Warning("第 X 页渲染失败")`

### BC-5: 大量页面导出
**场景**：用户生成 50 页 PPT（理论最大值）

**处理**：
- 分批渲染（每批 10 页）
- 显示实时进度：`progress_callback("正在转换第 X / 50 页...")`
- 生成 PPTX 后自动压缩图片（PNG 质量降至 85% 如果文件 >100MB）

## 5. 性能要求

| 指标 | 目标值 | 测试场景 |
|------|--------|----------|
| HTML 单页渲染时间 | <100ms | 标准布局 + 5 个要点 |
| HTML 完整文件生成时间 | <2 秒 | 20 页幻灯片 |
| PPTX 转换速度 | ≥0.2 页/秒 | 20 页 → ≤100 秒 |
| HTML 文件大小 | <2MB | 20 页，不含 base64 图片 |
| PPTX 文件大小 | <50MB | 20 页，每页一张 PNG |
| 图片搜索成功率 | ≥70% | 常见商业 / 科技主题 |
| AI 生图成功率 | ≥95% | 依赖 imagegen 后端 |
| 预览加载时间 | <2 秒 | Gradio Web UI 首次渲染 |

## 6. 安全要求

### SR-1: 图片来源验证
- 搜图时仅从白名单域名下载（如 unsplash.com / pexels.com）
- 验证图片 MIME 类型（防止下载恶意文件）
- 限制下载文件大小（<10MB）

### SR-2: HTML 注入防护
- 所有用户输入文本必须 HTML 转义（`<`, `>`, `&`, `"`, `'`）
- 禁止在 HTML 模板中插入 `<script>` 标签
- 使用 Jinja2 模板引擎的自动转义功能

### SR-3: 文件路径安全
- 所有文件路径必须在 workspace 目录下
- 禁止使用相对路径（`../` 等）
- 使用 `pathlib.Path.resolve()` 规范化路径

## 7. 依赖变更

### 新增依赖
- `playwright` (可选) — HTML → PNG 截图
  - 安装：`pip install playwright`
  - 浏览器：`playwright install chromium`
- `beautifulsoup4` — HTML 解析（提取文字层）
  - 安装：`pip install beautifulsoup4`

### 现有依赖（无变更）
- `pydantic` — 数据模型
- `python-pptx` — PPTX 组装
- `jinja2` — HTML 模板渲染
- `pyyaml` — 主题配置加载

## 8. 验收标准

### 完整流程测试
1. 启动 Web UI（`python web.py`）
2. 进入 PPT 生成 Tab
3. 选择"从主题生成"模式，输入主题："2024年Q3季度业绩汇报"
4. 点击"生成大纲"，等待大纲生成（<30 秒）
5. 编辑大纲（可选）：修改第 3 页的布局为"data_highlight"
6. 点击"确认并生成 PPT"，等待 HTML 预览生成（<5 秒）
7. 在预览区域翻页查看所有页面（<2 秒/页）
8. 点击"导出 PPTX"，等待转换完成（<100 秒，20 页）
9. 下载 .pptx 文件，用 PowerPoint 打开验证：
   - 所有页面完整显示
   - 图片清晰无失真
   - 文字可搜索（notes 区域）
   - 文件大小 <50MB

### 质量检查
- HTML 渲染保真度：与 PPTX 截图对比，差异 <5%
- 主题一致性：所有页面配色 / 字体 / 装饰元素统一
- 图片适配：所有图片尺寸正确，无拉伸变形
- 错误处理：图片加载失败时显示占位块，不影响其他页面
- 性能达标：20 页 PPT 从大纲到 PPTX 总耗时 <120 秒

## 9. 里程碑

### M1: HTML 渲染器（P0）
- [ ] `src/ppt/html_renderer.py` 实现
- [ ] 支持 12 种布局的 HTML 模板
- [ ] 主题样式映射（5 个主题）
- [ ] 单元测试覆盖率 ≥80%

### M2: PPTX 转换器（P0）
- [ ] `src/ppt/html_to_pptx.py` 实现
- [ ] Playwright 截图逻辑
- [ ] 文字层提取（可选）
- [ ] 错误处理（超时 / 浏览器崩溃）

### M3: 图片 Agent（P1）
- [ ] `src/ppt/image_agent.py` 实现
- [ ] 搜图模式（WebSearch 集成）
- [ ] AI 生图模式（imagegen 集成）
- [ ] 背景生成（纯色 / 渐变 / AI）

### M4: Web UI 集成（P0）
- [ ] 启用 PPT Tab 按钮
- [ ] HTML 预览区域（gr.HTML + 翻页控制）
- [ ] 导出 PPTX 按钮 + 下载
- [ ] 状态提示 + 进度条

### M5: 任务队列集成（P0）
- [ ] 新增 `ppt_render_html` 任务
- [ ] 新增 `ppt_export` 任务
- [ ] 修改 `_run_ppt_continue` 调用 HTML 渲染器

### M6: 测试与优化
- [ ] 端到端测试（主题生成 → HTML 预览 → PPTX 导出）
- [ ] 性能优化（HTML 渲染 / PPTX 转换）
- [ ] 文档更新（CLAUDE.md / README）
