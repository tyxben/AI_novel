# LangGraph 多 Agent 架构改造 - 任务清单

## 概述

本文档定义了 LangGraph 多 Agent 架构改造的分阶段实施任务。项目采用渐进式迭代方法，分为 3 个 Phase：

- **Phase 1: 基础架构 + 最小可用原型**（2 周）- 核心框架 + Director/ArtDirector Agent
- **Phase 2: 完整 Agent 体系 + 质量控制**（1.5 周）- 所有 5 个 Agent + 质量自检
- **Phase 3: 优化与增强**（1 周）- 性能优化 + 省钱模式 + 监控

总预计时间：**4.5 周**

---

## Phase 1: 基础架构 + 最小可用原型（2 周）

**目标**: 搭建 LangGraph StateGraph 框架，实现最简单的 Agent 流程（Director → ArtDirector → Editor），能端到端生成一个视频。

### 1. 环境准备与依赖安装

- [ ] 1.1 更新 `pyproject.toml`
  - [ ] 1.1.1 在 `[project.optional-dependencies]` 新增 `agent` 依赖组
    ```toml
    agent = [
        "langgraph>=0.0.26",
        "langchain>=0.1.0",
        "langchain-openai>=0.0.5",
    ]
    ```
  - [ ] 1.1.2 新增 `agent-gemini` 可选依赖（Gemini Vision）
    ```toml
    agent-gemini = [
        "langchain-google-genai>=0.0.5",
    ]
    ```
  - [ ] 1.1.3 更新 `all` 依赖组包含 `agent`
  - [ ] 1.1.4 提交变更：`git commit -m "feat: 添加 LangGraph Agent 模式依赖"`

- [ ] 1.2 本地安装测试
  - [ ] 1.2.1 运行 `pip install -e '.[agent]'` 验证安装成功
  - [ ] 1.2.2 Python 交互环境测试导入
    ```python
    from langgraph.graph import StateGraph
    from langchain.tools import BaseTool
    # 验证无报错
    ```

- [ ] 1.3 创建项目目录结构
  - [ ] 1.3.1 创建 `src/agents/` 目录
  - [ ] 1.3.2 创建 `src/agents/__init__.py`
  - [ ] 1.3.3 创建 `src/agents/utils.py`（公共工具函数）
  - [ ] 1.3.4 创建 `src/tools/` 目录（Tool 层）
  - [ ] 1.3.5 创建 `src/tools/__init__.py`

---

### 2. 数据模型定义

- [ ] 2.1 定义 `AgentState` 类型
  - [ ] 2.1.1 创建 `src/agents/state.py`
  - [ ] 2.1.2 定义 `AgentState` TypedDict，包含所有字段（见 design.md 2.1）
  - [ ] 2.1.3 定义 `Decision` TypedDict（决策日志结构）
  - [ ] 2.1.4 定义 `QualityEvaluation` TypedDict（质量评估结构）
  - [ ] 2.1.5 添加类型注解和文档字符串

- [ ] 2.2 实现决策日志工具函数
  - [ ] 2.2.1 在 `src/agents/utils.py` 实现 `log_decision()` 函数
    ```python
    def log_decision(state: AgentState, agent: str, step: str,
                     decision: str, reason: str, data: dict | None = None)
    ```
  - [ ] 2.2.2 实现 `save_decisions_to_file()` - 保存决策到 JSON
  - [ ] 2.2.3 实现 `load_decisions_from_file()` - 加载决策（断点续传用）

---

### 3. Tool 层封装（现有模块 → LangChain Tool）

- [ ] 3.1 实现 `SegmentTool`
  - [ ] 3.1.1 创建 `src/tools/segment_tool.py`
  - [ ] 3.1.2 继承 `BaseTool`，定义 `SegmentToolInput` schema
  - [ ] 3.1.3 实现 `_run()` 方法，调用现有 `src/segmenter/text_segmenter.py`
  - [ ] 3.1.4 编写单元测试 `tests/tools/test_segment_tool.py`

- [ ] 3.2 实现 `PromptGenTool`
  - [ ] 3.2.1 创建 `src/tools/prompt_gen_tool.py`
  - [ ] 3.2.2 封装现有 `src/promptgen/prompt_generator.py`
  - [ ] 3.2.3 支持传入 `characters`（角色一致性）和 `style`（视觉风格）参数
  - [ ] 3.2.4 编写单元测试

