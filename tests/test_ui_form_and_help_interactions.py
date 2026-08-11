from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from config import config
from ui_help_panel import HelpButton, HelpPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _DummyVoiceOutputManager:
    def __init__(self):
        self.vb_cable_device_id = 7
        self.microphone_passthrough_active = False
        self.last_microphone = None
        self.play_calls = []

    def get_microphone_list(self):
        return ["默认", "USB Mic"]

    def start_microphone_passthrough(self, microphone):
        self.microphone_passthrough_active = True
        self.last_microphone = microphone
        return True

    def stop_microphone_passthrough(self):
        self.microphone_passthrough_active = False

    def get_sound_duration(self, _path):
        return 0.5

    def play_audio_with_ptt_protocol(self, **kwargs):
        self.play_calls.append(kwargs)
        return True

    def stop_playback(self):
        return None


class _DummyMusicPlayer:
    def __init__(self):
        self.on_playlist_update = None
        self.on_playlist_change = None
        self.current_playlist_name = "默认"
        self.current_index = 0
        self.is_paused = False
        self.is_playing = False
        self.play_mode = "repeat_all"
        self._playlists = ["默认", "收藏"]
        self._playlist = [
            {"title": "Inferno Pulse", "artist": "FanPai", "duration": 182, "type": "local", "path": "a.mp3"},
            {"title": "Dust Loop", "artist": "FanPai", "duration": 201, "type": "local", "path": "b.mp3"},
        ]

    def get_playlist(self):
        return list(self._playlist)

    def get_all_playlists(self):
        return list(self._playlists)

    def switch_playlist(self, name):
        self.current_playlist_name = name

    def get_current_track(self):
        if 0 <= self.current_index < len(self._playlist):
            return self._playlist[self.current_index]
        return None

    def set_play_mode(self, play_mode):
        self.play_mode = play_mode

    def play(self, row):
        self.current_index = row
        self.is_playing = True
        self.is_paused = False


def _expand_help_panel(page, qapp, expected_text: str):
    help_button = page.findChild(HelpButton)
    help_panel = page.findChild(HelpPanel)
    assert help_button is not None
    assert help_panel is not None

    QTest.mouseClick(help_button, Qt.LeftButton)
    QTest.qWait(help_panel.EXPAND_DURATION + 80)
    qapp.processEvents()

    content = help_panel.findChild(QLabel, "helpContent")
    assert content is not None
    assert expected_text in content.text()
    assert help_panel.maximumHeight() > 0
    return help_panel


def test_advanced_page_help_and_controls_are_usable(qapp, monkeypatch):
    import pages.advanced_page as advanced_page_module
    from PySide6.QtWidgets import QLineEdit

    monkeypatch.setattr(advanced_page_module.AdvancedPage, "_try_auto_detect_cs2", lambda self: None)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "ui_theme", "dark", raising=False)
    monkeypatch.setattr(config, "debug_mode", False, raising=False)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: 0)

    page = advanced_page_module.AdvancedPage()
    page.resize(1280, 860)
    page.show()
    qapp.processEvents()

    _expand_help_panel(page, qapp, "gamestate_integration_fanpai.cfg")
    assert page.csgo_dir_text.isReadOnly() is True
    assert page.csgo_dir_text.placeholderText()
    assert page.debug_entry.echoMode() == QLineEdit.Password

    page.debug_entry.setText("8964")
    page._toggle_debug_mode()
    assert config.debug_mode is True
    assert page.debug_entry.text() == ""

    light_index = page.theme_combo.findData("light")
    assert light_index >= 0
    page.theme_combo.setCurrentIndex(light_index)
    qapp.processEvents()
    assert config.ui_theme == "light"
    assert page.theme_combo.count() >= 5

    page.deleteLater()
    qapp.processEvents()


