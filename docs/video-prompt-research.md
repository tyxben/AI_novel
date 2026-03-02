# Video Prompt Research - 视频 Prompt 工程研究报告

## 1. 现有 promptgen 架构分析

### 1.1 模块结构

```
src/promptgen/
  __init__.py              # 导出 PromptGenerator, CharacterTracker, get_preset, list_presets
  prompt_generator.py      # 核心生成器，支持 LLM 模式和本地关键词模式
  style_presets.py          # 风格预设系统（YAML + 内建后备）
  character_tracker.py      # 角色外观一致性追踪
```

### 1.2 PromptGenerator 核心逻辑

**双模式架构**：
- **LLM 模式**：当有可用的 LLM provider 时（Gemini/DeepSeek/OpenAI/Ollama），使用系统提示词 `_SYSTEM_PROMPT` 指导 LLM 将中文小说文本转换为英文 SD prompt
- **本地模式**：无 API 时，通过正则规则匹配场景关键词，拼接为 prompt

**关键流程**（`generate()` 方法）：
1. CharacterTracker 提取角色名并返回已知角色的英文描述
2. LLM 模式：将原文 + 角色描述 + 风格名发给 LLM，返回英文 SD prompt
3. 本地模式：时代检测 -> 规则匹配 -> 性别适配 -> 风格前缀/后缀拼接
4. 更新 CharacterTracker（从生成的 prompt 中学习角色描述）

**时代自动检测**：
- 统计现代关键词 vs 古风关键词出现频次
- 根据结果选择 `_MODERN_RULES` 或 `_CLASSICAL_RULES` 规则集
- 支持 `set_full_text()` 缓存全文判断结果

**LLM 系统提示词要点**：
- 分析场景、角色、动作、情绪
- 输出英文 SD prompt（逗号分隔短语）
- 包含场景描述、角色外观、动作姿态、光影氛围、画面构图
- 突出画面感，忽略对话内容

### 1.3 风格预设系统（style_presets.py）

**数据结构**：每个预设包含 `positive`、`negative`、`prefix` 三个字段
- `prefix`：画面类型前缀（如 "masterpiece ink painting of"）
- `positive`：正向画质/风格关键词
- `negative`：负向关键词（SD 专用，视频生成不一定支持）

**内建预设**：chinese_ink, anime, realistic, watercolor, cyberpunk

**扩展机制**：从 `presets/styles/*.yaml` 加载自定义预设，覆盖/补充内建预设

### 1.4 角色追踪器（character_tracker.py）

**功能**：维护 `角色名 -> 英文外观描述` 映射，保持跨片段的视觉一致性

**角色名提取**：
- 模式1：「汉字姓名 + 动词」结构（如 "宝玉笑道"）
- 模式2：引号中的 2-4 字称呼
- 排除代词、副词、常见名词等非人名词语

**描述学习**：从生成的英文 prompt 中用正则提取人物描述，关联到角色名。首次描述优先，后续不覆盖。

**序列化**：`to_dict()` / `from_dict()` 支持断点续传

---

## 2. 视频 Prompt vs 图片 Prompt 的关键差异

### 2.1 核心区别

| 维度 | 图片 Prompt (SD) | 视频 Prompt (Kling/Seedance) |
|------|------------------|------------------------------|
| **格式** | 逗号分隔的关键词短语 | 自然语言描述的完整句子 |
| **时间性** | 单一静态瞬间 | 有时间维度，描述动作过程 |
| **运镜** | 仅构图（俯视/特写等） | 需要描述相机运动轨迹 |
| **动作描述** | 静态姿态（standing, sitting） | 动态过程（slowly walks, turns around） |
| **负向提示** | 广泛使用 negative prompt | Seedance 不支持；Kling 支持但使用方式不同 |
| **画质词** | "masterpiece, best quality, 8k" | "4K, cinematic, sharp clarity" |
| **风格锚定** | 关键词叠加（"anime style, cel shading"） | 更偏叙述性描述 |
| **技术参数** | 无 | 可指定虚拟镜头参数（35mm, f/2.8 等作为风格暗示） |

