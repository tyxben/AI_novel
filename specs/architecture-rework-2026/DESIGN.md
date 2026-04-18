# 新架构设计 (2026-04-18)

> 配套审视报告 `AUDIT.md`，模块利用率 `MODULE_USAGE.md`。

## 设计目标

1. **支持各类型小说**（玄幻/悬疑/言情/科幻/现实/文学性…），无 default 体裁
2. **支持各长度**（30 章短篇 → 500 章长篇），章字数/卷划分按体裁自适应
3. **工具不替作者拍板**，所有审美/方向判断回归作者；工具只做"放大镜+账本+跑腿"
4. **卷为一等公民**，立项→搭骨架→单卷细纲→章循环→卷复盘→下卷立项 闭环
5. **生成期 Writer 真读账本**（不是事后报表）

## 7 条不可违反的架构原则

1. **propose 不入库** — 所有 `propose_xxx` 是建议，作者 accept/finalize 才落盘
2. **零自动重写** — Verifier/Reviewer 只标，作者拍板
3. **零全局硬阈值** — 所有 threshold 是项目级配置，立项时按体裁/长度生成默认
4. **零默认体裁** — 立项必须显式选，无 fallback
5. **卷为一等公民** — 每卷独立的 goal/outline/settlement，可以"先写完卷 1 再细化卷 2"
6. **写作时账本是实时的** — ChapterBrief 由 ChapterPlanner 从 Ledger 实时拼装
7. **删而不藏** — 砍掉的功能直接删，不留 fallback path

---

# Part 1 · 数据模型（重组）

```
Novel (项目根)
├── ProjectMeta              立项产物，可改
│   ├── genre                必填，无默认
│   ├── subgenre / style     必填
│   ├── target_length_class  short/medium/long（决定卷划分策略）
│   └── narrative_template   three_act / four_act / cyclic / freeform / ...
│
├── Spine                    骨架，可逐部分重生成
│   ├── synopsis             3-5 句主线
│   ├── main_characters[]    主角+核心配角
│   ├── world                设定/规则/术语
│   ├── arcs[]               跨卷大弧线
│   └── volume_breakdown[]   卷划分（每卷一两句）
│
├── Volumes[]                ★ 一等公民
│   ├── volume_id, number, title
│   ├── volume_goal          本卷讲什么
│   ├── volume_outline       本卷 N 章列表（每章一两句 + 伏笔规划）
│   ├── chapter_type_dist    本卷各 chapter_type 配额（决定字数/节奏）
│   ├── settlement?          本卷结算（写完才有）
│   └── chapters[]
│       ├── chapter_id, number, title
│       ├── target_words     ★ 章节级字数（按 chapter_type 设）
│       ├── chapter_type     setup/buildup/climax/resolution/interlude
│       ├── brief?           写之前规划，作者审过才有
│       ├── content?         正文
│       └── status           planned/drafted/reviewed/accepted/published
│
├── Ledger                   ★ 账本（事实统一入口，零判断）
│   ├── foreshadowings[]     伏笔（plant/collect/abandoned）
│   ├── debts[]              叙事债务
│   ├── character_states{}   每章的角色快照
│   ├── world_facts[]        已建立的世界观事实
│   └── changelog[]          所有变更历史
│
├── StyleProfile             ★ 本书的用词/句长/节奏统计指纹
│   ├── overused_phrases     >= 30% 章节出现的短语（自动检测）
│   ├── avg_sentence_len
│   └── pacing_curve         按章统计的"动作密度"
│
└── ReflexionLog[]           跨章经验积累（每章写完一条）
```

**关键变化**：
- `Volume` 从 model 提升到 pipeline 一等公民
- `target_words` 下放到 `Chapter`
- `ledger` 替代分散的 ObligationTracker / KnowledgeGraph 等独立 store（后端可以仍是分库，但语义层统一）
- `StyleProfile` 取代硬编码 AI 黑名单
- `chapter_type` 决定字数/节奏配额，无全局常量

---

# Part 2 · Agent 体系（5 个，每个有清晰职责）

> 砍掉 9 → 5。每个 Agent 是 LLM 调用 + system prompt + 输入输出 schema 的封装，无业务状态。

