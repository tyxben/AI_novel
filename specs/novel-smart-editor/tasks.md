# 小说智能编辑系统实施任务清单

## 版本信息
- **规格版本**: v1.0
- **创建日期**: 2026-03-24
- **预计工期**: 3-4 周（按优先级分批实施）

## 任务分组与优先级

### P0 - 核心流程（第一批，预计 1.5 周）
基础架构搭建，实现最小可用版本（MVP）

### P1 - 增强功能（第二批，预计 1 周）
MCP 集成、影响分析、变更历史

### P2 - 高级功能（第三批，预计 1 周）
批量操作、回滚、并发控制、性能优化

---

## P0: 核心流程任务

### 1. 数据模型扩展
**优先级**: P0-Critical
**预计工时**: 2h
**依赖**: 无

**子任务**:
- [x] 1.1 扩展 `CharacterProfile` 模型
  - 添加 `effective_from_chapter: int | None = None`
  - 添加 `deprecated_at_chapter: int | None = None`
  - 添加 `version: int = Field(1, ge=1)`
  - 编写单元测试验证向后兼容性

- [x] 1.2 扩展 `ChapterOutline` 模型
  - 添加相同版本字段
  - 测试 Pydantic 验证

- [x] 1.3 扩展 `WorldSetting` 模型
  - 添加相同版本字段
  - 测试 Pydantic 验证

- [ ] 1.4 扩展 `VolumeOutline` 模型（可选）
  - 添加相同版本字段

**验收标准**:
```python
# 测试向后兼容
old_char = {"name": "李明", "gender": "男", ...}
assert CharacterProfile.model_validate(old_char)  # 不报错

# 测试新字段
new_char = {"name": "李明", ..., "effective_from_chapter": 10}
assert CharacterProfile.model_validate(new_char).version == 1
```

**输出文件**:
- `src/novel/models/character.py` (修改)
- `src/novel/models/novel.py` (修改)
- `src/novel/models/world.py` (修改)
- `tests/novel/models/test_versioned_models.py` (新增)

---

### 2. 基础编辑器抽象
**优先级**: P0-Critical
**预计工时**: 4h
**依赖**: 任务 1

**子任务**:
- [x] 2.1 创建 `BaseEditor` 抽象类
  - 定义 `apply()` 抽象方法
  - 实现 `_add_version_fields()` 通用方法
  - 实现 `_deprecate_old_version()` 通用方法

- [x] 2.2 实现 `CharacterEditor`
  - `_add_character()` 方法
  - `_update_character()` 方法（简单原地更新）
  - `_delete_character()` 方法（软删除）
  - 单元测试（Mock FileManager）

- [x] 2.3 实现 `OutlineEditor`
  - `_edit_chapter_outline()` 方法
  - `_add_chapter_outline()` 方法
  - 单元测试

- [x] 2.4 实现 `WorldSettingEditor`
  - `_update_world_setting()` 方法
  - 单元测试

**验收标准**:
```python
editor = CharacterEditor(mock_file_manager)
novel_data = {"characters": []}
change = {"change_type": "add", "data": {...}}

old, new = editor.apply(novel_data, change)
assert old is None
assert new["character_id"] is not None
assert len(novel_data["characters"]) == 1
```

**输出文件**:
- `src/novel/editors/__init__.py` (新增)
- `src/novel/editors/base.py` (新增)
- `src/novel/editors/character_editor.py` (新增)
- `src/novel/editors/outline_editor.py` (新增)
- `src/novel/editors/world_editor.py` (新增)
- `tests/novel/editors/test_character_editor.py` (新增)
- `tests/novel/editors/test_outline_editor.py` (新增)

---

### 3. 文件管理器扩展
**优先级**: P0-Critical
**预计工时**: 2h
**依赖**: 无

**子任务**:
- [x] 3.1 新增 `save_backup()` 方法
  - 复制 `novel.json` 到 `revisions/novel_backup_{timestamp}.json`
  - 实现 `_cleanup_old_backups()` 保留最近 20 个

- [x] 3.2 新增变更日志相关方法（占位）
  - `save_change_log(novel_id, entry_dict) -> Path`
  - `list_change_logs(novel_id, limit) -> list[dict]`
  - `load_change_log(novel_id, change_id) -> dict | None`
  - （P0 仅实现接口，P1 完善逻辑）

