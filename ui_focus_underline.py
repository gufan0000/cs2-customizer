# SPDX-License-Identifier: GPL-3.0-or-later
"""
输入框焦点下划线动效
获得焦点时从中心向两侧展开 accent 色线条
"""

from PySide6.QtCore import (
    Qt, Property, QPropertyAnimation, QEasingCurve, QEvent, QRectF
)
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget
from theme_manager import get_theme_manager


class FocusUnderline(QWidget):
    """覆盖在输入框底部的动画下划线"""

    LINE_HEIGHT = 2

    def __init__(self, target, parent=None):
        super().__init__(parent or target)
        self._target = target
        self._width_ratio = 0.0
        self._tm = get_theme_manager()

        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)

        # 展开/收缩动画
        self._anim = QPropertyAnimation(self, b"width_ratio")
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        # 安装事件过滤器
        target.installEventFilter(self)
        self._reposition()

    def _reposition(self):
        """定位到目标控件底部"""
        t = self._target
        self.setGeometry(0, t.height() - self.LINE_HEIGHT, t.width(), self.LINE_HEIGHT)

    # ========== Property ==========

    def _get_ratio(self):
        return self._width_ratio

    def _set_ratio(self, val):
        self._width_ratio = val
        self.update()

    width_ratio = Property(float, _get_ratio, _set_ratio)

    # ========== 事件 ==========

    def eventFilter(self, obj, event):
        if obj is self._target:
            if event.type() == QEvent.FocusIn:
                self._animate_to(1.0, 200)
            elif event.type() == QEvent.FocusOut:
                self._animate_to(0.0, 150)
            elif event.type() == QEvent.Resize:
                self._reposition()
        return False

    def _animate_to(self, target, duration):
        self._anim.stop()
        self._anim.setDuration(duration)
        self._anim.setStartValue(self._width_ratio)
        self._anim.setEndValue(target)
        self._anim.start()

    def paintEvent(self, event):
        if self._width_ratio <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        colors = self._tm.current_theme.colors
        color = QColor(colors.accent_primary)

        w = self.width()
        line_w = w * self._width_ratio
        x = (w - line_w) / 2
        p.fillRect(QRectF(x, 0, line_w, self.LINE_HEIGHT), color)


def install_focus_underline(widget):
    """为输入框安装焦点下划线效果"""
    if hasattr(widget, '_focus_underline_installed'):
        return
    widget._focus_underline_installed = True
    FocusUnderline(widget, widget)
