# SPDX-License-Identifier: GPL-3.0-or-later
"""10-31 验收：配置重载屏蔽信号之后，标签、运行时和待播图标不能掉队。"""
import time
from types import SimpleNamespace

import pytest


@pytest.fixture
def no_disk_writes(monkeypatch):
    from config import config
    monkeypatch.setattr(config, "save_config", lambda *a, **k: None)
    return config


def test_blocking_controls_leaves_qt_internals_working(qapp):
    from PySide6.QtWidgets import QComboBox, QLabel, QTabWidget, QWidget
    from widgets.config_reload import block_control_signals
    page = QWidget()
    combo = QComboBox(page)
    tabs = QTabWidget(page)
    tabs.addTab(QLabel("one"), "1")
    tabs.addTab(QLabel("two"), "2")
    with block_control_signals(page):
        combo.addItems(["p", "q"])
        tabs.setCurrentIndex(1)
    assert combo.currentIndex() == 0 and combo.currentText() == "p"
    assert tabs.currentWidget().text() == "two"
    page.deleteLater()


def test_viewmodel_labels_and_auto_switch_follow_a_reload(qapp, no_disk_writes, monkeypatch):
    import copy
    from pages.viewmodel_page import ViewmodelPage
    from widgets.config_reload import reload_page_settings
    config = no_disk_writes
    page = ViewmodelPage()
    calls = []
    monkeypatch.setattr(page, "_start_auto_switch", lambda: calls.append("start"))
    monkeypatch.setattr(page, "_stop_auto_switch", lambda: calls.append("stop"))
    monkeypatch.setattr(config, "viewmodel_presets", copy.deepcopy(config.viewmodel_presets))
    monkeypatch.setattr(config, "viewmodel_auto_switch_enabled", True)
    config.viewmodel_presets[0].update(fov=60, x=1.5, y=-0.5, z=0.5)
    try:
        assert reload_page_settings(page)
        preset = page.preset_vars[0]
        shown = [preset[f"{name}_label"].text() for name in ("fov", "x", "y", "z")]
        assert shown == ["60", "1.5", "-0.5", "0.5"]
        assert calls == ["start"]
    finally:
        page.deleteLater()


def test_flash_page_refreshes_labels_controls_and_running_process(qapp, no_disk_writes, monkeypatch):
    from pages.flash_page import FlashPage
    from widgets.config_reload import reload_page_settings
    config = no_disk_writes
    page = FlashPage()
    synced = []
    monkeypatch.setattr(page.process_manager, "sync_from_config", lambda: synced.append(True))
    monkeypatch.setattr(config, "flash_max_opacity", 0.33)
    monkeypatch.setattr(config, "flash_audio_enabled", False)
    monkeypatch.setattr(config, "flash_style", "blur")
    shown = []
    monkeypatch.setattr(page, "_show_style_params", shown.append)
    try:
        assert reload_page_settings(page)
        assert page.opacity_label.text() == "33%"
        assert not page.audio_volume_slider.isEnabled() and not page.audio_preview_btn.isEnabled()
        assert shown[-1] == "模糊" and synced == [True]
    finally:
        page.deleteLater()


def test_flash_manager_takes_the_restored_values_without_saving(no_disk_writes, monkeypatch):
    from flash_process_manager import FlashProcessManager
    config = no_disk_writes
    manager = FlashProcessManager.__new__(FlashProcessManager)
    manager.config = config
    sent = {}
    manager.update_settings = lambda **values: sent.update(values)
    manager.update_fade_settings = lambda *values: sent.update(fade=values)
    manager.update_flash_style = lambda style: sent.update(style=style)
    manager.update_style_parameters = lambda params: sent.update(params=params)
    manager.update_image_rotation = lambda mode: sent.update(rotation=mode)
    manager._style_parameters_for = lambda style: {"for": style}
    manager.load_flash_image = lambda style: sent.update(image=style)
    manager.update_audio_enabled = lambda on: sent.update(audio=on)
    manager.update_audio_style = lambda style: sent.update(audio_style=style)
    manager.update_audio_volume = lambda volume: sent.update(volume=volume)
    manager.update_auto_stop_setting = lambda on: sent.update(auto_stop=on)
    manager.audio_style = "旧风格"
    manager._pending_flash_image_style = "旧图"
    monkeypatch.setattr(config, "flash_bg_color", "red")
    monkeypatch.setattr(config, "flash_max_opacity", 0.33)
    monkeypatch.setattr(config, "flash_style", "blur")
    monkeypatch.setattr(config, "flash_image_style", "新图")
    monkeypatch.setattr(config, "flash_audio_style", "新风格")
    manager.sync_from_config()
    assert sent["bg_color"] == "red" and sent["max_opacity"] == 0.33
    assert sent["style"] == "blur" and sent["params"] == {"for": "blur"}
    assert sent["image"] == "新图" and sent["audio_style"] == "新风格"


def _player(playlist, name="A"):
    from music_player import MusicPlayer
    player = MusicPlayer.__new__(MusicPlayer)
    player.current_playlist_name = name
    player.playlist = playlist
    player.current_index = 0
    player.stops = []
    player.stop = lambda: player.stops.append(True)
    return player


