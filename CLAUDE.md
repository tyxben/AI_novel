# AI 小说推文自动化

## 项目概述
将小说文本一键转换为短视频（有声书+配图风格），适用于抖音/小红书等平台。

## 技术栈
- Python 3.10+ / Click CLI
- edge-tts (微软免费TTS)
- diffusers + Stable Diffusion (本地生图，自动检测 CUDA/MPS/CPU)
- OpenAI GPT-4o-mini (文本分段/Prompt生成，可选)
- FFmpeg (视频合成)

## 项目结构
- `main.py` - CLI 入口 (click)
- `src/pipeline.py` - 流水线调度器，编排5个阶段
- `src/config_manager.py` - YAML 配置加载/验证
- `src/checkpoint.py` - 断点续传 (JSON)
- `src/logger.py` - Rich 日志
- `src/segmenter/` - 文本分段 (simple规则 / LLM智能)
- `src/promptgen/` - 小说文本→SD图片prompt
- `src/imagegen/` - Stable Diffusion 本地生图 (自动检测设备)
- `src/tts/` - edge-tts 配音 + SRT字幕
- `src/video/` - FFmpeg Ken Burns特效 + 视频合成

## 常用命令
```bash
# 安装
./setup.sh

# 或使用 pyproject.toml
pip install -e .           # 基础依赖
pip install -e '.[gpu]'    # + Stable Diffusion
pip install -e '.[llm]'    # + OpenAI
pip install -e '.[all]'    # 全部

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
- `imagegen.device` 默认 `auto`，自动检测: CUDA > MPS > CPU

## 开发注意事项
- 重依赖 (torch, diffusers, edge_tts) 使用懒加载，避免import时报错
- 图片尺寸 1024x1792 (竖屏9:16)
- 所有文件使用 UTF-8 编码
- FFmpeg 命令通过 subprocess.run 执行
- 字体检测跨平台: macOS PingFang / Linux Noto Sans CJK / Windows YaHei
