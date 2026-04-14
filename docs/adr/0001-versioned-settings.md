# ADR 0001: 版本化设定（Versioned Settings）

- **状态**: Accepted（随 Wave 1/2 落地）
- **日期**: 2026-03-24（创建）/ 2026-04-15（文档化）
- **相关 spec**: `specs/novel-smart-editor/`

## 上下文

长篇小说在连载中角色会成长、世界观会扩充、章节大纲会调整。早期
`src/novel/` 用单行原地更新（把 `characters[i]["age"]` 直接覆盖），这
样做的问题：

1. 已生成章节引用的是"当时的"角色版本，之后改年龄/性格会让旧章
   出现逻辑矛盾。
2. 无法在同一项目里对"第 5 章前的张三"与"第 5 章后的张三"分别引用。
3. 读者反馈 / 自动化影响分析需要知道变更的生效章节。

## 决策

在所有可编辑实体上引入三个版本字段：

| 字段 | 类型 | 语义 |
|------|------|------|
| `effective_from_chapter` | `int \| None` | 该版本从第几章起生效（闭）。`None` = 全时有效 |
| `deprecated_at_chapter` | `int \| None` | 从第几章起失效（开）。`None` = 永久有效 |
| `version` | `int`（默认 1） | 单调递增版本号，tie-breaker |

支持实体：`Character` / `ChapterOutline` / `WorldSetting`。字段已加入
对应 Pydantic 模型并有默认值 —— 旧项目加载时自动补齐，保证**向后
兼容**。

## 实施

- `src/novel/editors/base.py::_add_version_fields()` — 编辑器写入时
  自动填字段。
- `src/novel/editors/base.py::_deprecate_old_version()` — 软删除 / 替
  换旧版时设置 `deprecated_at_chapter`。
- `src/novel/utils/setting_version.py` — 查询辅助：
  - `is_effective_at(entry, chapter_num)`
  - `get_setting_at_chapter(entries, entity_id, chapter_num)`
  - `list_settings_at_chapter(entries, chapter_num)`
- `scripts/migrate_novel_v1_to_v2.py` — 一次性迁移老项目。
- 编辑链路：`NovelEditService.edit()` → `Editor.apply()` → 自动维护字段。

## 当前数据模型的折中

"单行原地更新"的语义至今未被多版本并存取代：编辑器修改已有角色时
直接 merge 字段（`_update_character`），而非追加新版本行。原因：

- 已上线 pipeline 代码（Writer/PlotPlanner/ContinuityService）只读单
  行，引入多版本行会连锁重写多个组件。
- 现阶段创作流程中版本回溯的主用户是**影响分析 + 变更历史 + 回滚**，
  已通过 `changelogs/*.json` 提供精确快照，不依赖多行。

因此 `setting_version.py` 是**预留 API**，在未来 Writer/PlotPlanner 明
确需要按章取不同版本时再接入（spec Task 18.2）。

## 查询优先级

当 `get_setting_at_chapter` 遇到多条匹配记录（同 entity_id、同时满足
章节区间）：

1. 优先 `effective_from_chapter` 大的（更近一版）
2. 再按 `version` 大的

这让数据异常（重叠区间）下仍能稳定选出"最新"版本。

## 替代方案（已否决）

- **整个 novel.json 全版本快照**：每次编辑落一个 `novel_vN.json`。体
  积爆炸，且大部分变更只动一个字段，全文快照信噪比极低。
- **数据库替代 JSON**：SQLite 等有成熟版本表模式，但会打断"小说项目
  就是一个目录"的心智模型，部署与分享成本陡增。
- **Git 仓库作为版本源**：已有独立规划（见 memory
  `project_novel_git_versioning.md`），与本决策并行推进，彼此不冲突。
