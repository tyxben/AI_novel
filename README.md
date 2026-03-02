# 🎬 AI 小说转视频

> 小说文本一键转短视频 — 输入文字，输出可直接发布到抖音/小红书的竖屏视频。

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-v0.4.0-orange)]()

---

## 功能亮点

- **AI 自动写故事** — LLM 智能分段 + 自动生成画面描述，小说秒变分镜脚本
- **多 LLM 后端** — Gemini（免费）/ DeepSeek / OpenAI / Ollama（本地离线），自动检测可用 Key
- **多图片生成后端** — SiliconFlow（免费）/ 阿里云万相 / Together.ai / 本地 Stable Diffusion
- **AI 视频片段生成** `NEW` — 可灵 Kling / 即梦 Seedance / MiniMax 海螺 / OpenAI Sora，让画面动起来
- **免费 TTS 配音** — 微软 edge-tts 高质量语音合成 + SRT 字幕自动生成
- **H.265 编码** — 相比 H.264 体积减少约一半，画质不变
- **Ken Burns 特效** — 图片自动缩放平移，告别静态幻灯片感
- **Web UI** — 基于 Gradio 的可视化界面，无需命令行知识
- **CLI 命令行** — Click 驱动的完整 CLI，适合批量处理和脚本集成
- **断点续传** — 中断后从上次进度继续，不浪费已完成的工作
- **桌面应用打包** — 支持 PyInstaller 打包为独立可执行文件

---

## 两种视频模式

本项目支持两种视频生成模式，按需选择：

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
pip install -e '.[cloud-video]' # + AI 视频生成（可灵 / 即梦 / MiniMax / Sora）
pip install -e '.[web]'        # + Gradio Web UI
pip install -e '.[all]'        # 全部安装
```

</details>

### 一键启动（Web UI）

```bash
./start.sh
```

脚本会自动检查 Python 版本、安装依赖、检测 FFmpeg，然后启动 Web UI。
打开浏览器访问 `http://127.0.0.1:7860` 即可使用。

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

### 环境变量（API Key）

根据使用的服务设置对应环境变量：

```bash
# ---- LLM（至少设一个，用于智能分段和 Prompt 生成）----
export GEMINI_API_KEY=xxx         # Google Gemini（免费）
export DEEPSEEK_API_KEY=xxx       # DeepSeek
export OPENAI_API_KEY=xxx         # OpenAI GPT / Sora

# ---- 图片生成（至少设一个）----
export SILICONFLOW_API_KEY=xxx    # 硅基流动（免费）
export DASHSCOPE_API_KEY=xxx      # 阿里云百炼万相
export TOGETHER_API_KEY=xxx       # Together.ai

# ---- AI 视频生成（可选）----
export KLING_API_KEY=xxx          # 可灵 Kling
export SEEDANCE_API_KEY=xxx       # 即梦 Seedance（火山方舟）
export MINIMAX_API_KEY=xxx        # MiniMax 海螺
# Sora 使用 OPENAI_API_KEY
```

也支持在项目根目录创建 `.env` 文件配置环境变量。

---

## 视频生成 API 对比

| 特性 | 可灵 Kling | 即梦 Seedance | MiniMax 海螺 | OpenAI Sora |
|------|-----------|--------------|-------------|-------------|
| **厂商** | 快手 | 字节跳动 | MiniMax | OpenAI |
| **最新模型** | Kling-V3-Omni | Seedance 2.0 | Hailuo 2.3 | Sora-2 |
| **最大时长** | 10s（续写 3min） | 15s | 10s | 25s (pro) |
| **最大分辨率** | 1080p | 2K | 1080p | 1080p |
| **9:16 竖屏** | 支持 | 支持 | 支持 | 支持 |
| **图生视频** | 支持 | 支持（多图） | 支持 | 支持 |
| **原生音频** | V3 支持 | 支持 | 不支持 | 不支持 |
| **5s 视频价格** | ~$0.21 (std) | ~$0.10-0.40 | ~$0.25 (768p) | ~$0.50 |
| **10s 视频价格** | ~$0.42 (std) | ~$0.20-0.80 | ~$0.50 (768p) | ~$1.00 |
| **API 文档** | 完善 | 较新 | 完善 | 完善 |

> 提示：价格仅供参考，以各平台官方定价为准。推荐从可灵或 MiniMax 开始尝试，性价比较高。

---

## 项目架构

### 目录结构

```
AI_novel/
├── main.py                  # CLI 入口（Click）
├── web.py                   # Web UI（Gradio）
├── config.yaml              # 全局配置
├── start.sh                 # 一键启动脚本
├── pyproject.toml           # 项目元数据 & 依赖
├── src/
│   ├── pipeline.py          # 流水线调度器
│   ├── config_manager.py    # YAML 配置加载/验证
│   ├── checkpoint.py        # 断点续传（JSON）
│   ├── logger.py            # Rich 日志
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
│   │   └── sora_backend.py      # OpenAI Sora
│   ├── tts/                 # edge-tts 配音 + SRT 字幕
│   ├── video/               # FFmpeg 视频合成 + Ken Burns 特效
│   └── utils/               # 工具函数（FFmpeg 检测等）
├── input/                   # 输入小说文本
├── presets/                 # 风格预设
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
| Web UI | Gradio |
| TTS | edge-tts（微软免费语音合成） |
| LLM | OpenAI / DeepSeek / Google Gemini / Ollama |
| 图片生成 | SiliconFlow / 阿里云万相 / Together.ai / Diffusers (本地 SD) |
| 视频生成 | 可灵 Kling / 即梦 Seedance / MiniMax 海螺 / OpenAI Sora |
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
| `.[web]` | + Gradio Web UI | Web 界面使用 |
| `.[gemini]` | + Google Gemini | 免费 LLM |
| `.[llm]` | + OpenAI SDK | OpenAI / DeepSeek |
| `.[ollama]` | + Ollama 客户端 | 本地 LLM |
| `.[cloud-image]` | + httpx | 云端生图 |
| `.[cloud-video]` | + httpx | AI 视频生成 |
| `.[gpu]` | + torch + diffusers | 本地 Stable Diffusion |
| `.[build]` | + PyInstaller | 桌面应用打包 |
| `.[all]` | 全部安装 | 开发环境 |

---

## License

[MIT](LICENSE)
