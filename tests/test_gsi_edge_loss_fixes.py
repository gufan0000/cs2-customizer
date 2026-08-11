# SPDX-License-Identifier: GPL-3.0-or-later
"""v2.2.1 系统排查修复的回归测试（击杀音效之外的同类丢失/逻辑bug）。

覆盖：
1. 胜负/MVP 音效——win_team 早于 phase→over 一帧时不再整块丢失
2. 死亡音效独立通道——互杀时不再被击杀声 drop
3. 手雷连投——第二声同优先级切入而非被吞
4. 音乐联动恢复——关闭联动/断流看门狗把音乐从暂停/低音量恢复常态
5. 闪光断流看门狗——闪光值卡住超时自动强清
"""
from __future__ import annotations

import gsi_handler_special
import pytest
from config import config


# ---------- 1. 胜负/MVP：win_team 与 over 沿解耦 ----------

class _ImmediateTimer:
    """threading.Timer 替身：start() 时同步执行回调（消除 0.15s MVP 延迟）。"""

    def __init__(self, _interval, func, args=None, kwargs=None):
        self._func = func
        self._args = list(args or [])
        self._kwargs = dict(kwargs or {})
        self.daemon = True

    def start(self):
        self._func(*self._args, **self._kwargs)

    def cancel(self):
        return None

    def is_alive(self):
        return False


class _SpyRoundSounds:
    def __init__(self, handler, monkeypatch):
        self.win_calls = 0
        self.lose_calls = 0
        monkeypatch.setattr(handler, "_play_round_win_sound", self._win)
        monkeypatch.setattr(handler, "_play_round_lose_sound", self._lose)
        # MVP 检查定时器同步化（真实实现是 Timer(0.15) 延迟判定）
        monkeypatch.setattr(gsi_handler_special.threading, "Timer", _ImmediateTimer)
        monkeypatch.setattr(
            handler, "_check_and_play_win_sound",
            lambda _data: self._win(),
        )

    def _win(self):
        self.win_calls += 1

    def _lose(self):
        self.lose_calls += 1


def _round_payload(phase: str, win_team: str | None = None, round_no: int = 3):
    payload = {
        "map": {"round": round_no, "phase": "live"},
        "round": {"phase": phase},
        "player": {"steamid": "s1", "activity": "playing", "team": "CT",
                   "state": {"health": 100}},
    }
    if win_team is not None:
        payload["round"]["win_team"] = win_team
    return payload


