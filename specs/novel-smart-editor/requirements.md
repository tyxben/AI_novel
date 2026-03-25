# 小说智能编辑系统需求规格

## 1. 项目背景

### 1.1 现状问题
当前 AI 小说创作平台存在以下关键问题：

1. **编辑逻辑嵌入 UI 层** — `web.py` 中 500+ 行表单处理和 JSON 操作（lines 1860-2360）
2. **MCP 无编辑能力** — `mcp_server.py` 只提供创建和生成工具，AI 助手无法修改设定
3. **依赖人工操作** — 需手动填写 Gradio 表单修改角色、大纲、世界观，违背 AI 创作初衷
4. **缺乏生效机制** — 修改立即全局生效，破坏已发表章节的连续性
5. **无变更追踪** — 缺少修改历史记录，无法审计或回滚变更

### 1.2 核心目标
设计一个智能编辑系统，使用户能够通过自然语言指令完成设定修改，系统自动：

- 解析用户意图（增/删/改 角色、大纲、世界观）
- 生成完整结构化数据（符合 Pydantic 模型）
- 标记生效起始章节（`effective_from_chapter`）
- 分析对已写章节的影响
- 可选：自动重写受影响章节

### 1.3 用户故事

**US-1: 自然语言添加角色**
> 作为小说作者，我想说"加一个30岁女剑客反派，第10章出场"，系统能自动生成完整角色档案并标记生效章节，这样我不必手动填表。

**US-2: 批量修改大纲**
> 作为小说作者，我想说"把第15-20章的主线从复仇改为寻宝"，系统能批量修改章节大纲并分析影响，这样我能快速调整故事走向。

**US-3: MCP 远程编辑**
> 作为 AI 助手用户，我想通过 Claude Desktop 调用 MCP 工具修改小说设定，而不是打开 Web UI，这样更符合我的工作流。

**US-4: 变更历史审计**
> 作为小说作者，我想查看所有设定变更记录（who/what/when/effective_from），并在需要时回滚，这样我能避免改坏设定。

**US-5: 影响分析预览**
> 作为小说作者，我想在应用变更前看到影响分析（哪些章节会受影响、有哪些矛盾），这样我能决定是否重写章节。

**US-6: 分卷大纲编辑**
> 作为小说作者，我想说"修改第2卷的核心矛盾为XXX"，系统能更新卷大纲并重新生成该卷的章节大纲（如果还未写完），这样我能保持大纲一致性。

## 2. 功能需求

### 2.1 自然语言编辑接口

**FR-1.1 意图识别**
- 系统应能从用户自然语言指令中识别：
  - 操作类型：add / update / delete
  - 目标实体：character / outline / world_setting / volume / chapter
  - 生效章节：`effective_from_chapter`（默认为当前写作进度 + 1）
  - 具体变更内容

**FR-1.2 结构化数据生成**
- 对于 `add character`，系统应生成完整的 `CharacterProfile` 对象：
  - 自动推断缺失字段（年龄、性格、外貌等）
  - 生成符合 Pydantic 验证的数据
  - 分配唯一 `character_id`（UUID）

**FR-1.3 智能字段推断**
- 当用户指令不完整时（如"加一个女剑客"），系统应：
  - 基于小说现有设定推断缺失字段（世界观、力量体系等）
  - 保持风格一致性（如玄幻小说的命名风格）
  - 为可选字段填充合理默认值

### 2.2 生效机制

**FR-2.1 版本化设定**
- 每个设定对象应包含 `effective_from_chapter` 字段
- 支持同一实体的多个版本（如角色第10章前后状态不同）
- 查询时根据章节号返回正确版本的设定

**FR-2.2 影响分析**
- 系统应分析设定变更对已写章节的影响：
  - 识别受影响章节范围（`affected_chapters: list[int]`）
  - 检测具体矛盾点（如角色未登场就出现对话）
  - 计算影响严重度（low / medium / high）
  - 生成修改建议（`suggested_fix`）

**FR-2.3 只读保护**
- 已发表章节（`status: "published"`）的设定应为只读
- 修改应自动标记 `effective_from_chapter` 为下一章
- 提供 `force` 参数允许管理员覆写保护（需显式确认）

### 2.3 变更历史管理

**FR-3.1 变更记录**
- 每次修改应记录：
  - `change_id`（UUID）
  - `timestamp`（ISO 格式）
  - `change_type`：add / update / delete
  - `target_entity_type`：character / outline / world_setting 等
  - `target_entity_id`：实体 ID
  - `old_value`：旧值快照（JSON）
  - `new_value`：新值快照（JSON）
  - `effective_from_chapter`：生效章节
  - `applied_by`：操作来源（web / mcp / cli）
  - `instruction`：用户原始指令

**FR-3.2 回滚功能**
- 支持按 `change_id` 回滚单次变更
- 回滚时检查依赖关系（如回滚角色删除需检查后续章节是否使用）
- 生成新的 `change_id`（而非真删除历史记录）

