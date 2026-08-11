# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""空闲侦测器回归测试（UP-005 / D-12）。

静默预载靠它判断"现在能不能干后台活"。它出错的后果是两极的：
- 判太松 → 用户操作时照样插一页进来，卡顿治理白做；
- 判太紧 → 空闲队列永远推不动，冷页永远要走骨架屏。
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

import core.utils.idle_watcher as iw


@pytest.fixture(autouse=True)
def _reset_singleton():
    inst = iw._instance
    if inst is not None:
        try:
            QApplication.instance().removeEventFilter(inst)
        except Exception:
            pass
    iw._instance = None
    yield
    inst = iw._instance
    if inst is not None:
        try:
            QApplication.instance().removeEventFilter(inst)
        except Exception:
            pass
    iw._instance = None


def _app():
    return QApplication.instance() or QApplication([])


def test_start_is_idempotent():
    app = _app()
    a = iw.start_idle_watcher(app)
    b = iw.start_idle_watcher(app)
    assert a is b
    assert iw.get_idle_watcher() is a


def test_get_returns_none_before_start():
    assert iw.get_idle_watcher() is None


def test_idle_grows_over_time(monkeypatch):
    w = iw.start_idle_watcher(_app())
    monkeypatch.setattr(w, "is_app_active", lambda: True)  # 只测输入时间维度
    w._last_input = time.perf_counter() - 30.0
    assert w.seconds_since_input() >= 30.0
    assert w.is_idle(10.0)
    assert not w.is_idle(60.0)


def test_key_event_resets_idle(monkeypatch):
    app = _app()
    w = iw.start_idle_watcher(app)
    monkeypatch.setattr(w, "is_app_active", lambda: True)
    w._last_input = time.perf_counter() - 30.0
    assert w.is_idle(10.0)

    target = QWidget()
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a")
    app.sendEvent(target, ev)

    assert not w.is_idle(10.0), "按键后应当立刻不再算空闲"
    assert w.seconds_since_input() < 1.0


def test_mouse_event_resets_idle(monkeypatch):
    app = _app()
    w = iw.start_idle_watcher(app)
    monkeypatch.setattr(w, "is_app_active", lambda: True)
    w._last_input = time.perf_counter() - 30.0

    target = QWidget()
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPoint(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(target, ev)

    assert not w.is_idle(10.0)


def test_non_input_event_does_not_reset(monkeypatch):
    """非输入事件（如重绘）不该被当成用户在操作，否则空闲队列永远推不动。"""
    app = _app()
    w = iw.start_idle_watcher(app)
    monkeypatch.setattr(w, "is_app_active", lambda: True)
    w._last_input = time.perf_counter() - 30.0

    target = QWidget()
    app.sendEvent(target, QEvent(QEvent.Type.UpdateRequest))

    assert w.is_idle(10.0), "重绘事件不应重置空闲计时"


def test_filter_never_swallows_events():
    """事件过滤器绝不能吞事件——吞了会让整个界面失去响应。"""
    app = _app()
    w = iw.start_idle_watcher(app)
    target = QWidget()
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_B, Qt.KeyboardModifier.NoModifier, "b")
    assert w.eventFilter(target, ev) is False


def test_note_input_marks_activity(monkeypatch):
    w = iw.start_idle_watcher(_app())
    monkeypatch.setattr(w, "is_app_active", lambda: True)
    w._last_input = time.perf_counter() - 30.0
    w.note_input()
    assert not w.is_idle(10.0)


# ==================== 应用未激活时不算空闲 ====================

def test_not_idle_when_app_inactive(monkeypatch):
    """用户 Alt-Tab 进 CS2 打比赛时，本应用收不到输入"看起来"很空闲，
    但那恰恰是最不该抢 CPU 的时刻——必须挡掉。"""
    w = iw.start_idle_watcher(_app())
    w._last_input = time.perf_counter() - 3600.0  # 一小时没输入

    monkeypatch.setattr(w, "is_app_active", lambda: False)
    assert not w.is_idle(10.0), "应用不在前台时不许认为空闲"

    monkeypatch.setattr(w, "is_app_active", lambda: True)
    assert w.is_idle(10.0), "应用在前台且久无输入时应当算空闲"


def test_is_app_active_is_defensive(monkeypatch):
    """取不到应用状态时应当返回 False（保守：宁可不干后台活）。"""
    w = iw.start_idle_watcher(_app())
    monkeypatch.setattr(
        "PySide6.QtWidgets.QApplication.instance", staticmethod(lambda: None)
    )
    assert w.is_app_active() is False