## A1. ProjectArchitect (项目架构师)
**何时出场**：立项 + 骨架阶段（一次性，但可重新唤起调整某部分）  
**输入**：作者的灵感/类型偏好/长度偏好  
**输出**：ProjectMeta proposal + Spine proposal（synopsis / characters / world / arcs / volume_breakdown）  
**LLM 调用**：每段独立调（synopsis 一次、characters 一次…），便于作者按段重生成  
**取代**：原 NovelDirector（部分） + WorldBuilder + CharacterDesigner

## A2. VolumeDirector (卷导演) ★ 新角色
**何时出场**：进入新卷时 + 卷写完时  
**输入**：Spine + 上一卷 settlement（如果有）+ 当前卷在 spine 中的位置  
**输出**：
- 进卷时：propose_volume_outline（本卷 N 章 + 每章一两句 + 伏笔规划 + chapter_type 分布）
- 出卷时：volume_settlement_report（本卷应兑现/未兑现、伏笔回收率、留给下卷的钩子）  
**LLM 调用**：进卷 1 次、出卷 1 次  
**取代**：贯穿全书的"导演"角色（之前缺失）

## A3. ChapterPlanner (章节规划师)
**何时出场**：写每章之前  
**输入**：Volume outline + 本章在卷中的位置 + Ledger 当前快照（应兑现债务、应回收伏笔、活跃角色状态）  
**输出**：ChapterBrief
```
{
  "chapter_number": N,
  "goal": "...",
  "scenes": [{"summary": "...", "characters": [...]}],
  "must_collect_foreshadowings": [...],   ← 从 Ledger 实时取
  "must_fulfill_debts": [...],            ← 从 Ledger 实时取
  "active_characters": [...],
  "world_facts_to_respect": [...],
  "target_words": N,                       ← 从 chapter_type 推
  "tone_notes": "..."
}
```
**LLM 调用**：每章 1 次  
**关键变化**：账本从 ContinuityService 摘条，升级为 Planner 主动按本章上下文取

## A4. Writer (作家)
**何时出场**：写稿 + 改稿  
**两个方法**：
- `draft(brief)` → 出初稿
- `refine(text, feedback)` → 按 reviewer/verifier 反馈精修

**关键变化**：删除 self_critique/polish_chapter（重复职责），统一 `refine()` 入口

## A5. Reviewer (审稿编辑) ★ 重设计
**何时出场**：每章写完后  
**输入**：chapter_text + ChapterBrief + StyleProfile + 上章 tail + 历次批注  
**输出**：CritiqueResult
```
{
  "strengths": [...],
  "issues": [{"type", "severity", "quote", "reason"}],
  "specific_revisions": [{"target", "suggestion"}],
  "overall_assessment": "..."
}
```
**关键变化**：
- 不打分，只标问题
- watchlist 来自 StyleProfile（本书口头禅）+ 用户配置，不来自全局黑名单
- **不触发自动重写**——只产出报告，作者决定是否 refine

**取代**：QualityReviewer + ConsistencyChecker + StyleKeeper（合并）

---

# Part 3 · Service 层（按职责分组）

## B1. 账本类（Ledger Layer，零判断，事实记录）

| Service | 职责 | 现状 |
|---|---|---|
| `LedgerStore` ★新 | 统一入口：foreshadowings / debts / character_states / world_facts | 包装现有 ObligationTracker + KnowledgeGraph + StructuredDB |
| `ChangelogManager` | 变更历史 | 已有，保留 |
| `ReflexionMemory` | 跨章经验 | 已有，保留 |

## B2. 放大镜类（Insight Layer，呈现状态供作者决策）

| Service | 职责 | 现状 |
|---|---|---|
| `BriefAssembler` ★改名 | 给 ChapterPlanner 拼上下文：从 Ledger 按章上下文取应兑现/回收/活跃角色 | 重构现有 ContinuityService |
| `ImpactAnalyzer` | 改章涟漪分析（纯规则） | 已有，保留 |
| `StyleProfileService` ★新 | 本书用词指纹（overused phrases / 句长 / 节奏） | 新写，取代 AI 黑名单 |
| `VolumeAnalyzer` ★新 | 卷级指标：本卷应兑现/伏笔回收率/角色覆盖 | 新写，取代 HealthService 的合成评分 |

## B3. 跑腿类（Mechanical Layer，执行机械活）

