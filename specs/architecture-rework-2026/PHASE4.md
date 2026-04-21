# Phase 4: 工具层重组 — propose / accept / regenerate 三段式统一

> 架构重构 2026 Phase 4 设计文档。Phase 0-3 已完成（commit `8fcd7be`）。
> 本 Phase 目标：MCP / CLI / agent_chat 三层接口统一到 propose / accept / regenerate 三段式。

---

## 目录

1. [设计目标与原则](#1-设计目标与原则)
2. [工具清单矩阵](#2-工具清单矩阵)
3. [数据回写 source of truth](#3-数据回写-source-of-truth)
4. [幂等与版本控制](#4-幂等与版本控制)
5. [Proposal 数据结构](#5-proposal-数据结构)
6. [三层接口映射](#6-三层接口映射)
7. [与现有 Agent API 的契合度分析](#7-与现有-agent-api-的契合度分析)
8. [现有工具迁移路径](#8-现有工具迁移路径)
9. [任务拆分与并行安全](#9-任务拆分与并行安全)
10. [不做什么](#10-不做什么)

---

## 1. 设计目标与原则

### 核心目标

将 ProjectArchitect / VolumeDirector / ChapterPlanner 已有的 `propose_*` +
`accept_into` / `accept` 方法暴露为三层统一接口（MCP tool / CLI subcommand /
agent_chat tool），让 AI 助手和人类作者都能按"生成草案 → 审阅 → 确认落盘 /
重新生成"的节奏工作。

### 不可违反的 Phase 4 原则

1. **propose 不入库** — 返回 Proposal 对象/JSON，不写 novel.json。
2. **accept 幂等** — 同一 proposal 重复 accept 不产生副作用。
3. **三层同底** — MCP / CLI / agent_chat 共享同一 facade 函数，禁止在任一层
   写独立业务逻辑。
4. **facade 不持有 LLM** — facade 负责加载项目、调 Agent、序列化结果；LLM
   实例在 Agent 内部创建（与 Phase 2 Node 模式一致）。
5. **渐进迁移** — 现有 MCP 工具保留并标记 deprecated，新工具并行上线，给
   调用方至少一个版本周期迁移。

---

## 2. 工具清单矩阵

### 2.1 实体 × 三段式矩阵

| 实体 | propose | accept | regenerate | 负责 Agent | 备注 |
|---|:---:|:---:|:---:|---|---|
| **project_setup** | Y | Y | N | ProjectArchitect | 立项；不需 regenerate——不满意就重新 propose（hints 不同） |
| **synopsis** | Y | Y | Y | ProjectArchitect | 骨架第一步 |
| **main_outline** | Y | Y | Y | ProjectArchitect | 三层大纲 |
| **characters** | Y | Y | Y | ProjectArchitect | 主角 + 核心配角 |
| **world_setting** | Y | Y | Y | ProjectArchitect | 世界观 + 力量体系 |
| **story_arcs** | Y | Y | Y | ProjectArchitect | 跨卷大弧线 |
| **volume_breakdown** | Y | Y | Y | ProjectArchitect | 全书卷骨架 |
| **volume_outline** | Y | Y | Y | VolumeDirector | 单卷 N 章细纲 |
| **chapter_brief** | Y | Y | N | ChapterPlanner | 不需 regenerate——brief 每次写之前自动重建 |

### 2.2 故意不做三段式的实体

| 实体 | 理由 |
|---|---|
| **chapter_text**（正文） | 正文生成由 Writer 负责，已有 `write_chapter` / `refine_chapter` / `rewrite_chapter` 工具。文本创作不是"审批"语义，强套 propose/accept 反直觉。 |
| **volume_settlement**（卷结算报告） | 结算是只读汇总，不涉及"草案→落盘"。保留 `settle_volume` 作为一次性命令。 |
| **revision**（改前章） | 已有 `propose_revision` / `analyze_revision_impact` / `apply_revision` / `rollback_revision` 四步工作流（DESIGN.md T5），形态已是三段式变体，不再套名。 |
| **style_profile** | 统计指纹，自动计算，无需人审。 |
| **ledger 条目**（伏笔/债务/角色状态） | 这些是事实记录，不是创意产出。管理 API 保留现有 `manage_debt` / `get_foreshadowing_graph` 等。 |

### 2.3 每个工具的输入输出 schema 草图

#### propose_project_setup

```python
# 输入
{
    "inspiration": str,            # 灵感文本
    "hints": {                     # 可选覆盖
        "genre": str | None,
        "target_length_class": str | None,
        "target_words": int | None,
        "theme": str | None,
        "style_name": str | None,
        "narrative_template": str | None,
    } | None
}
# 输出
{
    "proposal_id": str,            # UUID
    "proposal_type": "project_setup",
    "data": ProjectSetupProposal.to_dict(),
    "created_at": str,             # ISO timestamp
}
```

#### propose_synopsis / propose_characters / propose_world_setting / propose_story_arcs / propose_volume_breakdown

```python
# 通用输入（各 propose 共享 project_path，差异字段见下表）
{
    "project_path": str,           # 项目目录
    # propose_synopsis: 无额外参数（从 novel.json 读 meta）
    # propose_characters: "synopsis": str | None（可选上下文）
    # propose_world_setting: "synopsis": str | None
    # propose_story_arcs: 无额外参数（从 novel.json 读 outline）
    # propose_volume_breakdown: "synopsis": str | None
}
# 通用输出
{
    "proposal_id": str,
    "proposal_type": "synopsis" | "characters" | "world_setting" | "story_arcs" | "volume_breakdown",
    "data": <对应 Proposal>.to_dict(),
    "created_at": str,
}
```

#### propose_main_outline

```python
# 输入
{
    "project_path": str,
    "custom_ideas": str | None,    # 作者额外要求
}
# 输出
{
    "proposal_id": str,
    "proposal_type": "main_outline",
    "data": MainOutlineProposal.to_dict(),
    "decisions": list[dict],       # 透传 Agent 决策日志
    "errors": list[dict],
    "created_at": str,
}
```

#### propose_volume_outline

```python
# 输入
{
    "project_path": str,
    "volume_number": int,
}
# 输出
{
    "proposal_id": str,
    "proposal_type": "volume_outline",
    "data": VolumeOutlineProposal.to_dict(),
    "created_at": str,
}
```

#### propose_chapter_brief

```python
# 输入
{
    "project_path": str,
    "chapter_number": int,
}
# 输出
{
    "proposal_id": str,
    "proposal_type": "chapter_brief",
    "data": ChapterBriefProposal 序列化,
    "warnings": list[str],
    "created_at": str,
}
```

#### accept（通用）

```python
# 输入
{
    "project_path": str,
    "proposal_id": str,            # 来自 propose 返回
    "proposal_type": str,          # 用于 dispatch
    "data": dict,                  # propose 返回的 data（可被用户编辑后回传）
}
# 输出
{
    "status": "accepted",
    "proposal_id": str,
    "proposal_type": str,
    "changelog_id": str | None,    # 写入 changelog 的条目 ID（有的实体不写 changelog）
}
```

#### regenerate（通用）

```python
# 输入
{
    "project_path": str,
    "section": str,                # synopsis | characters | world_setting | story_arcs | volume_breakdown | main_outline | volume_outline
    "hints": str,                  # 作者对"哪里不满意/想要什么"的自然语言
    "volume_number": int | None,   # 仅 volume_outline 需要
}
# 输出 = 同 propose 的输出（新 proposal_id）
```

---

## 3. 数据回写 source of truth

### 3.1 决策：novel.json 是唯一 authoritative 持久化

| 层 | 角色 |
|---|---|
| **novel.json** | 唯一 source of truth。accept 写这里。 |
| **checkpoint.json** | pipeline 运行时的"进度断点"，记录 current_chapter / completed_chapters 等运行时状态。accept 操作不写 checkpoint——checkpoint 只在 `generate_chapters` 流程中更新。 |
| **LangGraph state** | 瞬态内存。Node 执行完毕后通过 `state_writeback` 写入 novel.json + checkpoint。Phase 4 不改动 LangGraph state 设计。 |

### 3.2 propose 不入库的实现方式

**选项 A：propose 结果只活在 caller 内存**（推荐）
- MCP / CLI 调用 `facade.propose_xxx()` → 拿到 `ProposalEnvelope` → 返回给
  caller（Claude / 终端 / Web UI）
- caller 审阅后带着 `proposal_id` + `data`（可能被编辑过）调 `facade.accept()`
- facade 不缓存任何 proposal；两次 propose 之间完全无状态

**选项 B：proposal 落临时文件（`workspace/proposals/<id>.json`）**
- 优点：MCP session 断线后还能 resume
- 缺点：引入文件 GC 问题；与"propose 不入库"精神不完全一致

**推荐 A**。理由：
- MCP session 断线是极小概率场景，重新 propose 成本低（单次 LLM 调用）
- B 需要 GC / TTL 机制，增加维护负担
- 架构原则 1 "propose 不入库"最干净的实现就是不落盘

### 3.3 accept 写什么

| proposal_type | accept 写入位置 | 写入方式 |
|---|---|---|
| project_setup | `novel.json` 根字段：genre / theme / style_name / target_words / narrative_template | `Proposal.accept_into(novel_data)` |
| synopsis | `novel.json`: synopsis + outline.main_storyline | `SynopsisProposal.accept_into(novel)` |
| main_outline | `novel.json`: outline + style_name + style_bible | `MainOutlineProposal.accept_into(novel)` |
| characters | `novel.json`: characters[] | `CharactersProposal.accept_into(novel)` |
| world_setting | `novel.json`: world_setting | `WorldProposal.accept_into(novel)` |
| story_arcs | `novel.json`: story_arcs[] | `ArcsProposal.accept_into(novel)` |
| volume_breakdown | `novel.json`: outline.volumes[] | `VolumeBreakdownProposal.accept_into(novel)` |
| volume_outline | `novel.json`: 对应 Volume 模型字段 | `VolumeOutlineProposal.accept(volume)` |
| chapter_brief | `novel.json`: 对应 chapter outline 的 chapter_brief 字段 | 直接 dict merge |

accept 之后统一调 `FileManager.save_novel(novel_id, novel_data)` 一次。

### 3.4 用户怎么看到 propose 结果

| 接口层 | 展示方式 |
|---|---|
| **MCP** | propose 工具返回 JSON → Claude 读取后用自然语言转述给用户 → 用户确认后 Claude 调 accept |
| **CLI** | propose 命令输出 YAML/JSON 到 stdout → 用户审阅 → 手动调 `accept` 命令（或 `--auto-accept` 跳过） |
| **agent_chat** | tool 返回 JSON → agent_chat LLM 读取后组织语言回复用户 → 下一轮 tool call accept |

---

## 4. 幂等与版本控制

### 4.1 重复 accept 同一 proposal

**行为**：幂等——再次 accept 等价于覆盖写入同一数据。因为 `accept_into` 是
纯 field 赋值（不做 append），重复写入效果一致。

**实现保障**：
- `accept` 入口记录 `last_accepted_proposal_id` 到 novel.json 的 `_meta` 字段
- 如果 `proposal_id == last_accepted_proposal_id`，跳过写入，直接返回 `status: "already_accepted"`
- 保证落盘 IO 最少

### 4.2 proposal 是否带 nonce / id

**是。每个 proposal 带 UUID `proposal_id`**：
- 用于 accept 时做幂等校验
- 用于日志追踪
- **不用于持久化**（proposal 不入库，id 仅在 caller 会话内有效）

### 4.3 regenerate 与历史版本

regenerate 不保留历史版本。理由：

- DESIGN.md 原则 7 "删而不藏"——regenerate 的语义是"不满意，重来"
- 旧 proposal 从未入库，无需回滚
- 已有的 `setting_version.py`（`effective_from_chapter` / `deprecated_at_chapter`）
  仅用于已 accept 的实体版本管理，不适用于 proposal 阶段

如果用户 accept 了 A，后来 regenerate 得到 B 并 accept B：
- characters / world_setting：走 `setting_version.py` 的版本链，A 被标记
  `deprecated_at_chapter = B.effective_from_chapter`
- synopsis / outline / arcs：直接覆盖（这些是全局唯一实例，不做多版本）

---

## 5. Proposal 数据结构

### 5.1 ProposalEnvelope — 工具层统一包装

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class ProposalEnvelope:
    """工具层返回给 caller 的统一包装。

    所有 propose 函数返回此对象（或其 to_dict() 序列化）。
    """
    proposal_id: str = field(default_factory=lambda: str(uuid4()))
    proposal_type: str = ""           # "synopsis" | "characters" | ...
    project_path: str = ""
    data: dict[str, Any] = field(default_factory=dict)  # Proposal.to_dict()
    decisions: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "project_path": self.project_path,
            "data": self.data,
            "decisions": self.decisions,
            "errors": self.errors,
            "warnings": self.warnings,
            "created_at": self.created_at,
        }
```

### 5.2 AcceptResult — accept 统一返回

```python
@dataclass
class AcceptResult:
    """accept 操作的统一返回。"""
    status: str = "accepted"          # "accepted" | "already_accepted" | "failed"
    proposal_id: str = ""
    proposal_type: str = ""
    changelog_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "status": self.status,
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
        }
        if self.changelog_id:
            result["changelog_id"] = self.changelog_id
        if self.error:
            result["error"] = self.error
        return result
```

### 5.3 现有 Proposal dataclass 不动

Phase 3 已定型的 Proposal dataclass（`ProjectSetupProposal` /
`SynopsisProposal` / `CharactersProposal` / `WorldProposal` / `ArcsProposal` /
`MainOutlineProposal` / `VolumeBreakdownProposal` / `VolumeOutlineProposal` /
`ChapterBriefProposal`）**不改动**。facade 层负责把它们包进
`ProposalEnvelope`。

---

## 6. 三层接口映射

### 6.1 架构分层

```
┌─────────────────────────────────────────────────────────┐
│  MCP tools    │  CLI commands   │  agent_chat tools     │
│  (mcp_server) │  (main.py)      │  (agent_chat.py)      │
├───────────────┴─────────────────┴───────────────────────┤
│                 NovelToolFacade                          │
│  (src/novel/services/tool_facade.py)  ← 新增，唯一入口  │
├─────────────────────────────────────────────────────────┤
│  ProjectArchitect │ VolumeDirector │ ChapterPlanner      │
│  (agents/)        │ (agents/)      │ (agents/)           │
├─────────────────────────────────────────────────────────┤
│  FileManager  │  LedgerStore  │  ChangelogManager       │
│  (storage/)   │  (services/)  │  (services/)            │
└─────────────────────────────────────────────────────────┘
```

关键：**NovelToolFacade 是三层共享的唯一业务入口**。MCP / CLI / agent_chat
只做参数适配（字符串 → Python 类型）和结果格式化（Python 对象 → JSON /
Rich Table），不含任何业务逻辑。

### 6.2 MCP 工具命名

采用 `novel_propose_<entity>` / `novel_accept_proposal` / `novel_regenerate_section`
格式。理由：

- 保持现有 `novel_` 前缀惯例
- accept 和 regenerate 各一个通用入口（通过 `proposal_type` / `section` 参数
  dispatch），避免注册 18 个 MCP 工具

```
# propose 系列（9 个）
novel_propose_project_setup(inspiration, hints?)
novel_propose_synopsis(project_path)
novel_propose_main_outline(project_path, custom_ideas?)
novel_propose_characters(project_path, synopsis?)
novel_propose_world_setting(project_path, synopsis?)
novel_propose_story_arcs(project_path)
novel_propose_volume_breakdown(project_path, synopsis?)
novel_propose_volume_outline(project_path, volume_number)
novel_propose_chapter_brief(project_path, chapter_number)

# accept（1 个，通用）
novel_accept_proposal(project_path, proposal_id, proposal_type, data)

# regenerate（1 个，通用）
novel_regenerate_section(project_path, section, hints, volume_number?)
```

**为什么 propose 分开但 accept/regenerate 合并？**
- propose 的参数差异大（inspiration vs project_path + chapter_number），分开有
  更好的 tool description + schema 自动补全
- accept 的参数完全统一（proposal_id + data），合并减少工具数
- regenerate 的参数几乎统一（section + hints），合并合理

### 6.3 CLI 子命令

```bash
# propose 系列
novel propose project-setup "一句灵感"
novel propose synopsis <project_path>
novel propose main-outline <project_path>
novel propose characters <project_path>
novel propose world-setting <project_path>
novel propose story-arcs <project_path>
novel propose volume-breakdown <project_path>
novel propose volume-outline <project_path> --volume 1
novel propose chapter-brief <project_path> --chapter 5

# accept（从 stdin 或 --file 读 proposal JSON）
novel accept <project_path> --proposal-file proposal.json
novel accept <project_path> --proposal-id <id> --type synopsis
# 快捷：propose + auto-accept（保留给自动化场景）
novel propose synopsis <project_path> --auto-accept

# regenerate
novel regenerate <project_path> --section synopsis --hints "主角换成女性"
```

**选项**：`--json` 输出纯 JSON（便于管道），`--yaml` 输出 YAML（便于人读），
默认 Rich Table 格式。

### 6.4 agent_chat 工具注册

在现有 `TOOLS` 列表末尾追加三段式工具定义。现有工具（`edit_setting` /
`generate_chapters` / `rewrite_chapter` 等）保留不动——它们不属于三段式范畴。

```python
# 追加到 TOOLS（示例，非完整）
{
    "name": "propose_synopsis",
    "description": "为当前小说项目生成主线故事骨架草案（不落盘）。返回 proposal JSON 供用户审阅。",
    "parameters": {},
},
{
    "name": "accept_proposal",
    "description": "确认落盘一个 propose_* 返回的草案。传入 proposal_id 和可能被用户编辑过的 data。",
    "parameters": {
        "proposal_id": {"type": "string", "description": "proposal ID"},
        "proposal_type": {"type": "string", "description": "synopsis/characters/world_setting/..."},
        "data": {"type": "object", "description": "草案数据（可被编辑）"},
    },
},
{
    "name": "regenerate_section",
    "description": "对不满意的骨架段落重新生成草案。传入 section 名 + hints。",
    "parameters": {
        "section": {"type": "string", "description": "synopsis/characters/world_setting/story_arcs/volume_breakdown/main_outline/volume_outline"},
        "hints": {"type": "string", "description": "哪里不满意、想要什么"},
        "volume_number": {"type": "integer", "description": "卷号（仅 volume_outline 需要）", "optional": True},
    },
},
```

### 6.5 三层共享底层函数签名

```python
class NovelToolFacade:
    """工具层统一 facade。MCP / CLI / agent_chat 共享此类。"""

    def __init__(self, workspace: str = "workspace"):
        self.workspace = workspace
        self._fm = FileManager(workspace)

    # --- propose ---
    def propose_project_setup(self, inspiration: str, hints: dict | None = None) -> ProposalEnvelope: ...
    def propose_synopsis(self, project_path: str) -> ProposalEnvelope: ...
    def propose_main_outline(self, project_path: str, custom_ideas: str | None = None) -> ProposalEnvelope: ...
    def propose_characters(self, project_path: str, synopsis: str | None = None) -> ProposalEnvelope: ...
    def propose_world_setting(self, project_path: str, synopsis: str | None = None) -> ProposalEnvelope: ...
    def propose_story_arcs(self, project_path: str) -> ProposalEnvelope: ...
    def propose_volume_breakdown(self, project_path: str, synopsis: str | None = None) -> ProposalEnvelope: ...
    def propose_volume_outline(self, project_path: str, volume_number: int) -> ProposalEnvelope: ...
    def propose_chapter_brief(self, project_path: str, chapter_number: int) -> ProposalEnvelope: ...

    # --- accept ---
    def accept_proposal(
        self,
        project_path: str,
        proposal_id: str,
        proposal_type: str,
        data: dict,
    ) -> AcceptResult: ...

    # --- regenerate ---
    def regenerate_section(
        self,
        project_path: str,
        section: str,
        hints: str = "",
        volume_number: int | None = None,
    ) -> ProposalEnvelope: ...
```

---

## 7. 与现有 Agent API 的契合度分析

### 7.1 ProjectArchitect — 高度吻合

| facade 方法 | Agent 方法 | 需要改动 |
|---|---|---|
| `propose_project_setup` | `ProjectArchitect.propose_project_setup()` | 无——返回 `ProjectSetupProposal`，facade 包 envelope |
| `propose_synopsis` | `ProjectArchitect.propose_synopsis()` | 无 |
| `propose_main_outline` | `ProjectArchitect.propose_main_outline()` | 无 |
| `propose_characters` | `ProjectArchitect.propose_main_characters()` | 命名微调（facade 用 `characters`，Agent 用 `main_characters`）——不改 Agent，facade 做映射 |
| `propose_world_setting` | `ProjectArchitect.propose_world_setting()` | 无 |
| `propose_story_arcs` | `ProjectArchitect.propose_story_arcs()` | 无 |
| `propose_volume_breakdown` | `ProjectArchitect.propose_volume_breakdown()` | 无 |
| `regenerate_section` | `ProjectArchitect.regenerate_section()` | 无——已支持 `section` + `current_spine` + `hints` |

**结论**：ProjectArchitect 已经是 facade 的直接映射。facade 只需做：
1. 从 `project_path` 加载 novel.json 构造 `meta` dict
2. 创建 LLM client
3. 调 Agent 方法
4. 包 `ProposalEnvelope`

### 7.2 VolumeDirector — 高度吻合

| facade 方法 | Agent 方法 | 需要改动 |
|---|---|---|
| `propose_volume_outline` | `VolumeDirector.propose_volume_outline()` | 无 |

regenerate_section 对 `volume_outline` 的处理：调
`VolumeDirector.propose_volume_outline(novel, volume_number, hints=...)` —
但当前 `propose_volume_outline` **没有 hints 参数**。

**需要新增**：`VolumeDirector.propose_volume_outline` 加可选 `hints: str = ""`
参数，注入到 prompt 中。改动量小——在 `_build_propose_prompt` 末尾加一行。

### 7.3 ChapterPlanner — 高度吻合

| facade 方法 | Agent 方法 | 需要改动 |
|---|---|---|
| `propose_chapter_brief` | `ChapterPlanner.propose_chapter_brief()` | 无 |

chapter_brief 不做 regenerate（每次 propose 都是从 Ledger 实时重建），
`update_chapter_brief` 已有（手动编辑 brief）。

### 7.4 需要新增的签名改动汇总

| 文件 | 改动 | 影响范围 |
|---|---|---|
| `volume_director.py` | `propose_volume_outline` 加 `hints: str = ""` | 纯新增可选参数，向后兼容 |
| （无其它 Agent 需要改动） | — | — |

### 7.5 是否需要 facade 还是 MCP 直接调 Agent

**需要 facade**。理由：

1. MCP / CLI / agent_chat 都需要"从 project_path 加载 novel.json → 构造
   meta → 创建 LLM → 调 Agent → 包装结果 → 写回 novel.json"这段公共逻辑。
   没有 facade 就要在三处重复实现。
2. accept 逻辑（加载 novel.json → 调 `Proposal.accept_into(novel)` → save）
   不属于任何 Agent，需要一个协调者。
3. facade 是纯同步 Python 类，不依赖 MCP / Click / LangGraph 框架，可独立测试。

---

## 8. 现有工具迁移路径

### 8.1 现有 MCP 工具处置矩阵

| 现有工具 | 处置 | 理由 |
|---|---|---|
| `novel_create` | **deprecated → 替代** | 被 `novel_propose_project_setup` + `novel_propose_main_outline` + `novel_accept_proposal` × N 组合替代。一步到位的 `novel_create` 语义与三段式矛盾。保留一个版本周期后删除。 |
| `novel_generate_chapters` | **保留** | 正文生成不走三段式。 |
| `novel_get_status` | **保留** | 只读查询，不涉及三段式。 |
| `novel_read_chapter` | **保留** | 只读查询。 |
| `novel_apply_feedback` | **保留** | 已有独立流程。 |
| `novel_export` | **保留** | 独立功能。 |
| `novel_list_projects` | **保留** | 只读查询。 |
| `novel_edit_setting` | **保留** | 编辑已落盘的设定（非 propose 语义）。与三段式互补：propose 用于创建新设定，edit 用于修改已有设定。 |
| `novel_analyze_change_impact` | **保留** | 只读分析。 |
| `novel_get_change_history` | **保留** | 只读查询。 |

### 8.2 deprecated 策略

`novel_create` 将被标记 deprecated：

```python
@mcp.tool()
def novel_create(...) -> dict[str, Any]:
    """[DEPRECATED] Use novel_propose_project_setup + novel_accept_proposal
    for step-by-step project creation with review.

    This tool is retained for backward compatibility and will be removed
    in a future version. It creates a project in one step without review.
    ...
    """
```

保留时间：至少到 Phase 5 完成。

### 8.3 CLI 现有命令处置

| 现有命令 | 处置 |
|---|---|
| `novel write` | **保留** 作为 "快速模式"（内部改为调 facade 的 propose + auto-accept）。新增 `novel propose` 子命令组作为"交互模式"。 |
| `novel resume` | **保留** |
| `novel export` | **保留** |
| `novel status` | **保留** |
| `novel list` | **保留** |
| `novel health` | **保留** |
| `novel edit` | **保留** |
| `novel history` | **保留** |
| `novel rollback` | **保留** |

新增命令组：

```
novel propose <subcommand>    # 9 个子命令
novel accept                  # 1 个命令
novel regenerate              # 1 个命令
```

### 8.4 agent_chat 现有工具处置

| 现有工具 | 处置 |
|---|---|
| `edit_setting` | **保留**——编辑已落盘设定 |
| `generate_chapters` | **保留**——正文生成 |
| `rewrite_chapter` | **保留**——正文重写 |
| `refine_chapter` | **保留**——审阅报告 |
| `critique_chapter` / `review_chapter` | **保留** |
| `verify_chapter` | **保留** |
| `plan_chapters` | **deprecated → 替代**——被 `propose_chapter_brief` 替代 |
| `get_novel_info` | **保留** |
| `read_chapter` | **保留** |
| 账本/放大镜类工具 | **全部保留** |

---

## 9. 任务拆分与并行安全

### 9.1 依赖顺序

```
[T0] NovelToolFacade 核心骨架 + ProposalEnvelope + AcceptResult
        ↓
[T1] facade propose 系列实现（调 Agent → 包 envelope）
[T2] facade accept 实现（加载 → accept_into → save）
[T3] facade regenerate 实现（dispatch → 调 Agent → 包 envelope）
        ↓
[T4] MCP 工具注册（调 facade）
[T5] CLI 子命令（调 facade）
[T6] agent_chat 工具注册（调 facade）
        ↓
[T7] 集成测试 + deprecated 标记
```

T0 必须先做（facade 骨架是其他一切的基础）。
T1/T2/T3 可并行（各自独立方法，不修改同一函数）。
T4/T5/T6 可并行（各自独立文件）。
T7 最后做。

### 9.2 推荐 3 个 task-executor

| Executor | 负责文件 | 任务 |
|---|---|---|
| **E1: Facade** | `src/novel/services/tool_facade.py`（新建）<br>`tests/novel/test_tool_facade.py`（新建） | T0 → T1 → T2 → T3。核心业务逻辑全在这一个文件，独占不冲突。 |
| **E2: MCP + CLI** | `mcp_server.py`（追加工具）<br>`main.py`（追加 `novel propose` / `novel accept` / `novel regenerate` 命令组）<br>`tests/novel/test_mcp_propose.py`（新建）<br>`tests/novel/test_cli_propose.py`（新建） | T4 + T5。两个入口文件各自独立。 |
| **E3: agent_chat + 集成** | `src/novel/services/agent_chat.py`（追加 tool 定义 + executor 方法）<br>`tests/novel/test_agent_chat_propose.py`（新建）<br>`volume_director.py`（加 `hints` 参数） | T6 + VolumeDirector 微调 + T7 集成测试。 |

### 9.3 并行安全边界

| 共享资源 | 冲突风险 | 缓解措施 |
|---|---|---|
| `mcp_server.py` | E2 独占追加 | 无冲突 |
| `main.py` | E2 独占追加 | 无冲突 |
| `agent_chat.py` | E3 独占追加 | 无冲突 |
| `volume_director.py` | E3 独占改（加 `hints` 参数） | 纯新增可选参数，不改现有代码 |
| `tool_facade.py` | E1 独占新建 | 无冲突（新文件） |
| `project_architect.py` | **无人改动** | Phase 3 已定型 |
| `chapter_planner.py` | **无人改动** | Phase 3 已定型 |

### 9.4 每个 Executor 的工作量估算

| Executor | 预估工时 | 新增代码量 |
|---|---|---|
| E1: Facade | 1 天 | ~400 行实现 + ~600 行测试 |
| E2: MCP + CLI | 0.5 天 | ~300 行 MCP 工具 + ~200 行 CLI + ~400 行测试 |
| E3: agent_chat + 集成 | 0.5 天 | ~100 行 agent_chat 追加 + ~50 行 VolumeDirector + ~300 行测试 |
| **总计** | **2 天** | **~2350 行** |

---

## 10. 不做什么

| 不做 | 理由 |
|---|---|
| **不改 Proposal dataclass 签名** | Phase 3 已定型，facade 只包装不改造 |
| **不改 LangGraph graph / state** | Phase 4 是工具层，graph 在 Phase 3 定型 |
| **不做 proposal 持久化** | 原则 1 "propose 不入库"，断线重新 propose 成本低 |
| **不做 chapter_text 的 propose/accept** | 正文创作不是审批语义 |
| **不做 Web UI 适配** | README 明确排除；Web UI 跟着后端 API 调 |
| **不合并 ContinuityService** | Phase 3 决策暂缓（低价值高 churn） |
| **不做 revision 工作流的三段式重命名** | 已有四步工作流，形态满足需求 |
| **不改 `novel_edit_setting`** | 编辑已落盘设定与 propose 新设定是互补关系，不是替代 |
| **不做 Phase 5 测试维度修正** | 独立 Phase，不前置 |

---

## 附录 A: facade 方法伪代码（参考实现骨架）

```python
def propose_synopsis(self, project_path: str) -> ProposalEnvelope:
    novel_id = self._extract_novel_id(project_path)
    novel_data = self._fm.load_novel(novel_id)
    if novel_data is None:
        return ProposalEnvelope(
            proposal_type="synopsis",
            project_path=project_path,
            errors=[{"message": f"项目不存在: {project_path}"}],
        )

    meta = self._build_meta(novel_data)
    llm = self._create_llm(novel_data)
    architect = ProjectArchitect(llm)
    proposal = architect.propose_synopsis(meta)

    return ProposalEnvelope(
        proposal_type="synopsis",
        project_path=project_path,
        data=proposal.to_dict(),
    )


def accept_proposal(
    self,
    project_path: str,
    proposal_id: str,
    proposal_type: str,
    data: dict,
) -> AcceptResult:
    novel_id = self._extract_novel_id(project_path)
    novel_data = self._fm.load_novel(novel_id)
    if novel_data is None:
        return AcceptResult(status="failed", error="项目不存在")

    # 幂等检查
    meta = novel_data.get("_meta", {})
    if meta.get("last_accepted_proposal_id") == proposal_id:
        return AcceptResult(
            status="already_accepted",
            proposal_id=proposal_id,
            proposal_type=proposal_type,
        )

    # Dispatch accept
    self._apply_proposal(novel_data, proposal_type, data)

    # 记录幂等标记
    novel_data.setdefault("_meta", {})["last_accepted_proposal_id"] = proposal_id

    # 持久化
    self._fm.save_novel(novel_id, novel_data)

    return AcceptResult(
        status="accepted",
        proposal_id=proposal_id,
        proposal_type=proposal_type,
    )


def _apply_proposal(self, novel_data: dict, proposal_type: str, data: dict):
    """Dispatch to the correct Proposal.accept_into."""
    if proposal_type == "synopsis":
        SynopsisProposal(**data).accept_into(novel_data)
    elif proposal_type == "characters":
        profiles = [CharacterProfile(**c) for c in data.get("characters", [])]
        CharactersProposal(characters=profiles).accept_into(novel_data)
    elif proposal_type == "world_setting":
        WorldProposal(world=WorldSetting(**data["world_setting"])).accept_into(novel_data)
    elif proposal_type == "story_arcs":
        ArcsProposal(arcs=data.get("arcs", [])).accept_into(novel_data)
    elif proposal_type == "volume_breakdown":
        VolumeBreakdownProposal(volumes=data.get("volumes", [])).accept_into(novel_data)
    elif proposal_type == "main_outline":
        MainOutlineProposal(**{k: data[k] for k in ("outline", "template", "style_name") if k in data}).accept_into(novel_data)
    elif proposal_type == "project_setup":
        ProjectSetupProposal(**data).accept_into(novel_data)
    elif proposal_type == "volume_outline":
        # volume_outline 的 accept 需要找到对应 Volume 模型
        # facade 封装这段查找逻辑
        ...
    elif proposal_type == "chapter_brief":
        # merge into chapter_outline.chapter_brief
        ...
    else:
        raise ValueError(f"未知 proposal_type: {proposal_type}")
```

---

## 附录 B: MCP 工具注册示例

```python
@mcp.tool()
def novel_propose_synopsis(project_path: str) -> dict[str, Any]:
    """Generate a synopsis proposal (3-5 sentences + structured main_storyline).

    Returns a proposal dict for review. Call novel_accept_proposal() to
    persist, or novel_regenerate_section() to try again with hints.

    Args:
        project_path: Path to the novel project directory.

    Returns:
        ProposalEnvelope dict with proposal_id, data, and metadata.
    """
    try:
        validated = _validate_project_path(project_path)
        facade = _get_facade()
        result = facade.propose_synopsis(str(validated))
        return result.to_dict()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def novel_accept_proposal(
    project_path: str,
    proposal_id: str,
    proposal_type: str,
    data: dict,
) -> dict[str, Any]:
    """Accept a proposal and persist it to novel.json.

    Args:
        project_path: Path to the novel project directory.
        proposal_id: The proposal_id from a propose_* call.
        proposal_type: One of: project_setup, synopsis, main_outline,
            characters, world_setting, story_arcs, volume_breakdown,
            volume_outline, chapter_brief.
        data: The proposal data dict (may have been edited by the user).

    Returns:
        AcceptResult dict with status and optional changelog_id.
    """
    try:
        validated = _validate_project_path(project_path)
        facade = _get_facade()
        result = facade.accept_proposal(
            str(validated), proposal_id, proposal_type, data
        )
        return result.to_dict()
    except Exception as e:
        return {"error": str(e)}
```
