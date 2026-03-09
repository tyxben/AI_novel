# LangGraph 多 Agent 架构改造 - 需求文档

## 1. 项目概述

### 1.1 背景
当前 AI 小说推文自动化项目采用线性流水线架构（Pipeline），按固定顺序执行 5 个阶段：文本分段 → Prompt 生成 → 图片生成 → TTS 配音 → 视频合成。虽然功能完整且支持断点续传，但存在以下局限：

- **缺乏智能决策**：无法根据内容特点自动选择最优策略（如分段方法、视觉风格、后端选择）
- **质量控制被动**：生成结果无自检机制，质量完全依赖初始配置
- **缺少反馈循环**：各阶段独立执行，无法根据下游结果优化上游决策
- **适应性差**：遇到生成失败或质量不佳时，只能整体重跑

### 1.2 改造目标
在保持现有模块完整性的前提下，上层加入 LangGraph 智能调度层，实现：

1. **多 Agent 协作**：导演、内容分析、美术指导、配音导演、剪辑 5 个专业 Agent 协同工作
2. **智能决策**：根据小说类型、内容特点自动选择策略
3. **质量自检**：关键阶段（图片生成）引入 LLM 视觉模型质量评估 + 自动重试
4. **渐进式改造**：保留原 Pipeline 模式，新增 `--mode agent` 可选启用
5. **透明化决策**：Agent 决策过程持久化到 workspace，便于调试和分析

### 1.3 核心用户故事

**US-1: 智能模式切换**
- **作为**项目用户
- **我想要**在运行时通过 `--mode agent` 启用智能 Agent 模式
- **以便**利用 AI 智能决策优化视频生成质量，同时保留简单模式满足快速处理需求

**US-2: 内容自适应策略**
- **作为**小说视频制作者
- **我想要**Agent 自动分析小说类型（武侠、都市、玄幻、言情等）并选择最合适的视觉风格和分段策略
- **以便**无需手动调优配置即可获得符合题材特色的视频

**US-3: 图片质量自检与重试**
- **作为**内容质量要求高的用户
- **我想要**系统自动评估生成图片的质量（构图、清晰度、与文本匹配度）
- **以便**当图片不符合标准时自动优化 prompt 并重试（最多 3 次），避免生成低质量视频

**US-4: 角色一致性保障**
- **作为**连续剧情视频制作者
- **我想要**美术指导 Agent 维护全局角色设定（外貌、服装、特征）并强制在所有 prompt 中保持一致
- **以便**避免同一角色在不同画面中外观差异过大

**US-5: 决策透明化**
- **作为**开发者或高级用户
- **我想要**查看 Agent 在每个决策点的思考过程（为什么选择某个风格、为什么重试、质量评分依据等）
- **以便**理解系统行为并优化配置

**US-6: 成本控制**
- **作为**预算有限的用户
- **我想要**启用"省钱模式"（`--budget-mode`）
- **以便**在非关键决策点使用规则/简单逻辑替代 LLM 调用，降低 API 成本

**US-7: 多后端智能选择**
- **作为**拥有多个 API Key 的用户
- **我想要**Agent 根据当前场景特点（静态/动态、细节复杂度）自动选择最合适的图片/视频生成后端
- **以便**在质量、速度、成本之间取得平衡

**US-8: 配音情感匹配**
- **作为**追求沉浸感的用户
- **我想要**配音导演 Agent 分析文本情感（紧张、悲伤、欢快）并自动调整语速、音调
- **以便**让旁白与画面情绪协调

---

## 2. 功能需求

### 2.1 系统架构需求

#### FR-2.1.1 双模式运行
**优先级**: P0（必须）

系统必须支持两种运行模式：

1. **Classic 模式**（默认）
   - 保持现有 `Pipeline` 类不变
   - 命令：`python main.py run input.txt`（无 `--mode` 参数或 `--mode classic`）
   - 适用场景：快速处理、调试、成本敏感

2. **Agent 模式**（智能）
   - 使用 LangGraph 多 Agent 调度
   - 命令：`python main.py run input.txt --mode agent`
   - 可选叠加：`--budget-mode` 启用省钱模式
   - 适用场景：质量优先、复杂内容、需要自适应

