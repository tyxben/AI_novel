# 小说生成质量三层增强（v1.2）

v1.2 在小说创作流程中新增了三个独立的质量增强服务，解决长篇小说生成中最常见的三个问题：
情节重复、角色漂移、章末疲软。

---

## 背景

在 v1.1 及之前的版本中，长篇小说生成存在几个典型的质量问题：

1. **情节重复** — 规划器看不到全书视角，容易在同一场景反复打转（例如连续 5 章都是"矿场整顿"）
2. **角色漂移** — 角色成长没有追踪，可能上章还冷静谋略、下章突然冲动，或者主要角色长期消失
3. **章末疲软** — 章节结尾常常是"回去休息了"这种没有悬念的收束，读者失去追章动力
4. **死人复活** — 前几章已被击杀的角色，后面章节又被当成活人引用（因为规划器只看 `goal` 字段，不看实际剧情）

v1.2 的三层增强围绕这些问题做了系统性改造。

---

## 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│               章节生成流程 (pipeline.generate_chapters)        │
│                                                              │
│   ┌─────────────────────────────┐                           │
│   │ 1. ContinuityService         │ 聚合上章结尾 + 悬念 +      │
│   │                              │ 未解决债务 + 死亡角色      │
│   └─────────────────────────────┘                           │
│                 ↓                                             │
│   ┌─────────────────────────────┐                           │
│   │ 2. GlobalDirector (NEW)      │ 全书视角: 卷位置 / 阶段 /  │
│   │                              │ 活跃弧线 / 重复预警        │
│   └─────────────────────────────┘                           │
│                 ↓                                             │
│   ┌─────────────────────────────┐                           │
│   │ 3. CharacterArcTracker (NEW) │ 角色成长阶段 / 长期缺席    │
│   └─────────────────────────────┘                           │
│                 ↓                                             │
│   ┌─────────────────────────────┐                           │
│   │ Writer.generate_chapter      │ 所有约束拼接进 system      │
│   │                              │ prompt 和 user prompt      │
│   └─────────────────────────────┘                           │
│                 ↓                                             │
│   ┌─────────────────────────────┐                           │
│   │ 4. HookGenerator (NEW)       │ 评分章末，弱结尾 LLM 重写  │
│   └─────────────────────────────┘                           │
│                 ↓                                             │
│   ┌─────────────────────────────┐                           │
│   │ 5. 保存 → 自动生成摘要 → 更新  │                         │
│   │    ArcTracker → 持久化        │                         │
│   └─────────────────────────────┘                           │
└──────────────────────────────────────────────────────────────┘
```

---

## GlobalDirector — 全书状态监控

### 文件位置

`src/novel/services/global_director.py`

### 解决的问题

单章生成时 LLM 只看前一章，不知道"你在卷一第 24/35 章"、"还有 11 章就要收束卷一"。
结果就是节奏失控，该进入高潮的时候还在日常，该收束的时候还在开新线。

### 工作原理

```python
from src.novel.services.global_director import GlobalDirector

director = GlobalDirector(novel_data, outline)
brief = director.analyze(
    chapter_number=24,
    recent_summaries=[
        {"chapter_number": 22, "title": "矿场立威", "actual_summary": "..."},
        {"chapter_number": 23, "title": "矿道夜查", "actual_summary": "..."},
    ],
)

prompt_block = director.format_for_prompt(brief)
```

输出的 prompt 块（注入到 Writer）：

```
## 全局导演视角
- 位置：「边村立旗」第 24/25 章（96.0%）
- 卷内剩余：1 章
- 阶段：卷末过渡
- 导演指引：
  · 卷末过渡：必须收束当前卷的核心冲突，留下进入下一卷的钩子
  · ⚠️ 距离本卷收束仅剩 1 章，必须开始收线
  · ⚠️ 最近 3 章场景集中在「矿」相关，建议切换场景或推进新冲突
```

### 关键能力

- **位置感知**：兼容两种 volume 数据格式（`chapters` 列表 和 `start_chapter`/`end_chapter`）
- **阶段推断**：0-20% 起势 / 20-60% 上升 / 60-85% 高潮 / 85-100% 收束
- **重复检测**：最近 5 章标题有 3 次以上共同字符时，强制要求切换场景
- **卷末倒数**：距离卷末 ≤ 3 章时发出收束预警

### 注入位置

1. **章节生成阶段** — `pipeline.generate_chapters` 循环内，追加到 `state["continuity_brief"]`
2. **大纲规划阶段** — `_fill_placeholder_outline` prompt 中注入 `director_section`

---

## CharacterArcTracker — 角色弧线追踪

### 文件位置

`src/novel/services/character_arc_tracker.py`

### 解决的问题

角色成长没有记录：上一章主角刚经历挫败（应该处于反思期），下一章直接变成意气风发的领袖，
读者会觉得人物塑造前后矛盾。同时，女主/配角长期消失后再突然出现，没有任何铺垫。

### 工作原理

```python
from src.novel.services.character_arc_tracker import CharacterArcTracker

