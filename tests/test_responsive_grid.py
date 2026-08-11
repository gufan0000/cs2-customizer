# SPDX-License-Identifier: GPL-3.0-or-later
"""ResponsiveGrid 单元测试 — 验证断点计算、addItem、首次 reflow"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from widgets.responsive_grid import ResponsiveGrid


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_compute_cols_uses_breakpoints(qapp):
    grid = ResponsiveGrid(breakpoints=[(1500, 3), (1000, 2), (0, 1)])
    assert grid._compute_cols(2000) == 3
    assert grid._compute_cols(1500) == 3
    assert grid._compute_cols(1499) == 2
    assert grid._compute_cols(1000) == 2
    assert grid._compute_cols(999) == 1
    assert grid._compute_cols(0) == 1


def test_breakpoints_sorted_descending(qapp):
    """无论传入顺序如何，内部存储应按 min_width 倒序"""
    grid = ResponsiveGrid(breakpoints=[(0, 1), (1500, 3), (1000, 2)])
    widths = [bp[0] for bp in grid.breakpoints]
    assert widths == sorted(widths, reverse=True)


def test_add_item_initially_single_column(qapp):
    grid = ResponsiveGrid(breakpoints=[(1500, 3), (1000, 2), (0, 1)])
    a, b, c = QLabel("a"), QLabel("b"), QLabel("c")
    grid.addItem(a)
    grid.addItem(b)
    grid.addItem(c)
    layout = grid._grid
    assert grid._items == [a, b, c]
    # 默认 _current_cols=1，3 个 item 应该 row 0,1,2 col 0,0,0
    assert layout.rowCount() == 3


def test_clear_removes_all(qapp):
    grid = ResponsiveGrid()
    for i in range(4):
        grid.addItem(QLabel(str(i)))
    assert len(grid._items) == 4
    grid.clear()
    assert grid._items == []


def test_reflow_changes_columns_when_width_changes(qapp):
    grid = ResponsiveGrid(breakpoints=[(1500, 3), (1000, 2), (0, 1)])
    for i in range(6):
        grid.addItem(QLabel(str(i)))
    grid.resize(1600, 800)
    # 直接调内部 reflow 跳过 debounce timer
    grid._reflow()
    assert grid.current_cols == 3

    grid.resize(1100, 800)
    grid._reflow()
    assert grid.current_cols == 2

    grid.resize(500, 800)
    grid._reflow()
    assert grid.current_cols == 1


def test_reflow_noop_when_cols_unchanged(qapp):
    """同样列数下重复 reflow 不应破坏布局"""
    grid = ResponsiveGrid(breakpoints=[(1500, 3), (1000, 2), (0, 1)])
    grid.addItem(QLabel("only"))
    grid.resize(800, 600)
    grid._reflow()
    cols_before = grid.current_cols
    grid._reflow()
    assert grid.current_cols == cols_before


def test_default_breakpoints(qapp):
    grid = ResponsiveGrid()
    # 默认 [(1700, 3), (1200, 2), (0, 1)]
    assert grid._compute_cols(1700) == 3
    assert grid._compute_cols(1200) == 2
    assert grid._compute_cols(800) == 1