| Service | 职责 | 现状 |
|---|---|---|
| `EditService` | 单条/批量/精修编辑 | 已有，保留 |
| `Sanitizer` | 清洗 markdown/元注释/重复开头 | 已有，保留 |
| `Verifier` | 硬约束验证（长度/事实/兑现/世界观一致） | 已有，移除 AI 词检查（移给 StyleProfile） |
| `IntentParser` | 自然语言→结构化变更 | 已有，保留 |

## B4. 编排类（Flow Layer，把上面串成工作流）★ 全新

| Flow | 职责 |
|---|---|
| `ProjectFlow` | 立项 → 骨架 |
| `VolumeFlow` | 进新卷 → 规划本卷 → 章循环 → 卷结算 → 推下卷 |
| `ChapterFlow` | brief → write → sanitize → verify → review → refine? → accept |
| `RevisionFlow` | 改前章 → 涟漪 → 决策 → 执行 → 后续核对 |

每个 Flow 是显式状态机，每步可暂停等作者反馈。

## 砍掉的 Service（与现状对比）

| 删 | 理由 |
|---|---|
| `narrative_rebuild.py` (867 行) | 与 batch_edit 重叠，几乎不用 |
| `import_service.py` (415 行) | **0 引用**，dead code |
| `health_service.py` 的合成评分 | 评分本身就是替作者下判断；保留事实统计移到 VolumeAnalyzer |
| `dedup_dialogue.py` | 单点功能，合并到 Verifier |
| `hook_generator.py` | 由 ChapterPlanner 接管 |
| `consistency_service.py` (旧版) | 由 BriefAssembler + Verifier 接管 |
| `setting_impact_analyzer.py` | 与 ImpactAnalyzer 合并 |
| `entity_extractor.py` + `entity_service.py` | 合并到 LedgerStore |
| `character_arc_tracker.py` | 合并到 LedgerStore.character_states |
| `proofreader.py` | 改成 ReviewerAgent 的一个维度 |
| `agent_chat.py` 中"自动 refine"路径 | 保留工具，删自动触发 |

---

# Part 4 · 工具层（暴露给 Agent / MCP / CLI / Web）

> 工具按用户工作流分组，命名遵循 `propose_/get_/apply_` 三段式：propose 是建议（不入库）、get 是读取、apply 是执行。

## T1. 立项 (ProjectFlow)
| 工具 | 职责 |
|---|---|
| `propose_project_setup(inspiration)` | LLM 反问对话生成 ProjectMeta 草案 |
| `finalize_project_setup(meta)` | 落盘 |

## T2. 骨架 (ProjectFlow 续)
| 工具 | 职责 |
|---|---|
| `propose_synopsis()` / `propose_main_storyline()` | 生成主线草案 |
| `propose_characters()` | 生成人物草案 |
| `propose_world_setting()` | 生成世界观草案 |
| `propose_volume_breakdown()` | 生成卷划分草案 |
| `accept_spine_section(section, content)` | 作者审过的部分落盘 |
| `regenerate_section(section, hints)` | 作者不满意时按提示重生 |

## T3. 卷 (VolumeFlow)
| 工具 | 职责 |
|---|---|
| `enter_new_volume(volume_number)` | 触发 VolumeDirector 进卷规划 |
| `propose_volume_outline(volume_number)` | 生成本卷章节列表草案 |
| `update_volume_outline(volume_number, edits)` | 作者改 |
| `get_volume_progress(volume_number)` | 当前卷写到哪、应兑现/未兑现 |
| `settle_volume(volume_number)` | 本卷写完，触发结算 + 推下卷 |

## T4. 章 (ChapterFlow)
| 工具 | 职责 |
|---|---|
| `propose_chapter_brief(chapter_number)` | 触发 ChapterPlanner，从 Ledger 实时拼 brief |
| `update_chapter_brief(chapter_number, edits)` | 作者改 brief |
| `write_chapter(chapter_number)` | 触发 Writer 出稿（用最新 brief） |
| `read_chapter(chapter_number)` | 读章节 |
| `review_chapter(chapter_number)` | 触发 Reviewer，得 critique 报告（不改文） |
| `refine_chapter(chapter_number, feedback?)` | 按反馈精修（默认用上次 critique；可传新反馈） |
| `accept_chapter(chapter_number)` | 落盘 + 写 reflexion + 更新 Ledger |
| `verify_chapter(chapter_number)` | 跑硬约束检查（长度/兑现/伏笔） |

