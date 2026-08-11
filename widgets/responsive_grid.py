"""
响应式网格容器 - 根据宽度自动决定列数

用法：
    grid = ResponsiveGrid(breakpoints=[(1700, 3), (1200, 2), (0, 1)])
    grid.addItem(weapon_row_1)
    grid.addItem(weapon_row_2)
    ...
    # 默认行为：在 1700+ 宽用 3 列，1200~1700 用 2 列，<1200 单列
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QWidget


class ResponsiveGrid(QWidget):
    """根据自身宽度自动决定列数的网格容器。

    breakpoints 格式: [(min_width, columns), ...] 必须按 min_width 倒序排列
    例如 [(1700, 3), (1200, 2), (0, 1)] 表示：
      - 宽度 >= 1700: 3 列
      - 宽度 >= 1200: 2 列
      - 其它（>= 0）: 1 列
    """

    def __init__(
        self,
        breakpoints: list[tuple[int, int]] | None = None,
        spacing: int = 6,
        debounce_ms: int = 60,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.breakpoints = breakpoints or [(1700, 3), (1200, 2), (0, 1)]
        # 按 min_width 倒序，方便从大到小查找
        self.breakpoints.sort(key=lambda x: -x[0])

        self._grid = QGridLayout(self)
        self._grid.setSpacing(spacing)
        self._grid.setContentsMargins(0, 0, 0, 0)

        self._items: list[QWidget] = []
        self._current_cols = 1

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._reflow)
        self._debounce_ms = debounce_ms

    def addItem(self, widget: QWidget) -> None:
        """添加一个子项（按当前列数排版）"""
        self._items.append(widget)
        idx = len(self._items) - 1
        row = idx // self._current_cols
        col = idx % self._current_cols
        self._grid.addWidget(widget, row, col)

    def clear(self) -> None:
        """移除所有子项（不销毁 widget）"""
        for item in self._items:
            self._grid.removeWidget(item)
        self._items.clear()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start(self._debounce_ms)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 首次显示时立刻 reflow（同步执行，避免"先单列后双列"闪烁）
        # debounce timer 仅用于后续 resize 事件
        self._reflow()
        # 再加一次延迟 reflow 兜底（widget 在 showEvent 时尺寸可能尚未计算完）
        self._resize_timer.start(50)

    def _compute_cols(self, width: int) -> int:
        for min_w, cols in self.breakpoints:
            if width >= min_w:
                return cols
        return 1

    def _reflow(self) -> None:
        w = self.width()
        cols = self._compute_cols(w)
        if cols == self._current_cols:
            return
        self._current_cols = cols

        # 从布局中临时移除所有 widget（不销毁）
        for item in self._items:
            self._grid.removeWidget(item)

        # 重新加入
        for i, item in enumerate(self._items):
            row = i // cols
            col = i % cols
            self._grid.addWidget(item, row, col)

    @property
    def current_cols(self) -> int:
        return self._current_cols