tracker = CharacterArcTracker()

# 每章生成后自动更新
tracker.update_from_chapter(
    chapter_number=16,
    actual_summary="主角在战斗中突然觉醒了体内的力量，明白了真正的战斗之道。",
    characters=[{"name": "主角"}, {"name": "配角A"}],
)

# 生成章节前注入到 prompt
prompt = tracker.format_for_prompt(
    character_names=["主角", "配角A"],
    current_chapter=17,
)
```

输出：

```
## 角色弧线状态
- 主角: 当前处于「觉醒/突破期」（上次出场在第 16 章）
  最近成长：第16章 主角在战斗中突然觉醒了体内的力量
- 配角A: 当前处于「初登场」（已 8 章未出场，需要重新介绍）

要求：本章涉及的角色行为必须与其当前弧线阶段一致，禁止性格漂移。
```

### 成长阶段识别

通过关键词检测从 actual_summary 自动识别：

| 阶段 | 关键词 |
|------|--------|
| `awakening` 觉醒/突破 | 觉醒 / 悟道 / 突破 / 顿悟 / 明白了 |
| `trial` 试炼/挫败 | 试炼 / 考验 / 困境 / 挫败 / 受挫 |
| `bonding` 结盟/情感 | 信任 / 联手 / 结盟 / 共识 / 情愫 / 心动 |
| `conflict` 冲突 | 对立 / 决裂 / 背叛 / 翻脸 / 争执 |
| `transformation` 蜕变 | 蜕变 / 改变 / 重生 / 脱胎换骨 |
| `loss` 失落 | 失去 / 牺牲 / 伤痛 / 陨落 |
| `victory` 胜利 | 胜利 / 成功 / 击败 / 完成 |

### 持久化

状态保存到 `workspace/novels/<novel_id>/novel.json` 的 `character_arc_states` 字段，
项目重启后自动恢复。

---

## HookGenerator — 章末钩子生成

### 文件位置

`src/novel/services/hook_generator.py`

### 解决的问题

LLM 生成的章节经常以"众人各自散去"、"一夜无话"这类平淡收束结尾，
完全没有让读者追下一章的动力。网文最核心的"卡点"反而成了最弱的环节。

### 工作原理

分两步：评分 → 重写

```python
from src.novel.services.hook_generator import HookGenerator

hg = HookGenerator(llm_client=llm)

# 1. 评估当前结尾
result = hg.evaluate(chapter_text)
# {
#   "score": 3,
#   "hook_type": "weak",
#   "issues": ["结尾过于平淡，缺乏悬念"],
#   "needs_improvement": True,
# }

# 2. 如果分数 < 6，调 LLM 重写最后一段
if result["needs_improvement"]:
    new_ending = hg.generate_hook(
        chapter_text=chapter_text,
        chapter_number=24,
        chapter_goal="推进主线冲突",
    )
    # "突然，屋顶传来一声闷响，林辰瞳孔骤缩——"
    
    chapter_text = hg.replace_ending(chapter_text, new_ending)
```

### 评分规则

强钩子模式（score +2）：
- 问句或感叹结尾
- `突然 / 忽然 / 猛然` 句式
- `就在这时 / 与此同时` 打断式
- 省略号悬念
- "消失了 / 不见了 / 断了"等"something gone"模式

弱结尾惩罚（score -3）：
- 休息类：`睡 / 休息 / 休整 / 安歇`
- 总结类：`于是 / 就这样 / 然后`
- 日常类：`吃饭 / 喝酒 / 聊天`

加分：出现 `危机 / 威胁 / 陷阱 / 杀机` 等悬念词（+1）

### 接入位置

`pipeline.generate_chapters` 中，在保存章节前：

```python
hook_gen = HookGenerator(llm_client=create_llm_client(...))
eval_result = hook_gen.evaluate(chapter_text)
if eval_result["needs_improvement"]:
    new_ending = hook_gen.generate_hook(chapter_text, ch_num, goal)
    if new_ending:
        chapter_text = hook_gen.replace_ending(chapter_text, new_ending)
```

---

## 辅助增强

### 1. 自动补全 actual_summary

**问题**：v1.2 之前写的章节没有 `actual_summary` 字段，新机制拿不到准确的历史剧情。

**修复**：`generate_chapters` 启动时扫描所有已写但缺摘要的章节，批量调 LLM 补全：

```python
# pipeline.generate_chapters 启动时自动执行
for ch in outline_chapters:
    if ch.get("actual_summary"):
        continue
    txt = fm.load_chapter_text(novel_id, ch["chapter_number"])
    if txt:
        ch["actual_summary"] = self._generate_actual_summary(txt, ...)
