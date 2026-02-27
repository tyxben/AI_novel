#!/bin/bash
# AI 小说转视频 - 开发启动脚本 (Mac/Linux)
set -e
cd "$(dirname "$0")"

# 安装 web 依赖（如果尚未安装）
pip install -e '.[web]' --quiet 2>/dev/null || true

echo "启动 AI 小说转视频..."
python web.py
