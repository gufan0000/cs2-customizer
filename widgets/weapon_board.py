# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""武器板：左边分类名，右边武器格，一张网格里上下对齐（批 146）。

39 把枪在 1280×800 下一屏看完，分类页签就不需要了。
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QScrollArea, QSizePolicy, QStyle

from ui_style_applier import keep_single_line
from widgets.master_switch_effect import PARAMETER_AREA_PROPERTY

#: 下拉和试听两段的下限。分类名和枪名那两段按字现算，字号变了跟着变。
CELL_TAIL_MIN_WIDTH = 128
NAME_PADDING = 22
CELL_GAP = 4
GROUP_GAP = 4
LABEL_GAP = 8


class WeaponBoard(QFrame):
    def __init__(self, parent=None, *, max_columns: int = 0):
        """`max_columns`：格子少的页面限一下列数，别把六格拉成窄窄一排（0 = 不限）。"""
        super().__init__(parent)
        self._max_columns = int(max_columns)
        self.setObjectName("weaponBoard")
        #: `master_switch_effect` 按这个认参数区：总开关关着时这一片要跟着降权
        self.setProperty(PARAMETER_AREA_PROPERTY, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._groups: list[tuple[QLabel | None, list]] = []
        self._cols = 0
        self._name_width = 0
        self._label_width = 0
        self._available_width = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(CELL_GAP)
        self._grid.setVerticalSpacing(CELL_GAP)

    def add_group(self, title: str, cells: list) -> None:
        """`title` 给空串：这一组不要分类名，格子从最左边开始。"""
        label = None
        if title:
            label = keep_single_line(QLabel(title, self))
            label.setObjectName("weaponGroupLabel")
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._groups.append((label, list(cells)))
        # 先摆成一列：格子有了父控件才找得到（没显示过的页签也要能置灰、能被搜索落到）。
        self._reflow(self._cols or 1)

    def cells(self) -> list:
        return [cell for _label, cells in self._groups for cell in cells]

    def columns(self) -> int:
        return self._cols

    def set_available_width(self, width: int) -> None:
        """页面告诉它能用多宽。

        ⚠ 不看自己的宽度：自己的宽度跟着滚动条变，列数一变内容高度就变，
        滚动条又跟着出现或消失，来回振荡。这个数已经扣掉了滚动条。
        """
        self._available_width = width
        self._sync_layout()

    def _sync_name_width(self) -> int:
        cells = self.cells()
        if not cells:
            return 0
        width = max(cell.name_text_width() for cell in cells) + NAME_PADDING
        if width != self._name_width:
            self._name_width = width
            for cell in cells:
                cell.set_name_width(width)
            self._cols = 0
        return width

    def _sync_label_width(self) -> int:
        labels = [label for label, _cells in self._groups if label is not None]
        if not labels:
            return 0
        for label in labels:
            label.ensurePolished()
        width = max(label.fontMetrics().horizontalAdvance(label.text()) for label in labels) + 2
        if width != self._label_width:
            self._label_width = width
            for label in labels:
                label.setFixedWidth(width)
            self._grid.setColumnMinimumWidth(0, width + LABEL_GAP - CELL_GAP)
        return width

    def _sync_layout(self) -> None:
        name_width = self._sync_name_width()
        if not name_width or self._available_width <= 0:
            return
        label_width = self._sync_label_width()
        room = self._available_width - (label_width + LABEL_GAP if label_width else 0)
        # 控件的真实下限也要算：极简主题走系统样式，下拉和按钮都比样式表里的宽
        cell_width = max(name_width + CELL_TAIL_MIN_WIDTH, self.cells()[0].minimumSizeHint().width())
        cols = max(1, (room + CELL_GAP) // (cell_width + CELL_GAP))
        if self._max_columns:
            cols = min(cols, self._max_columns)
        if cols != self._cols:
            self._reflow(cols)

    def _reflow(self, cols: int) -> None:
        for row in range(self._grid.rowCount()):
            self._grid.setRowMinimumHeight(row, 0)
        for col in range(self._grid.columnCount()):
            self._grid.setColumnStretch(col, 0)
        for label, cells in self._groups:
            if label is not None:
                self._grid.removeWidget(label)
            for cell in cells:
                self._grid.removeWidget(cell)

        row = 0
        for index, (label, cells) in enumerate(self._groups):
            if index:
                # 组和组之间多空一点：空行不算格子间距，只占它自己的高度
                self._grid.setRowMinimumHeight(row, GROUP_GAP)
                row += 1
            if label is not None:
                self._grid.addWidget(label, row, 0)
            for at, cell in enumerate(cells):
                self._grid.addWidget(cell, row + at // cols, 1 + at % cols)
            row += (len(cells) + cols - 1) // cols
        for col in range(1, cols + 1):
            self._grid.setColumnStretch(col, 1)
        self._cols = cols

    def changeEvent(self, event):
        super().changeEvent(event)
        # 界面字号走全局样式表：换字号时枪名列宽要跟着重算
        if event.type() in (QEvent.StyleChange, QEvent.FontChange) and self._available_width:
            self._sync_layout()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_layout()


class BoardScrollArea(QScrollArea):
    """页面的滚动区，顺带报告内容能用多宽。

    ⭐ 这个数**按滚动条总在算**：滚动条出现或消失都不影响列数。
    """

    availableWidthChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        bar = self.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, self)
        self.availableWidthChanged.emit(self.width() - bar)