### 2.4 批量操作支持

**FR-4.1 章节范围编辑**
- 支持批量修改章节大纲（如"第10-15章都改为过渡章节"）
- 支持条件筛选（如"把所有mood=大爽的章节改为小爽"）

**FR-4.2 关系型变更**
- 修改角色时自动更新关联数据：
  - 删除角色时清理 `relationships` 中的引用
  - 修改角色名时更新 `involved_characters` 中的引用
  - 修改世界观时标记所有使用该设定的章节

### 2.5 三端共用接口

**FR-5.1 Web UI 集成**
- `web.py` 通过服务层调用，移除直接 JSON 操作
- AI 编辑框复用服务层的自然语言解析
- 表单编辑转换为结构化指令调用服务层

**FR-5.2 MCP 工具暴露**
- 新增 `novel_edit_setting` 工具：
  - 参数：`project_path`, `instruction`, `effective_from_chapter`, `dry_run`
  - 返回：变更分析 + 应用结果
- 新增 `novel_analyze_change_impact` 工具（仅分析不应用）
- 新增 `novel_rollback_change` 工具（回滚变更）

**FR-5.3 CLI 支持**
- `main.py novel edit <project> --instruction "..." --dry-run`
- `main.py novel history <project> --limit 10`
- `main.py novel rollback <project> <change_id>`

## 3. 非功能需求

### 3.1 性能要求

**NFR-1.1 响应时间**
- 简单编辑（单字段修改）< 2s
- 复杂编辑（生成完整角色）< 10s
- 影响分析（已写50章）< 5s

**NFR-1.2 并发支持**
- Web UI 多标签页同时编辑不冲突（文件锁 + 时间戳检查）
- 禁止同时修改同一实体（乐观锁，基于 `updated_at` 字段）

### 3.2 可靠性要求

**NFR-2.1 数据一致性**
- 所有修改需通过 Pydantic 验证
- 外键引用完整性（如 `character_id` 必须存在）
- 原子性操作（变更成功或完全回滚）

**NFR-2.2 备份机制**
- 修改前自动备份 `novel.json` 到 `revisions/`
- 保留最近 20 次备份（或最近 30 天）
- 灾难恢复文档（如何从备份恢复）

### 3.3 可用性要求

**NFR-3.1 错误处理**
- LLM 解析失败时提供候选解释（"你是想...吗？"）
- 显示具体错误位置（如哪个字段验证失败）
- 提供修正建议（如"occupation 不能为空，建议填写：剑客/商人/..."）

**NFR-3.2 用户体验**
- 自然语言指令支持中英文
- 支持模糊匹配（如"李明" vs "李明（男，剑客）"）
- 提供变更预览（dry_run 模式）

### 3.4 可扩展性要求

**NFR-4.1 新实体类型支持**
- 编辑系统应易于扩展到新实体类型（如 `Faction`、`Item`）
- 使用注册表模式（Registry Pattern）管理实体编辑器

**NFR-4.2 自定义验证规则**
- 支持小说特定验证规则（如"主角不能在第1章死亡"）
- 验证规则可通过配置文件定义

## 4. 技术约束

### 4.1 必须遵守的约束

**TC-1.1 现有架构兼容**
- 复用 `create_llm_client` 接口（SYNC）
- 复用 `FileManager` 存储层
- 扩展 Pydantic 模型而非重建
- 不破坏 `create_novel` / `generate_chapters` 流程

**TC-1.2 数据模型扩展**
- 在 `CharacterProfile` / `ChapterOutline` / `WorldSetting` 中添加：
  - `effective_from_chapter: int | None` 字段
  - `version: int` 字段（版本号，从 1 开始）
  - `deprecated_at_chapter: int | None` 字段（被替换时标记）

**TC-1.3 存储层扩展**
- `FileManager` 新增方法：
  - `save_change_log(novel_id, change_entry_dict) -> Path`
  - `list_change_logs(novel_id, limit) -> list[dict]`
  - `load_change_log(novel_id, change_id) -> dict | None`

### 4.2 可选约束

**TC-2.1 LLM 后端**
- 默认使用 DeepSeek（便宜 + JSON mode 稳定）
- 允许降级到规则解析（如 LLM 不可用时）

**TC-2.2 测试要求**
- 所有外部依赖必须 Mock（LLM、FileManager）
- 覆盖边界条件（空值、超长输入、并发编辑）
- 回归测试：修改不能破坏现有测试

## 5. 验收标准

### 5.1 功能验收

**AC-1: 自然语言添加角色**
```python
result = editor.edit(
    project_path="workspace/novels/novel_123",
    instruction="加一个30岁女剑客反派，名叫柳青鸾，第10章出场",
    dry_run=False,
)
assert result["change_type"] == "add"
assert result["target_entity_type"] == "character"
assert result["new_value"]["name"] == "柳青鸾"
assert result["new_value"]["effective_from_chapter"] == 10
```

