# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标叠加层的 Qt 实现（KI-1）。

这是准心 R8b（见 [crosshair_overlay.py]）走过的同一条路：把叠加层从
pygame 子进程搬到主进程的 Qt 透明窗口。搬的理由与准心那次**不完全相同**，
这里最要紧的是第 1 条：

1. **老实现没有真透明**。pygame 窗口靠 `SetLayeredWindowAttributes` 的
   `LWA_COLORKEY` 把纯黑当透明抠掉。后果三连：素材里任何纯黑像素变成洞；
   边缘永远是硬锯齿（抠图是二值的，做不了 alpha 混合）；淡入淡出、发光、
   半透明这类效果在**物理上不可能**实现。Qt 的 `WA_TranslucentBackground`
   给的是逐像素 alpha，这三件事一次解决。
2. **多屏**。老实现用 `GetSystemMetrics(0/1)` 只认主屏，游戏开在副屏时
   图标弹在主屏上。这里直接复用准心那套 `pick_screen`——按 GDI 设备名匹配，
   不按坐标（坐标在混合缩放下跨坐标系，会挑错屏）。
3. 顺带砍掉一个常驻子进程（pygame + SDL 视频，实测 30~60MB）。

本文件同样刻意分成两层：

    playback_state(...)               ← 纯函数：(经过时间) → (第几帧, 不透明度)
    compute_overlay_geometry(...)     ← 纯函数：(屏幕, 缩放, 尺寸) → 窗口矩形
    KillIconOverlayWindow(QWidget)    ← 窗口与生命周期

拆开的收益在老实现上体现得最直白：pygame 版的播放循环是**零测试**的
（子进程 + SDL，测不动）。这里帧选择与几何都是纯函数，离屏画进 QImage
就能逐像素验，不建任何窗口、不打扰前台。

**帧数据一律用 QImage 而不是 QPixmap**：QPixmap 必须在 GUI 线程创建，
而解码和预缩放是要放到后台线程去做的（否则切换风格会卡主线程几百毫秒）。
QImage 没有这个限制，`drawImage` 画预缩放好的图也够快——省掉的那次
"后台转前台"反而是净赚。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from core.utils.logger import get_logger

logger = get_logger("KillIconOverlay")

#: 与 pygame 版逐字节一致的默认帧率。素材 JSON 缺 `fps` 时用它。
DEFAULT_FPS = 30

#: 帧率的合法区间。JSON 里的脏值（0、负数、字符串）一律夹回来——
#: fps=0 在老实现里会走到 `1.0 / max(1, fps)`，这里保持同样的"不炸"承诺。
MIN_FPS = 1
MAX_FPS = 60

#: 入场淡入 / 退场淡出时长（秒）。
#:
#: 退场是**动画播完之后**再挂一段尾巴（定格在最后一帧上渐隐），
#: 不是把最后 0.25 秒的画面压暗——素材作者画的收尾动作不该被我们吃掉。
FADE_IN_SECONDS = 0.12
FADE_OUT_SECONDS = 0.25

#: 播放期间的刷新节拍（Hz）。真正决定画面切帧的是 `playback_state`，
#: 这个节拍只决定"多久去问一次"。取 60 是为了淡入淡出够平滑；
#: 帧号和不透明度都没变时不会触发重绘，所以空转成本只有一次字典比较。
TICK_HZ = 60

#: 图标垂直落点：屏幕高度的 3/4 处再往下 50 物理像素。
#: 这两个数字照抄 pygame 版（`(screen_h * 3) // 4 - h // 2 + 50`），
#: 迁移时一个像素都不许动——用户存量的偏移值是**相对这个基准**调出来的。
VERTICAL_ANCHOR_NUMERATOR = 3
VERTICAL_ANCHOR_DENOMINATOR = 4
VERTICAL_ANCHOR_BIAS_PX = 50

#: 单个动画的帧数上限。素材是用户自己导入的，这里只做"别把内存吃干"的兜底。
MAX_FRAMES = 600

