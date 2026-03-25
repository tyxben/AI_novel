# 单一真源规范 (Canonical State Specification)

> 版本: v1.0 | 日期: 2026-03-24
> 状态: 待实施

## 1. 问题陈述

当前小说系统存在**双源状态**问题：

| 数据存储 | 写入方 | 读取方 | 内容 |
|----------|--------|--------|------|
| `checkpoint.json` | pipeline.py | generate_chapters, apply_feedback | outline, characters, world_setting + 运行时状态 |
| `novel.json` | edit_service.py, web.py | Web UI, MCP, CLI | outline, characters, world_setting + 元数据 |

**核心缺陷**: 用户通过 edit_service 修改角色/大纲/世界观后，只有 novel.json 被更新。后续调用 generate_chapters 仍从 checkpoint.json 加载旧数据，**编辑结果对生成链路不可见**。

### 已验证的问题位置

```
edit_service.py:83   → self.file_manager.load_novel(novel_id)     # 读 novel.json
edit_service.py:150  → self.file_manager.save_novel(novel_id, ...) # 写 novel.json
pipeline.py:388      → self._load_checkpoint(novel_id)             # 读 checkpoint.json
pipeline.py:902      → self._load_checkpoint(novel_id)             # 读 checkpoint.json
```

checkpoint.json 和 novel.json 中 `outline`、`characters`、`world_setting` 三个字段完全重复存储，但无同步机制。

---

## 2. 真源定义

### 规则 1: novel.json 是设定态真源

| 数据类别 | 真源 | 说明 |
|----------|------|------|
| outline (大纲) | novel.json | 包括 acts, volumes, chapters |
| characters (角色) | novel.json | 包括版本字段 effective_from_chapter |
| world_setting (世界观) | novel.json | |
| main_storyline (主线) | novel.json | |
| style_name (风格) | novel.json | |
| 元数据 (title, genre, theme, status) | novel.json | |

**任何修改设定的操作，目标都是 novel.json。**

### 规则 2: checkpoint.json 是运行态真源

| 数据类别 | 真源 | 说明 |
|----------|------|------|
| current_chapter (进度) | checkpoint.json | 当前生成到第几章 |
| retry_counts | checkpoint.json | 各章重试计数 |
| completed_nodes | checkpoint.json | 当前运行中已完成的节点 |
| decisions | checkpoint.json | agent 决策记录 |
| chapters (已写章节摘要) | checkpoint.json | 用于上下文传递 |
| should_continue | checkpoint.json | 生成是否继续 |

**运行时状态只存 checkpoint，不存 novel.json。**

### 规则 3: 设定字段在 checkpoint 中是缓存，不是真源

checkpoint 中的 outline / characters / world_setting 是从 novel.json **复制**过来的快照。
当两者不一致时，**以 novel.json 为准**。

---

## 3. 同步协议

### 3.1 生成启动时: novel.json → checkpoint (刷新设定)

`generate_chapters()` 启动时，必须从 novel.json 刷新设定字段到 state：

```python
# pipeline.py: generate_chapters() 启动时
state = self._load_checkpoint(novel_id)
novel_data = self.file_manager.load_novel(novel_id)

# 用 novel.json 中的设定覆盖 checkpoint 中的缓存
state["outline"] = novel_data.get("outline", state.get("outline"))
state["characters"] = novel_data.get("characters", state.get("characters"))
state["world_setting"] = novel_data.get("world_setting", state.get("world_setting"))
state["main_storyline"] = novel_data.get("outline", {}).get("main_storyline", state.get("main_storyline"))
state["style_name"] = novel_data.get("style_name", state.get("style_name"))
```

同理，`apply_feedback()` 启动时也必须执行相同刷新。

### 3.2 章节生成后: checkpoint → novel.json (同步进度)

每章生成完成后，同步进度和章节摘要到 novel.json：

```python
# pipeline.py: 每章完成后
novel_data["current_chapter"] = state["current_chapter"]
novel_data["status"] = "generating"
self.file_manager.save_novel(novel_id, novel_data)
```

这部分当前代码已有（pipeline.py:492-498），保持不变。

### 3.3 编辑操作: 只改 novel.json

edit_service.edit() 的写入目标保持不变（novel.json）。
**不需要同时写 checkpoint**——下次 generate 启动时会自动刷新。

### 3.4 大纲扩展: 双写

`_extend_outline()` 属于生成过程中的大纲扩展，需要同时更新两侧：
- checkpoint 立即更新（运行态需要）
- novel.json 同步更新（保持真源一致）

这部分当前代码已有（pipeline.py:1640-1642），保持不变。

---

## 4. 数据流图

```
┌──────────────────────────────────────────────────────────────┐
│                        novel.json                            │
│  (设定态真源: outline, characters, world_setting, metadata)  │
└──────────┬──────────────────────────────────┬────────────────┘
           │ 编辑写入                         │ 生成启动时刷新
           │                                  ↓
    ┌──────┴──────┐                 ┌─────────────────┐
    │ edit_service │                 │  checkpoint.json │
    │ Web UI      │                 │  (运行态真源)    │
    │ MCP         │                 │  进度 + 设定快照  │
    │ CLI         │                 └────────┬────────┘
    └─────────────┘                          │
                                             ↓
                                    ┌─────────────────┐
                                    │ generate_chapters│
                                    │ apply_feedback   │
                                    └────────┬────────┘
                                             │ 每章完成后同步进度
                                             ↓
                                      novel.json
```

---

## 5. 迁移策略

### 存量项目兼容

对于已有项目（checkpoint 中设定可能比 novel.json 更新），迁移规则：

1. 如果 novel.json 不存在设定字段 → 从 checkpoint 补充
2. 如果两侧都有 → 以 novel.json 的 `updated_at` 时间戳判断，取更新的一方
3. 迁移后统一以 novel.json 为准

### 新项目

create_novel() 完成后：
- novel.json 包含完整设定（已有）
- checkpoint.json 包含设定快照 + 运行态初始值（已有）
- 两者天然一致，无需额外处理

---

## 6. 验收标准

- [ ] 用户在 Web UI 修改角色后，generate_chapters 能看到新角色
- [ ] 用户在 MCP 修改大纲后，generate_chapters 使用新大纲
- [ ] 生成中途中断后 resume，仍能看到之前的编辑
- [ ] 编辑操作不影响 checkpoint 中的运行时状态（retry_counts 等）
- [ ] _extend_outline 双写行为不变
