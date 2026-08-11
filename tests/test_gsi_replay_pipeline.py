from __future__ import annotations

from copy import deepcopy

import gsi_handler_kills
import gsi_handler_sounds
import gsi_handler_special
from config import config


class _DummyAudioManager:
    def __init__(self):
        self.sounds = {}
        self.voices = {}
        self.play_sound_calls: list[tuple[str, str]] = []
        self.play_voice_calls: list[str] = []
        self.load_round_sound_calls: list[tuple[str, str]] = []
        self.play_sound_with_fade_calls: list[tuple[str, str]] = []

    def play_sound(self, key: str, channel_type: str = "kill_sound", **_kwargs):
        self.play_sound_calls.append((key, channel_type))
        return True

    def play_voice(self, key: str):
        self.play_voice_calls.append(key)

    def load_round_sound(self, round_type: str, style: str):
        self.load_round_sound_calls.append((round_type, style))
        return True

    def play_sound_with_fade(self, key: str, channel_type: str = "round_sound", **_kwargs):
        self.play_sound_with_fade_calls.append((key, channel_type))
        return True

    def load_health_warning_sound(self, _style: str):
        return True


class _DummyKeyboardController:
    def press(self, *_args, **_kwargs):
        return None

    def release(self, *_args, **_kwargs):
        return None


def _base_payload():
    return {
        "map": {"round": 1, "phase": "live"},
        "round": {"phase": "live", "win_team": ""},
        "player": {
            "steamid": "replay_steamid",
            "activity": "playing",
            "team": "CT",
            "state": {
                "health": 100,
                "round_kills": 0,
                "round_killhs": 0,
            },
            "weapons": {
                "weapon_0": {
                    "name": "weapon_awp",
                    "state": "active",
                    "ammo_clip": 5,
                },
                "weapon_1": {
                    "name": "weapon_hegrenade",
                    "state": "holstered",
                    "ammo_reserve": 1,
                },
            },
            "match_stats": {
                "mvps": 0,
            },
        },
    }


def _event(base: dict, mutator):
    data = deepcopy(base)
    mutator(data)
    return data


def _replay_all(handlers: list, events: list[dict]):
    for item in events:
        for handler in handlers:
            handler.process_data(item)