### 2.2 视频 Prompt 的独有要素

1. **运镜指令**：必须描述相机如何移动（dolly in, orbit, tracking shot）
2. **动作节奏**：需要修饰动作速度（slowly, gently, gradually）
3. **时序描述**：可以描述镜头内的时间变化（"starts with... then reveals..."）
4. **物理约束**：需要描述符合物理规则的运动
5. **一致性约束词**：Seedance 需要明确添加 "stable face, no distortion"
6. **持续时间意识**：视频有时长限制（5-10秒），prompt 中的动作量需匹配

### 2.3 从图片 Prompt 到视频 Prompt 的转换要点

图片 prompt 示例：
```
beautiful young woman in traditional Chinese hanfu, standing in bamboo forest, moonlight, cinematic lighting, masterpiece
```

视频 prompt 转换后：
```
A beautiful young woman in flowing traditional Chinese hanfu stands gracefully in a moonlit bamboo forest. The camera slowly dollies in toward her face as gentle wind moves through the bamboo leaves. Soft moonlight filters through the canopy, creating dappled shadows. Cinematic quality, 4K, natural and smooth movements.
```

---

## 3. 运镜描述术语总结

### 3.1 中英文对照（八字口诀 + 扩展）

| 中文术语 | 英文术语 | AI视频Prompt写法 | 效果 |
|---------|---------|------------------|------|
| **推** | Dolly In / Push In | "camera slowly dollies in toward..." | 靠近主体，聚焦细节 |
| **拉** | Dolly Out / Pull Back | "camera pulls back to reveal..." | 远离主体，展示环境 |
| **摇（水平）** | Pan Left/Right | "camera pans slowly to the right..." | 水平扫视场景 |
| **摇（垂直）** | Tilt Up/Down | "camera tilts up from feet to face..." | 垂直扫视 |
| **移** | Truck / Tracking Shot | "side tracking shot following..." | 平行移动跟随 |
| **跟** | Follow Shot | "camera follows the character as..." | 跟随主体运动 |
| **升** | Boom Up / Crane Up | "camera rises upward revealing..." | 垂直上升 |
| **降** | Boom Down / Crane Down | "camera descends from above..." | 垂直下降 |
| **甩** | Whip Pan / Swish Pan | "quick whip pan to the left..." | 快速甩镜，带模糊 |
| **环绕** | Orbit / Arc Shot | "camera orbits 360 degrees around..." | 围绕主体旋转 |
| **变焦** | Zoom In/Out | "slow zoom into the character's eyes..." | 焦距变化（相机不动） |
| **滑轨升降** | Pedestal Up/Down | "camera pedestals up from street level..." | 整体升降（不同于 tilt） |
| **航拍** | Drone Shot / Aerial | "high altitude drone shot over..." | 高空俯瞰 |
| **第一人称** | POV / First Person | "POV shot of hands opening a door..." | 主观视角 |
| **斯坦尼康** | Steadicam | "smooth steadicam follows character..." | 平滑跟拍 |
| **手持** | Handheld | "handheld camera, slight shake..." | 真实感/紧张感 |
| **定镜** | Static / Fixed | "static shot, no camera movement..." | 固定不动 |

### 3.2 复合运镜

| 名称 | Prompt 写法 | 效果 |
|------|------------|------|
| 推拉变焦（眩晕效果） | "dolly zoom / vertigo effect" | 主体不变，背景透视扭曲 |
| 升降+摇 | "crane up while panning right" | 上升同时水平转向 |
| 跟拍+环绕 | "tracking with slight orbit around subject" | 跟随中带旋转 |
| 推进+聚焦转移 | "dolly in with rack focus from background to foreground" | 推进同时焦点切换 |
| 螺旋上升 | "spiral camera movement rising upward" | 螺旋式上升 |