- [ ] 3.3 实现 `ImageGenTool`
  - [ ] 3.3.1 创建 `src/tools/image_gen_tool.py`
  - [ ] 3.3.2 封装现有 `src/imagegen/image_generator.py`
  - [ ] 3.3.3 处理输出路径（workspace/images/XXXX.png）
  - [ ] 3.3.4 编写单元测试（Mock 图片生成器）

- [ ] 3.4 实现 `TTSTool`
  - [ ] 3.4.1 创建 `src/tools/tts_tool.py`
  - [ ] 3.4.2 封装现有 `src/tts/tts_engine.py` 和 `src/tts/subtitle_generator.py`
  - [ ] 3.4.3 支持动态 TTS 参数（rate, volume）
  - [ ] 3.4.4 编写单元测试

- [ ] 3.5 实现 `VideoAssembleTool`
  - [ ] 3.5.1 创建 `src/tools/video_assemble_tool.py`
  - [ ] 3.5.2 封装现有 `src/video/video_assembler.py`
  - [ ] 3.5.3 支持可选 `video_clips` 参数（AI 视频模式）
  - [ ] 3.5.4 编写单元测试

- [ ] 3.6 工具注册与导出
  - [ ] 3.6.1 在 `src/tools/__init__.py` 导出所有 Tool
  - [ ] 3.6.2 创建 `create_tools()` 工厂函数，统一初始化

---

### 4. Director Agent 实现

- [ ] 4.1 实现 Director Agent 类
  - [ ] 4.1.1 创建 `src/agents/director.py`
  - [ ] 4.1.2 实现 `DirectorAgent` 类（见 design.md 4.1）
  - [ ] 4.1.3 实现 `analyze_task()` - 分析任务
  - [ ] 4.1.4 实现 `plan_pipeline()` - 编排流程
  - [ ] 4.1.5 实现 `_estimate_cost()` - 预估成本

- [ ] 4.2 实现 Director 节点函数
  - [ ] 4.2.1 在 `src/agents/director.py` 实现 `director_node(state: AgentState)`
  - [ ] 4.2.2 调用 DirectorAgent 执行逻辑
  - [ ] 4.2.3 记录决策到 `state["decisions"]`
  - [ ] 4.2.4 更新 `state["pipeline_plan"]`

- [ ] 4.3 单元测试
  - [ ] 4.3.1 创建 `tests/agents/test_director.py`
  - [ ] 4.3.2 测试 `analyze_task()` 逻辑
  - [ ] 4.3.3 测试成本预估准确性
  - [ ] 4.3.4 测试 `director_node()` State 更新

---

### 5. ArtDirector Agent 实现（简化版，暂不含质量检查）

- [ ] 5.1 实现 ArtDirector Agent 类
  - [ ] 5.1.1 创建 `src/agents/art_director.py`
  - [ ] 5.1.2 实现 `ArtDirectorAgent` 类
  - [ ] 5.1.3 实现 `generate_images()` - 生成所有图片（简单版，无质量检查）
    - [ ] 调用 `PromptGenTool` 生成 prompts
    - [ ] 调用 `ImageGenTool` 生成图片
    - [ ] 记录每张图片路径到 State

- [ ] 5.2 实现 ArtDirector 节点函数
  - [ ] 5.2.1 在 `src/agents/art_director.py` 实现 `art_director_node(state: AgentState)`
  - [ ] 5.2.2 遍历所有 segments 生成图片
  - [ ] 5.2.3 更新 `state["images"]`、`state["prompts"]`
  - [ ] 5.2.4 记录决策日志

- [ ] 5.3 单元测试
  - [ ] 5.3.1 创建 `tests/agents/test_art_director.py`
  - [ ] 5.3.2 Mock PromptGenTool 和 ImageGenTool
  - [ ] 5.3.3 测试图片生成流程

---

### 6. Editor Agent 实现

- [ ] 6.1 实现 Editor Agent 类
  - [ ] 6.1.1 创建 `src/agents/editor.py`
  - [ ] 6.1.2 实现 `EditorAgent` 类
  - [ ] 6.1.3 实现 `assemble()` - 调用 `VideoAssembleTool`

- [ ] 6.2 实现 Editor 节点函数
  - [ ] 6.2.1 实现 `editor_node(state: AgentState)`
  - [ ] 6.2.2 合成最终视频
  - [ ] 6.2.3 更新 `state["final_video"]`
  - [ ] 6.2.4 记录决策日志

