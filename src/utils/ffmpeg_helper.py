"""FFmpeg 自动检测与下载

首次运行时如果系统没有 FFmpeg，自动下载静态二进制到 ~/.novel-video/bin/。
"""

import os
import platform
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

from src.logger import log

_BIN_DIR = Path.home() / ".novel-video" / "bin"
_checked = False


def _download_progress(block_num: int, block_size: int, total_size: int) -> None:
    """urlretrieve 下载进度回调。"""
    if total_size > 0:
        downloaded = block_num * block_size
        percent = min(100, downloaded * 100 // total_size)
        mb = downloaded / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        print(f"\r  下载进度: {percent}% ({mb:.1f}/{total_mb:.1f} MB)", end="", flush=True)


def _download_ffmpeg_mac() -> None:
    """从 evermeet.cx 下载 macOS 静态 FFmpeg。"""
    urls = {
        "ffmpeg": "https://evermeet.cx/ffmpeg/getrelease/zip",
        "ffprobe": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
    }
    _BIN_DIR.mkdir(parents=True, exist_ok=True)

    for name, url in urls.items():
        dest = _BIN_DIR / name
        if dest.exists():
            continue
        log.info("下载 %s (macOS)...", name)
        zip_path = _BIN_DIR / f"{name}.zip"
        try:
            urlretrieve(url, str(zip_path), _download_progress)
            print()  # 换行
            with zipfile.ZipFile(zip_path) as zf:
                for member in zf.namelist():
                    if member.endswith(name) or member == name:
                        zf.extract(member, str(_BIN_DIR))
                        extracted = _BIN_DIR / member
                        if extracted != dest:
                            shutil.move(str(extracted), str(dest))
                        break
            dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
        finally:
            zip_path.unlink(missing_ok=True)


def _download_ffmpeg_windows() -> None:
    """从 gyan.dev 下载 Windows 静态 FFmpeg。"""
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    _BIN_DIR.mkdir(parents=True, exist_ok=True)

    ffmpeg_exe = _BIN_DIR / "ffmpeg.exe"
    ffprobe_exe = _BIN_DIR / "ffprobe.exe"
    if ffmpeg_exe.exists() and ffprobe_exe.exists():
        return

    log.info("下载 FFmpeg (Windows)...")
    zip_path = _BIN_DIR / "ffmpeg-win.zip"
    try:
        urlretrieve(url, str(zip_path), _download_progress)
        print()
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                basename = Path(member).name.lower()
                if basename in ("ffmpeg.exe", "ffprobe.exe"):
                    target = _BIN_DIR / basename
                    if not target.exists():
                        with zf.open(member) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
    finally:
        zip_path.unlink(missing_ok=True)


def _download_ffmpeg_linux() -> None:
    """从 johnvansickle.com 下载 Linux 静态 FFmpeg。"""
    arch = platform.machine()
    if arch in ("x86_64", "AMD64"):
        arch_name = "amd64"
    elif arch in ("aarch64", "arm64"):
        arch_name = "arm64"
    else:
        raise RuntimeError(f"不支持的 Linux 架构: {arch}")

    url = f"https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-{arch_name}-static.tar.xz"
    _BIN_DIR.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = _BIN_DIR / "ffmpeg"
    ffprobe_bin = _BIN_DIR / "ffprobe"
    if ffmpeg_bin.exists() and ffprobe_bin.exists():
        return

    log.info("下载 FFmpeg (Linux %s)...", arch_name)
    tar_path = _BIN_DIR / "ffmpeg-linux.tar.xz"
    try:
        urlretrieve(url, str(tar_path), _download_progress)
        print()
        with tarfile.open(tar_path, "r:xz") as tf:
            for member in tf.getmembers():
                basename = Path(member.name).name
                if basename in ("ffmpeg", "ffprobe"):
                    member.name = basename
                    tf.extract(member, str(_BIN_DIR))
                    extracted = _BIN_DIR / basename
                    extracted.chmod(extracted.stat().st_mode | stat.S_IEXEC)
    finally:
        tar_path.unlink(missing_ok=True)


def _add_bin_to_path() -> None:
    """将 ~/.novel-video/bin/ 加入 PATH。"""
    bin_str = str(_BIN_DIR)
    if bin_str not in os.environ.get("PATH", ""):
        os.environ["PATH"] = bin_str + os.pathsep + os.environ.get("PATH", "")


def ensure_ffmpeg() -> str:
    """确保 FFmpeg 可用，必要时自动下载。

    Returns:
        ffmpeg 可执行文件路径。

    Raises:
        RuntimeError: 下载或安装失败。
    """
    global _checked
    if _checked:
        return get_ffmpeg_path()

    # 1. 系统 PATH 中已有
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        _checked = True
        return shutil.which("ffmpeg")

    # 2. 检查 ~/.novel-video/bin/
    _add_bin_to_path()
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        _checked = True
        return shutil.which("ffmpeg")

    # 3. 自动下载
    system = platform.system()
    log.info("系统未找到 FFmpeg，正在自动下载...")
    try:
        if system == "Darwin":
            _download_ffmpeg_mac()
        elif system == "Windows":
            _download_ffmpeg_windows()
        elif system == "Linux":
            _download_ffmpeg_linux()
        else:
            raise RuntimeError(f"不支持的操作系统: {system}")
    except Exception as e:
        raise RuntimeError(
            f"FFmpeg 自动下载失败: {e}\n"
            "请手动安装 FFmpeg:\n"
            "  macOS: brew install ffmpeg\n"
            "  Ubuntu/Debian: sudo apt install ffmpeg\n"
            "  Windows: winget install ffmpeg"
        ) from e

    _add_bin_to_path()

    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "FFmpeg 下载完成但无法找到可执行文件。\n"
            f"请检查 {_BIN_DIR} 目录，或手动安装 FFmpeg。"
        )

    _checked = True
    log.info("FFmpeg 安装成功: %s", get_ffmpeg_path())
    return get_ffmpeg_path()


def get_ffmpeg_path() -> str:
    """获取 ffmpeg 可执行文件路径。"""
    path = shutil.which("ffmpeg")
    if path:
        return path
    _add_bin_to_path()
    return shutil.which("ffmpeg") or "ffmpeg"


def get_ffprobe_path() -> str:
    """获取 ffprobe 可执行文件路径。"""
    path = shutil.which("ffprobe")
    if path:
        return path
    _add_bin_to_path()
    return shutil.which("ffprobe") or "ffprobe"
