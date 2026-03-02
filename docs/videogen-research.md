# 视频生成模块研究报告

## 1. 现有架构分析

### 1.1 imagegen 多后端架构设计模式

项目已有的 `src/imagegen/` 模块采用了清晰的**抽象基类 + 工厂函数**设计模式，适合作为 videogen 的参考模板。

#### 核心结构

```
src/imagegen/
  __init__.py              # 空（重新导出在 image_generator.py）
  image_generator.py       # 抽象基类 ImageGenerator + 工厂函数 create_image_generator()
  diffusers_backend.py     # 本地 Stable Diffusion 后端
  together_backend.py      # Together.ai 云端后端
  siliconflow_backend.py   # 硅基流动云端后端
  dashscope_backend.py     # 阿里云万相后端
```

#### 设计模式要点

1. **抽象基类 (`ImageGenerator`)**
   - 继承 `ABC`，定义唯一抽象方法 `generate(prompt: str) -> Image.Image`
   - 接口极简：所有后端只需实现一个方法
   - 返回统一类型 `PIL.Image.Image`

2. **工厂函数 (`create_image_generator(config: dict)`)**
   - 根据 `config["backend"]` 字段选择后端
   - 使用 **懒导入**（`from src.imagegen.xxx import XxxBackend`），避免未安装依赖时报错
   - 未知 backend 抛出 `ValueError`

3. **后端实现共同模式**
   - 构造函数接收 `config: dict`，从中读取各种配置参数
   - API Key 来源：`config.get("api_key") or os.environ.get("XXX_API_KEY")`
   - HTTP 客户端采用 **懒加载** (`_get_client()` / `_client = None`)
   - 提供 `close()` 方法和 `__del__` 析构
   - 云端后端使用 `httpx.Client(timeout=120)` 发起 REST 请求
   - 图片返回方式：base64 解码 或 URL 下载后转 PIL Image

4. **配置驱动**
   - `config.yaml` 中 `imagegen.backend` 指定后端名
   - 各后端特有参数（model, steps, width, height 等）也在同一 dict 中
   - 设备自动检测（`auto` -> CUDA > MPS > CPU）

### 1.2 流水线 (Pipeline) 架构

`src/pipeline.py` 中的 `Pipeline` 类编排 5 个阶段：

```
Stage 1: 文本分段 (_stage_segment)   -> list[dict]
Stage 2: Prompt生成 (_stage_prompt)  -> list[str]
Stage 3: 图片生成 (_stage_image)     -> list[Path]
Stage 4: TTS配音 (_stage_tts)        -> list[dict{audio, srt}]
Stage 5: 视频合成 (_stage_video)     -> Path (最终MP4)
```

关键特征：
- **断点续传**: 每个阶段完成后通过 `Checkpoint` 标记，resume 时跳过已完成阶段
- **段级续传**: Stage 3/4 还支持跳过已生成的单个文件
- **配置合并**: 全局 LLM 配置与模块级配置通过 `{**global, **module}` 合并
- **进度通知**: `progress_callback(stage_num, total_stages, desc)` 回调
- **组件实例化**: 在各 stage 方法内部创建组件实例（而非构造时）

### 1.3 视频合成器 (VideoAssembler) 架构

`src/video/video_assembler.py` 当前采用 **静态图 + Ken Burns 特效** 方式：

```
输入: images(PNG) + audio_srt(MP3+SRT) -> 输出: MP4

流程:
1. 每段: 静态图片 + 音频 + SRT字幕 -> 制作片段视频
   - 解析 SRT，按字幕条目拆分子片段
   - 每个子片段: 图片烧录字幕 + Ken Burns zoom/pan + FFmpeg 编码
   - 子片段拼接 + 混入音频
2. 所有片段 concat 拼接
3. 可选混入 BGM
```

关键实现细节：
- Ken Burns 特效通过 FFmpeg `zoompan` 滤镜实现（`src/video/effects.py`）
- 字幕用 Pillow 渲染到图片上（非 FFmpeg drawtext），支持 CJK 字体
- 拼接使用 FFmpeg `concat demuxer`
- 分辨率默认 1080x1920（竖屏 9:16）

### 1.4 Prompt 生成

`src/promptgen/prompt_generator.py` 支持两种模式：
- **LLM 模式**: 使用统一 LLM 接口（支持 OpenAI/DeepSeek/Gemini/Ollama）
- **本地模式**: 基于正则规则匹配，自动区分现代/古风场景

当前 prompt 针对 Stable Diffusion 图片生成优化，后续需要适配视频生成 prompt。

---

## 2. 视频生成 API 调研

### 2.1 可灵 (Kling) API