def test_replay_pipeline_covers_major_audio_categories(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_special, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)

    # global toggles
    monkeypatch.setattr(config, "player_steamid", "replay_steamid", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "mode", "3. 死斗模式", raising=False)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)

    # kill / voice
    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "weapon_kill_sounds", {}, raising=False)
    monkeypatch.setattr(config, "weapon_kill_voices", {}, raising=False)

    # gun / switch / reload / death
    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "awp_enabled", True, raising=False)
    monkeypatch.setattr(config, "awp_style", "styleAwp", raising=False)
    monkeypatch.setattr(config, "awp_mute_duration", 0.2, raising=False)
    monkeypatch.setattr(config, "switch_weapon_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_switch_sounds", {"weapon_m4a1": "styleSwitch"}, raising=False)
    monkeypatch.setattr(config, "reload_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_reload_sounds", {"weapon_m4a1": "styleReload"}, raising=False)
    monkeypatch.setattr(config, "death_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "death_sound_style", "styleDeath", raising=False)

    # special
    monkeypatch.setattr(config, "grenade_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "grenade_sound_styles", {"hegrenade": "styleG"}, raising=False)
    monkeypatch.setattr(config, "c4_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "c4_sound_style", "styleC4", raising=False)
    monkeypatch.setattr(config, "health_warning_enabled", True, raising=False)
    monkeypatch.setattr(config, "health_warning_threshold", 35, raising=False)
    monkeypatch.setattr(config, "health_warning_style", "styleH", raising=False)
    monkeypatch.setattr(config, "round_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "round_start_style", "styleStart", raising=False)
    monkeypatch.setattr(config, "round_action_style", "styleAction", raising=False)
    monkeypatch.setattr(config, "round_win_style", "styleWin", raising=False)
    monkeypatch.setattr(config, "round_lose_style", "styleLose", raising=False)
    monkeypatch.setattr(config, "round_mvp_style", "styleMvp", raising=False)

    kill_handler = gsi_handler_kills.GSIHandlerKills()
    sound_handler = gsi_handler_sounds.GSIHandlerSounds()
    special_handler = gsi_handler_special.GSIHandlerSpecial()
    # Keep replay deterministic without filesystem dependency.
    kill_handler._get_weapon_kill_sound_key = lambda *_args, **_kwargs: "kill-styleReplay-1"
    kill_handler._get_weapon_kill_voice_key = lambda *_args, **_kwargs: "voice-styleReplay-1"

    # avoid OS side effects
    sound_handler._mute_game_sound = lambda: None
    sound_handler._schedule_restore_volume = lambda _delay: None

    base = _base_payload()
    events = [
        _event(base, lambda d: None),  # baseline
        _event(base, lambda d: d["player"]["weapons"]["weapon_0"].update({"ammo_clip": 4})),  # awp fired
        _event(
            base,
            lambda d: d["player"]["weapons"]["weapon_0"].update({"name": "weapon_m4a1", "state": "active", "ammo_clip": 30}),
        ),  # switch
        _event(
            base,
            lambda d: d["player"]["weapons"]["weapon_0"].update({"name": "weapon_m4a1", "state": "reloading", "ammo_clip": 20}),
        ),  # reload
        _event(base, lambda d: d["player"]["state"].update({"round_kills": 1})),  # kill + voice
        _event(base, lambda d: d["player"]["state"].update({"health": 0})),  # death
        _event(
            base,
            lambda d: d["player"]["weapons"].update(
                {
                    "weapon_0": {"name": "weapon_hegrenade", "state": "active", "ammo_clip": 1, "ammo_reserve": 1},
                    "weapon_1": {"name": "weapon_awp", "state": "holstered", "ammo_clip": 4},
                }
            ),
        ),  # hold grenade
        _event(
            base,
            lambda d: d["player"]["weapons"].update(
                {
                    "weapon_0": {"name": "weapon_m4a1", "state": "active", "ammo_clip": 30},
                    "weapon_1": {"name": "weapon_awp", "state": "holstered", "ammo_clip": 4},
                }
            ),
        ),  # grenade thrown (count drop)
        _event(base, lambda d: d.update({"bomb": "planted"})),  # c4
        _event(base, lambda d: d["player"]["state"].update({"health": 20})),  # health warning
        _event(base, lambda d: d["round"].update({"phase": "freezetime"})),  # round start
        _event(base, lambda d: d["round"].update({"phase": "live"})),  # action
        _event(base, lambda d: d["round"].update({"phase": "over", "win_team": "T"})),  # lose
    ]

    _replay_all([kill_handler, sound_handler, special_handler], events)

    keys = [key for key, _ in dummy_audio.play_sound_calls]

    assert any(k.startswith("kill-") for k in keys)
    assert any(k.startswith("gun-awp-") for k in keys)
    assert any(k.startswith("switch-") for k in keys)
    assert any(k.startswith("reload-") for k in keys)
    assert any(k.startswith("death-") for k in keys)
    assert any(k.startswith("grenade-") for k in keys)
    assert any(k.startswith("c4-planted-") for k in keys)
    assert any(k.startswith("health-warning-") for k in keys)
    assert any(k.startswith("round-") and c == "round_sound" for k, c in dummy_audio.play_sound_with_fade_calls)
    assert any(v.startswith("voice-") for v in dummy_audio.play_voice_calls)


def test_replay_pipeline_respects_disabled_flags(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_special, "audio_manager", dummy_audio)
    monkeypatch.setattr(gsi_handler_sounds, "Controller", _DummyKeyboardController)

    monkeypatch.setattr(config, "player_steamid", "replay_steamid", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "mode", "3. 死斗模式", raising=False)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)

    # disable most features
    monkeypatch.setattr(config, "kill_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "gun_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "awp_enabled", False, raising=False)
    monkeypatch.setattr(config, "switch_weapon_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "reload_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "death_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "grenade_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "c4_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "health_warning_enabled", False, raising=False)
    monkeypatch.setattr(config, "round_sound_enabled", False, raising=False)

    kill_handler = gsi_handler_kills.GSIHandlerKills()
    sound_handler = gsi_handler_sounds.GSIHandlerSounds()
    special_handler = gsi_handler_special.GSIHandlerSpecial()
    kill_handler._get_weapon_kill_sound_key = lambda *_args, **_kwargs: "kill-styleReplay-1"
    kill_handler._get_weapon_kill_voice_key = lambda *_args, **_kwargs: "voice-styleReplay-1"

    sound_handler._mute_game_sound = lambda: None
    sound_handler._schedule_restore_volume = lambda _delay: None

    base = _base_payload()
    events = [
        _event(base, lambda d: d["player"]["state"].update({"round_kills": 1, "health": 0})),
        _event(base, lambda d: d.update({"bomb": "planted"})),
        _event(base, lambda d: d["round"].update({"phase": "over", "win_team": "T"})),
    ]
    _replay_all([kill_handler, sound_handler, special_handler], events)

    assert dummy_audio.play_sound_calls == []
    assert dummy_audio.play_voice_calls == []
