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

⛔ 不拿像素比，拿**几何关系**比 —— 批 43 记过：能用结构表达的不变量别拿像素去量。
   这里量的是「谁离谁近」这个序关系，不是绝对坐标。
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


def _home_switch_geometry(win, page):
    """(switch_id, 离自己标签的距离, 离右边那个标签的距离, 右边那个的文案)。

    ⚠ 分母取**产品自己的那张表** `win.switches` 与它自己接的那条线 `toggle._label` ——
      不按控件类型猜、不靠 y 坐标凑行（批 34 连造三个错分母的教训）。
    """
    def rect(w):
        tl = w.mapTo(page, w.rect().topLeft())
        return tl.x(), tl.y(), w.width(), w.height()

    geo = {}
    for sid, tg in win.switches.items():
        label = getattr(tg, "_label", None)
        if label is None or not tg.isVisibleTo(page):
            continue
        lx, ly, lw, lh = rect(label)
        # 量**文字**的右沿，不是控件的右沿（批 59 复跑补刀）：
        # 标签统一宽度之后控件右沿永远紧挨着开关（6px），
        # 而用户看见的是文字结束的地方 —— 两者最多差 56px。
        # 判据量控件、用户看文字，就是一条量错了东西的判据。
        text_w = min(lw, label.fontMetrics().horizontalAdvance(label.text()))
        geo[sid] = (rect(tg), (lx, ly, text_w, lh), label.text())

    out = []
    for sid, (t, lb, _text) in geo.items():
        tx, ty, tw, th = t
        lx, _ly, lw, _lh = lb
        own = tx - (lx + lw)
        cy = ty + th / 2
        others = [
            (o_lb[0] - (tx + tw), o_text)
            for k, (_o_t, o_lb, o_text) in geo.items()
            if k != sid
            and abs(o_lb[1] + o_lb[3] / 2 - cy) <= 12
            and o_lb[0] >= tx + tw
        ]
        nearest, text = min(others, default=(None, None))
        out.append((sid, own, nearest, text))
    return out


@pytest.mark.parametrize("viewport", sorted(VIEWPORTS))
def test_every_home_switch_is_nearest_to_its_own_label(app, viewport):
    """⭐⭐ **S2**：每一颗开关，离自己的标签必须比离别人的标签近。"""
    import gui_widget
    from PySide6.QtCore import Qt

    width, height = VIEWPORTS[viewport]
    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.resize(width, height)
        win.show()
        for _ in range(4):
            app.processEvents()
        win.show_page("basic", animated=False, force=True)
        for _ in range(4):
            app.processEvents()
        page = win.pages["basic"]

        rows = _home_switch_geometry(win, page)
        #: 空转守卫：首页有 17 颗开关。一颗都量不到时下面那个循环什么都不比。
        assert len(rows) >= 15, (
            f"{viewport}档只量到 {len(rows)} 颗开关 —— 分母塌了，这条判据在空转")

        confusing = [
            (sid, own, other, text)
            for sid, own, other, text in rows
            if other is not None and other < own
        ]
        assert not confusing, (
            f"{viewport}档有 {len(confusing)} 颗开关离**别人的**标签更近：\n  "
            + "\n  ".join(
                f"{sid}：离自己 {own}px，而离「{text}」只有 {other}px"
                for sid, own, other, text in confusing)
            + "\n⭐ 站在那几个字前面往左看，最近的那颗开关是上一个功能的。\n"
            "⚠ 调列间距没用 —— 差距是十倍量级；弹簧必须在开关**后面**。")
    finally:
        win._force_exit = True
        win.close()
        win.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("viewport", sorted(VIEWPORTS))
def test_the_gap_to_its_own_label_stays_small(app, viewport):
    """⭐ 反向守卫：上面那条只比**序关系**，它在「所有标签都离得一样远」时也绿。

    这一条钉住「贴在一起」这个事实本身（实测修完是 6px），
    免得哪天有人用「把别人的标签推得更远」来满足上一条。
    """
    import gui_widget
    from PySide6.QtCore import Qt

    width, height = VIEWPORTS[viewport]
    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.resize(width, height)
        win.show()
        for _ in range(4):
            app.processEvents()
        win.show_page("basic", animated=False, force=True)
        for _ in range(4):
            app.processEvents()
        page = win.pages["basic"]

        rows = _home_switch_geometry(win, page)
        assert len(rows) >= 15, f"{viewport}档只量到 {len(rows)} 颗开关 —— 分母塌了"
        far = [(sid, own) for sid, own, _o, _t in rows if own > 80]
        assert not far, (
            f"{viewport}档这几颗开关离自己那几个字超过 80px：{far}\n"
            "⭐ 实测（标签统一宽度之后）最远的是「准心」两个字的 68px，"
            "而下一列的标签在 229px 外 —— 差 3 倍以上才叫归属清楚。")

        # ⭐ 序关系还不够：own 必须**显著**小于 next，
        #   否则「差不多远」的时候人还是要猜。
        ratio_bad = [
            (sid, own, other) for sid, own, other, _t in rows
            if other is not None and own * 2 > other
        ]
        assert not ratio_bad, (
            f"{viewport}档这几颗开关离自己那几个字，超过了到下一个标签距离的一半：\n  "
            + "\n  ".join(f"{sid}：自己 {own}px / 下一个 {other}px"
                          for sid, own, other in ratio_bad))
    finally:
        win._force_exit = True
        win.close()
        win.deleteLater()
        app.processEvents()

@pytest.mark.parametrize("viewport", sorted(VIEWPORTS))
def test_the_switches_still_line_up_in_columns(app, viewport):
    """⭐⭐ **改完复跑逼出来的那一刀**（批 59）。

    把弹簧挪到开关后面之后，开关跟着标签字数长短跑 ——
    外审同一批图 **6/6 发**报「开关未按列对齐，参差错位」（中）。
    ⚠ 那是我为了修 RN-530 亲手引入的，而**几何判据一条都看不见它**
      （序关系照样成立、间距照样小）。

    ⇒ 修法：标签统一到同一个宽度。两件事同时成立 ——
      开关仍紧跟自己的那几个字（最远 68px），而三列重新对齐。

    这条判据钉的就是「对齐」这件事：同一列里的开关，x 只许有一个取值。
    """
    import gui_widget
    from PySide6.QtCore import Qt

    width, height = VIEWPORTS[viewport]
    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.resize(width, height)
        win.show()
        for _ in range(4):
            app.processEvents()
        win.show_page("basic", animated=False, force=True)
        for _ in range(4):
            app.processEvents()
        page = win.pages["basic"]

        columns: dict[int, set[int]] = {}
        for _sid, tg in win.switches.items():
            label = getattr(tg, "_label", None)
            if label is None or not tg.isVisibleTo(page):
                continue
            lx = label.mapTo(page, label.rect().topLeft()).x()
            tx = tg.mapTo(page, tg.rect().topLeft()).x()
            columns.setdefault(lx, set()).add(tx)

        assert len(columns) >= 3, (
            f"{viewport}档只认出 {len(columns)} 列 —— 分母塌了，这条判据在空转")
        ragged = {lx: sorted(xs) for lx, xs in columns.items() if len(xs) > 1}
        assert not ragged, (
            f"{viewport}档这几列里的开关没对齐（同一列出现了多个 x）：{ragged}\n"
            "⭐ 标签字数不一样时，开关会跟着长短跑 —— 统一标签宽度才压得住。")
    finally:
        win._force_exit = True
        win.close()
        win.deleteLater()
        app.processEvents()
