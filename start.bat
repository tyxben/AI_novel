@echo off
REM AI 小说转视频 - 开发启动脚本 (Windows)
cd /d "%~dp0"

REM 安装 web 依赖（如果尚未安装）
pip install -e ".[web]" --quiet 2>nul

echo 启动 AI 小说转视频...
python web.py
