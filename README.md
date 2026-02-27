# AI 小说推文自动化

> 小说文本一键转短视频（有声书 + AI 配图），适用于抖音 / 小红书等平台。

## 功能特点

- **全自动流水线** — 输入小说文本，输出可直接发布的竖屏短视频
- **多 LLM 后端** — OpenAI / DeepSeek / Gemini(免费) / Ollama(本地离线)，自动检测
- **多图片生成后端** — SiliconFlow(免费) / 阿里云万相 / Pollinations(免费无Key) / Together.ai / 本地SD
- **智能分段** — 规则分段 + LLM 智能分段，自动控制节奏
- **TTS 配音** — 微软 edge-tts 免费高质量语音合成 + SRT 字幕
- **Ken Burns 特效** — 图片自动缩放平移，告别静态幻灯片
- **断点续传** — 中断后从上次进度继续，不浪费已完成的工作
- **跨平台** — macOS / Linux / Windows，GPU 自动检测（CUDA > MPS > CPU）

## 流水线

```
小说文本 → 文本分段 → LLM生成图片Prompt → 云端/本地AI生图
                  ↘ edge-tts配音+字幕  ↘
                           FFmpeg Ken Burns合成 → 短视频.mp4
```

## 快速开始

### 安装

```bash
git clone https://github.com/tyxben/AI_novel.git
cd AI_novel

pip install -e .               # 基础依赖
pip install -e '.[cloud-image]' # + 云端生图（推荐）
pip install -e '.[gemini]'      # + Gemini LLM（免费）
pip install -e '.[all]'         # 全部安装
```

### 前置要求

- Python 3.10+
- FFmpeg（`brew install ffmpeg` / `apt install ffmpeg`）
- 至少一个图片生成 API Key（见下方环境变量配置）

### 环境变量

根据你使用的服务，设置对应的环境变量：

```bash
# === LLM（至少设一个，用于智能分段和 Prompt 生成）===
export GEMINI_API_KEY=xxx       # Google Gemini（免费 1000次/天）
export DEEPSEEK_API_KEY=xxx     # DeepSeek（极低成本）
export OPENAI_API_KEY=xxx       # OpenAI GPT

# === 图片生成（至少设一个）===
export SILICONFLOW_API_KEY=xxx  # 硅基流动（免费，推荐）
export DASHSCOPE_API_KEY=xxx    # 阿里云百炼万相（新用户100张免费）
export TOGETHER_API_KEY=xxx     # Together.ai（需绑卡）

# 也可以不设任何 Key：使用 simple 分段 + 本地关键词 Prompt + Pollinations 免费生图
```

### 运行

```bash
# 全流程: 小说 → 短视频
python main.py run input/novel.txt

# 断点续传
python main.py run input/novel.txt --resume

# 自定义配置
python main.py run input/novel.txt --config my_config.yaml

# 仅文本分段（预览）
python main.py segment input/novel.txt

# 查看处理进度
python main.py status workspace/novel/
```

## 配置

全局配置文件 `config.yaml`，可通过 `--config` 指定自定义配置。

### 核心配置

| 配置项 | 说明 | 可选值 |
|--------|------|--------|
| `llm.provider` | LLM 后端 | `auto`(默认) / `openai` / `deepseek` / `gemini` / `ollama` |
| `imagegen.backend` | 图片生成后端 | `siliconflow`(默认) / `diffusers` / `together` / `pollinations` / `dashscope` |
| `segmenter.method` | 分段方式 | `simple`(规则) / `llm`(智能) |

### 图片生成后端对比

| 后端 | 费用 | 速度 | 质量 | 需要 |
|------|------|------|------|------|
| **siliconflow** | 免费 | ~4s/张 | FLUX 高质量 | API Key（免费注册） |
| **dashscope** | 100张免费 | ~5s/张 | 万相高质量 | 阿里云账号 |
| **pollinations** | 完全免费 | ~10s/张 | FLUX | 无需任何配置 |
| **together** | 需绑卡 | ~3s/张 | FLUX 高质量 | API Key |
| **diffusers** | 免费 | ~30s/张 | 一般 | GPU + torch |

### 其他配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `segmenter.max_chars` | 每段最大字数 | `100` |
| `imagegen.width` / `height` | 图片尺寸 | `1024` x `1792` |
| `tts.voice` | TTS 语音 | `zh-CN-YunxiNeural` |
| `tts.rate` | 语速调节 | `+0%` |
| `video.resolution` | 输出分辨率 | `[1080, 1920]` (竖屏 9:16) |
| `video.fps` | 帧率 | `30` |
| `video.bgm.path` | 背景音乐路径 | 空 (无 BGM) |

## 项目结构

```
AI_novel/
├── main.py                 # CLI 入口 (Click)
├── config.yaml             # 全局配置
├── src/
│   ├── pipeline.py         # 流水线调度器
│   ├── config_manager.py   # 配置加载/验证
│   ├── checkpoint.py       # 断点续传
│   ├── logger.py           # Rich 日志
│   ├── llm/                # LLM 统一抽象层
│   │   ├── llm_client.py   #   ABC + 工厂 + 自动检测
│   │   ├── openai_backend.py   # OpenAI + DeepSeek
│   │   ├── gemini_backend.py   # Google Gemini
│   │   └── ollama_backend.py   # Ollama 本地
│   ├── segmenter/          # 文本分段 (simple/llm)
│   ├── promptgen/          # 小说→图片 Prompt 生成
│   ├── imagegen/           # 图片生成
│   │   ├── image_generator.py      # ABC + 工厂
│   │   ├── siliconflow_backend.py  # 硅基流动 FLUX
│   │   ├── dashscope_backend.py    # 阿里云万相
│   │   ├── pollinations_backend.py # Pollinations 免费
│   │   ├── together_backend.py     # Together.ai
│   │   └── diffusers_backend.py    # 本地 Stable Diffusion
│   ├── tts/                # edge-tts 配音 + 字幕
│   └── video/              # FFmpeg 视频合成 + Ken Burns
├── input/                  # 输入小说文本
├── presets/                # 风格预设
├── workspace/              # 工作目录 (自动生成，已 gitignore)
└── output/                 # 输出视频 (自动生成，已 gitignore)
```

## 零成本方案

不花一分钱也能跑通完整流水线：

1. LLM 用 **Gemini**（免费 1000次/天）或不用（`segmenter.method: simple`）
2. 图片用 **SiliconFlow**（免费注册）或 **Pollinations**（完全免费）
3. TTS 用 **edge-tts**（免费）
4. 视频合成用 **FFmpeg**（免费）

## License

[MIT](LICENSE)
