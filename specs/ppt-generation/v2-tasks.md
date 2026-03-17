# AI PPT 生成 V2 - 任务列表（产品修正版）

## 任务概览

本任务列表将 V2 修正分为 **3 个迭代**（Milestone），每个迭代可独立交付和测试。

| Milestone | 主要功能 | 预估工作量 | 优先级 |
|-----------|---------|-----------|--------|
| **M1: 叙事结构 + 大纲审核** | 从主题生成 + 大纲暂停审核 | 5-7 天 | P0 |
| **M2: 内容强化 + 配图建议** | 演讲稿生成 + 配图建议 + AI 味检测 | 4-6 天 | P0 |
| **M3: 输出增强 + UI 优化** | 中间产物输出 + Web UI 优化 | 3-5 天 | P1 |

**总预估**：12-18 天（单人全职开发）

---

## Milestone 1: 叙事结构 + 大纲审核（P0）

**目标**：实现"从主题生成"入口 + 大纲审核环节（暂停点）。

### 1.1 数据模型扩展

#### Task 1.1.1: 新增叙事结构数据模型
- **文件**：`src/ppt/models.py`
- **操作**：新增
- **内容**：
  - 新增 `NarrativeStructure` 数据模型（包含 scenario, total_pages, sections）
  - 新增 `NarrativeSection` 数据模型（包含 role, title_hint, key_points_hint, speaker_notes_hint）
  - 新增 `Scenario` 枚举（quarterly_review, product_launch, tech_share, course_lecture, pitch_deck, workshop, status_update）
- **输入**：无
- **输出**：`src/ppt/models.py`（新增约 50 行）
- **依赖**：无
- **验收**：
  - [ ] `NarrativeStructure.model_validate()` 可正常解析 JSON
  - [ ] `Scenario` 枚举包含 7 个场景

---

#### Task 1.1.2: 新增可编辑大纲数据模型
- **文件**：`src/ppt/models.py`
- **操作**：新增
- **内容**：
  - 新增 `EditableOutline` 数据模型（包含 project_id, total_pages, estimated_duration, narrative_arc, slides）
  - 新增 `EditableSlide` 数据模型（包含 page_number, role, title, subtitle, key_points, layout, image_strategy, speaker_notes_hint, editable, locked）
- **输入**：无
- **输出**：`src/ppt/models.py`（新增约 40 行）
- **依赖**：Task 1.1.1
- **验收**：
  - [ ] `EditableOutline.model_validate()` 可正常解析 JSON/YAML
  - [ ] 可序列化为 YAML（用于 CLI 编辑）

---

### 1.2 叙事结构设计

#### Task 1.2.1: 创建叙事模板（YAML 配置）
- **文件**：`src/ppt/narratives/*.yaml`
- **操作**：新增
- **内容**：
  - 创建目录 `src/ppt/narratives/`
  - 为 7 个场景各创建一个 YAML 模板（quarterly_review.yaml, product_launch.yaml, tech_share.yaml, course_lecture.yaml, pitch_deck.yaml, workshop.yaml, status_update.yaml）
  - 每个模板包含：narrative_id, name, description, target_pages, structure（role 列表）, narrative_tips
- **输入**：V2 需求文档（叙事结构章节）
- **输出**：7 个 YAML 文件
- **依赖**：Task 1.1.1
- **验收**：
  - [ ] 每个 YAML 可正常解析为 Python dict
  - [ ] structure 包含至少 5 个 role（cover, executive_summary, ..., closing）

---

#### Task 1.2.2: 实现 NarrativeDesigner Agent
- **文件**：`src/ppt/narrative_designer.py`
- **操作**：新增
- **内容**：
  - 实现 `NarrativeDesigner` 类
  - `load_scenario_template(scenario_id) -> dict`：加载场景 YAML 模板
  - `design(topic, audience, scenario, materials) -> NarrativeStructure`：根据主题和场景生成叙事结构
  - LLM prompt：信息点挖掘（根据主题和场景，识别需要覆盖的关键信息点）
  - 整合用户提供的零散材料（materials）
- **输入**：
  - topic (str)
  - audience (str)
  - scenario (str)
  - materials (list[dict], optional)
