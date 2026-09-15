# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""自带样式表的按钮，仍然要有「聚焦」和「禁用」这两个状态（RN-435 族 / X2）。

## 这条判据在防什么

⭐⭐⭐ **一个自带样式表的控件，等于把自己从「所有还没写的」全站规则里摘了出去。**
Qt 里控件级 stylesheet 的特异度压过应用级 QSS ——
于是每当全站补一条新规则（`:disabled`、`:focus`、下一条还没写的），
这些控件**安静地不跟**，而屏幕上没有任何东西会提示。

同一个形状本工程已经撞了四次：

| 批次 | 谁 | 漏掉的那一条 |
|---|---|---|
| 23（RN-150） | 全站 | 修好 `:disabled` |
| 37（RN-453） | `accountQuickButton` | `setEnabled(False)` **一个像素都不变** |
| 63（RN-546） | `accountQuickButton` | 补焦点环时**又**漏了它 |
| 64（RN-435） | `magnifier` 8 颗箭头 + `utility` 3 颗 | 聚焦**和**禁用**两样一起漏** |

⇒ 不再按名字点名，改成**按形状划分母**：凡是自带样式表的按钮，两个状态都得看得见。

## 量法

聚焦前后 / 禁用前后各抓一次像素，比差。
⚠ `hasFocus()` 需要窗口是**活动窗口**，离屏窗口默认不活动 ——
  不 `activateWindow()` 的话这条判据会把「尺子没量到」读成「产品没做到」（批 62 踩过）。
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


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    import gui_widget

    w = gui_widget.MainWindow()
    w.setAttribute(Qt.WA_DontShowOnScreen, True)   # ⛔ 不打扰前台
    w.resize(1280, 800)
    w.show()
    w.activateWindow()
    app.setActiveWindow(w)
    app.processEvents()
    for pid in list(w._page_names):
        try:
            w.show_page(pid, animated=False)
        except Exception:  # noqa: BLE001
            pass
    app.processEvents()
    yield w
    w._force_exit = True
    w.close()


def _diff(a, b):
    if a.size() != b.size():
        return -1
    return sum(1 for y in range(a.height()) for x in range(a.width())
               if a.pixel(x, y) != b.pixel(x, y))


def _self_styled(win):
    seen, out = set(), []
    for b in win.findChildren(QPushButton):
        if not b.styleSheet().strip() or not b.isEnabled():
            continue
        key = (b.objectName(), (b.text() or "")[:6], len(b.styleSheet()))
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


@pytest.fixture(scope="module")
def measured(app, win):
    rows = []
    for b in _self_styled(win):
        b.ensurePolished()
        base = b.grab().toImage()
        b.setFocus(Qt.TabFocusReason)
        app.processEvents()
        got = b.hasFocus()
        focus_diff = _diff(base, b.grab().toImage())
        b.clearFocus()
        app.processEvents()
        b.setEnabled(False)
        app.processEvents()
        b.ensurePolished()
        disabled_diff = _diff(base, b.grab().toImage())
        b.setEnabled(True)
        app.processEvents()
        rows.append({"name": b.objectName() or "(无名)",
                     "text": (b.text() or "")[:10],
                     "focused": got, "focus": focus_diff, "disabled": disabled_diff})
    return rows


def test_the_denominator_is_not_empty(measured):
    """分母守卫：自带样式表的按钮一颗都找不到时，这条判据必须喊出来。"""
    assert len(measured) >= 5, (
        f"只找到 {len(measured)} 类自带样式表的按钮（批 64 实测 8）—— 分母塌了")
    assert any(r["focused"] for r in measured), (
        "一颗都没真拿到焦点 —— 窗口不是活动窗口，这把尺子在空量（批 62 踩过）")


def test_a_self_styled_button_still_shows_focus(measured):
    """RN-546 / RN-435：自带样式表也得有焦点环。"""
    mute = [f"{r['name']} {r['text']!r}" for r in measured
            if r["focused"] and r["focus"] == 0]
    assert not mute, (
        "这几颗自带样式表的按钮，Tab 上去一个像素都不变：\n  " + "\n  ".join(mute)
        + "\n⭐ 控件级 stylesheet 压过全站 QSS —— 全站补的 `:focus` 它们不跟。")


def test_a_self_styled_button_still_looks_disabled(measured):
    """RN-453 / 批 23：自带样式表也得有禁用态。"""
    mute = [f"{r['name']} {r['text']!r}" for r in measured if r["disabled"] == 0]
    assert not mute, (
        "这几颗自带样式表的按钮，禁用前后一个像素都不变：\n  " + "\n  ".join(mute)
        + "\n⭐ 「禁用了但看不出来」是批 23 花整整一批修掉的东西。")
