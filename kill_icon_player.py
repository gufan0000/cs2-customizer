# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标播放器（KI-1：pygame 子进程 → Qt 叠加层）。

对外接口与老实现**逐个方法对齐**，换渲染器时调用方一行都不用改：
`gui_widget`（建实例、退出清理）、`main_widget`（挂给击杀处理器）、
`pages/kill_icon_page`（风格/位置/缩放/FPS/测试）、`gsi_handler_kills`
（`play_images` / `stop_images`）。

渲染与几何在 [kill_icon_overlay.py]，本文件只管三件事：
生命周期、线程边界、素材缓存。

线程模型（与准心 R8b 同款，别改成 DirectConnection）
--------------------------------------------------
击杀事件从 **GSI 服务器线程**来，而 QWidget 只能在主线程碰。所以
`play_images` 只负责 `emit`，真正动窗口的 `_handle_play` 挂在信号上，
由 Qt 排队投递回主线程。老实现靠"跨进程队列"天然回避了这个问题，
搬进主进程后它就变成必须显式处理的事了。

素材装载则相反——**必须离开主线程**。一套风格 5 个等级、几十帧
350x250 的解码加预缩放，实测能占主线程几百毫秒；老实现把预缩放拖到
击杀那一瞬间才做（缓存未命中就当场缩放整套帧），代价是"换完风格第一次
击杀掉帧"。这里改成装载期在后台线程做完：QImage 不像 QPixmap 那样绑
GUI 线程，可以在工作线程里解码、缩放，再把结果整个交回主线程。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import NamedTuple

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QWidget

from config import config
from core.utils.logger import get_logger
from kill_icon_overlay import (
    FADE_IN_SECONDS,
    FADE_OUT_SECONDS,
    TICK_HZ,
    clamp_fps,
    clamp_hold,
    compute_overlay_geometry,
    compute_scaled_size,
    load_level_animation,
    paint_frame,
    playback_state,
    scale_animation,
)
from resource_manager import ResourceManager

#: RN-429 覆盖层的运行前提。击杀图标画在游戏画面上，同上。⚠ 配置它的 `kill_icon_page` 与本模块之间**没有任何 import 关系**（页面只配置，播放由 GSI 事件链驱动）—— 所以那一页的表态只能靠它自己写，任何 import 分母都够不着。
DRAWN_OVER_THE_GAME = True

logger = get_logger("KillIconPlayer")

#: 支持的击杀等级。>5 杀由 `gsi_handler_kills` 那边钳到 5，这里不重复判断。
KILL_LEVELS = tuple(range(1, 6))

#: 爆头变体的资源后缀：`<风格>/3hs.png` + `3hs.json`。
#: 没有这个文件就退回普通图标——变体是**可选覆写**，不是新的必需资源。
HEADSHOT_VARIANT = "hs"


class LevelInfo(NamedTuple):
    """一个击杀等级的元数据。**故意不含像素**——见 `KillIconPlayer._catalog`。"""

    frame_count: int
    fps: int
    frame_width: int
    frame_height: int
    hold_seconds: float = 0.0


