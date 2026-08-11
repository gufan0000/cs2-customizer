# -*- coding: utf-8 -*-
"""游戏内 OSD 提示(R2-3,2026-06-12)。

无边框/置顶/鼠标穿透的小药丸窗,角落滑入 1.6s 自动淡出。
- 纯外部窗口,零注入,VAC 安全性与现有闪光/准心 overlay 同级;
- CS2 需无边框窗口模式(全屏独占看不到,与现有 overlay 同限制);
- notify_osd() 线程安全:跨线程经 Qt queued signal 转主线程。

用途:切地图预设、音板发送等"用户在游戏里需要知道"的瞬时反馈。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from config import config

_CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")
_MARGIN = 28
_SHOW_MS = 1600


class _OsdWindow(QWidget):
    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("")
        self.label.setFont(QFont("Microsoft YaHei", 12, QFont.DemiBold))
        self.label.setStyleSheet(
            "QLabel { color: #FFFFFF; background-color: rgba(20,22,28,0.82);"
            " border: 1px solid rgba(255,255,255,0.18); border-radius: 14px;"
            " padding: 8px 18px; }"
        )
        lay.addWidget(self.label)

    def show_text(self, text: str):
        self.label.setText(text)
        self.adjustSize()
        corner = str(getattr(config, "osd_corner", "bottom_right"))
        if corner not in _CORNERS:
            corner = "bottom_right"
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.left() + _MARGIN if "left" in corner else geo.right() - self.width() - _MARGIN
        y = geo.top() + _MARGIN if "top" in corner else geo.bottom() - self.height() - _MARGIN
        self.move(x, y)
        self.setWindowOpacity(0.0)
        self.show()
        # 简洁淡入(三步,避免引入动画依赖)
        QTimer.singleShot(0, lambda: self.setWindowOpacity(0.5))
        QTimer.singleShot(60, lambda: self.setWindowOpacity(1.0))


class OsdNotifier(QObject):
    """单例;notify() 任意线程可调,实际显示在 GUI 线程。"""

    _message = Signal(str)
    _instance = None

    def __init__(self):
        super().__init__()
        self._window = None
        self._hide_timer = None
        self._message.connect(self._show_on_gui_thread)

    @classmethod
    def instance(cls) -> "OsdNotifier":
        if cls._instance is None:
            cls._instance = OsdNotifier()
        return cls._instance

    def notify(self, text: str):
        if not text:
            return
        if not bool(getattr(config, "osd_enabled", True)):
            return
        self._message.emit(str(text)[:60])

    def _show_on_gui_thread(self, text: str):
        try:
            if self._window is None:
                self._window = _OsdWindow()
                self._hide_timer = QTimer(self)
                self._hide_timer.setSingleShot(True)
                self._hide_timer.timeout.connect(self._window.hide)
            self._window.show_text(text)
            self._hide_timer.start(_SHOW_MS)
        except Exception:
            pass  # OSD 永不影响主流程


def notify_osd(text: str):
    """全局便捷入口(线程安全)。"""
    try:
        OsdNotifier.instance().notify(text)
    except Exception:
        pass