## T5. 改前章 (RevisionFlow)
| 工具 | 职责 |
|---|---|
| `propose_revision(chapter_number, instruction)` | LLM 解析 → 结构化变更草案 |
| `analyze_revision_impact(change)` | 涟漪分析：哪些后续章节可能受影响 |
| `apply_revision(change_id)` | 执行变更 |
| `propose_downstream_revisions(change_id)` | 建议哪些后续章节也要改 |
| `review_downstream(chapter_numbers)` | 扫一批章节，标出与新设定冲突的地方 |
| `rollback_revision(change_id)` | 回滚 |

## T6. 账本/放大镜（跨流程通用）
| 工具 | 职责 |
|---|---|
| `list_foreshadowings(filter)` | 含 plant/collect/forgotten |
| `list_debts(filter)` | 含 pending/overdue/fulfilled |
| `get_character_state(name, chapter)` | 某章时角色快照 |
| `get_world_facts()` | 已建立的世界观事实清单 |
| `get_style_profile()` | 本书的口头禅+句长+节奏统计 |
| `get_changelog(filter)` | 变更历史 |
| `get_volume_settlement(volume_number)` | 卷结算报告 |
| `get_reflexion_log(filter)` | 跨章经验日志 |

## T7. 元工具
| 工具 | 职责 |
|---|---|
| `chat_with_architect(message)` | 立项/骨架阶段的对话面（不是 CRUD） |
| `chat_with_director(message, context?)` | 卷级讨论（不是 CRUD） |

---

# Part 5 · 完整流程串联

## 流程 1: 写一本新书

```
[1] ProjectFlow
  作者: "我想写一个 30 章的悬疑短篇"
  → chat_with_architect()
  → propose_project_setup() 草案
  → 作者改 → finalize_project_setup()
  → propose_synopsis / characters / world / volume_breakdown
  → 每段作者 accept_spine_section() 或 regenerate_section()

[2] VolumeFlow (第 1 卷)
  → enter_new_volume(1)
  → VolumeDirector → propose_volume_outline(1)
  → 作者审 → update_volume_outline() 或 accept
  → 进章循环

[3] ChapterFlow (第 N 章)
  → propose_chapter_brief(N)
        ChapterPlanner 从 Ledger 实时取应兑现/回收/角色快照
  → 作者审 brief → update 或 accept
  → write_chapter(N)
        Writer.draft(brief)
  → Sanitizer 自动清洗
  → verify_chapter(N)
        硬约束报告（不自动重写，只标）
  → review_chapter(N)
        Reviewer 软质量批评（不打分，只标问题）
  → 作者看报告，决定:
      - accept_chapter(N)        → 落盘 + 写 reflexion + Ledger 更新
      - refine_chapter(N)        → Writer 按 critique 精修
      - update_chapter_brief()   → 改 brief 后 write_chapter() 重出稿

[4] 卷写完 → settle_volume(1)
  → VolumeDirector 输出本卷复盘 + 推 propose_volume_outline(2)

[5] 全书写完 → settle_volume(last)
  → 最终 reflexion 汇总 + 全书统计报告
```

## 流程 2: 中途改前章（作者发现 ch5 设定不对）

```
[1] propose_revision(5, "把主角职业从厨师改成医生")
  → IntentParser → 结构化变更
  → 落 Changelog (proposal status)

[2] analyze_revision_impact(change)
  → 列出所有提到主角职业的章节（ch7/ch12/ch20...）

[3] propose_downstream_revisions(change_id)
  → 对每个受影响章节，建议改写方案 + 估计改动量

[4] 作者勾选要改的章节（可全选可挑）

[5] apply_revision(change_id)
  → 改 ch5 + 改 spine.characters + 改后续被勾选的章节
  → 每步独立 changelog 条目，便于回滚

[6] review_downstream([7, 12, 20])
  → 跑 Verifier + Reviewer 扫这批章节，标出残留冲突

[7] 作者再次 refine_chapter() 或 accept

可随时 rollback_revision(change_id) — 回滚整个变更链
```