#: 定格时长（秒）的上限。见 `clamp_hold`。
MAX_HOLD_SECONDS = 10.0

#: 单帧素材的默认定格时长。
#:
#: KI-4 之前，拖一张静态 PNG 进来的结果是**图标只显示 33 毫秒**：静态图没有
#: 每帧时长信息，帧率回落到 30，1 帧 ÷ 30 = 0.033 秒。用户看到的是"导入成功"
#: 弹窗，然后游戏里什么都没有——一句报错都没有。这是整条链最尴尬的一个洞，
#: 因为静态图标是完全合理的需求，而且是新手最可能第一个拖进来的东西。
DEFAULT_STATIC_HOLD_SECONDS = 1.5


def clamp_fps(value) -> int:
    """把任意脏值夹成合法帧率。"""
    try:
        fps = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_FPS
    return max(MIN_FPS, min(MAX_FPS, fps))


def clamp_hold(value) -> float:
    """把任意脏值夹成合法定格时长（秒）。缺省/脏值一律 0，即"没有定格"。"""
    try:
        hold = float(value)
    except (TypeError, ValueError):
        return 0.0
    if hold != hold:  # NaN
        return 0.0
    return max(0.0, min(MAX_HOLD_SECONDS, hold))


def duration_for_fps(frame_count: int, fps) -> float:
    """这套帧按 `fps` 播要多久（秒）。"""
    return max(0.0, int(frame_count)) / float(clamp_fps(fps))


def fps_for_duration(frame_count: int, seconds: float) -> int:
    """要让这套帧正好播 `seconds` 秒，帧率该是多少。

    设置页把"播放速度"这个控件从 **FPS** 换成了**展示时长**，靠的就是这一对
    互逆函数——用户拖的是"这个图标在屏幕上待多久"，落盘的仍是 `fps`
    （素材 JSON 的格式一个字节没变，老素材照常能用）。

    换算必然有取整误差（30 帧要播 1.7 秒 → fps=17.6 → 18 → 实际 1.67 秒），
    所以设置页显示的是**换算回来的**时长，不是用户拖的原值。
    """
    frames = max(1, int(frame_count))
    seconds = max(0.01, float(seconds))
    return clamp_fps(round(frames / seconds))


@dataclass(frozen=True)
class KillIconAnimation:
    """一套击杀等级的帧数据。`frames` 是原始尺寸，缩放后的另存缓存。

    `hold_seconds` 是**播完之后定格在最后一帧上的时长**，默认 0（即老行为）。
    它是 KI-4 唯一新增的格式字段，老素材 JSON 里读不到就是 0，逐字节等价。
    """

    frames: tuple
    fps: int
    frame_width: int
    frame_height: int
    hold_seconds: float = 0.0

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def duration(self) -> float:
        return duration_for_fps(self.frame_count, self.fps) + clamp_hold(self.hold_seconds)


# ==================================================== 纯函数：播放时间轴


def playback_state(elapsed, fps, frame_count, fade_in=0.0, fade_out=0.0, hold=0.0):
    """`(经过秒数) → (该画第几帧, 不透明度)`；播完返回 None。

    时间轴是这样的（`hold` 和 `fade_out` 两段都**在动画之后**，都定格在最后一帧）：

        0     fade_in        frames/fps      +hold          +fade_out
        |------|---------------|--------------|----------------|
         淡入   正常播放         定格            最后一帧渐隐      结束

    为什么合成一个函数而不是拆成"第几帧"和"多透明"两个：这两件事共用同一条
    时间轴，也共用"什么时候算播完"这个判断。拆开写过一版，结果是帧号说播完了、
    不透明度还在算，窗口多留了一拍——合成一个返回值就不可能对不上。

    `hold` 让"单帧素材"这件事成立：1 帧 @30fps 只有 0.033 秒，肉眼看不见。
    它同样兜住"素材只有 20 帧但我想让 ACE 图标多停一会儿"。

    `fps<=0` / 帧数为 0 这类脏输入不抛异常：素材 JSON 是用户自己导入的，
    坏数据的正确表现是"不显示"，不是让 GSI 线程炸掉。
    """
    frame_count = max(0, int(frame_count))
    if frame_count == 0:
        return None

    fps = clamp_fps(fps)
    elapsed = max(0.0, float(elapsed))
    fade_in = max(0.0, float(fade_in))
    fade_out = max(0.0, float(fade_out))

    animation_duration = frame_count / float(fps) + clamp_hold(hold)
    total = animation_duration + fade_out
    if elapsed >= total:
        return None

    index = min(frame_count - 1, int(elapsed * fps))

    opacity = 1.0
    if fade_in > 0.0 and elapsed < fade_in:
        opacity = elapsed / fade_in
    if fade_out > 0.0 and elapsed > animation_duration:
        opacity = min(opacity, 1.0 - (elapsed - animation_duration) / fade_out)
    return index, max(0.0, min(1.0, opacity))