```

### 2. 死亡角色检测

从 actual_summary 用正则识别"处决/斩杀/身亡"等关键词，提取死亡角色名，
注入到 `forbidden_breaks`，要求 Writer 用"余部/残部"形式指代。

主角名不硬编码，而是从 `characters` 列表里 `role` 字段含"主角/protagonist"的自动提取：

```python
protagonist_names = ContinuityService._extract_protagonist_names(characters)
# ["陈风"]  — 根据小说的实际主角自动识别
```

### 3. 章节衔接硬约束

- Writer 的第一场景 system prompt 注入 5 条衔接规则（禁止跳时间/空间/事件）
- 首场景上下文窗口从 4000 字扩大到 6000 字
- 上下文标签从"前文回顾"改为"上章结尾 — 必须从这里接续"
- PlotPlanner 要求第一场景 title/summary 必须体现"承接上章"

### 4. 内容过滤器

`src/novel/agents/writer.py::_sanitize_chapter_text` 自动过滤：
- 系统 UI：`【系统】`、`【检测到...】`、`【主线分支更新】`
- 数值变化：`忠诚度：71→79`、`【兵煞值+8】`
- 保留故事性标记：`【叮！】`（允许列表可配置）

---

## 对比效果

以"被迫无奈当皇帝"小说第 25-27 章为例：

**v1.1 (旧)**：
- 第25章开头：`"矿下先锁死。"林辰转身就走...`（重复第19章结尾，没有真正续写）
- 第26章开头：`"矿下先锁死。"林辰转身就走...`（继续重复同一句话）
- 章末钩子：`矿场恢复了平静，众人各自回营`（极弱）
- 黑风煞（已在第17章死亡）仍被当成活人："黑风煞正带人摸过来"

**v1.2 (新)**：
- 第25章开头：`林辰那句"守村，和夺路，一起做"刚落，北坡外又是一阵急锣...`
- 第25章结尾：`苏晚照脸色骤变，捂着伤口失声道："不对——灵石脉在动！"林辰瞳孔一缩...`
- 第26章开头：`林辰那两个字还没出口，矿洞里那声闷响已经顺着地底滚了出来。轰。`（句子级衔接）
- 第26章结尾：`一道浑身是血的身影跌出林子，朝矿场方向扑来，嘶声喊了半句："别开——"`
- 第27章开头：`"别开——"` 那道浑身是血的身影刚扑出林子...`（无缝衔接到上章结尾）
- 黑风煞正确以"余部/残部"形式提及

---

## 日常使用流程

### 创作一本新小说（零起步）

```bash
# 1. 创建项目（CLI 或 Web UI）
python main.py novel write \
    --genre 玄幻 \
    --theme "少年修炼逆天改命" \
    --target-words 200000

# 2. 规划大纲（10 章一批）
# 通过 Web UI 点击"规划大纲"，系统自动使用三层增强生成不重复的大纲
# 可以在预览界面手动调整每章标题/目标

# 3. 批量生成章节
# 点击"生成章节"，每章会自动:
# - 注入 GlobalDirector 全书视角
# - 注入角色弧线状态
# - 生成后优化章末钩子
# - 死亡角色自动加入禁止列表
# - 生成 actual_summary 供后续规划使用

# 4. 重复 2-3，每 10 章一批，直到完本
```

### 修复已有小说的质量问题

对 v1.2 之前生成的小说，首次运行时系统会自动补全历史章节的 `actual_summary`：

```bash
# 启动生成任务（比如第 20 章）
# 系统会自动检测第 1-19 章是否有 actual_summary，没有就补全
# 这个过程只发生一次，后续章节都是增量
```

如果需要彻底重新规划后续章节：

```bash
# 在 Web UI 点击"规划大纲"，重新规划 20-30 章
# 系统会读取第 1-19 章的 actual_summary，基于真实剧情重新生成大纲
# 不会再出现"死人复活"或"场景重复"的问题
```

---

## 测试覆盖

v1.2 新增了 37 个单元测试，覆盖三个服务模块的所有核心方法：

```bash
python -m pytest tests/novel/services/test_global_director.py -v          # 14 tests
python -m pytest tests/novel/services/test_character_arc_tracker.py -v    # 9 tests
python -m pytest tests/novel/services/test_hook_generator.py -v           # 14 tests
```

全量测试总数从 v1.1 的 3420 增加到 v1.2 的 **3692**（+272 个新测试，包括三层增强 + 防御性测试）。

---

## 后续改进方向

v1.2 的三层增强解决了最严重的问题，但仍有可以继续优化的地方：

1. **读者模型** — 目前没有"读者视角"，不知道一个读者从第 1 章看到现在会有什么期待
2. **伏笔追踪** — 虽然 `foreshadowing_planted/collected` 字段存在，但没有专门的视图帮助作者看"哪些伏笔还没收"
3. **单场景重写** — 目前"反馈重写"是整章重写，如果只有一个场景有问题应该支持只重写那个场景
4. **全局回修** — 写完 50 章后发现前面某个设定有矛盾，目前只能手动修；应该支持基于新发现自动回修早期章节

这些是下一个版本（v1.3）的潜在方向。
