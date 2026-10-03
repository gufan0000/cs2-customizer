# SPDX-License-Identifier: GPL-3.0-or-later
"""批 129：GSI 边界事件那一轮审查（死后观战 / 中途启动 / 重连 / 换局 / 阵亡那一帧）逮到的八条。

判据的共同形状照旧：喂一串 GSI 帧，看**报了哪些事件 / 算出什么颜色 / 认成死还是活**。
每条都配了一个「对照组」：同一个判据把触发条件拿掉之后必须看得到原行为 ——
否则它可能是因为别的原因绿着（替身少接了一根线、帧里少了一个字段）。

分母：批 129 审查员「GSI 边界状态」视角报的 15 条里，核实为真、本批修的 8 条（其余进候选，见档案 B129）。
"""

from __future__ import annotations

import pytest

import gsi_handler_music
import gsi_handler_sounds
import gsi_handler_special
import gsi_handler_utility
from config import config
from core.hud.rule_model import get_default_hud_rules
from core.hud.runtime_engine import RuntimeHudEngine

ME = "76561198000000001"
MATE = "76561198000000002"


class _ImmediateTimer:
    def __init__(self, _interval, function, args=None, kwargs=None):
        self._fn, self._args, self._kwargs = function, args or [], kwargs or {}
        self.daemon = True

    def start(self):
        self._fn(*self._args, **self._kwargs)

    def cancel(self):
        return None


def _frame(*, steamid=ME, team="CT", health=100, map_name="de_dust2", phase="live",
           round_no=3, round_phase="live", win_team=None, weapons=None, activity="playing"):
    data = {
        "provider": {"steamid": ME},
        "player": {"steamid": steamid, "team": team, "activity": activity,
                   "state": {"health": health}},
    }
    if map_name is not None:
        data["map"] = {"name": map_name, "phase": phase, "round": round_no}
        data["round"] = {"phase": round_phase}
        if win_team:
            data["round"]["win_team"] = win_team
    if weapons is not None:
        data["player"]["weapons"] = weapons
    return data


# ── 特殊音效（回合 / C4 / 投掷物）────────────────────────────────────────

@pytest.fixture
def special(monkeypatch):
    monkeypatch.setattr(config, "player_steamid", ME, raising=False)
    monkeypatch.setattr(config, "round_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "c4_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "grenade_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", True, raising=False)   # 产品默认值
    monkeypatch.setattr(gsi_handler_special.threading, "Timer", _ImmediateTimer)
    h = gsi_handler_special.GSIHandlerSpecial()
    h.events = []
    monkeypatch.setattr(h, "_play_event", lambda g, k: (h.events.append((g, k)), True)[1])
    monkeypatch.setattr(h, "_play_grenade_sound", lambda t: h.events.append(("grenade", t)))
    return h


def test_dying_does_not_silence_the_round_result(special):
    """⭐⭐ 默认开着观战静音时，人一死整帧就被 return 掉 —— 回合胜负 / MVP / C4 全不响。
    回合结束时多半已经阵亡，所以这几乎等于「回合音效只在你活到最后时才响」。"""
    special.process_data(_frame())                                   # 本人活着，这张图记成「我这一局」
    special.process_data(_frame(steamid=MATE, round_phase="live"))   # 阵亡，观战队友
    special.process_data(_frame(steamid=MATE, round_phase="over", win_team="T"))
    assert ("round", "lose") in special.events


def test_watching_a_match_you_are_not_in_stays_muted(special):
    """对照：从没收到过本人帧的那张图（观战好友的比赛 / GOTV）—— 观战静音照旧整帧不管。"""
    special.process_data(_frame(steamid=MATE, map_name="de_mirage"))
    special.process_data(_frame(steamid=MATE, map_name="de_mirage", round_phase="over", win_team="T"))
    assert special.events == []


