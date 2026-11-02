# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""有事才占地方的横条（批 145）。

页面标题下面那条状态、页面底下那条按钮，常态下经常什么都不用说。
一个空框也要占一条缝（布局的 spacing 只跳过隐藏的控件），所以里面的东西全藏起来时，
它自己也藏起来；里面有东西露面，它跟着露面。
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QFrame, QWidget


class CollapsingFrame(QFrame):
    """直接子控件全部隐藏时，自己也隐藏。

    ⚠ 第一次显示之前不判断：页面还在搭，后面的子控件还没加进来，
    这时判「空」会把自己藏起来，而之后没有任何事件能把它叫回来。
    """

    #: 放在类上：构造途中 Qt 就可能来问 eventFilter，那时实例属性还没赋值（批 152 开源 CI 红）。
    _collapse_armed = False

    def childEvent(self, event):
        super().childEvent(event)
        if event.added() and event.child().isWidgetType():
            event.child().installEventFilter(self)

    def eventFilter(self, watched, event):
        if self._collapse_armed and event.type() in (QEvent.ShowToParent, QEvent.HideToParent):
            self._sync_collapsed()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._collapse_armed = True
        self._sync_collapsed()

    def _sync_collapsed(self) -> None:
        has_content = any(
            not child.isHidden()
            for child in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly))
        if has_content == self.isHidden():
            self.setVisible(has_content)


class StatusStrip(CollapsingFrame):
    """页面标题下面那条状态：只放「现在有问题」的话，没问题就不占地方。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusStrip")