**厂商**: 快手 (Kuaishou)
**官网**: https://klingai.com/global/dev

| 项目 | 详情 |
|------|------|
| **API Base URL** | `https://api.klingai.com` |
| **认证方式** | Bearer Token (`Authorization: Bearer {API_KEY}`) |
| **文生视频 Endpoint** | `POST /v1/videos/text2video` |
| **图生视频 Endpoint** | `POST /v1/videos/image2video` |
| **异步轮询** | 提交后返回 task_id，轮询任务状态直到完成 |
| **最大视频时长** | 5s / 10s（可通过视频续写扩展至 3 分钟） |
| **分辨率** | 最高 1080p |
| **宽高比** | 1:1, 16:9, 9:16, 4:3, 3:4, 2:3, 3:2, 21:9 |
| **支持图生视频** | 是（首帧/尾帧/多图参考） |

**请求示例 (Text-to-Video)**:
```json
POST /v1/videos/text2video
{
  "model": "kling-v2-6",
  "prompt": "A cat playing piano in a jazz club",
  "duration": 5,
  "aspect_ratio": "9:16",
  "mode": "std"
}
```

**响应**: 返回 `task_id`，轮询查询状态，完成后获取视频 URL。

**可用模型**: Kling-V3-Omni, Kling-Video-O1, Kling-V3, Kling-V2-6, Kling-V2-5-Turbo, Kling-V2-1, Kling-V1 等

**模式**: std (标准) / pro (专业) / master (大师)

**定价** (资源包单位制，1 unit ≈ $0.14):

| 模型 | 模式 | 时长 | 单位 | 约 USD |
|------|------|------|------|--------|
| Kling-V2-6 | std | 5s | 1.5 | $0.21 |
| Kling-V2-6 | std | 10s | 3.0 | $0.42 |
| Kling-V2-6 | pro | 5s | 2.5 | $0.35 |
| Kling-V2-6 | pro | 10s | 5.0 | $0.70 |
| Kling-V3 | std/s | 5s | 3.0 | $0.42 |
| Kling-V3 | pro/s | 5s | 4.0 | $0.56 |

### 2.2 即梦/Seedance API

**厂商**: 字节跳动 (ByteDance)
**平台**: 火山方舟 (Volcengine Ark) / 即梦 (Jimeng/Dreamina)
**官方文档**: https://www.volcengine.com/docs/82379/1366799

| 项目 | 详情 |
|------|------|
| **API Base URL** | 火山方舟 Endpoint（具体 URL 待官方最终发布确认） |
| **认证方式** | Bearer Token (`Authorization: Bearer {API_KEY}`) |
| **创建任务** | `POST /v1/video/generations` |
| **查询任务** | `GET /v1/video/generations/{task_id}` |
| **异步轮询** | 提交后返回 task_id，轮询间隔 ~5s |
| **最大视频时长** | 4-15 秒（可连续调整） |
| **分辨率** | 最高 2K |
| **宽高比** | 16:9, 9:16, 4:3, 3:4, 21:9, 1:1 |
| **支持图生视频** | 是（单图、首尾帧、多图最多9张） |

**请求示例 (Text-to-Video)**:
```json
POST /v1/video/generations
{
  "model": "seedance-2.0",
  "prompt": "文本描述",
  "aspect_ratio": "9:16",
  "duration": 5,
  "audio": false,
  "resolution": "1080p"
}
```

**请求示例 (Image-to-Video)**:
```json
{
  "model": "seedance-2.0",
  "prompt": "动画描述",
  "references": [
    {"type": "image", "data": "base64_encoded_string"}
  ],
  "aspect_ratio": "9:16",
  "duration": 6,
  "audio": false
}
```

**响应**:
```json
{
  "status": "processing",
  "data": {
    "task_id": "xxx",
    "url": "video_url",      // 完成后返回
    "status": "completed"
  }
}
```

**可用模型**: Seedance 2.0, Seedance 1.5-pro, Seedance 1.0-pro/lite

**独特功能**:
- 四模态输入（文本/图像/视频/音频）
- 原生音视频联合生成（自带配音能力）
- 最多 9 张参考图 + 3 个视频 + 3 个音频

**定价**: 按时长+分辨率计费，约 $0.10-$0.80/分钟（官方价格待确认）

### 2.3 MiniMax 海螺视频 (Hailuo)

**厂商**: MiniMax
**官方文档**: https://platform.minimax.io/docs/guides/video-generation