- **输出**：`NarrativeStructure`
- **依赖**：Task 1.2.1
- **验收**：
  - [ ] 可正常加载 7 个场景模板
  - [ ] LLM 生成的叙事结构包含合理的 title_hint 和 key_points_hint
  - [ ] 用户材料被正确归类到对应 role

---

### 1.3 大纲生成与审核

#### Task 1.3.1: 扩展 OutlineGenerator 支持从叙事结构生成
- **文件**：`src/ppt/outline_generator.py`
- **操作**：修改
- **内容**：
  - 新增方法 `from_narrative(narrative: NarrativeStructure, theme: str, target_pages: int) -> list[SlideOutline]`
  - 复用现有 LLM prompt，但从 NarrativeSection 填充 title/key_points
  - 保留现有 `from_document()` 方法（文档转 PPT 模式）
- **输入**：
  - narrative (NarrativeStructure)
  - theme (str)
  - target_pages (int)
- **输出**：`list[SlideOutline]`
- **依赖**：Task 1.2.2
- **验收**：
  - [ ] 从叙事结构生成的大纲，页面顺序符合场景模板
  - [ ] title 和 key_points 来自 LLM 填充（而非模板硬编码）

---

#### Task 1.3.2: 实现大纲序列化/反序列化
- **文件**：`src/ppt/outline_generator.py`
- **操作**：修改
- **内容**：
  - 新增函数 `serialize_outline_for_edit(outline: list[SlideOutline], project_id: str, narrative_arc: str) -> EditableOutline`
  - 新增函数 `deserialize_edited_outline(edited: EditableOutline) -> list[SlideOutline]`
  - 枚举类型与字符串互转（`PageRole.COVER.value` ↔ `"cover"`）
- **输入**：
  - `serialize_outline_for_edit`: `list[SlideOutline]`
  - `deserialize_edited_outline`: `EditableOutline`
- **输出**：
  - `serialize_outline_for_edit`: `EditableOutline`
  - `deserialize_edited_outline`: `list[SlideOutline]`
- **依赖**：Task 1.1.2
- **验收**：
  - [ ] 序列化 → 反序列化后，数据无损失
  - [ ] 枚举类型正确转换

---

### 1.4 Pipeline 改造

#### Task 1.4.1: 新增 ModeRouter
- **文件**：`src/ppt/pipeline.py`
- **操作**：修改
- **内容**：
  - 新增方法 `_route_mode(topic, document_text) -> str`（返回 "topic" 或 "document"）
  - 自动推断模式：如果有 topic 且无 document_text，则为 "topic" 模式
- **输入**：
  - topic (str | None)
  - document_text (str | None)
- **输出**：`str` ("topic" 或 "document")
- **依赖**：无
- **验收**：
  - [ ] 输入 topic="xxx" 且 document_text=None，返回 "topic"
  - [ ] 输入 document_text="xxx"，返回 "document"
  - [ ] 两者都无，抛出 ValueError

---

#### Task 1.4.2: 实现 generate_outline_only() 方法
- **文件**：`src/ppt/pipeline.py`
- **操作**：修改
- **内容**：
  - 新增方法 `generate_outline_only(topic, document_text, audience, scenario, materials, theme, target_pages) -> tuple[str, EditableOutline]`
  - 流程：
    1. Mode routing
    2. 根据模式调用 NarrativeDesigner 或 DocumentAnalyzer
    3. 调用 OutlineGenerator 生成大纲
    4. 序列化为 EditableOutline
    5. 保存 checkpoint（stage="outline_review"）
    6. 返回 project_id 和 EditableOutline
- **输入**：
  - topic (str | None)
  - document_text (str | None)
  - audience (str)
  - scenario (str)
  - materials (list[dict] | None)
  - theme (str)
  - target_pages (int | None)
- **输出**：`tuple[str, EditableOutline]`（project_id, editable_outline）
- **依赖**：Task 1.4.1, Task 1.3.1, Task 1.3.2
- **验收**：
  - [ ] topic 模式和 document 模式都能正常生成大纲
  - [ ] checkpoint 正确保存
  - [ ] 返回的 EditableOutline 可序列化为 YAML

---