### 3.3 情绪导向运镜选择建议

| 情绪/场景类型 | 推荐运镜 | 原因 |
|-------------|---------|------|
| 紧张/悬疑 | 缓慢 Dolly In + 手持微晃 | 逐渐压迫感 |
| 孤独/悲伤 | Crane Up 远离角色 | 角色显得渺小孤独 |
| 震撼/壮阔 | Drone 航拍 + Pan | 展示宏大场景 |
| 对话/日常 | 静镜 Static + 切换 | 稳定、自然 |
| 动作/追逐 | Tracking / Follow + 快速 | 动感、紧迫 |
| 揭示/反转 | Pan-to-Reveal / Pull Back | 信息逐步展开 |
| 角色登场 | Tilt Up（从脚到头） | 建立角色形象 |
| 浪漫/温馨 | Slow Orbit + 柔光 | 优美、亲密 |

---

## 4. 推荐的视频 Prompt 模板设计方案

### 4.1 视频 Prompt 结构公式

基于 Kling、Seedance、Sora 等主流平台的最佳实践，推荐以下分层结构：

```
[主体描述] + [动作描述] + [场景/环境] + [光影氛围] + [运镜指令] + [风格/画质] + [约束词]
```

### 4.2 各层详解

**Layer 1 - 主体描述 (Subject)**
```
A [age] [gender] [character appearance] [clothing]
```
来源：复用 CharacterTracker 的角色描述

**Layer 2 - 动作描述 (Action)**
```
[adverb: slowly/gently/dramatically] [action verb] [details]
```
新增：需要从小说动作描写中提取，并添加速度/力度修饰词

**Layer 3 - 场景/环境 (Scene)**
```
in/at [location], [weather], [time of day], [ambient details]
```
来源：复用现有 `_MODERN_RULES` / `_CLASSICAL_RULES` 的场景匹配

**Layer 4 - 光影氛围 (Lighting & Mood)**
```
[lighting type], [color temperature], [atmosphere]
```
来源：复用现有氛围规则 + 扩展视频专用光影描述

**Layer 5 - 运镜指令 (Camera Movement)**
```
[Camera movement type] [direction] [speed] [target]
```
新增：根据场景情绪自动选择合适的运镜方式

**Layer 6 - 风格/画质 (Style & Quality)**
```
[style keywords], [quality keywords: 4K, cinematic, sharp]
```
来源：改造现有 style_presets，添加视频专用画质词

**Layer 7 - 约束词 (Constraints)**
```
[consistency: stable face, no distortion] [physics: natural movement]
```
新增：视频专用，保证画面质量

### 4.3 LLM 系统提示词模板（视频版）

```python
VIDEO_SYSTEM_PROMPT = """\
你是一个专业的 AI 视频 Prompt 工程师。你的任务是将中文小说片段转换为 AI 视频生成 Prompt。

要求:
1. 分析文本中的场景、角色、动作、情绪
2. 生成英文视频生成 prompt（自然语言完整句子，非关键词堆叠）
3. 必须包含以下层次:
   - 主体: 角色外观、服装、表情
   - 动作: 具体动作过程，添加速度修饰（slowly, gently, dramatically）
   - 场景: 环境、天气、时间
   - 光影: 光源类型、色温、氛围
   - 运镜: 选择合适的相机运动（dolly in, pan, orbit, tracking 等）
   - 画质: 4K, cinematic quality, natural colors
4. 运镜选择原则:
   - 紧张场景: slow dolly in + 手持感
   - 孤独场景: crane up 远离
   - 壮阔场景: drone/aerial shot
   - 日常对话: static shot
   - 动作场景: tracking/follow shot
   - 揭示场景: pan-to-reveal 或 pull back
5. 动作必须柔和自然，优先使用 slow、gentle、smooth 等修饰词
6. 末尾添加约束: "Stable character appearance, natural smooth movements, cinematic quality, 4K"
7. 如果有角色，保持其外观描述一致

输出格式: 仅输出英文 prompt 文本，不要包含任何解释或前缀。Prompt 应为 2-4 句完整的英文句子。
"""
```

