# Requirements: 章节编辑工作台

## 1. 功能概述

为 AI 小说创作平台增加两个精修功能：
1. **章节编辑 + AI 校对**：用户手动编辑章节后，AI 检查语言问题（标点、语法、错别字、用词）
2. **设定/大纲修订 + 影响评估**：修改世界观/角色/大纲设定时，AI 分析对已写章节的影响，支持回溯修改

这两个功能组成"精修工作台"，让用户能够深度参与小说润色和设定调整。

---

## 2. 用户故事

### US-1: 章节编辑与 AI 校对

**角色**：小说作者

**需求**：
- 作为小说作者，我希望能在 Web UI 中加载某章内容、手动编辑文本
- 编辑后，我希望点击"AI 校对"按钮，让 AI 自动检查语言层面的问题（不改内容逻辑）
- AI 应返回结构化的问题清单，每条包含：位置、原文、修正建议、问题类型
- 我可以逐条勾选接受/拒绝，最后点击"应用修正"自动替换选中的问题
- 保存后，修改后的文本应作为新版本保存（利用现有 revision 机制）

**验收标准**：
1. **WHEN** 用户在编辑区加载第5章并修改部分文本
   - **THEN** 编辑区显示章节全文，用户可自由编辑
2. **WHEN** 用户点击"AI 校对"
   - **THEN** AI 分析当前编辑区文本，返回 JSON 格式问题清单
   - **AND** 问题清单至少包含：标点错误、语法问题、错别字、用词不当
3. **WHEN** AI 校对返回结果
   - **THEN** 前端以 Checkbox 列表展示每个问题，默认全选
   - **AND** 每条显示：问题类型、原文片段、修正建议
4. **WHEN** 用户取消勾选某些问题，点击"应用修正"
   - **THEN** 仅应用选中的修正，更新编辑区文本
5. **WHEN** 用户点击"保存章节"
   - **THEN** 保存修改后文本到 `chapter_NNN.txt`
   - **AND** 原文本保存到 revision history

**边界条件**：
- 如果章节文本为空，"AI 校对"按钮禁用
- 如果 AI 返回空问题列表，显示"未发现明显语言问题"
- 如果 AI 返回超过50条问题，仅显示前50条（避免 UI 卡顿）
- 如果修正应用失败（如原文片段不匹配），跳过该条并警告用户

**性能要求**：
- AI 校对响应时间 < 30秒（3000字章节）
- 应用修正操作 < 2秒

---

### US-2: 设定/大纲修订与影响评估

**角色**：小说作者

**需求**：
- 作为小说作者，我希望在 Web UI 中查看/编辑世界观设定、角色设定、大纲
- 修改后，我希望点击"评估影响"，让 AI 分析修改对已写章节的影响
- AI 应返回影响报告：哪些章节受影响、具体矛盾点
- 我可以选择"只改后续"（保存新设定，后续章节按新设定写）或"回溯修改"（重写受影响章节）
- 如选"回溯修改"，AI 应按新设定逐章重写，每章重写前需我确认

**验收标准**：
1. **WHEN** 用户选择某个项目，点击"编辑设定"
   - **THEN** 显示三个可编辑区域：世界观、角色列表、大纲
   - **AND** 加载 `novel.json` 中的 `world_setting`、`characters`、`outline`
2. **WHEN** 用户修改世界观（如将"修炼境界上限"从筑基改为金丹），点击"评估影响"
   - **THEN** AI 对比 old vs new 设定，扫描已写章节（读取 `chapter_*.json`）
   - **AND** 返回影响报告 JSON：`{ "affected_chapters": [3, 5], "conflicts": ["第3章主角突破筑基与新设定矛盾"] }`
3. **WHEN** 影响报告显示有冲突，用户点击"只改后续"
   - **THEN** 保存新设定到 `novel.json`
   - **AND** 在 `novel.json` 中标记 `setting_version: 2`，后续章节按新设定生成
   - **AND** 已写章节不修改
4. **WHEN** 用户点击"回溯修改受影响章节"
   - **THEN** 弹出确认框，列出待修改章节：第3章、第5章
   - **AND** 用户点击"确认"后，进入逐章重写流程
