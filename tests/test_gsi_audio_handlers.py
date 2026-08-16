# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import time

import gsi_handler_kills
import gsi_handler_special
import gsi_handler_sounds
import pytest
from config import config


class _DummyAudioManager:
    def __init__(self):
        self.sounds = {}
        self.voices = {}
        self.play_sound_calls: list[tuple[str, str]] = []
        self.play_voice_calls: list[str] = []
        self.load_round_sound_calls: list[tuple[str, str]] = []
        self.load_c4_sound_calls: list[tuple[str, str]] = []
        self.play_sound_with_fade_calls: list[tuple[str, str]] = []

    def play_sound(self, key: str, channel_type: str = "kill_sound", **_kwargs):
        self.play_sound_calls.append((key, channel_type))
        return True

    def play_voice(self, key: str):
        self.play_voice_calls.append(key)

    def load_round_sound(self, round_type: str, style: str):
        self.load_round_sound_calls.append((round_type, style))
        return True

    def load_health_warning_sound(self, _style: str):
        return True

    def load_c4_sound(self, style: str, event_key: str = "planted"):
        self.load_c4_sound_calls.append((event_key, style))
        return True

    def play_sound_with_fade(self, key: str, channel_type: str = "round_sound", **_kwargs):
        self.play_sound_with_fade_calls.append((key, channel_type))
        return True


class _DummyKeyboardController:
    def press(self, *_args, **_kwargs):
        return None

    def release(self, *_args, **_kwargs):
        return None


def _kill_payload(round_kills: int = 1, round_killhs: int = 0, match_kills: int | None = None):
    if match_kills is None:
        match_kills = round_kills
    return {
        "map": {"round": 1, "phase": "live"},
        "round": {"phase": "live"},
        "player": {
            "steamid": "test_steamid",
            "activity": "playing",
            "match_stats": {"kills": match_kills},
            "state": {
                "health": 100,
                "round_kills": round_kills,
                "round_killhs": round_killhs,
            },
            "weapons": {
                "weapon_0": {
                    "name": "weapon_ak47",
                    "state": "active",
                }
            },
        },
    }


