# SPDX-License-Identifier: GPL-3.0-or-later
"""v2.2.1 击杀音效丢失修复的回归测试。

覆盖三条真实丢音路径的修复：
1. 回合闩锁三重兜底（基线增量 / 基线回落 / 超时）——中途加入、归零包丢失不再整回合静音
2. match_stats 缺失降级——GSI cfg 无 player_match_stats 时回合结束补枪仍放行
3. 过渡防抖的开火推断放行
"""
from __future__ import annotations

import gsi_handler_kills
import pytest
from config import config


class _DummyAudioManager:
    def __init__(self):
        self.play_sound_calls: list[tuple[str, str]] = []
        self.play_voice_calls: list[str] = []

    def play_sound(self, key: str, channel_type: str = "kill_sound", **_kwargs):
        self.play_sound_calls.append((key, channel_type))
        return True

    def play_voice(self, key: str):
        self.play_voice_calls.append(key)


@pytest.fixture()
def handler(monkeypatch):
    dummy_audio = _DummyAudioManager()
    monkeypatch.setattr(gsi_handler_kills, "audio_manager", dummy_audio)
    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "mode", "1. 官匹竞技", raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "test_steamid", raising=False)

    h = gsi_handler_kills.GSIHandlerKills()
    # 键名带等级，方便断言播放的是第几连杀
    monkeypatch.setattr(
        h, "_get_weapon_kill_sound_key",
        lambda _weapon, level, _hs=False: f"kill-{level}",
    )
    h._dummy_audio = dummy_audio
    return h


def _payload(round_no: int, round_kills: int, *, phase: str = "live",
             match_kills: int | None = None, killhs: int = 0):
    player = {
        "steamid": "test_steamid",
        "activity": "playing",
        "state": {"health": 100, "round_kills": round_kills, "round_killhs": killhs},
        "weapons": {"weapon_0": {"name": "weapon_ak47", "state": "active"}},
    }
    if match_kills is not None:
        player["match_stats"] = {"kills": match_kills}
    return {
        "map": {"round": round_no, "phase": "live"},
        "round": {"phase": phase},
        "player": player,
    }


def _played(handler):
    return [k for k, c in handler._dummy_audio.play_sound_calls if c == "kill_sound"]


# ---------- 闩锁兜底 ----------

def test_latch_releases_on_increment_above_baseline_mid_join(handler):
    """中途加入：首包 round_kills=3（闩锁+采基线），随后打出第4杀应立即放行。"""
    # 首包触发"新回合"检测（previous_round=None→5），phase=live → 闩锁置位
    handler.process_data(_payload(5, 3, match_kills=3))
    assert _played(handler) == []  # 存量计数不播

    handler.process_data(_payload(5, 4, match_kills=4))
    assert _played(handler) == ["kill-4"]  # 新击杀放行，且等级正确


def test_latch_releases_on_drop_below_baseline_lost_zero_packet(handler):
    """归零包丢失：闩锁期计数从基线3直接跌到1（新回合已在计数）应按新生命放行。"""
    handler.process_data(_payload(5, 3, match_kills=3))
    assert _played(handler) == []

    # 0 包被队列丢弃，直接来了新回合的第1杀
    handler.process_data(_payload(5, 1, match_kills=4))
    assert _played(handler) == ["kill-1"]


def test_latch_releases_on_timeout(handler, monkeypatch):
    """计数持平卡闩锁：15s 超时后释放，后续击杀恢复播放。"""
    fake_now = [1000.0]
    monkeypatch.setattr(gsi_handler_kills.time, "time", lambda: fake_now[0])

    handler.process_data(_payload(5, 3, match_kills=3))
    handler.process_data(_payload(5, 3, match_kills=3))
    assert _played(handler) == []

    fake_now[0] += 16.0
    handler.process_data(_payload(5, 3, match_kills=3))  # 超时包：释放但不播
    assert _played(handler) == []

    handler.process_data(_payload(5, 4, match_kills=4))
    assert _played(handler) == ["kill-4"]


def test_latch_normal_zero_release_unchanged(handler):
    """原有行为不变：见到归零包正常释放，后续击杀从1开始播。"""
    handler.process_data(_payload(5, 3, match_kills=3))
    handler.process_data(_payload(5, 0, match_kills=3))  # 归零
    handler.process_data(_payload(5, 1, match_kills=4))
    assert _played(handler) == ["kill-1"]


# ---------- match_stats 缺失降级 ----------

def test_round_end_kill_allowed_without_match_stats_component(handler):
    """会话从未见过 match_stats：over 阶段补枪应降级放行。"""
    # 先正常打一杀建立状态（无 match_stats 字段）
    handler.previous_round = 5
    handler.process_data(_payload(5, 1))
    assert _played(handler) == ["kill-1"]

    # 回合结束瞬间补枪：phase=over，round_kills 2
    handler.process_data(_payload(5, 2, phase="over"))
    assert _played(handler) == ["kill-1", "kill-2"]


