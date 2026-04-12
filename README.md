# 🎬 AI 创意工坊

> AI 驱动的一站式内容创作平台 — 短视频自动制作 + AI 长篇小说创作，支持 CLI / Next.js Web UI / MCP 三种使用方式。

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-v1.3.0-orange)](https://github.com/tyxben/AI_novel/releases/tag/v1.3.0)

---

## 功能亮点

### 短视频制作
- **三种生成模式** — 经典流水线 / Agent 智能质控 / AI 导演（灵感一键出片）
- **AI 导演模式** `NEW` — 输入一句灵感，AI 自动生成脚本 → 分镜 → 画面 → 配音 → 成片
- **多 LLM 后端** — Gemini（免费）/ DeepSeek / OpenAI / Ollama（本地离线），自动检测可用 Key
- **多图片生成后端** — SiliconFlow（免费）/ 阿里云万相 / Together.ai / 本地 Stable Diffusion
- **AI 视频片段生成** — 可灵 Kling / 即梦 Seedance / MiniMax 海螺 / OpenAI Sora
- **Agent 智能模式** — LangGraph 5 Agent 编排（导演/内容分析/美术总监/配音导演/剪辑师），自动质量评估与重试
- **省钱模式** — 规则替代 LLM，跳过质量检查，成本降低约 40%

### AI 长篇小说（核心模块）

> 目前已实测生成 **50 万字级**长篇（200 章 × 6 卷），实际产出 14 万字 / 32 章持续推进中。

**v1.3 叙事弧线控制系统** `NEW`
- **里程碑自动生成** `NEW v1.3` — 进入新卷时 LLM 自动生成 3-5 个叙事里程碑，无需手动配置
- **里程碑强制控制** `NEW v1.3` — 逾期里程碑自动注入 PlotPlanner + Writer 约束，不可忽略，确保主线推进
- **陈旧大纲检测** `NEW v1.3` — 自动识别引用过时章节号 / 前章偏离的大纲，触发 LLM 重新规划
- **风格圣经 (StyleBible)** `NEW v1.3` — 项目专属风格锚定：量化指标 + 范例段落 + 反模式，新旧项目均自动生成
- **StyleKeeper 风格门禁** `NEW v1.3` — 每章零 LLM 成本量化检查（句长/对话比/感官密度），偏离时触发重写
- **卷进度预算** `NEW v1.3` — MilestoneTracker 追踪卷内完成度，VolumeSettlement 卷末收束 + 逾期里程碑自动继承

**v1.2 全书状态监控**
- **GlobalDirector** — 持续监控卷进度/阶段/活跃弧线，自动预警场景重复并强制切换
- **CharacterArcTracker** — 自动识别角色成长阶段，约束行为与成长一致，长期未出场自动预警
- **HookGenerator** — 评分弱结尾并 LLM 重写为强悬念（问句/突发/打断/省略）
- **死亡角色检测** — 自动识别已死亡角色，禁止作为活人出现
- **章节衔接硬约束** — 首场景强制注入衔接规则，禁止跳时间/空间/事件
- **内容过滤器** — 自动过滤系统 UI 泄漏（【检测到】/忠诚度+8）

**9 Agent 协作创作**
- **NovelDirector** 总导演 — 三层大纲（幕/卷/章） + 超长篇分卷按需生成
- **WorldBuilder** 世界观 + **CharacterDesigner** 角色设计 — 自动生成力量体系/社会结构/角色档案/关系网
- **PlotPlanner** 情节规划 — 场景分解 + 节奏设计 + 里程碑/债务/弧线约束注入
- **Writer** 写手 — 2000-3000 字/章，支持 one-shot 和 ReAct 双模式，反 AI 味指令
- **ConsistencyChecker** — Chroma 向量语义检查（每章）+ LLM 深度检查（每9章）
- **StyleKeeper** + **QualityReviewer** — 风格门禁 + 质量评审，自动重写不合格章节
- **FeedbackAnalyzer** — 读者反馈影响范围分析 + 逐章重写

**叙事引擎**
- **ContinuityService** — 每章写前聚合上下文（角色状态/叙事债务/弧线/伏笔/禁止断裂项）
- **ObligationTracker** — 未解决线索追踪 + 紧急度自动升级 + 卷末强制收束
- **向量语义一致性** — Chroma 向量检索，自动检测角色复活/失踪/事件矛盾
- **Agent Chat 会话记忆** — 自动恢复对话历史 + 工作记忆注入
- **ReAct 推理 + Prompt Registry** — Writer 工具链推理 + DB 管理提示词版本
- **两段式编排** — dynamic_outline 写前修订 + state_writeback 写后回写
- **LLM 分阶段配置** — 大纲用 GPT-4、写作用 DeepSeek，按阶段选配最优模型
- **读者反馈系统** — 分析反馈 → 影响范围 → 自动重写受影响章节
- **风格预设** — 玄幻爽文 / 都市 / 武侠 / 仙侠 / 文学 / 轻小说 6 大类

### 平台能力
- **Web UI** — Next.js + FastAPI 创作平台（短视频 / AI 小说 / 设置），异步任务队列
- **CLI 命令行** — Click 驱动的完整 CLI，适合批量处理和脚本集成
- **MCP Server** — FastMCP 协议，可被 Claude Code 等 AI 助手直接调用
- **免费 TTS 配音** — 微软 edge-tts 高质量语音合成 + SRT 字幕自动生成
- **H.265 编码** — 相比 H.264 体积减少约一半，画质不变
- **Ken Burns 特效** — 图片自动缩放平移，告别静态幻灯片感
- **断点续传** — 中断后从上次进度继续，不浪费已完成的工作
- **桌面应用打包** — 支持 PyInstaller 打包为独立可执行文件

---

## 三种视频制作模式

| 对比项 | 经典模式 | Agent 模式 | 导演模式 |
|--------|---------|-----------|---------|
| **输入** | 小说文本文件 | 小说文本文件 | 一句灵感/主题 |
| **流程** | 固定 5 阶段流水线 | 5 Agent 智能编排 | AI 自动编剧 + 制片 |
| **质量控制** | 无 | GPT-4V/Gemini 评分 + 自动重试 | AI 自动决策 |
| **适用场景** | 快速量产 | 精品内容 | 零素材创作 |
| **CLI** | `python main.py run novel.txt` | `--mode agent` | `python main.py create-video "灵感"` |

## 两种画面模式

本项目支持两种画面生成模式，按需选择：

| 对比项 | 静态图 + Ken Burns | AI 视频片段 |
|--------|-------------------|------------|
| **画面效果** | 图片缩放/平移动画 | AI 生成的真实动态视频 |
| **费用** | 免费（仅需图片生成） | 付费（视频 API 按次计费） |
| **生成速度** | 快（秒级合成） | 较慢（每段需等待 1-3 分钟） |
| **适用场景** | 日常量产、低成本起步 | 精品内容、高质量要求 |
| **配置方式** | 默认模式，无需额外配置 | 在 `config.yaml` 中启用 `videogen` 段 |
| **画面一致性** | 高（基于同一张图片） | 中等（AI 生成有随机性） |

两种模式可在配置文件中一键切换。未配置 `videogen` 时默认使用免费的静态图模式。

---

## AI 导演模式

v0.9.0 新增，从一句灵感出发，AI 自动完成编剧 + 制片全流程：

```bash
# CLI
python main.py create-video "一个程序员在深夜发现自己写的AI开始有了自我意识"

# Web UI — 打开 http://localhost:3000 切换到「导演模式」Tab 输入灵感即可
```

**流程**: 灵感 → IdeaPlanner(概念) → ScriptPlanner(分段脚本) → AssetStrategy(素材策略) → 图片/视频生成 → TTS → 合成

---

## Agent 智能模式

基于 LangGraph 的多 Agent 编排系统，在经典流水线基础上增加智能决策层：

### 5 个专职 Agent

| Agent | 职责 | 关键能力 |
|-------|------|---------|
| **Director** 导演 | 任务分析与成本估算 | 纯逻辑，无 LLM 调用 |
| **ContentAnalyzer** 内容分析 | 题材分类、角色提取、风格推荐 | 武侠→水墨、都市→写实、玄幻→动漫 |
| **ArtDirector** 美术总监 | 图片生成 + 质量闭环 | GPT-4V/Gemini Vision 评分，不达标自动重试 |
| **VoiceDirector** 配音导演 | 情感分析 + TTS 调参 | 紧张→语速+10%，悲伤→语速-15% |
| **Editor** 剪辑师 | FFmpeg 视频合成 | 收集所有资产，输出最终视频 |

### 使用方式

```bash
# CLI
python main.py run input/novel.txt --mode agent
python main.py run input/novel.txt --mode agent --budget-mode
python main.py run input/novel.txt --mode agent --quality-threshold 7.0

# Web UI
# 在 Web UI 中选择"Agent模式（智能质控）"即可
```

### 省钱模式 vs 标准模式

| 对比项 | 标准模式 | 省钱模式 |
|--------|---------|---------|
| 题材分类 | LLM 智能分析 | 正则关键词匹配 |
| 角色提取 | LLM 提取 | 正则模式匹配 |
| 图片质量检查 | GPT-4V/Gemini Vision | 跳过 |
| 情感分析 | LLM 分析 | 正则规则 |
| 成本（10段） | ~¥1.0 | ~¥0.6 |

---

## AI 长篇小说创作

> 这是项目投入最多的核心模块。目标是让 AI 全自动写出**结构完整、主线不散、风格统一**的 10-50 万字长篇小说。
>
> 已实测：50 万字 / 200 章 / 6 卷的玄幻长篇，当前产出 14 万字 / 32 章持续推进中。

### 解决的核心难题

AI 写长篇小说面临的最大挑战不是"写不出来"，而是写到中后期会**主线散漫、角色失忆、风格漂移、伏笔丢失**。本模块通过多层控制系统解决这些问题：

| 问题 | 解决方案 | 模块 |
|------|---------|------|
| 主线散漫，写到后面忘了核心冲突 | 卷级里程碑 + 逾期强制推进 | MilestoneTracker + 强制约束注入 |
| 角色前后矛盾（死人复活、性格突变） | 向量语义一致性检查 + 角色状态快照 | ConsistencyChecker + StructuredDB |
| 风格忽高忽低，越写越像 AI | 量化风格门禁 + 项目专属风格圣经 | StyleKeeper + StyleBible |
| 伏笔埋了不收，承诺了不兑现 | 叙事债务追踪 + 紧急度自动升级 | ObligationTracker |
| 大纲越写越旧，引用过时章节 | 陈旧大纲检测 + 自动重新规划 | _is_stale_outline |
| 卷末收不住，线索悬空 | 卷末收束模式 + 里程碑继承 | VolumeSettlement |
| 章与章之间断裂跳跃 | 连续性摘要 + 首场景衔接硬约束 | ContinuityService |

### 9 个专职 Agent

| Agent | 职责 | 关键能力 |
|-------|------|---------|
| **NovelDirector** 总导演 | 三层大纲 + 里程碑生成 | 题材→模板映射，超长篇分卷按需生成，卷级里程碑自动创建 |
| **WorldBuilder** 世界观构建 | 时代/地域/力量体系设定 | 自动生成专有名词和世界规则 |
| **CharacterDesigner** 角色设计 | 角色档案 + 关系网 | 性格标签、说话风格、成长弧线 |
| **PlotPlanner** 情节规划 | 场景分解 + 节奏设计 | 张力曲线 + 里程碑/债务/弧线约束注入 |
| **Writer** 写手 | 逐场景生成正文 | 2000-3000 字/章，one-shot / ReAct 双模式，反 AI 味指令 |
| **ConsistencyChecker** 一致性检查 | 矛盾检测 | Chroma 向量检查（每章） + LLM 深度检查（每9章） |
| **StyleKeeper** 风格守护 | 风格门禁 | 零 LLM 成本量化检查 + StyleBible 风格圣经对标 |
| **QualityReviewer** 质量评审 | 综合质量判断 | 规则硬指标 + LLM 打分，不合格自动重写 |
| **FeedbackAnalyzer** 反馈分析 | 读者反馈处理 | 影响范围分析 + 逐章重写指令 |

### 创作流程

```
输入(题材/主题/字数)
  ↓
┌─────────── 初始化阶段 ───────────────────┐
│ NovelDirector → 三层大纲(幕/卷/章)       │
│ WorldBuilder  → 世界观设定               │
│ CharacterDesigner → 角色档案 + 关系网    │
│ StyleBibleGenerator → 风格圣经           │
└──────────────────────────────────────────┘
  ↓
┌─────────── 逐章生成循环 ─────────────────┐
│                                          │
│  ┌─ 写前准备 ──────────────────────────┐ │
│  │ 陈旧大纲检测 → 重新规划(如需)       │ │
│  │ ContinuityService → 连续性摘要      │ │
│  │ MilestoneTracker → 卷进度预算       │ │
│  │ ObligationTracker → 叙事债务摘要    │ │
│  │ GlobalDirector → 全书节奏指导       │ │
│  │ 里程碑强制约束(如逾期) → 注入       │ │
│  └─────────────────────────────────────┘ │
│              ↓                            │
│  PlotPlanner → 场景分解(含约束)          │
│              ↓                            │
│  Writer → 正文生成(2000-3000字)          │
│              ↓                            │
│  ┌─ 质量检查(并行) ───────────────────┐  │
│  │ ConsistencyChecker (向量一致性)     │  │
│  │ StyleKeeper (风格门禁)             │  │
│  └────────────────────────────────────┘  │
│              ↓                            │
│  QualityReviewer → 综合评审              │
│      ↓ 不合格 → Writer 重写(最多3次)     │
│      ↓ 合格                              │
│  ┌─ 写后回写 ──────────────────────────┐ │
│  │ 角色状态快照 → StructuredDB         │ │
│  │ 章节摘要 → Chroma 向量库            │ │
│  │ 里程碑完成检查 → 标记完成/逾期      │ │
│  │ 叙事债务提取 → ObligationTracker    │ │
│  └─────────────────────────────────────┘ │
│                                          │
│  [卷末] VolumeSettlement → 收束 + 继承   │
│  [新卷] 自动生成新卷大纲 + 里程碑        │
└──────────────────────────────────────────┘
  ↓
完整小说(10-50万字)
```

### 叙事控制系统 (v1.3)

**卷进度预算** — 确保每卷的核心事件按时完成：

```
进入新卷 → LLM 自动生成 3-5 个里程碑
    ↓
每章生成后 → 关键词/LLM 验证里程碑是否完成
    ↓
进度健康度: on_track / behind_schedule / critical
    ↓ critical
强制约束注入 PlotPlanner + Writer → 必须推进逾期里程碑
    ↓
卷末收束 → 未完成的 critical 里程碑自动继承到下一卷
```

**风格圣经 (StyleBible)** — 防止风格漂移：

| 组成 | 说明 |
|------|------|
| quantitative_targets | 句长/对话比/感官密度/感叹号比的 [min, max] 区间 |
| voice_description | 50 字的目标语音描述 |
| exemplar_paragraphs | 2-5 段理想范文 |
| anti_patterns | 禁用的 AI 味表达列表 |
| volume_overrides | 可选的分卷风格微调 |

新项目由 LLM 生成，旧项目从已有章节纯文本分析自动迁移。

### 叙事状态管理

每章生成前，**ContinuityService** 自动聚合以下来源生成写前约束：

| 数据源 | 注入内容 |
|--------|---------|
| 上章钩子 | 必须承接的悬念、约定、行动 |
| 叙事债务 (ObligationTracker) | 未了结线索 + 紧急度 |
| 角色状态 (StructuredDB) | 各角色当前位置、状态、目标 |
| 故事弧线 (StoryUnit) | 当前弧线阶段和剩余章数 |
| 卷进度预算 (MilestoneTracker) | 里程碑完成度 + 健康状态 |
| 风格圣经 (StyleBible) | 量化风格目标 + 分卷覆盖 |
| 章节任务书 (chapter_brief) | 本章主冲突、兑现、伏笔 |
| 全书导演指导 (GlobalDirector) | 节奏预警 + 场景切换要求 |

每章生成后，自动提取角色快照、索引章节摘要到向量库、检查里程碑完成度，形成闭环。

### 省 Token 策略

长篇小说 LLM 调用量大，系统在多处优化成本：

| 策略 | 节省方式 |
|------|---------|
| 向量一致性检查（每章） | Chroma 语义检索 + 规则矛盾检测，零 LLM |
| LLM 深度一致性（每9章） | 事实提取 + 三层矛盾检测 + LLM 裁决 |
| StyleKeeper 风格门禁 | 纯文本量化分析，零 LLM |
| LLM 打分（每5章 + 末章） | budget_mode 下跳过中间章节 |
| 章节摘要压缩 | ChapterDigest 规则压缩 ~500 字后再送 LLM |
| 里程碑验证 | 优先关键词匹配（免费），仅 fallback 到 LLM |
| 超长篇分卷大纲 | 只生成当前卷详细大纲，后续卷按需扩展 |

### 使用方式

**Web UI（推荐）：**

```bash
cd frontend && npm run dev    # Next.js 前端 (port 3000)
python -m src.api.app         # FastAPI 后端 (port 8000)
# 打开 http://localhost:3000 → 切换到「AI 小说」Tab
# 1. 填写主题/灵感 → 点击「创建项目」
# 2. 选择已创建的项目 → 点击「继续写作」
# 3. 在右侧查看大纲/角色/世界观/章节内容
# 4. 可应用读者反馈、导出 TXT、一键发布到七猫
```

**CLI 方式：**

```bash
# 创建小说项目 + 生成前10章
python main.py novel write --genre 玄幻 --theme "穿越者统一修仙界" --target-words 100000

# 继续生成（断点续传）
python main.py novel resume workspace/novels/novel_xxx

# 查看项目状态
python main.py novel status workspace/novels/novel_xxx

# 导出为 TXT
python main.py novel export workspace/novels/novel_xxx
```

**Python API：**

```python
from src.novel.pipeline import NovelPipeline

pipe = NovelPipeline(workspace='workspace')

# 1. 创建项目（生成大纲 + 世界观 + 角色 + 风格圣经）
result = pipe.create_novel(
    genre='玄幻',
    theme='穿越者统一修仙界，地盘越大能力越强',
    target_words=500000,  # 50万字长篇
)

# 2. 生成章节（支持分批，自动断点续传）
pipe.generate_chapters(
    f"workspace/novels/{result['novel_id']}",
    start_chapter=1,
    end_chapter=30,     # 先写30章
    budget_mode=True,   # 省钱模式：跳过中间章节的 LLM 打分
)

# 3. 应用读者反馈（可选）
pipe.apply_feedback(
    project_path=f"workspace/novels/{result['novel_id']}",
    feedback_text="第5章主角性格突然变了，不符合前面的设定",
    chapter_number=5,
    dry_run=True,  # 先分析不修改
)

# 4. 查看进度
pipe.get_status(f"workspace/novels/{result['novel_id']}")
```

**MCP Server（AI 助手调用）：**

```bash
# 启动 MCP Server
python mcp_server.py

# Claude Code / AI IDE 可直接调用:
# novel_create, novel_generate_chapters, novel_get_status,
# novel_read_chapter, novel_apply_feedback, novel_export
```

### 风格预设

支持多种小说风格预设，每种预设包含 system prompt、量化约束和 few-shot 示例：

| 风格 | 预设名 | 适用题材 |
|------|--------|---------|
| 玄幻爽文 | `webnovel.xuanhuan` | 玄幻、修仙 |
| 都市爽文 | `webnovel.shuangwen` | 都市、系统流 |
| 古典武侠 | `wuxia.classical` | 武侠 |
| 现代仙侠 | `wuxia.modern` | 仙侠 |
| 现实主义 | `literary.realism` | 群像、悬疑、科幻 |
| 校园轻小说 | `light_novel.campus` | 轻小说 |

### 项目文件结构

```
workspace/novels/novel_xxx/
├── novel.json          # 项目元数据（大纲/角色/世界观/里程碑/风格圣经）
├── checkpoint.json     # 运行时状态（断点续传）
├── chapters/
│   ├── chapter_001.txt  # 章节正文
│   ├── chapter_001.json # 章节元数据（摘要/质量分/角色）
│   └── ...
├── memory/             # NovelMemory（SQLite + Chroma 向量库）
└── exports/            # 导出文件（TXT/EPUB）
```

---

## 快速开始

### 环境要求

- **Python 3.10+**
- **FFmpeg** — 视频合成必需

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows (scoop)
scoop install ffmpeg
```

### 安装

```bash
git clone https://github.com/tyxben/AI_novel.git
cd AI_novel

# 推荐：Web UI + 云端生图 + Gemini LLM（免费组合）
pip install -e '.[web,cloud-image,gemini]'
```

<details>
<summary>更多安装选项</summary>

```bash
pip install -e .                # 基础依赖（CLI + TTS）
pip install -e '.[gpu]'        # + 本地 Stable Diffusion（需 GPU）
pip install -e '.[llm]'        # + OpenAI / DeepSeek
pip install -e '.[gemini]'     # + Google Gemini
pip install -e '.[ollama]'     # + Ollama 本地 LLM
pip install -e '.[cloud-image]' # + 云端生图（SiliconFlow / 阿里云）
pip install -e '.[cloud-video]' # + AI 视频生成（可灵 / 即梦 / MiniMax）
pip install -e '.[agent]'     # + LangGraph Agent 智能模式
pip install -e '.[agent-gemini]' # + Agent + Gemini LLM
pip install -e '.[web]'        # + FastAPI Web 后端
pip install -e '.[all]'        # 全部安装
```

</details>

### 启动 Web UI

```bash
# 终端 1：启动 FastAPI 后端
python -m src.api.app         # http://localhost:8000

# 终端 2：启动 Next.js 前端
cd frontend && npm install && npm run dev   # http://localhost:3000
```

打开浏览器访问 `http://localhost:3000` 即可使用。

### CLI 方式

```bash
# 全流程：小说 → 短视频
python main.py run input/novel.txt

# 断点续传
python main.py run input/novel.txt --resume

# 自定义配置
python main.py run input/novel.txt --config my_config.yaml

# 仅文本分段（预览效果）
python main.py segment input/novel.txt

# 查看处理进度
python main.py status workspace/novel/

# Agent 智能模式
python main.py run input/novel.txt --mode agent

# Agent + 省钱模式
python main.py run input/novel.txt --mode agent --budget-mode

# 查看决策日志
python main.py status workspace/novel/ --decisions
```

---

## 配置说明

全局配置文件为 `config.yaml`，可通过 `--config` 参数指定自定义配置文件。

### LLM 配置

```yaml
llm:
  provider: auto  # auto | openai | deepseek | gemini | ollama
  # model: gemini-2.0-flash-lite  # 各后端有各自默认模型
```

`auto` 模式按以下优先级自动检测：`GEMINI_API_KEY` → `DEEPSEEK_API_KEY` → `OPENAI_API_KEY` → Ollama 本地服务。

### 图片生成配置

```yaml
imagegen:
  backend: siliconflow  # siliconflow | dashscope | together | diffusers
  model: black-forest-labs/FLUX.1-schnell
  width: 1024
  height: 1792  # 竖屏 9:16
```

| 后端 | 费用 | 速度 | 模型 | 需要 |
|------|------|------|------|------|
| **siliconflow** | 免费 | ~4s/张 | FLUX.1-schnell | `SILICONFLOW_API_KEY` |
| **dashscope** | 新用户 100 张免费 | ~5s/张 | 万相 wan2.6-t2i | `DASHSCOPE_API_KEY` |
| **together** | 需绑卡 | ~3s/张 | FLUX.1-schnell | `TOGETHER_API_KEY` |
| **diffusers** | 免费（本地） | ~30s/张 | Counterfeit-V2.5 等 | GPU + torch |

### 视频生成配置（可选）

不配置此项则使用默认的静态图 + Ken Burns 模式。启用 AI 视频片段需取消注释并填写：

```yaml
videogen:
  backend: kling        # kling | seedance | minimax | sora
  duration: 5           # 视频时长（秒）
  aspect_ratio: "9:16"  # 竖屏
  mode: std             # std | pro（仅 kling）
  use_image_as_first_frame: true  # 用生成的图片作为视频首帧
  poll_interval: 10     # 轮询间隔（秒）
  poll_timeout: 300     # 轮询超时（秒）
```

详细的视频生成 API 对比见 `docs/videogen-research.md`

### 环境变量（API Key）

根据使用的服务设置对应环境变量：

```bash
# ---- LLM（至少设一个，用于智能分段和 Prompt 生成）----
export GEMINI_API_KEY=xxx         # Google Gemini（免费）
export DEEPSEEK_API_KEY=xxx       # DeepSeek
export OPENAI_API_KEY=xxx         # OpenAI GPT

# ---- 图片生成（至少设一个）----
export SILICONFLOW_API_KEY=xxx    # 硅基流动（免费）
export DASHSCOPE_API_KEY=xxx      # 阿里云百炼万相
export TOGETHER_API_KEY=xxx       # Together.ai

# ---- AI 视频生成（可选）----
export KLING_API_KEY=xxx          # 可灵 Kling
export SEEDANCE_API_KEY=xxx       # 即梦 Seedance（火山方舟）
export MINIMAX_API_KEY=xxx        # MiniMax 海螺
export OPENAI_API_KEY=xxx         # OpenAI Sora（与 LLM 共用）
```

也支持在项目根目录创建 `.env` 文件配置环境变量。

---

## 项目架构

### 目录结构

```
AI_novel/
├── main.py                  # CLI 入口（Click）
├── frontend/                # Next.js Web UI（port 3000）
├── src/api/app.py           # FastAPI 后端（port 8000）
├── mcp_server.py            # MCP Server（FastMCP，供 AI 助手调用）
├── config.yaml              # 全局配置
├── pyproject.toml           # 项目元数据 & 依赖
├── src/
│   ├── pipeline.py          # 经典流水线调度器
│   ├── agent_pipeline.py    # Agent 模式流水线
│   ├── director_pipeline.py # AI 导演模式流水线
│   ├── config_manager.py    # YAML 配置加载/验证
│   ├── checkpoint.py        # 断点续传（JSON）
│   ├── logger.py            # Rich 日志
│   ├── agents/              # 视频 Agent 智能编排（LangGraph）
│   │   ├── graph.py         #   状态图构建 + 断点续传
│   │   ├── director.py      #   导演 Agent
│   │   ├── content_analyzer.py  # 内容分析 Agent
│   │   ├── art_director.py      # 美术总监 Agent
│   │   ├── voice_director.py    # 配音导演 Agent
│   │   └── editor.py       #   剪辑师 Agent
│   ├── tools/               # Tool 层（封装执行模块）
│   ├── scriptplan/          # AI 导演脚本规划
│   │   ├── idea_planner.py  #   灵感 → 概念
│   │   ├── script_planner.py    # 概念 → 分段脚本
│   │   ├── asset_strategy.py    # 素材策略决策
│   │   └── models.py       #   Pydantic 数据模型
│   ├── task_queue/          # 后台任务队列
│   │   ├── server.py        #   FastAPI 任务服务
│   │   ├── client.py        #   客户端接口
│   │   ├── workers.py       #   任务 Worker
│   │   └── db.py            #   SQLite 持久化
│   ├── llm/                 # LLM 统一抽象层
│   │   ├── llm_client.py    #   ABC + 工厂 + 自动检测
│   │   ├── openai_backend.py    # OpenAI / DeepSeek
│   │   ├── gemini_backend.py    # Google Gemini
│   │   └── ollama_backend.py    # Ollama 本地
│   ├── segmenter/           # 文本分段（simple 规则 / LLM 智能）
│   ├── promptgen/           # 小说文本 → 图片/视频 Prompt
│   ├── imagegen/            # 图片生成
│   │   ├── image_generator.py       # ABC + 工厂
│   │   ├── siliconflow_backend.py   # 硅基流动 FLUX
│   │   ├── dashscope_backend.py     # 阿里云万相
│   │   ├── together_backend.py      # Together.ai
│   │   └── diffusers_backend.py     # 本地 Stable Diffusion
│   ├── videogen/            # AI 视频片段生成
│   │   ├── video_generator.py   # ABC + 工厂
│   │   ├── base_backend.py      # 公共轮询逻辑
│   │   ├── kling_backend.py     # 可灵
│   │   ├── seedance_backend.py  # 即梦
│   │   ├── minimax_backend.py   # MiniMax 海螺
│   │   └── sora_backend.py     # OpenAI Sora
│   ├── tts/                 # edge-tts 配音 + SRT 字幕
│   ├── video/               # FFmpeg 视频合成 + Ken Burns 特效
│   ├── utils/               # 工具函数（FFmpeg 检测等）
│   └── novel/               # AI 长篇小说创作模块
│       ├── pipeline.py      #   小说创作流水线
│       ├── config.py        #   小说模块配置
│       ├── agents/          #   9 个 Agent（导演/世界观/角色/情节/写手/一致性/风格/质量/反馈）
│       ├── models/          #   Pydantic 数据模型
│       ├── storage/         #   存储层（SQLite + NetworkX + Chroma）
│       ├── tools/           #   BM25 检索(fallback) / 章节摘要 / 质量检查
│       ├── services/        #   ContinuityService / AgentChat / ObligationTracker / 一致性
│       └── templates/       #   风格预设 / 节奏模板 / AI味黑名单
├── scripts/                 # 实用脚本（批量生成、七猫发布等）
├── input/                   # 输入小说文本
├── presets/                 # 风格预设（YAML）
├── workspace/               # 工作目录（自动生成）
└── output/                  # 输出视频（自动生成）
```

### 流水线阶段

```
┌─────────────────────────────────────────────────────────────────┐
│                       Pipeline 流水线                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Stage 1: 文本分段                                              │
│  小说文本 → 按节奏切分为多个段落                                  │
│       ↓                                                         │
│  Stage 2: Prompt 生成                                           │
│  每段文本 → LLM 生成图片/视频描述 Prompt                         │
│       ↓                                                         │
│  Stage 3: 图片生成                                              │
│  Prompt → AI 生成竖屏插画（1024x1792）                           │
│       ↓                                                         │
│  Stage 3.5: AI 视频生成 [可选]                                   │
│  图片 + Prompt → AI 生成动态视频片段                              │
│       ↓                                                         │
│  Stage 4: TTS 配音                                              │
│  段落文本 → edge-tts 语音 + SRT 字幕                             │
│       ↓                                                         │
│  Stage 5: 视频合成                                              │
│  图片/视频 + 音频 + 字幕 → FFmpeg 合成最终 MP4                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

每个阶段完成后自动保存检查点，支持断点续传。

---

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| CLI | Click |
| Web UI | Next.js (frontend) + FastAPI (backend) |
| MCP | FastMCP（streamable-http + stdio） |
| 任务队列 | FastAPI + SQLite |
| TTS | edge-tts（微软免费语音合成） |
| LLM | OpenAI / DeepSeek / Google Gemini / Ollama |
| 图片生成 | SiliconFlow / 阿里云万相 / Together.ai / Diffusers (本地 SD) |
| 视频生成 | 可灵 Kling / 即梦 Seedance / MiniMax 海螺 / OpenAI Sora |
| 智能编排 | LangGraph — 视频 5 Agent + 小说 9 Agent + ContinuityService 叙事状态驱动 |
| 视频合成 | FFmpeg（H.265 编码、Ken Burns 特效、字幕烧录） |
| 日志 | Rich |
| 配置 | PyYAML |
| 打包 | PyInstaller |

---

## 零成本方案

不花一分钱跑通完整流水线：

1. **LLM** — Gemini 免费（1000 次/天），或使用 `segmenter.method: simple` 跳过 LLM
2. **图片** — SiliconFlow 免费注册即可使用
3. **TTS** — edge-tts 完全免费
4. **视频合成** — FFmpeg 开源免费
5. **视频模式** — 默认静态图 + Ken Burns，无需付费视频 API

---

## 开发指南

### 添加新的视频生成后端

项目采用 **抽象基类 + 工厂函数** 的插件化架构，添加新后端只需三步：

1. 在 `src/videogen/` 下创建 `xxx_backend.py`，继承 `BaseVideoBackend`：

```python
from src.videogen.base_backend import BaseVideoBackend
from src.videogen.video_generator import VideoResult

class XxxBackend(BaseVideoBackend):
    def _submit_task(self, prompt: str, image_path=None) -> str:
        """提交生成任务，返回 task_id"""
        ...

    def _poll_task(self, task_id: str) -> dict:
        """查询任务状态"""
        ...

    def _download_video(self, result: dict, output_path) -> Path:
        """下载视频到本地"""
        ...
```

2. 在 `src/videogen/video_generator.py` 的工厂函数中注册新后端：

```python
elif backend == "xxx":
    from src.videogen.xxx_backend import XxxBackend
    return XxxBackend(config)
```

3. 在 `config.yaml` 中添加对应配置项。

### 添加新的图片生成后端

同理，在 `src/imagegen/` 下创建后端文件，继承 `ImageGenerator` 基类，实现 `generate(prompt) -> PIL.Image` 方法，然后在工厂函数中注册。

### 依赖安装选项

| 选项 | 说明 | 典型场景 |
|------|------|---------|
| `pip install -e .` | 基础依赖（CLI + TTS） | 最小安装 |
| `.[web]` | + FastAPI Web 后端 | Web API 服务 |
| `.[gemini]` | + Google Gemini | 免费 LLM |
| `.[llm]` | + OpenAI SDK | OpenAI / DeepSeek |
| `.[ollama]` | + Ollama 客户端 | 本地 LLM |
| `.[cloud-image]` | + httpx | 云端生图 |
| `.[cloud-video]` | + httpx | AI 视频生成 |
| `.[agent]` | + LangGraph | Agent 智能模式 |
| `.[agent-gemini]` | + LangChain Gemini | Agent + Gemini LLM |
| `.[gpu]` | + torch + diffusers | 本地 Stable Diffusion |
| `.[build]` | + PyInstaller | 桌面应用打包 |
| `.[all]` | 全部安装 | 开发环境 |

---

## 更新计划

**已完成：**
- [x] AI 长篇小说自动创作 — 9 Agent 协作，支持 10-50 万字级别小说生成 + 读者反馈重写
- [x] 叙事弧线控制 v1.3 — 里程碑自动生成 + 强制控制 + 陈旧大纲检测 + 风格圣经
- [x] 全书状态监控 v1.2 — GlobalDirector + CharacterArcTracker + HookGenerator + 死亡检测
- [x] 叙事状态驱动架构 — ContinuityService + 向量一致性 + Agent Chat 会话记忆
- [x] 叙事控制层 — ObligationTracker 债务追踪 + VolumeSettlement 卷末收束 + 弧线推进
- [x] ReAct Agent 框架 — Writer ReAct 推理模式 + Prompt Registry 提示词版本管理
- [x] 两段式章节编排 — dynamic_outline 写前修订 + state_writeback 写后回写
- [x] 动态视频拼接 — AI 视频片段（可灵/即梦/MiniMax/Sora）替代静态贴图
- [x] AI 导演模式 — 灵感一键出片，AI 自动编剧 + 制片
- [x] Web UI 全面升级 — Next.js + FastAPI 创作平台（短视频 + AI 小说 + 设置）
- [x] MCP Server — FastMCP 协议，供 Claude Code 等 AI 助手调用
- [x] 存储重构 — canonical state 架构 + rename_chapter 防覆盖

**计划中：**
- [ ] 伏笔图谱 — NetworkX 伏笔关系图，自动追踪埋设/回收/遗忘
- [ ] 多角色语音 — 不同角色使用不同音色
- [ ] Agent 条件路由 — 根据内容自动选择最优生成策略
- [ ] 更多 LLM/图片后端 — 持续接入新的 AI 服务

---

## License

[MIT](LICENSE)