#### Task 1.4.3: 实现 continue_from_outline() 方法（简化版）
- **文件**：`src/ppt/pipeline.py`
- **操作**：修改
- **内容**：
  - 新增方法 `continue_from_outline(project_id, edited_outline) -> str`（返回 pptx 路径）
  - 流程：
    1. 反序列化 EditableOutline → list[SlideOutline]
    2. 调用现有的 ContentCreator / DesignOrchestrator / ImageGenerator / Renderer
    3. 返回 pptx 路径
  - **注意**：此任务为简化版，暂不包含演讲稿生成、配图建议、输出中间产物（留到 M2/M3）
- **输入**：
  - project_id (str)
  - edited_outline (EditableOutline)
- **输出**：`str`（pptx 文件路径）
- **依赖**：Task 1.3.2
- **验收**：
  - [ ] 可正常调用现有的 ContentCreator / DesignOrchestrator / Renderer
  - [ ] 生成的 .pptx 内容与编辑后的大纲一致

---

### 1.5 CLI 接口

#### Task 1.5.1: 新增 ppt create 命令
- **文件**：`main.py`
- **操作**：修改
- **内容**：
  - 新增 `@ppt.command("create")` 命令
  - 参数：topic, audience, scenario, theme, target_pages, materials
  - 调用 `pipeline.generate_outline_only()`
  - 输出：project_id 和大纲保存路径（YAML 格式）
  - 提示用户编辑后运行 `ppt continue`
- **输入**：CLI 参数
- **输出**：打印 project_id 和大纲路径
- **依赖**：Task 1.4.2
- **验收**：
  - [ ] `python main.py ppt create "主题" --audience business --scenario quarterly_review` 正常执行
  - [ ] 输出 YAML 文件可手动编辑

---

#### Task 1.5.2: 新增 ppt continue 命令
- **文件**：`main.py`
- **操作**：修改
- **内容**：
  - 新增 `@ppt.command("continue")` 命令
  - 参数：project_path
  - 加载 checkpoint 中的 EditableOutline
  - 调用 `pipeline.continue_from_outline()`
  - 输出：pptx 文件路径
- **输入**：project_path (str)
- **输出**：打印 pptx 文件路径
- **依赖**：Task 1.4.3
- **验收**：
  - [ ] `python main.py ppt continue workspace/ppt_xxx` 正常执行
  - [ ] 生成的 .pptx 反映大纲修改

---

#### Task 1.5.3: 修改 ppt generate 命令（加入暂停）
- **文件**：`main.py`
- **操作**：修改
- **内容**：
  - 修改 `@ppt.command("generate")` 命令
  - 新增 `--auto-continue` 选项（默认 False）
  - 如果 auto_continue=False，调用 `generate_outline_only()` 后暂停
  - 如果 auto_continue=True，调用 `generate_outline_only()` 后自动调用 `continue_from_outline()`（保持 V1 行为）
- **输入**：CLI 参数 + --auto-continue
- **输出**：取决于 auto_continue
- **依赖**：Task 1.4.2, Task 1.4.3
- **验收**：
  - [ ] `python main.py ppt generate input.txt` 在大纲生成后暂停
  - [ ] `python main.py ppt generate input.txt --auto-continue` 一键生成完成

---

### 1.6 测试

#### Task 1.6.1: 单元测试 - NarrativeDesigner
- **文件**：`tests/ppt/test_narrative_designer.py`
- **操作**：新增
- **内容**：
  - 测试场景模板加载
  - 测试叙事结构生成（Mock LLM）
  - 测试零散材料整合
- **依赖**：Task 1.2.2
- **验收**：
  - [ ] 测试覆盖率 ≥80%
  - [ ] 所有测试通过

---

#### Task 1.6.2: 单元测试 - OutlineGenerator（序列化/反序列化）
- **文件**：`tests/ppt/test_outline_generator.py`
- **操作**：修改
- **内容**：
  - 新增测试 `test_serialize_outline_for_edit()`
  - 新增测试 `test_deserialize_edited_outline()`
  - 新增测试 `test_from_narrative()`（Mock LLM）
- **依赖**：Task 1.3.1, Task 1.3.2
- **验收**：
  - [ ] 序列化 → 反序列化无损失
  - [ ] 所有测试通过

---

#### Task 1.6.3: 集成测试 - 从主题生成流程
- **文件**：`tests/ppt/test_pipeline_topic_mode.py`
- **操作**：新增
- **内容**：
  - 测试完整流程：topic → generate_outline_only → 编辑 → continue_from_outline
  - Mock LLM 和 ImageGenerator
