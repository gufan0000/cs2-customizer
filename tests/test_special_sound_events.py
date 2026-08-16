# SPDX-License-Identifier: GPL-3.0-or-later
"""特殊音效：MVP / 队伍判定 / 热身边沿 / 新增事件 的判据。

这一批全是 2026-08-15 排查出来的缺陷，**每条都对应一个此前无人看守的失效**：
特殊音效在此之前一条 MVP 相关的测试都没有（`grep -l mvp tests/` 命中的文件里
没有一个测的是这块）。

判据的共同形状：喂一串 GSI 帧进 `process_data`，看**报了哪些事件**。
拦截点是 `_play_event(group, key)` —— 事件身份是显式参数，比"哪个方法被调了"
更接近真正要断言的东西。
"""

from __future__ import annotations

import pytest

import gsi_handler_special
from config import config
from core.audio.special_events import (
    SOUND_EVENTS,
    config_defaults,
    events_in_group,
    get_event,
    sound_key,
    style_dir_parts,
)

MY_ID = "76561198000000001"
TEAMMATE_ID = "76561198000000002"


class _ImmediateTimer:
    """把后台等待同步化：真实实现在别的线程上等 MVP 计数落地。"""

    def __init__(self, _interval, function, args=None, kwargs=None):
        self._fn = function
        self._args = args or []
        self._kwargs = kwargs or {}
        self.daemon = True

    def start(self):
        self._fn(*self._args, **self._kwargs)

    def cancel(self):
        return None