**AC-2: 影响分析**
```python
result = editor.edit(
    project_path="workspace/novels/novel_123",
    instruction="删除角色李明",
    dry_run=True,
)
assert result["affected_chapters"] == [5, 8, 12]
assert result["severity"] == "high"
assert len(result["conflicts"]) > 0
```

**AC-3: MCP 工具调用**
```bash
# Claude Desktop 调用 MCP 工具
novel_edit_setting(
    project_path="workspace/novels/novel_123",
    instruction="修改第15章的mood为大爽",
)
# 应返回 {"change_id": "...", "status": "success"}
```

**AC-4: 回滚变更**
```python
result = editor.rollback(
    project_path="workspace/novels/novel_123",
    change_id="change_abc123",
)
assert result["status"] == "reverted"
assert "new_change_id" in result  # 回滚本身也是一次变更
```

### 5.2 非功能验收

**AC-5: 响应时间**
- 简单修改（单字段）在本地环境 < 2s（95th percentile）
- 生成完整角色 < 10s（95th percentile）

**AC-6: 数据一致性**
- 100 次随机编辑后，`novel.json` 仍能通过 `Novel.model_validate()`
- 删除角色后，所有 `relationships` 中无悬空引用

**AC-7: 并发安全**
- 两个 Web UI 标签页同时修改同一角色时，后者应收到冲突提示
- 使用乐观锁（基于 `updated_at`），拒绝过期修改

## 6. 实施优先级

### P0（核心流程，第一批实施）
- FR-1.1, FR-1.2：自然语言解析 + 结构化生成
- FR-2.1：版本化设定机制
- FR-5.1：Web UI 集成（替换现有编辑逻辑）
- NFR-2.1：数据一致性保证

### P1（增强功能，第二批实施）
- FR-2.2：影响分析
- FR-3.1：变更历史记录
- FR-5.2：MCP 工具暴露
- FR-5.3：CLI 支持

### P2（高级功能，后续迭代）
- FR-2.3：只读保护
- FR-3.2：回滚功能
- FR-4.1, FR-4.2：批量操作
- NFR-1.2：并发控制

## 7. 风险与缓解

### 7.1 技术风险

**R-1: LLM 解析不稳定**
- 风险：用户指令复杂时 LLM 可能误解
- 缓解：
  - 提供结构化模板（"请按以下格式输入..."）
  - 显示解析结果预览，要求用户确认
  - 兜底规则解析器（基于正则表达式）

**R-2: 版本化数据复杂度**
- 风险：同一实体多版本可能导致查询逻辑复杂
- 缓解：
  - 提供 `get_setting_at_chapter(entity_type, entity_id, chapter_num)` 辅助函数
  - 在 `NovelMemory` 中缓存当前版本映射

**R-3: 向后兼容性破坏**
- 风险：新增字段导致旧项目加载失败
- 缓解：
  - 所有新字段设为可选（`Field(default=None)`）
  - 提供迁移脚本（`migrate_project_v1_to_v2.py`）

### 7.2 业务风险

**R-4: 用户学习成本**
- 风险：自然语言编辑方式对用户陌生
- 缓解：
  - 提供示例库（"常见编辑操作示例"）
  - 保留表单编辑方式（双轨并行）
  - 内置帮助文档（`/help edit`）

## 8. 成功指标

### 8.1 定量指标
- 编辑操作成功率 > 95%（LLM 正确解析用户意图）
- 平均编辑时间 < 5s（从输入到应用）
- Web UI 表单编辑使用率下降 > 50%（说明自然语言更受欢迎）
- MCP 工具调用占比 > 30%（说明 AI 助手集成成功）

### 8.2 定性指标
- 用户反馈"编辑设定更方便了"（问卷调查 > 4/5 分）
- 代码可维护性提升（编辑逻辑从 web.py 抽离）
- 测试覆盖率 > 80%（核心编辑逻辑）

## 9. 术语表

| 术语 | 定义 |
|------|------|
| 生效章节 | `effective_from_chapter`，设定变更从哪一章开始生效 |
| 版本化设定 | 同一实体在不同章节有不同状态（如角色前后性格变化） |
| 影响分析 | 检测设定变更对已写章节的影响（矛盾检测） |
| 干运行 | `dry_run=True`，仅分析不实际应用变更 |
| 变更日志 | `ChangeLog`，记录所有设定修改历史 |
| 乐观锁 | 基于 `updated_at` 时间戳的并发控制机制 |

## 10. 参考资料

### 10.1 现有代码
- `web.py` lines 1860-2360：现有编辑实现
- `src/novel/pipeline.py`：创作流水线
- `src/novel/models/`：数据模型定义
- `src/novel/storage/file_manager.py`：存储层

### 10.2 相关规范
- Pydantic 数据验证：https://docs.pydantic.dev/
- MCP 工具协议：https://modelcontextprotocol.io/
- EARS 需求语法：Easy Approach to Requirements Syntax