def test_the_first_frame_after_start_or_reconnect_is_not_a_phase_change(special):
    """软件中途启动 / 重连：第一帧的阶段是「已经在那里」，不是「刚变成那样」。"""
    special.process_data(_frame(round_phase="live"))
    assert special.events == []
    special.process_data(_frame(map_name=None))                     # 回主菜单 / 断线
    special.process_data(_frame(round_phase="live"))
    assert special.events == []
    special.process_data(_frame(round_phase="freezetime"))          # 对照：真正的跳变照常响
    assert ("round", "start") in special.events


def test_a_new_match_on_the_other_side_is_not_halftime(special):
    special.process_data(_frame(team="CT"))
    special.process_data(_frame(map_name=None))                     # 这一局打完回菜单
    special.process_data(_frame(team="T", phase="warmup"))
    special.process_data(_frame(team="T", phase="live"))
    assert ("round", "halftime") not in special.events


def test_a_map_change_straight_into_warmup_is_not_halftime(special):
    """服务器直接换图开下一局（不经主菜单）：热身里重新分边是选人，不是半场交换。"""
    special.process_data(_frame(team="CT"))
    special.process_data(_frame(team="T", map_name="de_mirage", phase="warmup"))
    special.process_data(_frame(team="T", map_name="de_mirage", phase="live"))
    assert ("round", "halftime") not in special.events


def test_switching_sides_during_warmup_is_not_halftime(special):
    """热身里换边是选人：上一局最后是 CT、这一局热身先进 CT 再换 T，都不是半场交换。"""
    special.process_data(_frame(team="CT", phase="warmup"))
    special.process_data(_frame(team="CT", phase="warmup"))
    special.process_data(_frame(team="T", phase="warmup"))
    special.process_data(_frame(team="T", phase="live"))
    assert ("round", "halftime") not in special.events


def test_real_halftime_still_plays(special):
    """对照：同一局里阵营换了 ⇒ 照常是半场交换。"""
    special.process_data(_frame(team="CT", round_no=12))
    special.process_data(_frame(team="T", round_no=13))
    assert ("round", "halftime") in special.events


def test_dying_with_a_grenade_in_hand_is_not_a_throw(special):
    holding = {"weapon_0": {"name": "weapon_flashbang", "state": "active", "ammo_reserve": 1}}
    special.process_data(_frame(weapons=holding))
    special.process_data(_frame(health=0, weapons={}))
    assert not [e for e in special.events if e[0] == "grenade"]


def test_a_real_throw_still_plays(special):
    """对照：活着把雷扔出去（数量少了一个、人还活着）照常响。"""
    holding = {"weapon_0": {"name": "weapon_flashbang", "state": "active", "ammo_reserve": 1},
               "weapon_1": {"name": "weapon_ak47", "state": "holstered"}}
    special.process_data(_frame(weapons=holding))
    special.process_data(_frame(weapons={"weapon_1": {"name": "weapon_ak47", "state": "active"}}))
    assert ("grenade", "flashbang") in special.events or any(e[0] == "grenade" for e in special.events)


# ── 切枪音效：死后观战回来 ────────────────────────────────────────────────