| 项目 | 详情 |
|------|------|
| **API Base URL** | `https://api.minimax.io` |
| **认证方式** | Bearer Token (`Authorization: Bearer {MINIMAX_API_KEY}`) |
| **创建任务** | `POST /v1/video_generation` |
| **查询状态** | `GET /v1/query/video_generation?task_id=xxx` |
| **获取文件** | `GET /v1/files/retrieve?file_id=xxx` |
| **异步轮询** | 提交 -> task_id -> 每10s轮询 -> file_id -> 下载URL |
| **最大视频时长** | 6s / 10s |
| **分辨率** | 512p / 768p / 1080p |
| **支持图生视频** | 是（首帧/首尾帧/角色参考） |

**请求示例 (Text-to-Video)**:
```json
POST /v1/video_generation
{
  "prompt": "A dancer performing contemporary dance",
  "model": "MiniMax-Hailuo-2.3",
  "duration": 6,
  "resolution": "1080P"
}
```

**请求示例 (Image-to-Video)**:
```json
{
  "prompt": "The figure starts dancing",
  "first_frame_image": "https://example.com/image.png",
  "model": "MiniMax-Hailuo-2.3",
  "duration": 6,
  "resolution": "1080P"
}
```

**异步轮询三步流程**:
1. 提交生成任务 -> 获得 `task_id`
2. 每 10s 轮询 `GET /v1/query/video_generation?task_id=xxx` -> 等待 `status: "Success"` -> 获得 `file_id`
3. `GET /v1/files/retrieve?file_id=xxx` -> 获得 `download_url`

**可用模型**: MiniMax-Hailuo-2.3, MiniMax-Hailuo-02, S2V-01

**定价** (按单位 unit 计费):

| 模型 | 分辨率 | 时长 | 单位 | 约 USD |
|------|--------|------|------|--------|
| Hailuo-2.3 | 768p | 6s | 1.0 | ~$0.25 |
| Hailuo-2.3 | 768p | 10s | 2.0 | ~$0.50 |
| Hailuo-2.3 | 1080p | 6s | 2.0 | ~$0.50 |
| Hailuo-02 | 512p | 6s | 0.3 | ~$0.08 |
| Hailuo-02 | 512p | 10s | 0.5 | ~$0.13 |

---

## 3. API 对比表

| 特性 | 可灵 (Kling) | 即梦/Seedance | MiniMax 海螺 |
|------|-------------|--------------|-------------|
| **厂商** | 快手 | 字节跳动 | MiniMax |
| **最新模型** | Kling-V3-Omni | Seedance 2.0 | Hailuo 2.3 |
| **Base URL** | api.klingai.com | 火山方舟 Endpoint | api.minimax.io |
| **认证** | Bearer Token | Bearer Token | Bearer Token |
| **文生视频** | 支持 | 支持 | 支持 |
| **图生视频** | 支持 | 支持(多图) | 支持 |
| **最大时长** | 10s (续写3min) | 15s | 10s |
| **最大分辨率** | 1080p | 2K | 1080p |
| **9:16 竖屏** | 支持 | 支持 | 支持 |
| **异步轮询** | task_id 轮询 | task_id 轮询 | task_id -> file_id 三步 |
| **原生音频** | V3 支持 | 支持(音视频联合) | 不支持 |
| **5s 视频价格** | ~$0.21 (std) | ~$0.10-0.40 | ~$0.25 (768p) |
| **10s 视频价格** | ~$0.42 (std) | ~$0.20-0.80 | ~$0.50 (768p) |
| **API 文档质量** | 完善,英文/中文 | 较新,中文为主 | 完善,英文/中文 |
| **SDK/生态** | 多第三方 | 火山方舟SDK | 官方Python示例 |

---

## 4. 推荐的 videogen 模块设计方案

### 4.1 整体架构（参照 imagegen 模式）

```
src/videogen/
  __init__.py                # 导出 VideoGenerator, create_video_generator
  video_generator.py         # 抽象基类 + 工厂函数
  kling_backend.py           # 可灵 API 后端
  seedance_backend.py        # 即梦/Seedance 后端
  minimax_backend.py         # MiniMax 海螺后端
```

### 4.2 抽象基类设计

```python
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass

@dataclass
class VideoResult:
    """视频生成结果。"""
    video_path: Path        # 下载后的本地视频文件路径
    duration: float         # 视频时长（秒）
    width: int              # 视频宽度
    height: int             # 视频高度

class VideoGenerator(ABC):
    """视频生成器抽象基类。"""

    @abstractmethod
    def generate(self, prompt: str, image_path: Path | None = None) -> VideoResult:
        """根据文本提示词（可选配合图片）生成视频。

        Args:
            prompt: 视频生成的文本提示词。
            image_path: 可选的首帧图片路径（图生视频模式）。

        Returns:
            VideoResult 包含本地视频路径和元信息。
        """
        ...
```

