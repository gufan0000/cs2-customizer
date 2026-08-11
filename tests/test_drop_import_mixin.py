# -*- coding: utf-8 -*-
"""R1-8 通用拖拽导入:扩展名过滤、回调、防 GC 强引用。

用 duck-type 假事件而非手工构造 QDropEvent:PySide6 事件构造器跨版本签名不稳,
我们要测的是过滤/分发逻辑,不是 Qt 的事件机制本身。
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QMimeData, QUrl
from PySide6.QtWidgets import QApplication, QWidget

from widgets.drop_import_mixin import enable_file_drop


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _FakeEvent:
    def __init__(self, paths, etype=QEvent.Type.Drop):
        self._etype = etype
        self._mime = QMimeData()
        self._mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        self.accepted = False

    def type(self):
        return self._etype

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True


def test_drop_filters_by_extension_and_calls_handler(app, tmp_path):
    received = []
    w = QWidget()
    filt = enable_file_drop(w, (".xchr",), received.extend)
    assert w.acceptDrops()

    good = str(tmp_path / "a.xchr")
    bad = str(tmp_path / "b.exe")
    event = _FakeEvent([good, bad])
    handled = filt.eventFilter(w, event)
    assert handled is True
    assert event.accepted is True
    assert len(received) == 1
    assert received[0].lower().endswith(".xchr")


def test_drag_enter_accepts_matching(app, tmp_path):
    w = QWidget()
    filt = enable_file_drop(w, (".json",), lambda p: None)
    event = _FakeEvent([str(tmp_path / "x.json")], etype=QEvent.Type.DragEnter)
    assert filt.eventFilter(w, event) is True
    assert event.accepted is True


def test_drop_with_no_matching_files_not_handled(app, tmp_path):
    received = []
    w = QWidget()
    filt = enable_file_drop(w, (".xchr",), received.extend)
    event = _FakeEvent([str(tmp_path / "b.exe")])
    handled = filt.eventFilter(w, event)
    assert handled is False
    assert received == []


def test_handler_exception_swallowed(app, tmp_path):
    def boom(paths):
        raise RuntimeError("handler 崩了不能炸 UI")

    w = QWidget()
    filt = enable_file_drop(w, (".xchr",), boom)
    event = _FakeEvent([str(tmp_path / "a.xchr")])
    assert filt.eventFilter(w, event) is True


def test_multiple_filters_keep_strong_refs(app):
    w = QWidget()
    enable_file_drop(w, (".a",), lambda p: None)
    enable_file_drop(w, (".b",), lambda p: None)
    assert len(w._file_drop_filters) == 2


def test_crosshair_page_has_drop_enabled(app):
    from pages.crosshair_page import CrosshairPage

    page = CrosshairPage()
    try:
        assert page.acceptDrops()
        assert getattr(page, "_file_drop_filters", None)
    finally:
        page.deleteLater()
        app.processEvents()