**验收标准**:
```python
fm = FileManager("workspace")
backup_path = fm.save_backup("novel_123")
assert backup_path.exists()
assert "novel_backup_" in backup_path.name
```

**输出文件**:
- `src/novel/storage/file_manager.py` (修改)
- `tests/novel/storage/test_file_manager_backup.py` (新增)

---

### 4. 意图解析器（简化版）
**优先级**: P0-High
**预计工时**: 6h
**依赖**: 任务 1, 2

**子任务**:
- [x] 4.1 创建 `IntentParser` 类
  - `parse()` 方法骨架
  - `_build_parse_prompt()` 生成 LLM prompt
  - `_postprocess()` 后处理（字段推断、验证）

- [x] 4.2 实现 Prompt 模板
  - 系统提示词（要求输出 JSON）
  - 用户提示词（包含小说上下文）

- [x] 4.3 LLM 调用 + JSON 解析
  - 调用 `create_llm_client().chat(..., json_mode=True)`
  - 稳健的 JSON 提取（`_extract_json_obj()`）
  - 重试机制（最多 3 次）

- [x] 4.4 单元测试
  - Mock LLM 返回预定义 JSON
  - 测试各种指令类型（add/update/delete）
  - 测试错误处理（LLM 返回无效 JSON）

**验收标准**:
```python
parser = IntentParser(mock_llm)
novel_context = {"genre": "玄幻", "characters": [...]}

change = parser.parse("添加角色李明", novel_context)
assert change["change_type"] == "add"
assert change["entity_type"] == "character"
assert change["data"]["name"] == "李明"
```

**输出文件**:
- `src/novel/services/__init__.py` (新增)
- `src/novel/services/intent_parser.py` (新增)
- `tests/novel/services/test_intent_parser.py` (新增)

---

### 5. 核心编辑服务（简化版）
**优先级**: P0-Critical
**预计工时**: 8h
**依赖**: 任务 1-4

**子任务**:
- [x] 5.1 创建 `NovelEditService` 类
  - 初始化各子模块（`IntentParser`, `CharacterEditor`, ...）
  - `edit()` 方法主流程（不含影响分析）
  - 乐观锁检查（基于 `updated_at`）

- [x] 5.2 实现 `edit()` 核心流程
  - 加载项目 + 锁检查
  - 调用 `IntentParser.parse()`（如果是自然语言）
  - 推断 `effective_from_chapter`
  - 调用对应编辑器 `apply()`
  - Pydantic 验证
  - 备份 + 保存

- [x] 5.3 实现 `_infer_effective_chapter()`
  - 默认为 `current_chapter + 1`

- [x] 5.4 单元测试
  - Mock 所有依赖（FileManager, IntentParser, Editors）
  - 测试完整流程（add/update/delete）
  - 测试错误路径（验证失败、并发冲突）

**验收标准**:
```python
service = NovelEditService()
result = service.edit(
    project_path="workspace/novels/novel_123",
    instruction="添加角色李明",
    dry_run=False,
)
assert result.status == "success"
assert result.change_type == "add"
```

**输出文件**:
- `src/novel/services/edit_service.py` (新增)
- `tests/novel/services/test_edit_service.py` (新增)

---

### 6. Web UI 集成（最小化）
**优先级**: P0-High
**预计工时**: 4h
**依赖**: 任务 5

**子任务**:
- [x] 6.1 重构 `_novel_setting_ai_modify()`
  - 调用 `NovelEditService.edit()`
  - 格式化结果为 Markdown
  - 重新加载表单（复用现有函数）

- [x] 6.2 保留旧版表单编辑（暂不重构）
  - `_novel_setting_save_form()` 暂时保持原样
  - 后续 P1 再重构为调用服务层

- [ ] 6.3 UI 测试
  - 手动测试 AI 编辑框功能
  - 验证错误提示友好性

**验收标准**:
- 在 Web UI 输入"添加角色李明"，能成功添加并刷新表单
- 输入无效指令时显示友好错误提示

**输出文件**:
- `web.py` (修改)

---

### 7. 集成测试（P0）
**优先级**: P0-High
**预计工时**: 3h
**依赖**: 任务 1-6

**子任务**:
- [x] 7.1 端到端测试：创建项目 + 添加角色
  - 使用真实 `NovelEditService.edit()` + 真实 FileManager
  - 验证 `novel.json` 正确更新、备份创建、变更日志记录

