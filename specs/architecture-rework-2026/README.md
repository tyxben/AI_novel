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

- **Phase 0** 拆迁准备（删 dead code + 砍硬阈值/词表/default genre）
- **Phase 1** 数据模型升级（Volume 一等公民 + Ledger 统一 + StyleProfile）
- **Phase 2** Agent 重组（15 → 5）
- **Phase 3** Flow 编排层（ProjectFlow / VolumeFlow / ChapterFlow / RevisionFlow）
- **Phase 4** 工具层重组（按工作流分组）
- **Phase 5** 测试维度修正（加文本质量评估 + LLM-as-judge + 跨体裁回归）