# ==================================================== 纯函数：几何


def compute_scaled_size(frame_width, frame_height, base_width, scale):
    """按基准宽度和缩放比算出图标的**物理**像素尺寸，等比保持原始宽高比。

    宽高比取自素材本身而不是 `base_height`：老实现也是这么做的
    （`aspect_ratio = 原高 / 原宽`），`kill_icon_base_height` 实际只在
    素材缺失时当占位用。改成按 base_height 拉伸会把所有非 350:250 的
    素材压变形，而用户素材是什么比例我们管不着。
    """
    frame_width = max(1, int(frame_width or 1))
    frame_height = max(1, int(frame_height or 1))
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        scale = 1.0
    scale = max(0.1, min(4.0, scale))

    target_width = max(1, int(round(float(base_width or frame_width) * scale)))
    target_height = max(1, int(round(target_width * frame_height / frame_width)))
    return target_width, target_height


def compute_overlay_geometry(screen_geometry, dpr, physical_width, physical_height,
                             offset_x=0, offset_y=0):
    """`(屏幕逻辑几何, 缩放, 图标物理尺寸, 偏移) → 窗口的逻辑矩形`。

    ⚠ 这里是本模块最容易出错的地方，和准心那边的
    `compute_centered_geometry` 是同一类坑：**`setGeometry` 收逻辑像素，
    而图标尺寸和用户调的偏移值都是物理像素**。125% 缩放屏上直接把物理值
    传进去，图标会整体放大 25%、偏移也跟着多走 25%。

    所以算法是：先在物理像素空间里把落点算完（这样才和 pygame 版逐像素
    对得上），最后一步除以 dpr 换回逻辑像素。

    纯函数，为的是不依赖真实多屏/高 DPI 环境就能验。
    """
    x, y, width, height = screen_geometry
    try:
        dpr = float(dpr) or 1.0
    except (TypeError, ValueError):
        dpr = 1.0
    if dpr <= 0:
        dpr = 1.0

    screen_w = float(width) * dpr
    screen_h = float(height) * dpr

    physical_width = max(1, int(physical_width))
    physical_height = max(1, int(physical_height))

    base_x = (screen_w - physical_width) / 2.0
    base_y = (
        screen_h * VERTICAL_ANCHOR_NUMERATOR / VERTICAL_ANCHOR_DENOMINATOR
        - physical_height / 2.0
        + VERTICAL_ANCHOR_BIAS_PX
    )

    physical_x = base_x + int(offset_x or 0)
    physical_y = base_y + int(offset_y or 0)

    return (
        x + int(round(physical_x / dpr)),
        y + int(round(physical_y / dpr)),
        max(1, int(round(physical_width / dpr))),
        max(1, int(round(physical_height / dpr))),
    )


# ==================================================== 素材装载


def _read_metadata(path):
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        logger.warning(f"读取击杀图标配置失败 {path}: {exc}")
        return {}


