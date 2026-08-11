from __future__ import annotations

from types import SimpleNamespace

from config import config
import music_control_bar
import music_player
import pages.death_sound_page as death_sound_page
import pages.gun_sound_page as gun_sound_page
import pages.music_page as music_page
import pages.reload_sound_page as reload_sound_page
import pages.switch_weapon_page as switch_weapon_page


class _DummyRow:
    def __init__(self):
        self.value = None

    def set_current_style(self, value):
        self.value = value


class _DummyCombo:
    def __init__(self, mapping):
        self.mapping = mapping
        self.index = None

    def findData(self, value):
        return self.mapping.get(value, -1)

    def setCurrentIndex(self, index):
        self.index = index


class _DummySlider:
    def __init__(self):
        self.value = None

    def setValue(self, value):
        self.value = value


class _DummyLabel:
    def __init__(self):
        self.text = None

    def setText(self, value):
        self.text = value


def test_reload_sound_page_load_settings_keeps_explicit_disabled(monkeypatch):
    page = reload_sound_page.ReloadSoundPage.__new__(reload_sound_page.ReloadSoundPage)
    page.weapon_rows = {"weapon_ak47": _DummyRow()}
    page.weapon_reload_styles = {"weapon_ak47": ["styleReload"]}
    page.logger = SimpleNamespace(info=lambda *_a, **_k: None)
    page._refresh_status_badge = lambda: None

    monkeypatch.setattr(config, "weapon_reload_sounds", {"weapon_ak47": "0"}, raising=False)

    page.load_settings()

    assert config.weapon_reload_sounds["weapon_ak47"] == "0"
    assert page.weapon_rows["weapon_ak47"].value == "不启用"


def test_switch_sound_page_load_settings_keeps_explicit_disabled(monkeypatch):
    page = switch_weapon_page.SwitchWeaponPage.__new__(switch_weapon_page.SwitchWeaponPage)
    page.weapon_rows = {"weapon_ak47": _DummyRow()}
    page.weapon_switch_styles = {"weapon_ak47": ["styleSwitch"]}
    page.logger = SimpleNamespace(info=lambda *_a, **_k: None)
    page._refresh_status_badge = lambda: None

    monkeypatch.setattr(config, "weapon_switch_sounds", {"weapon_ak47": "0"}, raising=False)

    page.load_settings()

    assert config.weapon_switch_sounds["weapon_ak47"] == "0"
    assert page.weapon_rows["weapon_ak47"].value == "不启用"


def test_gun_sound_page_load_settings_keeps_explicit_disabled(monkeypatch):
    page = gun_sound_page.GunSoundPage.__new__(gun_sound_page.GunSoundPage)
    page.weapon_configs = {"awp": gun_sound_page.GUN_SOUND_PROFILES["awp"]}
    page.weapon_rows = {
        "awp": {
            "style_combo": _DummyCombo({"0": 0, "styleGun": 1}),
            "duration_slider": _DummySlider(),
            "duration_label": _DummyLabel(),
        }
    }
    page.weapon_styles = {"awp": ["styleGun"]}
    page.logger = SimpleNamespace(info=lambda *_a, **_k: None)
    page._refresh_status_badge = lambda: None

    monkeypatch.setattr(config, "awp_style", "0", raising=False)
    monkeypatch.setattr(config, "awp_mute_duration", 0.5, raising=False)

    page.load_settings()

    assert config.awp_style == "0"
    assert page.weapon_rows["awp"]["style_combo"].index == 0


def test_death_sound_page_style_change_saves_config(monkeypatch):
    saved = []
    page = death_sound_page.DeathSoundPage.__new__(death_sound_page.DeathSoundPage)
    page.style_combo = SimpleNamespace(currentData=lambda: "styleDeath")
    page._refresh_status_badge = lambda: None
    page.logger = SimpleNamespace(info=lambda *_a, **_k: None)

    monkeypatch.setattr(config, "death_sound_style", "0", raising=False)
    monkeypatch.setattr(config, "save_config", lambda: saved.append(True), raising=False)

    page._on_style_changed("styleDeath")

    assert config.death_sound_style == "styleDeath"
    assert saved == [True]


def test_gun_sound_page_style_change_saves_config(monkeypatch):
    saved = []
    page = gun_sound_page.GunSoundPage.__new__(gun_sound_page.GunSoundPage)
    page.weapon_configs = {"awp": gun_sound_page.GUN_SOUND_PROFILES["awp"]}
    page.logger = SimpleNamespace(info=lambda *_a, **_k: None)
    page._refresh_status_badge = lambda: None

    monkeypatch.setattr(config, "awp_style", "0", raising=False)
    monkeypatch.setattr(config, "save_config", lambda: saved.append(True), raising=False)

    page._on_weapon_style_changed("awp", "styleGun")

    assert config.awp_style == "styleGun"
    assert saved == [True]


