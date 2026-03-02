# AI 小说推文自动化

## 项目概述
将小说文本一键转换为短视频（有声书+配图风格），适用于抖音/小红书等平台。

## 技术栈
- Python 3.10+ / Click CLI
- edge-tts (微软免费TTS)
- 多 LLM 后端: OpenAI / DeepSeek / Gemini(免费) / Ollama(本地) — 统一接口 `src/llm/`
- 图片生成: diffusers(本地SD) / Together.ai Flux(云端免费) — 统一接口 `src/imagegen/`
- AI视频片段: 可灵(Kling) / 即梦(Seedance) / MiniMax(海螺) — 统一接口 `src/videogen/`
- FFmpeg (视频合成)

## 项目结构
- `main.py` - CLI 入口 (click)
- `src/pipeline.py` - 流水线调度器，编排5个阶段
- `src/config_manager.py` - YAML 配置加载/验证
- `src/checkpoint.py` - 断点续传 (JSON)
- `src/logger.py` - Rich 日志
- `src/llm/` - LLM 统一抽象层 (OpenAI/DeepSeek/Gemini/Ollama)
- `src/segmenter/` - 文本分段 (simple规则 / LLM智能)
- `src/promptgen/` - 小说文本→图片/视频prompt生成
- `src/imagegen/` - 图片生成 (diffusers本地 / SiliconFlow / DashScope云端)
- `src/videogen/` - AI视频片段生成 (可灵Kling / 即梦Seedance / MiniMax海螺)
- `src/tts/` - edge-tts 配音 + SRT字幕
- `src/video/` - FFmpeg 视频合成 (静态图Ken Burns特效 / AI视频片段拼接)

## 常用命令
```bash
# 安装
./setup.sh

# 或使用 pyproject.toml
pip install -e .              # 基础依赖
pip install -e '.[gpu]'       # + Stable Diffusion
pip install -e '.[llm]'       # + OpenAI
pip install -e '.[gemini]'    # + Google Gemini
pip install -e '.[ollama]'    # + Ollama
pip install -e '.[cloud-image]' # + Together.ai
pip install -e '.[cloud-video]' # + 视频生成API (可灵/即梦/MiniMax)
pip install -e '.[all]'       # 全部

# 全流程
python main.py run input/novel.txt

# 断点续传
python main.py run input/novel.txt --resume

# 仅分段
python main.py segment input/novel.txt

# 查看进度
python main.py status workspace/novel/
```

## 配置
全局配置在 `config.yaml`，可通过 `--config` 指定自定义配置。
- `llm.provider` 默认 `auto`，按优先级检测: GEMINI_API_KEY → DEEPSEEK_API_KEY → OPENAI_API_KEY → Ollama
- `imagegen.backend` 支持 `diffusers`(本地) 和 `together`(云端，需 TOGETHER_API_KEY)
- `imagegen.device` 默认 `auto`，自动检测: CUDA > MPS > CPU
- `videogen.backend` 支持 `kling` / `seedance` / `minimax`（可选，不配置则用静态图模式）

## 开发注意事项
- 重依赖 (torch, diffusers, edge_tts) 使用懒加载，避免import时报错
- 图片尺寸 1024x1792 (竖屏9:16)
- 所有文件使用 UTF-8 编码
- FFmpeg 命令通过 subprocess.run 执行
- 字体检测跨平台: macOS PingFang / Linux Noto Sans CJK / Windows YaHei
