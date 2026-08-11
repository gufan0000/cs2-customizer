# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R14/S10：结果面板"关了要能回来"的判据（离屏真窗口，2026-08-11）。

**缺陷**（用户真机反馈）：输入 → 出下拉 → 点一下别处 → 下拉消失 →
点回搜索框，下拉**不回来**，必须把字删掉重新打一遍。

面板是 `Qt::Popup`，点别处就关是 Qt 的语义，改不了也不该改（否则它会一直
浮在界面上挡东西）。缺陷在于**关了没有回来的路**：原来只在"聚焦 **且** 框是空的"
时弹一次，带着文字点回来就什么也不发生。

⚠ 判据为什么拆成两条而不是一条端到端：
离屏平台**不做窗口激活**，`QWidget.hasFocus()` 恒为 False（实测 `activateWindow()`
也救不回来）。而 `_reopen_search_popup` 里有一道"焦点已经跑了就别硬弹"的守卫——
它是对的，不能为了让判据跑通就把它拆掉（那是"判据自己先把前提做掉"）。
所以分开量：
  A. **分发**：哪些事件该安排重开、哪些不该  →  真事件走真 eventFilter
  B. **重开**：安排到了之后，面板里是不是**当次**搜索的结果  →  焦点用 monkeypatch 造
两条合起来才是完整的链路，各自都骗不了人。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QFocusEvent, QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    import gui_widget
    from config import config

    config.ui_expert_mode = True
    w = gui_widget.MainWindow(auto_background_preload=False)
    w.setAttribute(Qt.WA_DontShowOnScreen, True)
    w.show()
    app.processEvents()
    yield w
    try:
        w.close()
        w.deleteLater()
        app.processEvents()
    except Exception:
        pass


def _focus_in():
    return QFocusEvent(QEvent.FocusIn, Qt.OtherFocusReason)


def _click():
    return QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def _key(k):
    return QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier)


def _reopen_calls(win, app, monkeypatch, event):
    """真事件 → 真 eventFilter，数它安排了几次重开。"""
    seen = []
    monkeypatch.setattr(win, "_reopen_search_popup", lambda: seen.append(1))
    win.eventFilter(win.settings_search_box, event)
    app.processEvents()      # 让 singleShot(0) 落地
    return len(seen)


# ---------------- A. 分发：哪些事件该重开 ----------------


@pytest.mark.parametrize("make_event,label", [
    (_focus_in, "点回搜索框（FocusIn）"),
    (_click, "焦点没走、只是面板被关了（MouseButtonPress）"),
    (lambda: _key(Qt.Key_Down), "键盘用户按 ↓"),
    (lambda: _key(Qt.Key_Up), "键盘用户按 ↑"),
])
def test_these_events_reopen_the_panel(win, app, monkeypatch, make_event, label):
    """带着文字时这四种动作都要把面板叫回来。

    改造前只认「FocusIn **且** 框是空的」——这四条里三条根本不进分支，
    剩下 FocusIn 那条也被"框里有字"挡掉，于是用户只能删字重打。
    """
    win.settings_search_box.setText("准心")
    monkeypatch.setattr(win, "_search_popup_visible", lambda: False)
    assert _reopen_calls(win, app, monkeypatch, make_event()) == 1, f"{label} 没能重开"


def test_empty_box_also_reopens(win, app, monkeypatch):
    """空框点回来要给「最近搜索 / 常去页面」，这是改造前就有的行为，别弄丢。"""
    win.settings_search_box.setText("")
    monkeypatch.setattr(win, "_search_popup_visible", lambda: False)
    assert _reopen_calls(win, app, monkeypatch, _focus_in()) == 1


def test_visible_panel_is_not_reopened(win, app, monkeypatch):
    """面板已经开着时，↑↓ 要留给 completer 选行，不能被我们抢去重建 model。

    抢了的表现是：按 ↓ 选不动行，因为每按一次 model 就被重新填一遍。
    """
    win.settings_search_box.setText("准心")
    monkeypatch.setattr(win, "_search_popup_visible", lambda: True)
    for ev in (_focus_in(), _click(), _key(Qt.Key_Down), _key(Qt.Key_Up)):
        assert _reopen_calls(win, app, monkeypatch, ev) == 0


