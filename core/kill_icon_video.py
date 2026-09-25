# SPDX-License-Identifier: GPL-3.0-or-later
"""视频 → 击杀图标的帧（批 120，对标补课唯一追的深度差距）。

以前拖视频进来只得到一句「先用在线工具或 ffmpeg 转成 WebP / GIF 再拖进来」——
「去装个 ffmpeg、命令行敲对参数」正是 KI-2 说要消灭的那种门槛。
解码走 **Qt 自带的多媒体后端**（PySide6 6.10 带 FFmpeg，LGPL，随 Qt 已履行）：
不要用户装任何东西，打包放开 `QtMultimedia` 约 +21MB。

⭐ 闸门在**解码之前**：`时长 × 帧率 ≤ MAX_FRAMES`。超了先降帧率（不低于 MIN_FPS）、再截短，
并如实说。不是解到一半把内存吃光。

线程：导入跑在 `threading.Thread` 里（KillIconImportTask）。那种线程里用一个局部 `QEventLoop`
收帧是实测可行的（2 秒 30fps 片、4 倍速：60 帧一帧不少、0.58 秒）。
⛔ AGPL：对标对象的视频导入源码本批没有打开过，只按「它给用户什么」这一行为规格做。
"""
from __future__ import annotations

import os

VIDEO_EXTENSIONS = (".mp4", ".webm", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".flv")
MAX_FRAMES = 600                 # 与 kill_icon_import.MAX_FRAMES 对齐
MAX_SECONDS = 10.0               # 击杀图标是一闪而过的东西；更长的视频只取开头
DEFAULT_FPS = 30
MIN_FPS = 12                     # 再低就不像动画了 ⇒ 宁可截短
DECODE_RATE = 4.0                # 解码时的播放倍速（实测 4 倍速不丢帧）
LOAD_TIMEOUT_MS = 8000


class VideoError(Exception):
    """解不出来。消息直接给用户看。"""


