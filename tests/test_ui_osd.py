# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R2-3 OSD:单例、开关门控、跨线程 notify 不炸、角落定位合法。"""
import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from config import config
from ui_osd import OsdNotifier, notify_osd


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def osd_on():
    old = getattr(config, "osd_enabled", True)
    config.osd_enabled = True
    yield
    config.osd_enabled = old


def test_singleton(app):
    assert OsdNotifier.instance() is OsdNotifier.instance()


def test_notify_shows_window(app):
    notify_osd("测试提示")
    app.processEvents()
    inst = OsdNotifier.instance()
    assert inst._window is not None
    assert inst._window.label.text() == "测试提示"


def test_disabled_switch_blocks(app):
    config.osd_enabled = False
    inst = OsdNotifier.instance()
    before = inst._window.label.text() if inst._window else None
    notify_osd("不该显示")
    app.processEvents()
    after = inst._window.label.text() if inst._window else None
    assert after == before


def test_notify_from_worker_thread_safe(app):
    done = threading.Event()

    def worker():
        notify_osd("线程消息")
        done.set()

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)
    assert done.is_set()
    app.processEvents()  # queued signal 在主线程消化
    assert OsdNotifier.instance()._window.label.text() == "线程消息"


def test_long_text_truncated(app):
    notify_osd("x" * 200)
    app.processEvents()
    assert len(OsdNotifier.instance()._window.label.text()) <= 60


def test_invalid_corner_falls_back(app):
    config.osd_corner = "middle_of_nowhere"
    notify_osd("位置回退")
    app.processEvents()  # 不抛异常即通过(show_text 内部回退 bottom_right)
    config.osd_corner = "bottom_right"