#### FR-2.1.2 LangGraph State Graph 架构
**优先级**: P0

Agent 模式采用 LangGraph StateGraph，包含以下节点：

- **Director（导演）节点** - 入口，分析任务，编排整体流程
- **ContentAnalyzer（内容分析）节点** - 分析小说类型、风格、角色
- **ArtDirector（美术指导）节点** - 管理视觉风格、生成/优化 prompt、质量评估
- **VoiceDirector（配音导演）节点** - 选择声音、调整情感参数
- **Editor（剪辑）节点** - 视频节奏、特效、最终合成

节点之间通过共享 `State` 对象通信，State 包含：
- 原始输入（小说文本、配置）
- 中间结果（分段、prompts、图片路径、音频路径）
- Agent 决策记录
- 质量评分、重试计数器

#### FR-2.1.3 现有模块作为 Tool
**优先级**: P0

所有现有执行模块保留不变，封装为 LangChain Tool：

- `SegmentTool` - 调用 `src/segmenter/`
- `PromptGenTool` - 调用 `src/promptgen/`
- `ImageGenTool` - 调用 `src/imagegen/`
- `VideoGenTool` - 调用 `src/videogen/`
- `TTSTool` - 调用 `src/tts/`
- `VideoAssembleTool` - 调用 `src/video/`

### 2.2 Agent 角色与职责

#### FR-2.2.1 Director Agent（导演 Agent）
**优先级**: P0

**职责**：
1. 接收用户输入（小说文本、配置）
2. 首次分析：小说长度、语言复杂度、是否包含对话
3. 决策：是否需要启用 AI 视频生成、是否需要智能分段
4. 编排流程：调用 ContentAnalyzer → ArtDirector → VoiceDirector → Editor
5. 处理全局异常和重试逻辑

**工具列表**：
- `AnalyzeNovelLengthTool` - 计算字数、估算段数
- `CheckConfigTool` - 读取并验证用户配置

**决策输出**：
- `pipeline_plan`: dict - 包含各阶段开关、预估资源消耗
- `analysis_needed`: bool - 是否需要深度内容分析

#### FR-2.2.2 ContentAnalyzer Agent（内容分析 Agent）
**优先级**: P0

**职责**：
1. 分析小说类型（武侠、玄幻、都市、言情、科幻等）
2. 提取主要角色及其特征（外貌、服装、性格）
3. 判断时代背景（古代、现代、未来）
4. 建议分段策略（简单规则 vs LLM 智能）
5. 建议默认视觉风格（anime / realistic / chinese_ink 等）

**工具列表**：
- `SegmentTool` - 执行文本分段
- `ExtractCharactersTool` - 调用 LLM 提取角色信息
- `ClassifyGenreTool` - 调用 LLM 分类小说类型

**决策输出**：
- `genre`: str - 小说类型
- `era`: str - 时代背景
- `characters`: list[dict] - 角色列表（name, description）
- `suggested_style`: str - 推荐视觉风格
- `segments`: list[dict] - 分段结果

#### FR-2.2.3 ArtDirector Agent（美术指导 Agent）
**优先级**: P0

**职责**：
1. 根据内容分析结果确定最终视觉风格
2. 为每个分段生成图片 prompt（调用 PromptGenTool）
3. 调用图片生成 Tool 生成图片
4. **质量自检**：使用 GPT-4V/Gemini Vision 评估图片质量（0-10 分）
5. **智能重试**：若评分 < 6 分，优化 prompt 后重新生成（最多 3 次）
6. 维护角色一致性（确保所有 prompt 中角色描述一致）
7. 生成视频 prompt（如果启用 AI 视频）

**工具列表**：
- `PromptGenTool` - 生成图片/视频 prompt
- `ImageGenTool` - 调用图片生成器
- `VideoGenTool` - 调用视频生成器（可选）
- `EvaluateImageQualityTool` - 调用 GPT-4V/Gemini Vision 评估图片
- `OptimizePromptTool` - 根据质量反馈优化 prompt