- **依赖**：Task 1.4.2, Task 1.4.3
- **验收**：
  - [ ] 流程顺畅，无报错
  - [ ] 生成的 .pptx 内容正确

---

#### Task 1.6.4: CLI 端到端测试
- **文件**：手动测试（可选自动化）
- **操作**：手动测试
- **内容**：
  - 运行 `python main.py ppt create "测试主题" --audience business --scenario quarterly_review`
  - 手动编辑生成的 YAML 文件
  - 运行 `python main.py ppt continue workspace/ppt_xxx`
  - 检查生成的 .pptx
- **依赖**：Task 1.5.1, Task 1.5.2
- **验收**：
  - [ ] CLI 交互流畅
  - [ ] 编辑后的修改正确应用

---

## Milestone 2: 内容强化 + 配图建议（P0）

**目标**：生成详细演讲稿 + 配图建议（而非直接生成图片）+ AI 味检测。

### 2.1 演讲稿生成

#### Task 2.1.1: 扩展 SlideContent 数据模型
- **文件**：`src/ppt/models.py`
- **操作**：修改
- **内容**：
  - `SlideContent` 新增字段 `speaker_notes: str`（演讲稿，200-300 字）
  - `SlideContent` 新增字段 `speaker_notes_word_count: int`
- **输入**：无
- **输出**：`src/ppt/models.py`（修改约 10 行）
- **依赖**：无
- **验收**：
  - [ ] `SlideContent.model_validate()` 可正常解析包含 speaker_notes 的 JSON

---

#### Task 2.1.2: 实现演讲稿生成（ContentCreator）
- **文件**：`src/ppt/content_creator.py`
- **操作**：修改
- **内容**：
  - 修改 `create_content(slide_outline) -> SlideContent` 方法
  - 新增 LLM 调用：生成演讲稿（200-300 字）
  - Prompt 要求：开场白/过渡句/强调点/口语化/禁止空洞词
  - 字数统计：`speaker_notes_word_count = len(speaker_notes)`
- **输入**：`SlideOutline`
- **输出**：`SlideContent`（包含 speaker_notes）
- **依赖**：Task 2.1.1
- **验收**：
  - [ ] 生成的演讲稿字数在 180-320 字之间（允许 10% 误差）
  - [ ] 演讲稿口语化，不刻板
  - [ ] 第一页包含开场白，非第一页包含过渡句

---

#### Task 2.1.3: 支持跳过演讲稿生成（可选）
- **文件**：`src/ppt/pipeline.py`
- **操作**：修改
- **内容**：
  - `continue_from_outline()` 方法新增参数 `generate_speaker_notes: bool = True`
  - 如果 False，跳过演讲稿生成（speaker_notes 为空）
- **输入**：generate_speaker_notes (bool)
- **输出**：无变化
- **依赖**：Task 2.1.2
- **验收**：
  - [ ] `continue_from_outline(..., generate_speaker_notes=False)` 正常执行
  - [ ] speaker_notes 为空

---

### 2.2 配图建议生成

#### Task 2.2.1: 新增 ImageSuggestion 数据模型
- **文件**：`src/ppt/models.py`
- **操作**：新增
- **内容**：
  - 新增 `ImageSuggestion` 数据模型（包含 page_number, title, type, description, composition, color_scheme, alternative_text, prompt_if_generate, generate_image, generated_image_path）
- **输入**：无
- **输出**：`src/ppt/models.py`（新增约 30 行）
- **依赖**：无
- **验收**：
  - [ ] `ImageSuggestion.model_validate()` 可正常解析 JSON

---

#### Task 2.2.2: 实现 ImageAdvisor Agent
- **文件**：`src/ppt/image_advisor.py`
- **操作**：新增
- **内容**：
  - 实现 `ImageAdvisor` 类
  - `advise(slide_outline, slide_content) -> ImageSuggestion`：为单页生成配图建议
  - `advise_all(outlines, contents) -> list[ImageSuggestion]`：批量生成
  - LLM prompt：根据 role/title/key_points/image_strategy 生成建议
- **输入**：
  - slide_outline (SlideOutline)
  - slide_content (SlideContent)
