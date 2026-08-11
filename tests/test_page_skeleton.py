# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R1-5 首次切页骨架屏:单例复用、切页路径不破、重入保护。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    import gui_widget

    w = gui_widget.MainWindow(auto_background_preload=False)
    yield w
    w.close()
    w.deleteLater()
    app.processEvents()


def test_skeleton_lazy_singleton(win):
    s1 = win._get_page_skeleton()
    s2 = win._get_page_skeleton()
    assert s1 is s2
    assert win.content_stack.indexOf(s1) >= 0


def test_first_visit_uses_skeleton_then_lands_on_page(win):
    # 选一个默认未加载、且非专家模式门控的页
    target = "about"
    if win.is_page_loaded(target):
        pytest.skip("目标页已被预加载,换环境再测")
    win.show_page(target, animated=False)
    assert win.is_page_loaded(target)
    assert win.content_stack.currentWidget() is win.pages[target]


def test_second_visit_skips_loading_path(win):
    target = "about"
    assert win.is_page_loaded(target)
    win.show_page("basic", animated=False)
    win.show_page(target, animated=False)
    assert win.content_stack.currentWidget() is win.pages[target]


def test_reentrancy_guard_flag_resets(win):
    assert getattr(win, "_page_loading", False) is False
