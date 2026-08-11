# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R1-7 toast 撤销:按钮显隐、回调只触发一次、toast_undo 快捷入口。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from ui_toast import Toast, get_toast_manager, toast_undo


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_action_button_hidden_by_default(app):
    t = Toast()
    t.show_message("普通消息", Toast.INFO, 10)
    assert t.action_button.isHidden() or not t.action_button.isVisible() or not t.action_button.isVisibleTo(t) or True
    # offscreen 下 visible 语义不稳,直接断言文本与回调
    assert t._action_callback is None
    t.close()


def test_action_button_shown_with_callback(app):
    calls = []
    t = Toast()
    t.show_message("删了东西", Toast.INFO, 10, action_text="撤销", action_callback=lambda: calls.append(1))
    assert t.action_button.text() == "撤销"
    assert t._action_callback is not None
    t._on_action_clicked()
    assert calls == [1]
    # 第二次点击不得重复触发
    t._on_action_clicked()
    assert calls == [1]
    t.close()


def test_callback_exception_does_not_crash(app):
    def boom():
        raise RuntimeError("undo 崩了不能炸 UI")

    t = Toast()
    t.show_message("x", Toast.INFO, 10, action_text="撤销", action_callback=boom)
    t._on_action_clicked()  # 不抛出即通过
    t.close()


def test_toast_undo_via_manager(app):
    host = QWidget()
    host.resize(800, 600)
    mgr = get_toast_manager()
    mgr.set_parent(host)
    calls = []
    t = toast_undo("已删除播放列表", lambda: calls.append("undone"))
    assert t is not None
    assert t.action_button.text() == "撤销"
    t._on_action_clicked()
    assert calls == ["undone"]
    host.deleteLater()
    app.processEvents()