## 流程 3: AI 助手通过 MCP 协作（用户在 Claude Desktop 里）

```
用户: "帮我把第 3 卷大纲做得更紧凑"
Claude:
  → get_volume_progress(3) ← 看当前进度
  → get_volume_outline(3)  ← 拿现有大纲
  → 分析 → propose 一个修改方案给用户看
  → 用户同意 → update_volume_outline(3, edits)

用户: "帮我看看第 17 章哪里写得不好"
Claude:
  → review_chapter(17)
  → 把 critique 报告翻译成自然语言讨论
  → 用户问"那个对话是不是太长了" → Claude 引用具体段落讨论
  → 用户决定改 → refine_chapter(17, "对话部分压缩到 1/3")
```

---

# Part 6 · 体裁/长度去中心化

立项时 `target_length_class` + `genre` 决定一组**默认配置模板**，但模板是参数化的，不是硬编码：

| length_class | volume_count | chapters_per_volume | default_target_words | template_dir |
|---|---|---|---|---|
| short_story | 1 | 5-15 | 1500-3000 | templates/short/ |
| novella | 1-3 | 8-20 | 2000-3500 | templates/medium/ |
| novel | 5-15 | 15-40 | 2000-4000 | templates/long/ |
| webnovel | 20-100+ | 10-30 | 2000-3000 | templates/webnovel/ |

`chapter_type` → `target_words` 倍率：
- setup: 0.8x  
- buildup: 1.0x  
- climax: 1.5x  
- resolution: 1.2x  
- interlude: 0.6x

每个 genre 自带：
- chapter_type 分布建议（悬疑卷里 climax 章更密）
- Reviewer 维度权重（言情侧重情感曲线，悬疑侧重伏笔密度）
- StyleProfile 初始 watchlist（可选，用户自己加）

**不存在 default genre / default template。立项必须显式选。**

---

# Part 7 · 实施路线图（建议顺序）

## Phase 0: 拆迁准备（1-2 天）
- 删 dead code: `import_service` / `narrative_rebuild` / `writer_react`
- 砍 hardcoded 词表: `templates/ai_flavor_blacklist.py` 删除
- 砍硬阈值: `_WORDS_PER_CHAPTER` 改为读 chapter.target_words
- 砍 default genre: 立项必须显式选

## Phase 1: 数据模型升级（2-3 天）
- `ChapterOutline` 加 `target_words` + `chapter_type`
- `Volume` 提升为一等公民
- `Ledger` 统一入口（包装现有 ObligationTracker / KnowledgeGraph）
- `StyleProfile` 新建

## Phase 2: Agent 重组（3-4 天）
- 合并: WorldBuilder + CharacterDesigner → ProjectArchitect
- 合并: QualityReviewer + ConsistencyChecker + StyleKeeper → Reviewer
- 新建: VolumeDirector
- 重写: ChapterPlanner（从 Ledger 实时取，不是 ContinuityService 摘）
- 删: writer_react, dynamic_outline (合并入 VolumeDirector)

## Phase 3: Flow 编排层（2-3 天）
- 新建: ProjectFlow / VolumeFlow / ChapterFlow / RevisionFlow
- 都做成显式状态机，可暂停等作者反馈

## Phase 4: 工具层重组（2 天）
- 按 T1-T7 分组重组 agent_chat 工具
- MCP 工具加 `propose_/accept_/regenerate_` 三段式
- 删自动重写路径

## Phase 5: 测试维度修正（1-2 天）
- 加章节文本质量评估（不是字段格式）
- 加 LLM-as-judge 做样本对比
- 跨体裁回归测试（悬疑/言情/科幻 各跑 3 章）

**总计 11-16 天工作量**。Phase 0-1 是不破不立的基础，Phase 2-3 是核心改造，Phase 4-5 是收尾。

---

# Part 8 · 不打算做的事（明确划界）

为避免 scope creep，明确以下不在本次重构范围：

- ❌ Web UI 重做（保持现有，跟着后端 API 调）
- ❌ 多人协作（单作者 + AI 协作即可）
- ❌ 出版/发布工具链
- ❌ 训练自定义模型
- ❌ 真人配音 / 视频化
- ❌ 评分排行 / 推荐系统

聚焦"高质量长文本生成 + 中途可控修订"这一件事。
