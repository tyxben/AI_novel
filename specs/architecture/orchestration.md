# 编排规范 (Orchestration Specification)

> 版本: v1.0 | 日期: 2026-03-24
> 状态: 待实施

## 1. 问题陈述

当前小说系统的编排存在三个结构性问题：

### 1.1 Graph 声明 ≠ 实际执行

| 组件 | 声明 | 实际 |
|------|------|------|
| Init Graph | `build_init_graph()` (graph.py:102) | **从未被调用**。create_novel() 手工逐节点调用 (pipeline.py:235) |
| Chapter Graph | `build_chapter_graph()` (graph.py:137) | 被使用。generate_chapters() 中调用 (pipeline.py:513) |
| Init 注释 | "Run init graph nodes" (pipeline.py:235) | 注释描述与代码行为不一致 |

### 1.2 LangGraph / Fallback 语义不一致

| 模式 | consistency_checker + style_keeper | 代码位置 |
|------|-----------------------------------|----------|
| LangGraph | 串行 (checker → keeper) | graph.py:147-167 |
| Fallback | 并行 (ThreadPoolExecutor) | graph.py:260-284 |

同一套系统在"装没装 LangGraph"下行为语义不同。如果 consistency_checker 的输出影响 style_keeper 的判断，两种模式结果不同。

### 1.3 风格字段三重表达

| 位置 | 字段 | 状态 |
|------|------|------|
| NovelState (state.py:30) | `style_name` = "webnovel.shuangwen" | 唯一被正确赋值 |
| Novel 模型 (novel.py:126-129) | `style_category` + `style_subcategory` | **从未被赋值** |
| StyleKeeper (style_keeper.py:207-210) | 读 `style_category` / `style_subcategory` | **读到空值，静默跳过检查** |
| 传播重写 (pipeline.py:1467) | 读 `style_subcategory` | 拿到子类名而非完整名 |

**结果**: StyleKeeper agent 实际上一直在空转，风格检查完全失效。

---

## 2. 编排模型选型: Pipeline-first

### 决策

**选择 Pipeline-first，Graph 退化为可选内部机制。**

### 理由

1. `build_init_graph()` 已经是死代码——实际从未被执行
2. pipeline.py 中有大量非 graph 逻辑：进度回调、断点续传、章节落盘、质量检查暂停
3. 这些逻辑不可能干净地放入 graph 节点
4. 强推 graph-first 会导致更多 workaround，加剧架构漂移

### 新规则

```
Pipeline 是官方入口，拥有流程控制权。
Graph 是 Pipeline 内部可选的执行引擎。
Agent 是无状态的业务函数，不感知编排。
```

---

## 3. 编排规则

### 规则 1: 单一入口

每个产品能力只有一个入口函数：

| 能力 | 入口 | 文件 |
|------|------|------|
| 创建小说 | `NovelPipeline.create_novel()` | pipeline.py |
| 生成章节 | `NovelPipeline.generate_chapters()` | pipeline.py |
| 应用反馈 | `NovelPipeline.apply_feedback()` | pipeline.py |
| 编辑设定 | `NovelEditService.edit()` | edit_service.py |
| 查询历史 | `NovelEditService.get_history()` | edit_service.py |

Web UI / MCP / CLI 只能调用上述入口，不能绕过。

### 规则 2: Graph 的使用边界

Graph **只用于**章节生成循环中的 agent 编排：

```
plot_planner → writer → [checkers] → quality_reviewer → (重写循环)
```

Graph **不用于**：
- 初始化流程（create_novel）— 用 pipeline 直接调度
- 反馈处理（apply_feedback）— 用 pipeline 直接调度
- 设定编辑 — 用 edit_service 调度

### 规则 3: Fallback 必须与 Graph 语义一致

当 LangGraph 不可用时，fallback 的执行语义**必须与 graph 定义一致**。

当前 graph 定义 checker 为串行：
```python
graph.add_edge("consistency_checker", "style_keeper")
```

则 fallback 也必须串行：
```python
# 修改前 (graph.py:260-284): ThreadPoolExecutor 并行 ← 语义不一致
# 修改后: 串行调用
result = self.nodes["consistency_checker"](state)
state = _merge_state(state, result)
result = self.nodes["style_keeper"](state)
state = _merge_state(state, result)
```

如果未来希望并行执行 checker，**必须同时修改 graph 定义和 fallback**。

### 规则 4: 删除死代码

`build_init_graph()` 必须删除：
- 函数定义 (graph.py:102-129)
- 相关测试
- pipeline.py 中的 import
- pipeline.py:235 处的误导注释

保留的组件：
- `build_chapter_graph()` — 仍在使用
- `_get_node_functions()` — 被 create_novel() 的手工调用使用
- `_merge_state()` — 通用 merge 工具

---

## 4. 风格字段统一

### 规则: 只保留 `style_name`

