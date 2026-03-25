# 分层职责规范 (Layer Contract Specification)

> 版本: v1.0 | 日期: 2026-03-24
> 状态: 待实施

## 1. 问题陈述

当前小说系统有 agent / service / tool / storage 四层，但边界模糊：

- Agent 节点内部直接构造 LLM client（如 writer.py:96），绕过了统一配置
- Pipeline 既做流程控制又做文件 I/O，职责混杂
- FileManager 在做 CRUD 的同时也承担了部分业务判断（如章节编号推断）
- Service 层（edit_service）直接创建 LLM client（edit_service.py:231），与 agent 的 LLM 使用路径不统一

---

## 2. 四层架构定义

```
┌─────────────────────────────────────────────────┐
│              用户接口层 (Interface)              │
│         Web UI / MCP Server / CLI               │
│  职责: 参数校验、格式转换、进度展示             │
│  禁止: 业务逻辑、直接操作存储                   │
└──────────────────────┬──────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────┐
│          编排层 (Orchestration)                  │
│     Pipeline / EditService / FeedbackService    │
│  职责: 流程控制、事务边界、状态同步、失败恢复   │
│  禁止: LLM 调用、内容生成                       │
└──────────────────────┬──────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────┐
│          业务层 (Business)                       │
│        Agent / Service / Tool                   │
│  职责: 决策、内容生成、分析、检查               │
│  禁止: 文件 I/O、流程跳转                       │
└──────────────────────┬──────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────┐
│          存储层 (Storage)                        │
│              FileManager                        │
│  职责: CRUD、索引、备份                         │
│  禁止: 业务判断、LLM 调用                       │
└─────────────────────────────────────────────────┘
```

---

## 3. 各层规则

### 3.1 用户接口层 (web.py / mcp_server.py / main.py)

**可以做:**
- 接收用户输入、参数校验
- 调用编排层方法
- 格式化输出（Markdown、JSON、表格）
- 进度回调展示

**不能做:**
- ❌ 直接读写 novel.json / checkpoint.json
- ❌ 直接调用 agent 节点函数
- ❌ 包含业务判断逻辑（如"第几章该不该做一致性检查"）
- ❌ 直接构造 LLM client

**当前违规:**
- web.py 中 `_novel_setting_save_form()` 直接操作 novel.json（应改为调用 edit_service）

### 3.2 编排层 (pipeline.py / edit_service.py)

**可以做:**
- 定义执行流程（先做什么后做什么）
- 管理事务边界（备份 → 修改 → 验证 → 保存）
- 调用 agent/tool 获取结果
- 调用 storage 持久化
- 失败恢复和断点续传
- 进度回调

**不能做:**
- ❌ 直接调用 LLM（应通过 agent 或 service 间接调用）
- ❌ 包含内容生成逻辑（如拼接 prompt）
- ❌ 跨编排层互相调用（pipeline 不应调用 edit_service，反之亦然）

**当前违规:**
- pipeline.py 中有大量 prompt 拼接逻辑（如卷大纲生成 pipeline.py:1540-1600）
- edit_service.py 直接调用 `create_llm_client()` (应由 IntentParser 封装)

### 3.3 业务层

#### 3.3.1 Agent (src/novel/agents/)

**可以做:**
- 接收结构化输入（state dict 或明确参数）
- 调用 LLM 生成内容
- 返回结构化输出（state patch 或具体结果）

**不能做:**
- ❌ 直接调用 FileManager 读写文件
- ❌ 决定"下一步该执行哪个 agent"（这是编排层的事）
- ❌ 修改自身输入的 state（应返回新 patch，由编排层合并）
- ❌ 捕获异常后静默继续（应抛出让编排层处理）

**约定:**
- 每个 agent 是"纯函数"：相同输入必须产生相同类型的输出
- LLM client 由 agent 自行构造（从 config 参数），这是合理的
- Agent 之间不能直接调用，必须通过编排层传递

#### 3.3.2 Service (src/novel/services/)

**可以做:**
- 封装可复用的业务能力（意图解析、影响分析、变更管理）
- 组合 tool 和 storage 完成功能
- 调用 LLM（通过自身的 LLM client）

