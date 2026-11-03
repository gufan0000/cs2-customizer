# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 157：窗口拉宽后，页面内容停在一条右缘上，不再摊满整屏。

1280 宽的默认窗口内容区只有 1064，碰不到上限，所以默认尺寸和紧凑档一个像素都不变
（那两档由视觉基线管）；这里只量拉宽之后。

⚠ 上限写死 1200，不读 `PAGE_CONTENT_MAX_WIDTH`：读常量的话，常量被改大，判据跟着放宽。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

LIMIT = 1200
#: 页头在滚动区里 / 在外面、带微调栏、整页包一层容器、滚动区套在容器里 —— 五种搭法各挑一页
CAPPED_PAGES = ("hud_color", "kill_sound", "gun_sound", "music", "special_sound", "preset_center")


@pytest.fixture(scope="module")
def win():
    import gui_widget
    from PySide6.QtCore import Qt

    app = QApplication.instance() or QApplication([])
    window = gui_widget.MainWindow(auto_background_preload=False)
    window.setAttribute(Qt.WA_DontShowOnScreen, True)
    window.show()
    window.setMinimumSize(1920, 900)
    window.resize(1920, 900)
    for _ in range(4):
        app.processEvents()
    yield window
    window._force_exit = True
    window.close()
    window.deleteLater()
    app.processEvents()


def _show(win, pid):
    app = QApplication.instance()
    win.show_page(pid, animated=False, force=True)
    for _ in range(6):
        app.processEvents()
    return win.pages[pid]


def _right(widget, page):
    return widget.mapTo(page, widget.rect().topRight()).x() + 1


def _root_widgets(page):
    root = page.layout()
    return [root.itemAt(i).widget() for i in range(root.count())
            if root.itemAt(i).widget() is not None and root.itemAt(i).widget().isVisible()]


@pytest.mark.parametrize("pid", CAPPED_PAGES)
def test_nothing_on_the_page_runs_past_the_limit(win, pid):
    page = _show(win, pid)
    assert page.width() > 1600, f"窗口没拉宽（页面 {page.width()}）—— 这一条量的是拉宽之后"
    edges = {}
    for widget in _root_widgets(page):
        if isinstance(widget, QScrollArea):
            widget = widget.widget()
        edges[type(widget).__name__] = _right(widget, page)
    for scroll in page.findChildren(QScrollArea):
        if scroll.isVisible() and scroll.widget() is not None and scroll.widgetResizable():
            edges.setdefault(f"滚动区内容 {scroll.objectName() or type(scroll).__name__}",
                             _right(scroll.widget(), page))
    over = {name: right for name, right in edges.items() if right > LIMIT}
    assert not over, f"{pid}：这些摊过了 {LIMIT}：{over}"


def test_the_weapon_board_counts_columns_on_the_capped_width(win):
    """武器板按滚动区报的可用宽排列数：报的是没限过的宽，就会多排一列、挤出内容区。"""
    page = _show(win, "kill_sound")
    content = page.content_scroll.widget()
    assert page.weapon_board._available_width <= content.width(), (
        f"武器板以为有 {page.weapon_board._available_width}，内容区只有 {content.width()}")


def test_a_page_with_a_side_panel_stays_whole(win):
    """准心页是舞台 + 参数栏（根布局里套着子布局，限不了宽）：整页不限，页头和参数栏的右缘对齐。"""
    page = _show(win, "crosshair")
    header_right = max(_right(w, page) for w in _root_widgets(page))
    panel_right = _right(page.parameter_scroll, page)
    assert abs(header_right - panel_right) <= 4, (
        f"页头停在 {header_right}，参数栏在 {panel_right}：一页之内两条右缘")