def plan_sampling(duration_s: float, fps: float = DEFAULT_FPS, max_frames: int = MAX_FRAMES):
    """**解码之前**算好取多少秒、每秒几帧：`(秒数, 帧率, 警告)`。纯函数。"""
    warnings = []
    seconds = max(0.0, float(duration_s or 0.0))
    fps = max(1, int(round(fps or DEFAULT_FPS)))
    if seconds > MAX_SECONDS:
        warnings.append(f"视频有 {seconds:.1f} 秒，击杀图标只取开头 {MAX_SECONDS:.0f} 秒。")
        seconds = MAX_SECONDS
    if seconds * fps > max_frames:
        lower = max(MIN_FPS, int(max_frames // max(seconds, 0.001)))
        if lower < fps:
            warnings.append(f"帧数太多，帧率从 {fps} 降到 {lower}（上限 {max_frames} 帧）。")
            fps = lower
        if seconds * fps > max_frames:
            cut = max_frames / fps
            warnings.append(f"降到 {fps} 帧/秒还装不下，只取开头 {cut:.1f} 秒。")
            seconds = cut
    return seconds, fps, warnings


def sample_times_us(seconds: float, fps: int):
    """每一帧该取的时刻（微秒）。"""
    count = max(1, int(seconds * fps + 1e-6))
    return [int(i * 1_000_000 / fps) for i in range(count)]


def _player():
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

    player = QMediaPlayer()
    audio = QAudioOutput()
    audio.setMuted(True)                  # §3：不出声、不占音频设备的可闻输出
    player.setAudioOutput(audio)
    sink = QVideoSink()
    player.setVideoSink(sink)
    player._keep = (audio, sink)          # 别被回收
    return player, sink


def target_fps(source_fps):
    """源帧率照用，但不超过 DEFAULT_FPS（一闪而过的图标，60 帧只是把图集撑大一倍）。"""
    try:
        source = int(round(float(source_fps or 0)))
    except (TypeError, ValueError):
        source = 0
    return min(source, DEFAULT_FPS) if source > 0 else DEFAULT_FPS


def probe_video(path):
    """`(时长秒, 宽, 高, 源帧率)`，只加载元数据、不解码画面（选完文件就要出信息）。"""
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtMultimedia import QMediaMetaData, QMediaPlayer

    if not os.path.isfile(path):
        raise VideoError(f"找不到这个视频：{path}")
    player, _sink = _player()
    loop = QEventLoop()
    player.mediaStatusChanged.connect(
        lambda st: loop.quit() if st in (QMediaPlayer.LoadedMedia, QMediaPlayer.InvalidMedia) else None)
    player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
    QTimer.singleShot(LOAD_TIMEOUT_MS, loop.quit)
    if player.mediaStatus() not in (QMediaPlayer.LoadedMedia, QMediaPlayer.InvalidMedia):
        loop.exec()
    if player.mediaStatus() != QMediaPlayer.LoadedMedia:
        # errorString 是 Qt 的英文原话（"Could not open file"），不给用户看
        raise VideoError(f"这个视频打不开：{os.path.basename(path)}。"
                         f"可能文件坏了，或编码不认识 —— 换成 mp4 / webm 再试。")
    meta = player.metaData()
    size = meta.value(QMediaMetaData.Resolution)
    width, height = (size.width(), size.height()) if size is not None and hasattr(size, "width") else (0, 0)
    rate = meta.value(QMediaMetaData.VideoFrameRate)
    duration = player.duration() / 1000.0
    player.stop()
    return duration, width, height, rate or 0.0


def _to_pil(frame, max_edge):
    from PIL import Image
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    image = frame.toImage()
    if max(image.width(), image.height()) > max_edge:
        image = image.scaled(max_edge, max_edge, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    image = image.convertToFormat(QImage.Format_RGBA8888)
    data = bytes(image.constBits())[: image.bytesPerLine() * image.height()]
    return Image.frombuffer("RGBA", (image.width(), image.height()), data, "raw", "RGBA",
                            image.bytesPerLine(), 1).copy()


def read_video_frames(path, fps=None, max_edge=1024, progress=None, cancel=None):
    """解码成 `(帧列表 PIL RGBA, 帧率, 警告)`。闸门在解码之前（`plan_sampling`）。"""
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtMultimedia import QMediaPlayer

    duration, _w, _h, source_fps = probe_video(path)
    seconds, fps, warnings = plan_sampling(duration, fps or target_fps(source_fps))
    wanted = sample_times_us(seconds, fps)
    frames = []
    player, sink = _player()
    loop = QEventLoop()
    state = {"next": 0}

    def on_frame(frame):
        if not frame.isValid() or state["next"] >= len(wanted):
            return
        if cancel is not None and cancel():
            loop.quit()
            return
        # 这一帧在屏幕上的区间 [start, end) 覆盖到的取样时刻都取它（源帧率低于目标时一帧用几次；
        # 只比 start 会漏掉最后一帧之后、片尾之前的那个时刻 —— 实测 20fps 源取 30fps 少 1 帧）
        end = frame.endTime() if frame.endTime() > frame.startTime() else frame.startTime() + 1
        while state["next"] < len(wanted) and wanted[state["next"]] < end:
            frames.append(_to_pil(frame, max_edge))          # 源帧率低于目标时同一帧用几次
            state["next"] += 1
            if progress is not None:
                try:
                    progress(len(frames), len(wanted), "解码视频")
                except Exception:
                    pass
        if state["next"] >= len(wanted):
            loop.quit()

    sink.videoFrameChanged.connect(on_frame)
    player.mediaStatusChanged.connect(
        lambda st: loop.quit() if st in (QMediaPlayer.EndOfMedia, QMediaPlayer.InvalidMedia) else None)
    player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
    player.setPlaybackRate(DECODE_RATE)
    player.play()
    QTimer.singleShot(int(max(5.0, seconds / DECODE_RATE * 3 + 5) * 1000), loop.quit)   # 兜底：别永远等
    loop.exec()
    player.stop()
    if cancel is not None and cancel():
        from core.kill_icon_import import KillIconImportCancelled
        raise KillIconImportCancelled()
    if not frames:
        raise VideoError(f"没能从 {os.path.basename(path)} 里解出任何一帧。")
    if len(frames) < len(wanted):
        warnings.append(f"视频比预计短，实际取到 {len(frames)} 帧。")
    return frames, fps, warnings