- [ ] 6.3 单元测试
  - [ ] 6.3.1 创建 `tests/agents/test_editor.py`
  - [ ] 6.3.2 Mock VideoAssembleTool
  - [ ] 6.3.3 测试视频合成逻辑

---

### 7. LangGraph StateGraph 构建

- [ ] 7.1 创建图构建函数
  - [ ] 7.1.1 创建 `src/agents/graph.py`
  - [ ] 7.1.2 实现 `create_agent_graph(config: dict) -> StateGraph`
  - [ ] 7.1.3 添加节点：director, art_director, editor
  - [ ] 7.1.4 定义边：director → art_director → editor → END
  - [ ] 7.1.5 编译并返回图

- [ ] 7.2 测试图执行
  - [ ] 7.2.1 创建 `tests/agents/test_graph.py`
  - [ ] 7.2.2 构造最小 State
  - [ ] 7.2.3 调用 `graph.invoke(state)` 验证流程

---

### 8. AgentPipeline 入口类

- [ ] 8.1 实现 `AgentPipeline` 类
  - [ ] 8.1.1 创建 `src/agent_pipeline.py`
  - [ ] 8.1.2 实现 `__init__()` - 初始化配置、workspace、State
  - [ ] 8.1.3 实现 `_init_state()` - 初始化 AgentState
  - [ ] 8.1.4 实现 `run()` - 调用 StateGraph 执行
  - [ ] 8.1.5 实现 `_save_decisions()` - 保存决策日志到文件

- [ ] 8.2 State 持久化
  - [ ] 8.2.1 实现 `_save_state()` - 保存 State 到 `agent_state.json`
  - [ ] 8.2.2 实现 `_load_state()` - 加载 State（断点续传）
  - [ ] 8.2.3 在每个节点完成后调用 `_save_state()`

- [ ] 8.3 集成测试
  - [ ] 8.3.1 创建 `tests/test_agent_pipeline.py`
  - [ ] 8.3.2 使用测试小说文本（100 字）
  - [ ] 8.3.3 运行完整流程，验证生成视频
  - [ ] 8.3.4 验证 `agent_decisions.json` 文件生成

---

### 9. CLI 集成（双模式切换）

- [ ] 9.1 扩展 `main.py` 命令行参数
  - [ ] 9.1.1 在 `run` 命令添加 `--mode` 参数（classic | agent，默认 classic）
  - [ ] 9.1.2 添加 `--budget-mode` flag（暂时占位，Phase 2 实现）
  - [ ] 9.1.3 添加 `--quality-threshold` 参数（暂时占位，Phase 2 实现）

- [ ] 9.2 模式路由逻辑
  - [ ] 9.2.1 在 `run()` 函数添加条件分支
    ```python
    if mode == "agent":
        from src.agent_pipeline import AgentPipeline
        pipe = AgentPipeline(...)
    else:
        from src.pipeline import Pipeline
        pipe = Pipeline(...)
    ```
  - [ ] 9.2.2 验证 `--mode classic` 仍使用现有 Pipeline
  - [ ] 9.2.3 验证 `--mode agent` 使用新 AgentPipeline

- [ ] 9.3 端到端测试
  - [ ] 9.3.1 准备测试小说文件 `tests/fixtures/sample_novel.txt`
  - [ ] 9.3.2 运行 `python main.py run tests/fixtures/sample_novel.txt --mode classic`
  - [ ] 9.3.3 运行 `python main.py run tests/fixtures/sample_novel.txt --mode agent`
  - [ ] 9.3.4 对比两种模式生成的视频

---

### 10. 文档与示例

- [ ] 10.1 更新 README.md
  - [ ] 10.1.1 新增"Agent 模式"章节
  - [ ] 10.1.2 添加安装命令 `pip install -e '.[agent]'`
  - [ ] 10.1.3 添加使用示例
    ```bash
    # Classic 模式
    python main.py run input.txt

    # Agent 模式
    python main.py run input.txt --mode agent
    ```
  - [ ] 10.1.4 说明 Agent 模式的优势

- [ ] 10.2 创建使用指南
  - [ ] 10.2.1 创建 `docs/agent_mode_guide.md`
  - [ ] 10.2.2 说明 Agent 模式工作原理
  - [ ] 10.2.3 解释决策日志结构
  - [ ] 10.2.4 提供故障排查指南