- **输出**：`ImageSuggestion`
- **依赖**：Task 2.2.1
- **验收**：
  - [ ] 生成的配图建议具体（description ≥50 字）
  - [ ] prompt_if_generate 为英文，符合图片生成 API 要求
  - [ ] alternative_text 实用（例如"在 Excel 中绘制柱状图"）

---

#### Task 2.2.3: 修改 ImageGenerator 支持可选生成
- **文件**：`src/ppt/pipeline.py`（或新增 `src/ppt/image_generator_wrapper.py`）
- **操作**：修改
- **内容**：
  - `continue_from_outline()` 方法新增参数 `generate_images: bool = True`
  - 调用 ImageAdvisor 生成建议
  - 如果 generate_images=True，调用现有 ImageGenerator 生成图片（仅生成 `generate_image=True` 的建议）
  - 如果 generate_images=False，跳过图片生成
- **输入**：generate_images (bool)
- **输出**：`list[ImageSuggestion]`（部分可能有 generated_image_path）
- **依赖**：Task 2.2.2
- **验收**：
  - [ ] generate_images=False 时，跳过图片生成
  - [ ] generate_images=True 时，仅生成 generate_image=True 的图片

---

### 2.3 AI 味检测

#### Task 2.3.1: 创建 PPT 专用 AI 味黑名单
- **文件**：`src/ppt/ai_taste_blacklist.py`
- **操作**：新增
- **内容**：
  - 定义 `PPT_SPECIFIC_BLACKLIST: dict[str, str]`（空洞词 → 替换词）
  - 包含 15 个常见空洞词（赋能、闭环、抓手、颗粒度、打通、沉淀、抽象、链路、触达、心智等）
- **输入**：无
- **输出**：`src/ppt/ai_taste_blacklist.py`（新增约 30 行）
- **依赖**：无
- **验收**：
  - [ ] 黑名单包含 ≥15 个词
  - [ ] 每个词有合理替换词

---

#### Task 2.3.2: 实现 AI 味检测和替换（QualityChecker）
- **文件**：`src/ppt/quality_checker.py`
- **操作**：修改
- **内容**：
  - 新增方法 `check_ai_taste(content: SlideContent) -> list[str]`：检测空洞词
  - 新增方法 `auto_replace_ai_taste(content: SlideContent) -> SlideContent`：自动替换
  - 在 `check_quality()` 中调用 AI 味检测
- **输入**：`SlideContent`
- **输出**：
  - `check_ai_taste`: `list[str]`（检测到的问题）
  - `auto_replace_ai_taste`: `SlideContent`（替换后）
- **依赖**：Task 2.3.1
- **验收**：
  - [ ] 检测到空洞词，返回问题列表
  - [ ] 自动替换后，空洞词被替换

---

#### Task 2.3.3: 集成 AI 味检测到 Pipeline
- **文件**：`src/ppt/pipeline.py`
- **操作**：修改
- **内容**：
  - 在 `continue_from_outline()` 中，ContentCreator 生成内容后，调用 QualityChecker.auto_replace_ai_taste()
  - 记录检测日志（info 级别）
- **输入**：无
- **输出**：无
- **依赖**：Task 2.3.2
- **验收**：
  - [ ] 生成的内容中，空洞词被自动替换
  - [ ] 日志中显示替换记录

---

### 2.4 测试

#### Task 2.4.1: 单元测试 - ContentCreator（演讲稿）
- **文件**：`tests/ppt/test_content_creator.py`
- **操作**：修改
- **内容**：
  - 新增测试 `test_generate_speaker_notes()`（Mock LLM）
  - 测试字数控制（180-320 字）
  - 测试口语化检测（不包含"首先、其次、最后"）
- **依赖**：Task 2.1.2
- **验收**：
  - [ ] 所有测试通过

---

#### Task 2.4.2: 单元测试 - ImageAdvisor
- **文件**：`tests/ppt/test_image_advisor.py`
- **操作**：新增
- **内容**：
  - 测试配图建议生成（Mock LLM）
  - 测试 prompt 格式（英文）
  - 测试 alternative_text 实用性
- **依赖**：Task 2.2.2
- **验收**：
  - [ ] 所有测试通过

---