- [x] 7.2 端到端测试：修改大纲
  - 修改章节 title/goal + 新增章节大纲
  - 验证 `outline.chapters` 更新 + 排序

- [x] 7.3 端到端测试：删除角色（软删除）
  - 验证角色 `status` 变为 `retired`/`deceased`
  - 验证 `deprecated_at_chapter` 设置正确

**验收标准**:
```python
def test_p0_integration(tmp_path):
    # 1. 创建项目
    pipe = NovelPipeline(workspace=str(tmp_path))
    result = pipe.create_novel(genre="玄幻", theme="修炼", target_words=50000)

    # 2. 添加角色
    service = NovelEditService(workspace=str(tmp_path))
    edit_result = service.edit(
        project_path=result["project_path"],
        instruction="添加角色柳青鸾",
    )

    # 3. 验证
    novel_data = service.file_manager.load_novel(result["novel_id"])
    assert any(c["name"] == "柳青鸾" for c in novel_data["characters"])
```

**输出文件**:
- `tests/novel/integration/test_edit_flow_p0.py` (新增)

---

## P1: 增强功能任务

### 8. 影响分析器
**优先级**: P1-High
**预计工时**: 6h
**依赖**: 任务 5

**子任务**:
- [ ] 8.1 创建 `ImpactAnalyzer` 类
  - `analyze()` 主方法
  - `_analyze_character_impact()` 角色影响分析
  - `_analyze_outline_impact()` 大纲影响分析
  - `_find_character_appearances()` 查找角色出现章节

- [ ] 8.2 实现影响检测逻辑
  - 检查 `involved_characters` 字段
  - （可选）LLM 分析章节文本（成本较高）

- [ ] 8.3 冲突检测
  - 角色删除 → 检查后续章节是否使用
  - 世界观修改 → 检查是否与章节内容矛盾

- [ ] 8.4 单元测试
  - Mock 小说数据
  - 测试各种影响场景

**验收标准**:
```python
analyzer = ImpactAnalyzer()
novel_data = {
    "current_chapter": 10,
    "outline": {"chapters": [
        {"chapter_number": 5, "involved_characters": ["char_1"]},
    ]},
}
change = {"change_type": "delete", "entity_id": "char_1", "effective_from_chapter": 1}

impact = analyzer.analyze(novel_data, change)
assert 5 in impact.affected_chapters
assert impact.severity == "high"
```

**输出文件**:
- `src/novel/services/impact_analyzer.py` (新增)
- `tests/novel/services/test_impact_analyzer.py` (新增)

---

### 9. 变更历史管理
**优先级**: P1-Medium
**预计工时**: 4h
**依赖**: 任务 5

**子任务**:
- [ ] 9.1 定义 `ChangeLogEntry` Pydantic 模型
  - `change_id`, `timestamp`, `change_type`, ...
  - 包含 `old_value`, `new_value` JSON 快照

- [ ] 9.2 实现 `ChangeLogManager` 类
  - `record()` 记录变更
  - `list_changes()` 查询历史
  - `get()` 获取单条记录

- [ ] 9.3 集成到 `NovelEditService.edit()`
  - 每次成功修改后调用 `record()`

- [ ] 9.4 单元测试
  - 测试记录和查询

**验收标准**:
```python
manager = ChangeLogManager("workspace")
entry = manager.record(
    novel_id="novel_123",
    change={...},
    old_value={...},
    new_value={...},
)
assert entry.change_id is not None

history = manager.list_changes("novel_123", limit=10)
assert len(history) > 0
```

**输出文件**:
- `src/novel/models/changelog.py` (新增)
- `src/novel/services/changelog_manager.py` (新增)
- `tests/novel/services/test_changelog_manager.py` (新增)

---

### 10. MCP 工具暴露
**优先级**: P1-High
**预计工时**: 3h
**依赖**: 任务 5, 8, 9

**子任务**:
- [x] 10.1 新增 `novel_edit_setting` MCP 工具
  - 参数：`project_path`, `instruction`, `effective_from_chapter`, `dry_run`
  - 调用 `NovelEditService.edit()`
  - 返回 `EditResult` 序列化

- [x] 10.2 新增 `novel_get_change_history` MCP 工具
  - 调用 `NovelEditService.get_history()`