def test_utility_page_help_and_numeric_inputs_are_usable(qapp, monkeypatch):
    import pages.utility_page as utility_page_module

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "utility_guide_position_x", 0, raising=False)
    monkeypatch.setattr(config, "utility_guide_position_y", 0, raising=False)
    monkeypatch.setattr(config, "utility_guide_display_duration", 10, raising=False)
    monkeypatch.setattr(config, "utility_guide_mode", "toggle", raising=False)

    page = utility_page_module.UtilityPage()
    page.resize(1360, 900)
    page.show()
    qapp.processEvents()

    _expand_help_panel(page, qapp, "AppData/Local/FanTool/resources/utility_guides/")

    page.x_offset_edit.selectAll()
    QTest.keyClicks(page.x_offset_edit, "12")
    qapp.processEvents()
    assert config.utility_guide_position_x == 12

    page.y_offset_edit.selectAll()
    QTest.keyClicks(page.y_offset_edit, "-8")
    qapp.processEvents()
    assert config.utility_guide_position_y == -8

    page.duration_edit.selectAll()
    QTest.keyClicks(page.duration_edit, "25")
    qapp.processEvents()
    assert config.utility_guide_display_duration == 25

    page.hold_radio.click()
    qapp.processEvents()
    assert config.utility_guide_mode == "hold"

    page.deleteLater()
    qapp.processEvents()


def test_magnifier_page_help_inputs_and_options_are_usable(qapp, monkeypatch):
    import pages.magnifier_page as magnifier_page_module

    class _DummyThemeManager:
        def register_theme_changed_callback(self, _callback):
            return None

        def unregister_theme_changed_callback(self, _callback):
            return None

    monkeypatch.setattr(magnifier_page_module, "get_theme_manager", lambda: _DummyThemeManager())
    monkeypatch.setattr(magnifier_page_module, "magnification_available", True)
    monkeypatch.setattr(magnifier_page_module, "MagInitialize", lambda: True, raising=False)
    monkeypatch.setattr(magnifier_page_module, "MagUninitialize", lambda: True, raising=False)
    monkeypatch.setattr(magnifier_page_module, "MagSetFullscreenTransform", lambda *_args, **_kwargs: True, raising=False)
    monkeypatch.setattr(magnifier_page_module, "MagShowSystemCursor", lambda *_args, **_kwargs: True, raising=False)
    monkeypatch.setattr(
        magnifier_page_module.user32,
        "GetSystemMetrics",
        lambda index: 1920 if index == 0 else 1080,
        raising=False,
    )
    monkeypatch.setattr(magnifier_page_module.MagnifierPage, "_setup_key_detection", lambda self: None)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "magnifier_enabled", True, raising=False)
    monkeypatch.setattr(
        config,
        "magnifier",
        {
            "zoom_factor": 2.0,
            "primary_hotkey": "右键",
            "secondary_hotkey": "右键",
            "trigger_mode": "长按触发",
            "debounce_time": 150,
            "sensitivity_sync_enabled": False,
            "base_sensitivity": 1.0,
            "sensitivity_multiplier": 0.82,
            "sync_trigger_key": "SCROLLLOCK",
            "weapon_settings": {"weapon_awp": True},
            "zoom_settings": {},
        },
        raising=False,
    )

    page = magnifier_page_module.MagnifierPage(config)
    page.resize(1400, 960)
    page.show()
    qapp.processEvents()

    _expand_help_panel(page, qapp, "fanpai_magnifier_runtime.cfg")
    assert page.zoom_combo.count() >= 3
    assert page.primary_hotkey_combo.count() >= 5
    assert page.trigger_mode_combo.count() == 2

    page.base_sensitivity_input.setText("1.25")
    page.base_sensitivity_input.editingFinished.emit()
    qapp.processEvents()
    assert config.magnifier["base_sensitivity"] == pytest.approx(1.25)

    page.sensitivity_multiplier_input.setText("0.90")
    page.sensitivity_multiplier_input.editingFinished.emit()
    qapp.processEvents()
    assert config.magnifier["sensitivity_multiplier"] == pytest.approx(0.90)

    page.primary_hotkey_combo.setCurrentText("F2")
    page.trigger_mode_combo.setCurrentText("单击切换")
    qapp.processEvents()
    assert config.magnifier["primary_hotkey"] == "F2"
    assert config.magnifier["trigger_mode"] == "单击切换"

    page.x_offset_input.setText("15")
    page.y_offset_input.setText("-10")
    page._apply_offset()
    assert config.magnifier["zoom_settings"]["2.0"]["x_offset"] == 15
    assert config.magnifier["zoom_settings"]["2.0"]["y_offset"] == -10

    page.deleteLater()
    qapp.processEvents()