- [ ] 10.3 提交 Phase 1 完成
  - [ ] 10.3.1 提交所有代码：`git commit -m "feat: Phase 1 - LangGraph 基础架构 + 最小可用原型"`
  - [ ] 10.3.2 标记里程碑：`git tag v0.5.0-alpha-agent`

---

## Phase 2: 完整 Agent 体系 + 质量控制（1.5 周）

**目标**: 实现所有 5 个 Agent，加入质量自检循环，支持断点续传。

### 11. ContentAnalyzer Agent 实现

- [ ] 11.1 实现 ContentAnalyzer Agent 类
  - [ ] 11.1.1 创建 `src/agents/content_analyzer.py`
  - [ ] 11.1.2 实现 `ContentAnalyzerAgent` 类（见 design.md 4.2）
  - [ ] 11.1.3 实现 `classify_genre()` - LLM 分类小说类型
  - [ ] 11.1.4 实现 `_classify_genre_by_rules()` - 规则分类（省钱模式，暂占位）
  - [ ] 11.1.5 实现 `extract_characters()` - LLM 提取角色
  - [ ] 11.1.6 实现 `suggest_style()` - 根据类型推荐风格

- [ ] 11.2 实现 ContentAnalyzer 节点函数
  - [ ] 11.2.1 实现 `content_analyzer_node(state: AgentState)`
  - [ ] 11.2.2 调用 SegmentTool 分段
  - [ ] 11.2.3 调用 classify_genre 分析类型
  - [ ] 11.2.4 调用 extract_characters 提取角色
  - [ ] 11.2.5 调用 suggest_style 推荐风格
  - [ ] 11.2.6 更新 State 并记录决策

- [ ] 11.3 集成到 StateGraph
  - [ ] 11.3.1 在 `src/agents/graph.py` 添加 `content_analyzer` 节点
  - [ ] 11.3.2 修改边：director → content_analyzer → art_director → editor

- [ ] 11.4 单元测试
  - [ ] 11.4.1 创建 `tests/agents/test_content_analyzer.py`
  - [ ] 11.4.2 测试类型分类（使用 Mock LLM）
  - [ ] 11.4.3 测试角色提取
  - [ ] 11.4.4 测试风格推荐逻辑

---

### 12. VoiceDirector Agent 实现

- [ ] 12.1 实现 VoiceDirector Agent 类
  - [ ] 12.1.1 创建 `src/agents/voice_director.py`
  - [ ] 12.1.2 实现 `VoiceDirectorAgent` 类（见 design.md 4.4）
  - [ ] 12.1.3 定义 `EMOTION_TTS_PARAMS` 映射表
  - [ ] 12.1.4 实现 `analyze_emotion()` - LLM 情感分析
  - [ ] 12.1.5 实现 `_analyze_emotion_by_rules()` - 规则情感分析（省钱模式，暂占位）
  - [ ] 12.1.6 实现 `get_tts_params()` - 根据情感返回 TTS 参数

- [ ] 12.2 实现 VoiceDirector 节点函数
  - [ ] 12.2.1 实现 `voice_director_node(state: AgentState)`
  - [ ] 12.2.2 遍历 segments 分析情感
  - [ ] 12.2.3 调用 TTSTool 生成音频和字幕
  - [ ] 12.2.4 更新 State 并记录决策

- [ ] 12.3 集成到 StateGraph
  - [ ] 12.3.1 在 `src/agents/graph.py` 添加 `voice_director` 节点
  - [ ] 12.3.2 修改边：... → art_director → voice_director → editor

- [ ] 12.4 单元测试
  - [ ] 12.4.1 创建 `tests/agents/test_voice_director.py`
  - [ ] 12.4.2 测试情感分析（Mock LLM）
  - [ ] 12.4.3 测试 TTS 参数映射
  - [ ] 12.4.4 测试节点函数 State 更新

---

### 13. 图片质量自检与重试机制

- [ ] 13.1 实现 `EvaluateImageQualityTool`
  - [ ] 13.1.1 创建 `src/tools/evaluate_quality_tool.py`
  - [ ] 13.1.2 实现 GPT-4V 图片质量评估逻辑
    - [ ] 读取图片并转 base64
    - [ ] 构造评估 prompt（见 design.md 4.3）
    - [ ] 调用 `ChatOpenAI(model="gpt-4o")` vision API
    - [ ] 解析 JSON 响应为 `QualityEvaluation`
  - [ ] 13.1.3 添加 Gemini Vision 支持（可选）
    ```python
    if vision_provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp")
    ```