@pytest.fixture()
def special_handler(monkeypatch):
    monkeypatch.setattr(config, "round_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "grenade_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "c4_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "health_warning_enabled", False, raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "s1", raising=False)
    handler = gsi_handler_special.GSIHandlerSpecial()
    handler.team_side = "ct"
    return handler


def test_win_sound_plays_when_win_team_arrives_before_over(special_handler, monkeypatch):
    """GSI 先发 win_team 再翻 over（差一帧）：旧逻辑要求同帧，胜利音效整块丢失。"""
    spy = _SpyRoundSounds(special_handler, monkeypatch)

    special_handler.process_data(_round_payload("live"))
    # win_team 先到，phase 还是 live
    special_handler.process_data(_round_payload("live", win_team="CT"))
    # 下一帧才翻 over
    special_handler.process_data(_round_payload("over", win_team="CT"))

    assert spy.win_calls == 1
    assert spy.lose_calls == 0


def test_lose_sound_plays_when_win_team_arrives_before_over(special_handler, monkeypatch):
    spy = _SpyRoundSounds(special_handler, monkeypatch)

    special_handler.process_data(_round_payload("live"))
    special_handler.process_data(_round_payload("live", win_team="T"))
    special_handler.process_data(_round_payload("over", win_team="T"))

    assert spy.lose_calls == 1
    assert spy.win_calls == 0


def test_same_team_wins_consecutive_rounds(special_handler, monkeypatch):
    """同队连胜：旧逻辑 previous_round_win 跨回合残留会吞掉第二回合的胜利音。"""
    spy = _SpyRoundSounds(special_handler, monkeypatch)

    special_handler.process_data(_round_payload("live", round_no=3))
    special_handler.process_data(_round_payload("over", win_team="CT", round_no=3))
    assert spy.win_calls == 1

    # 新回合（round 4）→ 再次 CT 胜
    special_handler.process_data(_round_payload("freezetime", round_no=4))
    special_handler.process_data(_round_payload("live", round_no=4))
    special_handler.process_data(_round_payload("over", win_team="CT", round_no=4))
    assert spy.win_calls == 2


# ---------- 2. 死亡音效独立通道 ----------

def test_death_sound_gets_dedicated_channel():
    """死亡音效不再与击杀共用 ch1——互杀时不会被击杀声(100>40) drop。"""
    from core.audio.audio_manager import AudioManager

    mgr = AudioManager()
    death_channel = mgr._select_channel("death_sound")
    kill_channel = mgr._select_channel("kill_sound")
    assert death_channel is mgr.death_sound_channel
    assert death_channel is not kill_channel


# ---------- 3. 手雷连投同优先级切入 ----------

def test_grenade_same_priority_preempts_not_drops():
    from core.audio.audio_playback_policy import PlaybackRequest, decide_channel_action

    active = PlaybackRequest(key="grenade-smoke", channel_type="grenade_sound",
                             event_type="grenade", priority=45, allow_preempt=True)
    new = PlaybackRequest(key="grenade-flash", channel_type="grenade_sound",
                          event_type="grenade", priority=45, allow_preempt=True)
    decision = decide_channel_action(new, active, channel_busy=True)
    assert decision.action == "preempt"


# ---------- 4. 音乐联动恢复 ----------

class _FakeMusicPlayer:
    def __init__(self):
        self.is_playing = True
        self.is_paused = True
        self.resume_calls = 0
        self.reset_temp_calls = 0
        self.apply_effective_calls = 0

    def resume(self):
        self.resume_calls += 1
        self.is_paused = False

    def reset_temp_volume(self):
        self.reset_temp_calls += 1

    def _apply_effective_volume(self):
        self.apply_effective_calls += 1


def test_music_restore_game_link_state_resumes_and_restores_volume():
    import gsi_handler_music

    handler = gsi_handler_music.GSIHandlerMusic()
    player = _FakeMusicPlayer()
    handler.player = player
    handler.is_paused_by_game = True
    handler.is_volume_lowered = True
    handler.player_alive = True

    handler.restore_game_link_state("测试")

    assert player.resume_calls == 1
    assert player.reset_temp_calls == 1
    assert player.apply_effective_calls == 1
    assert handler.is_paused_by_game is False
    assert handler.is_volume_lowered is False
    assert handler.player_alive is None  # 下个GSI包按全新状态判定


def test_music_restore_noop_when_not_in_link_state():
    """未处于联动态时不动播放器，避免打扰用户手动操作。"""
    import gsi_handler_music

    handler = gsi_handler_music.GSIHandlerMusic()
    player = _FakeMusicPlayer()
    handler.player = player
    handler.is_paused_by_game = False
    handler.is_volume_lowered = False

    handler.restore_game_link_state()

    assert player.resume_calls == 0
    assert player.reset_temp_calls == 0


def test_music_handler_module_getter():
    import gsi_handler_music

    handler = gsi_handler_music.GSIHandlerMusic()
    assert gsi_handler_music.get_music_gsi_handler() is handler


# ---------- 5. 闪光断流看门狗 ----------

def test_flash_stale_watchdog_force_clears(monkeypatch):
    from flash_process_manager import FlashProcessManager

    manager = FlashProcessManager.__new__(FlashProcessManager)  # 不起进程
    manager.current_flash_value = 200
    manager._last_flash_update_time = 1000.0
    manager.flash_stale_timeout = 10.0
    cleared = {"count": 0}
    manager.force_clear_flash = lambda: cleared.__setitem__("count", cleared["count"] + 1)

    # 未超时：不清
    assert manager._check_flash_stale(1005.0) is False
    assert cleared["count"] == 0

    # 超时：强清并归零
    assert manager._check_flash_stale(1011.0) is True
    assert cleared["count"] == 1
    assert manager.current_flash_value == 0


def test_flash_stale_watchdog_ignores_zero_value():
    from flash_process_manager import FlashProcessManager

    manager = FlashProcessManager.__new__(FlashProcessManager)
    manager.current_flash_value = 0
    manager._last_flash_update_time = 1000.0
    manager.flash_stale_timeout = 10.0
    manager.force_clear_flash = lambda: (_ for _ in ()).throw(AssertionError("不应清除"))

    assert manager._check_flash_stale(2000.0) is False