5. **WHEN** 进入逐章重写流程
   - **THEN** 对每章显示：修改前文本预览、AI 重写后文本预览
   - **AND** 用户可以"接受重写"/"跳过"/"手动调整"
6. **WHEN** 所有受影响章节处理完毕
   - **THEN** 保存新设定 + 更新受影响章节
   - **AND** 更新 NovelMemory（如角色关系图、伏笔网络）

**边界条件**：
- 如果修改设定后，AI 未检测到任何冲突，显示"修改未影响已写章节"
- 如果受影响章节超过20章，警告用户"影响范围过大，建议分批修改或开新卷"
- 如果用户修改大纲（增删章节），需重新计算 `target_words` 和 `current_chapter`

**安全要求**：
- 修改设定前，备份原 `novel.json` 到 `revisions/novel_backup_TIMESTAMP.json`
- 回溯修改章节时，原章节自动保存到 revision history

**性能要求**：
- 影响评估响应时间 < 60秒（扫描40章）
- 单章重写 < 30秒

---

## 3. 功能细节

### 3.1 章节编辑 + AI 校对

#### 3.1.1 AI 校对 Prompt 设计

**输入**：章节文本（`full_text`）

**Prompt**：
```
你是一位资深文字编辑。请检查以下小说章节的语言问题，返回结构化问题清单。

【检查范围】
- 标点符号错误（如逗号误用顿号、引号不匹配、句号漏加）
- 语法问题（如主谓不一致、歧义句、病句）
- 错别字（如"的地得"混用、同音字错误）
- 用词不当（如网络流行语混入古代背景、口语化过重）

【不检查的内容】
- 情节逻辑（即使有矛盾也不管）
- 人物性格（即使 OOC 也不管）
- 重复内容（这是风格问题，不是语言问题）

【章节文本】
{full_text}

返回 JSON：
{
    "issues": [
        {
            "type": "punctuation|grammar|typo|word_choice",
            "location": "段落索引或文本片段定位",
            "original": "原文（30字以内）",
            "correction": "修正后",
            "reason": "简短说明（一句话）"
        }
    ]
}

要求：
1. 每条问题的 original 必须是原文中能精确匹配的片段（用于字符串替换）
2. 如果没有明显语言问题，返回 {"issues": []}
3. 不要过度纠错（如"有点儿"改"有些"这种可接受变体不算错）
```

**输出**：结构化 JSON

**稳健性**：
- 使用 `extract_json_from_llm()` 解析 LLM 返回
- 如果 LLM 返回无法解析，返回空问题列表 + 警告日志

#### 3.1.2 前端 UI 设计（Gradio）

**编辑区布局**：
```
┌─────────────────────────────────────────────┐
│ 章节编辑                                     │
├─────────────────────────────────────────────┤
│ [Dropdown: 选择章节] [Load]                 │
│ [Textbox: 章节文本，lines=25, interactive]  │
│ [Button: AI 校对] [Button: 保存章节]        │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ 校对结果                                     │
├─────────────────────────────────────────────┤
│ [Markdown: 显示问题清单]                     │
│ [ ] 标点 - 第3段："你好吗。" → "你好吗？"   │
│ [ ] 语法 - 第5段："他们都很高兴" → "他们都很高兴" │
│ ...                                          │
│ [Button: 全选] [Button: 全不选]             │
│ [Button: 应用选中的修正]                     │
└─────────────────────────────────────────────┘
```

**实现方案**：
- 用 `gr.CheckboxGroup` 展示问题列表（每条问题格式化为字符串）
- 问题字符串格式：`{type_icon} - {original[:20]}... → {correction[:20]}... | {reason}`
- 用户选中的 checkbox values 对应问题索引
- 点击"应用修正"时，按索引批量应用字符串替换

**限制**：
- Gradio 没有富文本编辑器，无法实现"高亮原文位置"
- 使用 Markdown + Checkbox 组合是最接近的方案

#### 3.1.3 修正应用逻辑

