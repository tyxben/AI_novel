@echo off
chcp 65001 >nul 2>&1
REM AI 小说转视频 - 启动脚本 (Windows)
cd /d "%~dp0"

echo =====================================
echo   AI 小说转视频 - 启动中...
echo =====================================
echo.

REM 1. 检查 Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PY_VERSION=%%i
for /f "tokens=*" %%i in ('python -c "import sys; print(sys.version_info.major)"') do set PY_MAJOR=%%i
for /f "tokens=*" %%i in ('python -c "import sys; print(sys.version_info.minor)"') do set PY_MINOR=%%i

if %PY_MAJOR% LSS 3 (
    echo [ERROR] Python 版本过低: %PY_VERSION%（需要 ≥3.10）
    pause
    exit /b 1
)
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 10 (
    echo [ERROR] Python 版本过低: %PY_VERSION%（需要 ≥3.10）
    pause
    exit /b 1
)
echo [OK] Python %PY_VERSION%

REM 2. 检测虚拟环境
if "%VIRTUAL_ENV%"=="" if "%CONDA_DEFAULT_ENV%"=="" (
    echo [WARN] 未检测到虚拟环境，建议使用 venv 或 conda
    echo        创建虚拟环境: python -m venv .venv ^&^& .venv\Scripts\activate
    echo.
)

REM 3. 安装依赖
echo [INFO] 检查并安装依赖...
python -m pip install -e ".[web,cloud-image,gemini]" --quiet 2>nul
if errorlevel 1 (
    echo [WARN] 部分依赖安装失败，尝试最小安装...
    python -m pip install -e ".[web]" --quiet
)
echo [OK] 依赖已就绪

REM 4. 检查 FFmpeg
echo [INFO] 检查 FFmpeg...
python -c "from src.utils.ffmpeg_helper import ensure_ffmpeg; ensure_ffmpeg()" 2>nul
if errorlevel 1 (
    echo [WARN] FFmpeg 未找到，视频合成功能将不可用
    echo        下载地址: https://ffmpeg.org/download.html
) else (
    echo [OK] FFmpeg 已就绪
)

REM 5. 提示信息
echo.
echo =====================================
echo   启动 Web UI
echo   打开浏览器访问: http://127.0.0.1:7860
echo   按 Ctrl+C 停止
echo =====================================
echo.

REM 6. 启动
python web.py
pause