**唯一表达**: `style_name: str` — 格式为 `"{category}.{subcategory}"`，如 `"webnovel.shuangwen"`

**删除**:
- Novel 模型中的 `style_category` 和 `style_subcategory` 字段
- 改为单一 `style_name: str` 字段

**派生** (需要时在运行时计算):
```python
def split_style(style_name: str) -> tuple[str, str]:
    """从 style_name 派生 category 和 subcategory。"""
    parts = style_name.split(".", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], ""
```

### 受影响的代码

| 文件 | 修改 |
|------|------|
| `src/novel/models/novel.py:126-129` | 删除 style_category/style_subcategory，加 style_name |
| `src/novel/agents/state.py:30` | 保持 style_name（已正确） |
| `src/novel/agents/style_keeper.py:207-210` | 改为读 `state["style_name"]` |
| `src/novel/pipeline.py:1467` | 改为读 `novel_data.get("style_name", "webnovel.shuangwen")` |
| `src/novel/pipeline.py:328` | 保持 style_name（已正确） |

---

## 5. 编排流程定义

### 5.1 create_novel() 流程

```
1. 初始化 state (genre, theme, target_words, style_name, ...)
2. 调用 novel_director 节点 → 生成大纲
3. 合并 state
4. 调用 world_builder 节点 → 生成世界观
5. 合并 state
6. 调用 character_designer 节点 → 生成角色
7. 合并 state
8. 保存 novel.json (设定态)
9. 保存 checkpoint.json (运行态初始值)
10. 返回结果
```

**不使用 graph**。每步之间插入进度回调。

### 5.2 generate_chapters() 流程

```
1. 加载 checkpoint.json
2. 从 novel.json 刷新设定字段 ← 新增步骤(canonical-state.md 规则 3.1)
3. 如需扩展大纲 → 调用 novel_director.generate_volume_outline()
4. 循环每章:
   a. 构建 chapter graph (或 fallback runner)
   b. 执行: plot_planner → writer → checkers → quality_reviewer
   c. 保存章节文件 (chapter_NNN.txt + chapter_NNN.json)
   d. 更新 checkpoint
   e. 同步进度到 novel.json
5. 完成
```

### 5.3 apply_feedback() 流程

```
1. 加载 checkpoint.json
2. 从 novel.json 刷新设定字段 ← 新增步骤
3. 调用 FeedbackAnalyzer → 分析反馈
4. 调用 Writer.rewrite_chapter() → 重写
5. 传播调整后续章节
6. 保存修订版本
7. 更新 checkpoint 和 novel.json
```

### 5.4 edit() 流程

```
1. 加载 novel.json
2. 解析指令 (IntentParser / 结构化输入)
3. 推断 effective_from_chapter
4. 备份 novel.json
5. 调用编辑器 apply()
6. 保存 novel.json
7. 记录变更日志
8. 返回 EditResult
```

**不操作 checkpoint**。下次 generate 启动时自动同步。

---

## 6. 视频侧编排现状 (备注)

视频生成当前有三套入口并存：

| 入口 | 文件 | 用途 |
|------|------|------|
| 经典流水线 | src/pipeline.py | 小说文本 → 视频 |
| Agent 模式 | src/agent_pipeline.py | LangGraph 编排 |
| 导演模式 | src/director_pipeline.py | 灵感 → 视频 |

视频侧的收口不在本规范范围内，但原则相同：
- 选一个作为官方入口
- 其他作为内部实现或废弃
- 不允许三套并存且互不通信

---

## 7. 实施优先级

| 优先级 | 任务 | 风险 |
|--------|------|------|
| P0 | generate_chapters 启动时从 novel.json 刷新设定 | 用户可见 bug |
| P0 | apply_feedback 启动时从 novel.json 刷新设定 | 用户可见 bug |
| P1 | StyleKeeper 改为读 style_name | 功能静默失效 |
| P1 | 传播重写读 style_name | 风格错误 |
| P1 | Novel 模型统一为 style_name | 数据模型不一致 |
| P2 | 删除 build_init_graph() + 修正注释 | 架构误导 |
| P2 | Fallback checker 串行化 | 语义不一致 |
| P2 | web.py 表单编辑改走 edit_service | 违反分层 |

---

## 8. 验收标准

### 编排一致性
- [ ] 没有声明了但未使用的 graph
- [ ] LangGraph 模式和 fallback 模式输出一致（给定相同输入）
- [ ] 每个产品能力只有一个入口函数

### 风格统一
- [ ] 代码中没有 `style_category` 或 `style_subcategory` 的读写
- [ ] StyleKeeper 使用 `style_name` 且功能正常（不再空转）
- [ ] 传播重写使用正确的风格名

### 状态一致
- [ ] NovelState 中声明的字段覆盖所有 agent 读取的字段
- [ ] 没有 agent 通过 dict key 偷偷传递未声明字段
