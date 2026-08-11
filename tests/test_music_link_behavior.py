from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

import gsi_handler_music
import music_control_bar as music_control_bar_module
import music_player
import pages.music_page as music_page_module
from config import config


def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _DummyPlayer:
    def __init__(self):
        self.is_playing = True
        self.is_paused = False
        self.current_track = {"path": "demo.mp3"}
        self.current_index = -1
        self.current_playlist_name = "默认"
        self.on_playlist_update = None
        self.on_playlist_change = None
        self.on_track_change = None
        self.on_state_change = None
        self.fade_calls: list[tuple[float, float, object]] = []
        self.set_volume_calls: list[tuple[float, bool]] = []
        self.seek_calls: list[float] = []
        self.play_mode_calls: list[str] = []
        self.playlist = []

    def fade_volume(self, target_volume, duration, callback=None, temporary=None):
        self.fade_calls.append((target_volume, duration, temporary))
        if callback:
            callback()

    def set_volume(self, volume, temporary=False):
        self.set_volume_calls.append((volume, temporary))

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def play(self, *_args, **_kwargs):
        self.is_playing = True

    def get_playlist(self):
        return list(self.playlist)

    def get_all_playlists(self):
        return ["默认"]

    def switch_playlist(self, *_args, **_kwargs):
        return True

    def create_playlist(self, *_args, **_kwargs):
        return True

    def rename_playlist(self, *_args, **_kwargs):
        return True

    def delete_playlist(self, *_args, **_kwargs):
        return True

    def add_track(self, *_args, **_kwargs):
        return True

    def remove_track(self, *_args, **_kwargs):
        return True

    def clear_playlist(self):
        return True

    def get_current_track(self):
        return self.current_track

    def get_progress(self):
        return (0, 0)

    def set_play_mode(self, mode):
        self.play_mode_calls.append(mode)

    def previous(self):
        return None

    def next(self):
        return None

    def seek(self, position):
        self.seek_calls.append(position)


def _kill_payload(health: int = 100):
    return {
        "player": {
            "steamid": "music_test_steamid",
            "activity": "playing",
            "state": {"health": health},
        }
    }


def test_gsi_music_handler_ignores_game_link_when_master_toggle_off(monkeypatch):
    dummy_player = _DummyPlayer()
    monkeypatch.setattr(gsi_handler_music, "get_music_player", lambda: dummy_player)

    monkeypatch.setattr(config, "music_enabled", False, raising=False)
    monkeypatch.setattr(config, "music_game_link_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_revive_action", "lower", raising=False)
    monkeypatch.setattr(config, "music_revive_volume", 0.2, raising=False)
    monkeypatch.setattr(config, "music_fade_enabled", False, raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "", raising=False)

    handler = gsi_handler_music.GSIHandlerMusic()
    handler.process_data(_kill_payload(health=100))

    assert dummy_player.set_volume_calls == []
    assert dummy_player.fade_calls == []


def test_gsi_music_handler_lowers_volume_when_master_toggle_on(monkeypatch):
    dummy_player = _DummyPlayer()
    monkeypatch.setattr(gsi_handler_music, "get_music_player", lambda: dummy_player)

    monkeypatch.setattr(config, "music_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_game_link_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_revive_action", "lower", raising=False)
    monkeypatch.setattr(config, "music_revive_volume", 0.2, raising=False)
    monkeypatch.setattr(config, "music_fade_enabled", False, raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "", raising=False)

    handler = gsi_handler_music.GSIHandlerMusic()
    handler.process_data(_kill_payload(health=100))

    assert dummy_player.set_volume_calls == [(0.2, True)]


def test_gsi_music_handler_does_not_create_player_when_link_disabled(monkeypatch):
    calls = []

    def _factory():
        calls.append("created")
        return _DummyPlayer()

    monkeypatch.setattr(gsi_handler_music, "get_music_player", _factory)
    monkeypatch.setattr(config, "music_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_game_link_enabled", False, raising=False)

    handler = gsi_handler_music.GSIHandlerMusic()
    handler.process_data(_kill_payload(health=100))

    assert calls == []
    assert handler.player is None


def test_music_control_bar_init_does_not_create_player(monkeypatch):
    qapp()
    calls = []

    def _factory():
        calls.append("created")
        return _DummyPlayer()

    monkeypatch.setattr(music_control_bar_module, "get_music_player", _factory)
    monkeypatch.setattr(music_control_bar_module.music_player_module, "music_player", None)

    bar = music_control_bar_module.MusicControlBar()

    assert calls == []
    assert bar.player is None


def test_music_control_bar_uses_existing_player_without_creation(monkeypatch):
    qapp()
    dummy_player = _DummyPlayer()
    dummy_player.current_track = {"title": "Demo", "artist": "Tester", "duration": 123}

    monkeypatch.setattr(
        music_control_bar_module,
        "get_music_player",
        lambda: (_ for _ in ()).throw(AssertionError("should not create player")),
    )
    monkeypatch.setattr(music_control_bar_module.music_player_module, "music_player", dummy_player)

    bar = music_control_bar_module.MusicControlBar()

    assert bar.player is dummy_player
    assert bar.track_title_label.text() == "Demo"


