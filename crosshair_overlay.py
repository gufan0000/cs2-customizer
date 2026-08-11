# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""准心叠加层的 Qt 实现（R8b / UP-054）。

设计依据见 [docs/ui-perf/06_R8b_准心Qt化_设计文档.md]。要点复述三条：

1. **为什么不是 pygame**：老实现把窗口建在主线程（`pygame.display.set_mode`），
   却在工作线程调 `event.get()` / `display.flip()`——违反 Win32 的窗口线程亲和性。
   Qt 天生强制「QWidget 只能在主线程」，这一整类问题结构性消失。
2. **窗口配方照抄 `screen_effect_overlay.EdgeParticleOverlay`**，不自创。
   那套标志/扩展样式的组合已经在生产里画在游戏上了，缺任何一项都会破坏
   「不打扰前台」（少 `WA_ShowWithoutActivating` 会抢焦点把游戏切出去，
   少 `WS_EX_TRANSPARENT` 会吃掉屏幕正中的鼠标点击）。
3. **一切坐标按物理像素算**。Qt 的绘制坐标是逻辑像素，缩放屏上 1 逻辑 = 1.25 物理；
   而准心是功能性元素，`crosshair_size=20` 指的是屏幕上真实的 20 个点。
   所以这里统一 `painter.scale(1/dpr)` 后在物理像素空间里画——
   准心差几个像素就毫无意义，这是本模块最不能出错的地方。

本文件刻意分成两层：

    paint_crosshair(painter, frame)   ← 纯函数，只认一个 CrosshairFrame
    CrosshairOverlayWindow(QWidget)   ← 窗口与生命周期

