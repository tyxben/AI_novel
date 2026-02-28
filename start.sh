#!/bin/bash
# AI 小说转视频 - 启动脚本 (Mac/Linux)
set -e
cd "$(dirname "$0")"

echo "====================================="
echo "  AI 小说转视频 - 启动中..."
echo "====================================="
echo

# 1. 检查 Python 版本 ≥3.10
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "❌ 未找到 Python，请先安装 Python 3.10+"
    exit 1
fi

PYTHON=$(command -v python3 || command -v python)
PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "❌ Python 版本过低: $PY_VERSION（需要 ≥3.10）"
    exit 1
fi
echo "✅ Python $PY_VERSION"

# 2. 检测虚拟环境
if [ -z "$VIRTUAL_ENV" ] && [ -z "$CONDA_DEFAULT_ENV" ]; then
    echo "⚠️  未检测到虚拟环境，建议使用 venv 或 conda"
    echo "   创建虚拟环境: python3 -m venv .venv && source .venv/bin/activate"
    echo
fi

# 3. 安装依赖
echo "📦 检查并安装依赖..."
$PYTHON -m pip install -e '.[web,cloud-image,gemini]' --quiet 2>&1 | tail -1 || {
    echo "⚠️  部分依赖安装失败，尝试最小安装..."
    $PYTHON -m pip install -e '.[web]' --quiet
}
echo "✅ 依赖已就绪"

# 4. 检查 FFmpeg
echo "🔍 检查 FFmpeg..."
$PYTHON -c "from src.utils.ffmpeg_helper import ensure_ffmpeg; ensure_ffmpeg()" 2>/dev/null && {
    echo "✅ FFmpeg 已就绪"
} || {
    echo "⚠️  FFmpeg 未找到，视频合成功能将不可用"
    echo "   安装方法: brew install ffmpeg (Mac) / apt install ffmpeg (Linux)"
}

# 5. 提示信息
echo
echo "====================================="
echo "  🚀 启动 Web UI"
echo "  📎 打开浏览器访问: http://127.0.0.1:7860"
echo "  📎 按 Ctrl+C 停止"
echo "====================================="
echo

# 6. 启动
$PYTHON web.py
