# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""FlowLayout —— 一行放不下就换行的横向布局（UP-017）。

为什么需要它：`QHBoxLayout` 的最小宽度是**所有子项最小宽度之和**。一排 chip
放进 QHBoxLayout，页面的 `minimumSizeHint` 就被顶到"chip 总宽"那么大；
外层滚动区如果又禁了横向滚动（高级设置页正是如此），窗口一窄，
右边的内容就**永久够不到**——没有滚动条，也没有任何提示。
高级设置页实测在 1200 宽下溢出 290px，23 个交互控件滚不到。

FlowLayout 的最小宽度只等于**最宽的那一个子项**，窄窗口下自动多占几行，
从根上消掉这类溢出。

实现要点（Qt 布局协议）：
- `hasHeightForWidth()` 返回 True + `heightForWidth()` 给出所需高度，
  垂直布局才知道该给我们留几行的空间；
- `minimumSize()` 取子项最小尺寸的**逐维最大值**，不是求和；
- `_do_layout(rect, test_only=True)` 只算高度不摆放，供 heightForWidth 复用。
"""
from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    """横向流式布局：放不下就换行。"""

    def __init__(self, parent=None, margin: int = 0,
                 h_spacing: int = 6, v_spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(QMargins(margin, margin, margin, margin))

    # ---------------------------------------------------------- QLayout 协议

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        """逐维取最大值，**不是求和** —— 这正是它能消掉溢出的原因。"""
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    # ------------------------------------------------------------------ 内部

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        """按行摆放子项，返回总高度。test_only=True 时只算不摆。"""
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(),
                                  -margins.right(), -margins.bottom())
        x, y = effective.x(), effective.y()
        line_height = 0

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() and line_height > 0:
                # 这一行放不下了，换行
                x = effective.x()
                y = y + line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()


def make_flow_container(widget_cls=None, **kwargs):
    """建一个装着 FlowLayout 的容器 QWidget，返回 (容器, 布局)。

    容器的垂直策略设为 Minimum：让它按 heightForWidth 撑到需要的行数，
    而不是被父布局拉伸或压扁。
    """
    from PySide6.QtWidgets import QWidget

    container = QWidget() if widget_cls is None else widget_cls()
    layout = FlowLayout(container, **kwargs)
    container.setLayout(layout)
    container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return container, layout
