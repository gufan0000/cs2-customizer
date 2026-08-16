# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for core/audio/audio_manager.py."""

import os
from core.gun_sound_profiles import GUN_SOUND_PROFILE_LIST


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"")


class TestAudioManagerInit:
    def test_import_and_singleton(self):
        from core.audio.audio_manager import AudioManager, get_audio_manager

        mgr = get_audio_manager()
        assert isinstance(mgr, AudioManager)
        mgr2 = get_audio_manager()
        assert mgr is mgr2

    def test_channels_exist(self):
        from core.audio.audio_manager import get_audio_manager

        mgr = get_audio_manager()
        assert mgr.awp_channel is not None
        assert mgr.kill_sound_channel is not None
        assert mgr.kill_voice_channel is not None
        assert mgr.switch_weapon_channel is not None
        assert mgr.reload_channel is not None
        assert mgr.grenade_sound_channel is not None
        assert mgr.c4_sound_channel is not None
        assert mgr.health_warning_channel is not None
        assert mgr.round_sound_channel is not None

    def test_directory_attributes(self):
        from core.audio.audio_manager import get_audio_manager

        mgr = get_audio_manager()
        assert hasattr(mgr, "audio_base_dir")
        assert hasattr(mgr, "kill_sounds_dir")
        assert hasattr(mgr, "kill_voices_dir")
        assert hasattr(mgr, "weapon_voices_dir")
        assert hasattr(mgr, "gun_sounds_dir")
        assert hasattr(mgr, "death_sounds_dir")
        assert hasattr(mgr, "switch_weapons_dir")
        assert hasattr(mgr, "reload_sounds_dir")

    def test_play_sound_accepts_channel_kwarg(self):
        from core.audio.audio_manager import get_audio_manager
        import inspect

        mgr = get_audio_manager()
        sig = inspect.signature(mgr.play_sound)
        params = list(sig.parameters.keys())
        assert "channel" in params
        assert "channel_type" in params

    def test_style_lists_initialized(self):
        from core.audio.audio_manager import get_audio_manager

        mgr = get_audio_manager()
        assert isinstance(mgr.kill_sound_styles, list)
        assert isinstance(mgr.kill_voice_styles, list)
        assert isinstance(mgr.weapon_kill_voice_styles, dict)
        assert isinstance(mgr.death_sound_styles, list)


def test_scan_special_styles(tmp_path):
    from core.audio.audio_manager import AudioManager

    mgr = AudioManager()
    mgr.switch_weapons_dir = str(tmp_path / "switch_weapons")
    mgr.reload_sounds_dir = str(tmp_path / "reload_sounds")
    mgr.grenade_sounds_dir = str(tmp_path / "grenade_sounds")
    mgr.c4_sounds_dir = str(tmp_path / "c4_sounds")
    mgr.health_warning_dir = str(tmp_path / "health_warning")
    mgr.round_sounds_dir = str(tmp_path / "round_sounds")
    mgr.gun_sounds_dir = str(tmp_path / "gun_sounds")

    _touch(str(tmp_path / "switch_weapons" / "weapon_ak47" / "styleA" / "a.wav"))
    _touch(str(tmp_path / "reload_sounds" / "weapon_ak47" / "styleB" / "a.wav"))
    _touch(str(tmp_path / "grenade_sounds" / "hegrenade" / "styleC" / "a.wav"))
    _touch(str(tmp_path / "c4_sounds" / "styleD" / "planted.wav"))
    _touch(str(tmp_path / "health_warning" / "styleE" / "warn.wav"))
    _touch(str(tmp_path / "round_sounds" / "start" / "styleF" / "start.wav"))
    _touch(str(tmp_path / "gun_sounds" / "awp" / "styleG" / "shot.wav"))
    _touch(str(tmp_path / "gun_sounds" / "xm1014" / "styleShotgun" / "shot.wav"))

    assert "styleA" in mgr.scan_switch_weapon_styles().get("weapon_ak47", [])
    assert "styleB" in mgr.scan_reload_styles().get("weapon_ak47", [])
    assert "styleC" in mgr.scan_grenade_sound_styles().get("hegrenade", [])
    assert "styleD" in mgr.scan_c4_sound_styles()
    assert "styleE" in mgr.scan_health_warning_styles()
    mgr.scan_round_sound_styles()
    assert "styleF" in mgr.round_start_styles
    assert "styleG" in mgr.scan_gun_sound_styles().get("awp", [])
    assert "styleShotgun" in mgr.gun_sound_styles.get("xm1014", [])


