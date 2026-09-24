# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 115：`round_kills` 涨了，但不是玩家开枪打死的 —— 炸弹、投掷物；以及「哪一个是我」。

- RN-683 **炸弹炸死的人头**记在下包者名下、一包跳几个 ⇒ 旧逻辑直接播三杀音效、弹三杀图标、
  HUD 闪连杀色，而玩家那一刻一枪没开。
- RN-684 **扔雷 → 切枪 → 雷炸死人**：这包推断不出开火，旧逻辑取「此刻举着的枪」⇒
  AK 的专属击杀音在没开枪时响；击杀音效页「手雷/道具」三项配置从来没生效过。
- RN-685 **「哪一个是我」五个处理器三种口径**：`config.player_steamid` 是第一帧记下的，
  第一帧在观战就会记成别人 ⇒ 观战静音反过来静掉自己。

⚠ 这些帧是**按 GSI 字段形状自造的**，证明的是「判定逻辑对这种帧给对的答案」，
不证明 CS2 真的这样发 —— 那一半在 M7 进游戏清单里（下包炸死两人 / 扔雷切枪 / 观战切人）。
"""
from __future__ import annotations

import types

import pytest

import gsi_handler_kills
from config import config
from core.gsi.identity import is_self, resolve_self_steamid
from core.gsi.kill_attribution import BombKillFilter, GrenadeKillTracker
from core.hud.rule_model import get_default_hud_rules
from core.hud.runtime_engine import RuntimeHudEngine

ME = "76561190000000001"
MATE = "76561190000000002"


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now


class _Audio:
    def __init__(self):
        self.calls = []

    def play_sound(self, key, channel_type="kill_sound", **_kw):
        self.calls.append(key)
        return True

    def play_voice(self, key):
        pass

    # 处理器真会调的其余接口（守卫：test_the_things_the_audit_left_open）
    def load_c4_sound(self, *a, **k):
        return True

    def load_health_warning_sound(self, *a, **k):
        return True

    def load_round_sound(self, *a, **k):
        return True

    def play_sound_with_fade(self, *a, **k):
        return True


@pytest.fixture()
def rig(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(gsi_handler_kills, "time", types.SimpleNamespace(time=clock.time))
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", _Audio())
    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 官匹竞技", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", ME, raising=False)
    monkeypatch.setattr(config, "save_config", lambda *a, **k: None, raising=False)

    h = gsi_handler_kills.GSIHandlerKills()
    played = []   # (等级, 判定武器)
    monkeypatch.setattr(
        h, "_get_weapon_kill_sound_key",
        lambda weapon, level, _hs=False: played.append((level, weapon)) or f"kill-{level}")
    h.callbacks_fired = []
    h.register_kill_callback(lambda hs: h.callbacks_fired.append(hs))
    return h, clock, played


def _weapons(active, ak_ammo=30, he=1, molotov=0):
    w = {
        "weapon_0": {"name": "weapon_knife", "state": "active" if active == "weapon_knife" else "holstered"},
        "weapon_1": {"name": "weapon_ak47", "ammo_clip": ak_ammo,
                     "state": "active" if active == "weapon_ak47" else "holstered"},
    }
    if he:
        w["weapon_2"] = {"name": "weapon_hegrenade", "ammo_reserve": he,
                         "state": "active" if active == "weapon_hegrenade" else "holstered"}
    if molotov:
        w["weapon_3"] = {"name": "weapon_molotov", "ammo_reserve": molotov,
                         "state": "active" if active == "weapon_molotov" else "holstered"}
    return w


def _frame(kills, *, rnd=3, phase="live", bomb="", active="weapon_ak47", ak_ammo=30, he=1,
           molotov=0, killhs=0, match_kills=None, player=ME, provider=ME):
    state = {"health": 100, "round_kills": kills, "round_killhs": killhs}
    p = {"steamid": player, "activity": "playing", "state": state,
         "weapons": _weapons(active, ak_ammo, he, molotov)}
    p["match_stats"] = {"kills": 10 + kills if match_kills is None else match_kills}
    rnd_block = {"phase": phase}
    if bomb:
        rnd_block["bomb"] = bomb
    return {"provider": {"steamid": provider}, "map": {"round": rnd, "phase": "live"},
            "round": rnd_block, "player": p}


def _feed(h, clock, frames):
    for dt, f in frames:
        clock.now += dt
        h.process_data(f)


# ──────────────────────────── RN-683 炸弹 ────────────────────────────

def test_bomb_kills_give_no_kill_feedback(rig):
    """⭐ 已有一杀，下的包炸死两个 CT：一包 1→3，不许播「三杀」、不许触发击杀回调。"""
    h, clock, played = rig
    _feed(h, clock, [
        (0.1, _frame(0)),
        (0.1, _frame(0)),
        (0.1, _frame(1, ak_ammo=29)),                                   # 真击杀：开了一枪
        (5.0, _frame(1, ak_ammo=29, bomb="planted")),
        (40.0, _frame(3, ak_ammo=29, phase="over", bomb="exploded")),   # 炸弹：一包跳两个
    ])
    assert [lv for lv, _ in played] == [1], f"炸弹人头被当成了连杀: {played}"
    assert len(h.callbacks_fired) == 1, "炸弹人头触发了击杀回调（准心动画之类会跟着动）"


def test_a_real_kill_after_the_bomb_counts_from_the_real_number(rig):
    """回合结束后拿枪补人：round_kills 3→4，但真实只有第 2 杀 ⇒ 播二杀，不是四杀。"""
    h, clock, played = rig
    _feed(h, clock, [
        (0.1, _frame(0)),
        (0.1, _frame(0)),
        (0.1, _frame(1, ak_ammo=29)),
        (5.0, _frame(1, ak_ammo=29, bomb="planted")),
        (40.0, _frame(3, ak_ammo=29, phase="over", bomb="exploded")),
        (2.0, _frame(4, ak_ammo=27, phase="over", bomb="exploded")),     # 补枪：弹夹少了
    ])
    assert [lv for lv, _ in played] == [1, 2], played


def test_gunfire_in_the_explosion_frame_is_still_a_kill(rig):
    """同一包里本帧推断出开火 ⇒ 这是枪杀，照播（过滤器只拦『没开枪』的人头）。"""
    h, clock, played = rig
    _feed(h, clock, [
        (0.1, _frame(0)),
        (0.1, _frame(0, bomb="planted")),
        (0.1, _frame(1, ak_ammo=28, phase="over", bomb="exploded")),
    ])
    assert [lv for lv, _ in played] == [1]


def test_the_next_round_starts_counting_from_zero_again(rig):
    h, clock, played = rig
    _feed(h, clock, [
        (0.1, _frame(0)),
        (0.1, _frame(0, bomb="planted")),
        (0.1, _frame(2, phase="over", bomb="exploded")),
        (8.0, _frame(0, rnd=4, phase="freezetime")),
        (15.0, _frame(0, rnd=4)),
        (3.0, _frame(1, rnd=4, ak_ammo=29)),
    ])
    assert [lv for lv, _ in played] == [1]


def test_the_bomb_filter_only_counts_the_moment_it_went_off():
    f = BombKillFilter()
    f.observe({"round": {"bomb": "planted"}}, 1.0)
    assert not f.is_bomb_kill(1.0)
    f.observe({"round": {"bomb": "exploded"}}, 2.0)
    assert f.is_bomb_kill(2.0)
    assert f.is_bomb_kill(2.9)
    assert not f.is_bomb_kill(2.9, fired=True)
    f.observe({"round": {"bomb": "exploded"}}, 5.0)
    assert not f.is_bomb_kill(5.0), "爆炸之后几秒还在按炸弹算 ⇒ 回合末补枪会被吞"
    f.observe({"bomb": {"state": "exploded"}}, 6.0)  # 只有 bomb 组件
    assert not f.is_bomb_kill(6.0), "状态没变却又记了一次爆炸"


# ──────────────────────────── RN-684 投掷物 ────────────────────────────

def _throw_he(clock, h, *, kills=0):
    _feed(h, clock, [
        (0.1, _frame(kills, active="weapon_hegrenade", he=1)),
        (0.1, _frame(kills, active="weapon_hegrenade", he=1)),
        (0.3, _frame(kills, active="weapon_ak47", he=0)),     # 扔出去、自动切回 AK
    ])


def test_a_grenade_kill_after_switching_back_belongs_to_the_grenade(rig):
    """⭐ 扔雷 → 切 AK → 两秒后雷炸死人，这一包没开火 ⇒ 判手雷，不判 AK。"""
    h, clock, played = rig
    _feed(h, clock, [(0.1, _frame(0)), (0.1, _frame(0))])
    _throw_he(clock, h)
    _feed(h, clock, [(1.8, _frame(1, he=0))])
    assert played == [(1, "weapon_hegrenade")], played


def test_firing_a_gun_after_the_throw_gives_the_kill_back_to_the_gun(rig):
    """扔完雷又开了枪 ⇒ 之后的击杀更可能是枪（宁漏不错）。"""
    h, clock, played = rig
    _feed(h, clock, [(0.1, _frame(0)), (0.1, _frame(0))])
    _throw_he(clock, h)
    _feed(h, clock, [
        (0.5, _frame(0, he=0, ak_ammo=28)),     # 开枪
        (0.2, _frame(1, he=0, ak_ammo=28)),     # 击杀包晚一拍到（RN-096 那种）
    ])
    assert played == [(1, "weapon_ak47")], played


def test_a_kill_long_after_the_throw_is_not_the_grenade(rig):
    h, clock, played = rig
    _feed(h, clock, [(0.1, _frame(0)), (0.1, _frame(0))])
    _throw_he(clock, h)
    _feed(h, clock, [(6.0, _frame(1, he=0))])
    assert played and played[0][1] != "weapon_hegrenade", played


def test_a_headshot_is_never_the_grenade(rig):
    h, clock, played = rig
    _feed(h, clock, [(0.1, _frame(0)), (0.1, _frame(0))])
    _throw_he(clock, h)
    _feed(h, clock, [(1.5, _frame(1, he=0, killhs=1))])
    assert played and played[0][1] != "weapon_hegrenade", played


def test_one_fire_can_burn_two_people_in_two_packets(rig):
    """一团火分两包烧死两个人：第二杀也归燃烧瓶（击杀后不消耗）。"""
    h, clock, played = rig
    _feed(h, clock, [(0.1, _frame(0, he=0, molotov=1)), (0.1, _frame(0, he=0, molotov=1))])
    _feed(h, clock, [
        (0.1, _frame(0, he=0, molotov=1, active="weapon_molotov")),
        (0.1, _frame(0, he=0, molotov=1, active="weapon_molotov")),
        (0.3, _frame(0, he=0, molotov=0, active="weapon_ak47")),
        (4.0, _frame(1, he=0, molotov=0)),
        (1.5, _frame(2, he=0, molotov=0)),
    ])
    assert played == [(1, "weapon_molotov"), (2, "weapon_molotov")], played


def test_switching_spectated_player_forgets_the_throw():
    t = GrenadeKillTracker()
    t.observe(_weapons("weapon_hegrenade", he=1), 1.0)
    t.observe(_weapons("weapon_ak47", he=0), 1.2)
    assert t.claim(2.0) == "weapon_hegrenade"
    t.reset()
    assert t.claim(2.1) == ""


def test_the_throw_sound_still_fires_through_the_shared_detector(monkeypatch):
    """投掷音效那条检测改成调共用判定之后，举雷→扔出仍要响；举雷→切走不扔不许响。"""
    import gsi_handler_special
    h = gsi_handler_special.GSIHandlerSpecial()
    thrown = []
    monkeypatch.setattr(h, "_play_grenade_sound", thrown.append)
    for w in (_weapons("weapon_hegrenade", he=1), _weapons("weapon_ak47", he=0)):
        h._process_grenade_throw({"player": {"weapons": w}})
    assert thrown == ["hegrenade"]
    for w in (_weapons("weapon_hegrenade", he=1), _weapons("weapon_ak47", he=1)):
        h._process_grenade_throw({"player": {"weapons": w}})
    assert thrown == ["hegrenade"], "只是切走没扔，也播了投掷音效"


def test_the_grenade_sound_page_entries_can_now_be_reached():
    """击杀音效页「手雷/道具」那三项的键名，必须正好是归属会给出的武器名 —— 否则配了照样没反应。"""
    from core.gsi.kill_attribution import LETHAL_GRENADE_WINDOWS_S
    for name in LETHAL_GRENADE_WINDOWS_S:
        assert name in config.weapon_kill_sounds, f"{name} 能被判出来，但击杀音效配置里没有这一项"


# ──────────────────────────── RN-685 哪一个是我 ────────────────────────────

def test_provider_beats_a_wrongly_remembered_steamid(rig, monkeypatch):
    """config 里记成了别人（第一帧在观战），观战静音开着：自己的击杀仍要响。"""
    h, clock, played = rig
    monkeypatch.setattr(config, "player_steamid", MATE, raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", True, raising=False)
    _feed(h, clock, [(0.1, _frame(0)), (0.1, _frame(0)), (0.1, _frame(1, ak_ammo=29))])
    assert [lv for lv, _ in played] == [1], "provider 说是我，却被当成观战别人静掉了"


def test_spectating_a_teammate_is_still_muted(rig, monkeypatch):
    h, clock, played = rig
    monkeypatch.setattr(config, "spectator_mode_mute", True, raising=False)
    _feed(h, clock, [(0.1, _frame(0, player=MATE)), (0.1, _frame(0, player=MATE)),
                     (0.1, _frame(1, player=MATE, ak_ammo=29))])
    assert played == []


def test_the_first_remembered_steamid_comes_from_provider(rig, monkeypatch):
    h, clock, _ = rig
    monkeypatch.setattr(config, "player_steamid", "", raising=False)
    h.process_data(_frame(0, player=MATE))
    assert config.player_steamid == ME


def test_identity_rules():
    assert resolve_self_steamid({"provider": {"steamid": ME}}, MATE) == ME
    assert resolve_self_steamid({}, MATE) == MATE
    assert is_self({"provider": {"steamid": ME}, "player": {"steamid": ME}})
    assert not is_self({"provider": {"steamid": ME}, "player": {"steamid": MATE}})
    assert is_self({"player": {"steamid": MATE}}), "两边都认不出时维持旧行为（按本人）"


# ──────────────────────────── HUD 同一个判定 ────────────────────────────

def _hud_frame(kills, bomb=""):
    rnd = {"phase": "over" if bomb == "exploded" else "live", "win_team": ""}
    if bomb:
        rnd["bomb"] = bomb
    return {"provider": {"steamid": ME}, "round": rnd, "bomb": {"state": ""},
            "player": {"steamid": ME, "activity": "playing", "team": "t",
                       "state": {"health": 100, "round_kills": kills, "round_killhs": 0},
                       "weapons": {"w": {"name": "weapon_ak47", "state": "active"}}}}


def test_the_hud_does_not_flash_kill_colours_for_bomb_kills():
    rules = get_default_hud_rules("balanced_default")
    for key in rules["event_rules"]:
        rules["event_rules"][key]["enabled"] = False
    for key in rules["state_rules"]:
        rules["state_rules"][key]["enabled"] = False
    rules["event_rules"]["kill"]["enabled"] = True
    rules["event_rules"]["multi_kill"]["enabled"] = True
    engine = RuntimeHudEngine(rules)
    engine.evaluate(_hud_frame(1), now=1.0)
    engine.evaluate(_hud_frame(1, bomb="planted"), now=2.0)
    engine._event_triggered_at.clear()      # 第一杀（0→1）那一闪是真的，清掉只看后面
    engine.evaluate(_hud_frame(3, bomb="exploded"), now=40.0)
    assert "kill" not in engine._event_triggered_at and "multi_kill" not in engine._event_triggered_at, (
        "炸弹人头让 HUD 闪了击杀/连杀色")
    engine.evaluate(_hud_frame(4, bomb="exploded"), now=43.0)   # 回合末补一枪：真实第 2 杀
    assert "kill" in engine._event_triggered_at
    assert "multi_kill" not in engine._event_triggered_at, "真实只有两杀，却按 4 杀闪了连杀色"