def load_sprite_sheet(sprite_path, json_path):
    """从图集 + JSON 切出帧序列。切不出来返回 None。"""
    if not os.path.isfile(sprite_path):
        return None
    metadata = _read_metadata(json_path)

    sheet = QImage(sprite_path)
    if sheet.isNull():
        logger.warning(f"击杀图标图集读不出来: {sprite_path}")
        return None

    frame_width = int(metadata.get("frame_width") or 0)
    frame_height = int(metadata.get("frame_height") or 0)
    if frame_width <= 0 or frame_height <= 0:
        logger.warning(f"击杀图标配置缺少帧尺寸: {json_path}")
        return None

    cols = int(metadata.get("cols") or 0) or max(1, sheet.width() // frame_width)
    frame_count = int(metadata.get("frames") or 0) or cols
    frame_count = max(0, min(frame_count, MAX_FRAMES))

    frames = []
    for index in range(frame_count):
        left = (index % cols) * frame_width
        top = (index // cols) * frame_height
        if left + frame_width > sheet.width() or top + frame_height > sheet.height():
            # 图集比 JSON 声称的小：能切几帧算几帧，不整套丢弃。
            break
        frames.append(sheet.copy(left, top, frame_width, frame_height))

    if not frames:
        return None
    return KillIconAnimation(
        frames=tuple(frames),
        fps=clamp_fps(metadata.get("fps", DEFAULT_FPS)),
        frame_width=frame_width,
        frame_height=frame_height,
        hold_seconds=clamp_hold(metadata.get("hold_seconds", 0.0)),
    )


def load_frame_sequence(frames_dir, metadata_path=None):
    """老格式：一个目录里一堆图片，按文件名排序当帧序列。"""
    if not frames_dir or not os.path.isdir(frames_dir):
        return None
    try:
        names = sorted(os.listdir(frames_dir))
    except OSError as exc:
        logger.warning(f"读取击杀图标目录失败 {frames_dir}: {exc}")
        return None

    frames = []
    for name in names:
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
            continue
        path = os.path.join(frames_dir, name)
        if not os.path.isfile(path):
            continue
        image = QImage(path)
        if image.isNull():
            continue
        frames.append(image)
        if len(frames) >= MAX_FRAMES:
            break

    if not frames:
        return None
    metadata = _read_metadata(metadata_path)
    return KillIconAnimation(
        frames=tuple(frames),
        fps=clamp_fps(metadata.get("fps", DEFAULT_FPS)),
        frame_width=frames[0].width(),
        frame_height=frames[0].height(),
        hold_seconds=clamp_hold(metadata.get("hold_seconds", 0.0)),
    )


def load_level_animation(style_name, kills, variant=""):
    """按"图集优先、逐帧目录兜底"的顺序装载一个击杀等级。

    这两代格式的兼容逻辑是从 pygame 版原样搬过来的，连顺序都没换：
    存量用户的资源目录里两种都有，改判定顺序等于让一部分人的图标凭空消失。
    """
    from resource_manager import ResourceManager

    sprite_path, json_path = ResourceManager.get_kill_icon_sprite_sheet_paths(
        style_name, kills, variant=variant
    )
    animation = load_sprite_sheet(sprite_path, json_path)
    if animation is not None:
        return animation

    if variant:
        # 爆头等变体只认图集，不往逐帧目录上兜——老格式里没有变体这个概念，
        # 兜过去只会把普通图标当成爆头图标用。
        return None

    legacy_dir = ResourceManager.get_kill_icon_legacy_frames_dir(style_name, kills)
    if not legacy_dir:
        return None
    return load_frame_sequence(
        legacy_dir, ResourceManager.get_kill_icon_metadata_path(style_name, kills)
    )


def load_level_thumbnail(style_name, kills, variant=""):
    """只取第一帧，给风格卡片当缩略图用。装不出来返回 None。

    **不能用 `load_level_animation` 代替**：那个会把整套帧切出来，而风格库里
    有几套风格就要装几次。用户真实的默认风格光 5 杀就 201 帧、整套 519 帧，
    按 `load_level_animation` 走一遍是几百毫秒起步——而这些帧**一帧都用不上**，
    卡片上只画第一帧。KI-3 就为"建页时同步解码整套帧"的同款问题挨过一次
    （46 帧 41ms，占建页耗时一半），那次的量级还小得多。

    图集这条路只读一次 QImage 再 copy 一个矩形；逐帧目录这条路只读排在最前
    的那个文件，`os.listdir` 之后就不再碰别的帧了。
    """
    from resource_manager import ResourceManager

    sprite_path, json_path = ResourceManager.get_kill_icon_sprite_sheet_paths(
        style_name, kills, variant=variant
    )
    if os.path.isfile(sprite_path):
        metadata = _read_metadata(json_path)
        frame_width = int(metadata.get("frame_width") or 0)
        frame_height = int(metadata.get("frame_height") or 0)
        sheet = QImage(sprite_path)
        if not sheet.isNull():
            if frame_width <= 0 or frame_height <= 0:
                # 没有 JSON 也别放弃：整张图当一帧总比什么都不显示强
                return sheet
            if frame_width <= sheet.width() and frame_height <= sheet.height():
                return sheet.copy(0, 0, frame_width, frame_height)
            return sheet

    if variant:
        return None

    legacy_dir = ResourceManager.get_kill_icon_legacy_frames_dir(style_name, kills)
    if not legacy_dir or not os.path.isdir(legacy_dir):
        return None
    try:
        names = sorted(os.listdir(legacy_dir))
    except OSError:
        return None
    for name in names:
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
            continue
        image = QImage(os.path.join(legacy_dir, name))
        if not image.isNull():
            return image
    return None


def scale_animation(animation, physical_width, physical_height):
    """把整套帧预缩放到目标物理尺寸。

    预缩放放在**装载期**做，不是播放期。老实现是在击杀那一瞬间才发现缓存
    未命中、当场 `smoothscale` 整套帧的（`kill_icon_player.py:298`），
    表现就是"每次换风格后的第一次击杀掉帧"。
    """
    if animation is None or not animation.frames:
        return ()
    width = max(1, int(physical_width))
    height = max(1, int(physical_height))
    return tuple(
        frame.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        for frame in animation.frames
    )


def paint_frame(painter, frame, dpr=1.0, opacity=1.0):
    """把一帧画到 painter 上（物理像素空间，左上角对齐）。

    与准心同一个套路：先 `scale(1/dpr)` 换进物理像素空间再画。帧是按物理
    尺寸预缩放好的，这样"屏幕上有多大"就与 Windows 缩放无关了。

    ⚠ 淡入淡出走 `painter.setOpacity`，**不是**窗口的 `setWindowOpacity`。
    Windows 上无边框透明窗做窗口级 opacity 动画有花屏/整窗变黑的历史问题
    （QTBUG-29010 一族），而且窗口级 opacity 会连带影响合成路径；
    画的时候调 alpha 只是改一次绘制状态，没有这些副作用。
    """
    if frame is None or frame.isNull():
        return False
    try:
        dpr = float(dpr) or 1.0
    except (TypeError, ValueError):
        dpr = 1.0
    if dpr <= 0:
        dpr = 1.0

    painter.save()
    if dpr != 1.0:
        painter.scale(1.0 / dpr, 1.0 / dpr)
    painter.setOpacity(max(0.0, min(1.0, float(opacity))))
    painter.drawImage(0, 0, frame)
    painter.restore()
    return True


def render_frame_to_image(frame, opacity=1.0):
    """把一帧渲染进一张离屏 QImage —— 设置页的预览和测试都用它。

    预览**必须**走这个函数，不许在页面里另写一段绘制。准心那边"预览是第二套
    独立绘制代码"的教训很贵：十字预览大了一倍、点准心随粗细漂移，两套几何
    各画各的，肉眼才能发现。
    """
    if frame is None or frame.isNull():
        return None
    canvas = QImage(frame.width(), frame.height(), QImage.Format_ARGB32_Premultiplied)
    canvas.fill(0)
    painter = QPainter(canvas)
    paint_frame(painter, frame, dpr=1.0, opacity=opacity)
    painter.end()
    return canvas