**相比 imagegen 的关键差异**:
- 返回 `VideoResult` dataclass（而非 PIL Image），因为视频需要本地文件路径 + 元数据
- 接口增加可选 `image_path` 参数，支持图生视频（利用已有的 imagegen 产出作为首帧）
- 所有云端 API 都是异步任务制，需要内部封装轮询逻辑

### 4.3 工厂函数

```python
def create_video_generator(config: dict) -> VideoGenerator:
    backend = config.get("backend", "kling")
    if backend == "kling":
        from src.videogen.kling_backend import KlingBackend
        return KlingBackend(config)
    elif backend == "seedance":
        from src.videogen.seedance_backend import SeedanceBackend
        return SeedanceBackend(config)
    elif backend == "minimax":
        from src.videogen.minimax_backend import MinimaxBackend
        return MinimaxBackend(config)
    else:
        raise ValueError(f"Unknown video backend: {backend}")
```

### 4.4 后端实现共同模式

每个后端需实现的核心逻辑：
1. `__init__`: 读取 config，获取 API Key（config 或环境变量）
2. `_get_client()`: 懒加载 httpx.Client
3. `_submit_task()`: 提交生成任务，获取 task_id
4. `_poll_task()`: 轮询任务状态，支持超时和重试
5. `_download_video()`: 下载生成的视频到本地
6. `generate()`: 编排上述步骤
7. `close()` + `__del__`: 资源清理

**异步轮询建议实现**:
```python
def _poll_task(self, task_id: str, timeout: int = 300, interval: int = 10) -> dict:
    """轮询任务状态直到完成或超时。"""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = self._query_task(task_id)
        if status["state"] == "completed":
            return status
        if status["state"] == "failed":
            raise RuntimeError(f"视频生成失败: {status.get('error', 'unknown')}")
        time.sleep(interval)
    raise TimeoutError(f"视频生成超时 ({timeout}s): task_id={task_id}")
```

### 4.5 config.yaml 扩展

```yaml
# 视频生成（新增）
videogen:
  backend: kling          # kling | seedance | minimax
  duration: 5             # 视频时长（秒）
  aspect_ratio: "9:16"    # 竖屏
  mode: std               # std | pro
  use_image_as_first_frame: true  # 是否用 imagegen 的图片作为首帧
  poll_interval: 10       # 轮询间隔（秒）
  poll_timeout: 300       # 轮询超时（秒）
  output_dir: videos      # workspace 下的视频子目录
  # --- 可灵 Kling ---
  # model: kling-v2-6
  # --- 即梦 Seedance ---
  # model: seedance-2.0
  # resolution: 1080p
  # --- MiniMax 海螺 ---
  # model: MiniMax-Hailuo-2.3
  # resolution: 1080P
```

### 4.6 Pipeline 集成方案

在 Pipeline 中增加一个可选阶段 **Stage 3.5: 视频片段生成**，位于图片生成之后、视频合成之前：

```
Stage 1: 文本分段
Stage 2: Prompt 生成
Stage 3: 图片生成（保留，可作为视频首帧）
Stage 3.5 [新增/可选]: AI 视频片段生成
Stage 4: TTS 配音
Stage 5: 视频合成（改造：支持视频片段输入）
```

当 `videogen.backend` 配置存在时，启用 Stage 3.5，将每段的图片 + prompt 提交给视频生成 API，获得短视频片段。Stage 5 的 VideoAssembler 需要改造：
- 当输入是视频片段时，跳过 Ken Burns 特效（因为 AI 视频已自带动态）
- 仅做字幕烧录（如果 TTS 字幕需要叠加）+ 音频替换 + 拼接

### 4.7 推荐优先实现顺序

1. **MiniMax (Hailuo)** - API 文档最完善、异步流程清晰、定价透明，适合先实现
2. **可灵 (Kling)** - 模型丰富、生态成熟，作为第二个后端
3. **Seedance** - 技术最先进（2K/15s/音视频联合），但 API 仍较新，作为第三个

---

## 5. 参考资料

- 可灵官方文档: https://klingai.com/global/dev
- 可灵定价: https://klingai.com/global/dev/model/video
- 即梦/Seedance 火山引擎文档: https://www.volcengine.com/docs/82379/1366799
- Seedance API 指南: https://help.apiyi.com/en/seedance-2-api-video-generation-guide-en.html
- MiniMax 官方文档: https://platform.minimax.io/docs/guides/video-generation
- MiniMax 定价: https://platform.minimax.io/docs/pricing/video-package
