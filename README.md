# AI 小说推文自动化

> 小说文本一键转短视频（有声书 + AI 配图），适用于抖音 / 小红书等平台。

## 功能特点

- **全自动流水线** — 输入小说文本，输出可直接发布的竖屏短视频
- **AI 配图** — Stable Diffusion 本地生图，支持风格预设（动漫、水墨等）
- **智能分段** — 规则分段 + LLM 智能分段（可选），自动控制节奏
- **TTS 配音** — 微软 edge-tts 免费高质量语音合成 + SRT 字幕
- **Ken Burns 特效** — 图片自动缩放平移，告别静态幻灯片
- **断点续传** — 中断后从上次进度继续，不浪费已完成的工作
- **跨平台** — macOS / Linux / Windows，GPU 自动检测（CUDA > MPS > CPU）

## 流水线

```
小说文本 → 文本分段 → AI配图Prompt → Stable Diffusion生图
                  ↘ edge-tts配音+字幕 ↘
                           FFmpeg Ken Burns合成 → 短视频.mp4
```

## 快速开始

### 方式一：setup.sh（推荐）

```bash
git clone https://github.com/your-username/AI_novel.git
cd AI_novel
chmod +x setup.sh
./setup.sh
```

### 方式二：pip install

```bash
pip install -e .            # 基础依赖
pip install -e '.[gpu]'     # + Stable Diffusion 本地生图
pip install -e '.[llm]'     # + GPT 智能分段
pip install -e '.[all]'     # 全部安装
```

### 方式三：requirements.txt

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 前置要求

- Python 3.10+
- FFmpeg（`brew install ffmpeg` / `apt install ffmpeg`）
- （可选）NVIDIA GPU 或 Apple Silicon 用于本地生图

## 使用

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

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `segmenter.method` | 分段方式 | `simple` (规则) / `llm` (GPT) |
| `segmenter.max_chars` | 每段最大字数 | `100` |
| `imagegen.device` | GPU 设备 | `auto` (自动检测) |
| `imagegen.model` | SD 模型 | `gsdf/Counterfeit-V2.5` |
| `imagegen.steps` | 推理步数 | `30` |
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
├── setup.sh                # 一键安装脚本
├── src/
│   ├── pipeline.py         # 流水线调度器
│   ├── config_manager.py   # 配置加载/验证
│   ├── checkpoint.py       # 断点续传
│   ├── logger.py           # Rich 日志
│   ├── segmenter/          # 文本分段 (simple/llm)
│   ├── promptgen/          # 小说→图片 Prompt 生成
│   ├── imagegen/           # Stable Diffusion 本地生图
│   ├── tts/                # edge-tts 配音 + 字幕
│   └── video/              # FFmpeg 视频合成 + Ken Burns
├── input/                  # 输入小说文本
├── presets/                # 风格预设
├── workspace/              # 工作目录 (自动生成，已 gitignore)
└── output/                 # 输出视频 (自动生成，已 gitignore)
```

## LLM 模式说明

本项目的 LLM 功能（GPT 智能分段、Prompt 生成）为**可选**依赖。不安装 `openai` 包时，项目仍可正常使用规则分段 + 模板 Prompt 方式运行。

如需启用 LLM 模式：
1. 安装：`pip install -e '.[llm]'`
2. 设置环境变量：`export OPENAI_API_KEY=your_key`
3. 配置 `config.yaml` 中 `segmenter.method: llm`

## License

[MIT](LICENSE)
