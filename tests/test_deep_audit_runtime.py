# SPDX-License-Identifier: GPL-3.0-or-later
"""离线故障注入：退出、失败重试和后台任务结果。"""
import logging
import threading
from types import SimpleNamespace

import pytest


def test_audio_lru_does_not_stop_a_playing_sound():
    from collections import OrderedDict
    from core.audio.audio_manager import AudioManager
    stopped = []
    manager = AudioManager.__new__(AudioManager)
    manager._sounds = {"old": SimpleNamespace(sound=SimpleNamespace(stop=lambda: stopped.append(True)))}
    manager._access_order = OrderedDict(old=None)
    manager._evict_lru_locked()
    assert not manager._sounds and not stopped


@pytest.mark.parametrize("operation", ["_run_reload_audio", "_run_import_refresh"])
def test_audio_save_failure_is_a_failed_task(monkeypatch, operation):
    from core.audio import audio_task_runner as mod
    manager = SimpleNamespace(ensure_styles_scanned=lambda: None, load_all_enabled_sounds=lambda: None)
    monkeypatch.setattr(mod, "get_runtime_audio_manager", lambda: manager)
    monkeypatch.setattr(mod.config, "save_config_now", lambda: False)
    runner = mod.AudioTaskRunner()
    task = mod._Task("test", operation, "test", getattr(runner, operation))
    runner._execute_task(task)
    assert task.success is False and "保存失败" in task.message
    runner.stop()


def test_hud_failed_write_can_retry_same_color():
    from gsi_handler_hud_color import GSIHandlerHudColor
    handler = GSIHandlerHudColor.__new__(GSIHandlerHudColor)
    handler._write_lock = threading.Lock()
    handler._stopped = False
    handler.current_color = 1
    handler._last_write_time = 0
    handler._min_write_interval = .1
    results = iter([False, True])
    handler._write_runtime_cfg = lambda color: next(results)
    handler._maybe_write_color(5, 1)
    assert handler.current_color == 1
    handler._maybe_write_color(5, 2)
    assert handler.current_color == 5


def test_map_apply_failure_is_retried_after_backoff(monkeypatch):
    from core.presets import map_rules as mod
    monkeypatch.setattr(mod.config, "map_preset_enabled", True)
    monkeypatch.setattr(mod.config, "map_preset_rules", {"de_test": {"bundle": {}}})
    monkeypatch.setattr(mod, "validate_bundle", lambda b: SimpleNamespace(ok=True))
    values = iter([False, True])
    monkeypatch.setattr(mod, "apply_bundle", lambda *a, **k: SimpleNamespace(ok=next(values)))
    now = [1.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    applier = mod.MapPresetApplier()
    assert not applier.on_map("de_test")
    assert not applier.on_map("de_test")
    now[0] = 4.0
    assert applier.on_map("de_test")
    assert not applier.on_map("de_test")


def test_extra_shot_cleanup_cancels_and_blocks_late_callback(monkeypatch):
    import gsi_handler_sounds as mod
    handler = mod.GSIHandlerSounds.__new__(mod.GSIHandlerSounds)
    handler.logger = logging.getLogger("test")
    handler._extra_shot_lock = threading.RLock()
    handler._closed = False
    cancelled, played = [], []
    handler._pending_extra_shots = {"test": [SimpleNamespace(cancel=lambda: cancelled.append(True))]}
    handler._game_audio_ducker = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(mod, "is_gun_sound_master_enabled", lambda cfg: True)
    monkeypatch.setattr(mod, "SUPPORTED_GUN_SOUND_PROFILES", {"test": SimpleNamespace(style_key="audit_style")})
    monkeypatch.setattr(mod.config, "audit_style", "style", raising=False)
    monkeypatch.setattr(mod, "resolve_gun_sound_style", lambda s: s)
    monkeypatch.setattr(mod, "gun_sound_style_enabled", lambda s: True)
    monkeypatch.setattr(mod.audio_manager, "play_sound", lambda *a, **k: played.append(True))
    handler.cleanup()
    handler._play_extra_shot("test", "gun-test-style")
    assert cancelled == [True] and not played and not handler._pending_extra_shots


def test_music_cancel_keeps_owned_loader_without_joining_gui():
    from music_player import MusicPlayer
    player = MusicPlayer.__new__(MusicPlayer)
    cancelled = []
    def forbidden_join(*a, **k):
        raise AssertionError("GUI cancellation must not join a downloader")
    loader = SimpleNamespace(is_alive=lambda: True, cancel=lambda: cancelled.append(True), join=forbidden_join)
    player.loader_thread = loader
    player._debug_log = lambda _: None
    player.cancel_loading()
    assert cancelled == [True] and player.loader_thread is loader


def test_download_cancellation_closes_response_and_removes_partial(tmp_path, monkeypatch):
    mod = pytest.importorskip("url_resolver")
    resolver = mod.MusicURLResolver.__new__(mod.MusicURLResolver)
    resolver.cache_dir = str(tmp_path)
    resolver.headers = {}
    cancelled, closed = [False], []
    def chunks(**kwargs):
        yield b"ID3" + b"x" * 8192
        cancelled[0] = True
        yield b"y" * 8192
    response = SimpleNamespace(status_code=200, headers={}, raise_for_status=lambda: None,
                               iter_content=chunks, close=lambda: closed.append(True))
    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: response)
    assert resolver.download_to_cache("https://example.invalid/test.mp3", {"url": "https://example.invalid/test.mp3"},
                                      should_cancel=lambda: cancelled[0]) is None
    assert closed and not list(tmp_path.iterdir())


def test_background_failure_or_cancel_never_claims_all_ready(monkeypatch, qapp):
    import background_loader as mod
    def fail():
        raise OSError("injected resource failure")
    monkeypatch.setattr(mod.ResourceManager, "copy_resources_to_appdata", fail)
    loader = mod.BackgroundLoader(None, {})
    ready, errors = [], []
    loader.all_completed.connect(lambda: ready.append(True))
    loader.error_occurred.connect(lambda *args: errors.append(args))
    loader.run()
    assert errors and not ready
    loader.cancel()
    loader.run()
    assert not ready


def test_async_browser_cancel_cleans_late_launch(qapp, monkeypatch):
    from core.fun import afterlife as mod
    from test_afterlife_controller import _FakeBrowser, _Cfg
    controller = mod.AfterlifeController(_Cfg())
    browser = _FakeBrowser()
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    caller = threading.get_ident()
    identities = []
    finished = threading.Event()
    def launch(**kwargs):
        identities.append(threading.get_ident())
        entered.set()
        if not release.wait(3):
            return False
        browser.alive = True
        return True
    def close():
        browser.alive = False
        closed.set()
        if release.is_set():
            finished.set()
    monkeypatch.setattr(browser, "launch", launch)
    monkeypatch.setattr(browser, "close", close)
    monkeypatch.setattr(controller, "_build_browser", lambda: browser)
    monkeypatch.setattr(mod, "find_browser", lambda _: "fake")
    monkeypatch.setattr(mod, "find_game_window", lambda: 0)
    try:
        assert controller.preheat()
        assert entered.wait(2)
        controller.shutdown()
        release.set()
        assert closed.wait(2)
        assert finished.wait(2)
        qapp.processEvents()
        assert identities == [identities[0]] and identities[0] != caller
        assert controller.browser is None and not browser.alive
    finally:
        release.set()
        controller.shutdown()