@pytest.fixture
def handler(monkeypatch):
    """一个只记账不出声的处理器。"""
    monkeypatch.setattr(config, "player_steamid", MY_ID, raising=False)
    monkeypatch.setattr(config, "round_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "c4_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(gsi_handler_special.threading, "Timer", _ImmediateTimer)

    h = gsi_handler_special.GSIHandlerSpecial()
    h.events = []
    monkeypatch.setattr(h, "_play_event", lambda g, k: (h.events.append((g, k)), True)[1])
    return h


def _frame(
    *,
    phase="live",
    round_phase="live",
    round_no=3,
    win_team=None,
    team="CT",
    mvps=None,
    all_mvps=None,
    steamid=MY_ID,
    bomb=None,
):
    """造一帧 GSI。`all_mvps` 走 allplayers（死亡观战时唯一能拿到自己数据的路）。"""
    payload = {
        "map": {"round": round_no, "phase": phase},
        "round": {"phase": round_phase},
        "player": {
            "steamid": steamid,
            "team": team,
            "activity": "playing",
            "state": {"health": 100},
        },
    }
    if win_team:
        payload["round"]["win_team"] = win_team
    if mvps is not None:
        payload["player"]["match_stats"] = {"mvps": mvps}
    if all_mvps is not None:
        payload["allplayers"] = {
            "1": {"steamid": MY_ID, "team": "CT", "match_stats": {"mvps": all_mvps}},
            "2": {"steamid": TEAMMATE_ID, "team": "CT", "match_stats": {"mvps": 99}},
        }
    if bomb is not None:
        payload["bomb"] = {"state": bomb}
    return payload


# ── MVP ────────────────────────────────────────────────────────────────


def test_mvp_first_observation_seeds_instead_of_firing(handler):
    """中途启动/重连时，第一帧读到的真实计数**不算一次增长**。

    旧实现把 previous_mvps_count 初值设成 0，于是首帧读到 3 会被当成"从 0 涨到 3"，
    当前回合直接被误标 MVP —— 这一局只要你队赢了就误播 MVP 音效。
    """
    handler.process_data(_frame(mvps=3))
    assert handler.is_current_round_mvp is False
    assert handler.previous_mvps_count == 3


def test_mvp_fires_on_real_increase(handler):
    handler.process_data(_frame(mvps=3))
    handler.process_data(_frame(mvps=4))
    assert handler.is_current_round_mvp is True


def test_mvp_count_reset_on_new_match_is_not_an_event(handler):
    """换一局计数归零，只重新播种，不是 MVP。"""
    handler.process_data(_frame(mvps=5))
    handler.process_data(_frame(mvps=0, round_no=1))
    assert handler.is_current_round_mvp is False
    assert handler.previous_mvps_count == 0


def test_mvp_is_read_from_allplayers_while_dead_spectating(handler):
    """**死了也要拿得到 MVP**。

    死亡观战时 GSI 的 player 块会切成被观战者。旧实现只读 player.match_stats
    且被 is_self 挡掉，于是回合结束那一刻自己的 MVP 增量根本没被看见 ——
    MVP 音效只在"你活到回合结束"时才响，而埋包 MVP 恰恰最常在死后拿到。
    """
    handler.process_data(_frame(all_mvps=2, steamid=MY_ID))
    # 现在死了，player 块变成队友的（队友有 99 个 MVP，不能被当成自己的）
    handler.process_data(_frame(all_mvps=3, steamid=TEAMMATE_ID, mvps=99))
    assert handler.is_current_round_mvp is True
    assert handler.previous_mvps_count == 3


def test_teammate_mvp_count_never_leaks_in(handler):
    """观战队友时，对方的 MVP 计数不许污染自己的跟踪。"""
    handler.process_data(_frame(all_mvps=1, steamid=MY_ID))
    handler.process_data(_frame(steamid=TEAMMATE_ID, mvps=99))
    assert handler.previous_mvps_count == 1
    assert handler.is_current_round_mvp is False


def test_win_round_with_mvp_plays_mvp_not_win(handler):
    handler.process_data(_frame(all_mvps=1))
    handler.process_data(_frame(all_mvps=2))
    handler.process_data(_frame(round_phase="over", win_team="CT", all_mvps=2))
    assert ("round", "mvp") in handler.events
    assert ("round", "win") not in handler.events


def test_win_round_without_mvp_plays_win(handler):
    handler.process_data(_frame(all_mvps=1))
    handler.process_data(_frame(round_phase="over", win_team="CT", all_mvps=1))
    assert ("round", "win") in handler.events
    assert ("round", "mvp") not in handler.events


def test_mvp_wait_does_not_leak_into_next_round(handler):
    """上一回合置位的等待事件必须在新回合被清掉，否则下一回合会立刻"命中"。"""
    handler.process_data(_frame(all_mvps=1))
    handler.process_data(_frame(all_mvps=2))
    handler.process_data(_frame(round_phase="over", win_team="CT", all_mvps=2))
    handler.events.clear()
    # 新回合的冻结期
    handler.process_data(_frame(round_no=4, round_phase="freezetime", all_mvps=2))
    assert handler.is_current_round_mvp is False
    assert handler._mvp_resolved.is_set() is False


# ── 队伍判定 ────────────────────────────────────────────────────────────


def test_team_is_resolved_by_steamid_not_by_player_block(handler):
    """观战敌方时不许把胜负判反。

    旧实现是 `if player.team ... elif allplayers ...`，而 player.team 几乎总是
    存在，那条 elif **永远走不到**。休闲/死斗里能观战敌方，于是 team_side 跟着
    被观战者跑，胜负音效整个反过来。
    """
    handler.process_data(_frame(all_mvps=0, team="CT"))
    assert handler.team_side == "ct"

    # 死了，正在观战一个 T 方玩家：player 块是对方的，但 allplayers 里我还是 CT
    frame = _frame(all_mvps=0, steamid=TEAMMATE_ID, team="T")
    frame["allplayers"]["1"]["team"] = "CT"
    handler.process_data(frame)
    assert handler.team_side == "ct", "队伍判定跟着被观战者跑了"


def test_lose_sound_when_enemy_wins(handler):
    handler.process_data(_frame(all_mvps=0, team="CT"))
    handler.process_data(_frame(round_phase="over", win_team="T", all_mvps=0))
    assert ("round", "lose") in handler.events


# ── 热身边沿 ────────────────────────────────────────────────────────────


def test_warmup_does_not_fire_round_sounds(handler):
    """热身期 map.phase 是 warmup，而 round.phase 照样报 freezetime。

    不排除热身的话，"回合开始"会在热身时响一声，而真正的第一回合因为
    previous_freeze_time 已经是 True，反而**不响**。
    """
    handler.process_data(_frame(phase="warmup", round_phase="freezetime", all_mvps=0))
    handler.process_data(_frame(phase="warmup", round_phase="live", all_mvps=0))
    assert ("round", "start") not in handler.events
    assert ("round", "action") not in handler.events


def test_first_real_round_still_fires_after_warmup(handler):
    handler.process_data(_frame(phase="warmup", round_phase="freezetime", all_mvps=0))
    handler.process_data(_frame(phase="live", round_phase="freezetime", round_no=1, all_mvps=0))
    assert ("round", "start") in handler.events


# ── 比赛级事件 ──────────────────────────────────────────────────────────


def test_match_start_fires_once_on_warmup_to_live(handler):
    handler.process_data(_frame(phase="warmup", all_mvps=0))
    handler.process_data(_frame(phase="live", all_mvps=0))
    handler.process_data(_frame(phase="live", all_mvps=0))
    assert handler.events.count(("round", "match_start")) == 1


def test_match_start_does_not_fire_when_joining_mid_match(handler):
    """中途启动软件时 map.phase 直接就是 live，不许误报"比赛开始"。"""
    handler.process_data(_frame(phase="live", all_mvps=0))
    assert ("round", "match_start") not in handler.events


def test_match_end_fires_on_gameover(handler):
    handler.process_data(_frame(phase="live", all_mvps=0))
    handler.process_data(_frame(phase="gameover", all_mvps=0))
    assert ("round", "match_end") in handler.events


def test_halftime_fires_when_own_side_swaps(handler):
    handler.process_data(_frame(team="CT", all_mvps=0))
    frame = _frame(team="T", all_mvps=0)
    frame["allplayers"]["1"]["team"] = "T"
    handler.process_data(frame)
    assert ("round", "halftime") in handler.events


def test_halftime_does_not_fire_on_first_frame(handler):
    """刚进服第一次确定阵营不算换边。"""
    handler.process_data(_frame(team="T", all_mvps=0))
    assert ("round", "halftime") not in handler.events


# ── C4 ──────────────────────────────────────────────────────────────────


def test_c4_defused_and_exploded_fire(handler, monkeypatch):
    monkeypatch.setattr(config, "c4_defused_style", "s", raising=False)
    handler.process_data(_frame(bomb="planted", all_mvps=0))
    handler.process_data(_frame(bomb="defused", all_mvps=0))
    assert ("c4", "defused") in handler.events

    handler.events.clear()
    handler.process_data(_frame(bomb="planted", round_no=4, all_mvps=0))
    handler.process_data(_frame(bomb="exploded", round_no=4, all_mvps=0))
    assert ("c4", "exploded") in handler.events


def test_c4_events_fire_once_per_transition(handler):
    handler.process_data(_frame(bomb="planted", all_mvps=0))
    for _ in range(3):
        handler.process_data(_frame(bomb="defused", all_mvps=0))
    assert handler.events.count(("c4", "defused")) == 1


# ── 素材查找：不回落 ────────────────────────────────────────────────────


def test_token_lookup_returns_none_when_nothing_matches(tmp_path):
    """C4 三个事件共用一个风格目录，挑不到就必须**安静地不响**。

    回落到目录里第一个文件的话，只放了"下包"音效的老用户会在拆包时听到那声
    下包音效——听起来像 bug，比不响更糟。
    """
    from core.audio.audio_file_utils import find_audio_by_tokens, find_first_audio_file

    style_dir = tmp_path / "s"
    style_dir.mkdir()
    (style_dir / "planted.mp3").write_bytes(b"x")

    assert find_audio_by_tokens(str(style_dir), ("defused", "拆除")) is None
    # 对照：老的 find_first_audio_file 会把它回落成 planted.mp3
    assert find_first_audio_file(str(style_dir), preferred_tokens=("defused",)) is not None


def test_token_lookup_finds_the_right_file(tmp_path):
    from core.audio.audio_file_utils import find_audio_by_tokens

    style_dir = tmp_path / "s"
    style_dir.mkdir()
    (style_dir / "planted.mp3").write_bytes(b"x")
    (style_dir / "拆除成功.mp3").write_bytes(b"x")

    found = find_audio_by_tokens(str(style_dir), ("defused", "拆除"))
    assert found is not None and "拆除" in found


# ── 事件表本身 ──────────────────────────────────────────────────────────


def test_every_event_has_a_config_default():
    """事件表是唯一真相源：每个事件都必须能在 config 上找到自己的字段。"""
    defaults = config_defaults()
    for event in SOUND_EVENTS:
        assert event.config_attr in defaults
        assert hasattr(config, event.config_attr), (
            f"{event.label} 的 {event.config_attr} 没落到 config 上"
        )


def test_config_attrs_are_unique():
    attrs = [e.config_attr for e in SOUND_EVENTS]
    assert len(attrs) == len(set(attrs))


def test_legacy_config_attrs_are_untouched():
    """存量字段名不许改——改名等于把用户已有的设置清空。"""
    legacy = {
        "round_start_style", "round_action_style", "round_win_style",
        "round_lose_style", "round_mvp_style", "c4_sound_style",
        "health_warning_style",
    }
    assert legacy <= {e.config_attr for e in SOUND_EVENTS}


def test_legacy_sound_keys_are_untouched():
    """音效键格式不许变，用户的预载清单按它走。"""
    assert sound_key(get_event("round", "win"), "abc") == "round-win-abc"
    assert sound_key(get_event("c4", "planted"), "abc") == "c4-planted-abc"
    assert sound_key(get_event("health", "warning"), "abc") == "health-warning-abc"


def test_c4_events_share_one_style_directory():
    """分层目录会让老用户已导入的 C4 素材全部失联。"""
    dirs = {tuple(style_dir_parts(e, "s")) for e in events_in_group("c4")}
    assert dirs == {("c4_sounds", "s")}


def test_round_events_have_their_own_directories():
    dirs = [tuple(style_dir_parts(e, "s")) for e in events_in_group("round")]
    assert len(dirs) == len(set(dirs))


def test_audio_manager_round_types_are_derived():
    """ROUND_TYPES 原本是手写的第二份清单。"""
    from core.audio.audio_manager import AudioManager
    from core.audio.special_events import round_event_keys

    assert tuple(AudioManager.ROUND_TYPES) == round_event_keys()


def test_round_event_keys_have_no_hyphen():
    """音效键是 `round-<key>-<style>`，key 里带减号会把解析劈错。"""
    for event in events_in_group("round"):
        assert "-" not in event.key