### 4.4 本地模式运镜自动匹配规则

```python
# 根据文本情绪/场景自动选择运镜
_CAMERA_MOVEMENT_RULES = [
    # 紧张/悬疑 -> 缓慢推进
    (r"紧张|心跳|不对劲|危险|杀气|恐怖|诡异", "The camera slowly dollies in"),
    # 孤独/悲伤 -> 升降远离
    (r"孤独|一个人|独自|离去|远去|消失", "The camera slowly cranes upward, pulling away"),
    # 壮阔场景 -> 航拍
    (r"山顶|战场|全城|远方|天地|苍茫", "Aerial drone shot sweeping over"),
    # 角色登场 -> 从下往上
    (r"出现|走来|现身|登场|站在.*面前", "The camera tilts up from ground level"),
    # 对话/日常 -> 静镜
    (r"说道|问道|笑道|答道|聊|谈", "Static medium shot"),
    # 追逐/动作 -> 跟拍
    (r"追|跑|逃|冲|飞|闪|躲", "Tracking shot following"),
    # 环顾/展示 -> 环绕
    (r"环顾|四周|周围|打量|审视", "The camera slowly orbits around"),
    # 揭示/发现 -> 拉镜
    (r"发现|原来|看到|映入|展现|豁然", "The camera pulls back to reveal"),
    # 回忆/梦境 -> 缓慢zoom
    (r"回忆|想起|记得|梦|往事|从前", "Slow zoom in with soft focus"),
    # 默认 -> 轻微推进
    (r".*", "Gentle dolly in"),
]
```

### 4.5 完整示例

**输入文本**：
> 夜深了，林晚从办公室走出来，拉紧了外套。街灯把她的影子拉得很长。她低着头，耳机里播放着一首老歌，独自走在空荡荡的街道上。

**生成的视频 Prompt**：
```
A young woman in a dark coat walks out of a modern office building into the quiet night.
She pulls her coat tighter and lowers her head, wearing earphones, walking alone down an
empty city street. The camera slowly cranes upward, pulling away to reveal her solitary
figure under warm street lamps that cast long shadows on the pavement. Late night atmosphere,
dim amber street lighting, soft bokeh from distant city lights. Cinematic quality, 4K,
natural smooth movements, stable character appearance, melancholic mood.
```

---

## 5. 如何复用现有 CharacterTracker 和 StylePresets

### 5.1 CharacterTracker 复用方案

**直接复用**：
- 角色名提取逻辑（`extract_characters()`）完全适用于视频 prompt
- 角色描述映射（`_characters` 字典）可直接用于视频 prompt 的主体描述层
- 序列化/反序列化（`to_dict()` / `from_dict()`）用于断点续传

**需要扩展**：
- `get_character_prompt()` 当前返回逗号分隔的 SD 关键词片段，视频模式需要返回自然语言描述
- 可添加 `get_character_prompt_video()` 方法，或在现有方法中添加 `mode` 参数

**建议的接口扩展**：
```python
def get_character_prompt(self, characters: list[str], mode: str = "image") -> str:
    """
    mode="image": 返回 SD 风格逗号分隔关键词（现有行为）
    mode="video": 返回自然语言描述句子
    """
```

- `update()` 方法中从 prompt 提取角色描述的正则 `_DESCRIPTION_PATTERN` 需要适配视频 prompt 的自然语言格式（当前仅匹配 SD 关键词风格的描述）

### 5.2 StylePresets 复用方案

**现有预设结构**：
```python
{
    "positive": "风格正向关键词",
    "negative": "风格负向关键词",
    "prefix": "画面类型前缀",
}
```