**决策输出**：
- `prompts`: list[str] - 最终使用的图片 prompts
- `images`: list[Path] - 生成的图片路径
- `quality_scores`: list[float] - 各图片质量评分
- `retry_log`: list[dict] - 重试记录
- `video_clips`: list[Path] - AI 视频片段路径（可选）

**质量评估标准**：
- 构图合理性（2 分）
- 清晰度/锐度（2 分）
- 与文本描述匹配度（3 分）
- 色彩协调性（2 分）
- 角色一致性（1 分，如有角色）

#### FR-2.2.4 VoiceDirector Agent（配音导演 Agent）
**优先级**: P1（重要）

**职责**：
1. 分析每个分段的情感基调（平静、紧张、悲伤、欢快、激动）
2. 根据情感调整 TTS 参数（语速 rate、音量 volume）
3. 调用 TTS Tool 生成音频和字幕
4. （可选）根据场景匹配背景音乐

**工具列表**：
- `AnalyzeSentimentTool` - 调用 LLM 分析文本情感
- `TTSTool` - 调用 TTS 引擎生成音频

**决策输出**：
- `audio_files`: list[Path] - 音频文件路径
- `srt_files`: list[Path] - 字幕文件路径
- `tts_params`: list[dict] - 各段使用的 TTS 参数

**情感与参数映射**（默认规则，省钱模式使用）：
| 情感 | rate | volume | 说明 |
|------|------|--------|------|
| 平静 | +0% | +0% | 默认 |
| 紧张 | +10% | +5% | 稍快稍响 |
| 悲伤 | -15% | -5% | 慢且轻柔 |
| 欢快 | +20% | +10% | 明快响亮 |
| 激动 | +15% | +10% | 快速高亢 |

#### FR-2.2.5 Editor Agent（剪辑 Agent）
**优先级**: P1

**职责**：
1. 分析整体节奏（是否需要调整转场时长）
2. 决定 Ken Burns 特效强度（静态场景加强、动态场景减弱）
3. 调用 VideoAssembleTool 合成最终视频
4. 验证输出文件完整性

**工具列表**：
- `VideoAssembleTool` - 调用 FFmpeg 合成视频
- `AnalyzeRhythmTool` - 分析音频时长分布

**决策输出**：
- `final_video`: Path - 最终视频文件路径
- `assembly_log`: dict - 合成参数记录

### 2.3 质量控制需求

#### FR-2.3.1 图片质量自检循环
**优先级**: P0

在 ArtDirector 节点，每生成一张图片后：

1. 调用 `EvaluateImageQualityTool`（GPT-4V 或 Gemini Vision）
2. 获得 0-10 分评分和文字反馈
3. 判断：
   - **≥ 7 分**：通过，继续下一张
   - **6 分**：警告但通过（记录日志）
   - **< 6 分 且 重试次数 < 3**：优化 prompt 并重新生成
   - **< 6 分 且 重试次数 = 3**：强制通过，记录警告

4. 优化策略（`OptimizePromptTool`）：
   - 根据反馈调整关键词（如反馈"模糊"→ 加 "sharp focus, high detail"）
   - 根据反馈调整权重（如反馈"角色不清晰"→ 提升角色描述权重）

#### FR-2.3.2 重试预算管理
**优先级**: P0

State 中维护每个分段的重试计数器：
```python
retry_counts: dict[int, int] = {}  # {segment_index: retry_count}
MAX_RETRIES = 3
```

当某段触发重试时：
- 计数器 +1
- 若达到上限，强制使用当前结果并记录警告
- 最终在决策日志中汇总重试统计

#### FR-2.3.3 省钱模式（Budget Mode）
**优先级**: P1

当启用 `--budget-mode` 时：

1. **关闭图片质量自检**：跳过 GPT-4V/Gemini Vision 评估，直接使用生成结果
2. **简化内容分析**：
   - 不调用 LLM 分类类型，使用关键词匹配（如检测"修炼/法宝"→ 玄幻）
   - 不调用 LLM 提取角色，使用正则提取人名
3. **固定 TTS 参数**：不分析情感，所有段使用默认参数
4. **使用廉价 LLM**：Prompt 生成改用 DeepSeek/Gemini Flash（而非 GPT-4）