拆开是为了让渲染能**离屏逐样式验**（画进 QImage 断言有非透明像素），
不必创建任何窗口、不打扰前台。动画层（R8b-B/C）同样会做成
「(状态, 时间) → CrosshairFrame」的纯函数，那样帧率解耦才验得动。
"""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from core.utils.logger import get_logger

logger = get_logger("CrosshairOverlay")

#: 画布边长（物理像素）。R8a 之前就定下的 100x100，迁移时原样保住——
#: 击杀联动里最大的扩散半径是 40（直径 80），仍在画布内。
CANVAS_PX = 100

#: 与 pygame 版逐字节一致的颜色表，别改值（用户存量配置指向这些名字）
COLOR_MAP = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "white": (255, 255, 255),
}
DEFAULT_COLOR = (0, 255, 0)

#: UI 上真正给用户选的五个样式。
#: `t_shape` 是 R9-A 补进来的（UP-086）：它在老渲染器里一直有一整个绘制分支，
#: 但从没接到 UI 上，全仓够不着。CS2 自己有 `cl_crosshair_t`，T 型准心是真实
#: 打法（去掉上半段，不挡爆头线），所以按「补进 UI」而不是「当死代码删」处理。
#: ⚠ 这里是样式的**唯一真相源**，`pages/crosshair_page.py` 的中文名表要与它同步，
#: `tests/test_crosshair_style_catalog_r9a.py` 会盯着两边不许漂移。
USER_STYLES = ("crosshair", "dot", "circle", "t_shape", "custom")

#: 渲染器内部样式：不出现在 UI 上，由击杀联动驱动（R8b-C 接入）
INTERNAL_STYLES = ("x_mark", "shatter")

#: 空闲动画，顺序与 `pages/crosshair_page.py` 的下拉框一一对应
IDLE_ANIMATIONS = (
    "none", "breathing", "pulse", "color", "rotate",
    "wave", "bounce", "blink", "shake",
)

#: 相位推进速度（弧度/秒）。
#: 老实现是 `self.animation_phase += 0.05` **每帧**，在 24FPS 下就是 1.2 rad/s。
#: 这里换成按时间算，取值使 24FPS 下的观感与老版逐帧一致——
#: 换算不是为了「更精确」，是因为按帧计数意味着**帧率一变动画速度就变**，
#: 而 R8b 恰好要动帧率策略（静态准心从 tick(1) 改成完全不跑定时器）。
PHASE_RATE = 0.05 * 24

#: 击杀联动，顺序与 `pages/crosshair_page.py` 的下拉框一一对应
KILL_EFFECTS = (
    "none", "pulse", "explosion", "rotate", "shake", "x_flash",
    "rainbow_wave", "shatter", "multi_pulse", "neon_wave", "x_overlay",
)

#: 一次击杀联动的时长，与老实现一致
KILL_DURATION_S = 0.8

#: pulse 动画的触发频率。老实现是每帧 `random.random() < 0.01`，
#: 24FPS 下 = 每秒 0.24 次。换成按时间算的泊松过程，频率不随帧率漂移。
PULSE_RATE_HZ = 0.01 * 24
#: 一次 pulse 的持续时间。老实现只持续 1 帧（24FPS 下约 42ms），
#: 固定成时长后，60FPS 下也能看到同样长短的一下放大，而不是一闪而过。
PULSE_HOLD_S = 1.0 / 24


def compute_centered_geometry(screen_geometry, dpr: float):
    """算出画布的**逻辑像素**几何，使其物理边长 = CANVAS_PX 且居中于屏幕。

    做成纯函数是为了能不依赖真实缩放屏就验 1.0 / 1.25 / 1.5 三档
    ——本模块最容易出错、也最致命的就是这里（准心偏几个像素就废了）。

    `setGeometry` 收的是逻辑像素，而 `crosshair_size=20` 指的是屏幕上真实的
    20 个点。所以边长要除以 dpr 反算回去：不这么做的话，125% 缩放屏上
    窗口会变成 125 物理像素、准心跟着整体放大 25%。
    """
    x, y, w, h = screen_geometry
    dpr = float(dpr) if dpr else 1.0
    logical = max(1, int(round(CANVAS_PX / dpr)))
    return (x + (w - logical) // 2, y + (h - logical) // 2, logical, logical)


def resolve_color(name, alpha=255) -> QColor:
    r, g, b = COLOR_MAP.get(str(name or ""), DEFAULT_COLOR)
    return QColor(r, g, b, alpha)


@dataclass
class CrosshairFrame:
    """一帧准心的完整描述（**物理像素**坐标系，原点在画布左上角）。

    动画层的产物就是它：R8b-B/C 的每个动画/联动最终都只是在改这里的字段，
    渲染层完全不知道「呼吸」「爆炸」这些概念。
    """

    style: str = "crosshair"
    size: int = 20
    thickness: int = 2
    color: QColor = field(default_factory=lambda: QColor(0, 255, 0, 255))
    center: QPointF = field(default_factory=lambda: QPointF(CANVAS_PX / 2, CANVAS_PX / 2))
    rotation: float = 0.0          # 角度制，与老实现一致
    antialias: bool = False        # 默认关：准心是功能件不是装饰，抗锯齿会让 1px 细线糊成灰边
    custom_points: tuple = ()      # style == "custom" 时的像素点，(x, y) 取值 0..30

    #: 击杀联动里有三个（rainbow_wave / neon_wave / x_overlay）不改准心本身，
    #: 而是**另外画**扩散环或十字星辉。它们走这条通道，渲染层照单画即可。
    overlays: tuple = ()

    #: shatter（破碎重组）专用：碎片是在触发那一刻一次生成的，之后按进度外扩
    shatter_progress: float = 0.0
    shatter_fragments: tuple = ()
    shatter_base_style: str = "crosshair"


@dataclass
class CrosshairState:
    """用户在准心页选出来的东西——也就是配置里存的那几项。

    与 `CrosshairFrame` 的分工：State 是「用户选了什么」，Frame 是
    「这一瞬间该画成什么样」。动画层就是 `(State, 时间) → Frame` 这个映射。
    """

    size: int = 20
    thickness: int = 2
    color: str = "green"
    style: str = "crosshair"
    animation: str = "none"
    kill_effect: str = "none"
    custom_points: tuple = ()
    antialias: bool = False


@dataclass
class RingOverlay:
    """一圈描边圆（rainbow_wave 的冲击波、neon_wave 的三层扩散）。"""

    radius: float
    color: QColor
    width: int = 2


@dataclass
class LineOverlay:
    """一条线段（x_overlay 的十字星辉由四条构成）。"""

    x1: float
    y1: float
    x2: float
    y2: float
    color: QColor
    width: int = 2


def hsv_to_rgb(h: float, s: float, v: float):
    """与老实现同款的 HSV→RGB（0..1 输入，0..255 输出）。

    没有换成 `QColor.fromHsvF`：那个在边界上的取整与老实现有差异，
    而这里的目的是**观感等价**，不是「用更标准的 API」。
    """
    if s == 0.0:
        return (int(v * 255), int(v * 255), int(v * 255))
    i = int(h * 6)
    f = (h * 6) - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    i %= 6
    table = (
        (v, t, p), (q, v, p), (p, v, t),
        (p, q, v), (t, p, v), (v, p, q),
    )
    return tuple(int(c * 255) for c in table[i])


def brighten(color: QColor, factor: float) -> QColor:
    return QColor(
        min(255, int(color.red() * factor)),
        min(255, int(color.green() * factor)),
        min(255, int(color.blue() * factor)),
        color.alpha(),
    )


def dim(color: QColor, factor: float) -> QColor:
    """调暗颜色。

    老实现这里有个 `max(1, ...)` 的下限钳制，注释写着「纯黑是分层窗口的
    透明色键，压暗到精确纯黑会被整块抠成透明」。Qt 用的是逐像素 alpha
    不是颜色键控，**这个钳制没有存在意义了**，故去掉。

    影响面：六种可选颜色都是饱和色（最暗的分量本来就是 0），
    ×0.7 之后没有一个会落到纯黑，所以对现有配置是**逐像素等价**的。
    """
    return QColor(
        int(color.red() * factor),
        int(color.green() * factor),
        int(color.blue() * factor),
        color.alpha(),
    )


class CrosshairAnimator:
    """把 `CrosshairState` + 时间，算成一帧 `CrosshairFrame`。

    刻意做成可注入 `rng` 的对象：`pulse` / `shake` 带随机性，
    不能注入的话「频率不随帧率漂移」这条判据根本没法验（D-5）。
    """

    def __init__(self, rng=None):
        import random as _random

        self._rng = rng if rng is not None else _random.Random()
        self._last_t = None
        self._pulse_until = 0.0
        self._kill_type = None
        self._kill_start = 0.0
        self._kill_fragments = ()

    def reset(self):
        self._last_t = None
        self._pulse_until = 0.0
        self._kill_type = None
        self._kill_fragments = ()

    # -------------------------------------------------------------- 击杀联动

    def trigger_kill(self, state: CrosshairState, now: float) -> bool:
        """收到击杀事件。返回是否真的起了动画（`none` 不起）。

        ⚠ 只能在主线程调——`CrosshairOverlayManager` 用 Signal 把 GSI 线程的
        事件排队过来，就是为了保证这一点。
        """
        effect = str(state.kill_effect or "none")
        if effect == "none" or effect not in KILL_EFFECTS:
            return False
        self._kill_type = effect
        self._kill_start = now
        self._kill_fragments = (
            self._make_fragments(state) if effect == "shatter" else ()
        )
        return True

    def kill_active(self, now: float) -> bool:
        return (self._kill_type is not None
                and (now - self._kill_start) <= KILL_DURATION_S)

    def _make_fragments(self, state: CrosshairState):
        """破碎效果的碎片：触发时一次生成，之后只按进度外扩。

        老实现是靠 `kill_animation_start_time != last_shatter_time` 来判断
        「要不要重新生成」——那等于把生成时机藏在绘制循环里。
        这里改成在触发点显式生成，行为一样但不需要那个哨兵变量。
        """
        import math

        size = max(1, int(state.size))
        if state.style in ("crosshair", "t_shape"):
            # 与 `_paint_shatter` 的线状分支配套：线状样式碎片更多、飞得更远
            count, lo, hi, frag = 8, 0.3, 1.0, max(3, size // 3)
        else:
            count, lo, hi, frag = 6, 0.2, 0.8, max(2, size // 4)
        out = []
        for i in range(count):
            angle = 2 * math.pi * i / count
            distance = self._rng.uniform(lo, hi) * size
            out.append((
                math.cos(angle) * distance,
                math.sin(angle) * distance,
                frag,
                self._rng.uniform(0, math.pi),
            ))
        return tuple(out)

    @staticmethod
    def needs_timer(state: CrosshairState, kill_active: bool = False) -> bool:
        """静态准心一帧都不用重画——比老实现的 `clock.tick(1)` 再省一步。"""
        return kill_active or str(state.animation or "none") != "none"

    def advance(self, state: CrosshairState, now: float) -> CrosshairFrame:
        import math

        dt = 0.0 if self._last_t is None else max(0.0, now - self._last_t)
        self._last_t = now

        color = resolve_color(state.color)
        frame = CrosshairFrame(
            style=state.style,
            size=max(1, int(state.size)),
            thickness=max(1, int(state.thickness)),
            color=color,
            center=QPointF(CANVAS_PX / 2, CANVAS_PX / 2),
            antialias=bool(state.antialias),
            custom_points=tuple(tuple(p) for p in (state.custom_points or ())),
        )

        animation = str(state.animation or "none")
        if animation == "none":
            self._apply_kill(frame, state, now)
            return frame

        # 相位按**时间**推进（见 PHASE_RATE 的说明），不是按帧计数
        phase = (now * PHASE_RATE) % (2 * math.pi)
        sin_p = math.sin(phase)
        sin_2p = math.sin(phase * 2)
        sin_3p = math.sin(phase * 3)

        if animation == "breathing":
            frame.size = int(frame.size * (1.0 + 0.2 * abs(sin_p)))

        elif animation == "pulse":
            # 泊松过程：每帧触发概率 = 频率 × dt，于是每秒期望触发次数与帧率无关
            if now < self._pulse_until:
                frame.size = int(frame.size * 1.3)
            elif dt > 0 and self._rng.random() < PULSE_RATE_HZ * dt:
                self._pulse_until = now + PULSE_HOLD_S
                frame.size = int(frame.size * 1.3)

        elif animation == "color":
            frame.color = QColor(
                int((math.sin(phase) * 0.5 + 0.5) * 255),
                int((math.sin(phase + 2.0) * 0.5 + 0.5) * 255),
                int((math.sin(phase + 4.0) * 0.5 + 0.5) * 255),
                255,
            )

        elif animation == "rotate":
            frame.rotation = math.degrees(phase)

        elif animation == "wave":
            frame.size = int(frame.size * (1.0 + 0.15 * sin_2p))
            frame.thickness = max(1, int(frame.thickness * (1.0 + 0.2 * sin_3p)))

        elif animation == "bounce":
            frame.center = QPointF(frame.center.x(), frame.center.y() + sin_2p * 5)

        elif animation == "blink":
            frame.color = brighten(color, 1.5) if sin_3p > 0 else dim(color, 0.7)

        elif animation == "shake":
            frame.center = QPointF(
                frame.center.x() + self._rng.uniform(-2.0, 2.0),
                frame.center.y() + self._rng.uniform(-2.0, 2.0),
            )

        self._apply_kill(frame, state, now)
        return frame

    def _apply_kill(self, frame: CrosshairFrame, state: CrosshairState, now: float) -> None:
        """把击杀联动叠在空闲动画**之上**——顺序与老实现一致。"""
        import math

        if self._kill_type is None:
            return
        elapsed = now - self._kill_start
        if elapsed > KILL_DURATION_S:
            self._kill_type = None
            self._kill_fragments = ()
            return

        progress = max(0.0, elapsed / KILL_DURATION_S)
        effect = self._kill_type
        base_color = resolve_color(state.color)

        if effect == "pulse":
            frame.size = int(frame.size * (1.0 + math.sin(progress * math.pi)))

        elif effect == "explosion":
            factor = (1.0 + progress * 4.0) if progress < 0.5 else (3.0 - (progress - 0.5) * 4.0)
            frame.size = int(frame.size * factor)

        elif effect == "rotate":
            frame.rotation += progress * 720

        elif effect == "shake":
            intensity = 10.0 * (1.0 - progress)
            frame.center = QPointF(
                frame.center.x() + self._rng.uniform(-intensity, intensity),
                frame.center.y() + self._rng.uniform(-intensity, intensity),
            )

        elif effect == "x_flash":
            if progress < 0.4:
                frame.style = "x_mark"
                frame.color = QColor(255, 0, 0, 255)
            else:
                frame.color = brighten(base_color, 1.5)

        elif effect == "rainbow_wave":
            r, g, b = hsv_to_rgb(((progress * 360) % 360) / 360, 1.0, 1.0)
            radius = progress * 40
            if radius > 0:
                frame.overlays = frame.overlays + (
                    RingOverlay(radius, QColor(r, g, b, int(255 * (1.0 - progress))), 2),
                )

        elif effect == "shatter":
            frame.shatter_fragments = self._kill_fragments
            frame.shatter_base_style = state.style
            if progress < 0.3:
                frame.style = "shatter"
                frame.shatter_progress = progress / 0.3
            elif progress < 0.7:
                frame.style = "dot"
                frame.size = max(3, int(state.size) // 8)
            else:
                frame.style = "shatter"
                frame.shatter_progress = 1.0 - (progress - 0.7) / 0.3

        elif effect == "multi_pulse":
            wave = abs(math.sin(progress * math.pi * 15))
            frame.size = int(frame.size * (1.0 + 0.8 * wave))
            frame.color = brighten(base_color, (0.7 + 0.3 * wave) + 0.5)

        elif effect == "neon_wave":
            r, g, b = hsv_to_rgb(((progress * 360) % 360) / 360, 1.0, 1.0)
            frame.color = QColor(r, g, b, 255)
            rings = []
            for i in range(3):
                wave_progress = (progress + i * 0.2) % 1.0
                alpha = int(255 * (1.0 - wave_progress))
                if alpha > 0:
                    rings.append(RingOverlay(
                        wave_progress * 40,
                        QColor(r, g, b, alpha),
                        max(1, int(frame.thickness * (1.0 - wave_progress))),
                    ))
            frame.overlays = frame.overlays + tuple(rings)

        elif effect == "x_overlay":
            frame.overlays = frame.overlays + self._x_overlay_lines(frame, state)

    @staticmethod
    def _x_overlay_lines(frame: CrosshairFrame, state: CrosshairState):
        """十字星辉：四条从内圈射向外圈的 45° 线段。"""
        import math

        cx, cy = frame.center.x(), frame.center.y()
        rad = math.radians(45)
        cos_v, sin_v = math.cos(rad), math.sin(rad)
        length = int(int(state.size) * 1.8 // 2)
        gap = max(3, frame.size // 4)
        color = resolve_color(state.color)
        width = max(1, frame.thickness)

        pairs = (
            ((cos_v, sin_v), 1), ((cos_v, sin_v), -1),
            ((sin_v, -cos_v), 1), ((sin_v, -cos_v), -1),
        )
        return tuple(
            LineOverlay(
                cx + length * dx * sign, cy + length * dy * sign,
                cx + gap * dx * sign, cy + gap * dy * sign,
                color, width,
            )
            for (dx, dy), sign in pairs
        )


def _draw_line(painter, x1, y1, x2, y2):
    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def paint_crosshair(painter: QPainter, frame: CrosshairFrame) -> None:
    """把一帧准心画到 painter 上（纯函数，不碰任何全局状态）。

    调用方负责：已经把坐标系换算到物理像素、已经清好背景。
    """
    painter.setRenderHint(QPainter.Antialiasing, bool(frame.antialias))

    pen = QPen(frame.color)
    pen.setWidth(max(1, int(frame.thickness)))
    pen.setCapStyle(Qt.FlatCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    cx, cy = frame.center.x(), frame.center.y()
    size = max(1, int(frame.size))
    half = size // 2
    style = frame.style

    if style == "crosshair":
        if frame.rotation:
            _paint_rotated_cross(painter, cx, cy, half, frame.rotation)
        else:
            _draw_line(painter, cx, cy - half, cx, cy + half)
            _draw_line(painter, cx - half, cy, cx + half, cy)

    elif style == "dot":
        radius = max(2, size // 4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(frame.color)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

    elif style == "circle":
        radius = max(5, size // 2)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

    elif style == "t_shape":
        # T 型：横杆整条 + 竖杆只向下半条（上半段留空，不挡爆头线）
        _paint_t_shape(painter, cx, cy, half, frame.rotation)

    elif style == "x_mark":
        # 击杀联动 x_flash 的前 40% 会切到这个样式
        length = half
        _draw_line(painter, cx - length, cy - length, cx + length, cy + length)
        _draw_line(painter, cx - length, cy + length, cx + length, cy - length)

    elif style == "custom":
        _paint_custom(painter, frame, cx, cy, size)

    elif style == "shatter":
        _paint_shatter(painter, frame, cx, cy)

    _paint_overlays(painter, frame)


def _paint_overlays(painter, frame):
    """画击杀联动额外要的图元（扩散环 / 十字星辉）。

    这些**不是准心本身**，所以放在准心之后画、且各自带自己的画笔颜色，
    不受 `frame.color` 影响——老实现里它们也是这么独立算色的。
    """
    for item in frame.overlays or ():
        if isinstance(item, RingOverlay):
            if item.radius <= 0:
                continue
            pen = QPen(item.color)
            pen.setWidth(max(1, int(item.width)))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(frame.center, item.radius, item.radius)
        elif isinstance(item, LineOverlay):
            pen = QPen(item.color)
            pen.setWidth(max(1, int(item.width)))
            painter.setPen(pen)
            _draw_line(painter, item.x1, item.y1, item.x2, item.y2)


def _paint_shatter(painter, frame, cx, cy):
    """破碎重组：碎片按进度从中心外扩，形状随**原准心样式**变。"""
    import math

    progress = frame.shatter_progress
    thickness = max(1, int(frame.thickness))
    pen = QPen(frame.color)
    pen.setWidth(max(1, thickness - 1))
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    for dx, dy, frag_size, angle in frame.shatter_fragments or ():
        x = cx + dx * progress
        y = cy + dy * progress
        if frame.shatter_base_style in ("crosshair", "t_shape"):
            # 线状样式碎成线段；点/圆/自定义走下面的兜底（圆点碎片）
            half = frag_size // 2
            a = angle + progress * math.pi
            _draw_line(painter,
                       x - math.cos(a) * half, y - math.sin(a) * half,
                       x + math.cos(a) * half, y + math.sin(a) * half)
        elif frame.shatter_base_style == "circle":
            # QPainter 的弧以 1/16 度为单位
            rect_x, rect_y = x - frag_size, y - frag_size
            painter.drawArc(int(rect_x), int(rect_y), int(frag_size * 2), int(frag_size * 2),
                            int(math.degrees(angle) * 16), 180 * 16)
        else:
            painter.setBrush(frame.color)
            painter.setPen(Qt.NoPen)
            radius = max(1, frag_size // 2)
            painter.drawEllipse(QPointF(x, y), radius, radius)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)


def _paint_t_shape(painter, cx, cy, half, angle_deg=0.0):
    """T 型准心。angle_deg=0 时几何与老渲染器 `crosshair_animation.py` 逐点一致：
    横杆 (cx-half, cy)→(cx+half, cy)，竖杆 (cx, cy)→(cx, cy+half)。

    竖杆只有下半条，所以它**不是**中心对称的——旋转时必须绕中心转向量，
    不能照搬 `_paint_rotated_cross` 那套「两条过心线」的写法。
    """
    import math

    rad = math.radians(angle_deg or 0.0)
    cos_v, sin_v = math.cos(rad), math.sin(rad)

    def rot(dx, dy):
        return cx + dx * cos_v - dy * sin_v, cy + dx * sin_v + dy * cos_v

    x1, y1 = rot(-half, 0)
    x2, y2 = rot(half, 0)
    _draw_line(painter, x1, y1, x2, y2)

    sx, sy = rot(0, half)
    _draw_line(painter, cx, cy, sx, sy)


def _paint_rotated_cross(painter, cx, cy, length, angle_deg):
    import math

    rad = math.radians(angle_deg)
    cos_v, sin_v = math.cos(rad), math.sin(rad)
    _draw_line(painter,
               cx + length * cos_v, cy + length * sin_v,
               cx - length * cos_v, cy - length * sin_v)
    _draw_line(painter,
               cx + length * sin_v, cy - length * cos_v,
               cx - length * sin_v, cy + length * cos_v)


def _paint_custom(painter, frame, cx, cy, size):
    """自定义准心：一张 30x30 的像素画，(15, 15) 是中心。

    换算方式与老实现保持一致（`scale = size / 15`，方块边长 = 线宽），
    否则用户存量的自定义图案会整体缩放变形。
    """
    import math

    points = frame.custom_points or ()
    if not points:
        return

    scale = size / 15.0
    pixel = max(1, int(frame.thickness))
    painter.setPen(Qt.NoPen)
    painter.setBrush(frame.color)

    rad = math.radians(frame.rotation) if frame.rotation else 0.0
    cos_v, sin_v = (math.cos(rad), math.sin(rad)) if frame.rotation else (1.0, 0.0)

    for point in points:
        try:
            x, y = point
        except (TypeError, ValueError):
            continue
        rel_x = (x - 15) * scale
        rel_y = (y - 15) * scale
        if frame.rotation:
            abs_x = cx + rel_x * cos_v - rel_y * sin_v
            abs_y = cy + rel_x * sin_v + rel_y * cos_v
        else:
            abs_x = cx + rel_x
            abs_y = cy + rel_y
        painter.drawRect(int(abs_x - pixel / 2), int(abs_y - pixel / 2), pixel, pixel)


class CrosshairOverlayWindow(QWidget):
    """透明、置顶、点击穿透、不抢焦点的 100x100 画布。

    ⚠ 这五个 Qt 标志 + 四个 Win32 扩展样式是一整套，别按直觉删减。
    组合来自 `screen_effect_overlay.EdgeParticleOverlay`（已在生产里画在游戏上）。
    """

    def __init__(self):
        super().__init__(None)
        self._win32_style_applied = False
        self._frame = CrosshairFrame()

        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        # PySide6 不同版本这两个枚举的挂载位置不一样，沿用特效层的兼容写法
        for name in ("WindowTransparentForInput", "WindowDoesNotAcceptFocus"):
            flag = getattr(Qt, name, None)
            if flag is None and hasattr(Qt, "WindowType"):
                flag = getattr(Qt.WindowType, name, None)
            if flag is not None:
                flags |= flag
        self.setWindowFlags(flags)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)   # 不抢焦点 = 不把游戏切出去
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    # ------------------------------------------------------------------ 几何

    def device_pixel_ratio(self) -> float:
        screen = self.screen() or QApplication.primaryScreen()
        try:
            return float(screen.devicePixelRatio()) if screen else 1.0
        except Exception:
            return 1.0

    def recenter(self) -> bool:
        screen = QApplication.primaryScreen()
        if screen is None:
            return False
        geo = screen.geometry()
        self.setGeometry(*compute_centered_geometry(
            (geo.x(), geo.y(), geo.width(), geo.height()), self.device_pixel_ratio()))
        return True

    # ------------------------------------------------------------------ 绘制

    def set_frame(self, frame: CrosshairFrame) -> None:
        self._frame = frame
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        dpr = self.device_pixel_ratio()
        if dpr and dpr != 1.0:
            # 换到物理像素空间：下面所有坐标就都是「屏幕上真实的点」
            painter.scale(1.0 / dpr, 1.0 / dpr)
        paint_crosshair(painter, self._frame)
        painter.end()

    # ------------------------------------------------- Win32 点击穿透（补刀）

    def apply_click_through(self) -> bool:
        """Qt 标志已经声明了穿透，这里再从 Win32 层补一遍。

        原因与特效层一致：`WindowTransparentForInput` 在部分 Qt/驱动组合下
        不落到扩展样式上，而准心正好盖在屏幕正中——漏一次就是用户点不动东西。
        """
        if self._win32_style_applied or not sys.platform.startswith("win"):
            return False
        try:
            hwnd = int(self.winId())
            if not hwnd:
                return False
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_NOACTIVATE = 0x08000000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            self._win32_style_applied = True
            return True
        except Exception as exc:
            logger.debug(f"应用点击穿透扩展样式失败: {exc}")
            return False


class CrosshairOverlayManager(QObject):
    """准心的对外门面。**接口与 `CrosshairAnimationSystem` 逐个方法对齐**，
    这样 R8b-D 换渲染器时调用方一行都不用改
    （`gui_widget` / `pages/crosshair_page` / `pages/magnifier_page` 共 12 处调用）。

    线程模型（设计文档 §6）：击杀事件从 **GSI 服务器线程**来，而 Qt 控件只能
    在主线程碰。所以 `on_kill_event` 只负责 `emit`，真正改状态的
    `_handle_kill` 挂在信号上，由 Qt 排队投递回主线程。

    ⚠ 别把这个连接写成 `DirectConnection`——那等于没改，回到老实现
    「在别的线程里动窗口」的老路上（那正是 UP-054 的根因）。
    """

    _kill_signal = Signal(bool)

    #: 24FPS。保留老实现的锁帧值，但**理由不是省 CPU**——实测一帧只要
    #: 0.0065ms（最贵的组合 0.065ms），24FPS 下占主线程 0.156%。
    #: 锁帧真正限制的是合成与定时器唤醒次数。见设计文档 §5-1。
    FRAME_INTERVAL_MS = int(round(1000 / 24))

    def __init__(self, config_obj, root=None):
        super().__init__(root if isinstance(root, QObject) else None)
        self.config = config_obj
        self.root = root
        self._window = None
        self._animator = CrosshairAnimator()
        self._visible = False

        self._state = CrosshairState(
            size=getattr(config_obj, "crosshair_size", 20),
            thickness=getattr(config_obj, "crosshair_thickness", 2),
            color=getattr(config_obj, "crosshair_color", "green"),
            style=getattr(config_obj, "crosshair_style", "crosshair"),
            animation=getattr(config_obj, "crosshair_animation", "none"),
            kill_effect=getattr(config_obj, "crosshair_kill_effect", "none"),
            custom_points=tuple(tuple(p) for p in (getattr(config_obj, "crosshair_custom_data", ()) or ())),
        )

        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._kill_signal.connect(self._handle_kill)

    # ------------------------------------------------------------ 兼容接口

    @property
    def is_visible(self) -> bool:
        return self._visible

    @property
    def overlay_win(self):
        """老接口：`gui_widget` 拿它判断「有没有窗口要清理」。"""
        return self._window

    # 老实现把这六项当**公开实例属性**摆着，而 `pages/magnifier_page.py:1568-1574`
    # 正是靠读它们把「进放大镜前的准心」整套存下来，退出时再还原。
    # 藏进 `_state` 就会让那段 getattr 全部落到默认值上——放大镜退出后
    # 准心被还原成别的样子，而且不报任何错。
    # 命名照抄老实现（注意是 `animation_style` 不是 `animation`），别顺手"改规范"。

    @property
    def size(self):
        return self._state.size

    @size.setter
    def size(self, value):
        self._state.size = value

    @property
    def thickness(self):
        return self._state.thickness

    @thickness.setter
    def thickness(self, value):
        self._state.thickness = value

    @property
    def color(self):
        return self._state.color

    @color.setter
    def color(self, value):
        self._state.color = value

    @property
    def style(self):
        return self._state.style

    @style.setter
    def style(self, value):
        self._state.style = value

    @property
    def animation_style(self):
        return self._state.animation

    @animation_style.setter
    def animation_style(self, value):
        self._state.animation = value

    @property
    def kill_effect(self):
        return self._state.kill_effect

    @kill_effect.setter
    def kill_effect(self, value):
        self._state.kill_effect = value

    def show_crosshair(self):
        if self._window is None:
            self._window = CrosshairOverlayWindow()
        self._window.recenter()
        self._window.show()
        self._window.raise_()
        self._window.apply_click_through()
        self._visible = True
        self._render_once()
        self._sync_timer()

    def hide_crosshair(self):
        self._visible = False
        self._timer.stop()
        if self._window is not None:
            self._window.hide()

    def destroy(self):
        self.hide_crosshair()
        self._animator.reset()
        if self._window is not None:
            self._window.close()
            self._window.deleteLater()
            self._window = None

    def update_settings(self, size, thickness, color, style, animation_style, kill_effect):
        self._state.size = size
        self._state.thickness = thickness
        self._state.color = color
        self._state.style = style
        self._state.animation = animation_style
        self._state.kill_effect = kill_effect
        self._state.custom_points = tuple(
            tuple(p) for p in (getattr(self.config, "crosshair_custom_data", ()) or ())
        )
        self._render_once()
        self._sync_timer()

    def register_kill_handler(self, gsi_handler_kills):
        if not gsi_handler_kills:
            return
        gsi_handler_kills.register_kill_callback(self.on_kill_event)
        logger.info("[CrosshairOverlay] 已注册到击杀处理器")

    def on_kill_event(self, is_headshot):
        """**在 GSI 线程上被调用**——所以这里除了 emit 什么都不做。"""
        if not self._visible:
            return
        self._kill_signal.emit(bool(is_headshot))

    # ------------------------------------------------------------ 内部

    def _handle_kill(self, is_headshot):  # noqa: ARG002 - 爆头与否暂不改观感，与老实现一致
        if not self._visible:
            return
        if self._animator.trigger_kill(self._state, self._now()):
            self._sync_timer()

    @staticmethod
    def _now() -> float:
        import time

        return time.monotonic()

    def _sync_timer(self):
        """静态准心不跑定时器；有动画或联动进行中才跑。"""
        now = self._now()
        want = self._visible and CrosshairAnimator.needs_timer(
            self._state, self._animator.kill_active(now))
        if want and not self._timer.isActive():
            self._timer.start()
        elif not want and self._timer.isActive():
            self._timer.stop()

    def _tick(self):
        self._render_once()
        if not self._animator.kill_active(self._now()):
            self._sync_timer()

    def _render_once(self):
        if self._window is None or not self._visible:
            return
        self._window.set_frame(self._animator.advance(self._state, self._now()))
