# -*- coding: utf-8 -*-
"""QA-017：音板的"本地监听"必须跟随当前的 Windows 默认输出。

PortAudio 在进程内只枚举一次设备（全仓也没有 `_terminate()/_initialize()`），
所以 `default_speaker_id` 是启动那一刻冻结下来的**具体物理设备**索引。
用户中途换耳机之后：旧设备还在但已非默认 → 监听持续从旧设备出声，
用户戴着耳机听不到；旧设备已拔掉 → 开流抛异常被吞成一条日志，界面毫无提示。

修法是改走 MME 的 WAVE_MAPPER 伪设备（每次开流才解析当时的默认）。
判据用一个**忠实模拟 PortAudio 冻结语义**的假 sounddevice：
`query_devices` 永远返回启动时那份快照，另设一个 `win_default_out` 表示
"Windows 此刻的默认"；假 OutputStream 在 device 是映射器时把路由解析成
`win_default_out` 那台 —— 这就是 WAVE_MAPPER 的真实行为。
"""
from __future__ import annotations

import time
import types

import numpy as np
import pytest

import voice_output_manager as vom

MAPPER_IDX = 2
SNAPSHOT_DEFAULT_OUT = 3          # 启动时的默认 = 音箱
CABLE_IDX = 4
HEADSET_IDX = 5

_DEVICES = [
    {"name": "Microsoft 声音映射器 - Input", "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 44100.0, "hostapi": 0},
    {"name": "麦克风 (Realtek)", "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 44100.0, "hostapi": 0},
    {"name": "Microsoft 声音映射器 - Output", "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 44100.0, "hostapi": 0},
    {"name": "音箱 (Realtek)", "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 44100.0, "hostapi": 0},
    {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 44100.0, "hostapi": 0},
    {"name": "耳机 (USB Headset)", "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 44100.0, "hostapi": 0},
]


class _FakeStream:
    def __init__(self, routed, device, **_kw):
        self.routed = routed
        self.device = device

    def start(self):
        return None

    def write(self, _chunk):
        return None

    def stop(self):
        return None

    def close(self):
        return None


def _make_fake_sd(default_out_idx: int, win_default_out: int, routed: list):
    """默认输出的**快照**在 default_out_idx；Windows 此刻的默认在 win_default_out。"""
    mod = types.SimpleNamespace()
    devices = [dict(d) for d in _DEVICES]

    def query_devices(device=None, kind=None):
        if kind == "output":
            return devices[default_out_idx]
        if kind == "input":
            return devices[1]
        if device is None:
            return devices
        return devices[device]

    def query_hostapis():
        return [{"name": "MME", "devices": list(range(len(devices)))}]

    def OutputStream(device=None, **kw):        # noqa: N802 —— 模仿 sounddevice 的名字
        # 映射器的真实行为：开流时才解析到"当时的 Windows 默认"
        resolved = win_default_out if device == MAPPER_IDX else device
        routed.append(devices[resolved]["name"] if resolved is not None else None)
        return _FakeStream(routed, device, **kw)

    def check_output_settings(**_kw):
        return None

    mod.query_devices = query_devices
    mod.query_hostapis = query_hostapis
    mod.OutputStream = OutputStream
    mod.check_output_settings = check_output_settings
    mod.default = types.SimpleNamespace(device=(1, default_out_idx))
    return mod


@pytest.fixture
def audio_block():
    return np.zeros((4800, 2), dtype=np.float32)


def _wait_routed(routed, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline and not routed:
        time.sleep(0.02)
    assert routed, "一次开流都没记录到 —— 判据自己没跑起来，不许当成通过"
    return routed


def test_local_monitor_follows_current_default_not_startup_snapshot(monkeypatch, audio_block):
    """换了耳机之后，监听必须落到耳机，而不是启动时那台音箱。"""
    routed: list = []
    fake = _make_fake_sd(SNAPSHOT_DEFAULT_OUT, win_default_out=HEADSET_IDX, routed=routed)
    monkeypatch.setattr(vom, "sd", fake)

    mgr = vom.VoiceOutputManager()
    mgr.detect_devices()
    # 前置断言：防判据自身假绿
    assert mgr.default_speaker_id == SNAPSHOT_DEFAULT_OUT, \
        f"启动快照的默认扬声器不是音箱：{mgr.default_speaker_id}"
    assert mgr.default_speaker_id != MAPPER_IDX

    mgr._play_data_locally(audio_block, 48000)
    _wait_routed(routed)

    assert routed[-1] == "耳机 (USB Headset)", (
        f"监听落到了 {routed[-1]}，没跟上当前的 Windows 默认输出（QA-017）")


def test_local_monitor_avoids_cable_when_cable_is_system_default(monkeypatch, audio_block):
    """系统默认输出就是 CABLE 时，监听绝不能灌回虚拟麦。

    这条防的是修法自身的回归：走映射器会让同一段音频被写进虚拟麦两遍，
    队友听到叠加/回声，用户本地反而彻底没声。
    """
    routed: list = []
    fake = _make_fake_sd(CABLE_IDX, win_default_out=CABLE_IDX, routed=routed)
    monkeypatch.setattr(vom, "sd", fake)

    mgr = vom.VoiceOutputManager()
    mgr.detect_devices()

    mgr._play_data_locally(audio_block, 48000)
    _wait_routed(routed)

    assert "CABLE" not in (routed[-1] or ""), (
        f"监听被灌回虚拟麦了：{routed[-1]}")