**流程**：
1. 用户勾选问题 #1, #3, #5
2. 前端收集对应的 `issues[1]`, `issues[3]`, `issues[5]`
3. 按顺序应用字符串替换：`text = text.replace(issue["original"], issue["correction"])`
4. 如果某条替换失败（原文不匹配），跳过并记录警告
5. 更新编辑区文本

**问题**：如果多条问题涉及同一位置，替换顺序可能导致冲突

**解决**：
- 按 `original` 在文本中的位置从后往前排序（避免替换后位置偏移）
- 如果检测到多条问题有重叠区域，合并为一条（LLM prompt 中要求避免重叠）

---

### 3.2 设定/大纲修订 + 影响评估

#### 3.2.1 设定编辑 UI

**布局**：
```
┌─────────────────────────────────────────────┐
│ 设定编辑                                     │
├─────────────────────────────────────────────┤
│ [Tabs]                                       │
│   - 世界观                                   │
│     [Textbox: world_setting JSON 编辑]      │
│   - 角色设定                                 │
│     [Textbox: characters JSON 编辑]         │
│   - 大纲                                     │
│     [Textbox: outline JSON 编辑]            │
├─────────────────────────────────────────────┤
│ [Button: 评估影响] [Button: 保存设定]       │
└─────────────────────────────────────────────┘
```

**数据格式**：
- 用 `gr.Code(language="json")` 展示 JSON（支持语法高亮）
- 或用 `gr.Textbox` + 手动格式化

**保存逻辑**：
1. 解析用户编辑的 JSON
2. 验证 Pydantic 模型（`WorldSetting.model_validate()`）
3. 保存到 `novel.json`

#### 3.2.2 影响评估 Prompt 设计

**输入**：
- 修改前设定（`old_world`）
- 修改后设定（`new_world`）
- 已写章节列表（`chapters: list[{chapter_number, title, summary}]`）

**Prompt**：
```
用户修改了小说设定，请分析修改对已写章节的影响。

【修改前设定】
{old_world_json}

【修改后设定】
{new_world_json}

【已写章节摘要】
{chapters_summary}

返回 JSON：
{
    "affected_chapters": [受影响的章节号列表],
    "conflicts": [
        {
            "chapter": 章节号,
            "conflict": "具体矛盾描述",
            "severity": "low|medium|high"
        }
    ],
    "recommendation": "建议：只改后续|回溯修改|拆分为新卷"
}

分析要点：
1. 如果修改的设定在已写章节中未涉及，affected_chapters 为空
2. 如果修改导致设定矛盾（如主角已突破的境界在新设定中不存在），severity=high
3. 如果修改只是细节优化（如境界名称改了但结构不变），severity=low
4. 如果受影响章节超过20章，建议拆分为新卷
```

**输出**：结构化 JSON

#### 3.2.3 回溯修改流程

**流程**：
1. 用户点击"回溯修改"
2. 对每个受影响章节 `ch`：
   - 调用 `Writer.rewrite_chapter(ch, rewrite_instruction="按新设定修改：{conflict}")`
   - 显示修改前/后预览
   - 用户确认"接受"/"跳过"/"手动调整"
3. 保存所有接受的重写
4. 更新 NovelMemory

**技术实现**：
- 调用现有 `Writer.rewrite_chapter()` 方法（已支持 `rewrite_instruction`）
- 重写前，原章节自动保存到 `FileManager.save_chapter_revision()`
- 重写后，更新 `chapter.full_text` 和 `chapter.revision_count += 1`

**UI 流程**：
```
┌─────────────────────────────────────────────┐
│ 回溯修改预览                                 │
├─────────────────────────────────────────────┤
│ 第3章「境界突破」                            │
│ 冲突：主角突破筑基，但新设定已删除筑基境界   │
│                                              │
│ [Tab: 修改前] [Tab: 修改后]                 │
│ ... 章节文本预览 ...                         │
│                                              │
│ [Button: 接受重写] [Button: 跳过] [Button: 手动调整] │
└─────────────────────────────────────────────┘
```

---

## 4. 数据模型

### 4.1 新增模型（可选）