def test_load_sound_by_key_parses_compat_prefixes(monkeypatch):
    from core.audio.audio_manager import AudioManager

    mgr = AudioManager()
    calls = {}

    monkeypatch.setattr(mgr, "ensure_styles_scanned", lambda: None)
    monkeypatch.setattr(mgr, "load_switch_weapon_sound", lambda w, s: calls.setdefault("switch", (w, s)) or True)
    monkeypatch.setattr(mgr, "load_reload_sound", lambda w, s: calls.setdefault("reload", (w, s)) or True)
    monkeypatch.setattr(mgr, "load_grenade_sound", lambda g, s: calls.setdefault("grenade", (g, s)) or True)
    # load_c4_sound 现在带事件参数：安放/拆除/爆炸共用一个风格目录（2026-08-15）
    monkeypatch.setattr(
        mgr, "load_c4_sound",
        lambda s, event_key="planted": calls.setdefault("c4", s) or True,
    )
    monkeypatch.setattr(mgr, "load_health_warning_sound", lambda s: calls.setdefault("health", s) or True)
    monkeypatch.setattr(mgr, "load_round_sound", lambda a, b: calls.setdefault("round", (a, b)) or True)

    assert mgr._load_sound_by_key("switch-weapon_ak47-style1")
    assert calls["switch"] == ("weapon_ak47", "style1")

    assert mgr._load_sound_by_key("reload-weapon_ak47-style2")
    assert calls["reload"] == ("weapon_ak47", "style2")

    assert mgr._load_sound_by_key("grenade-hegrenade-style3")
    assert calls["grenade"] == ("hegrenade", "style3")

    assert mgr._load_sound_by_key("c4-planted-style4")
    assert calls["c4"] == "style4"

    assert mgr._load_sound_by_key("health-warning-style5")
    assert calls["health"] == "style5"

    assert mgr._load_sound_by_key("round-start-style6")
    assert calls["round"] == ("start", "style6")


def test_load_all_enabled_sounds_uses_gun_sound_master_switch(monkeypatch):
    from core.audio.audio_manager import AudioManager
    from config import config

    mgr = AudioManager()
    loaded = []

    monkeypatch.setattr(mgr, "ensure_styles_scanned", lambda: None)
    monkeypatch.setattr(mgr, "load_gun_sound", lambda gun, style: loaded.append((gun, style)) or True)
    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    for profile in GUN_SOUND_PROFILE_LIST:
        monkeypatch.setattr(config, profile.style_key, "0", raising=False)
    monkeypatch.setattr(config, "awp_enabled", False, raising=False)
    monkeypatch.setattr(config, "awp_style", "styleAwp", raising=False)

    mgr.load_all_enabled_sounds()

    assert loaded == [("awp", "styleAwp")]


def test_load_all_enabled_sounds_supports_new_gun_profiles(monkeypatch):
    from core.audio.audio_manager import AudioManager
    from config import config

    mgr = AudioManager()
    loaded = []

    monkeypatch.setattr(mgr, "ensure_styles_scanned", lambda: None)
    monkeypatch.setattr(mgr, "load_gun_sound", lambda gun, style: loaded.append((gun, style)) or True)
    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    for profile in GUN_SOUND_PROFILE_LIST:
        monkeypatch.setattr(config, profile.style_key, "0", raising=False)
    monkeypatch.setattr(config, "xm1014_style", "styleShotgun", raising=False)

    mgr.load_all_enabled_sounds()

    assert ("xm1014", "styleShotgun") in loaded


def test_load_all_enabled_sounds_skips_hidden_full_auto_gun_profiles(monkeypatch):
    from core.audio.audio_manager import AudioManager
    from config import config

    mgr = AudioManager()
    loaded = []

    monkeypatch.setattr(mgr, "ensure_styles_scanned", lambda: None)
    monkeypatch.setattr(mgr, "load_gun_sound", lambda gun, style: loaded.append((gun, style)) or True)
    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    for profile in GUN_SOUND_PROFILE_LIST:
        monkeypatch.setattr(config, profile.style_key, "0", raising=False)
    monkeypatch.setattr(config, "ak47_style", "styleAk", raising=False)
    monkeypatch.setattr(config, "awp_style", "styleAwp", raising=False)

    mgr.load_all_enabled_sounds()

    assert ("awp", "styleAwp") in loaded
    assert ("ak47", "styleAk") not in loaded
