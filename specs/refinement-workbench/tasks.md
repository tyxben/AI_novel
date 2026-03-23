# Tasks: 章节编辑工作台

## 概览

实现两个主要功能：
1. **章节编辑 + AI 校对**：用户编辑章节 → AI 检查语言问题 → 批量修正
2. **设定修订 + 影响评估**：用户修改设定 → AI 分析影响 → 回溯修改章节

---

## 任务拆分

### Phase 1: 数据模型与基础服务（后端）

- [ ] **1.1 创建数据模型**
  - [ ] 1.1.1 创建 `src/novel/models/refinement.py`
    - [ ] 定义 `ProofreadingIssue` 模型
    - [ ] 定义 `SettingConflict` 模型
    - [ ] 定义 `SettingImpact` 模型
  - [ ] 1.1.2 扩展 `src/novel/models/novel.py`
    - [ ] 添加 `setting_version: int` 字段
    - [ ] 添加 `setting_history: list[dict]` 字段
  - [ ] 1.1.3 编写模型单元测试 `tests/novel/models/test_refinement.py`
    - [ ] 测试 Pydantic 验证（必填字段、类型检查）
    - [ ] 测试 JSON 序列化/反序列化

- [ ] **1.2 实现 Proofreader 服务**
  - [ ] 1.2.1 创建 `src/novel/services/proofreader.py`
    - [ ] 实现 `__init__(llm_client)`
    - [ ] 实现 `proofread(text: str) -> list[ProofreadingIssue]`
      - [ ] 设计 LLM prompt（系统提示词 + 用户提示词）
      - [ ] 调用 `llm.chat(messages, json_mode=True)`
      - [ ] 解析 LLM 返回的 JSON（使用 `extract_json_from_llm`）
      - [ ] 验证 issue type 合法性
      - [ ] 限制最多返回50条问题
    - [ ] 实现 `apply_fixes(text, issues, selected_indices) -> (str, list[str])`
      - [ ] 按 original 在文本中的位置从后往前排序
      - [ ] 逐条应用 `text.replace(original, correction)`
      - [ ] 记录失败的修正（原文不匹配）
  - [ ] 1.2.2 编写 Proofreader 单元测试 `tests/novel/services/test_proofreader.py`
    - [ ] 测试 proofread（正常、空文本、LLM 返回空、LLM 返回格式错误）
    - [ ] 测试 apply_fixes（单条、多条、部分失败、全失败）
    - [ ] Mock LLM 返回

- [ ] **1.3 实现 SettingImpactAnalyzer 服务**
  - [ ] 1.3.1 创建 `src/novel/services/setting_impact_analyzer.py`
    - [ ] 实现 `__init__(llm_client, file_manager)`
    - [ ] 实现 `_generate_chapters_summary(novel_id) -> str`
      - [ ] 加载已写章节列表
      - [ ] 生成每章摘要（章节号 + 标题 + 前100字）
      - [ ] 限制最多40章
    - [ ] 实现 `analyze_impact(novel_id, modified_setting, old_value, new_value) -> SettingImpact`
      - [ ] 设计 LLM prompt（对比 old vs new，扫描章节摘要）
      - [ ] 调用 LLM
      - [ ] 解析返回的影响报告 JSON
      - [ ] 验证受影响章节号在合法范围内
    - [ ] 实现 `rewrite_affected_chapters(novel_id, impact, writer, progress_callback) -> dict[int, str]`
      - [ ] 加载世界观、角色、大纲
      - [ ] 对每个受影响章节调用 `writer.rewrite_chapter()`
      - [ ] 保存原章节到 revision
      - [ ] 保存重写后章节
      - [ ] 返回重写结果
  - [ ] 1.3.2 编写 SettingImpactAnalyzer 单元测试 `tests/novel/services/test_setting_impact_analyzer.py`
    - [ ] 测试 _generate_chapters_summary（正常、空章节、超过40章）
    - [ ] 测试 analyze_impact（正常、无影响、LLM 返回错误）
    - [ ] 测试 rewrite_affected_chapters（正常、部分失败）
    - [ ] Mock LLM、FileManager、Writer

---

### Phase 2: NovelPipeline 扩展（后端 API）