def test_round_end_kill_still_strict_when_match_stats_present(handler):
    """见过 match_stats 的会话维持严格校验：over 且 match_kills 未涨不播。"""
    handler.previous_round = 5
    handler.process_data(_payload(5, 1, match_kills=10))
    assert _played(handler) == ["kill-1"]

    # over 阶段 round_kills 涨了但 match_kills 没涨（如观战视角切换噪声）→ 不播
    handler.process_data(_payload(5, 2, phase="over", match_kills=10))
    assert _played(handler) == ["kill-1"]


# ---------- 过渡防抖的开火推断放行 ----------

def test_transition_guard_bypassed_when_fire_inferred(handler, monkeypatch):
    """phase 缺失 + 新回合 0.3s 内，但本帧有开火推断 → 是真实击杀，应放行。"""
    handler.previous_round = 5
    # 直接构造防抖窗口内的状态
    handler._ensure_kill_state("test_steamid", gsi_handler_kills.time.time())
    handler.new_round_start_time["test_steamid"] = gsi_handler_kills.time.time()
    handler.await_round_kill_reset["test_steamid"] = False

    payload = _payload(5, 1)
    payload["round"] = {}  # phase 缺失
    payload["map"].pop("phase", None)
    monkeypatch.setattr(handler, "_get_round_phase", lambda _d: "")
    # 模拟弹药差分推断到开火
    handler.frame_inferred_fire_weapon = "weapon_ak47"
    monkeypatch.setattr(handler, "_infer_fired_weapon", lambda _s: "weapon_ak47")

    handler.process_data(payload)
    assert _played(handler) == ["kill-1"]


# ---------- AudioManager 级集成：爆头声占道时普通击杀切入而非被吞 ----------

class _FakeSound:
    def __init__(self):
        self.play_calls = 0

    def set_volume(self, _v):
        return None

    def play(self, loops=0):
        self.play_calls += 1


class _FakeBusyChannel:
    def __init__(self):
        self.stop_calls = 0
        self.play_calls = []

    def get_busy(self):
        return True  # 始终忙：模拟爆头声还在播

    def stop(self):
        self.stop_calls += 1

    def play(self, sound, loops=0):
        self.play_calls.append(sound)


def test_audio_manager_kill_preempts_active_headshot(monkeypatch):
    """端到端验证修复①：真实 play_sound 路径上，普通击杀(100)在爆头声(110)
    占道时应 preempt 播放而不是被 drop 静音。"""
    from core.audio.audio_manager import AudioInfo, AudioManager

    mgr = AudioManager()
    fake_channel = _FakeBusyChannel()
    monkeypatch.setattr(mgr, "_select_channel", lambda _ct: fake_channel)

    hs_sound, kill_sound = _FakeSound(), _FakeSound()
    mgr._sounds["kill-hs"] = AudioInfo(path="hs.mp3", category="kill_sound", loaded=True, sound=hs_sound)
    mgr._sounds["kill-2"] = AudioInfo(path="k2.mp3", category="kill_sound", loaded=True, sound=kill_sound)
    mgr._access_order["kill-hs"] = None
    mgr._access_order["kill-2"] = None

    # 第一声：爆头（通道忙但无 active 元数据 → preempt 播放，登记 active=headshot/110）
    assert mgr.play_sound("kill-hs", channel_type="kill_sound", event_type="headshot", allow_preempt=True)
    # 第二声：普通击杀——旧策略在此 lower_priority drop（返回 False），修复后必须切入
    assert mgr.play_sound("kill-2", channel_type="kill_sound", event_type="kill", allow_preempt=True)
    assert fake_channel.play_calls[-1] is kill_sound  # 第二声真实播出
    assert fake_channel.stop_calls >= 1  # 切入前停掉了占道的爆头声


def test_transition_guard_still_absorbs_stale_count_without_fire(handler, monkeypatch):
    """phase 缺失 + 窗口内无开火推断 → 仍按残留计数吸收，不播。"""
    handler.previous_round = 5
    handler._ensure_kill_state("test_steamid", gsi_handler_kills.time.time())
    handler.new_round_start_time["test_steamid"] = gsi_handler_kills.time.time()
    handler.await_round_kill_reset["test_steamid"] = False

    payload = _payload(5, 1)
    payload["round"] = {}
    payload["map"].pop("phase", None)
    # 去掉 weapons，避免弹药差分产生开火推断
    payload["player"].pop("weapons", None)
    monkeypatch.setattr(handler, "_get_round_phase", lambda _d: "")
    monkeypatch.setattr(handler, "_infer_fired_weapon", lambda _s: "")

    handler.process_data(payload)
    assert _played(handler) == []