def test_music_player_follows_the_restored_playlist(monkeypatch):
    from config import config
    monkeypatch.setattr(config, "music_playlists", {"A": [{"path": "a"}], "B": [{"path": "b"}]})
    monkeypatch.setattr(config, "music_current_playlist", "B")
    monkeypatch.setattr(config, "music_current_index", 0)
    player = _player([{"path": "a"}])
    player.sync_from_config()
    assert player.current_playlist_name == "B" and player.playlist == [{"path": "b"}]
    assert player.stops == [True] and player.current_index == 0


def test_music_player_keeps_playing_when_the_playlist_did_not_change(monkeypatch):
    from config import config
    monkeypatch.setattr(config, "music_playlists", {"A": [{"path": "a"}]})
    monkeypatch.setattr(config, "music_current_playlist", "A")
    player = _player([{"path": "a"}])
    player.sync_from_config()
    assert player.stops == []


def test_music_page_syncs_the_player_after_a_reload():
    from pages.music_page import MusicPage
    calls = []
    page = SimpleNamespace(
        selected_indices={1},
        player=SimpleNamespace(sync_from_config=lambda: calls.append("player")),
        refresh_playlist_display=lambda: calls.append("list"),
        _sync_overview_status=lambda: calls.append("overview"),
    )
    MusicPage.sync_after_config_reload(page)
    assert calls == ["player", "list", "overview"] and page.selected_indices == set()


def _loader_player(track_type, monkeypatch):
    import threading

    import music_player as mod
    player = mod.MusicPlayer.__new__(mod.MusicPlayer)
    player._transition_lock = threading.RLock()
    player._transition_generation = 1
    player.loader_thread = SimpleNamespace(is_alive=lambda: True)
    player.retries = []
    player._schedule_transition = lambda *a, **k: player.retries.append(a)
    started = []

    class FakeLoader:
        def __init__(self, owner, track):
            self.track = track

        def start(self):
            started.append(self.track)

    monkeypatch.setattr(mod, "MusicLoaderThread", FakeLoader)
    player._start_loader_when_ready({"type": track_type, "path": "x"}, 1)
    return player, started


def test_local_track_does_not_wait_for_a_cancelled_download(monkeypatch):
    player, started = _loader_player("local", monkeypatch)
    assert len(started) == 1 and not player.retries


def test_network_track_still_waits_for_the_old_download(monkeypatch):
    player, started = _loader_player("url", monkeypatch)
    assert not started and len(player.retries) == 1


def _icon_player():
    import kill_icon_player as mod
    player = mod.KillIconPlayer()
    player.current_style = "甲"
    player.played = []
    return player


def _deliver(player, style="甲"):
    original = player._handle_play
    player._handle_play = lambda *args: player.played.append(args)
    try:
        player._handle_assets_ready(style, player._load_token, {})
    finally:
        player._handle_play = original


def test_kill_during_load_is_replayed_while_it_is_still_fresh(qapp):
    player = _icon_player()
    player._pending_play = (1, "", -1, "甲", time.monotonic(), False)
    _deliver(player)
    assert player.played == [(1, "", -1, False)]
    player.deleteLater()


def test_stale_kill_is_not_replayed(qapp):
    player = _icon_player()
    player._pending_play = (1, "", -1, "甲", time.monotonic() - 30, False)
    _deliver(player)
    assert not player.played
    player.deleteLater()


def test_kill_from_another_style_is_not_replayed(qapp):
    player = _icon_player()
    player._pending_play = (1, "", -1, "乙", time.monotonic(), False)
    _deliver(player)
    assert not player.played
    player.deleteLater()


def test_switching_style_forgets_the_pending_kill(qapp, monkeypatch):
    player = _icon_player()
    monkeypatch.setattr(player, "_start_load", lambda style: None)
    player._pending_play = (1, "", -1, "甲", time.monotonic(), False)
    player.load_style("乙")
    assert player._pending_play is None
    player.deleteLater()


def test_kill_right_after_the_worker_exits_is_still_registered(qapp, monkeypatch):
    from config import config
    player = _icon_player()
    monkeypatch.setattr(config, "kill_icon_enabled", True)
    monkeypatch.setattr(player, "_start_load", lambda style: None)
    player._loading_thread = None          # 线程已退出，结果信号还在排队
    player._handle_play(2, "", -1)
    assert player._pending_play[:4] == (2, "", -1, "甲")
    player.deleteLater()


def test_preview_with_the_master_switch_off_survives_a_cold_cache(qapp, monkeypatch):
    from config import config
    player = _icon_player()
    monkeypatch.setattr(config, "kill_icon_enabled", False)
    monkeypatch.setattr(player, "_start_load", lambda style: None)
    player.preview_position_and_scale(1, 3)
    assert player._pending_play[-1] is True
    assert config.kill_icon_enabled is False
    player._handle_play(1, "", -1)          # 普通击杀仍被总开关拦下
    assert player._pending_play[-1] is True
    player.deleteLater()
