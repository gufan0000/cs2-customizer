# SPDX-License-Identifier: GPL-3.0-or-later
"""批 142：改图标缩放时旧缓存和新缓存同时占内存，默认风格（519 帧）进程树峰值 1234MB。"""

from __future__ import annotations

import weakref


def test_icon_reload_releases_inactive_pixels_before_allocating_replacement(monkeypatch):
    import kill_icon_player as module
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])

    class Pixels:
        pass

    player = module.KillIconPlayer()
    current, inactive = Pixels(), Pixels()
    current_ref, inactive_ref = weakref.ref(current), weakref.ref(inactive)
    player._scaled = {(1, ""): (current,), (5, ""): (inactive,)}
    player._current_frames = (current,)
    player._catalog_style = "old"
    del current, inactive
    allocations = []

    class Thread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            # 开始解码新缓存的那一刻：不当前的旧像素已释放，正在播的还活着
            allocations.append(True)
            assert inactive_ref() is None
            assert current_ref() is player._current_frames[0]
            assert player._catalog_style is None

    monkeypatch.setattr(module.threading, "Thread", Thread)
    try:
        player._start_load("new")
        assert allocations
        player._handle_stop()
        assert current_ref() is None
    finally:
        player.cleanup()
