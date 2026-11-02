# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import gc
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLabel

import gui_widget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _dispose_widgets(app, *widgets):
    """Phase1: 测试创建的无父级 widget 必须在 QApplication 存活期内经
    deleteLater 体面销毁——否则解释器退出阶段由 GC 乱序析构会触发
    原生堆损坏 (0xC0000374)，用例全过但进程崩溃。"""
    for w in widgets:
        try:
            w.deleteLater()
        except RuntimeError:
            pass
    for _ in range(3):
        app.processEvents()
    gc.collect()
    app.processEvents()


def test_home_player_label_elides_long_id(qapp):
    long_id = "76561198012345678"
    win = type("W", (), {})()
    win.config = SimpleNamespace(player_steamid=long_id)
    win.player_label = QLabel()
    win.player_label.resize(118, 28)
    win._home_player_label_text = (
        lambda player_id=None: gui_widget.MainWindow._home_player_label_text(win, player_id)
    )

    gui_widget.MainWindow._refresh_home_player_label(win)

    # ⭐ RN-403（批 59）：文案从「当前玩家ID: x」缩短成「ID · x」，
    #   省略方向从 ElideMiddle 改成 ElideRight ——
    #   真要切，切掉的该是一长串数字的尾巴，不是句子中间那截。
    assert win.player_label.toolTip() == f"ID · {long_id}"
    shown = win.player_label.text()
    assert len(shown) < len(win.player_label.toolTip())
    assert win.player_label.toolTip().startswith(shown.rstrip("…").rstrip(".")), (
        f"显示的「{shown}」不是全文的前缀 —— 被切掉的是中间那截")

    _dispose_widgets(qapp, win.player_label)
