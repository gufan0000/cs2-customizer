# SPDX-License-Identifier: GPL-3.0-or-later
"""A real flash edge must start audio even when image rotation is disabled."""
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("rotation", ["none", "sequence"])
def test_flash_audio_does_not_require_image_rotation(monkeypatch, rotation):
    import flash_process_manager as mod

    monkeypatch.setattr(mod, "_game_monitor_device", lambda: "test-monitor")
    manager = mod.FlashProcessManager.__new__(mod.FlashProcessManager)
    manager.is_running = True
    manager.command_queue = Queue()
    manager.config = SimpleNamespace(flash_image_rotation=rotation)
    manager.current_flash_value = 0
    manager.audio_enabled = True
    manager.audio_style = "configured"
    manager.audio_auto_stop = True
    manager._clear_pending_flash_updates = lambda: {}
    manager._rotate_flash_image = Mock()
    manager.play_audio = Mock()
    manager.stop_audio = Mock()

    assert manager.update_flash_value(100)
    manager.play_audio.assert_called_once_with()
    assert manager._rotate_flash_image.call_count == (rotation != "none")
    assert manager.update_flash_value(80)
    manager.play_audio.assert_called_once_with()
    assert manager.update_flash_value(0)
    manager.stop_audio.assert_called_once_with()
    assert manager.command_queue.get_nowait()["monitor"] == "test-monitor"


@pytest.mark.parametrize("enabled,style", [(False, "configured"), (True, "none")])
def test_disabled_flash_audio_does_not_start(monkeypatch, enabled, style):
    import flash_process_manager as mod

    monkeypatch.setattr(mod, "_game_monitor_device", lambda: "test-monitor")
    manager = mod.FlashProcessManager.__new__(mod.FlashProcessManager)
    manager.is_running = True
    manager.command_queue = Queue()
    manager.config = SimpleNamespace(flash_image_rotation="none")
    manager.current_flash_value = 0
    manager.audio_enabled, manager.audio_style = enabled, style
    manager.audio_auto_stop = False
    manager._clear_pending_flash_updates = lambda: {}
    manager.play_audio = Mock()
    assert manager.update_flash_value(100)
    manager.play_audio.assert_not_called()