#### ProofreadingIssue
```python
class ProofreadingIssue(BaseModel):
    """AI 校对问题条目"""
    issue_id: str = Field(default_factory=lambda: str(uuid4()))
    type: Literal["punctuation", "grammar", "typo", "word_choice"]
    location: str = Field(..., description="段落索引或文本片段定位")
    original: str = Field(..., max_length=100, description="原文片段")
    correction: str = Field(..., max_length=100, description="修正后")
    reason: str = Field(..., max_length=200, description="修正原因")
```

#### SettingImpact
```python
class SettingImpact(BaseModel):
    """设定修改影响评估结果"""
    impact_id: str = Field(default_factory=lambda: str(uuid4()))
    modified_setting: Literal["world", "character", "outline"]
    old_value: dict = Field(..., description="修改前设定（JSON）")
    new_value: dict = Field(..., description="修改后设定（JSON）")
    affected_chapters: list[int] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    recommendation: str = Field(..., description="建议")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
```

### 4.2 现有模型扩展

#### Novel（扩展）
```python
class Novel(BaseModel):
    # ... 现有字段 ...

    # 新增：设定版本管理
    setting_version: int = Field(1, description="设定版本号，修改设定时递增")
    setting_history: list[dict] = Field(default_factory=list, description="设定修改历史")
```

---

## 5. 非功能需求

### 5.1 性能

- AI 校对（3000字章节）：< 30秒
- 影响评估（40章）：< 60秒
- 单章重写：< 30秒

### 5.2 安全

- 所有修改操作前自动备份原文件
- 用户手动编辑的文本不自动覆盖（需点击"保存"）
- 设定修改前备份 `novel.json` 到 `revisions/`

### 5.3 可用性

- UI 操作流程简洁（不超过3步）
- 错误信息清晰（如"第5章原文不匹配，修正失败"）
- 支持撤销（通过 revision history 恢复）

### 5.4 可测试性

- 所有 LLM 调用可 Mock
- 影响评估逻辑可单元测试（无需真实章节文件）
- UI 操作可手动测试（Gradio 无自动化测试框架）

---

## 6. 优先级

### P0（必须有）
- 章节编辑 + AI 校对（基础语言问题检查）
- 设定编辑 + 保存
- 影响评估（检测冲突）

### P1（重要）
- 修正应用（批量字符串替换）
- 回溯修改（逐章重写预览 + 确认）

### P2（可选）
- 设定版本管理（历史回滚）
- 影响评估智能建议（如"建议拆分为新卷"）
- 手动调整重写（用户编辑 AI 重写的文本）

---

## 7. 依赖

### 外部依赖
- LLM 后端（Gemini/DeepSeek/OpenAI/Ollama）
- 现有 `Writer.rewrite_chapter()` 方法
- 现有 `FileManager.save_chapter_revision()` 方法

### 内部模块
- `src/novel/pipeline.py`：调用 Writer、FileManager
- `src/novel/storage/file_manager.py`：读写 chapter、novel.json、revision
- `src/novel/agents/writer.py`：重写章节
- `src/llm/llm_client.py`：LLM 调用

---

## 8. 限制与风险

### 限制
- Gradio 无富文本编辑器，无法实现"点击问题跳转到原文位置"
- JSON 编辑体验较差（用户需手动保证格式正确）
- 大纲修改（增删章节）可能导致 `current_chapter` 错乱

### 风险
- LLM 校对可能误报（如将成语当错别字）
- 影响评估可能漏检（AI 未发现的矛盾）
- 回溯修改大量章节可能导致风格不一致

### 缓解措施
- 校对结果支持用户逐条选择（避免盲目接受）
- 影响评估结果由用户确认（不自动重写）
- 回溯修改前强制备份

---

## 9. 成功指标

- 用户能在 Web UI 中完成章节编辑 + 校对 + 保存（3步）
- 用户能在 Web UI 中修改设定 + 评估影响 + 选择修改策略（5步）
- AI 校对准确率 > 80%（基于人工抽查）
- 影响评估召回率 > 70%（真正受影响的章节中，AI 识别出的比例）