- [x] 10.3 新增 `novel_analyze_change_impact` MCP 工具（dry_run 模式）
  - 调用 `edit(..., dry_run=True)`
  - ImpactAnalyzer 集成到 NovelEditService.edit()，结果放在 EditResult.impact_report
  - 编辑器层 (add/update/delete × character/outline/world_setting) 映射到 ImpactAnalyzer 的 change_type/entity_type
  - ImpactAnalyzer 失败不阻塞 edit（warning + impact_report=None）

- [x] 10.4 MCP 测试
  - 使用 `fastmcp` 测试框架
  - 验证工具可正常调用
  - 新增 tests/test_mcp_novel_edit.py（19 测试）+ 补充 tests/novel/services/test_edit_service.py::TestImpactReportIntegration（8 测试）

**验收标准**:
```python
# Claude Desktop 调用 MCP 工具
result = novel_edit_setting(
    project_path="workspace/novels/novel_123",
    instruction="添加角色柳青鸾",
)
assert result["status"] == "success"
```

**输出文件**:
- `mcp_server.py` (修改)

---

### 11. CLI 支持
**优先级**: P1-Medium
**预计工时**: 2h
**依赖**: 任务 5, 9

**子任务**:
- [ ] 11.1 新增 `novel edit` 子命令
  - `python main.py novel edit <project> --instruction "..." --dry-run`
  - 调用 `NovelEditService.edit()`

- [ ] 11.2 新增 `novel history` 子命令
  - `python main.py novel history <project> --limit 20`
  - 格式化输出变更历史

- [ ] 11.3 CLI 测试
  - 手动测试各命令

**验收标准**:
```bash
python main.py novel edit workspace/novels/novel_123 --instruction "添加角色李明"
# 输出: ✅ 角色已添加 (change_id: abc123)

python main.py novel history workspace/novels/novel_123
# 输出: 变更历史列表
```

**输出文件**:
- `main.py` (修改)

---

### 12. Web UI 完整集成
**优先级**: P1-Medium
**预计工时**: 4h
**依赖**: 任务 8

**子任务**:
- [ ] 12.1 重构 `_novel_setting_save_form()`
  - 收集表单数据为 `structured_change`
  - 调用 `NovelEditService.edit()`

- [ ] 12.2 新增影响分析 UI
  - "分析影响" 按钮
  - 显示 `ImpactReport`（受影响章节、冲突列表）

- [ ] 12.3 UI 测试
  - 验证表单编辑和 AI 编辑都使用服务层

**验收标准**:
- Web UI 表单编辑和 AI 编辑都不直接操作 JSON
- 影响分析结果正确显示

**输出文件**:
- `web.py` (修改)

---

### 13. 集成测试（P1）
**优先级**: P1-High
**预计工时**: 2h
**依赖**: 任务 8-12

**子任务**:
- [ ] 13.1 测试影响分析流程
  - 修改角色 → 检测受影响章节

- [ ] 13.2 测试变更历史查询
  - 多次修改 → 查询历史 → 验证顺序

- [ ] 13.3 测试 MCP 工具
  - 通过 MCP 调用编辑 → 验证成功

**验收标准**:
```python
def test_p1_integration_impact_analysis(tmp_path):
    # 1. 创建项目并生成几章
    # 2. 添加角色
    # 3. 删除角色
    # 4. 验证影响分析报告正确
```

**输出文件**:
- `tests/novel/integration/test_edit_flow_p1.py` (新增)

---

## P2: 高级功能任务

### 14. 回滚功能
**优先级**: P2-Medium
**预计工时**: 4h
**依赖**: 任务 9

**子任务**:
- [ ] 14.1 实现 `NovelEditService.rollback()`
  - 加载变更日志
  - 反向应用变更（add → delete, update → 恢复旧值）
  - 记录回滚本身为新变更

- [ ] 14.2 依赖检查
  - 回滚删除 → 检查后续是否有依赖该角色的变更

- [ ] 14.3 单元测试
  - 测试各种回滚场景

**验收标准**:
```python
# 1. 添加角色
result1 = service.edit(..., instruction="添加角色李明")

# 2. 回滚
result2 = service.rollback(project_path, result1.change_id)

# 3. 验证角色已移除
novel_data = service.file_manager.load_novel(...)
assert not any(c["name"] == "李明" for c in novel_data["characters"])
```

**输出文件**:
- `src/novel/services/edit_service.py` (修改)
- `tests/novel/services/test_rollback.py` (新增)

---

### 15. 批量操作
**优先级**: P2-Low
**预计工时**: 3h
**依赖**: 任务 5