#### Task 2.4.3: 单元测试 - AI 味检测
- **文件**：`tests/ppt/test_quality_checker.py`
- **操作**：修改
- **内容**：
  - 新增测试 `test_check_ai_taste()`
  - 新增测试 `test_auto_replace_ai_taste()`
  - 测试检测召回率（准备 20 个包含空洞词的句子，检测率 ≥90%）
- **依赖**：Task 2.3.2
- **验收**：
  - [ ] 检测召回率 ≥90%
  - [ ] 所有测试通过

---

#### Task 2.4.4: 集成测试 - 完整流程（含演讲稿+配图建议）
- **文件**：`tests/ppt/test_pipeline_v2.py`
- **操作**：新增
- **内容**：
  - 测试完整流程：topic → outline → continue（含演讲稿、配图建议、AI 味检测）
  - Mock LLM 和 ImageGenerator
  - 验证输出包含 speaker_notes 和 image_suggestions
- **依赖**：Task 2.1.2, Task 2.2.2, Task 2.3.3
- **验收**：
  - [ ] 流程顺畅，无报错
  - [ ] 输出内容包含演讲稿和配图建议

---

## Milestone 3: 输出增强 + UI 优化（P1）

**目标**：输出中间产物（Markdown/JSON/PDF）+ Web UI 大纲编辑器 + MCP 接口更新。

### 3.1 输出中间产物

#### Task 3.1.1: 新增 OutputFiles 数据模型
- **文件**：`src/ppt/models.py`
- **操作**：新增
- **内容**：
  - 新增 `OutputFiles` 数据模型（包含 pptx_path, outline_md_path, content_txt_path, speaker_notes_pdf_path, image_suggestions_json_path, quality_report_md_path）
- **输入**：无
- **输出**：`src/ppt/models.py`（新增约 20 行）
- **依赖**：无
- **验收**：
  - [ ] `OutputFiles.model_validate()` 可正常解析 JSON

---

#### Task 3.1.2: 实现 OutputManager
- **文件**：`src/ppt/output_manager.py`
- **操作**：新增
- **内容**：
  - 实现 `OutputManager` 类
  - `generate_outline_markdown(outline, contents) -> str`：生成 Markdown 大纲
  - `generate_content_txt(contents) -> str`：生成逐页内容文本
  - `generate_image_suggestions_json(suggestions) -> str`：生成配图建议 JSON
  - `generate_speaker_notes_pdf(contents, output_path) -> None`：生成演讲者备注 PDF（可选，需 reportlab）
  - `output_all(pptx_path, outline, contents, suggestions) -> OutputFiles`：输出所有文件
  - `output_content_only(outline, contents, suggestions) -> OutputFiles`：仅输出内容（不渲染 PPT）
- **输入**：
  - outline (EditableOutline)
  - contents (list[SlideContent])
  - suggestions (list[ImageSuggestion])
- **输出**：`OutputFiles`
- **依赖**：Task 3.1.1
- **验收**：
  - [ ] 生成的 Markdown 格式正确，可在飞书文档中使用
  - [ ] 生成的 JSON 格式正确，可被 Python 解析
  - [ ] 生成的 PDF（如果实现）排版清晰

---

#### Task 3.1.3: 集成 OutputManager 到 Pipeline
- **文件**：`src/ppt/pipeline.py`
- **操作**：修改
- **内容**：
  - 修改 `continue_from_outline()` 方法，返回 `OutputFiles`（而非单个 pptx_path）
  - 新增参数 `content_only: bool = False`
  - 如果 content_only=True，调用 `output_manager.output_content_only()`
  - 如果 content_only=False，调用 `output_manager.output_all()`
- **输入**：content_only (bool)
- **输出**：`OutputFiles`
- **依赖**：Task 3.1.2
- **验收**：
  - [ ] content_only=True 时，跳过渲染，仅输出 Markdown/JSON
  - [ ] content_only=False 时，输出所有文件

---

### 3.2 CLI 接口增强

#### Task 3.2.1: ppt continue 支持 --content-only
- **文件**：`main.py`
- **操作**：修改
- **内容**：
  - `@ppt.command("continue")` 新增 `--content-only` 选项
  - 调用 `pipeline.continue_from_outline(..., content_only=True)`
  - 输出所有生成的文件路径
- **输入**：--content-only (bool)
- **输出**：打印文件路径
- **依赖**：Task 3.1.3
- **验收**：
  - [ ] `python main.py ppt continue workspace/ppt_xxx --content-only` 正常执行
  - [ ] 仅输出 Markdown/JSON，无 .pptx