- [ ] 13.2 升级 ArtDirector Agent 支持质量控制
  - [ ] 13.2.1 在 `ArtDirectorAgent` 添加 `vision_llm` 属性
  - [ ] 13.2.2 实现 `evaluate_quality()` 方法（调用 EvaluateImageQualityTool）
  - [ ] 13.2.3 实现 `generate_with_quality_control()` 方法（见 design.md 4.3）
    - [ ] 生成图片 → 评估质量 → 判断是否重试
    - [ ] 重试逻辑：优化 prompt 后重新生成
    - [ ] 重试上限：3 次
  - [ ] 13.2.4 实现 `_optimize_prompt_based_on_feedback()` - 根据反馈优化 prompt

- [ ] 13.3 更新 ArtDirector 节点函数
  - [ ] 13.3.1 修改 `art_director_node()` 调用 `generate_with_quality_control()`
  - [ ] 13.3.2 记录质量评分到 `state["quality_scores"]`
  - [ ] 13.3.3 记录重试次数到 `state["retry_counts"]`
  - [ ] 13.3.4 在决策日志中记录每次质量检查和重试

- [ ] 13.4 测试质量控制循环
  - [ ] 13.4.1 创建 `tests/tools/test_evaluate_quality.py`
  - [ ] 13.4.2 Mock GPT-4V API 响应
  - [ ] 13.4.3 测试质量评分解析
  - [ ] 13.4.4 在 `test_art_director.py` 测试重试逻辑
  - [ ] 13.4.5 端到端测试：使用低质量 prompt，验证触发重试

---

### 14. 断点续传支持

- [ ] 14.1 State 持久化机制
  - [ ] 14.1.1 在 `AgentPipeline._save_state()` 保存完整 State 到 `agent_state.json`
  - [ ] 14.1.2 在每个节点完成后调用 `_save_state()`
  - [ ] 14.1.3 实现 `_load_state()` 加载已保存的 State

- [ ] 14.2 断点续传逻辑
  - [ ] 14.2.1 在 `AgentPipeline.__init__()` 检查 `--resume` 参数
  - [ ] 14.2.2 如果 `resume=True` 且 `agent_state.json` 存在
    - [ ] 加载已保存的 State
    - [ ] 读取 `last_node` 字段，确定从哪个节点继续
  - [ ] 14.2.3 LangGraph 支持从中间节点启动（研究 API）
  - [ ] 14.2.4 跳过已完成节点，继续后续流程

- [ ] 14.3 测试断点续传
  - [ ] 14.3.1 运行 Agent 模式到一半后中断（Ctrl+C）
  - [ ] 14.3.2 验证 `agent_state.json` 包含中间结果
  - [ ] 14.3.3 运行 `python main.py run input.txt --mode agent --resume`
  - [ ] 14.3.4 验证跳过已完成节点，从断点继续
  - [ ] 14.3.5 验证最终视频生成成功

---

### 15. 配置文件扩展

- [ ] 15.1 扩展 `config.yaml`
  - [ ] 15.1.1 添加 `agent:` 顶级配置节
  - [ ] 15.1.2 添加 `quality_check:` 子配置
    ```yaml
    agent:
      quality_check:
        enabled: true
        threshold: 6.0
        max_retries: 3
        vision_provider: openai  # openai | gemini
    ```
  - [ ] 15.1.3 添加 `decisions:` 子配置
    ```yaml
    agent:
      decisions:
        enabled: true
        file: agent_decisions.json
        verbose: true
    ```

- [ ] 15.2 更新 `config_manager.py`
  - [ ] 15.2.1 在 `_validate()` 添加 `agent` 配置验证（可选字段）
  - [ ] 15.2.2 提供默认值（如果配置缺失）

- [ ] 15.3 测试配置加载
  - [ ] 15.3.1 创建测试配置文件 `tests/fixtures/test_config_agent.yaml`
  - [ ] 15.3.2 验证加载成功并应用到 AgentPipeline

---

### 16. 集成测试与验收