**子任务**:
- [ ] 15.1 实现 `NovelEditService.batch_edit()`
  - 接受 `changes: list[dict]`
  - 共享备份和验证
  - 返回 `list[EditResult]`

- [ ] 15.2 支持范围操作
  - "第10-15章mood改为小爽" → 生成 6 个 change

- [ ] 15.3 单元测试
  - 测试批量修改成功
  - 测试部分失败场景

**验收标准**:
```python
changes = [
    {"change_type": "update", "entity_type": "outline", "data": {...}},
    {"change_type": "update", "entity_type": "outline", "data": {...}},
]
results = service.batch_edit(project_path, changes)
assert len(results) == 2
assert all(r.status == "success" for r in results)
```

**输出文件**:
- `src/novel/services/edit_service.py` (修改)
- `tests/novel/services/test_batch_edit.py` (新增)

---

### 16. 并发控制增强
**优先级**: P2-Low
**预计工时**: 3h
**依赖**: 任务 5

**子任务**:
- [ ] 16.1 实现文件锁（Unix）
  - `FileManager._acquire_lock()`
  - `FileManager._release_lock()`
  - 使用 `fcntl.flock()`

- [ ] 16.2 友好错误提示
  - `ConcurrentModificationError` 提示用户刷新

- [ ] 16.3 测试
  - 模拟并发修改（多进程）

**验收标准**:
```python
# 进程 1
service1.edit(...)  # 获得锁

# 进程 2（阻塞或报错）
service2.edit(...)  # ConcurrentModificationError
```

**输出文件**:
- `src/novel/storage/file_manager.py` (修改)
- `tests/novel/storage/test_concurrent_edit.py` (新增)

---

### 17. 性能优化
**优先级**: P2-Low
**预计工时**: 2h
**依赖**: 任务 8

**子任务**:
- [ ] 17.1 IntentParser 缓存
  - 使用 `@lru_cache` 缓存 LLM 解析结果

- [ ] 17.2 ImpactAnalyzer 优化
  - 索引 `involved_characters`（避免全量遍历）

- [ ] 17.3 性能测试
  - 压测 100 次连续编辑
  - 验证响应时间 < 5s（95th percentile）

**验收标准**:
```python
# 100 次编辑的平均时间 < 3s
import time
start = time.time()
for i in range(100):
    service.edit(..., instruction=f"修改角色{i}")
elapsed = time.time() - start
assert elapsed / 100 < 3
```

**输出文件**:
- `src/novel/services/intent_parser.py` (修改)
- `src/novel/services/impact_analyzer.py` (修改)

---

### 18. 版本查询辅助函数
**优先级**: P2-Medium
**预计工时**: 2h
**依赖**: 任务 1

**子任务**:
- [ ] 18.1 实现 `get_setting_at_chapter()`
  - 查询指定章节生效的实体版本
  - 支持角色、世界观等

- [ ] 18.2 集成到 Agent
  - `PlotPlanner` / `Writer` 调用此函数获取正确版本

- [ ] 18.3 单元测试
  - 测试多版本查询

**验收标准**:
```python
from src.novel.utils.setting_version import get_setting_at_chapter

chars = [
    {"character_id": "c1", "name": "李明v1", "effective_from_chapter": 1, "deprecated_at_chapter": 10},
    {"character_id": "c1", "name": "李明v2", "effective_from_chapter": 10},
]

char_v1 = get_setting_at_chapter(chars, "c1", chapter_num=5)
assert char_v1["name"] == "李明v1"

char_v2 = get_setting_at_chapter(chars, "c1", chapter_num=15)
assert char_v2["name"] == "李明v2"
```

**输出文件**:
- `src/novel/utils/__init__.py` (新增)
- `src/novel/utils/setting_version.py` (新增)
- `tests/novel/utils/test_setting_version.py` (新增)

---

### 19. 迁移脚本
**优先级**: P2-Low
**预计工时**: 1h
**依赖**: 任务 1

**子任务**:
- [ ] 19.1 编写 `migrate_novel_v1_to_v2.py`
  - 遍历 `workspace/novels/`
  - 为所有实体添加版本字段（默认值）
  - 备份旧版本

- [ ] 19.2 测试
  - 准备 v1 测试项目
  - 运行迁移
  - 验证迁移后能正常加载

**验收标准**:
```bash
python scripts/migrate_novel_v1_to_v2.py
# 输出: ✅ Migrated 5 projects

python -c "from src.novel.storage.file_manager import FileManager; ..."
# 无报错
```