---

#### Task 3.2.2: ppt continue 支持 --no-images
- **文件**：`main.py`
- **操作**：修改
- **内容**：
  - `@ppt.command("continue")` 新增 `--no-images` 选项
  - 调用 `pipeline.continue_from_outline(..., generate_images=False)`
- **输入**：--no-images (bool)
- **输出**：打印文件路径
- **依赖**：Task 2.2.3
- **验收**：
  - [ ] `python main.py ppt continue workspace/ppt_xxx --no-images` 正常执行
  - [ ] 跳过图片生成

---

### 3.3 Web UI 大纲编辑器

#### Task 3.3.1: 设计大纲编辑器 UI（Gradio DataFrame）
- **文件**：`web.py`
- **操作**：修改
- **内容**：
  - PPT Tab 新增"从主题生成"表单（topic, audience, scenario, materials）
  - "生成大纲"按钮，调用 `pipeline.generate_outline_only()`
  - 显示 `gr.DataFrame`（可编辑表格），列：页码/角色/标题/要点/布局/配图策略
  - 新增"删除选中页"、"新增页面"按钮
  - "确认大纲"按钮，调用 `pipeline.continue_from_outline()`
- **输入**：表单输入
- **输出**：DataFrame + 按钮
- **依赖**：Task 1.4.2
- **验收**：
  - [ ] UI 布局合理，表格可编辑
  - [ ] 按钮功能正常

---

#### Task 3.3.2: 实现 DataFrame ↔ EditableOutline 转换
- **文件**：`web.py`
- **操作**：修改
- **内容**：
  - 实现函数 `_editable_outline_to_df(outline: EditableOutline) -> list[list]`
  - 实现函数 `_df_to_editable_outline(df_data: list[list], project_id: str) -> EditableOutline`
- **输入**：
  - `_editable_outline_to_df`: `EditableOutline`
  - `_df_to_editable_outline`: `list[list]`（DataFrame 数据）
- **输出**：
  - `_editable_outline_to_df`: `list[list]`
  - `_df_to_editable_outline`: `EditableOutline`
- **依赖**：Task 3.3.1
- **验收**：
  - [ ] 转换无损失
  - [ ] DataFrame 编辑后，转回 EditableOutline 正确

---

#### Task 3.3.3: 实现 Web UI 事件处理
- **文件**：`web.py`
- **操作**：修改
- **内容**：
  - `_on_generate_outline()`：调用 `pipeline.generate_outline_only()`，返回 DataFrame
  - `_on_confirm_outline()`：调用 `pipeline.continue_from_outline()`，提交后台任务
  - `_on_delete_page()`：从 DataFrame 删除选中行
  - `_on_add_page()`：在 DataFrame 插入新行
- **输入**：表单输入 / DataFrame 数据
- **输出**：更新 UI 组件
- **依赖**：Task 3.3.2
- **验收**：
  - [ ] 事件处理正常，无报错
  - [ ] 后台任务正常提交

---

### 3.4 MCP Server 接口

#### Task 3.4.1: 新增 ppt_create_from_topic 工具
- **文件**：`mcp_server.py`
- **操作**：修改
- **内容**：
  - 新增 `@mcp.tool() def ppt_create_from_topic(topic, audience, scenario, theme, target_pages, materials) -> dict`
  - 调用 `pipeline.generate_outline_only()`
  - 返回 `{"project_id": "...", "outline": {...}, "status": "outline_ready"}`
- **输入**：topic, audience, scenario, theme, target_pages, materials
- **输出**：dict
- **依赖**：Task 1.4.2
- **验收**：
  - [ ] MCP 工具可正常调用
  - [ ] 返回格式正确

---

#### Task 3.4.2: 新增 ppt_confirm_outline 工具
- **文件**：`mcp_server.py`
- **操作**：修改
- **内容**：
  - 新增 `@mcp.tool() def ppt_confirm_outline(project_id, edited_outline, content_only, generate_images) -> dict`
  - 调用 `pipeline.continue_from_outline()`
  - 返回 `{"project_id": "...", "output_files": {...}, "status": "completed"}`
