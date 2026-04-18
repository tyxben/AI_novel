# 模块利用率统计 (2026-04-18)

非测试代码中模块被引用次数。`used by N` 是排除自身和 tests/ 后的导入计数。

## Agents (15 个) — 砍 9，留 5

| 模块 | LOC | used by | 处理 |
|---|---|---|---|
| writer.py | 1732 | 6 | 保留（核心） |
| novel_director.py | 1327 | 4 | 拆 → ProjectArchitect + VolumeDirector |
| state_writeback.py | 1009 | 1 | 合并入 ChapterFlow |
| plot_planner.py | 950 | 1 | 重写为 ChapterPlanner |
| consistency_checker.py | 910 | 1 | 合并入 Reviewer |
| feedback_analyzer.py | 710 | 1 | 合并入 Writer.refine() |
| dynamic_outline.py | 525 | 2 | 合并入 VolumeDirector |
| quality_reviewer.py | 487 | 1 | 合并入 Reviewer |
| chapter_critic.py | 343 | 3 | 重命名为 Reviewer，吸收 quality/consistency/style |
| character_designer.py | ? | 1 | 合并入 ProjectArchitect |
| world_builder.py | ? | 1 | 合并入 ProjectArchitect |
| style_keeper.py | ? | 2 | 合并入 Reviewer |
| writer_react.py | ? | 1 | **删**（与 writer.py 双轨） |
| graph.py | — | — | 保留（编排基础设施） |
| state.py | — | — | 保留（schema） |

## Services (29 个) — 砍 11+，留 18

| 模块 | LOC | used by | 处理 |
|---|---|---|---|
| agent_chat.py | 2127 | 1 | 重组工具，删自动 refine 路径 |
| narrative_rebuild.py | 867 | 2 | **删**（与 batch_edit 重叠） |
| continuity_service.py | 810 | 3 | 重构为 BriefAssembler |
| edit_service.py | 737 | 5 | 保留 |
| impact_analyzer.py | 595 | 2 | 保留 |
| foreshadowing_service.py | 538 | 2 | 合并入 LedgerStore |
| volume_settlement.py | 457 | 6 | 升级为 VolumeAnalyzer 一部分 |
| obligation_tracker.py | 450 | 10 | 合并入 LedgerStore |
| debt_extractor.py | 449 | 2 | 合并入 LedgerStore |
| health_service.py | 429 | 1 | 拆：保留事实统计 → VolumeAnalyzer，**删合成评分** |
| **import_service.py** | **415** | **0** | **删（dead code）** |
| changelog_manager.py | ? | 1 | 保留 |
| chapter_verifier.py | ? | 3 | 保留，移除 AI 词检查 |
| character_arc_tracker.py | ? | 1 | 合并入 LedgerStore |
| character_service.py | ? | 1 | 合并入 LedgerStore |
| consistency_service.py | ? | 1 | 删（与 BriefAssembler+Verifier 重叠） |
| dedup_dialogue.py | ? | 2 | 合并入 Verifier |
| entity_extractor.py | ? | 2 | 合并入 LedgerStore |
| entity_service.py | ? | 2 | 合并入 LedgerStore |
| global_director.py | ? | 2 | 合并入 VolumeDirector |
| hook_generator.py | ? | 1 | 合并入 ChapterPlanner |
| intent_parser.py | ? | 1 | 保留 |
| milestone_tracker.py | ? | 3 | 合并入 LedgerStore |
| proofreader.py | ? | 2 | 改为 Reviewer 的一个维度 |
| refine_loop.py | ? | 1 | 升级为 ChapterFlow 一部分 |
| reflexion_memory.py | ? | 1 | 保留 |
| setting_impact_analyzer.py | ? | 1 | 合并入 ImpactAnalyzer |
| style_bible_generator.py | ? | 3 | 评估后定，疑似与 StyleProfile 重叠 |
| world_service.py | ? | 1 | 合并入 LedgerStore |

## Tools (10 个) — 大部分整合到 Reviewer

| 模块 | used by | 处理 |
|---|---|---|
| chapter_digest.py | 3 | 保留（摘要工具） |
| style_analysis_tool.py | 3 | 升级为 StyleProfileService |
| quality_check_tool.py | 2 | 删（合并入 Reviewer） |
| bm25_retriever.py | 1 | 保留（fallback 检索） |
| brief_validator.py | 1 | 合并入 ChapterPlanner |
| character_tool.py | 1 | 合并入 LedgerStore |
| consistency_tool.py | 1 | 删（合并入 Verifier） |
| foreshadowing_tool.py | 1 | 删（合并入 LedgerStore） |
| react_writer_tools.py | 1 | 删（writer_react 一并删） |
| world_setting_tool.py | 1 | 合并入 LedgerStore |

## 总账

| 类别 | 现状 | 目标 | 减少 |
|---|---|---|---|
| Agents | 15 文件 | 5 + 基础设施 | -10 |
| Services | 29 | 18 | -11 |
| Tools | 10 | 3-4 | -6+ |
| **总文件** | **54** | **~26** | **-28 (-52%)** |
| 估计 LOC | ~16,000 | ~9,000 | -7,000 |

## 0 引用 / 极低使用模块（红灯）

| 模块 | LOC | 引用 |
|---|---|---|
| **import_service.py** | **415** | **0** ← 显式 dead |
| writer_react.py | ? | 1 ← 与 writer 双轨 |
| state_writeback.py | 1009 | 1 ← 合并入 flow |
| feedback_analyzer.py | 710 | 1 ← 合并入 Writer |
| consistency_service.py | ? | 1 ← 重叠 |
| narrative_rebuild.py | 867 | 2 ← 重叠 |