**输出文件**:
- `scripts/migrate_novel_v1_to_v2.py` (新增)

---

### 20. 文档编写
**优先级**: P2-Medium
**预计工时**: 4h
**依赖**: 任务 1-19

**子任务**:
- [ ] 20.1 用户文档
  - 自然语言编辑示例库（`docs/edit_examples.md`）
  - MCP 工具使用指南（`docs/mcp_edit_guide.md`）
  - 变更历史查询教程（`docs/changelog_guide.md`）

- [ ] 20.2 开发文档
  - 架构决策记录（`docs/adr/0001-versioned-settings.md`）
  - 实体编辑器扩展指南（`docs/dev/extend_editor.md`）

- [ ] 20.3 更新 CLAUDE.md
  - 添加编辑系统说明
  - 更新命令示例

**输出文件**:
- `docs/edit_examples.md` (新增)
- `docs/mcp_edit_guide.md` (新增)
- `docs/changelog_guide.md` (新增)
- `docs/adr/0001-versioned-settings.md` (新增)
- `docs/dev/extend_editor.md` (新增)
- `CLAUDE.md` (修改)

---

## 任务依赖关系图

```mermaid
graph TD
    T1[1. 数据模型扩展] --> T2[2. 基础编辑器]
    T1 --> T3[3. 文件管理器扩展]
    T1 --> T4[4. 意图解析器]

    T2 --> T5[5. 核心编辑服务]
    T3 --> T5
    T4 --> T5

    T5 --> T6[6. Web UI 集成]
    T5 --> T7[7. 集成测试 P0]
    T5 --> T8[8. 影响分析器]
    T5 --> T9[9. 变更历史管理]

    T8 --> T10[10. MCP 工具]
    T9 --> T10
    T5 --> T10

    T9 --> T11[11. CLI 支持]
    T8 --> T12[12. Web UI 完整集成]

    T10 --> T13[13. 集成测试 P1]
    T12 --> T13

    T9 --> T14[14. 回滚功能]
    T5 --> T15[15. 批量操作]
    T5 --> T16[16. 并发控制]
    T8 --> T17[17. 性能优化]
    T1 --> T18[18. 版本查询辅助]
    T1 --> T19[19. 迁移脚本]

    T14 --> T20[20. 文档编写]
    T15 --> T20
    T16 --> T20
    T17 --> T20
    T18 --> T20
```

---

## 质量门禁

### 每批次完成标准

#### P0 批次完成标准：
- [ ] 所有 P0 任务测试通过（单元测试 + 集成测试）
- [ ] Web UI AI 编辑功能可用（手动测试）
- [ ] 向后兼容性验证（老项目能加载）
- [ ] 代码审查通过（无 CRITICAL/HIGH 级别问题）

#### P1 批次完成标准：
- [ ] 所有 P1 任务测试通过
- [ ] MCP 工具可用（手动测试 Claude Desktop）
- [ ] 影响分析准确率 > 90%（手动验证 20 个案例）
- [ ] 文档完善（用户文档 + 开发文档）

#### P2 批次完成标准：
- [ ] 所有 P2 任务测试通过
- [ ] 性能测试达标（响应时间 < 5s）
- [ ] 并发测试通过（无数据损坏）
- [ ] 迁移脚本验证（迁移 10 个真实项目）

---

## 风险与缓解

### 风险 1：LLM 解析不稳定
**缓解措施**：
- 任务 4.4 实现重试机制（最多 3 次）
- 提供规则解析器兜底（任务 4）
- 用户确认机制（dry_run 模式预览）

### 风险 2：向后兼容性破坏
**缓解措施**：
- 任务 1.1 确保所有新字段有默认值
- 任务 19 提供迁移脚本
- 任务 7 测试老项目加载

### 风险 3：并发编辑冲突
**缓解措施**：
- 任务 5.1 实现乐观锁
- 任务 16 实现文件锁（可选）
- 友好错误提示

### 风险 4：性能下降
**缓解措施**：
- 任务 17 性能优化
- 批量操作优化（任务 15）
- LLM 调用缓存（任务 17.1）

---

## 进度跟踪