**不能做:**
- ❌ 管理流程（不能决定"做完这个接着做那个"）
- ❌ 直接操作 checkpoint
- ❌ 调用 agent

**与 Agent 的区别:**
- Agent 是"有状态上下文的决策者"（如 Writer 知道当前写到第几章）
- Service 是"无状态的能力提供者"（如 IntentParser 不关心当前进度）

#### 3.3.3 Tool (src/novel/tools/)

**可以做:**
- 提供原子级能力（BM25 检索、风格分析、规则检查、章节摘要）
- 接受明确参数，返回明确结果

**不能做:**
- ❌ 有副作用（不写文件、不修改状态）
- ❌ 调用 LLM（这是 agent/service 的事）
- ❌ 依赖全局状态

**约定:**
- Tool 是最底层的可复用单元，应该可以独立测试
- Tool 不感知"小说项目"概念，只处理数据

### 3.4 存储层 (src/novel/storage/)

**可以做:**
- 文件读写（JSON、TXT）
- 目录管理
- 备份和清理
- 变更日志记录

**不能做:**
- ❌ 数据验证（Pydantic 验证在编辑器层做）
- ❌ 业务逻辑（如"该不该覆盖"）
- ❌ 路径以外的输入决策

**约定:**
- FileManager 是唯一允许做文件 I/O 的模块
- 其他层如果需要文件操作，必须通过 FileManager
- FileManager 方法应该是幂等的（重复调用不产生副作用）

---

## 4. 调用关系矩阵

| 调用方 ↓ / 被调方 → | Interface | Pipeline | Agent | Service | Tool | Storage |
|---------------------|-----------|----------|-------|---------|------|---------|
| **Interface**       | -         | ✅       | ❌    | ❌      | ❌   | ❌      |
| **Pipeline**        | ❌        | -        | ✅    | ✅      | ❌   | ✅      |
| **Agent**           | ❌        | ❌       | ❌    | ❌      | ✅   | ❌      |
| **Service**         | ❌        | ❌       | ❌    | ❌      | ✅   | ✅      |
| **Tool**            | ❌        | ❌       | ❌    | ❌      | -    | ❌      |
| **Storage**         | ❌        | ❌       | ❌    | ❌      | ❌   | -       |

**关键约束:**
- Agent 不调用 Storage（通过 Pipeline 中转）
- Interface 不调用 Agent（通过 Pipeline 中转）
- Service 不调用 Agent（职责不同）
- Tool 不调用任何上层模块

---

## 5. 状态传递规则

### NovelState 是唯一的跨 agent 状态容器

```python
# src/novel/agents/state.py
class NovelState(TypedDict):
    # 设定字段 (从 novel.json 刷新)
    outline: dict
    characters: list[dict]
    world_setting: dict
    style_name: str            # 唯一风格字段
    main_storyline: dict

    # 运行态字段
    current_chapter: int
    total_chapters: int
    # ... 其他运行时字段
```

**规则:**
- Agent 只读 NovelState 中声明过的字段
- Agent 返回的 patch 只包含 NovelState 中声明过的字段
- 如果 agent 需要新字段，**必须先在 NovelState 中声明**，不能偷偷通过 dict 传递
- Pipeline 负责 merge patch 到 state

---

## 6. 当前违规清单

| 文件 | 行号 | 违规 | 修复方向 |
|------|------|------|----------|
| web.py | _novel_setting_save_form | Interface 直接操作 novel.json | 改为调用 edit_service |
| pipeline.py | 1540-1600 | 编排层包含 prompt 拼接 | 移入 NovelDirector agent |
| edit_service.py | 231 | 编排层直接创建 LLM client | 通过构造函数注入或由 IntentParser 内部管理 |
| style_keeper.py | 207-210 | Agent 读取 NovelState 未声明的字段 | 统一读 style_name |
| pipeline.py | 1467 | 读 style_subcategory 而非 style_name | 统一为 style_name |

---

## 7. 验收标准

- [ ] 所有 agent 的输入输出类型在 NovelState 中有声明
- [ ] 没有 agent 直接调用 FileManager
- [ ] Interface 层不包含业务逻辑
- [ ] Pipeline 不直接调用 LLM
- [ ] Tool 无副作用
- [ ] FileManager 是唯一的文件 I/O 入口
