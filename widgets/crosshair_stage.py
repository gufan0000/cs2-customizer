# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""准心页的预览舞台、分段单选和色块（批 146）。

舞台画一条灰盒走廊：准心清不清楚，要看它压在亮处、暗处和烟里的样子，压在纯色底上看不出来。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QPixmap, QPolygonF, QRadialGradient,
)
from PySide6.QtWidgets import QFrame, QRadioButton, QSizePolicy

SCENE_BRIGHT = "bright"
SCENE_DARK = "dark"
SCENE_SMOKE = "smoke"
#: 顺序就是切换按钮从左到右的顺序
SCENE_LABELS = {SCENE_BRIGHT: "亮", SCENE_DARK: "暗", SCENE_SMOKE: "烟雾"}

_BRIGHT_COLORS = {
    "ceil": "#d3d6db", "back": "#c2c6cc", "left": "#b0b4bb", "right": "#9ca1a9",
    "floor": "#878c94", "door": "#5b6068", "crate_front": "#8a7d68",
    "crate_side": "#75695a", "crate_top": "#9a8e79", "figure": "#3a3f47",
}
_DARK_COLORS = {
    "ceil": "#22252b", "back": "#1c1f24", "left": "#17191e", "right": "#131519",
    "floor": "#0e1013", "door": "#08090b", "crate_front": "#25221d",
    "crate_side": "#1e1c18", "crate_top": "#2b2822", "figure": "#050608",
}
_SCENE_COLORS = {SCENE_BRIGHT: _BRIGHT_COLORS, SCENE_DARK: _DARK_COLORS, SCENE_SMOKE: _BRIGHT_COLORS}

#: 场景按这个尺寸画，等比铺满舞台。人影的头正好在中心，准心压在要瞄的地方。
_SCENE_WIDTH = 800
_SCENE_HEIGHT = 560
_POLYGONS = (
    ("ceil", ((0, 0), (800, 0), (500, 210), (300, 210))),
    ("floor", ((0, 560), (800, 560), (500, 350), (300, 350))),
    ("left", ((0, 0), (300, 210), (300, 350), (0, 560))),
    ("right", ((800, 0), (500, 210), (500, 350), (800, 560))),
    ("back", ((300, 210), (500, 210), (500, 350), (300, 350))),
    ("door", ((362, 240), (438, 240), (438, 350), (362, 350))),
    ("crate_front", ((96, 400), (226, 400), (226, 520), (96, 520))),
    ("crate_top", ((96, 400), (226, 400), (258, 376), (128, 376))),
    ("crate_side", ((226, 400), (258, 376), (258, 486), (226, 520))),
    ("crate_front", ((580, 372), (704, 372), (704, 490), (580, 490))),
    ("crate_top", ((580, 372), (704, 372), (676, 352), (552, 352))),
    ("crate_side", ((580, 372), (552, 352), (552, 462), (580, 490))),
)
_SMOKE_PUFFS = (
    (400, 300, 230, "#b4b8be"), (290, 350, 190, "#a8acb3"),
    (520, 250, 200, "#bdc1c6"), (420, 170, 170, "#adb1b7"),
)
_CORNER_RADIUS = 8


def paint_scene(painter: QPainter, width: float, height: float, scene: str) -> None:
    colors = _SCENE_COLORS.get(scene, _BRIGHT_COLORS)
    scale = max(width / _SCENE_WIDTH, height / _SCENE_HEIGHT)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate((width - _SCENE_WIDTH * scale) / 2, (height - _SCENE_HEIGHT * scale) / 2)
    painter.scale(scale, scale)
    painter.setPen(Qt.NoPen)
    for key, points in _POLYGONS:
        painter.setBrush(QColor(colors[key]))
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    painter.setBrush(QColor(colors["figure"]))
    painter.drawEllipse(QPointF(400, 274), 8, 8)
    painter.drawRoundedRect(QRectF(388, 284, 24, 66), 6, 6)
    if scene == SCENE_SMOKE:
        for x, y, radius, color in _SMOKE_PUFFS:
            solid = QColor(color)
            clear = QColor(color)
            clear.setAlpha(0)
            gradient = QRadialGradient(QPointF(x, y), radius)
            gradient.setColorAt(0.0, solid)
            gradient.setColorAt(0.6, solid)
            gradient.setColorAt(1.0, clear)
            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(x, y), radius, radius)
    painter.restore()


class CrosshairStage(QFrame):
    """准心预览的底。准心本身是摆在上面的 `QLabel`，这里只管场景。

    ⚠ 场景画一次存成图：拖滑块每一下都要重画准心，走廊不用跟着重画。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("crosshairPreviewFrame")
        self.setMinimumSize(240, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 默认暗：一大块亮灰压在深色界面里太抢，想看亮处点一下就有
        self._scene = SCENE_DARK
        self._cache = QPixmap()

    def scene(self) -> str:
        return self._scene

    def set_scene(self, scene: str) -> None:
        if scene == self._scene:
            return
        self._scene = scene
        self._cache = QPixmap()
        self.update()

    def _scene_pixmap(self) -> QPixmap:
        ratio = self.devicePixelRatioF() or 1.0
        wanted = self.size() * ratio
        if self._cache.isNull() or self._cache.size() != wanted:
            self._cache = QPixmap(wanted)
            self._cache.fill(Qt.transparent)
            painter = QPainter(self._cache)
            paint_scene(painter, wanted.width(), wanted.height(), self._scene)
            painter.end()
            self._cache.setDevicePixelRatio(ratio)
        return self._cache

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), _CORNER_RADIUS, _CORNER_RADIUS)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, self._scene_pixmap())
        painter.end()
        super().paintEvent(event)   # 样式表的描边和悬停态在场景上面


class SegmentRadio(QRadioButton):
    """长得像分段按钮的单选，语义和方向键行为还是单选。样式在 `theme_manager`。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("segmentRadio")


class ColorSwatch(QRadioButton):
    """一个色块。颜色是游戏里真正画出来的那个，名字进 tooltip 和无障碍名。"""

    SIZE = 28

    def __init__(self, rgb: tuple, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("colorSwatch")
        self._color = QColor(*rgb)
        self.setAccessibleName(name)
        self.setToolTip(name)
        self.setFixedSize(self.SIZE, self.SIZE)

    def hitButton(self, pos):
        # 没有文字：极简主题（没有样式表）下默认的点击区只有一个小圈
        return self.rect().contains(pos)

    def paintEvent(self, event):
        super().paintEvent(event)   # 选中和焦点的那一圈
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(4, 4, -4, -4), 3, 3)
        painter.end()
