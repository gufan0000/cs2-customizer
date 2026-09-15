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
    # ⚠⚠ 这一行原本以 `or True` 结尾 —— **它一个字都没有在断言**（批 74 的
    #   AST 普查逮到，147 条碰可见性的断言里它是唯一一条）。作者的顾虑是真的
    #   （「offscreen 下 visible 语义不稳」），但答案不是短路掉它：
    #   ⭐ `isVisibleTo(t)` 问的是「若祖先显示出来它会不会露脸」，
    #     **不需要真的显示**，offscreen 下语义是稳的。
    assert not t.action_button.isVisibleTo(t), (
        "没给回调的普通 toast，撤销按钮却会露脸")
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