@pytest.mark.parametrize("key", [Qt.Key_A, Qt.Key_Left, Qt.Key_Home, Qt.Key_Escape])
def test_other_keys_do_not_reopen(win, app, monkeypatch, key):
    """普通打字/移光标不该触发重开——那条路是 textEdited 的活儿，
    在这里再来一遍等于每个字符搜两次。Esc 更是要**关**面板不是开。"""
    win.settings_search_box.setText("准心")
    monkeypatch.setattr(win, "_search_popup_visible", lambda: False)
    assert _reopen_calls(win, app, monkeypatch, _key(key)) == 0


def test_wheel_interception_survives(win, app):
    """⚠ 这段逻辑挂在**既有**的 eventFilter 里。另写一个同名方法的话，
    Python 后定义的会把先定义的整个覆盖掉，滚轮拦截那一整套就没了——
    改造过程中差点这么干过，所以留一条判据钉住。
    """
    import gui_widget

    src = (ROOT / "gui_widget.py").read_text(encoding="utf-8")
    assert src.count("    def eventFilter(") == 1, "出现了第二个 eventFilter 定义"
    assert hasattr(gui_widget.MainWindow, "_forward_wheel_to_scroll_area")


# ---------------- B. 重开：面板里是不是**当次**的结果 ----------------


def _force_focus(monkeypatch, win):
    """离屏平台不做窗口激活，hasFocus 恒 False。这里只造焦点，不动那道守卫。"""
    monkeypatch.setattr(win.settings_search_box, "hasFocus", lambda: True)


def test_reopen_refills_rows_for_the_current_text(win, app, monkeypatch):
    """带文字重开 → 面板里必须是**这段文字**的搜索结果。"""
    from core.settings_search import search_detailed

    _force_focus(monkeypatch, win)
    win.settings_search_box.setText("准星")
    win._search_rows = [{"kind": "page", "text": "陈年旧行", "page_id": "about"}]

    win._reopen_search_popup()
    app.processEvents()

    expected = search_detailed("准星")
    assert [r["text"] for r in win._search_rows] == [r["text"] for r in expected]
    assert win._settings_search_completer.popup().isVisible(), "行填了但面板没弹出来"


def test_reopen_reruns_the_search_instead_of_reusing_stale_rows(win, app, monkeypatch):
    """必须**重新搜**，不能把上次的行直接弹回来。

    中间可能已经换了主题、去过别的页（「常去」会变）、清过最近搜索。
    把旧行糊上去，用户看到的是一份过期结果——而且这种错静默、不报错。
    """
    calls = []
    real = win._on_search_text_edited
    monkeypatch.setattr(win, "_on_search_text_edited",
                        lambda t: (calls.append(t), real(t))[1])
    _force_focus(monkeypatch, win)
    win.settings_search_box.setText("音量")
    win._reopen_search_popup()
    app.processEvents()
    assert calls == ["音量"], f"没有重新跑搜索，只是把旧行弹回来了: {calls}"


def test_reopen_on_empty_box_gives_suggestions(win, app, monkeypatch):
    _force_focus(monkeypatch, win)
    win.settings_search_box.setText("")
    win._reopen_search_popup()
    app.processEvents()
    assert win._search_rows
    assert all(r.get("kind") in ("recent", "suggest") for r in win._search_rows)


def test_reopen_bails_when_focus_already_left(win, app):
    """守卫：这 0ms 里焦点跑了就别硬弹，否则弹出一个没人要的面板浮在界面上。

    离屏平台 hasFocus 天然是 False，这条不用造条件——环境白送的一条真判据。
    """
    win.settings_search_box.setText("准心")
    win._settings_search_completer.popup().hide()
    app.processEvents()
    win._search_rows = [{"kind": "page", "text": "哨兵", "page_id": "about"}]

    win._reopen_search_popup()
    app.processEvents()

    assert win._search_rows[0]["text"] == "哨兵", "焦点不在还是弹了"
    assert not win._settings_search_completer.popup().isVisible()


def test_ctrl_f_opens_the_panel_even_with_text(win, app, monkeypatch):
    """Ctrl+F 带文字时也要弹：文字已经全选，用户要么直接看结果、
    要么打字覆盖，两条路都比"面板不出来"强。"""
    _force_focus(monkeypatch, win)
    win.settings_search_box.setText("准心")
    win._search_rows = []
    win._focus_settings_search()
    app.processEvents()
    assert win._search_rows, "Ctrl+F 带文字时面板是空的"
