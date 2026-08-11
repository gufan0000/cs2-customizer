# -*- coding: utf-8 -*-
"""2.2.0 空闲预构建:按频次排队、专家页门控、同步驱动全部建成、幂等。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core import page_usage_tracker as put


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def usage():
    put.reset()
    for _ in range(5):
        put.record_page_open("music")
    for _ in range(3):
        put.record_page_open("crosshair")
    yield
    put.reset()


def _drain(win):
    """同步驱动预构建队列(绕过 QTimer 间隔)。"""
    guard = 0
    while getattr(win, "_idle_preload_queue", None) and guard < 10:
        win._preload_next_page()
        guard += 1


def test_preload_builds_frequent_pages(app, usage):
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.start_idle_preload()
        # 2.2.0 卡顿治理:music 构造即起线程,在 _preload_skip_pages,
        # 即使频次第一也不许进静默预载队列
        assert "music" not in win._idle_preload_queue
        assert "crosshair" in win._idle_preload_queue
        _drain(win)
        assert win.is_page_loaded("crosshair")
        assert not win.is_page_loaded("music")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_preload_idempotent_and_skips_loaded(app, usage):
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.show_page("music", animated=False)  # 已加载页不应进队列
        win.start_idle_preload()
        assert "music" not in win._idle_preload_queue
        queue_first = list(win._idle_preload_queue)
        win.start_idle_preload()  # 二次调用幂等
        assert win._idle_preload_queue == queue_first
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_preload_respects_expert_gate(app):
    put.reset()
    for _ in range(9):
        put.record_page_open("preset_center")  # 专家页
    import gui_widget
    from config import config

    old = getattr(config, "ui_expert_mode", False)
    config.ui_expert_mode = False
    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.start_idle_preload()
        assert "preset_center" not in win._idle_preload_queue
    finally:
        config.ui_expert_mode = old
        win.close()
        win.deleteLater()
        app.processEvents()
        put.reset()