- [ ] 16.1 端到端测试（标准模式）
  - [ ] 16.1.1 准备 500 字测试小说（包含角色、情感变化）
  - [ ] 16.1.2 运行 `python main.py run test.txt --mode agent`
  - [ ] 16.1.3 验证生成视频质量
  - [ ] 16.1.4 检查 `agent_decisions.json`
    - [ ] 包含 5 个 Agent 的决策记录
    - [ ] 包含质量评分和重试记录
    - [ ] 包含情感分析结果

- [ ] 16.2 对比测试（Classic vs Agent）
  - [ ] 16.2.1 同一小说分别用两种模式生成
  - [ ] 16.2.2 对比生成时间（记录到文档）
  - [ ] 16.2.3 对比视频质量（主观评价）
  - [ ] 16.2.4 对比 API 成本（根据决策日志计算）

- [ ] 16.3 压力测试
  - [ ] 16.3.1 使用 2000 字长文本测试
  - [ ] 16.3.2 验证质量检查不会导致超时
  - [ ] 16.3.3 验证重试次数合理（不会无限重试）

- [ ] 16.4 提交 Phase 2 完成
  - [ ] 16.4.1 提交代码：`git commit -m "feat: Phase 2 - 完整 5 Agent 体系 + 质量自检"`
  - [ ] 16.4.2 标记里程碑：`git tag v0.6.0-beta-agent`

---

## Phase 3: 优化与增强（1 周）

**目标**: 实现省钱模式、性能优化、成本监控、文档完善。

### 17. 省钱模式（Budget Mode）

- [ ] 17.1 配置扩展
  - [ ] 17.1.1 在 `config.yaml` 添加 `budget_mode:` 配置
    ```yaml
    agent:
      budget_mode:
        disable_quality_check: true
        use_cheap_llm: true
        simple_emotion_analysis: true
    ```
  - [ ] 17.1.2 在 `main.py` CLI 支持 `--budget-mode` flag

- [ ] 17.2 ContentAnalyzer 省钱逻辑
  - [ ] 17.2.1 完善 `_classify_genre_by_rules()` 规则分类
  - [ ] 17.2.2 实现简单正则提取角色（替代 LLM）
  - [ ] 17.2.3 在 `budget_mode=True` 时自动切换

- [ ] 17.3 ArtDirector 省钱逻辑
  - [ ] 17.3.1 在 `budget_mode=True` 时跳过质量检查
  - [ ] 17.3.2 Prompt 生成改用 DeepSeek（在 PromptGenTool 中实现）
  - [ ] 17.3.3 记录决策日志说明省钱模式已启用

- [ ] 17.4 VoiceDirector 省钱逻辑
  - [ ] 17.4.1 完善 `_analyze_emotion_by_rules()` 规则情感分析
  - [ ] 17.4.2 在 `budget_mode=True` 时自动切换

- [ ] 17.5 LLM 后端切换
  - [ ] 17.5.1 在各 Agent 初始化时检测 `budget_mode`
  - [ ] 17.5.2 如果启用，使用 DeepSeek 替代 GPT-4o-mini
    ```python
    if budget_mode:
        self.llm = ChatOpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            model="deepseek-chat"
        )
    ```

- [ ] 17.6 测试省钱模式
  - [ ] 17.6.1 运行 `python main.py run test.txt --mode agent --budget-mode`
  - [ ] 17.6.2 验证未调用 GPT-4V（检查决策日志）
  - [ ] 17.6.3 对比成本：标准模式 vs 省钱模式（计算 API 调用）
  - [ ] 17.6.4 验证成本降低 ≥ 40%

---

### 18. 成本追踪与监控

- [ ] 18.1 实现 `CostTracker` 类
  - [ ] 18.1.1 创建 `src/agents/cost_tracker.py`
  - [ ] 18.1.2 定义各 LLM API 价格常量（见 design.md 12.2）
  - [ ] 18.1.3 实现 `add_call()` - 记录单次 API 调用
  - [ ] 18.1.4 实现 `total_cost()` - 计算总成本
  - [ ] 18.1.5 实现 `get_breakdown()` - 按模型分类成本

- [ ] 18.2 集成到 AgentPipeline
  - [ ] 18.2.1 在 `AgentPipeline.__init__()` 初始化 `CostTracker`
  - [ ] 18.2.2 在各 Tool 调用 LLM 后记录 token 使用量
  - [ ] 18.2.3 在 `run()` 完成后保存成本报告到决策日志

