# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""侧栏一项，右边带一个状态小点（批 148）：这个功能开着（绿）、开着但有事要处理（黄）。

点是画上去的，不另建控件。状态变了才重绘，没有定时器。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QPushButton

DOT_ON = "on"
DOT_WARN = "warn"
DOT_NONE = ""

_DOT_RADIUS = 3.0
_DOT_RIGHT = 12
_DOT_TOKEN = {DOT_ON: "success", DOT_WARN: "warning"}
_DOT_TIP = {DOT_ON: "开着", DOT_WARN: "开着，有配的风格失效了"}


class NavButton(QPushButton):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._status_dot = DOT_NONE

    def status_dot(self) -> str:
        return self._status_dot

    def set_status_dot(self, level: str) -> None:
        if level == self._status_dot:
            return
        self._status_dot = level
        self.setToolTip(_DOT_TIP.get(level, ""))
        self.setAccessibleDescription(_DOT_TIP.get(level, ""))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        token = _DOT_TOKEN.get(self._status_dot)
        if token is None:
            return
        from theme_manager import get_color

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(get_color(token)))
        painter.drawEllipse(QPointF(self.width() - _DOT_RIGHT, self.height() / 2), _DOT_RADIUS, _DOT_RADIUS)
