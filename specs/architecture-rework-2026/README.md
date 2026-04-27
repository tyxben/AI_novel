# 架构重构 2026

针对 AI 小说写作工具的端到端审视与重构方案。

## 文档索引

| 文档 | 内容 |
|---|---|
| [AUDIT.md](AUDIT.md) | 审视报告：现状诊断、流程对标、8 条理念错位、通用性陷阱 |
| [DESIGN.md](DESIGN.md) | 新架构设计：数据模型、5 Agent 体系、Service 分层、工具层、流程串联、实施路线图 |
| [MODULE_USAGE.md](MODULE_USAGE.md) | 当前模块利用率统计 + 砍/留/合并清单（54→26 文件，-52%） |

## 核心结论

> 方向只对了 30%。底层"记账"是真资产，上层踩在三个错误的产品哲学上：用工程指标替代审美判断 / Agent 数量替代 Agent 协作 / 默认体裁是网文爽文。
> 当前架构最该做的不是再加一个 Agent，而是**砍掉一半 Agent 和所有硬阈值**，把腾出来的空间还给作者。

## 7 条不可违反的新原则

1. propose 不入库
2. 零自动重写
3. 零全局硬阈值
4. 零默认体裁
5. 卷为一等公民
6. 写作时账本是实时的
7. 删而不藏

## 实施路线（11-16 天）

> **状态**：Phase 0-5 已于 2026-04-21 全部完工。下方是原始规划，配合
> 各 Phase 实际交付备注阅读（实际交付以 PHASE4.md / PHASE5.md / 仓库
> `src/novel/` 现状为准）。

- **Phase 0** 拆迁准备（删 dead code + 砍硬阈值/词表/default genre）✅
- **Phase 1** 数据模型升级（Volume 一等公民 + Ledger 统一 + StyleProfile）✅
- **Phase 2** Agent 重组（**9 → 5**：实际终态 ProjectArchitect / VolumeDirector / ChapterPlanner / Writer / Reviewer）✅
- **Phase 3** Flow 编排层（原计划独立 ProjectFlow / VolumeFlow / ChapterFlow / RevisionFlow 类；**实际并入 `pipeline.py` + `agents/graph.py`**，未拆独立 Flow 类，DESIGN.md 仅作设计参考）
- **Phase 4** 工具层重组 — **实际交付：三段式工具层**（propose / accept / regenerate × 9 实体），见 `PHASE4.md` ✅
- **Phase 5** 测试维度修正（7 维质量评估 + LLM-as-judge 异源 + A/B 双向 de-bias），见 `PHASE5.md` ✅
- **后续修复（v2.2）** Writer 上章原文通道修复 — P0 (`ffffda2`) + C3 (`15095b3`)，新增 `services/prev_tail_summarizer.py`，pipeline 三处生成通道全经摘要