实现方式：
- 配置文件新增 `agent.budget_mode: bool`
- 各 Agent 在初始化时读取此标志，选择不同 Tool 实现

### 2.4 决策日志需求

#### FR-2.4.1 决策日志结构
**优先级**: P0

在 workspace 目录下生成 `agent_decisions.json`，包含：

```json
{
  "mode": "agent",
  "budget_mode": false,
  "timestamp": "2026-03-09T10:30:00",
  "decisions": [
    {
      "agent": "Director",
      "step": "initialize",
      "decision": "启用 AI 视频生成",
      "reason": "检测到用户配置了 videogen.backend",
      "timestamp": "2026-03-09T10:30:05"
    },
    {
      "agent": "ContentAnalyzer",
      "step": "classify_genre",
      "decision": "类型=武侠, 风格=chinese_ink",
      "reason": "检测到'江湖''剑气''武功'等关键词",
      "timestamp": "2026-03-09T10:30:12"
    },
    {
      "agent": "ArtDirector",
      "step": "image_quality_check",
      "segment": 3,
      "score": 5.5,
      "feedback": "人物面部模糊，背景过暗",
      "action": "重新生成（第1次重试）",
      "timestamp": "2026-03-09T10:32:45"
    }
  ],
  "summary": {
    "total_retries": 8,
    "avg_quality_score": 7.2,
    "cost_estimate": "$1.20"
  }
}
```

#### FR-2.4.2 日志可视化（可选）
**优先级**: P2

在 `status` 命令中新增选项：
```bash
python main.py status workspace/novel/ --decisions
```

输出 Rich 格式的表格，展示：
- 各 Agent 决策次数
- 重试统计
- 平均质量评分

### 2.5 性能与兼容性需求

#### FR-2.5.1 断点续传兼容
**优先级**: P0

Agent 模式必须复用现有 `Checkpoint` 机制：
- 每个 Agent 节点完成后调用 `checkpoint.mark_done(stage)`
- 支持 `--resume` 参数，跳过已完成的 Agent 节点
- State 持久化到 `workspace/agent_state.json`

#### FR-2.5.2 性能基线
**优先级**: P1

- **Classic 模式**：性能不得劣化（±5% 容差）
- **Agent 模式**（无质量检查）：相比 Classic 慢 ≤ 20%
- **Agent 模式**（含质量检查）：相比 Classic 慢 ≤ 50%（因增加 GPT-4V 调用）

#### FR-2.5.3 依赖管理
**优先级**: P0

新增依赖：
- `langgraph >= 0.0.26` - StateGraph 核心
- `langchain >= 0.1.0` - Tool 抽象
- `langchain-openai >= 0.0.5` - GPT-4V 集成（质量评估）
- `langchain-google-genai >= 0.0.5` - Gemini Vision 集成（可选）

在 `pyproject.toml` 新增：
```toml
[project.optional-dependencies]
agent = [
    "langgraph>=0.0.26",
    "langchain>=0.1.0",
    "langchain-openai>=0.0.5",
]
agent-gemini = [
    "langchain-google-genai>=0.0.5",
]
all = [
    "novel-video[gpu,llm,gemini,ollama,cloud-image,cloud-video,web,agent]",
]
```

---

## 3. 非功能需求

### 3.1 可扩展性
**NFR-3.1**: 新增 Agent 角色或 Tool 时，无需修改 StateGraph 核心逻辑，通过配置注册即可

### 3.2 可测试性
**NFR-3.2**: 各 Agent 必须支持单元测试（Mock Tool 输入输出），StateGraph 支持集成测试

### 3.3 可观测性
**NFR-3.3**: 所有 Agent 决策必须通过结构化日志（JSON）记录，便于追溯和分析

### 3.4 成本透明
**NFR-3.4**: 决策日志包含 API 调用次数和预估成本（按当前费率计算）

### 3.5 向后兼容
**NFR-3.5**: 现有用户的 `config.yaml` 和命令行用法在不加 `--mode agent` 时完全不受影响

---

## 4. 验收标准

### AC-1: 模式切换
- 运行 `python main.py run input.txt` → 使用 Classic Pipeline
- 运行 `python main.py run input.txt --mode agent` → 使用 LangGraph Agent
- 两种模式输出视频质量主观对比：Agent 模式 ≥ Classic 模式