- [ ] **2.1 扩展 NovelPipeline 方法**
  - [ ] 2.1.1 在 `src/novel/pipeline.py` 中添加章节校对方法
    - [ ] 实现 `proofread_chapter(project_path, chapter_number, text=None) -> list[dict]`
      - [ ] 加载章节文本（如果 text=None）
      - [ ] 调用 Proofreader.proofread()
      - [ ] 转换为 dict 格式（Gradio 友好）
    - [ ] 实现 `apply_proofreading_fixes(project_path, chapter_number, text, issues, selected_indices) -> (str, list[str])`
      - [ ] 转换 dict → ProofreadingIssue
      - [ ] 调用 Proofreader.apply_fixes()
    - [ ] 实现 `save_edited_chapter(project_path, chapter_number, text, save_revision=True) -> str`
      - [ ] 保存原章节到 revision（如果 save_revision=True）
      - [ ] 保存新章节文本
      - [ ] 更新章节 JSON（word_count, revision_count）
  - [ ] 2.1.2 在 `src/novel/pipeline.py` 中添加设定修订方法
    - [ ] 实现 `analyze_setting_impact(project_path, modified_setting, new_value) -> dict`
      - [ ] 加载原设定
      - [ ] 调用 SettingImpactAnalyzer.analyze_impact()
      - [ ] 转换为 dict 格式
    - [ ] 实现 `save_setting(project_path, modified_setting, new_value, save_history=True) -> str`
      - [ ] 备份原 novel.json 到 revisions/
      - [ ] 记录修改历史（setting_history）
      - [ ] 递增 setting_version
      - [ ] 保存新设定到 novel.json
    - [ ] 实现 `rewrite_affected_chapters(project_path, impact, progress_callback=None) -> dict[int, str]`
      - [ ] 初始化 Writer
      - [ ] 调用 SettingImpactAnalyzer.rewrite_affected_chapters()
      - [ ] 返回重写结果
  - [ ] 2.1.3 编写 NovelPipeline 扩展方法的单元测试 `tests/novel/test_pipeline_refinement.py`
    - [ ] 测试 proofread_chapter（正常、章节不存在）
    - [ ] 测试 apply_proofreading_fixes（正常、部分失败）
    - [ ] 测试 save_edited_chapter（正常、revision 保存）
    - [ ] 测试 analyze_setting_impact（正常、无影响）
    - [ ] 测试 save_setting（正常、备份检查）
    - [ ] 测试 rewrite_affected_chapters（正常、部分失败）
    - [ ] Mock FileManager、Proofreader、SettingImpactAnalyzer

---

### Phase 3: Web UI 实现（Gradio）

- [ ] **3.1 章节编辑 Tab**
  - [ ] 3.1.1 在 `web.py` 中添加"章节编辑" Tab
    - [ ] 创建 UI 组件
      - [ ] `edit_project_select`: Dropdown（项目选择）
      - [ ] `edit_chapter_num`: Number（章节号）
      - [ ] `edit_load_btn`: Button（加载章节）
      - [ ] `edit_text`: Textbox（编辑区，lines=25）
      - [ ] `edit_proofread_btn`: Button（AI 校对）
      - [ ] `edit_save_btn`: Button（保存章节）
      - [ ] `edit_issues_checkboxes`: CheckboxGroup（问题列表）
      - [ ] `edit_select_all_btn`: Button（全选）
      - [ ] `edit_select_none_btn`: Button（全不选）
      - [ ] `edit_apply_fixes_btn`: Button（应用修正）
      - [ ] `edit_status`: Textbox（状态显示）
      - [ ] `edit_issues_json`: State（隐藏状态，存储 issues）
    - [ ] 实现事件处理函数
      - [ ] `_on_edit_load_chapter(project, ch_num)` → 加载章节文本
      - [ ] `_on_edit_proofread(project, ch_num, text)` → AI 校对
        - [ ] 调用 `pipeline.proofread_chapter()`
        - [ ] 格式化为 Checkbox labels（含索引、图标、原文、修正）
        - [ ] 返回 checkbox choices + issues JSON
      - [ ] `_on_edit_select_all(choices)` → 全选
      - [ ] `_on_edit_select_none(choices)` → 全不选
      - [ ] `_on_edit_apply_fixes(project, ch_num, text, issues, selected)` → 应用修正
        - [ ] 解析 selected labels 提取索引
        - [ ] 调用 `pipeline.apply_proofreading_fixes()`
        - [ ] 返回修正后文本 + 状态消息
      - [ ] `_on_edit_save_chapter(project, ch_num, text)` → 保存章节
        - [ ] 调用 `pipeline.save_edited_chapter()`
        - [ ] 返回状态消息
    - [ ] 绑定事件
      - [ ] `edit_load_btn.click → _on_edit_load_chapter`
      - [ ] `edit_proofread_btn.click → _on_edit_proofread`
      - [ ] `edit_select_all_btn.click → _on_edit_select_all`
      - [ ] `edit_select_none_btn.click → _on_edit_select_none`
      - [ ] `edit_apply_fixes_btn.click → _on_edit_apply_fixes`
      - [ ] `edit_save_btn.click → _on_edit_save_chapter`
  - [ ] 3.1.2 手动测试章节编辑流程
    - [ ] 创建测试项目 → 生成1章
    - [ ] 加载章节 → 编辑文本 → AI 校对
    - [ ] 勾选问题 → 应用修正 → 保存章节
    - [ ] 验证 revision history 是否保存
    - [ ] 测试边界条件（空文本、超长文本、LLM 失败）

