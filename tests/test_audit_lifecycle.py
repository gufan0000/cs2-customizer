# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic cancellation and device-failure tests; no real devices."""
import threading
import time
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest


def test_stale_kills_advance_state_without_replay(monkeypatch):
    from tests.test_kill_sound_loss_fixes import _DummyAudioManager, _payload
    import gsi_handler_kills as mod
    from config import config
    audio = _DummyAudioManager()
    monkeypatch.setattr(mod, "audio_manager", audio)
    for key, value in dict(kill_sound_enabled=True, kill_voice_enabled=False,
                           kill_icon_enabled=False, spectator_mode_mute=False,
                           mode="1. 官匹竞技", player_steamid="test_steamid").items():
        monkeypatch.setattr(config, key, value)
    handler = mod.GSIHandlerKills()
    handler._get_weapon_kill_sound_key = lambda weapon, level, hs=False: f"kill-{level}"
    for count in (3, 4):
        packet = _payload(5, count, match_kills=count)
        packet["_cs2customizer_recv_monotonic"] = time.monotonic() - 10
        handler.process_data(packet)
    assert not audio.play_sound_calls
    handler.process_data(_payload(5, 5, match_kills=5))
    assert audio.play_sound_calls == [("kill-5", "kill_sound")]


def test_dispatch_stops_before_next_handler():
    from gsi_server import GSIServer
    server = GSIServer()
    server.data_queue = Queue()
    entered, release = threading.Event(), threading.Event()
    later = Mock()
    server.handlers = [SimpleNamespace(process_data=lambda data: (entered.set(), release.wait(3))), later]
    worker = threading.Thread(target=server.process_data)
    worker.start()
    server.data_queue.put({})
    try:
        assert entered.wait(2)
        stopper = threading.Thread(target=server.stop)
        stopper.start()
        assert server._stop_event.wait(2)
        release.set()
        stopper.join(3)
        worker.join(3)
        assert not worker.is_alive()
        later.process_data.assert_not_called()
    finally:
        release.set()
        server.stop()
        worker.join(3)


def test_hud_dynamic_write_cannot_follow_restore(monkeypatch):
    import gsi_handler_hud_color as mod
    writes = []
    handler = mod.GSIHandlerHudColor()
    handler._get_cfg_path = lambda: "synthetic.cfg"
    monkeypatch.setattr(mod, "write_runtime_cfg", lambda *a: writes.append("restore"))
    handler._write_runtime_cfg = lambda *a: writes.append("dynamic")
    handler.stop()
    handler._maybe_write_color(2, time.time())
    handler._ensure_effect_timer()
    assert writes == ["restore"]
    assert handler._effect_timer is None


@pytest.mark.parametrize("cancel", ["_handle_respawn", "shutdown", "retract_now"])
def test_pending_death_callback_is_cancelled(qapp, cancel):
    from core.fun.afterlife import AfterlifeController
    cfg = SimpleNamespace(fun_afterlife_enabled=True, fun_afterlife_delay_ms=800)
    ctl = AfterlifeController(cfg)
    ctl.preheat = Mock(return_value=True)
    ctl._handle_death()
    getattr(ctl, cancel)()
    ctl._show_now()  # emulate an already-queued timeout
    ctl.preheat.assert_not_called()
    assert not ctl._show_timer.isActive()


def test_music_old_transition_and_loader_cannot_restart_after_stop(monkeypatch):
    import music_player as mod
    player = mod.MusicPlayer.__new__(mod.MusicPlayer)
    player._debug_log = lambda *a: None
    player.on_state_change = None
    player._cancel_transition()
    pending = []
    class Timer:
        def __init__(self, delay, callback): self.callback = callback
        def start(self): pending.append(self)
        def cancel(self): pass
    monkeypatch.setattr(mod.threading, "Timer", Timer)
    monkeypatch.setattr(mod.pygame.mixer.music, "stop", lambda: None)
    played = Mock()
    player._schedule_transition(0.2, played)
    player.stop()
    pending[0].callback()
    played.assert_not_called()
    loader = Mock(is_cancelled=False, generation=player._transition_generation - 1)
    player.loader_thread = loader
    player._deliver_loader_result(loader, played)
    played.assert_not_called()


@pytest.mark.parametrize("phase", ["load", "channel", "play"])
def test_flash_disable_during_start_leaves_no_loop(monkeypatch, phase):
    import pygame
    from flash_process_manager import FlashProcessManager
    manager = FlashProcessManager.__new__(FlashProcessManager)
    manager._audio_lock = threading.RLock()
    manager._audio_generation = 0
    manager.audio_enabled = True
    manager.audio_style = "synthetic"
    manager.audio_auto_stop = False
    manager.audio_volume = 0.3
    manager.audio_playing = False
    manager.audio_channel = None
    manager._select_audio_file = lambda: "synthetic.wav"
    busy = [False]
    channel = Mock(get_busy=lambda: busy[0], stop=lambda: busy.__setitem__(0, False))
    def make_sound(path):
        if phase == "load":
            manager.update_audio_enabled(False)
        return Mock()
    def make_channel(index):
        if phase == "channel":
            manager.update_audio_enabled(False)
        return channel
    def play(*a, **kw):
        busy[0] = True
        if phase == "play":
            manager.update_audio_enabled(False)
    channel.play.side_effect = play
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: True)
    monkeypatch.setattr(pygame.mixer, "get_num_channels", lambda: 18)
    monkeypatch.setattr(pygame.mixer, "Sound", make_sound)
    monkeypatch.setattr(pygame.mixer, "Channel", make_channel)
    manager.play_audio()
    assert not busy[0] and not manager.audio_playing


@pytest.mark.parametrize("failed", ["stop", "close"])
def test_voice_cleanup_releases_mute_when_device_removed(monkeypatch, failed):
    import voice_output_manager as mod
    manager = mod.VoiceOutputManager.__new__(mod.VoiceOutputManager)
    manager.microphone_passthrough_active = True
    manager.vb_cable_rate = 48000
    manager.vb_cable_device_id = -1
    manager.chunk_size = 1024
    manager.latency = "low"
    manager.logger = Mock()
    manager._acquire_mic_mute = Mock()
    manager._release_mic_mute = Mock()
    stream = Mock()
    getattr(stream, failed).side_effect = RuntimeError("device removed")
    monkeypatch.setattr(mod.sd, "query_devices", lambda d: {"max_output_channels": 2})
    monkeypatch.setattr(mod.sd, "OutputStream", lambda **kw: stream)
    manager._play_file_data(np.zeros((0, 2), dtype="float32"), 48000, False, auto_mode=True)
    stream.stop.assert_called_once()
    stream.close.assert_called_once()
    manager._release_mic_mute.assert_called_once()
