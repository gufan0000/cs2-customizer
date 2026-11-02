# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-530（**S2**）：一颗开关，必须离**它自己的**标签最近。

## 这条判据在防什么

首页「功能开关」是 3 列网格，每格 `[标签] [弹簧] [开关]`。
弹簧夹在标签和开关**中间** ⇒ 开关被推到格子最右边，而下一列的标签就在它右边一点点。

实测（批 59，两档）：

| | 离**自己**的标签 | 离**右边那个**标签 | 右边更近的 |
|---|---|---|---|
| 完整 1280×800 | 217px | **18px** | **11 / 17** |
| 紧凑 860×640 | 190px | **18px** | **11 / 17** |

⭐ 站在「击杀语音」四个字前面往左看，18px 外那颗开关其实是「击杀音效」的。

⚠ **光调列间距不可能修好它**：差距是 10~12 倍，列距要拉到 >217px 才谈得上翻转。
⇒ 修法只能是把弹簧挪到开关**后面**，让标签和它自己的开关贴在一起。

## 行为证据（改前 / 改后同题面，各 24 发）

问「你想关掉『击杀语音』，会去拨哪一颗开关」：
**改前 24/24 答「分不清」**（逐字：「左边紧挨着一颗开着的紫色开关，右边较远处又有一颗」）；
**改后 24/24 全部答对**，且理由是版面本身（「每一项开关都紧跟在其对应功能名称的右侧」）。

## 批 148

功能开关住进了卡片，开关贴卡片右边、名字贴左边：**边框接手了归属**，不再靠距离。
量的还是几何关系：开关和名字在同一张卡里，卡片之间留得开，同一列的开关对得齐。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

#: 出图工装用的那两档 —— **窗口尺寸只有一个来源**（CLAUDE.md §2）。
VIEWPORTS = {"完整": (1280, 800), "紧凑": (860, 640)}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=sorted(VIEWPORTS))
def win(app, request):
    import gui_widget
    from PySide6.QtCore import Qt

    width, height = VIEWPORTS[request.param]
    window = gui_widget.MainWindow(auto_background_preload=False)
    window.setAttribute(Qt.WA_DontShowOnScreen, True)
    window.resize(width, height)
    window.show()
    for _ in range(4):
        app.processEvents()
    window.show_page("basic", animated=False, force=True)
    for _ in range(8):
        app.processEvents()
    yield window
    window._force_exit = True
    window.close()
    window.deleteLater()
    app.processEvents()


def _rect(widget, page):
    return widget.rect().translated(widget.mapTo(page, widget.rect().topLeft()))


def test_every_home_switch_shares_a_card_with_its_own_name(win):
    """⭐⭐ **S2**：每一颗开关和它自己的名字在同一张卡里，别人的名字不在这张卡里。"""
    page = win.pages["basic"]
    assert len(win.switches) == 17, f"只量到 {len(win.switches)} 颗开关 —— 分母塌了"
    names = {sid: _rect(card.name_label, page) for sid, card in win.feature_cards.items()}
    for sid, toggle in win.switches.items():
        box = _rect(win.feature_cards[sid], page)
        assert box.contains(_rect(toggle, page)), sid
        assert box.contains(names[sid]), sid
        strangers = [other for other, rect in names.items() if other != sid and box.intersects(rect)]
        assert not strangers, f"{sid} 那张卡盖住了 {strangers} 的名字"


def test_the_cards_do_not_touch(win):
    """⭐ 反向守卫：边框是归属的全部依据，贴在一起就又分不清了。"""
    page = win.pages["basic"]
    rects = [(sid, _rect(card, page)) for sid, card in win.feature_cards.items()]
    for sid, rect in rects:
        for other, other_rect in rects:
            if other != sid:
                assert not rect.adjusted(-4, -4, 4, 4).intersects(other_rect), (sid, other)


def test_the_switches_still_line_up_in_columns(win):
    """⭐⭐ 批 59：开关跟着标签字数长短跑，外审 6/6 发报「参差错位」，而几何判据一条都看不见。

    这条钉的就是「对齐」：三组卡片里，同一列的开关 x 只许有一个取值。
    """
    page = win.pages["basic"]
    columns: dict[int, set[int]] = {}
    for sid, toggle in win.switches.items():
        columns.setdefault(_rect(win.feature_cards[sid], page).x(), set()).add(_rect(toggle, page).x())
    assert len(columns) >= 2, f"只认出 {len(columns)} 列 —— 分母塌了，这条判据在空转"
    ragged = {x: sorted(xs) for x, xs in columns.items() if len(xs) > 1}
    assert not ragged, f"这几列里的开关没对齐：{ragged}"
