# SPDX-License-Identifier: GPL-3.0-or-later
"""P2 behavior: no hidden preview ticks or GSI disk waits."""
from __future__ import annotations

import threading
from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget


def _wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_hidden_preview_sleeps_and_resumes_without_restarting(qapp):
    from widgets.kill_icon_preview import KillIconPreview
    parent = QWidget()
    widget = KillIconPreview(parent)
    frame = QImage(16, 16, QImage.Format_ARGB32)
    frame.fill(0xffabcdef)
    animation = SimpleNamespace(frames=(frame,) * 40, frame_width=16, frame_height=16, fps=30)
    try:
        widget.set_animation(animation)
        assert not widget._timer.isActive()  # installed while the page is hidden
        parent.show()
        _wait(80)
        assert widget._elapsed > 0
        parent.hide()
        elapsed, index = widget._elapsed, widget._index
        ticks = []
        widget._timer.timeout.connect(lambda: ticks.append(True))
        _wait(80)
        assert not ticks
        assert (widget._elapsed, widget._index) == (elapsed, index)
        widget.set_fps(20)
        assert not widget._timer.isActive()
        parent.show()
        _wait(50)
        assert ticks and widget._timer.isActive()
        widget.stop()
        parent.hide()
        parent.show()
        assert not widget._timer.isActive()  # explicit stop survives visibility changes
        widget.set_animation(None)
        parent.hide()
        parent.show()
        assert not widget._timer.isActive()
    finally:
        widget.stop()
        parent.close()


def test_hud_callback_never_waits_for_cfg_and_keeps_all_colors(monkeypatch):
    import gsi_handler_hud_color as mod
    from core.hud.rule_model import get_default_hud_rules
    monkeypatch.setattr(mod.config, "hud_rules_enabled", True)
    monkeypatch.setattr(mod.config, "hud_runtime_sync_mode", "safe")
    monkeypatch.setattr(mod.config, "hud_rules", get_default_hud_rules("balanced_default"))
    handler = mod.GSIHandlerHudColor()
    handler._refresh_rules_if_needed = lambda: None
    handler.engine.evaluate = lambda data, now: SimpleNamespace(color=data["color"])
    handler._min_write_interval = 0
    handler._get_cfg_path = lambda: None
    entered, release = threading.Event(), threading.Event()
    writes = []
    def write(color):
        entered.set()
        assert release.wait(3)
        writes.append(color)
        return True
    handler._write_runtime_cfg = write
    returned = threading.Event()
    def receive():
        for color in (1, 2, 3, 2):
            handler.process_data({"color": color})
        returned.set()
    receiver = threading.Thread(target=receive)
    try:
        receiver.start()
        assert entered.wait(1)
        # Synchronization assertion, not a sub-ms timing budget: disk is blocked.
        assert returned.wait(.5), "GSI callback waited for filesystem I/O"
        assert not writes
    finally:
        release.set()
        receiver.join(3)
        if hasattr(handler, "_color_queue"):
            handler._color_queue.join()
        handler.stop()
    assert writes == [1, 2, 3, 2]
    handler.process_data({"color": 4})
    assert writes == [1, 2, 3, 2]


def test_hud_stop_waits_for_inflight_write_before_restoring(monkeypatch):
    import gsi_handler_hud_color as mod
    handler = mod.GSIHandlerHudColor()
    handler._get_cfg_path = lambda: "synthetic.cfg"
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    writes = []
    def write(color):
        entered.set()
        assert release.wait(3)
        writes.append(color)
        return True
    handler._write_runtime_cfg = write
    monkeypatch.setattr(mod, "write_runtime_cfg", lambda *args: writes.append("restore"))
    def stop():
        handler.stop()
        stopped.set()
    worker = threading.Thread(target=stop)
    try:
        handler._queue_color(5, 1)
        assert entered.wait(1)
        worker.start()
        assert not stopped.wait(.05)
    finally:
        release.set()
        worker.join(3)
        handler.stop()
    assert stopped.is_set()
    assert writes[:2] == [5, "restore"]
    assert all(value == "restore" for value in writes[2:])
    assert handler._color_writer is None


def test_hud_worker_writes_exact_cfg_and_retries_failure(monkeypatch, tmp_path):
    import gsi_handler_hud_color as mod
    handler = mod.GSIHandlerHudColor()
    destination = tmp_path / "runtime.cfg"
    handler._get_cfg_path = lambda: str(destination)
    real_write = handler._write_runtime_cfg
    attempts = []
    def write(color):
        attempts.append(color)
        return False if len(attempts) == 1 else real_write(color)
    handler._write_runtime_cfg = write
    try:
        handler._queue_color(5, 1)
        handler._color_queue.join()
        assert handler.current_color == -1
        handler._queue_color(5, 2)
        handler._color_queue.join()
        assert handler.current_color == 5
        assert destination.read_text(encoding="utf-8") == "cl_hud_color 5\n"
        handler._queue_color(5, 3)
        handler._queue_color(2, 2.01)  # same 50ms rate limit as synchronous writes
        handler._color_queue.join()
        assert attempts == [5, 5]
    finally:
        handler.stop()