def test_music_control_bar_prefers_loaded_current_track_when_index_track_missing(monkeypatch):
    qapp()

    class _TrackFallbackPlayer(_DummyPlayer):
        def get_current_track(self):
            return None

    dummy_player = _TrackFallbackPlayer()
    dummy_player.current_track = {"name": "Recovered Demo", "type": "local", "duration": 248}

    monkeypatch.setattr(
        music_control_bar_module,
        "get_music_player",
        lambda: (_ for _ in ()).throw(AssertionError("should not create player")),
    )
    monkeypatch.setattr(music_control_bar_module.music_player_module, "music_player", dummy_player)

    bar = music_control_bar_module.MusicControlBar()

    assert bar.track_title_label.text() == "Recovered Demo"
    assert bar.mini_track_label.text().startswith("♪ Recovered Demo")


def test_music_control_bar_expanded_height_fits_content(monkeypatch):
    qapp()
    dummy_player = _DummyPlayer()

    monkeypatch.setattr(
        music_control_bar_module,
        "get_music_player",
        lambda: (_ for _ in ()).throw(AssertionError("should not create player")),
    )
    monkeypatch.setattr(music_control_bar_module.music_player_module, "music_player", dummy_player)

    bar = music_control_bar_module.MusicControlBar()
    qapp().processEvents()

    assert bar.expanded_height >= bar.sizeHint().height()
    assert bar.maximumHeight() >= bar.sizeHint().height()


def test_music_control_bar_restores_saved_progress_from_config_without_player(monkeypatch):
    qapp()
    calls = []

    def _factory():
        calls.append("created")
        return _DummyPlayer()

    monkeypatch.setattr(music_control_bar_module, "get_music_player", _factory)
    monkeypatch.setattr(music_control_bar_module.music_player_module, "music_player", None)
    monkeypatch.setattr(config, "music_current_playlist", "默认", raising=False)
    monkeypatch.setattr(
        config,
        "music_playlists",
        {
            "默认": [
                {"title": "Saved Track", "artist": "Saved Artist", "duration": 248},
            ]
        },
        raising=False,
    )
    monkeypatch.setattr(config, "music_current_index", 0, raising=False)
    monkeypatch.setattr(config, "music_current_position", 177, raising=False)
    monkeypatch.setattr(config, "music_is_playing", False, raising=False)

    bar = music_control_bar_module.MusicControlBar()

    assert calls == []
    assert bar.player is None
    assert bar.track_title_label.text() == "Saved Track"
    assert bar.track_artist_label.text() == "Saved Artist"
    assert bar.current_time_label.text() == "2:57"
    assert bar.total_time_label.text() == "4:08"
    assert bar.progress_slider.value() == 713


def test_music_control_bar_creates_player_on_play_action(monkeypatch):
    qapp()
    calls = []
    dummy_player = _DummyPlayer()
    dummy_player.is_playing = False
    dummy_player.playlist = [{"title": "Demo Track"}]

    def _factory():
        calls.append("created")
        return dummy_player

    monkeypatch.setattr(music_control_bar_module, "get_music_player", _factory)
    monkeypatch.setattr(music_control_bar_module.music_player_module, "music_player", None)

    bar = music_control_bar_module.MusicControlBar()
    bar.toggle_play_pause()

    assert calls == ["created"]
    assert bar.player is dummy_player
    assert dummy_player.is_playing is True


def test_music_page_radio_changes_persist_to_config(monkeypatch):
    qapp()
    dummy_player = _DummyPlayer()
    monkeypatch.setattr(music_page_module, "get_music_player", lambda: dummy_player)

    monkeypatch.setattr(config, "music_game_link_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_death_action", "play", raising=False)
    monkeypatch.setattr(config, "music_death_volume_custom", False, raising=False)
    monkeypatch.setattr(config, "music_death_volume", 1.0, raising=False)
    monkeypatch.setattr(config, "music_revive_action", "lower", raising=False)
    monkeypatch.setattr(config, "music_revive_volume", 0.2, raising=False)
    monkeypatch.setattr(config, "music_fade_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_fade_out_duration", 0.3, raising=False)

    page = music_page_module.MusicPage()
    page.alive_action_group.button(2).click()
    page.death_volume_group.button(1).click()

    assert config.music_revive_action == "keep"
    assert config.music_death_volume_custom is True
    assert not page.alive_volume_slider.isEnabled()



def test_music_player_fade_volume_updates_temp_state(monkeypatch):
    fake_music = SimpleNamespace(
        _volume=0.0,
        set_volume=lambda value: setattr(fake_music, "_volume", value),
        get_volume=lambda: fake_music._volume,
    )
    monkeypatch.setattr(music_player.pygame, "mixer", SimpleNamespace(music=fake_music))

    player = music_player.MusicPlayer.__new__(music_player.MusicPlayer)
    player.base_volume = 0.5
    player.volume = 0.5
    player.temp_volume = None
    player.fade_thread = None
    player.stop_fade = False

    player.fade_volume(0.2, 0, temporary=True)
    player.fade_thread.join(timeout=1)

    assert player.temp_volume == 0.2
    assert abs(fake_music._volume - 0.2) < 1e-6
