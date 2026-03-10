# Agent 编排架构设计

## 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    入口层 (Entry)                        │
│  CLI: main.py --mode agent    Web: web.py (Gradio)      │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              Agent Pipeline (agent_pipeline.py)          │
│  - 初始化 AgentState                                    │
│  - 构建 LangGraph StateGraph                            │
│  - 断点续传 (agent_state.json)                          │
│  - 决策日志 (agent_decisions.json)                      │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│            LangGraph 状态图 (agents/graph.py)            │
│                                                          │
│  START → Director → ContentAnalyzer → ArtDirector        │
│                          → VoiceDirector → Editor → END  │
│                                                          │
│  每个节点自动包装:                                       │
│  ┌─ 检查 completed_nodes → 跳过(续传) 或 执行          │
│  └─ 执行后保存 state checkpoint                         │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              5 个专职 Agent (src/agents/)                │
│                                                          │
│  Director        任务分析 + 成本估算 (纯逻辑, 无LLM)    │
│  ContentAnalyzer 题材分类 + 角色提取 + 风格推荐          │
│  ArtDirector     图片生成 + 质量评估 + 重试优化 ⭐       │
│  VoiceDirector   情感分析 + TTS 参数动态调整             │
│  Editor          FFmpeg 视频合成                         │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                Tool 层 (src/tools/)                      │
│  封装现有模块, Agent 通过 Tool 调用执行层               │
│                                                          │
│  SegmentTool      → segmenter/text_segmenter            │
│  PromptGenTool    → promptgen/prompt_generator           │
│  ImageGenTool     → imagegen/image_generator             │
│  TTSTool          → tts/tts_engine + subtitle_generator  │
│  VideoAssembleTool→ video/video_assembler                │
│  EvaluateQualityTool → GPT-4V/Gemini Vision 质量评估    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│               执行层 (Execution Modules)                 │
│  segmenter/ │ promptgen/ │ imagegen/ │ tts/ │ video/    │
│  与经典模式共享, 零修改                                 │
└─────────────────────────────────────────────────────────┘
```

---

## 核心数据流: AgentState

所有 Agent 共享一个 `AgentState` (TypedDict), 通过 LangGraph 自动合并:

```
AgentState
├── 输入
│   ├── input_file       # 小说文件路径
│   ├── config           # 完整配置
│   ├── workspace        # 工作目录
│   ├── budget_mode      # 省钱模式开关
│   └── resume           # 断点续传开关
│
├── 内容分析结果
│   ├── full_text        # 完整小说文本
│   ├── genre            # 题材 (武侠/玄幻/都市/科幻...)
│   ├── era              # 时代 (古代/现代/未来/架空)
│   ├── characters       # 角色列表 [{name, description}]
│   └── suggested_style  # 推荐画风 (chinese_ink/anime/realistic...)
│
├── 生成资产
│   ├── segments         # 文本分段 [{text, index}]
│   ├── prompts          # 图片 prompt 列表
│   ├── images           # 图片路径列表
│   ├── audio_files      # 音频路径列表
│   ├── srt_files        # 字幕路径列表
│   ├── video_clips      # AI视频片段路径 (可选)
│   └── final_video      # 最终视频路径
│
├── 质量控制
│   ├── quality_scores   # 每段图片评分 (0-10)
│   └── retry_counts     # 每段重试次数
│
└── 编排控制 (使用 operator.add reducer 自动累加)
    ├── decisions        # 决策记录 [Decision]
    ├── errors           # 错误记录 [Error]
    ├── completed_nodes  # 已完成节点 (续传用)
    └── pipeline_plan    # Director 的执行计划
```

---

## 5 个 Agent 详解

### 1. Director — 导演 (纯逻辑, 无 LLM 调用)

```
输入: full_text, config
输出: pipeline_plan, decisions

职责:
  ├── 文本长度分析 → 预估分段数
  ├── 判断是否需要深度内容分析 (>500字 && 非省钱模式)
  ├── 检查视频生成是否启用
  └── 估算 API 成本
```

### 2. ContentAnalyzer — 内容分析师

```
输入: full_text, config, budget_mode
输出: segments, genre, era, characters, suggested_style, decisions

职责:
  ├── 文本分段 (via SegmentTool)
  ├── 题材分类
  │   ├── 标准模式: LLM JSON → {genre, era, confidence}
  │   └── 省钱模式: 正则关键词 (修炼→玄幻, 江湖→武侠, ...)
  ├── 角色提取
  │   ├── 标准模式: LLM → [{name, description}]
  │   └── 省钱模式: 正则 [\u4e00-\u9fa5]{2,4}(说道|问道...)
  └── 风格推荐 (题材+时代 → 画风)
      ├── (武侠, 古代) → chinese_ink
      ├── (玄幻, 架空) → anime
      ├── (都市, 现代) → realistic
      ├── (科幻, 未来) → cyberpunk
      └── 默认 → watercolor
```

### 3. ArtDirector — 美术总监 ⭐ (最复杂)

```
输入: segments, suggested_style, characters, config, budget_mode
输出: prompts, images, quality_scores, retry_counts, decisions

职责 (每个分段循环):
  ┌─────────────────────────────────────────┐
  │  生成 prompt (PromptGenTool)            │
  │         ↓                               │
  │  生成图片 (ImageGenTool)                │
  │         ↓                               │
  │  [标准模式] 质量评估 (EvaluateQuality)  │
  │         ↓                               │
  │  评分 < 阈值(6.0) && 重试 < 3?         │
  │    ├── 是 → 优化 prompt → 重新生成 ↑   │
  │    └── 否 → 选最佳图片, 继续下一段     │
  └─────────────────────────────────────────┘

