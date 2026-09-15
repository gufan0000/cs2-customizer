# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tab 到一颗按钮，屏幕上必须有变化（RN-546 / X2）。

## 这条判据在防什么

WCAG 2.1 §2.4.7 要求键盘焦点**可见**。实测（批 62）：8 类按钮
（`navButton` 侧栏导航 / `navGroupHeader` / `hamburgerButton` / `helpButton` /
`helpCloseButton` / `accountQuickButton` / `modeToggleButton` /
`modeToggleIconButton`）**聚焦前后像素差全部为 0** —— Tab 上去，
屏幕上一个像素都不变。

根因：QSS 里 `QPushButton:focus {{ outline: none; }}`，而它上面那句注释写着
「navButton/iconButton 等无显式 :focus 的**也走这**」。
⭐ **注释说「这些也走这里」，而那条规则什么都没给它们。**

⚠ `scripts/tab_order_audit.py` 一直是绿的 —— 它管的是焦点**顺序**，
  不是**看不看得见**。⭐ 名字里带「焦点」的审计，未必看着焦点的这一面。

## 这把尺子自己差点是错的

第一版报「13/13 零像素」——**包括本该会变的 `secondaryButton`**。
`hasFocus()` 需要窗口是**活动窗口**，而离屏窗口默认不活动。
⭐⭐ **是阳性对照把这把尺子拦下的**：有 `:focus` 规则的那几个必须会变，
它们要是也不变，那就是尺子坏了，不是产品坏了。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

#: 这 8 类原来只落到 `QPushButton:focus {{ outline: none }}` 上。
WAS_MUTE = (
    "navButton", "navGroupHeader", "hamburgerButton", "accountQuickButton",
    "helpButton", "helpCloseButton", "modeToggleButton", "modeToggleIconButton",
)
#: 阳性对照：本来就有 `:focus` 规则的，必须会变 —— 它们不变就是尺子坏了。
CONTROL = ("primaryButton", "secondaryButton")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    import gui_widget

    w = gui_widget.MainWindow()
    # ⛔ 不打扰前台（CLAUDE.md §3）；⭐ 但必须 show + activate，
    #   否则 `hasFocus()` 恒假，这条判据会把「尺子没量到」读成「产品没做到」。
    w.setAttribute(Qt.WA_DontShowOnScreen, True)
    w.resize(1280, 800)
    w.show()
    w.activateWindow()
    app.setActiveWindow(w)
    app.processEvents()
    # ⚠⚠ 批 67：这里原来走  —— 批 66 记过**两条加载路径量出不同的数**，
    #   而这一条正是判据站错路的那一次：单跑时只建得出 4 类按钮（分母守卫当场判红），
    #   整套跑时靠别的判据顺手把窗口带成另一个样子才凑够 8 类。
    #   ⭐ **一条依赖别人副作用才够分母的判据，单跑与整跑会给出不同结论。**
    w.show_page("basic", animated=False, force=True)
    for _ in range(6):
        app.processEvents()
    yield w
    w._force_exit = True
    w.close()


def _focus_diff(app, widget):
    """聚焦前后的像素差；返回 (真拿到焦点, 差了几个像素)。"""
    widget.clearFocus()
    app.processEvents()
    widget.ensurePolished()
    before = widget.grab().toImage()
    widget.setFocus(Qt.TabFocusReason)
    app.processEvents()
    got = widget.hasFocus()
    after = widget.grab().toImage()
    widget.clearFocus()
    app.processEvents()
    if before.size() != after.size():
        return got, -1
    diff = sum(1 for y in range(before.height()) for x in range(before.width())
               if before.pixel(x, y) != after.pixel(x, y))
    return got, diff


def _sample(win):
    seen, out = set(), []
    for b in win.findChildren(QPushButton):
        name = b.objectName()
        if name in seen or not b.isEnabled() or not b.isVisibleTo(win):
            continue
        if name in WAS_MUTE or name in CONTROL:
            seen.add(name)
            out.append((name, b))
    return out


def test_the_ruler_itself_works(app, win):
    """⭐ 阳性对照先立起来：本来就有 `:focus` 规则的那几个必须会变。"""
    rows = [(n, b) for n, b in _sample(win) if n in CONTROL]
    assert len(rows) >= 2, f"只取到 {[n for n, _ in rows]} —— 阳性对照的分母塌了"
    for name, b in rows:
        got, diff = _focus_diff(app, b)
        assert got, f"{name} 没真拿到焦点 —— 窗口不是活动窗口，这把尺子在空量"
        assert diff > 0, (
            f"阳性对照 {name} 聚焦前后一个像素都没变 —— **是尺子坏了，不是产品坏了**")


def test_every_button_shows_something_when_focused(app, win):
    """RN-546：这 8 类按钮 Tab 上去，屏幕上必须有变化。"""
    rows = [(n, b) for n, b in _sample(win) if n in WAS_MUTE]
    # ⚠ 批 98：下限 5 —— 开源版首屏没有「登录账号」那颗（RN-543）。
    assert len(rows) >= 5, (
        f"只取到 {sorted(n for n, _ in rows)} —— 分母塌了（批 62 实测这 8 类都在首屏）")
    mute = []
    for name, b in rows:
        got, diff = _focus_diff(app, b)
        if not got:
            continue
        if diff == 0:
            mute.append(name)
    assert not mute, (
        f"这几类按钮 Tab 上去屏幕上一个像素都不变：{sorted(mute)}\n"
        "⭐ WCAG 2.1 §2.4.7：键盘焦点必须看得见 —— 侧栏导航是键盘用户的主路。")


def test_the_generic_rule_does_not_silently_swallow_them():
    """⭐ 结构断言：`QPushButton:focus {{ outline: none }}` 那条规则还在，

    所以只要有人把这 8 类的 `:focus` 规则删掉，它们又会安静地落回去 ——
    **而屏幕上不会有任何东西提示**。这条钉住「它们有自己的规则」这件事。
    """
    src = (REPO / "theme_manager.py").read_text(encoding="utf-8")
    assert "QPushButton:focus" in src, "样式表里找不到通用 :focus 规则 —— 判据在空转"
    missing = [n for n in WAS_MUTE
               if f"QPushButton#{n}:focus" not in src
               and n != "accountQuickButton"]     # 它走 gui_widget 里的内联样式表
    assert not missing, (
        f"这几类在样式表里没有自己的 `:focus` 规则了：{missing}\n"
        "⭐ 它们会安静地落回 `QPushButton:focus {{ outline: none }}`。")
    inline = (REPO / "gui_widget.py").read_text(encoding="utf-8")
    if "accountQuickButton" not in inline:
        return    # 开源版没有那颗按钮（RN-543 同步时验收门逮到的），前八类已经在上面断言过
    assert "QPushButton:focus" in inline, (
        "`accountQuickButton` 的内联样式表里没有 `:focus` 了 —— "
        "⭐ 它的内联样式表特异度压过全站 QSS（同 RN-453），这一条必须在那儿写一遍。")