- [ ] 18.3 决策日志扩展
  - [ ] 18.3.1 在 `agent_decisions.json` 添加 `summary.cost_breakdown`
    ```json
    "summary": {
      "total_cost": 1.23,
      "cost_breakdown": {
        "gpt-4o-mini": 0.15,
        "gpt-4o-vision": 0.90,
        "deepseek-chat": 0.18
      }
    }
    ```

- [ ] 18.4 测试成本追踪
  - [ ] 18.4.1 运行完整流程并检查决策日志
  - [ ] 18.4.2 验证成本计算准确性（与实际 API 账单对比）

---

### 19. 性能优化

- [ ] 19.1 图片生成并行化（可选）
  - [ ] 19.1.1 研究 LangGraph 异步节点支持
  - [ ] 19.1.2 实现 `art_director_node_async()`
  - [ ] 19.1.3 使用 `asyncio.gather()` 并行生成前 N 张图片
  - [ ] 19.1.4 性能测试：对比同步 vs 异步耗时

- [ ] 19.2 缓存机制
  - [ ] 19.2.1 在 `ContentAnalyzerAgent.classify_genre()` 添加 `@lru_cache`
  - [ ] 19.2.2 缓存类型分类结果（避免重复分析相同文本）
  - [ ] 19.2.3 验证缓存命中率（日志记录）

- [ ] 19.3 批处理优化（如果后端支持）
  - [ ] 19.3.1 研究 Together.ai / SiliconFlow 批量 API
  - [ ] 19.3.2 在 `ImageGenTool` 实现 `invoke_batch()` 方法
  - [ ] 19.3.3 ArtDirector 使用批量生成（如果配置启用）

---

### 20. CLI 增强

- [ ] 20.1 扩展 `status` 命令
  - [ ] 20.1.1 在 `main.py` 的 `status` 命令添加 `--decisions` flag
  - [ ] 20.1.2 实现决策日志可视化
    - [ ] 使用 Rich Table 展示各 Agent 决策次数
    - [ ] 展示重试统计
    - [ ] 展示平均质量评分
    - [ ] 展示预估成本

- [ ] 20.2 测试 CLI
  - [ ] 20.2.1 运行 `python main.py status workspace/novel/ --decisions`
  - [ ] 20.2.2 验证输出清晰易读

---

### 21. 文档完善

- [ ] 21.1 更新 README.md
  - [ ] 21.1.1 添加 Agent 模式详细介绍
  - [ ] 21.1.2 添加省钱模式使用示例
  - [ ] 21.1.3 添加质量控制说明
  - [ ] 21.1.4 添加成本预估表格

- [ ] 21.2 创建 Agent 模式文档
  - [ ] 21.2.1 完善 `docs/agent_mode_guide.md`
  - [ ] 21.2.2 说明各 Agent 职责
  - [ ] 21.2.3 提供决策日志示例
  - [ ] 21.2.4 FAQ（常见问题）

- [ ] 21.3 创建配置参考文档
  - [ ] 21.3.1 创建 `docs/agent_config_reference.md`
  - [ ] 21.3.2 列出所有 `agent.*` 配置项
  - [ ] 21.3.3 说明各参数含义和默认值

- [ ] 21.4 创建迁移指南
  - [ ] 21.4.1 创建 `docs/migration_to_agent.md`
  - [ ] 21.4.2 说明如何从 Classic 模式迁移到 Agent 模式
  - [ ] 21.4.3 对比两种模式差异
  - [ ] 21.4.4 提供最佳实践建议

---

### 22. 测试与质量保证

- [ ] 22.1 单元测试覆盖率
  - [ ] 22.1.1 运行 `pytest --cov=src/agents --cov=src/tools`
  - [ ] 22.1.2 确保覆盖率 ≥ 80%
  - [ ] 22.1.3 补充缺失测试

- [ ] 22.2 集成测试
  - [ ] 22.2.1 创建 `tests/integration/test_agent_e2e.py`
  - [ ] 22.2.2 测试完整流程（多种小说类型）
    - [ ] 武侠小说
    - [ ] 都市小说
    - [ ] 科幻小说
  - [ ] 22.2.3 验证决策日志完整性
  - [ ] 22.2.4 验证视频质量

- [ ] 22.3 回归测试
  - [ ] 22.3.1 确保 Classic 模式功能完全不受影响
  - [ ] 22.3.2 运行现有所有测试套件
  - [ ] 22.3.3 修复任何回归问题

---

### 23. 性能基准测试