def test_gun_sound_page_load_settings_supports_new_weapon_profile(monkeypatch):
    page = gun_sound_page.GunSoundPage.__new__(gun_sound_page.GunSoundPage)
    page.weapon_configs = {"xm1014": gun_sound_page.SUPPORTED_GUN_SOUND_PROFILES["xm1014"]}
    page.weapon_rows = {
        "xm1014": {
            "style_combo": _DummyCombo({"0": 0, "styleAk": 1}),
            "duration_slider": _DummySlider(),
            "duration_label": _DummyLabel(),
        }
    }
    page.weapon_styles = {"xm1014": ["styleAk"]}
    page.logger = SimpleNamespace(info=lambda *_a, **_k: None)
    page._refresh_status_badge = lambda: None

    monkeypatch.setattr(config, "xm1014_style", "styleAk", raising=False)
    monkeypatch.setattr(config, "xm1014_mute_duration", 0.3, raising=False)

    page.load_settings()

    assert page.weapon_rows["xm1014"]["style_combo"].index == 1
    assert page.weapon_rows["xm1014"]["duration_slider"].value == 3
    assert page.weapon_rows["xm1014"]["duration_label"].text.startswith("0.3")


def test_reload_and_switch_style_change_save_config(monkeypatch):
    saved = []
    monkeypatch.setattr(config, "save_config", lambda: saved.append(True), raising=False)

    reload_page = reload_sound_page.ReloadSoundPage.__new__(reload_sound_page.ReloadSoundPage)
    reload_page._refresh_status_badge = lambda: None
    reload_page.logger = SimpleNamespace(info=lambda *_a, **_k: None)
    monkeypatch.setattr(config, "weapon_reload_sounds", {"weapon_ak47": "0"}, raising=False)
    reload_page._on_weapon_style_changed("weapon_ak47", "styleReload")

    switch_page = switch_weapon_page.SwitchWeaponPage.__new__(switch_weapon_page.SwitchWeaponPage)
    switch_page._refresh_status_badge = lambda: None
    switch_page.logger = SimpleNamespace(info=lambda *_a, **_k: None)
    monkeypatch.setattr(config, "weapon_switch_sounds", {"weapon_ak47": "0"}, raising=False)
    switch_page._on_weapon_style_changed("weapon_ak47", "styleSwitch")

    assert config.weapon_reload_sounds["weapon_ak47"] == "styleReload"
    assert config.weapon_switch_sounds["weapon_ak47"] == "styleSwitch"
    assert saved == [True, True]


def test_music_page_play_mode_change_uses_canonical_modes(monkeypatch):
    captured = []
    page = music_page.MusicPage.__new__(music_page.MusicPage)
    page.player = SimpleNamespace(set_play_mode=lambda mode: captured.append(mode))
    page.logger = SimpleNamespace(info=lambda *_a, **_k: None)

    page._on_play_mode_changed(3)

    assert captured == ["repeat_all"]


def test_music_player_normalizes_legacy_play_modes(monkeypatch):
    saved = []
    monkeypatch.setattr(config, "save_config", lambda: saved.append(True), raising=False)

    player = music_player.MusicPlayer.__new__(music_player.MusicPlayer)
    player._debug_log = lambda *_a, **_k: None
    player.play_mode = "sequence"

    player.set_play_mode("loop")

    assert player.play_mode == "repeat_all"
    assert config.music_play_mode == "repeat_all"
    assert saved == [True]


def test_music_control_bar_cycle_play_mode_uses_canonical_modes(monkeypatch):
    saved = []
    monkeypatch.setattr(config, "music_play_mode", "sequence", raising=False)
    monkeypatch.setattr(config, "save_config", lambda: saved.append(True), raising=False)

    captured = []
    bar = music_control_bar.MusicControlBar.__new__(music_control_bar.MusicControlBar)
    bar.player = SimpleNamespace(set_play_mode=lambda mode: captured.append(mode))
    bar.mode_btn = SimpleNamespace(
        setIcon=lambda *_a, **_k: None,
        setToolTip=lambda *_a, **_k: None,
    )
    bar._create_themed_icon = lambda icon: icon
    bar.logger = SimpleNamespace(info=lambda *_a, **_k: None)

    bar.cycle_play_mode()

    assert config.music_play_mode == "shuffle"
    assert captured == ["shuffle"]
    assert saved == [True]