def test_kill_handler_plays_voice_even_if_not_preloaded(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "3. 死斗模式", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", lambda *_args, **_kwargs: "kill-styleA-1")
    monkeypatch.setattr(handler, "_get_weapon_kill_voice_key", lambda *_args, **_kwargs: "voice-styleA-1")

    handler.process_data(_kill_payload(round_kills=1, round_killhs=0))

    assert ("kill-styleA-1", "kill_sound") in dummy_audio.play_sound_calls
    assert "voice-styleA-1" in dummy_audio.play_voice_calls


def test_kill_handler_does_not_drop_kill_when_activity_fluctuates(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 官匹竞技", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.previous_round = 1  # 避免本次测试触发新回合初始化路径
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", lambda *_args, **_kwargs: "kill-styleA-1")

    payload = _kill_payload(round_kills=1, round_killhs=0)
    payload["player"]["activity"] = "menu"  # 模拟 activity 抖动
    handler.process_data(payload)

    assert ("kill-styleA-1", "kill_sound") in dummy_audio.play_sound_calls


def test_kill_handler_does_not_drop_rapid_consecutive_kills_with_default_debounce(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 瀹樺尮绔炴妧", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.previous_round = 1
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", lambda *_args, **_kwargs: "kill-styleA-1")

    handler.process_data(_kill_payload(round_kills=1, round_killhs=0, match_kills=20))
    handler.process_data(_kill_payload(round_kills=2, round_killhs=0, match_kills=21))

    played = [k for k, c in dummy_audio.play_sound_calls if c == "kill_sound" and k == "kill-styleA-1"]
    assert len(played) == 2


def test_kill_handler_fallback_to_default_key_when_style_key_fails(monkeypatch):
    class _FailPreferredAudioManager(_DummyAudioManager):
        def play_sound(self, key: str, channel_type: str = "kill_sound", **_kwargs):
            self.play_sound_calls.append((key, channel_type))
            if key == "kill-styleA-1":
                return False
            return True

    dummy_audio = _FailPreferredAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 官匹竞技", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.previous_round = 1
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", lambda *_args, **_kwargs: "kill-styleA-1")

    handler.process_data(_kill_payload(round_kills=1, round_killhs=0))

    # 先尝试风格key，再回退到默认 kill-1
    assert ("kill-styleA-1", "kill_sound") in dummy_audio.play_sound_calls
    assert ("kill-1", "kill_sound") in dummy_audio.play_sound_calls


def test_kill_handler_no_replay_after_round_over(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 官匹竞技", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.debounce_delay = 0.0
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", lambda *_args, **_kwargs: "kill-styleA-1")

    baseline = _kill_payload(round_kills=0, round_killhs=0)
    baseline["map"]["round"] = 1
    baseline["map"]["phase"] = "live"
    baseline["round"]["phase"] = "live"
    handler.process_data(baseline)

    round1_kill = _kill_payload(round_kills=1, round_killhs=0)
    round1_kill["map"]["round"] = 1
    round1_kill["map"]["phase"] = "live"
    round1_kill["round"]["phase"] = "live"
    handler.process_data(round1_kill)

    round1_over = _kill_payload(round_kills=1, round_killhs=0)
    round1_over["map"]["round"] = 1
    round1_over["map"]["phase"] = "live"
    round1_over["round"]["phase"] = "over"
    handler.process_data(round1_over)

    round2_freezetime = _kill_payload(round_kills=1, round_killhs=0)
    round2_freezetime["map"]["round"] = 2
    round2_freezetime["map"]["phase"] = "live"
    round2_freezetime["round"]["phase"] = "freezetime"
    handler.process_data(round2_freezetime)

    round2_live_zero = _kill_payload(round_kills=0, round_killhs=0)
    round2_live_zero["map"]["round"] = 2
    round2_live_zero["map"]["phase"] = "live"
    round2_live_zero["round"]["phase"] = "live"
    handler.process_data(round2_live_zero)

    round2_first_kill = _kill_payload(round_kills=1, round_killhs=0)
    round2_first_kill["map"]["round"] = 2
    round2_first_kill["map"]["phase"] = "live"
    round2_first_kill["round"]["phase"] = "live"
    handler.process_data(round2_first_kill)

    played = [k for k, c in dummy_audio.play_sound_calls if c == "kill_sound" and k == "kill-styleA-1"]
    assert len(played) == 2


def test_kill_handler_allows_final_kill_when_phase_is_over(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 官匹竞技", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.debounce_delay = 0.0
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", lambda *_args, **_kwargs: "kill-styleA-1")

    baseline = _kill_payload(round_kills=0, round_killhs=0, match_kills=5)
    baseline["map"]["round"] = 1
    baseline["map"]["phase"] = "live"
    baseline["round"]["phase"] = "live"
    handler.process_data(baseline)

    # 最终击杀数据在 over 阶段才到达
    final_kill_on_over = _kill_payload(round_kills=1, round_killhs=0, match_kills=6)
    final_kill_on_over["player"]["activity"] = "menu"
    final_kill_on_over["map"]["round"] = 1
    final_kill_on_over["map"]["phase"] = "live"
    final_kill_on_over["round"]["phase"] = "over"
    handler.process_data(final_kill_on_over)

    # over 阶段重复包不应重复播放
    handler.process_data(final_kill_on_over)

    played = [k for k, c in dummy_audio.play_sound_calls if c == "kill_sound" and k == "kill-styleA-1"]
    assert len(played) == 1


def test_kill_handler_does_not_play_when_over_delta_has_no_match_kill_growth(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 官匹竞技", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.debounce_delay = 0.0
    handler.previous_round = 1
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", lambda *_args, **_kwargs: "kill-styleA-1")

    baseline = _kill_payload(round_kills=0, round_killhs=0, match_kills=10)
    baseline["map"]["round"] = 1
    baseline["round"]["phase"] = "live"
    handler.process_data(baseline)

    # over 阶段仅 round_kills 变化，但总击杀不变，视为非本人最终击杀，不应播放
    over_not_my_final = _kill_payload(round_kills=1, round_killhs=0, match_kills=10)
    over_not_my_final["player"]["activity"] = "menu"
    over_not_my_final["map"]["round"] = 1
    over_not_my_final["round"]["phase"] = "over"
    handler.process_data(over_not_my_final)

    played = [k for k, c in dummy_audio.play_sound_calls if c == "kill_sound" and k == "kill-styleA-1"]
    assert len(played) == 0


def test_kill_handler_non_live_with_menu_only_syncs_counter(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 官匹竞技", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.debounce_delay = 0.0
    handler.previous_round = 1
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", lambda *_args, **_kwargs: "kill-styleA-1")

    menu_freezetime = _kill_payload(round_kills=1, round_killhs=0)
    menu_freezetime["player"]["activity"] = "menu"
    menu_freezetime["round"]["phase"] = "freezetime"
    handler.process_data(menu_freezetime)

    menu_live = _kill_payload(round_kills=2, round_killhs=0)
    menu_live["player"]["activity"] = "menu"
    menu_live["round"]["phase"] = "live"
    handler.process_data(menu_live)

    played = [k for k, c in dummy_audio.play_sound_calls if c == "kill_sound" and k == "kill-styleA-1"]
    assert len(played) == 1


def test_kill_handler_round_lock_releases_on_zero_when_phase_missing(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 官匹竞技", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.debounce_delay = 0.0
    handler.previous_round = 1
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", lambda *_args, **_kwargs: "kill-styleA-1")

    round1_kill = _kill_payload(round_kills=1, round_killhs=0)
    round1_kill["map"]["round"] = 1
    round1_kill["round"]["phase"] = "live"
    handler.process_data(round1_kill)

    round2_missing_phase_stale = _kill_payload(round_kills=1, round_killhs=0)
    round2_missing_phase_stale["map"]["round"] = 2
    round2_missing_phase_stale["map"].pop("phase", None)
    round2_missing_phase_stale.pop("round", None)
    handler.process_data(round2_missing_phase_stale)

    round2_missing_phase_zero = _kill_payload(round_kills=0, round_killhs=0)
    round2_missing_phase_zero["map"]["round"] = 2
    round2_missing_phase_zero["map"].pop("phase", None)
    round2_missing_phase_zero.pop("round", None)
    handler.process_data(round2_missing_phase_zero)

    round2_live_first_kill = _kill_payload(round_kills=1, round_killhs=0)
    round2_live_first_kill["map"]["round"] = 2
    round2_live_first_kill["map"]["phase"] = "live"
    round2_live_first_kill["round"]["phase"] = "live"
    handler.process_data(round2_live_first_kill)

    played = [k for k, c in dummy_audio.play_sound_calls if c == "kill_sound" and k == "kill-styleA-1"]
    assert len(played) == 2


def test_switch_sound_uses_lazy_key_loading(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)

    monkeypatch.setattr(config, "weapon_switch_sounds", {"weapon_m4a1": "styleSwitch"}, raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler.last_active_weapon = "weapon_ak47"

    payload = {
        "player": {
            "weapons": {
                "weapon_0": {
                    "name": "weapon_m4a1",
                    "state": "active",
                }
            }
        }
    }
    handler._process_weapon_switch_sound(payload)

    assert ("switch-weapon_m4a1-styleSwitch", "switch_weapon") in dummy_audio.play_sound_calls


def test_reload_sound_uses_lazy_key_loading(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)

    monkeypatch.setattr(config, "weapon_reload_sounds", {"weapon_m4a1": "styleReload"}, raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()

    payload = {
        "player": {
            "weapons": {
                "weapon_0": {
                    "name": "weapon_m4a1",
                    "state": "reloading",
                }
            }
        }
    }
    handler._process_reload_sound(payload)

    assert ("reload-weapon_m4a1-styleReload", "reload") in dummy_audio.play_sound_calls


def test_death_sound_uses_lazy_key_loading(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)

    monkeypatch.setattr(config, "death_sound_style", "styleDeath", raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler.last_health = 100
    duck_calls: list[bool] = []
    handler._apply_death_sound_duck = lambda *, mute_only: duck_calls.append(mute_only)

    payload = {
        "player": {
            "state": {
                "health": 0,
            }
        }
    }
    handler._process_death_sound(payload)

    assert duck_calls == [False]
    # v2.2.1: 死亡音效改走独立通道 death_sound（旧版挤 kill_sound=ch1，互杀被drop）
    assert ("death-styleDeath", "death_sound") in dummy_audio.play_sound_calls


def test_death_sound_style_zero_uses_ducking_without_playback(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)

    monkeypatch.setattr(config, "death_sound_style", "0", raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler.last_health = 100
    duck_calls: list[bool] = []
    handler._apply_death_sound_duck = lambda *, mute_only: duck_calls.append(mute_only)

    payload = {
        "player": {
            "state": {
                "health": 0,
            }
        }
    }
    handler._process_death_sound(payload)

    assert duck_calls == [True]
    assert dummy_audio.play_sound_calls == []


def test_gsi_sounds_restores_lingering_duck_when_gun_and_death_features_are_disabled(monkeypatch):
    class _DummyDucker:
        def __init__(self):
            self.restore_calls = 0

        def is_ducked(self):
            return True

        def restore(self):
            self.restore_calls += 1
            return True

    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)
    monkeypatch.setattr(gsi_handler_sounds, "is_gun_sound_master_enabled", lambda _cfg: False)

    monkeypatch.setattr(config, "death_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler._game_audio_ducker = _DummyDucker()

    payload = {
        "player": {
            "steamid": "test_steamid",
            "activity": "playing",
            "weapons": {
                "weapon_0": {
                    "name": "weapon_awp",
                    "state": "active",
                    "ammo_clip": 4,
                }
            },
        }
    }

    handler.process_data(payload)

    assert handler._game_audio_ducker.restore_calls == 1


def test_awp_sound_uses_lazy_key_loading(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)

    monkeypatch.setattr(config, "awp_style", "styleAwp", raising=False)
    monkeypatch.setattr(config, "awp_mute_duration", 0.3, raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler._mute_game_sound = lambda: None
    handler._schedule_restore_volume = lambda _delay: None
    handler.previous_awp_ammo["weapon_0"] = 5
    handler.last_awp_fire_time = 0.0

    payload = {
        "player": {
            "weapons": {
                "weapon_0": {
                    "name": "weapon_awp",
                    "state": "active",
                    "ammo_clip": 4,
                }
            }
        }
    }
    handler._process_awp_sound(payload)

    assert ("gun-awp-styleAwp", "gun_sound") in dummy_audio.play_sound_calls


def test_semi_auto_shotgun_sound_uses_lazy_key_loading_for_supported_profile(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)

    monkeypatch.setattr(config, "xm1014_style", "styleXm", raising=False)
    monkeypatch.setattr(config, "xm1014_mute_duration", 0.3, raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler.previous_xm1014_ammo["weapon_0"] = 7
    handler.last_xm1014_fire_time = 0.0

    payload = {
        "player": {
            "weapons": {
                "weapon_0": {
                    "name": "weapon_xm1014",
                    "state": "active",
                    "ammo_clip": 6,
                }
            }
        }
    }
    handler._process_gun_sound("xm1014", payload)

    assert ("gun-xm1014-styleXm", "gun_sound") in dummy_audio.play_sound_calls


def test_usp_burst_ducking_becomes_more_aggressive(monkeypatch):
    class _DummyDucker:
        def __init__(self):
            self.calls: list[tuple[float, dict[str, float | int]]] = []

        def duck_for(self, delay: float, **kwargs):
            self.calls.append((delay, kwargs))
            return True

    dummy_ducker = _DummyDucker()
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)

    monkeypatch.setattr(config, "usp_style", "styleUsp", raising=False)
    monkeypatch.setattr(config, "usp_mute_duration", 0.2, raising=False)
    monkeypatch.setattr(config, "gun_sound_duck_ratio", 0.18, raising=False)
    monkeypatch.setattr(config, "gun_sound_duck_release_ms", 120, raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler._game_audio_ducker = dummy_ducker
    profile = gsi_handler_sounds.GUN_SOUND_PROFILES["usp"]

    first_plan = handler._apply_gun_sound_duck(profile, last_fire_time=0.0, current_time=10.0)
    second_plan = handler._apply_gun_sound_duck(profile, last_fire_time=10.0, current_time=10.16)

    assert len(dummy_ducker.calls) == 2
    first_delay, first_kwargs = dummy_ducker.calls[0]
    second_delay, second_kwargs = dummy_ducker.calls[1]

    assert first_delay == pytest.approx(first_plan.hold_duration)
    assert second_delay == pytest.approx(second_plan.hold_duration)
    assert second_delay > first_delay
    assert second_kwargs["peak_ratio"] < first_kwargs["peak_ratio"]
    assert second_kwargs["sustain_ratio"] < first_kwargs["sustain_ratio"]
    assert second_kwargs["release_ms"] > first_kwargs["release_ms"]


def test_death_sound_ducking_uses_aggressive_runtime_plan(monkeypatch):
    class _DummyDucker:
        def __init__(self):
            self.calls: list[tuple[float, dict[str, float | int]]] = []

        def duck_for(self, delay: float, **kwargs):
            self.calls.append((delay, kwargs))
            return True

    dummy_ducker = _DummyDucker()
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)
    monkeypatch.setattr(config, "gun_sound_duck_ratio", 0.18, raising=False)
    monkeypatch.setattr(config, "gun_sound_duck_release_ms", 120, raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler._game_audio_ducker = dummy_ducker

    handler._apply_death_sound_duck(mute_only=False)

    assert len(dummy_ducker.calls) == 1
    delay, kwargs = dummy_ducker.calls[0]
    assert delay == pytest.approx(gsi_handler_sounds.DEATH_SOUND_HOLD_DURATION)
    assert kwargs["peak_ratio"] == pytest.approx(0.0)
    assert kwargs["peak_ms"] == gsi_handler_sounds.DEATH_SOUND_PEAK_MS
    assert kwargs["sustain_ratio"] == pytest.approx(0.081)
    assert kwargs["release_ms"] == 192


def test_process_data_uses_gun_sound_master_switch(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)

    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "awp_enabled", False, raising=False)
    monkeypatch.setattr(config, "awp_style", "styleAwp", raising=False)
    monkeypatch.setattr(config, "awp_mute_duration", 0.2, raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "death_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "switch_weapon_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "reload_sound_enabled", False, raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler._mute_game_sound = lambda: None
    handler._schedule_restore_volume = lambda _delay: None
    handler.previous_awp_ammo["weapon_0"] = 5

    payload = {
        "player": {
            "steamid": "test_steamid",
            "activity": "playing",
            "weapons": {
                "weapon_0": {
                    "name": "weapon_awp",
                    "state": "active",
                    "ammo_clip": 4,
                }
            },
        }
    }

    handler.process_data(payload)

    assert ("gun-awp-styleAwp", "gun_sound") in dummy_audio.play_sound_calls


def test_gsi_sounds_updates_magnifier_weapon_to_empty_when_active_weapon_missing(monkeypatch):
    class _DummyMagnifierComponent:
        def __init__(self):
            self.updates: list[str] = []

        def update_current_weapon(self, weapon_name: str):
            self.updates.append(weapon_name)

    dummy_audio = _DummyAudioManager()
    dummy_magnifier = _DummyMagnifierComponent()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)
    monkeypatch.setattr(config, "gun_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "awp_enabled", False, raising=False)
    monkeypatch.setattr(config, "deagle_enabled", False, raising=False)
    monkeypatch.setattr(config, "usp_enabled", False, raising=False)
    monkeypatch.setattr(config, "revolver_enabled", False, raising=False)
    monkeypatch.setattr(config, "ssg08_enabled", False, raising=False)
    monkeypatch.setattr(config, "scar20_enabled", False, raising=False)
    monkeypatch.setattr(config, "g3sg1_enabled", False, raising=False)
    monkeypatch.setattr(config, "nova_enabled", False, raising=False)
    monkeypatch.setattr(config, "mag7_enabled", False, raising=False)
    monkeypatch.setattr(config, "sawedoff_enabled", False, raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler.set_magnifier_component(dummy_magnifier)

    active_payload = {
        "player": {
            "steamid": "test_steamid",
            "activity": "playing",
            "weapons": {
                "weapon_0": {
                    "name": "weapon_awp",
                    "state": "active",
                    "ammo_clip": 4,
                }
            },
        }
    }
    handler.process_data(active_payload)

    empty_payload = {
        "player": {
            "steamid": "test_steamid",
            "activity": "playing",
            "weapons": {},
        }
    }
    handler.process_data(empty_payload)

    assert dummy_magnifier.updates == ["weapon_awp", ""]


def test_gsi_sounds_updates_magnifier_weapon_even_when_activity_fluctuates(monkeypatch):
    class _DummyMagnifierComponent:
        def __init__(self):
            self.updates: list[str] = []

        def update_current_weapon(self, weapon_name: str):
            self.updates.append(weapon_name)

    dummy_audio = _DummyAudioManager()
    dummy_magnifier = _DummyMagnifierComponent()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)
    monkeypatch.setattr(config, "gun_sound_enabled", False, raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler.set_magnifier_component(dummy_magnifier)

    payload = {
        "player": {
            "steamid": "test_steamid",
            "activity": "menu",
            "weapons": {
                "weapon_0": {
                    "name": "weapon_awp",
                    "state": "active",
                    "ammo_clip": 4,
                }
            },
        }
    }
    handler.process_data(payload)

    assert dummy_magnifier.updates == ["weapon_awp"]


def test_gsi_sounds_current_weapon_falls_back_to_non_holstered_weapon(monkeypatch):
    class _DummyMagnifierComponent:
        def __init__(self):
            self.updates: list[str] = []

        def update_current_weapon(self, weapon_name: str):
            self.updates.append(weapon_name)

    dummy_audio = _DummyAudioManager()
    dummy_magnifier = _DummyMagnifierComponent()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)
    monkeypatch.setattr(config, "gun_sound_enabled", False, raising=False)

    handler = gsi_handler_sounds.GSIHandlerSounds()
    handler.set_magnifier_component(dummy_magnifier)

    payload = {
        "player": {
            "steamid": "test_steamid",
            "activity": "playing",
            "weapons": {
                "weapon_0": {
                    "name": "weapon_knife",
                    "state": "holstered",
                },
                "weapon_1": {
                    "name": "weapon_awp",
                    "state": "",
                    "ammo_clip": 4,
                },
            },
        }
    }
    handler.process_data(payload)

    assert dummy_magnifier.updates == ["weapon_awp"]


def test_special_grenade_and_c4_use_runtime_audio(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_special, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "grenade_sound_styles", {"hegrenade": "styleG"}, raising=False)
    monkeypatch.setattr(config, "c4_sound_style", "styleC4", raising=False)

    handler = gsi_handler_special.GSIHandlerSpecial()
    handler._play_grenade_sound("hegrenade")
    handler._process_bomb_events({"bomb": "planted"})

    assert ("grenade-hegrenade-styleG", "grenade_sound") in dummy_audio.play_sound_calls
    assert ("c4-planted-styleC4", "c4_sound") in dummy_audio.play_sound_calls


def test_special_c4_detects_planted_when_activity_not_playing(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_special, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "c4_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "c4_sound_style", "styleC4", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_special.GSIHandlerSpecial()
    payload = {
        "map": {"round": 5, "phase": "planted"},
        "round": {"phase": "live"},
        "bomb": "planted",
        "player": {
            "steamid": "test_steamid",
            "activity": "menu",
            "state": {"health": 100},
            "match_stats": {"mvps": 0},
        },
    }
    handler.process_data(payload)

    assert ("c4-planted-styleC4", "c4_sound") in dummy_audio.play_sound_calls


def test_special_c4_does_not_play_when_planting_canceled(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_special, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "c4_sound_style", "styleC4", raising=False)

    handler = gsi_handler_special.GSIHandlerSpecial()
    handler._process_bomb_events({"bomb": "planting"})
    handler._process_bomb_events({"bomb": "carried"})

    c4_plays = [k for k, c in dummy_audio.play_sound_calls if c == "c4_sound" and k.startswith("c4-planted-")]
    assert c4_plays == []


def test_special_health_warning_uses_runtime_audio(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_special, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "health_warning_threshold", 35, raising=False)
    monkeypatch.setattr(config, "health_warning_style", "styleH", raising=False)

    handler = gsi_handler_special.GSIHandlerSpecial()
    handler.previous_health = 100
    handler.health_warning_played = False
    handler.health_warning_cooldown = 0

    payload = {
        "player": {
            "state": {
                "health": 20,
            }
        }
    }
    handler._process_health_warning(payload)

    assert ("health-warning-styleH", "health_warning") in dummy_audio.play_sound_calls


def test_special_round_sounds_use_runtime_audio(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_special, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "round_start_style", "styleStart", raising=False)
    monkeypatch.setattr(config, "round_action_style", "styleAction", raising=False)
    monkeypatch.setattr(config, "round_win_style", "styleWin", raising=False)
    monkeypatch.setattr(config, "round_lose_style", "styleLose", raising=False)
    monkeypatch.setattr(config, "round_mvp_style", "styleMvp", raising=False)

    handler = gsi_handler_special.GSIHandlerSpecial()
    # 五个 `_play_round_*` 方法已合并成 `_play_event(group, key)`（2026-08-15）。
    # 它们本来就是逐字复制、只差三个字面量的五份代码。
    for event_key in ("start", "action", "win", "lose", "mvp"):
        handler._play_event("round", event_key)

    expected_loads = {
        ("start", "styleStart"),
        ("action", "styleAction"),
        ("win", "styleWin"),
        ("lose", "styleLose"),
        ("mvp", "styleMvp"),
    }
    expected_plays = {
        ("round-start-styleStart", "round_sound"),
        ("round-action-styleAction", "round_sound"),
        ("round-win-styleWin", "round_sound"),
        ("round-lose-styleLose", "round_sound"),
        ("round-mvp-styleMvp", "round_sound"),
    }

    assert expected_loads.issubset(set(dummy_audio.load_round_sound_calls))
    assert expected_plays.issubset(set(dummy_audio.play_sound_with_fade_calls))


def test_kill_handler_headshot_batched_delta_is_conservative(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 官匹竞技", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.debounce_delay = 0.0
    handler.previous_round = 1
    captured = []

    def _capture_headshot(_weapon, _kills, is_headshot=False):
        captured.append(bool(is_headshot))
        return "kill-styleA-1"

    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", _capture_headshot)

    first_kill = _kill_payload(round_kills=1, round_killhs=0, match_kills=20)
    first_kill["map"]["round"] = 1
    handler.process_data(first_kill)

    batched_two_kills_one_hs = _kill_payload(round_kills=3, round_killhs=1, match_kills=22)
    batched_two_kills_one_hs["map"]["round"] = 1
    handler.process_data(batched_two_kills_one_hs)

    # 第二次触发对应合包更新，headshot应为保守False
    assert len(captured) >= 2
    assert captured[-1] is False


def test_get_weapon_kill_sound_key_returns_none_when_weapon_explicitly_disabled(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_kill_sounds", {"weapon_ak47": "0"}, raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()

    assert handler._get_weapon_kill_sound_key("weapon_ak47", 2, False) is None


def test_get_weapon_kill_voice_key_returns_none_for_legacy_disabled_dict(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_voice_enabled", True, raising=False)
    monkeypatch.setattr(
        config,
        "weapon_kill_voices",
        {"weapon_ak47": {"enabled": False, "style": "塑水"}},
        raising=False,
    )

    handler = gsi_handler_kills.GSIHandlerKills()

    assert handler._get_weapon_kill_voice_key("weapon_ak47", 2, False) is None


def test_kill_handler_skips_audio_when_weapon_style_is_disabled(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "3. 死斗模式", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "", raising=False)
    monkeypatch.setattr(config, "weapon_kill_sounds", {"weapon_ak47": "0"}, raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.process_data(_kill_payload(round_kills=1, round_killhs=0))

    assert dummy_audio.play_sound_calls == []


def test_deathmatch_positive_counter_reset_starts_new_life_without_reusing_old_virtual_keys(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "3. 死斗模式", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.debounce_delay = 0.0
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", lambda *_args, **_kwargs: "kill-styleA-1")

    first_life_kill_1 = _kill_payload(round_kills=1, round_killhs=0, match_kills=1)
    handler.process_data(first_life_kill_1)

    first_life_kill_2 = _kill_payload(round_kills=2, round_killhs=0, match_kills=2)
    handler.process_data(first_life_kill_2)

    # 未先收到 0 包，下一次看到的就是新生命里的第一杀（2 -> 1）
    next_life_first_seen_kill = _kill_payload(round_kills=1, round_killhs=0, match_kills=3)
    handler.process_data(next_life_first_seen_kill)

    played = [k for k, c in dummy_audio.play_sound_calls if c == "kill_sound" and k == "kill-styleA-1"]
    assert len(played) == 3


def test_deathmatch_trade_packet_with_health_zero_still_plays_once(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "3. 死斗模式", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.debounce_delay = 0.0
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key", lambda *_args, **_kwargs: "kill-styleA-1")

    trade_payload = _kill_payload(round_kills=1, round_killhs=0, match_kills=1)
    trade_payload["player"]["activity"] = "menu"
    trade_payload["player"]["state"]["health"] = 0

    handler.process_data(trade_payload)
    handler.process_data(trade_payload)

    played = [k for k, c in dummy_audio.play_sound_calls if c == "kill_sound" and k == "kill-styleA-1"]
    assert len(played) == 1


def test_resolve_kill_weapon_ignores_previous_kill_when_current_frame_has_no_reliable_weapon(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.last_kill_weapon = "weapon_ak47"
    handler.last_confirmed_fire_weapon = "weapon_ak47"
    handler.last_confirmed_fire_weapon_time = time.time()
    handler.frame_has_weapon_snapshot = True
    handler.frame_active_weapon = ""
    handler.frame_inferred_fire_weapon = ""

    assert handler._resolve_kill_weapon(time.time()) == ""


def test_resolve_kill_weapon_keeps_recent_confirmed_fire_when_snapshot_missing(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.last_confirmed_fire_weapon = "weapon_ak47"
    handler.last_confirmed_fire_weapon_time = time.time()
    handler.frame_has_weapon_snapshot = False
    handler.frame_active_weapon = ""
    handler.frame_inferred_fire_weapon = ""

    assert handler._resolve_kill_weapon(time.time()) == "weapon_ak47"


def test_kill_handler_does_not_reuse_previous_weapon_style_when_weapon_is_unresolved(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 官匹竞技", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()
    handler.previous_round = 1
    handler.current_weapon = "weapon_ak47"
    handler.last_kill_weapon = "weapon_ak47"
    handler.last_confirmed_fire_weapon = "weapon_ak47"
    handler.last_confirmed_fire_weapon_time = time.time() - 5

    monkeypatch.setattr(
        handler,
        "_get_weapon_kill_sound_key",
        lambda weapon_name, *_args, **_kwargs: "kill-styleA-1" if weapon_name == "weapon_ak47" else None,
    )

    payload = _kill_payload(round_kills=1, round_killhs=0)
    payload["player"]["weapons"] = {}
    handler.process_data(payload)

    assert dummy_audio.play_sound_calls == []


def test_get_weapon_kill_sound_key_keeps_generic_fallback_for_unmapped_weapon(monkeypatch):
    class _FallbackAudioManager(_DummyAudioManager):
        def _load_sound_by_key(self, key: str):
            return key == "kill-3"

    dummy_audio = _FallbackAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)

    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_kill_sounds", {}, raising=False)

    handler = gsi_handler_kills.GSIHandlerKills()

    assert handler._get_weapon_kill_sound_key("weapon_new", 3, False) == "kill-3"
