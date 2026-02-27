#!/usr/bin/env bash
set -euo pipefail

echo "=== AI 小说推文自动化 - 环境安装 ==="

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "错误: 未找到 python3，请先安装 Python 3.10+"
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python 版本: $PY_VER"

# 检查 FFmpeg
if ! command -v ffmpeg &>/dev/null; then
    OS="$(uname -s)"
    case "$OS" in
        Darwin)
            echo "警告: 未找到 ffmpeg，正在通过 brew 安装..."
            if command -v brew &>/dev/null; then
                brew install ffmpeg
            else
                echo "错误: 未找到 brew，请手动安装 ffmpeg:"
                echo "  brew install ffmpeg"
                echo "  或前往 https://ffmpeg.org/download.html"
                exit 1
            fi
            ;;
        Linux)
            echo "错误: 未找到 ffmpeg，请使用系统包管理器安装:"
            echo "  Ubuntu/Debian: sudo apt install ffmpeg"
            echo "  Fedora:        sudo dnf install ffmpeg"
            echo "  Arch:          sudo pacman -S ffmpeg"
            exit 1
            ;;
        *)
            echo "错误: 未找到 ffmpeg，请手动安装:"
            echo "  https://ffmpeg.org/download.html"
            exit 1
            ;;
    esac
fi
echo "FFmpeg: $(ffmpeg -version | head -1)"

# 创建虚拟环境
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
echo "虚拟环境已激活: $VENV_DIR"

# 安装依赖
echo "安装 Python 依赖..."
pip install --upgrade pip
pip install -e .

echo ""
echo "=== 安装完成 ==="
echo ""
echo "可选: 安装 GPU 支持 (Stable Diffusion 本地生图):"
echo "  pip install -e '.[gpu]'"
echo ""
echo "可选: 安装 LLM 支持 (GPT 智能分段/Prompt 生成):"
echo "  pip install -e '.[llm]'"
echo ""
echo "使用方法:"
echo "  source .venv/bin/activate"
echo "  python main.py run input/novel.txt"
