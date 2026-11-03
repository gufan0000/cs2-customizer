#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
页面过渡系统
设计原则：干净利落，不干扰用户

批 160：新页立即就位，旧页的一张快照盖在上面淡出（FADE_MS）。
只过渡正文区；不位移、不缩放，密集的表单不跟着晃。

注意：不使用 QGraphicsOpacityEffect，因为它会覆盖页面内卡片的
QGraphicsDropShadowEffect（Qt 每个 widget 只能有一个 GraphicsEffect）。
快照画在一层不吃鼠标的覆盖层上，真实页面不参与透明合成。
"""

import sys

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from core.utils.logger import get_logger

#: 淡出时长（毫秒）。比 Motion.fast 还短：切页是最频繁的动作，过渡只能是「顺」，不能是「等」
FADE_MS = 110
#: 时长上限：判据钉住，过渡永远不许比这更长
FADE_MS_MAX = 150


def system_animations_enabled() -> bool:
    """Windows「显示动画」关了就不做过渡（SPI_GETCLIENTAREAANIMATION）。读不到按开着算。"""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        value = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0):
            return bool(value.value)
    except Exception:  # noqa: BLE001
        pass
    return True


class _FadeOverlay(QWidget):
    """盖在正文区上的旧页快照，透明度由动画推着走。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.pixmap = None
        self.opacity = 1.0
        self.hide()

    def paintEvent(self, event):
        if self.pixmap is None:
            return
        painter = QPainter(self)
        painter.setOpacity(self.opacity)
        painter.drawPixmap(0, 0, self.pixmap)


class PageTransitionManager:
    """页面过渡管理器：旧页快照淡出；连续切换以最后一次为准"""

    def __init__(self, stacked_widget):
        self.stack = stacked_widget
        self.logger = get_logger("PageTransition")
        self.current_animation = None
        self.is_animating = False
        self._overlay = None
        self.logger.info("页面过渡管理器已初始化")

    def _can_animate(self) -> bool:
        """截图、测试、离屏审计里都不做：那里要的是切完就定格的那一帧。"""
        if not self.stack.isVisible():
            return False
        if QGuiApplication.platformName() in ("offscreen", "minimal"):
            return False
        if self.stack.window().testAttribute(Qt.WA_DontShowOnScreen):
            return False
        return system_animations_enabled()

    def switch_page(self, new_widget):
        if not new_widget:
            return
        old_widget = self.stack.currentWidget()
        if old_widget == new_widget:
            return
        self._stop()
        pixmap = None
        if old_widget is not None and self._can_animate():
            pixmap = old_widget.grab()
        self.stack.setCurrentWidget(new_widget)
        if pixmap is not None and not pixmap.isNull():
            self._fade_out(pixmap)

    def _fade_out(self, pixmap):
        if self._overlay is None:
            self._overlay = _FadeOverlay(self.stack)
        overlay = self._overlay
        overlay.pixmap = pixmap
        overlay.opacity = 1.0
        overlay.setGeometry(self.stack.rect())
        overlay.raise_()
        overlay.show()

        anim = QVariantAnimation(self.stack)
        anim.setDuration(FADE_MS)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self._on_value)
        anim.finished.connect(self._stop)
        self.current_animation = anim
        self.is_animating = True
        anim.start()

    def _on_value(self, value):
        if self._overlay is not None:
            self._overlay.opacity = float(value)
            self._overlay.update()

    def _stop(self):
        anim, self.current_animation = self.current_animation, None
        if anim is not None:
            anim.stop()
            anim.deleteLater()
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.pixmap = None
        self.is_animating = False

    def cleanup(self):
        self._stop()
        self.logger.info("页面过渡管理器已清理")


def create_page_transition(stacked_widget):
    return PageTransitionManager(stacked_widget)
