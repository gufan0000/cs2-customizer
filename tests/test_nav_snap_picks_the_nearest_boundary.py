# -*- coding: utf-8 -*-
"""RN-100：侧栏对齐要**就近**，两个方向都试。

**这条是开源版逮到的，而闭源版一直是绿的。**

原实现只往上退：`target = max(t for t in tops if t <= current)`，
注释写的理由是"不会把当前项推出视口"。闭源版看不出问题——
那里导航项高恰好统一 43px，`ensureWidgetVisible` 算出的滚动值天然落在
项顶边上，`target == current` 直接返回，**这条路根本没走过**。

开源版少一个账号页，项高变成 42 / 43 / 47 混着（分组标题比普通项高），
滚动值偏离边界 4px：实测 48 / 91 / 134 / 177…，而项顶边在 52 / 99 / 141…。
这时"只往上退"的唯一候选是 10 —— 往上跳 38px 会把当前项挤出视口 ⇒ 撤销
⇒ 停在 48 ⇒ **顶上那一项 40px 里被切掉 38**，只剩 2px。开源版 28 页里 14 页中招。

⭐ **同一段代码在两边表现完全不同，差别只是"项高是否恰好整齐"。
一个只在整齐时正确的算法，在它正确的那个环境里是看不出来的。**
⇒ 所以这条判据**自己造出不整齐**，不依赖产品当下的项高。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def rig(qapp):
    """造一个项高不齐的侧栏：42 / 47 / 42 / 43 —— 和开源版实测同形。"""
    from PySide6.QtWidgets import QPushButton, QScrollArea, QVBoxLayout, QWidget

    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(0, 10, 0, 0)
    lay.setSpacing(0)
    buttons = []
    for i, h in enumerate((42, 47, 42, 43, 42, 47, 42, 43)):
        b = QPushButton(f"项{i}")
        b.setFixedHeight(h)
        lay.addWidget(b)
        buttons.append(b)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)
    scroll.resize(200, 120)
    scroll.show()
    qapp.processEvents()
    yield scroll, content, buttons
    scroll.deleteLater()
    qapp.processEvents()


def _tops(content, buttons):
    from PySide6.QtCore import QPoint
    return sorted({b.mapTo(content, QPoint(0, 0)).y() for b in buttons})


def test_snapping_lands_exactly_on_an_item_boundary(rig, qapp):
    import gui_widget

    scroll, content, buttons = rig
    tops = _tops(content, buttons)
    bar = scroll.verticalScrollBar()
    if bar.maximum() <= 0:
        pytest.skip("造出来的内容没溢出，滚不动（宁可跳过也不假绿）")

    # 故意停在两个边界之间：上一个边界之后 4px
    between = tops[1] + 4
    if between >= bar.maximum():
        pytest.skip("造的样本滚不到那么远")
    bar.setValue(between)
    qapp.processEvents()
    assert bar.value() not in tops, "前提没造出来：这个值本来就在边界上"

    gui_widget.MainWindow._snap_nav_scroll_to_item_boundary(scroll)

    assert bar.value() in tops, (
        f"对齐之后滚动值 {bar.value()} 仍不在项顶边 {tops} 上 —— "
        "视口上边缘落在某一项中间，那一项被切成半截（RN-060/RN-100）")


def test_it_picks_the_nearer_boundary_not_always_the_one_above(rig, qapp):
    """⭐ 要害：就近，而不是一律往上退。

    停在「上一个边界 +4」时，下一个边界只差几十 px 里的一小截，
    而上一个边界差 4px —— 无论哪个更近，都不许出现"跳过整整一项"的结果。
    """
    import gui_widget

    scroll, content, buttons = rig
    tops = _tops(content, buttons)
    bar = scroll.verticalScrollBar()
    if bar.maximum() <= 0:
        pytest.skip("滚不动")
    # ⚠ 必须停在**边界之前**：这时最近的边界在**上方**（下一项的顶边），
    # 而"只往上退"会退回上一项的顶边——跳掉整整一项。
    # 停在"边界之后 4px"是**不能鉴别**的场景：那时往上退恰好就是最近的，
    # 两种实现给同一个答案。第一版判据就是这么造的，回退验证当场判它假绿。
    between = tops[2] - 4
    if between <= 0 or between >= bar.maximum():
        pytest.skip("造的样本滚不到那么远")
    bar.setValue(between)
    qapp.processEvents()
    assert bar.value() == between and between not in tops, "前提没造出来"

    gui_widget.MainWindow._snap_nav_scroll_to_item_boundary(scroll)

    moved = abs(bar.value() - between)
    nearest = min(abs(t - between) for t in tops)
    assert moved == nearest, (
        f"对齐挪动了 {moved}px，而最近的边界只差 {nearest}px。"
        "只往上退会跳掉整整一项，那一项就被切成半截。")


def test_keeping_the_current_item_visible_still_wins(rig, qapp):
    """RN-008 优先级不变：两个方向都会把当前项挤出去时，放弃对齐。"""
    import gui_widget

    scroll, content, buttons = rig
    bar = scroll.verticalScrollBar()
    if bar.maximum() <= 0:
        pytest.skip("滚不动")
    tops = _tops(content, buttons)
    between = tops[1] + 4
    if between >= bar.maximum():
        pytest.skip("造的样本滚不到那么远")
    bar.setValue(between)
    qapp.processEvents()

    class _NeverVisible:
        """无论滚到哪都"在视口外"——逼对齐放弃。"""
        def mapTo(self, *_a):
            from PySide6.QtCore import QPoint
            return QPoint(0, -9999)

        def height(self):
            return 40

        def sizeHint(self):
            return self

    gui_widget.MainWindow._snap_nav_scroll_to_item_boundary(
        scroll, keep_visible=_NeverVisible())
    assert bar.value() == between, (
        "当前项怎么都挤出视口时应该放弃对齐、保持原样（RN-008 优先于 RN-060）")