- **输入**：project_id, edited_outline, content_only, generate_images
- **输出**：dict
- **依赖**：Task 3.1.3
- **验收**：
  - [ ] MCP 工具可正常调用
  - [ ] 返回格式正确

---

#### Task 3.4.3: 修改 ppt_generate 工具（支持 auto_continue）
- **文件**：`mcp_server.py`
- **操作**：修改
- **内容**：
  - 修改 `@mcp.tool() def ppt_generate(..., auto_continue=False)`
  - 如果 auto_continue=False，仅返回大纲（暂停）
  - 如果 auto_continue=True，直接生成完成（V1 行为）
- **输入**：auto_continue (bool)
- **输出**：dict
- **依赖**：Task 1.4.2, Task 3.1.3
- **验收**：
  - [ ] auto_continue=False 时，返回大纲
  - [ ] auto_continue=True 时，返回完整输出

---

### 3.5 测试

#### Task 3.5.1: 单元测试 - OutputManager
- **文件**：`tests/ppt/test_output_manager.py`
- **操作**：新增
- **内容**：
  - 测试 Markdown 生成（格式正确）
  - 测试 JSON 生成（可解析）
  - 测试 PDF 生成（如果实现）
- **依赖**：Task 3.1.2
- **验收**：
  - [ ] 所有测试通过

---

#### Task 3.5.2: Web UI 端到端测试
- **文件**：手动测试（可选自动化）
- **操作**：手动测试
- **内容**：
  - 打开 Web UI，填写"从主题生成"表单
  - 生成大纲，编辑 DataFrame（修改标题、删除页面、新增页面）
  - 确认大纲，等待生成完成
  - 下载输出文件（.pptx / outline.md / image_suggestions.json）
- **依赖**：Task 3.3.3
- **验收**：
  - [ ] UI 交互流畅
  - [ ] DataFrame 编辑正确应用
  - [ ] 输出文件正确

---

#### Task 3.5.3: MCP 端到端测试
- **文件**：手动测试（可选自动化）
- **操作**：手动测试
- **内容**：
  - 使用 MCP Inspector 调用 `ppt_create_from_topic`
  - 手动编辑返回的 outline JSON
  - 调用 `ppt_confirm_outline`
  - 检查输出文件
- **依赖**：Task 3.4.1, Task 3.4.2
- **验收**：
  - [ ] MCP 工具正常调用
  - [ ] 输出文件正确

---

## 任务总结

### 任务数量统计
| Milestone | 新增文件 | 修改文件 | 测试文件 | 任务数 |
|-----------|---------|---------|---------|--------|
| **M1** | 7 | 3 | 4 | 16 |
| **M2** | 3 | 4 | 4 | 13 |
| **M3** | 2 | 4 | 3 | 13 |
| **总计** | 12 | 11 | 11 | **42** |

### 关键路径
```
M1: 叙事模板 → NarrativeDesigner → OutlineGenerator(扩展) → Pipeline(generate_outline_only) → CLI(ppt create)
M2: ImageAdvisor → ContentCreator(演讲稿) → QualityChecker(AI味) → Pipeline(集成)
M3: OutputManager → Pipeline(输出增强) → Web UI(大纲编辑器) → MCP(新工具)
```

### 里程碑依赖关系
- M2 依赖 M1（需要 Pipeline 和 OutlineGenerator 完成）
- M3 依赖 M2（需要 ContentCreator 和 ImageAdvisor 完成）

---

## 附录：任务模板

### 任务描述模板
```markdown
#### Task X.X.X: 任务标题
- **文件**：src/xxx/yyy.py
- **操作**：新增 / 修改
- **内容**：
  - 简要描述（3-5 句话）
  - 关键实现点
- **输入**：输入参数或依赖数据
- **输出**：输出数据或文件
- **依赖**：依赖的其他任务
- **验收**：
  - [ ] 验收标准 1
  - [ ] 验收标准 2
```

### 测试任务模板
```markdown
#### Task X.X.X: 单元测试 - 模块名
- **文件**：tests/ppt/test_xxx.py
- **操作**：新增 / 修改
- **内容**：
  - 测试场景 1
  - 测试场景 2
  - Mock 策略
- **依赖**：对应的实现任务
- **验收**：
  - [ ] 测试覆盖率 ≥80%
  - [ ] 所有测试通过
```
