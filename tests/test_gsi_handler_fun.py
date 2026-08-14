# SPDX-License-Identifier: GPL-3.0-or-later
"""整活事件源（死亡/复活/中断边沿）单测。

重点压两个观战陷阱：
  1. 观战队友死亡不能触发（player 节点会整个换成被观战者）
  2. 自己死后自动观战队友，队友血量不能覆盖基线，否则复活边沿丢失
"""
from __future__ import annotations

import time

import pytest
from config import config
from gsi_handler_fun import GSIHandlerFun

SELF_ID = "76561198000000001"
MATE_ID = "76561198000000002"


class _Recorder:
    def __init__(self):
        self.deaths = 0
        self.respawns = 0
        self.aborts: list[str] = []

    def bind(self, handler: GSIHandlerFun):
        handler.set_callbacks(
            on_death=self._death,
            on_respawn=self._respawn,
            on_abort=self.aborts.append,
        )
        return self

    def _death(self):
        self.deaths += 1

    def _respawn(self):
        self.respawns += 1


def _payload(health, *, steamid=SELF_ID, activity="playing", mode="deathmatch", map_name="de_dust2", with_map=True):
    data = {
        "provider": {"steamid": SELF_ID},
        "player": {
            "steamid": steamid,
            "activity": activity,
            "state": {"health": health},
        },
    }
    if with_map:
        data["map"] = {"name": map_name, "mode": mode, "phase": "live"}
    return data


@pytest.fixture(autouse=True)
def _enable_fun(monkeypatch):
    monkeypatch.setattr(config, "fun_afterlife_enabled", True, raising=False)
    monkeypatch.setattr(config, "fun_afterlife_modes", ["deathmatch", "casual"], raising=False)
    monkeypatch.setattr(config, "fun_afterlife_max_per_match", 0, raising=False)
    monkeypatch.setattr(config, "player_steamid", SELF_ID, raising=False)


def _new():
    handler = GSIHandlerFun()
    return handler, _Recorder().bind(handler)


def test_death_edge_fires_once():
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    assert rec.deaths == 1
    # 死亡状态持续多帧不能重复触发
    for _ in range(5):
        handler.process_data(_payload(0))
    assert rec.deaths == 1


def test_first_frame_does_not_fire():
    """首帧 health=0（比如软件在玩家已死时启动）不能算死亡边沿。"""
    handler, rec = _new()
    handler.process_data(_payload(0))
    assert rec.deaths == 0


def test_respawn_edge_fires():
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    handler.process_data(_payload(100))
    assert rec.deaths == 1
    assert rec.respawns == 1


def test_respawn_survives_spectating_teammate():
    """核心回归：死后自动观战队友，队友血量不能覆盖基线。

    若把观战帧当自己的数据处理，last_health 会被队友的 100 覆盖，
    自己复活时 prev 已是 100，0→100 的复活边沿就永远不会出现，
    表现为窗口弹出来后再也收不回去。
    """
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    assert rec.deaths == 1

    # 死后观战队友若干帧：player 节点整个是队友的，activity 仍是 playing
    for hp in (100, 87, 62, 43):
        handler.process_data(_payload(hp, steamid=MATE_ID))
    assert rec.respawns == 0
    assert handler.last_health == 0, "观战帧不得覆盖自己的血量基线"

    # 自己复活
    handler.process_data(_payload(100))
    assert rec.respawns == 1


def test_spectated_player_death_does_not_fire():
    """观战别人时对方阵亡，不能把窗口糊到人脸上。"""
    handler, rec = _new()
    handler.process_data(_payload(100, steamid=MATE_ID))
    handler.process_data(_payload(0, steamid=MATE_ID))
    assert rec.deaths == 0


def test_provider_steamid_wins_over_stale_config():
    """config.player_steamid 过期（换号）时，以 provider 为准。"""
    handler, rec = _new()
    config.player_steamid = "76561198999999999"  # 陈旧值
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    assert rec.deaths == 1


def test_unknown_identity_is_fail_closed(monkeypatch):
    """provider 与 config 都认不出自己时，一律不动作。"""
    monkeypatch.setattr(config, "player_steamid", "", raising=False)
    handler, rec = _new()
    data = _payload(100)
    data["provider"] = {}
    handler.process_data(data)
    dead = _payload(0)
    dead["provider"] = {}
    handler.process_data(dead)
    assert rec.deaths == 0


def test_mode_whitelist_blocks():
    handler, rec = _new()
    handler.process_data(_payload(100, mode="competitive"))
    handler.process_data(_payload(0, mode="competitive"))
    assert rec.deaths == 0


def test_mode_whitelist_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(config, "fun_afterlife_modes", ["DeathMatch"], raising=False)
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    assert rec.deaths == 1


def test_empty_mode_list_blocks_everything(monkeypatch):
    monkeypatch.setattr(config, "fun_afterlife_modes", [], raising=False)
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    assert rec.deaths == 0


def test_disabled_still_tracks_baseline(monkeypatch):
    """关闭期间死过一次，重新打开时不能凭陈旧基线补一个假死亡。"""
    monkeypatch.setattr(config, "fun_afterlife_enabled", False, raising=False)
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    assert rec.deaths == 0
    assert handler.last_health == 0

    monkeypatch.setattr(config, "fun_afterlife_enabled", True, raising=False)
    handler.process_data(_payload(0))
    assert rec.deaths == 0, "开启瞬间不得凭陈旧基线补触发"


def test_cooldown_blocks_rapid_retrigger():
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))  # 冷却期内的第二次死亡
    assert rec.deaths == 1


def test_cooldown_expires():
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    handler.death_cooldown = time.time() - 1  # 手动过期，避免测试里真等 5 秒
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    assert rec.deaths == 2


def test_max_per_match_limit(monkeypatch):
    monkeypatch.setattr(config, "fun_afterlife_max_per_match", 2, raising=False)
    handler, rec = _new()
    for _ in range(4):
        handler.death_cooldown = 0
        handler.process_data(_payload(100))
        handler.process_data(_payload(0))
    assert rec.deaths == 2


def test_map_change_aborts_and_resets_limit(monkeypatch):
    monkeypatch.setattr(config, "fun_afterlife_max_per_match", 1, raising=False)
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    assert rec.deaths == 1

    handler.process_data(_payload(100, map_name="de_mirage"))
    assert rec.aborts, "换图必须收回窗口"

    handler.death_cooldown = 0
    handler.process_data(_payload(100, map_name="de_mirage"))
    handler.process_data(_payload(0, map_name="de_mirage"))
    assert rec.deaths == 2, "换图后每局上限应重新计数"


def test_leaving_match_aborts():
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))
    handler.process_data(_payload(0, with_map=False))  # 回主菜单
    assert rec.aborts


def test_abort_only_when_currently_dead():
    """活着时换图不该发中断——没弹窗口就没什么可收的。"""
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(100, map_name="de_mirage"))
    assert rec.aborts == []


def test_callback_exception_does_not_propagate():
    """回调炸了不能带崩 GSI 线程——同一条线上还挂着音效/闪光等 handler。"""
    handler = GSIHandlerFun()
    handler.set_callbacks(on_death=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    handler.process_data(_payload(100))
    handler.process_data(_payload(0))  # 不抛即通过


def test_menu_activity_ignored():
    handler, rec = _new()
    handler.process_data(_payload(100))
    handler.process_data(_payload(0, activity="menu"))
    assert rec.deaths == 0
