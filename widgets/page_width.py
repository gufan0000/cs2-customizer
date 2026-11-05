# SPDX-License-Identifier: GPL-3.0-or-later
"""页面内容区的宽度上限（批 157）。

窗口拉宽或最大化时，卡片原来跟着摊满整屏：一行字从左读到右要转头，
一个下拉框和它的说明隔着半个屏幕。上限取默认窗口（1280 宽）碰不到的值，
所以默认尺寸和紧凑档一个像素都不变，只管拉宽之后。

全站一处套用（`gui_widget._harmonize_page_chrome`）：只限一部分页，切页时内容宽度会跳。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QScrollArea, QWidget

#: 页面从左缘起最多这么宽（含左右页边距），靠左对齐
PAGE_CONTENT_MAX_WIDTH = 1200
#: 批 161：有固定底栏的页，内容要滚时末尾至少留这么多
SCROLL_END_GAP = 12


def cap_page(page) -> None:
    """页头、状态卡、滚动区里的内容、微调栏、底栏，都停在同一条右缘上。

    ⚠ 滚动区本身不限：它一窄，滚动条就从窗口边上挪进来。只限它里面的内容。
    ⚠ 根布局里直接套着子布局的页（准心：舞台 + 参数栏）整页不限 ——
      子布局限不了宽，只限页头会让一页之内两条右缘。
    """
    root = page.layout()
    if root is None:
        return
    widgets = []
    for index in range(root.count()):
        item = root.itemAt(index)
        if item.layout() is not None:
            return
        if item.widget() is not None:
            widgets.append(item.widget())
    margins = root.contentsMargins()
    limit = PAGE_CONTENT_MAX_WIDTH - margins.left() - margins.right()
    for widget in widgets:
        if not isinstance(widget, QScrollArea):
            widget.setMaximumWidth(limit)
    for scroll in page_level_scrolls(page):
        content = scroll.widget()
        if content is not None:
            content.setMaximumWidth(limit if scroll.parentWidget() is page else PAGE_CONTENT_MAX_WIDTH)
            scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)


def keep_scroll_end_clear(scroll: QScrollArea, gap: int = SCROLL_END_GAP) -> None:
    """内容本来就要滚时，末尾垫一截 `gap`，滚到底最后一行不贴着底栏（预设中心原来 0px）。

    ⚠ 放得下时不垫：垫了会平白多出几像素可滚、冒一条滚动条（局内视角 5px、语音输出 2px）。
    所以不能写成布局的下边距，只能是一截跟着滚动范围显隐的占位。
    """
    content = scroll.widget()
    lay = content.layout() if content is not None else None
    if not isinstance(lay, QBoxLayout) or lay.contentsMargins().bottom() >= gap:
        return
    spacer = QWidget(content)
    spacer.setObjectName("scrollEndGap")
    spacer.setFixedHeight(max(0, gap - max(0, lay.spacing())))   # 它前面那段布局间距也算在 gap 里
    spacer.hide()
    lay.addWidget(spacer)

    def sync(_low, high):
        shown = spacer.isVisibleTo(content)
        overflow = high - (spacer.height() + max(0, lay.spacing()) if shown else 0)   # 不垫的话还要滚多少
        if (overflow > 0) != shown:
            spacer.setVisible(overflow > 0)

    scroll.verticalScrollBar().rangeChanged.connect(sync)


def available_width(scroll: QScrollArea, width: int) -> int:
    """滚动区里的内容实际能用多宽：内容有上限时按上限算（武器板按它排列数）。"""
    content = scroll.widget()
    return min(int(width), content.maximumWidth()) if content is not None else int(width)


def page_level_scrolls(page) -> list[QScrollArea]:
    """页面自己的滚动区：不套在另一个滚动区里的那些（卡片里的小滚动区不算）。"""
    scrolls = []
    for scroll in page.findChildren(QScrollArea):
        parent = scroll.parentWidget()
        nested = False
        while parent is not None and parent is not page:
            if isinstance(parent, QScrollArea):
                nested = True
                break
            parent = parent.parentWidget()
        if not nested:
            scrolls.append(scroll)
    return scrolls