class _Audio:
    def __init__(self):
        self.played = []

    def play_sound(self, key, channel_type=None, **_kw):
        self.played.append(key)
        return True

    # 处理器真正会调的其余几样（RN-665：替身要显式实现产品调的方法，不靠 __getattr__ 兜）
    def play_sound_with_fade(self, *a, **k):
        return True

    def stop_channel_type(self, *a, **k):
        return None

    def load_round_sound(self, *a, **k):
        return True

    def load_c4_sound(self, *a, **k):
        return True

    def load_health_warning_sound(self, *a, **k):
        return True

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def sounds(monkeypatch):
    audio = _Audio()
    monkeypatch.setattr(gsi_handler_sounds, "audio_manager", audio)
    monkeypatch.setattr(config, "player_steamid", ME, raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", True, raising=False)
    monkeypatch.setattr(config, "switch_weapon_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "reload_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "death_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "gun_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "weapon_switch_sounds",
                        {"weapon_ak47": "S", "weapon_knife": "S"}, raising=False)
    monkeypatch.setattr(gsi_handler_sounds, "is_gun_sound_master_enabled", lambda _c: False)
    h = gsi_handler_sounds.GSIHandlerSounds()
    return h, audio


def _held(name):
    return {"weapon_0": {"name": name, "state": "active"}}


def test_respawning_after_spectating_is_not_a_weapon_switch(sounds):
    h, audio = sounds
    h.process_data(_frame(weapons=_held("weapon_ak47")))
    audio.played.clear()
    h.process_data(_frame(steamid=MATE, weapons=_held("weapon_m4a1")))     # 阵亡观战
    h.process_data(_frame(weapons=_held("weapon_knife")))                  # 下一回合复活
    assert audio.played == []


def test_a_real_switch_still_plays(sounds):
    """对照：本人一直在场、自己切刀 ⇒ 照常响。"""
    h, audio = sounds
    h.process_data(_frame(weapons=_held("weapon_ak47")))
    audio.played.clear()
    h.process_data(_frame(weapons=_held("weapon_knife")))
    assert audio.played == ["switch-weapon_knife-S"]


# ── 动态 HUD：死后观战时死亡色不退 / 首帧误闪 ─────────────────────────────

def _hud_rules(event):
    rules = get_default_hud_rules("balanced_default")
    for key in rules["event_rules"]:
        rules["event_rules"][key]["enabled"] = False
    for key in rules["state_rules"]:
        rules["state_rules"][key]["enabled"] = False
    rules["event_rules"][event].update(enabled=True, effect="solid", main=5, duration_ms=500)
    rules["default_color"] = 0
    return rules


def _hud_frame(steamid=ME, health=100, round_kills=0):
    return {
        "provider": {"steamid": ME},
        "round": {"phase": "live"},
        "player": {"steamid": steamid, "activity": "playing", "team": "ct",
                   "state": {"health": health, "round_kills": round_kills, "round_killhs": 0},
                   "weapons": {"weapon_0": {"name": "weapon_ak47", "state": "active"}}},
    }


def test_the_death_colour_expires_while_spectating():
    engine = RuntimeHudEngine(_hud_rules("death"))
    engine.evaluate(_hud_frame(), now=1.0)
    assert engine.evaluate(_hud_frame(health=0), now=1.1).color == 5
    assert engine.evaluate(_hud_frame(steamid=MATE), now=1.3).color == 5     # 时间窗内
    assert engine.evaluate(_hud_frame(steamid=MATE), now=1.8).color == 0     # 到点退回默认色


def test_spectating_without_having_died_still_drives_nothing():
    """对照：没见过本人阵亡（例如软件启动时就在观战）⇒ 观战帧照旧不出颜色。"""
    engine = RuntimeHudEngine(_hud_rules("death"))
    assert engine.evaluate(_hud_frame(steamid=MATE), now=1.0).color is None


def test_the_first_frame_does_not_flash_kill_colours():
    engine = RuntimeHudEngine(_hud_rules("kill"))
    assert engine.evaluate(_hud_frame(round_kills=3), now=1.0).color == 0
    assert engine.evaluate(_hud_frame(round_kills=4), now=1.1).color == 5     # 对照：之后的击杀照常闪


# ── 音乐联动：打字 / 对局里按 ESC 不算死 ─────────────────────────────────

def test_typing_or_pausing_in_a_match_is_not_dying():
    h = gsi_handler_music.GSIHandlerMusic()
    assert h._is_player_active(_frame(activity="textinput")) is True
    assert h._is_player_active(_frame(activity="menu")) is True
    assert h._is_player_active(_frame(activity="menu", map_name=None)) is False   # 对照：真回了主菜单


# ── 道具瞄点：死后观战时被观战者活着不等于我活着 ─────────────────────────

def test_utility_menu_follows_me_not_the_player_i_watch(monkeypatch):
    monkeypatch.setattr(config, "player_steamid", ME, raising=False)
    h = gsi_handler_utility.GSIHandlerUtility()
    h.process_data(_frame())
    assert h.player_alive is True
    h.process_data(_frame(steamid=MATE, team="T"))
    assert h.player_alive is False
    assert h.player_team != "T"
