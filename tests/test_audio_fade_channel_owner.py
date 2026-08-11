# -*- coding: utf-8 -*-
"""QA-016：上一段回合音效的淡出定时器，不许把下一段已经在播的音效掐掉。

五个回合音效（start/action/win/lose/mvp）共用同一个 round_sound 通道。
淡出 Timer 是在 fade_in 跑完之后才 start 的，所以实际落点 ≈ 素材长度 + fade_in,
早已越过"自己还在播"的时刻；等它触发时通道上往往换成了**下一回合的音效**，
而那句 `channel.stop()` 会把别人的声音硬切掉。
竞技 7 秒冻结期下，只要胜/负素材长度落在约 6.4~12.4 秒（用户自己导入的号角/梗音效
绝大多数在这段），**每个己方胜负回合都必现**。

两条一组，缺一不可：
- A（反向）：碰撞时新音效必须活着 —— 回退即红；
- B（正向对照）：单播时淡出斜坡必须真的跑过 —— 防"干脆不建 Timer"让 A 假绿。
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from threading import Lock

import pytest

import config as config_mod
from core.audio.audio_manager import AudioManager


class _SilentLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _FakeSound:
    def __init__(self, name, length):
        self.name = name
        self._length = length
        self.volume = 1.0
        self.min_volume = 1.0

    def set_volume(self, v):
        self.volume = v
        self.min_volume = min(self.min_volume, v)

    def get_volume(self):
        return self.volume

    def get_length(self):
        return self._length


class _FakeChannel:
    """按时间算 busy；stop 时记下 (时刻, 被停的 Sound 名)。"""

    def __init__(self):
        self.current = None
        self.end_at = 0.0
        self.stop_log = []
        self._lock = Lock()

    def play(self, sound, *a, **kw):
        with self._lock:
            self.current = sound
            self.end_at = time.time() + sound.get_length()

    def get_busy(self):
        with self._lock:
            return self.current is not None and time.time() < self.end_at

    def stop(self):
        with self._lock:
            self.stop_log.append((time.time(), getattr(self.current, "name", None)))
            self.current = None
            self.end_at = 0.0

    def set_volume(self, *_a):
        return None


class _Cfg:
    round_sound_volume = 1.0
    volume = 1.0
    category_volumes = {}
    audio_event_timeline_enabled = False


def _probe(monkeypatch, sounds):
    mgr = AudioManager.__new__(AudioManager)
    mgr.logger = _SilentLogger()
    mgr._lock = Lock()
    mgr._sounds = {}
    mgr._access_order = OrderedDict()
    mgr._max_sounds = 50
    mgr._styles_scanned = True
    mgr._volume = 1.0
    mgr.fade_timers = {}
    mgr.fade_threads = {}
    mgr.fade_owner = {}
    mgr._fade_seq = 0
    channel = _FakeChannel()
    mgr.round_sound_channel = channel
    for key, snd in sounds.items():
        mgr._store(key, snd, path=f"{key}.wav", category="round")
    monkeypatch.setattr(config_mod, "config", _Cfg())
    return mgr, channel


@pytest.fixture(autouse=True)
def _join_timers():
    yield
    # 别把 Timer 漏给下一个用例
    for t in list(threading.enumerate()):
        if isinstance(t, threading.Timer):
            t.cancel()


def test_previous_round_sound_fadeout_must_not_kill_the_next_one(monkeypatch):
    """碰撞档：旧音效的淡出定时器到点时，新音效必须毫发无伤。"""
    win = _FakeSound("round-win-1", 1.0)
    start = _FakeSound("round-start-1", 2.0)
    mgr, channel = _probe(monkeypatch, {"round-win-1": win, "round-start-1": start})

    mgr.play_sound_with_fade("round-win-1", "round_sound", fade_in_ms=50, fade_out_ms=200)
    time.sleep(0.5)
    mgr.play_sound_with_fade("round-start-1", "round_sound", fade_in_ms=50, fade_out_ms=200)

    # 等到旧 Timer 早已触发并跑完（旧的落点 ≈ 0.05 + (1.0-0.2) + 0.2 ≈ 1.05s）
    time.sleep(1.3)

    victims = [name for _t, name in channel.stop_log if name == "round-start-1"]
    assert not victims, (
        f"上一回合音效的淡出把下一段掐掉了（QA-016）：stop_log={channel.stop_log}")
    assert channel.get_busy(), "新音效应该还在播"
    assert channel.current is start, f"通道上的不是新音效：{channel.current}"
    assert start.volume == pytest.approx(1.0), (
        f"新音效的音量被旧音效的淡出循环写过了：{start.volume}")


def test_fade_out_timer_still_ramps_the_sound_it_owns(monkeypatch):
    """正向对照：只播一个时，淡出斜坡必须真的跑过。

    这条与修复无关、必须始终绿。它锁死了"干脆不建 Timer / 直接 return"
    这类能让上一条假绿的偷懒改法。
    """
    win = _FakeSound("round-win-1", 1.0)
    mgr, _channel = _probe(monkeypatch, {"round-win-1": win})

    mgr.play_sound_with_fade("round-win-1", "round_sound", fade_in_ms=50, fade_out_ms=200)
    time.sleep(1.15)

    assert win.min_volume < 0.8, (
        f"淡出斜坡根本没跑过（最低音量 {win.min_volume}）—— 淡出功能已经死了")