- [ ] **3.2 设定编辑 Tab**
  - [ ] 3.2.1 在 `web.py` 中添加"设定编辑" Tab
    - [ ] 创建 UI 组件
      - [ ] `setting_project_select`: Dropdown（项目选择）
      - [ ] `setting_load_btn`: Button（加载设定）
      - [ ] `setting_world_editor`: Code（世界观 JSON，language="json"）
      - [ ] `setting_char_editor`: Code（角色 JSON）
      - [ ] `setting_outline_editor`: Code（大纲 JSON）
      - [ ] `setting_analyze_btn`: Button（评估影响）
      - [ ] `setting_save_btn`: Button（保存设定）
      - [ ] `setting_impact_display`: JSON（影响报告）
      - [ ] `setting_save_only_future_btn`: Button（只改后续）
      - [ ] `setting_retroactive_btn`: Button（回溯修改）
      - [ ] `setting_status`: Textbox（状态显示）
      - [ ] `setting_modified_type`: State（当前修改类型，默认"world"）
    - [ ] 实现事件处理函数
      - [ ] `_on_setting_load(project)` → 加载设定
        - [ ] 调用 `pipeline.file_manager.load_novel()`
        - [ ] 提取 world_setting、characters、outline
        - [ ] 转换为 JSON 字符串
        - [ ] 返回三个编辑器内容
      - [ ] `_on_setting_analyze_impact(project, world_json, char_json, outline_json, modified_type)` → 评估影响
        - [ ] 解析 JSON（捕获 JSONDecodeError）
        - [ ] 调用 `pipeline.analyze_setting_impact()`
        - [ ] 返回影响报告 JSON
      - [ ] `_on_setting_save_only_future(project, world_json, modified_type)` → 只改后续
        - [ ] 解析 JSON
        - [ ] 调用 `pipeline.save_setting()`
        - [ ] 返回状态消息
      - [ ] `_on_setting_retroactive(project, impact)` → 回溯修改
        - [ ] 检查 affected_chapters 非空
        - [ ] 调用 `pipeline.rewrite_affected_chapters()`
        - [ ] 格式化重写结果
        - [ ] 返回状态消息
    - [ ] 绑定事件
      - [ ] `setting_load_btn.click → _on_setting_load`
      - [ ] `setting_analyze_btn.click → _on_setting_analyze_impact`
      - [ ] `setting_save_only_future_btn.click → _on_setting_save_only_future`
      - [ ] `setting_retroactive_btn.click → _on_setting_retroactive`
  - [ ] 3.2.2 手动测试设定编辑流程
    - [ ] 创建测试项目 → 生成3章
    - [ ] 加载设定 → 修改世界观（如改力量体系）→ 评估影响
    - [ ] 验证影响报告（受影响章节、冲突）
    - [ ] 测试"只改后续"（验证 novel.json 保存 + 备份）
    - [ ] 测试"回溯修改"（验证章节重写 + revision 保存）
    - [ ] 测试边界条件（JSON 格式错误、无影响、LLM 失败）

---

### Phase 4: 集成测试与优化