def test_voice_output_page_help_and_controls_are_usable(qapp, monkeypatch):
    import pages.voice_output_page as voice_output_page_module

    dummy = _DummyVoiceOutputManager()
    monkeypatch.setattr(voice_output_page_module, "get_voice_output_manager", lambda: dummy)
    monkeypatch.setattr(voice_output_page_module.keyboard, "add_hotkey", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(voice_output_page_module.keyboard, "remove_hotkey", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(voice_output_page_module.keyboard, "hook", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(voice_output_page_module.keyboard, "unhook", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "voice_output_volume", 0.65, raising=False)
    monkeypatch.setattr(config, "voice_output_mode", "覆盖", raising=False)
    monkeypatch.setattr(config, "voice_output_also_local", True, raising=False)
    monkeypatch.setattr(config, "voice_output_ptt_enabled", True, raising=False)
    monkeypatch.setattr(config, "voice_output_ptt_key", "V", raising=False)
    monkeypatch.setattr(config, "voice_output_stop_key", "F8", raising=False)
    monkeypatch.setattr(config, "voice_output_microphone", "默认", raising=False)
    monkeypatch.setattr(config, "voice_output_slots", {"0": {"audio": "demo.wav", "key": "ctrl+1", "volume": 0.8, "name": "Demo Clip"}}, raising=False)
    monkeypatch.setattr(config, "sfx_forwarding_enabled", False, raising=False)
    monkeypatch.setattr(config, "sfx_forwarding_options", {"kill_sound": True, "special_sound": True}, raising=False)

    page = voice_output_page_module.VoiceOutputPage()
    page.resize(1440, 960)
    page.show()
    qapp.processEvents()

    _expand_help_panel(page, qapp, "voice_output_config.json")
    assert page.mic_combo.count() >= 2
    assert page.play_mode_combo.count() == 3
    assert page.soundboard_slots[0]["preview_button"].isEnabled() is True

    page.play_mode_combo.setCurrentText("自动")
    qapp.processEvents()
    assert config.voice_output_mode == "自动"
    assert dummy.microphone_passthrough_active is True

    page.mic_combo.setCurrentText("USB Mic")
    qapp.processEvents()
    assert config.voice_output_microphone == "USB Mic"
    assert dummy.last_microphone == "USB Mic"

    page.ptt_enabled_check.setChecked(False)
    qapp.processEvents()
    assert config.voice_output_ptt_enabled is False

    page.sfx_forwarding_check.setChecked(True)
    qapp.processEvents()
    assert config.sfx_forwarding_enabled is True

    page.cleanup()
    page.deleteLater()
    qapp.processEvents()


def test_music_page_help_and_playlist_controls_are_usable(qapp, monkeypatch):
    import pages.music_page as music_page_module

    dummy = _DummyMusicPlayer()
    monkeypatch.setattr(music_page_module, "get_music_player", lambda: dummy)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "music_game_link_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_play_mode", "repeat_all", raising=False)
    monkeypatch.setattr(config, "music_current_playlist", "默认", raising=False)
    monkeypatch.setattr(config, "music_death_action", "play", raising=False)
    monkeypatch.setattr(config, "music_death_volume_custom", False, raising=False)
    monkeypatch.setattr(config, "music_death_volume", 1.0, raising=False)
    monkeypatch.setattr(config, "music_revive_action", "lower", raising=False)
    monkeypatch.setattr(config, "music_revive_volume", 0.4, raising=False)
    monkeypatch.setattr(config, "music_fade_enabled", True, raising=False)
    monkeypatch.setattr(config, "music_fade_out_duration", 0.5, raising=False)

    page = music_page_module.MusicPage()
    page.resize(1380, 920)
    page.show()
    qapp.processEvents()

    _expand_help_panel(page, qapp, "AppData/Local/FanTool/config.json")
    assert page.playlist_combo.count() >= 2
    assert page.playlist_widget.count() >= 2

    page.play_mode_group.button(1).click()
    qapp.processEvents()
    assert dummy.play_mode == "shuffle"

    page.game_link_checkbox.setChecked(False)
    qapp.processEvents()
    assert config.music_game_link_enabled is False
    assert page.link_content_frame.isEnabled() is False

    page.deleteLater()
    qapp.processEvents()
