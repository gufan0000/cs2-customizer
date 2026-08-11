# -*- coding: utf-8 -*-
"""QA-015：音效转发必须发生在「按需加载」之后。

原顺序是先转发、后加载：预载有预算上限（`_max_sounds=50`，而重度配置有 171 项），
没被预载到的键第一次触发时缓存里根本没有 Sound，转发就被静默跳过 ——
本地照常出声、日志一个字没有，**队友什么都听不到**，第二次起才正常。
开了音效转发的用户，每个新音效都会先哑一次。

判据全部落在"转发接口被调了几次、传的是不是同一个 Sound 对象"上，
不看日志文本、不看源码字符串。
"""
from __future__ import annotations

import sys
import types
from collections import OrderedDict
from threading import Lock

import pytest

import config as config_mod
from core.audio.audio_manager import AudioManager


class _SilentLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _FakeSound:
    def __init__(self, name):
        self.name = name
        self.volume = 1.0

    def set_volume(self, v):
        self.volume = v

    def get_volume(self):
        return self.volume

    def get_length(self):
        return 1.0


class _FakeChannel:
    def __init__(self):
        self.played = []

    def play(self, sound, *a, **kw):
        self.played.append(sound)

    def get_busy(self):
        return False

    def stop(self):
        return None

    def set_volume(self, *_a):
        return None


class _Recorder:
    def __init__(self):
        self.calls = []

    def play_pygame_sound_to_voice(self, sound, volume):
        self.calls.append((sound, volume))


class _Cfg:
    sfx_forwarding_enabled = True
    sfx_forwarding_options = {"kill_sound": True, "kill_voice": True}
    voice_output_enabled = True
    audio_event_timeline_enabled = False
    audio_policy_profile = "kill_preempt_v1"
    volume = 1.0
    category_volumes = {}


@pytest.fixture
def am(monkeypatch):
    """只搭出 LRU/播放需要的字段，不跑 __init__（那会初始化 mixer 占设备）。"""
    mgr = AudioManager.__new__(AudioManager)
    mgr.logger = _SilentLogger()
    mgr._lock = Lock()
    from threading import RLock
    mgr._playback_lock = RLock()
    mgr._sounds = {}
    mgr._access_order = OrderedDict()
    mgr._max_sounds = 50
    mgr._styles_scanned = True
    mgr._volume = 1.0
    mgr._active_channel_requests = {}
    mgr.kill_sound_channel = _FakeChannel()
    mgr.kill_voice_channel = _FakeChannel()

    recorder = _Recorder()
    fake_mod = types.ModuleType("voice_output_manager")
    fake_mod.get_voice_output_manager = lambda: recorder
    monkeypatch.setitem(sys.modules, "voice_output_manager", fake_mod)
    monkeypatch.setattr(config_mod, "config", _Cfg())

    def _load(key):
        """扮演真实的按需加载：走真实 _store 把 Sound 塞进缓存。"""
        mgr._store(key, _FakeSound(key), path=f"{key}.wav", category="kill")
        return True

    monkeypatch.setattr(mgr, "_load_sound_by_key", _load)
    monkeypatch.setattr(mgr, "_load_voice_by_key", _load)
    mgr._recorder = recorder
    return mgr


def test_cold_key_first_play_is_forwarded(am):
    """缓存为空时的第一次播放，队友也必须听得到。"""
    assert "kill-CF-1" not in am._sounds
    am.play_sound("kill-CF-1", channel_type="kill_sound")

    assert len(am._recorder.calls) == 1, (
        "冷键第一次播放没有转发 —— 队友这一次听不到（QA-015）")
    forwarded = am._recorder.calls[0][0]
    played = am.kill_sound_channel.played[-1]
    assert forwarded is played, "转发出去的不是本地实际播放的那个 Sound 对象"


def test_evicted_key_replay_is_forwarded(am):
    """被 LRU 挤出缓存后重播，同样不许哑一次。"""
    am.play_sound("kill-CF-1", channel_type="kill_sound")
    am.play_sound("kill-CF-1", channel_type="kill_sound")
    before = len(am._recorder.calls)

    for i in range(60):
        am._store(f"filler-{i}", _FakeSound(f"filler-{i}"),
                  path=f"filler-{i}.wav", category="kill")
    assert "kill-CF-1" not in am._sounds, "填充没能把目标键挤出缓存，判据前提不成立"

    am.play_sound("kill-CF-1", channel_type="kill_sound")
    assert len(am._recorder.calls) == before + 1, "被挤出后重播又哑了一次"


def test_play_voice_cold_key_is_forwarded(am):
    """play_voice 是同一个错，一并守住。"""
    assert "voice-CF-1" not in am._sounds
    am.play_voice("voice-CF-1")

    assert len(am._recorder.calls) == 1, "语音冷键第一次播放没有转发（QA-015）"
    forwarded = am._recorder.calls[0][0]
    played = am.kill_voice_channel.played[-1]
    assert forwarded is played, "转发出去的不是本地实际播放的那个 Sound 对象"