class KillIconOverlayWindow(QWidget):
    """透明、置顶、点击穿透、不抢焦点的图标画布。

    ⚠ 这套标志 + 扩展样式是一整体，别按直觉删减——组合与
    `crosshair_overlay.CrosshairOverlayWindow` 完全一致，那套已经在生产里
    画在游戏上了。少 `WA_ShowWithoutActivating` 会抢焦点把游戏切出去，
    少 `WS_EX_TRANSPARENT` 会吃掉图标那块区域的鼠标点击。
    """

    def __init__(self):
        super().__init__(None)
        self._win32_style_applied = False
        self._frame = None
        self._opacity = 1.0
        self._dpr = 1.0

        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        for name in ("WindowTransparentForInput", "WindowDoesNotAcceptFocus"):
            flag = getattr(Qt, name, None)
            if flag is None and hasattr(Qt, "WindowType"):
                flag = getattr(Qt.WindowType, name, None)
            if flag is not None:
                flags |= flag
        self.setWindowFlags(flags)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    # ------------------------------------------------------------------ 几何

    def device_pixel_ratio(self, screen=None) -> float:
        screen = screen or self.screen() or QApplication.primaryScreen()
        try:
            return float(screen.devicePixelRatio()) if screen else 1.0
        except Exception:
            return 1.0

    def target_screen(self):
        """图标该画在哪块屏——游戏在哪块就在哪块。

        老实现用 `GetSystemMetrics(0/1)` 取主屏尺寸，副屏打游戏时图标弹在
        主屏上。这里复用准心那套按 GDI 设备名匹配的实现，**不要另写一个**。
        """
        from crosshair_overlay import game_screen_device_name, pick_screen

        return pick_screen(
            QApplication.screens(),
            QApplication.primaryScreen(),
            game_screen_device_name(),
        )

    def place(self, physical_width, physical_height, offset_x=0, offset_y=0) -> bool:
        screen = self.target_screen()
        if screen is None:
            return False
        geo = screen.geometry()
        # dpr 取**目标屏**的：跨屏移动那一刻窗口还在旧屏上，拿旧屏的缩放
        # 算新屏的尺寸会差一个缩放比（准心那边踩过的同一个坑）。
        self._dpr = self.device_pixel_ratio(screen)
        target = compute_overlay_geometry(
            (geo.x(), geo.y(), geo.width(), geo.height()),
            self._dpr,
            physical_width,
            physical_height,
            offset_x,
            offset_y,
        )
        current = self.geometry()
        if (current.x(), current.y(), current.width(), current.height()) != target:
            self.setGeometry(*target)
        return True

    # ------------------------------------------------------------------ 绘制

    def set_frame(self, frame, opacity=1.0):
        self._frame = frame
        self._opacity = opacity
        self.update()

    def paintEvent(self, event):
        if self._frame is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        paint_frame(painter, self._frame, dpr=self._dpr, opacity=self._opacity)
        painter.end()

    # ------------------------------------------------- Win32 点击穿透（补刀）

    def apply_click_through(self) -> bool:
        """Qt 标志已经声明了穿透，这里再从 Win32 层补一遍。

        原因与准心/特效层一致：`WindowTransparentForInput` 在部分 Qt/驱动
        组合下不落到扩展样式上，漏一次就是用户点不动图标底下的东西。
        """
        if self._win32_style_applied or not sys.platform.startswith("win"):
            return False
        try:
            import ctypes

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


