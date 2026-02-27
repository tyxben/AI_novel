"""Ken Burns 特效与转场滤镜 - 返回 FFmpeg 滤镜字符串"""

from __future__ import annotations


def ken_burns_filter(
    duration: float,
    width: int,
    height: int,
    zoom_range: tuple[float, float] = (1.0, 1.15),
    direction: int = 0,
    fps: int = 30,
    zoom_start: float | None = None,
    zoom_end: float | None = None,
) -> str:
    """返回 FFmpeg zoompan 滤镜字符串，实现 Ken Burns（慢推慢拉）特效。

    Args:
        duration:   片段时长（秒）。
        width:      输出宽度（像素）。
        height:     输出高度（像素）。
        zoom_range: (起始缩放, 结束缩放)，如 (1.0, 1.15)。
        direction:  运镜方向，按 idx % 4 循环:
                    0 = zoom in（推近）
                    1 = zoom out（拉远）
                    2 = pan left（左移）
                    3 = pan right（右移）
        fps:        帧率，默认 30。
        zoom_start: 覆盖起始 zoom 值（用于子片段连续性）。
        zoom_end:   覆盖结束 zoom 值（用于子片段连续性）。

    Returns:
        形如 ``zoompan=z='...' :x='...' :y='...' :d=... :s=WxH :fps=30``
        的 FFmpeg 滤镜字符串。
    """
    total_frames = int(duration * fps)
    if total_frames < 1:
        total_frames = 1

    z_lo, z_hi = zoom_range
    zs = zoom_start if zoom_start is not None else z_lo
    ze = zoom_end if zoom_end is not None else z_hi

    mode = direction % 4

    if mode == 0:
        # Zoom in: 从 zs 线性增长到 ze，画面居中
        z_expr = f"min({zs}+({ze}-{zs})*on/{total_frames},{ze})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    elif mode == 1:
        # Zoom out: 从 ze 线性缩小到 zs，画面居中
        z_expr = f"max({ze}-({ze}-{zs})*on/{total_frames},{zs})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    elif mode == 2:
        # Pan left: 保持放大 z_hi，x 从右侧平移到左侧
        z_expr = str(z_hi)
        z_range = z_hi - z_lo
        if z_range > 0 and (zoom_start is not None or zoom_end is not None):
            p_s = (zs - z_lo) / z_range
            p_e = (ze - z_lo) / z_range
            x_expr = f"(iw/zoom-iw/zoom/{z_hi})*({1-p_s}+({p_s-p_e})*on/{total_frames})"
        else:
            x_expr = f"(iw/zoom-iw/zoom/{z_hi})*(1-on/{total_frames})"
        y_expr = "ih/2-(ih/zoom/2)"

    else:
        # Pan right: 保持放大 z_hi，x 从左侧平移到右侧
        z_expr = str(z_hi)
        z_range = z_hi - z_lo
        if z_range > 0 and (zoom_start is not None or zoom_end is not None):
            p_s = (zs - z_lo) / z_range
            p_e = (ze - z_lo) / z_range
            x_expr = f"(iw/zoom-iw/zoom/{z_hi})*({p_s}+({p_e-p_s})*on/{total_frames})"
        else:
            x_expr = f"(iw/zoom-iw/zoom/{z_hi})*(on/{total_frames})"
        y_expr = "ih/2-(ih/zoom/2)"

    return (
        f"zoompan=z='{z_expr}'"
        f":x='{x_expr}'"
        f":y='{y_expr}'"
        f":d={total_frames}"
        f":s={width}x{height}"
        f":fps={fps}"
    )


def crossfade_filter(duration: float = 0.5, offset: float = 0.0) -> str:
    """返回 FFmpeg xfade 滤镜字符串，用于片段间的交叉淡入淡出转场。

    Args:
        duration: 转场时长（秒），默认 0.5。
        offset:   转场起始时间点（秒）。由调用方根据前一个片段
                  的时长减去 duration 来计算。

    Returns:
        形如 ``xfade=transition=fade:duration=0.5:offset=4.5`` 的字符串。
    """
    return f"xfade=transition=fade:duration={duration}:offset={offset}"