- [ ] **4.1 端到端集成测试**
  - [ ] 4.1.1 编写集成测试脚本 `tests/novel/integration/test_refinement_workflow.py`
    - [ ] 测试完整章节编辑流程
      - [ ] 创建项目 → 生成章节 → 加载 → 编辑 → 校对 → 应用修正 → 保存
      - [ ] 验证 revision history
    - [ ] 测试完整设定修订流程
      - [ ] 创建项目 → 生成章节 → 修改设定 → 评估影响 → 保存
      - [ ] 验证 setting_version 递增
      - [ ] 验证 novel.json 备份
    - [ ] 测试回溯修改流程
      - [ ] 创建项目 → 生成章节 → 修改设定 → 回溯修改
      - [ ] 验证章节重写 + revision 保存
  - [ ] 4.1.2 运行集成测试
    - [ ] 确保所有测试通过
    - [ ] 修复失败用例

- [ ] **4.2 性能优化**
  - [ ] 4.2.1 优化 AI 校对性能
    - [ ] 如果章节文本超过5000字，分段校对
    - [ ] 设置 `max_tokens=2048` 限制 LLM 返回长度
  - [ ] 4.2.2 优化影响评估性能
    - [ ] 限制章节摘要最多40章
    - [ ] 只加载摘要（前100字 + outline.goal），不加载全文
  - [ ] 4.2.3 优化回溯修改性能
    - [ ] 使用 ThreadPoolExecutor 并行重写章节
    - [ ] 提供 progress_callback 实时更新进度（TODO：Gradio 支持流式进度）

- [ ] **4.3 错误处理增强**
  - [ ] 4.3.1 增强 Proofreader 错误处理
    - [ ] LLM 返回无法解析 → 返回空列表 + 警告日志
    - [ ] 字符串替换失败 → 记录失败条目 + 继续处理
  - [ ] 4.3.2 增强 SettingImpactAnalyzer 错误处理
    - [ ] LLM 返回无法解析 → 返回空影响报告
    - [ ] 章节重写失败 → 记录失败章节 + 继续处理其他
  - [ ] 4.3.3 增强 Web UI 错误处理
    - [ ] JSON 解析错误 → 显示具体错误信息
    - [ ] LLM 调用失败 → 显示友好提示 + 重试建议

---

### Phase 5: 文档与部署

- [ ] **5.1 文档编写**
  - [ ] 5.1.1 更新 CLAUDE.md
    - [ ] 添加"章节编辑工作台"功能说明
    - [ ] 添加使用示例
  - [ ] 5.1.2 更新 README.md（如有）
    - [ ] 添加新功能截图/演示
  - [ ] 5.1.3 编写用户指南
    - [ ] 章节编辑步骤说明
    - [ ] 设定修订步骤说明
    - [ ] 常见问题 FAQ

- [ ] **5.2 代码审查**
  - [ ] 5.2.1 启动 code-reviewer Agent 审查新代码
    - [ ] 审查 Proofreader、SettingImpactAnalyzer
    - [ ] 审查 NovelPipeline 扩展
    - [ ] 审查 Web UI 代码
  - [ ] 5.2.2 修复 CRITICAL/HIGH 级别问题

- [ ] **5.3 部署准备**
  - [ ] 5.3.1 运行完整测试套件
    - [ ] `python -m pytest tests/novel/services/`
    - [ ] `python -m pytest tests/novel/test_pipeline_refinement.py`
    - [ ] `python -m pytest tests/novel/integration/`
  - [ ] 5.3.2 手动测试 Web UI 完整流程
  - [ ] 5.3.3 提交代码
    - [ ] Git commit 新增文件
    - [ ] Git commit 修改文件

---

## 任务依赖关系

```
Phase 1: 数据模型与基础服务
  ├── 1.1 创建数据模型 ← 无依赖
  ├── 1.2 实现 Proofreader 服务 ← 依赖 1.1
  └── 1.3 实现 SettingImpactAnalyzer 服务 ← 依赖 1.1

Phase 2: NovelPipeline 扩展
  ├── 2.1 扩展 NovelPipeline 方法 ← 依赖 1.2, 1.3

Phase 3: Web UI 实现
  ├── 3.1 章节编辑 Tab ← 依赖 2.1
  └── 3.2 设定编辑 Tab ← 依赖 2.1

Phase 4: 集成测试与优化
  ├── 4.1 端到端集成测试 ← 依赖 3.1, 3.2
  ├── 4.2 性能优化 ← 依赖 4.1
  └── 4.3 错误处理增强 ← 依赖 4.1

Phase 5: 文档与部署
  ├── 5.1 文档编写 ← 依赖 4.3
  ├── 5.2 代码审查 ← 依赖 5.1
  └── 5.3 部署准备 ← 依赖 5.2
```