- [ ] 23.1 建立基准
  - [ ] 23.1.1 创建 `benchmarks/benchmark_agent.py`
  - [ ] 23.1.2 测试 1000 字小说处理时间
    - [ ] Classic 模式
    - [ ] Agent 模式（无质量检查）
    - [ ] Agent 模式（含质量检查）
    - [ ] Agent 模式（省钱模式）

- [ ] 23.2 记录结果
  - [ ] 23.2.1 创建 `benchmarks/results.md`
  - [ ] 23.2.2 记录各模式耗时、成本、质量评分
  - [ ] 23.2.3 绘制对比图表（可选）

---

### 24. 发布准备

- [ ] 24.1 版本号更新
  - [ ] 24.1.1 更新 `pyproject.toml` version 为 `0.7.0`
  - [ ] 24.1.2 更新 CHANGELOG.md（新增 Agent 模式相关条目）

- [ ] 24.2 示例与演示
  - [ ] 24.2.1 创建 `examples/agent_demo.py` 脚本
  - [ ] 24.2.2 录制演示视频（可选）
  - [ ] 24.2.3 准备示例输入输出（放入 `examples/` 目录）

- [ ] 24.3 提交 Phase 3 完成
  - [ ] 24.3.1 提交代码：`git commit -m "feat: Phase 3 - 省钱模式 + 性能优化 + 完整文档"`
  - [ ] 24.3.2 标记正式版本：`git tag v0.7.0`
  - [ ] 24.3.3 推送到远程仓库

---

## 验收检查清单

在所有 Phase 完成后，逐项检查以下验收标准：

### 功能完整性

- [ ] AC-1: 双模式切换
  - [ ] `--mode classic` 使用现有 Pipeline
  - [ ] `--mode agent` 使用 LangGraph Agent
  - [ ] 两种模式生成视频质量对比：Agent ≥ Classic

- [ ] AC-2: 质量自检生效
  - [ ] 使用低质量 prompt 触发重试
  - [ ] `agent_decisions.json` 包含质量检查记录
  - [ ] 最终图片评分 ≥ 6 分

- [ ] AC-3: 省钱模式
  - [ ] `--budget-mode` 关闭 GPT-4V 评估
  - [ ] 决策日志显示 `budget_mode: true`
  - [ ] 成本降低 ≥ 40%

- [ ] AC-4: 决策日志完整性
  - [ ] 包含所有 5 个 Agent 的决策
  - [ ] 包含 `summary` 统计字段
  - [ ] JSON 格式正确，可解析

- [ ] AC-5: 断点续传
  - [ ] 中途中断后 `--resume` 成功继续
  - [ ] 跳过已完成节点
  - [ ] 最终视频生成成功

- [ ] AC-6: 角色一致性
  - [ ] 所有 prompt 包含一致的角色描述
  - [ ] 视频中角色外观差异 ≤ 可接受范围

- [ ] AC-7: 性能基准
  - [ ] Agent 模式（省钱）耗时 / Classic 耗时 ≤ 1.2

### 代码质量

- [ ] 单元测试覆盖率 ≥ 80%
- [ ] 所有测试通过（`pytest tests/`）
- [ ] 无 lint 错误（`ruff check src/`）
- [ ] 类型检查通过（`mypy src/` 可选）

### 文档完整性

- [ ] README.md 包含 Agent 模式说明
- [ ] `docs/agent_mode_guide.md` 存在且完整
- [ ] `docs/agent_config_reference.md` 存在且完整
- [ ] `docs/migration_to_agent.md` 存在且完整
- [ ] CHANGELOG.md 记录所有变更

### 向后兼容

- [ ] Classic 模式功能完全不受影响
- [ ] 现有配置文件无需修改即可使用
- [ ] 现有测试套件全部通过

---

## 后续优化方向（Post-MVP，不在当前 Scope）

以下功能可在后续版本迭代：

- [ ] Human-in-the-Loop 交互模式
- [ ] Web UI 可视化 Agent 决策流程
- [ ] A/B 测试框架（生成多版本自动对比）
- [ ] 风格迁移 Agent（学习用户偏好）
- [ ] 多模态检索（主动搜索参考图片）
- [ ] 分布式执行（多片段并行处理）
- [ ] Cost Optimizer Agent（实时成本监控与优化）

---

**文档版本**: v1.0
**最后更新**: 2026-03-09
**作者**: AI Planning Assistant
**状态**: 待实施