### P0 批次（预计 1.5 周）
| 任务 | 负责人 | 预计工时 | 实际工时 | 状态 |
|------|--------|----------|----------|------|
| 1. 数据模型扩展 | Claude | 2h | 1h | ✅ Done |
| 2. 基础编辑器 | Claude | 4h | 2h | ✅ Done |
| 3. 文件管理器扩展 | Claude | 2h | 1h | ✅ Done |
| 4. 意图解析器 | Claude | 6h | 3h | ✅ Done |
| 5. 核心编辑服务 | Claude | 8h | 3h | ✅ Done |
| 6. Web UI 集成 | Claude | 4h | 2h | ✅ Done (6.3 UI手动测试除外) |
| 7. 集成测试 P0 | Claude | 3h | 1h | ✅ Done |

**总计**: 29h（约 4 个工作日）

### P1 批次（预计 1 周）
| 任务 | 负责人 | 预计工时 | 实际工时 | 状态 |
|------|--------|----------|----------|------|
| 8. 影响分析器 | TBD | 6h | - | ⏳ Pending |
| 9. 变更历史管理 | TBD | 4h | - | ⏳ Pending |
| 10. MCP 工具 | TBD | 3h | - | ⏳ Pending |
| 11. CLI 支持 | TBD | 2h | - | ⏳ Pending |
| 12. Web UI 完整 | TBD | 4h | - | ⏳ Pending |
| 13. 集成测试 P1 | TBD | 2h | - | ⏳ Pending |

**总计**: 21h（约 3 个工作日）

### P2 批次（预计 1 周）
| 任务 | 负责人 | 预计工时 | 实际工时 | 状态 |
|------|--------|----------|----------|------|
| 14. 回滚功能 | TBD | 4h | - | ⏳ Pending |
| 15. 批量操作 | TBD | 3h | - | ⏳ Pending |
| 16. 并发控制 | TBD | 3h | - | ⏳ Pending |
| 17. 性能优化 | TBD | 2h | - | ⏳ Pending |
| 18. 版本查询 | TBD | 2h | - | ⏳ Pending |
| 19. 迁移脚本 | TBD | 1h | - | ⏳ Pending |
| 20. 文档编写 | TBD | 4h | - | ⏳ Pending |

**总计**: 19h（约 2.5 个工作日）

**项目总工时**: 69h（约 9 个工作日，按 8h/天计算）

---

## 实施建议

### 第一周：P0 批次
**目标**: 实现核心编辑流程，Web UI 可用

**日程**:
- Day 1: 任务 1-3（基础设施）
- Day 2: 任务 4（意图解析器）
- Day 3-4: 任务 5（核心服务）
- Day 5: 任务 6-7（Web UI + 测试）

### 第二周：P1 批次
**目标**: MCP 集成、影响分析、变更历史

**日程**:
- Day 1-2: 任务 8-9（影响分析 + 变更历史）
- Day 3: 任务 10-11（MCP + CLI）
- Day 4: 任务 12（Web UI 完整集成）
- Day 5: 任务 13（集成测试 + bug 修复）

### 第三周：P2 批次（可选）
**目标**: 高级功能、性能优化、文档

**日程**:
- Day 1: 任务 14-15（回滚 + 批量）
- Day 2: 任务 16-17（并发 + 性能）
- Day 3: 任务 18-19（版本查询 + 迁移）
- Day 4-5: 任务 20（文档 + 发布准备）

---

## 验收清单

### 功能验收
- [ ] 自然语言添加角色（"添加角色李明"）
- [ ] 自然语言修改大纲（"第10章改为大爽"）
- [ ] 删除角色（软删除）
- [ ] 影响分析（检测矛盾）
- [ ] MCP 工具调用（Claude Desktop）
- [ ] CLI 命令（`novel edit`, `novel history`）
- [ ] 变更历史查询
- [ ] 回滚变更（P2）
- [ ] 批量操作（P2）

### 质量验收
- [ ] 单元测试覆盖率 > 80%
- [ ] 集成测试通过
- [ ] 向后兼容性验证（老项目加载）
- [ ] 性能测试达标（响应时间 < 5s）
- [ ] 并发测试通过（乐观锁）
- [ ] 代码审查通过（无高危问题）

### 文档验收
- [ ] 用户文档完整（编辑示例、MCP 指南）
- [ ] 开发文档完整（架构设计、扩展指南）
- [ ] CLAUDE.md 更新
- [ ] README 更新（新增命令示例）

---

**任务清单版本**: v1.0
**创建日期**: 2026-03-24
**预计完成日期**: 2026-04-14（3-4 周）
**负责人**: TBD