### AC-2: 质量自检生效
- 在 Agent 模式下，故意使用低质量 prompt（如过于简短、语义模糊）
- 检查 `agent_decisions.json` 中存在 `image_quality_check` 记录
- 确认触发了重试逻辑
- 最终生成的图片评分 ≥ 6 分

### AC-3: 省钱模式
- 运行 `python main.py run input.txt --mode agent --budget-mode`
- 确认 `agent_decisions.json` 中 `budget_mode: true`
- 确认无 GPT-4V 质量评估调用（通过日志验证）
- API 成本比标准 Agent 模式降低 ≥ 40%

### AC-4: 决策日志完整性
- 完成一次 Agent 模式运行后，检查 `workspace/novel/agent_decisions.json`
- 验证包含：Director、ContentAnalyzer、ArtDirector、VoiceDirector、Editor 各节点的决策记录
- 验证 `summary` 字段包含统计数据

### AC-5: 断点续传
- Agent 模式运行中途中断（Ctrl+C）
- 再次运行相同命令 + `--resume`
- 确认跳过已完成节点，从中断点继续

### AC-6: 角色一致性
- 输入包含明确角色描述的小说片段（如"张三，身穿白衣，手持长剑"）
- 检查所有生成图片的 prompt 中角色描述一致
- 使用人工评审确认画面中角色外观差异 ≤ 可接受范围

### AC-7: 性能基准
- 使用相同 1000 字小说文本，分别运行 Classic 和 Agent（budget 模式）
- Classic 耗时 T1，Agent 耗时 T2
- 验证 T2 / T1 ≤ 1.2

---

## 5. 边界与约束

### 5.1 边界
**IN SCOPE（本次改造包含）**:
- LangGraph StateGraph 架构搭建
- 5 个核心 Agent 实现（Director, ContentAnalyzer, ArtDirector, VoiceDirector, Editor）
- 图片质量自检 + 重试机制
- 决策日志记录
- 省钱模式
- 与现有 Tool 集成

**OUT OF SCOPE（不包含）**:
- LLM Agent 自主学习/训练（使用现成的 GPT-4/Gemini）
- Web UI 可视化 Agent 决策流程（暂时仅 JSON + CLI）
- 实时流式处理（仍为批量处理）
- 多语言支持（仅中文小说）

### 5.2 约束
- **技术约束**：必须使用 LangGraph（不使用 AutoGPT/CrewAI/其他框架）
- **成本约束**：标准 Agent 模式单次运行成本 < $2（1000 字小说）
- **时间约束**：Phase 1 最小可用原型 2 周内完成
- **兼容性约束**：Python 3.10+，现有依赖版本不降级

---

## 6. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| LLM API 不稳定导致 Agent 频繁失败 | 中 | 高 | 增加重试逻辑 + 降级到规则策略 |
| 质量评估标准主观性强，误判率高 | 中 | 中 | 提供可配置的阈值 + 人工审核模式 |
| 成本超预期（GPT-4V 调用过多） | 高 | 中 | 默认启用省钱模式 + 成本预警 |
| 新架构增加代码复杂度，维护困难 | 中 | 中 | 模块化设计 + 完善文档 + 单元测试 |
| 用户不理解 Agent 决策，信任度低 | 低 | 低 | 详细决策日志 + FAQ 文档 |

---

## 7. 未来扩展方向（Post-MVP）

1. **Human-in-the-Loop**: 在关键决策点（如风格选择）弹出交互界面让用户确认
2. **A/B 测试框架**: 自动生成多版本视频，由用户选择最佳
3. **风格迁移 Agent**: 学习用户历史偏好，自动调整风格参数
4. **多模态检索**: Agent 主动搜索参考图片（如角色原型）辅助生成
5. **分布式执行**: 多个片段并行由不同 Agent 实例处理
6. **Cost Optimizer Agent**: 实时监控成本，动态切换后端

---

**文档版本**: v1.0
**最后更新**: 2026-03-09
**作者**: AI Planning Assistant
**审阅状态**: 待用户确认