---

## 预估工作量

| Phase | 任务数 | 预估时间 | 复杂度 |
|-------|-------|---------|--------|
| Phase 1 | 9 | 6-8h | 中等 |
| Phase 2 | 7 | 4-6h | 中等 |
| Phase 3 | 11 | 8-10h | 高 |
| Phase 4 | 10 | 4-6h | 中等 |
| Phase 5 | 8 | 2-3h | 低 |
| **总计** | **45** | **24-33h** | - |

---

## 风险与注意事项

### 技术风险
1. **Gradio CheckboxGroup 索引映射**：checkbox 返回 label 列表，需要映射回 issue 索引
   - 缓解：在 label 中嵌入索引（如 `[0] 标点 - ...`）
2. **LLM 校对准确率**：可能误报或漏检
   - 缓解：用户可逐条选择，不盲目接受
3. **影响评估召回率**：AI 可能漏检某些冲突
   - 缓解：影响报告由用户确认，不自动修改

### 开发风险
1. **Web UI 调试困难**：Gradio 无自动化测试框架
   - 缓解：充分单元测试后端，手动测试 UI
2. **JSON 编辑体验差**：用户需手动保证格式正确
   - 缓解：捕获 JSONDecodeError，显示友好提示

### 用户体验风险
1. **回溯修改时间长**：重写20章可能需5-10分钟
   - 缓解：提供进度显示（TODO：需 Gradio 支持流式进度）
2. **修正应用失败**：原文片段不匹配
   - 缓解：记录失败条目，显示给用户

---

## 测试清单

### 单元测试
- [ ] `tests/novel/models/test_refinement.py`（模型验证）
- [ ] `tests/novel/services/test_proofreader.py`（AI 校对）
- [ ] `tests/novel/services/test_setting_impact_analyzer.py`（影响评估）
- [ ] `tests/novel/test_pipeline_refinement.py`（Pipeline 扩展）

### 集成测试
- [ ] `tests/novel/integration/test_refinement_workflow.py`（完整流程）

### 手动测试
- [ ] 章节编辑流程（加载 → 编辑 → 校对 → 修正 → 保存）
- [ ] 设定修订流程（加载 → 修改 → 评估 → 保存/回溯）
- [ ] 边界条件（空文本、超长文本、JSON 错误、LLM 失败）

---

## 完成标准

- [ ] 所有单元测试通过（100% 覆盖核心逻辑）
- [ ] 所有集成测试通过
- [ ] Web UI 手动测试通过（章节编辑 + 设定修订）
- [ ] 代码审查无 CRITICAL/HIGH 级别问题
- [ ] 文档更新完成（CLAUDE.md + 用户指南）
- [ ] 用户能在 Web UI 中完成完整流程（3-5步）

---

## 优先级说明

### P0（必须实现）
- Phase 1: 数据模型与基础服务（核心逻辑）
- Phase 2: NovelPipeline 扩展（API 层）
- Phase 3.1: 章节编辑 Tab（基础 UI）

### P1（重要）
- Phase 3.2: 设定编辑 Tab（高级 UI）
- Phase 4: 集成测试与优化

### P2（可选）
- Phase 4.2.3: 并行重写优化（性能优化）
- Phase 5.1.3: 用户指南（文档完善）

---

## 开发建议

1. **并行开发**：Phase 1 和 Phase 2 可由不同 task-executor Agent 并行实现
2. **优先后端**：先完成 Phase 1-2（后端逻辑），再开发 Phase 3（UI）
3. **充分测试**：每个 Phase 完成后立即编写测试，避免后期返工
4. **渐进交付**：先实现 P0 功能（章节编辑），验证可行性后再实现 P1（设定修订）
5. **用户反馈**：手动测试时邀请用户试用，收集反馈迭代改进
