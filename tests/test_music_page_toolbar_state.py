from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from config import config
import pages.music_page as music_page_module


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _visible_audio_status_chip_texts(status_bar) -> list[str]:
    layout = status_bar.layout()
    if layout is None:
        return []
    texts: list[str] = []
    for idx in range(layout.count()):
        item = layout.itemAt(idx)
        widget = item.widget() if item else None
        if (
            isinstance(widget, QLabel)
            and widget.objectName() == "audioStatusChip"
            and not widget.isHidden()
        ):
            texts.append(widget.text())
    return texts


class _DummyPlayer:
    def __init__(self):
        self.current_playlist_name = "默认列表"
        self.current_index = 0
        self.is_playing = True
        self.is_paused = False
        self.play_mode_calls: list[str] = []
        self.playlist = [
            {"title": "Demo Track", "artist": "Tester", "duration": 75},
            {"title": "Second Track", "artist": "Guest", "duration": 0, "type": "url"},
        ]
        self.on_playlist_update = None
        self.on_playlist_change = None

    def get_playlist(self):
        return list(self.playlist)

    def get_all_playlists(self):
        return ["默认列表"]

    def switch_playlist(self, name):
        self.current_playlist_name = name
        return True

    def set_play_mode(self, mode):
        self.play_mode_calls.append(mode)


def test_music_page_playlist_panel_and_action_bar_sync(qapp, monkeypatch):
    dummy_player = _DummyPlayer()
    monkeypatch.setattr(music_page_module, "get_music_player", lambda: dummy_player)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "music_game_link_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_death_action", "play", raising=False)
    monkeypatch.setattr(config, "music_death_volume_custom", False, raising=False)
    monkeypatch.setattr(config, "music_death_volume", 1.0, raising=False)
    monkeypatch.setattr(config, "music_revive_action", "lower", raising=False)
    monkeypatch.setattr(config, "music_revive_volume", 0.4, raising=False)
    monkeypatch.setattr(config, "music_fade_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_fade_out_duration", 0.5, raising=False)
    monkeypatch.setattr(config, "music_play_mode", "shuffle", raising=False)
    monkeypatch.setattr(config, "music_current_playlist", "默认列表", raising=False)

    page = music_page_module.MusicPage()

    assert page.action_bar.primary_btn.text() == "添加音乐"
    assert page.action_bar.secondary_btn.text() == "刷新列表"

    chips = _visible_audio_status_chip_texts(page.playlist_status_badge_label)
    assert len(chips) == 4
    assert any(text == "曲目 · 2 首" for text in chips)
    assert any(text == "选中 · 0 首" for text in chips)
    assert "当前列表：" in page.action_bar.message_label.text()

    page.playlist_widget.item(0).setSelected(True)
    qapp.processEvents()

    chips = _visible_audio_status_chip_texts(page.playlist_status_badge_label)
    assert any(text == "选中 · 1 首" for text in chips)
    assert "已选 1 首" in page.action_bar.message_label.text()

    page._refresh_playlist_catalog()
    qapp.processEvents()

    assert page.playlist_widget.item(0).isSelected() is True
    chips = _visible_audio_status_chip_texts(page.playlist_status_badge_label)
    assert any(text == "选中 · 1 首" for text in chips)

    page.death_volume_group.button(1).click()
    page.death_volume_slider.setValue(65)
    assert "65%" in page.music_summary_label.text()

    page.deleteLater()
    qapp.processEvents()