class KillIconPlayer(QObject):
    """击杀图标的对外门面。"""

    #: (击杀等级, 变体, 指定帧率或 -1)
    _play_signal = Signal(int, str, int)
    _stop_signal = Signal()
    #: (风格名, 装载令牌, 素材字典)
    _assets_signal = Signal(str, int, object)

    #: (风格名) —— 后台装载完成。**设置页必须连这个**。
    #:
    #: `load_style` 是同步返回、异步装载的：它立刻把 `current_style` 改掉，
    #: 而缓存要等后台线程跑完才换。中间那段窗口期里，页面问"这个风格有多少帧"
    #: 拿到的会是**上一个风格**的数——实测表现是刚导入一个包，清单板上五个格子
    #: 显示的是老风格的帧数和时长，而且不会自己好，要等下一次刷新才对。
    assets_ready = Signal(str)

    def __init__(self, parent_window=None):
        super().__init__(parent_window if isinstance(parent_window, QObject) else None)
        self.parent_window = parent_window
        self.current_style = None
        #: 老接口：`{等级: {'fps': int}}`，设置页和测试都读它
        self.animations = {}

        self._window = None
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, int(round(1000 / TICK_HZ))))
        self._timer.timeout.connect(self._tick)

        self._playing = False
        self._start_time = 0.0
        self._current_frames = ()
        self._current_fps = 30
        self._current_hold = 0.0
        self._last_paint_key = None

        #: {(等级, 变体): LevelInfo}，**只有元数据没有像素**
        #:
        #: 这里原本存的是整套原始帧（KillIconAnimation），理由是"改缩放时不用
        #: 重读盘"。实测（默认风格 519 帧 350x250）：
        #:
        #:     缩放 100%   只留缩放 +174MB   两份都留 +174MB
        #:     缩放 150%   只留缩放 +475MB   两份都留 +564MB
        #:
        #: 100% 那行不是笔误——`QImage::scaled` 在目标尺寸与源相同时返回的是
        #: **同一个隐式共享对象**，所以默认缩放下那份"副本"根本不占内存。
        #: 真正要钱的是缩放≠100% 的情况（多 89MB）。为一个交互动作（改缩放，
        #: 本来就在后台线程做、还有系统页缓存兜着）常驻这份，不划算。
        #:
        #: ⚠ 别把这条当成"内存优化"记住。**大头是 `_scaled` 自己**：默认风格
        #: 5 个等级共 519 帧（等级 5 就有 201 帧），100% 下 174MB、150% 下 475MB。
        #: 那是素材本身的体量，pygame 版同样要付（只是付在子进程里，主进程的
        #: 内存计数看不见）。真要压它得动"按需装载 + 淘汰"的结构，不在这一层。
        self._catalog = {}
        #: {(等级, 变体): tuple[QImage]}，已按当前缩放预缩放好——**唯一的像素副本**
        self._scaled = {}
        #: `_catalog` / `_scaled` 里装的**到底是哪个风格**的东西。
        #: 不能拿 `current_style` 代替：那个在 `load_style` 里同步就改了，
        #: 而缓存要等后台线程跑完。两者不分开，切风格之后的一小段时间里
        #: 所有"这个风格有多少帧"的问题都会拿到上一个风格的答案。
        self._catalog_style = None
        self._assets_lock = threading.Lock()
        self._load_token = 0
        self._loading_thread = None

        self._play_signal.connect(self._handle_play)
        self._stop_signal.connect(self._handle_stop)
        self._assets_signal.connect(self._handle_assets_ready)

    # ============================================================ 素材装载

    def _target_size_for(self, animation):
        return compute_scaled_size(
            animation.frame_width,
            animation.frame_height,
            getattr(config, "kill_icon_base_width", 350),
            getattr(config, "kill_icon_scale", 1.0),
        )

    def _load_worker(self, style_name, token):
        """后台线程：解码 + 预缩放整套风格。

        原始帧**用完即弃**，只把预缩放结果和元数据交回主线程——原始帧的唯一
        用途就是被缩放一次，留着它等于常驻一份完整副本（见 `_catalog` 的说明）。
        """
        try:
            assets = {}
            for kills in KILL_LEVELS:
                for variant in ("", HEADSHOT_VARIANT):
                    animation = load_level_animation(style_name, kills, variant)
                    if animation is None:
                        continue
                    width, height = self._target_size_for(animation)
                    assets[(kills, variant)] = (
                        LevelInfo(animation.frame_count, animation.fps,
                                  animation.frame_width, animation.frame_height,
                                  animation.hold_seconds),
                        scale_animation(animation, width, height),
                    )
            self._assets_signal.emit(style_name, token, assets)
        except Exception as exc:
            logger.error(f"装载击杀图标素材失败（风格 {style_name}）: {exc}")

    def _start_load(self, style_name):
        with self._assets_lock:
            self._load_token += 1
            token = self._load_token
        thread = threading.Thread(
            target=self._load_worker,
            args=(style_name, token),
            daemon=True,
            name="KillIconLoad",
        )
        self._loading_thread = thread
        thread.start()

    def _handle_assets_ready(self, style_name, token, assets):
        """主线程：接收后台装载结果。"""
        with self._assets_lock:
            if token != self._load_token:
                return  # 已被更新的一次装载取代
        self.current_style = style_name
        self._catalog = {key: value[0] for key, value in assets.items()}
        self._scaled = {key: value[1] for key, value in assets.items()}
        self._catalog_style = style_name
        self.animations = {
            kills: {"fps": info.fps}
            for (kills, variant), info in self._catalog.items()
            if not variant
        }
        logger.info(
            f"击杀图标素材就绪: 风格={style_name}, 等级={sorted(self.animations)}"
        )
        # 设置页靠它把清单板刷新成新风格的数据——不发这一枪，页面会一直显示
        # 上一个风格的帧数与时长，而且不会自己好。
        self.assets_ready.emit(style_name)

    def _frames_for(self, kills, variant):
        """取某等级的帧序列；变体缺失时退回普通图标。

        后台还没装载完（刚换风格就击杀）时**当场从盘上读一次**：慢一帧总好过
        不显示。这条路只在装载竞态里走得到，命中率极低，所以不值得为它常驻
        一份原始帧——那正是这次省掉 80MB 的地方。
        """
        for key in ((kills, variant), (kills, "")):
            frames = self._scaled.get(key)
            if frames:
                info = self._catalog[key]
                return frames, info.fps, info.hold_seconds

        for key in ((kills, variant), (kills, "")):
            animation = load_level_animation(self.current_style, kills, key[1])
            if animation is None:
                continue
            width, height = self._target_size_for(animation)
            frames = scale_animation(animation, width, height)
            self._scaled[key] = frames
            self._catalog[key] = LevelInfo(animation.frame_count, animation.fps,
                                           animation.frame_width, animation.frame_height,
                                           animation.hold_seconds)
            return frames, animation.fps, animation.hold_seconds
        return (), clamp_fps(None), 0.0

    # ============================================================ 播放

    def _handle_play(self, kills, variant, custom_fps):
        if not getattr(config, "kill_icon_enabled", False):
            return
        frames, fps, hold = self._frames_for(int(kills), variant or "")
        if not frames:
            logger.debug(f"击杀图标没有可播的素材: 等级={kills}, 变体={variant!r}")
            return

        if custom_fps and int(custom_fps) > 0:
            fps = clamp_fps(custom_fps)

        if self._window is None:
            self._window = KillIconOverlayWindow()

        first = frames[0]
        placed = self._window.place(
            first.width(),
            first.height(),
            getattr(config, "kill_icon_offset_x", 0),
            getattr(config, "kill_icon_offset_y", 0),
        )
        if not placed:
            logger.warning("找不到可用屏幕，击杀图标本次不显示")
            return

        # 新击杀直接接管，不排队。参考同类工具的一致做法：连杀时排队会让
        # 画面一直落后于战斗，而玩家要看的是"刚刚这一杀"。
        self._current_frames = frames
        self._current_fps = fps
        self._current_hold = hold
        self._start_time = time.monotonic()
        self._last_paint_key = None
        self._playing = True

        self._window.set_frame(frames[0], 0.0 if self._fade_enabled() else 1.0)
        self._window.show()
        self._window.raise_()
        self._window.apply_click_through()
        self._timer.start()
        self._tick()

    def _fade_enabled(self) -> bool:
        return bool(getattr(config, "kill_icon_fade_enabled", True))

    def _tick(self):
        if not self._playing:
            return
        fade_in = FADE_IN_SECONDS if self._fade_enabled() else 0.0
        fade_out = FADE_OUT_SECONDS if self._fade_enabled() else 0.0
        state = playback_state(
            time.monotonic() - self._start_time,
            self._current_fps,
            len(self._current_frames),
            fade_in,
            fade_out,
            getattr(self, "_current_hold", 0.0),
        )
        if state is None:
            self._handle_stop()
            return

        index, opacity = state
        # 帧号和不透明度都没变就别重绘：透明置顶窗每次重绘都要走一遍合成。
        key = (index, round(opacity * 100))
        if key == self._last_paint_key:
            return
        self._last_paint_key = key
        if self._window is not None:
            self._window.set_frame(self._current_frames[index], opacity)

    def _handle_stop(self):
        self._playing = False
        self._timer.stop()
        self._last_paint_key = None
        if self._window is not None:
            self._window.hide()
            self._window.set_frame(None, 1.0)

    @property
    def is_playing(self) -> bool:
        return self._playing

    # ============================================================ 对外接口

    def enable_kill_icons(self):
        """开启：把当前风格的素材准备好（窗口按需在播放时才建）。"""
        style = getattr(config, "kill_icon_style", "")
        if style and style != self.current_style:
            self.load_style(style)

    def disable_kill_icons(self):
        self._stop_signal.emit()

    def load_style(self, style_name):
        """切风格。返回值表示"这个风格有没有可用素材"（同步判断，不等装载）。"""
        style_found = any(
            ResourceManager.has_kill_icon_level_assets(style_name, kills)
            for kills in KILL_LEVELS
        )
        self.current_style = style_name
        self._start_load(style_name)
        return style_found

    def play_icon(self, kills, custom_fps=None, is_headshot=False):
        self._play_signal.emit(
            int(kills),
            HEADSHOT_VARIANT if is_headshot else "",
            int(custom_fps) if custom_fps else -1,
        )

    def play_images(self, style, kills, is_headshot=False):
        """GSI 击杀回调的入口（`style` 参数是老签名的遗留位，忽略）。"""
        if not getattr(config, "kill_icon_enabled", False):
            return
        configured = getattr(config, "kill_icon_style", "")
        if configured and configured != self.current_style:
            if not self.load_style(configured):
                return
        if is_headshot and not getattr(config, "kill_icon_headshot_enabled", True):
            is_headshot = False
        self.play_icon(kills, None, is_headshot)

    def stop(self):
        self._stop_signal.emit()

    def stop_images(self):
        self.stop()

    def clear_preloaded_images(self):
        """老接口，保留空实现：缓存现在跟着风格与缩放走，不需要外部清。"""

    def update_position_offset(self, offset_x, offset_y):
        """位置偏移改了。下一次播放时生效（几何在 `place` 里现算）。"""
        if self._playing and self._window is not None and self._current_frames:
            first = self._current_frames[0]
            self._window.place(first.width(), first.height(), offset_x, offset_y)

    def update_scale(self, scale):
        """缩放改了：拿内存里的原始帧重新预缩放，不重读盘。"""
        if self.current_style:
            self._start_load(self.current_style)

    def preview_position_and_scale(self, kills=1, duration=3):
        """按当前设置真弹一次图标（`duration` 是老签名的遗留位）。

        老实现要靠 `threading.Timer` 到点去 stop——因为它那边"播完"这件事
        没人管。现在动画自己会走完时间轴并隐藏，不需要外部计时器。
        """
        was_enabled = getattr(config, "kill_icon_enabled", False)
        if not was_enabled:
            config.kill_icon_enabled = True
        try:
            self.play_icon(kills)
        finally:
            if not was_enabled:
                # 只放行这一次预览；别把用户的总开关改掉
                QTimer.singleShot(50, lambda: setattr(config, "kill_icon_enabled", was_enabled))

    def cleanup(self):
        self._handle_stop()
        if self._window is not None:
            self._window.close()
            self._window.deleteLater()
            self._window = None
        self._catalog = {}
        self._scaled = {}

    # ============================================================ 素材元数据

    def _read_style_metadata(self, style_name, kills):
        metadata_path = ResourceManager.get_kill_icon_metadata_path(style_name, kills)
        if not os.path.exists(metadata_path):
            return {}
        try:
            with open(metadata_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get_style_fps(self, style_name, kills):
        if style_name == self._catalog_style and kills in self.animations:
            return self.animations[kills].get("fps", 30)
        return clamp_fps(self._read_style_metadata(style_name, kills).get("fps", 30))

    def get_style_hold(self, style_name, kills):
        """这个等级的定格时长（秒）。老素材没有这个字段，返回 0。"""
        info = self._catalog.get((kills, "")) if style_name == self._catalog_style else None
        if info is not None:
            return clamp_hold(info.hold_seconds)
        return clamp_hold(self._read_style_metadata(style_name, kills).get("hold_seconds", 0.0))

    def get_style_frame_count(self, style_name, kills):
        """这个等级有多少帧——设置页的"展示时长"控件靠它做时长↔帧率换算。"""
        info = self._catalog.get((kills, "")) if style_name == self._catalog_style else None
        if info is not None:
            return info.frame_count

        frames = int(self._read_style_metadata(style_name, kills).get("frames", 0) or 0)
        if frames > 0:
            return frames

        legacy_dir = ResourceManager.get_kill_icon_legacy_frames_dir(style_name, kills)
        if legacy_dir and os.path.isdir(legacy_dir):
            try:
                return sum(
                    1
                    for name in os.listdir(legacy_dir)
                    if name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp"))
                )
            except OSError:
                return 0
        return 0

    def update_fps_for_style(self, style_name, kills, new_fps):
        return self._update_timing(style_name, kills, fps=clamp_fps(new_fps))

    def update_hold_for_style(self, style_name, kills, new_hold):
        """只改定格时长。

        单帧素材走的是这条：对一张静态图来说"播放速度"没有意义，
        用户拖的那个滑条量的直接就是"停多久"。
        """
        return self._update_timing(style_name, kills, hold=clamp_hold(new_hold))

    def _update_timing(self, style_name, kills, fps=None, hold=None):
        metadata_path = ResourceManager.get_kill_icon_metadata_path(style_name, kills)
        style_dir = ResourceManager.get_kill_icon_style_dir(style_name)
        try:
            if not ResourceManager.has_kill_icon_level_assets(style_name, kills):
                return False
            os.makedirs(style_dir, exist_ok=True)
            data = self._read_style_metadata(style_name, kills)
            if fps is not None:
                data["fps"] = clamp_fps(fps)
            if hold is not None:
                data["hold_seconds"] = clamp_hold(hold)
            with open(metadata_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
            if fps is not None and style_name == self._catalog_style and kills in self.animations:
                self.animations[kills]["fps"] = clamp_fps(fps)
            key = (kills, "")
            info = self._catalog.get(key)
            if info is not None:
                # 节奏变了但帧没变：只换元数据，不重新解码也不重新缩放
                if fps is not None:
                    info = info._replace(fps=clamp_fps(fps))
                if hold is not None:
                    info = info._replace(hold_seconds=clamp_hold(hold))
                self._catalog[key] = info
            return True
        except OSError as exc:
            logger.error(f"更新击杀图标播放设置失败: {exc}")
            return False