质量评估维度 (满分 10):
  ├── 构图 composition:  0-2
  ├── 清晰度 clarity:    0-2
  ├── 文本匹配 text_match: 0-3
  ├── 色彩 color:        0-2
  └── 一致性 consistency: 0-1

Prompt 优化策略:
  ├── 清晰度低 → 追加 "sharp focus, high detail, 8k resolution"
  ├── 构图差   → 追加 "well-composed, rule of thirds"
  └── 匹配差   → 追加 "accurate depiction of the scene"
```

### 4. VoiceDirector — 配音导演

```
输入: segments, config, budget_mode
输出: audio_files, srt_files, decisions

职责 (每个分段):
  ├── 情感分析
  │   ├── 标准模式: LLM 分类
  │   └── 省钱模式: 正则 (危险|杀→紧张, 哭|泪→悲伤, 笑→欢快)
  └── TTS 参数动态映射
      ├── 平静: rate=+0%,  volume=+0%
      ├── 紧张: rate=+10%, volume=+5%
      ├── 悲伤: rate=-15%, volume=-5%
      ├── 欢快: rate=+20%, volume=+10%
      └── 激动: rate=+15%, volume=+10%
```

### 5. Editor — 剪辑师

```
输入: images, audio_files, srt_files, video_clips, config
输出: final_video, decisions

职责:
  ├── 收集所有资产
  ├── 调用 VideoAssembleTool (FFmpeg)
  │   ├── 静态图模式: Ken Burns 特效 (缩放+平移)
  │   └── AI视频模式: 视频片段拼接
  └── 输出 output/{filename}.mp4
```

---

## 省钱模式对比

| Agent | 标准模式 | 省钱模式 | 节省 |
|-------|---------|---------|------|
| Director | 纯逻辑 | 纯逻辑 | — |
| ContentAnalyzer | LLM 分类+提取 | 正则规则 | ~$0.005/次 |
| ArtDirector | GPT-4V 质量评估 + 重试 | 跳过质量检查 | ~$0.01/图 |
| VoiceDirector | LLM 情感分析 | 正则规则 | ~$0.002/段 |
| Editor | — | — | — |
| **总计** | 10段约 $0.15 | 10段约 $0.08 | **~40%** |

---

## 断点续传机制

```
graph.py: _make_skip_or_run(node_fn)

执行节点时:
  1. 检查 node_name ∈ state["completed_nodes"]?
     ├── 是 → 跳过, 日志 "[Resume] 跳过已完成: {node}"
     └── 否 → 执行节点
  2. 执行成功后:
     ├── 追加 node_name 到 completed_nodes
     └── 原子写入 workspace/agent_state.json (先写 .tmp 再 rename)

恢复时:
  AgentPipeline._load_state() 读取 agent_state.json
  → 已完成的节点自动跳过
  → 从断点节点继续执行
```

---

## 决策追踪系统

每个 Agent 的关键决策都通过 `make_decision()` 记录:

```python
Decision = {
    "agent":     "ArtDirector",           # 哪个 Agent
    "step":      "quality_seg3_try2",     # 步骤标识
    "decision":  "评分=7.1/10, 通过",     # 决策结论
    "reason":    "高于阈值 6.0",          # 决策原因
    "data":      {"score": 7.1, ...},     # 结构化数据
    "timestamp": "2024-01-15T08:30:00Z"   # UTC 时间
}
```

所有决策通过 `Annotated[list[Decision], operator.add]` 自动累加,
最终保存到 `workspace/{name}/agent_decisions.json`。

---

## 完整执行流程示例

```
用户: python main.py run novel.txt --mode agent

1. Director (0.1s, 无API)
   → "1000字, 预计10段, 成本约$0.15"

2. ContentAnalyzer (2-3s, 2次LLM)
   → 分段: 10段
   → 题材: 武侠, 时代: 古代
   → 角色: 张三(少年剑客), 李四(黑衣杀手)
   → 画风: chinese_ink

3. ArtDirector (30-60s, 10次图片+N次质量评估)
   → 段1: prompt生成 → 图片生成 → 评分6.8 → 通过
   → 段2: prompt生成 → 图片生成 → 评分4.2 → 重试
         → 优化prompt → 重新生成 → 评分7.5 → 通过
   → ... (共10段)

4. VoiceDirector (5-10s, 10次TTS免费)
   → 段1: 情感=平静 → rate=+0%, vol=+0%
   → 段3: 情感=紧张 → rate=+10%, vol=+5%
   → ... (共10段)

5. Editor (10-20s, FFmpeg)
   → 合成 10个片段 → output/novel.mp4

总耗时: ~1-2分钟
输出文件:
  ├── output/novel.mp4              # 最终视频
  ├── workspace/novel/agent_state.json     # 状态快照
  └── workspace/novel/agent_decisions.json # 50+条决策日志
```

---

## 文件索引

| 文件 | 职责 |
|------|------|
| `src/agent_pipeline.py` | Agent 模式入口, 状态管理 |
| `src/agents/graph.py` | LangGraph 图构建, 断点续传 |
| `src/agents/state.py` | AgentState 类型定义 |
| `src/agents/director.py` | 导演 Agent |
| `src/agents/content_analyzer.py` | 内容分析 Agent |
| `src/agents/art_director.py` | 美术总监 Agent |
| `src/agents/voice_director.py` | 配音导演 Agent |
| `src/agents/editor.py` | 剪辑师 Agent |
| `src/agents/utils.py` | 决策工具, JSON提取 |
| `src/agents/cost_tracker.py` | API 成本追踪 |
| `src/tools/*.py` | 6个 Tool 封装 |