**视频预设需要扩展的字段**：
```python
{
    # 原有字段（图片模式继续使用）
    "positive": "...",
    "negative": "...",
    "prefix": "...",

    # 新增视频字段
    "video_style": "cinematic quality, 4K, natural colors",       # 视频画质词
    "video_mood": "soft lighting, warm atmosphere",                # 视频氛围词
    "video_constraints": "stable face, no distortion, natural smooth movements",  # 约束词
    "default_camera": "gentle dolly in",                          # 默认运镜
}
```

**建议的视频风格预设**：

```yaml
# presets/styles/chinese_ink_video.yaml
name: chinese_ink_video
video_style: "cinematic Chinese ink painting style, flowing artistic quality, 4K"
video_mood: "traditional Chinese aesthetic, ethereal atmosphere, muted elegant colors"
video_constraints: "stable character appearance, smooth natural movements, no distortion"
default_camera: "slow dolly in"

# presets/styles/anime_video.yaml
name: anime_video
video_style: "anime cinematic style, vibrant colors, detailed animation quality, 4K"
video_mood: "dynamic anime atmosphere, expressive lighting"
video_constraints: "consistent character design, smooth animation, no flickering"
default_camera: "tracking shot"

# presets/styles/realistic_video.yaml
name: realistic_video
video_style: "photorealistic cinematic quality, 4K, shallow depth of field"
video_mood: "natural lighting, authentic atmosphere"
video_constraints: "stable face, no morphing, natural physics, smooth movements"
default_camera: "gentle dolly in"
```

### 5.3 PromptGenerator 扩展策略

推荐**在现有 PromptGenerator 中添加视频模式**，而不是创建独立的 VideoPromptGenerator：

```python
class PromptGenerator:
    def __init__(self, config: dict) -> None:
        # ... 现有初始化 ...
        self._mode: str = config.get("prompt_mode", "image")  # "image" | "video"

    def generate(self, text: str, segment_index: int) -> str:
        if self._mode == "video":
            return self._generate_video(text, segment_index)
        return self._generate_image(text, segment_index)  # 原有逻辑
```

这样可以最大程度复用时代检测、角色追踪、风格预设等基础设施。

### 5.4 平台适配层

不同视频平台对 prompt 有细微差异，建议在生成基础视频 prompt 后，添加平台适配层：

```python
def _adapt_for_platform(self, prompt: str, platform: str) -> str:
    """针对不同视频生成平台微调 prompt"""
    if platform == "kling":
        # Kling 支持 negative prompt，可附加
        # Kling 偏好 cinematic phrasing
        prompt += ", cinematic, high quality"
    elif platform == "seedance":
        # Seedance 不支持 negative prompt
        # 需要用正向约束替代
        prompt += ". Stable character appearance, no distortion, natural smooth movements, 4K ultra HD."
    return prompt
```

---

## 参考来源

- [Cinematic AI video prompts: 2026 expert playbook](https://www.truefan.ai/blogs/cinematic-ai-video-prompts-2026)
- [Kling 2.6 Pro Prompt Guide](https://fal.ai/learn/devs/kling-2-6-pro-prompt-guide)
- [Kling 2.5 Prompt Guide: 70+ Camera Movement Commands](https://www.hixx.ai/blog/ai-industry-insights/kling-25-prompt)
- [Cinematic Camera Movements in Kling AI](https://blog.segmind.com/cinematic-ai-camera-movements-in-kling-ai-1-6-top-7-types/)
- [Seedance 2.0 Prompt Mastery Guide](https://blog.wenhaofree.com/en/posts/articles/seedance-2-0-prompt-mastery-guide/)
- [Seedance 2.0 Video Generation Guide](https://videoweb.ai/blog/detail/Seedance-2-0-Video-Generation-Guide-Tutorial-Prompts-578fb91b8f46/)
- [Gen-4 Video Prompting Guide - Runway](https://help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide)
- [Sora 2 Prompt Guide](https://www.atlabs.ai/blog/sora-2-prompt-guide)
- [运镜技巧中英文对照 (CSDN)](https://blog.csdn.net/qq_41176800/article/details/126434104)
