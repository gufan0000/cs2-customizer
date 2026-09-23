# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""社区报障（社区创作者，2026-09-22）：音乐盒无法触发 / 语音触发很奇怪 / 不能叠加。

他那句「左下角应该是一直开麦然后播放我的音乐盒的」是关键 —— 截图里左下角
**没有**开麦图标。所以要量的是 `keyboard.press/release` 的事件序列，
不是有没有字节写进 VB-Cable。

本文件守五件事，每一条都对应一处实测出来的缺陷：

  ① 播放被取消后，线程不许再睡满**整首歌**才放开麦键
     —— 旧代码 `time.sleep(remaining_time + 0.1)` 不看 cancel_event，而
        remaining_time 是按完整数组长度算的。一首 3 分钟的音乐盒被停掉
        = 3 分钟热麦 + VB-Cable 被占住 3 分钟。
  ② 一次播放只许按一次、松一次
     —— 以前两套兜底计时器检查条款不对称，实测每次播完盲放 3 次（按 1 / 松 4）。
        2026-09-23 两套兜底整体换成「保持尾巴」，这条照样守着计数。
  ③ stop_playback() 不许把**别人**持有的麦克风静音引用清零
     —— 它只取消独占播放那一路，却把所有路共用的 refcount 一把归零。
  ④ 混音模式在麦克风穿透没跑时，不许把音频丢进一个没人读的槽
     —— current_mix_audio 的唯一读者是 passthrough_worker（AST 核实）。
  ⑤ 驱动缺失时，音板不许在界面上显示"正在播放"

第二轮（2026-09-23）补的：
  ⑧ 连续两段音效之间不许「松开 → 再按下」（用户原话「他会等关上再开麦」）
  ⑨ 保持尾巴结束后键必须真的松开，不许一直按着
  ⑩ 开麦延迟在**按下之后**等，不是先等再按；键已按着就不等
  ⑪ 回合音效（MVP / 比赛结束等 8 个事件）必须转发 —— 以前那个勾选框是假的
  ⑫ 同组（回合音效）新的一段取消旧的一段
  ⑬ 退出时松开开麦键（退出链路末尾是 os._exit，没人会再补一个抬起）

第三轮（2026-09-23）补的：
  ⑰ stop_playback 不 join、也不抹掉它没取消的那几路本地播放
  ⑱ 转发说明说真话：转发总按「覆盖」播，与页面模式无关（行为 + 文案两条）

⛔ 全程不碰真音频设备（CLAUDE.md §3）：sounddevice / keyboard 全部打桩。
"""
from __future__ import annotations

import threading
import time
import types

import numpy as np
import pytest

import voice_output_manager as vom

CABLE_IDX = 3
_OPEN_LOG: list = []          # (device, 开流时刻) —— 量「按下到出声」的间隔用
_DEVICES = [
    {"name": "Microsoft 声音映射器 - Output", "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 48000.0, "hostapi": 0},
    {"name": "音箱 (Realtek)", "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 48000.0, "hostapi": 0},
    {"name": "麦克风 (Realtek)", "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 48000.0, "hostapi": 0},
    {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 48000.0, "hostapi": 0},
]


class _FakeStream:
    """写入按真实时长阻塞 —— 判据量的是墙钟，流必须忠实地慢下来。"""

    def __init__(self, opened, device=None, samplerate=48000, **_kw):
        self._opened, self.device, self.rate = opened, device, samplerate
        self._on = False

    def start(self):
        self._opened.append(self.device)
        _OPEN_LOG.append((self.device, time.time()))
        self._on = True

    def write(self, data):
        time.sleep(len(data) / float(self.rate))

    def read(self, n):
        time.sleep(n / float(self.rate))
        return np.zeros((n, 2), dtype="float32"), False

    def stop(self):
        return None

    def close(self):
        if self._on:
            self._opened.remove(self.device)
            self._on = False


def _fake_sd(opened):
    mod = types.SimpleNamespace()
    devices = [dict(d) for d in _DEVICES]

    def query_devices(device=None, kind=None):
        if kind == "output":
            return devices[1]
        if kind == "input":
            return devices[2]
        return devices if device is None else devices[device]

    mod.query_devices = query_devices
    mod.query_hostapis = lambda: [{"name": "MME", "devices": [0, 1, 2, 3]}]
    mod.OutputStream = lambda **kw: _FakeStream(opened, **kw)
    mod.InputStream = lambda **kw: _FakeStream(opened, **kw)
    return mod


class _KeyLog:
    """记下每一次 press/release，带时间戳 —— 麦哪一刻开着由它裁定。"""

    def __init__(self):
        self.events = []
        self._t0 = time.time()

    def press(self, key):
        self.events.append(("press", key, time.time() - self._t0))

    def release(self, key):
        self.events.append(("release", key, time.time() - self._t0))

    @property
    def presses(self):
        return [e for e in self.events if e[0] == "press"]

    @property
    def releases(self):
        return [e for e in self.events if e[0] == "release"]


@pytest.fixture
def manager(monkeypatch):
    """一个装好了假 VB-Cable 的 VoiceOutputManager。"""
    opened, keys = [], _KeyLog()
    _OPEN_LOG.clear()
    monkeypatch.setattr(vom, "sd", _fake_sd(opened))
    monkeypatch.setattr(vom, "keyboard", keys)
    monkeypatch.setattr(vom, "sf", types.SimpleNamespace(
        read=lambda p, dtype="float32": (
            np.zeros((int(48000 * _secs(p)), 2), dtype="float32"), 48000),
        info=lambda p: types.SimpleNamespace(duration=_secs(p))))
    monkeypatch.setattr(vom.os.path, "exists", lambda p: True)

    m = vom.VoiceOutputManager()
    assert m.is_initialized and m.vb_cable_device_id == CABLE_IDX, "打桩没生效"
    m._test_keys, m._test_opened = keys, opened
    yield m
    m.force_release_ptt_key("v")


def _secs(path) -> float:
    """假音频的时长编在文件名里：`x_6.0s.wav` → 6.0 秒。"""
    return float(str(path).rsplit("_", 1)[-1].replace("s.wav", ""))


@pytest.fixture
def qapp_offscreen():
    """离屏 QApplication —— 不弹真窗口（CLAUDE.md §3）。"""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


# ── ① 取消之后不许睡满整首歌 ──────────────────────────────
def test_cancelled_playback_stops_within_a_beat_not_the_whole_track(manager):
    """6 秒音频播到 0.3 秒被取消 —— 线程必须马上收尾，不是再等 5.7 秒。

    旧代码：写循环 break 之后紧跟 `time.sleep(remaining_time + 0.1)`，
    而 remaining_time = 完整时长 - 已写时长 ≈ 5.7 秒。这段 sleep 不看
    cancel_event，于是 PTT 租约和 VB-Cable 流都被扣住 5.7 秒。
    """
    cancel = threading.Event()
    audio = np.zeros((48000 * 6, 2), dtype="float32")

    done = threading.Event()
    t0 = time.time()

    def run():
        manager._play_file_data(audio, 48000, also_local=False, cancel_event=cancel)
        done.set()

    threading.Thread(target=run, daemon=True).start()
    time.sleep(0.3)
    cancel.set()

    assert done.wait(timeout=2.5), (
        "取消之后 _play_file_data 还在睡 —— 尾部那段等待没看 cancel_event"
    )
    elapsed = time.time() - t0
    assert elapsed < 2.0, f"取消后花了 {elapsed:.2f} 秒才收尾（整首 6 秒）"
    # 流必须已经关掉，否则 VB-Cable 被一个已经没在播的线程占着
    assert manager._test_opened == [], f"取消后还有流没关：{manager._test_opened}"


# ── ② 键已松开就不许再盲放 ────────────────────────────────
def test_independent_fallback_stops_once_the_key_is_already_up(manager):
    """播完一段之后，松开次数必须等于按下次数。

    以前的独立兜底每 0.2 秒 release 一次共 3 次，前置只查租约不查
    ptt_key_pressed，实测按 1 / 松 4。2026-09-23 两套兜底整体换成保持尾巴，
    函数名留着没改（断点和登记册在引用它），守的仍是这个计数。
    """
    manager.play_audio_with_ptt_protocol(
        audio_path="x_0.4s.wav", mode="覆盖", also_local=False,
        ptt_key="v", ptt_delay=0,
    )
    time.sleep(2.0)                      # 覆盖掉独立兜底的 0.2×3 窗口

    keys = manager._test_keys
    assert len(keys.presses) == 1, f"按下次数异常：{keys.events}"
    assert len(keys.releases) == 1, (
        f"松开 {len(keys.releases)} 次而只按下 1 次 —— 兜底在盲放：{keys.events}"
    )


# ── ③ stop_playback 不许清掉别人的静音引用 ────────────────
def test_stop_playback_leaves_a_concurrent_forwards_mute_alone(manager):
    """一路转发正持有麦克风静音时，音板触发的 stop_playback 不许解除它。

    refcount 这个机制本来就是为了防「B 路结束不能把仍在转发的 A 路提前
    解除静音」（见 __init__ 里的注释），而 stop_playback 单方面清零把它绕过去了。
    """
    manager._acquire_mic_mute()                   # 假装有一路转发正在写
    assert manager.mute_microphone is True

    manager.stop_playback()

    assert manager._mute_refcount == 1, "别人的静音引用被 stop_playback 清零了"
    assert manager.mute_microphone is True, (
        "转发还在写 VB-Cable，麦克风静音却被提前解除 —— 本地麦会混进去"
    )
    manager._release_mic_mute()
    assert manager.mute_microphone is False       # 归零后才真的解除


# ── ④ 混音模式在没人消费时要退回直写 ──────────────────────
def test_mix_mode_does_not_drop_audio_into_a_slot_nobody_reads(manager):
    """麦克风穿透没跑时，混音模式必须退回直写，而不是静默丢弃。

    _play_with_mix_data 自己不写 VB-Cable，它只把数据放进 current_mix_audio，
    唯一的读者是 passthrough_worker 的转发循环。穿透没在跑的时候，这段音频
    既不会被读走、也不会被清空 —— 不报错、不出声。
    """
    assert manager.microphone_passthrough_active is False

    handed_off = manager._play_with_mix_data(
        np.zeros((48000, 2), dtype="float32"), 48000, also_local=False)

    assert handed_off is False, "没人消费却报告交接成功"
    assert manager.current_mix_audio is None, (
        "返回 False 还把数据塞进了 current_mix_audio —— 会变成永不清理的残留，"
        "等下次穿透真启动了突然播出来"
    )

    # 端到端：走 mode=混音 的完整协议，必须落到直写那条路上
    wrote = []
    real = manager._play_file_data
    manager._play_file_data = lambda *a, **k: (wrote.append(1), real(*a, **k))[1]
    manager.play_audio_with_ptt_protocol(
        audio_path="m_0.3s.wav", mode="混音", also_local=False,
        ptt_key="v", ptt_delay=0,
    )
    time.sleep(1.5)
    assert wrote, "混音模式在穿透没跑时没有退回直写 —— 这一段被静默丢弃了"


# ── ⑤ 驱动缺失时不许假装在播 ──────────────────────────────
def test_soundboard_does_not_claim_to_play_without_the_driver():
    """VB-Cable 没装时，音板槽位不许在界面上显示「▶ 播放」。

    play_audio_with_ptt_protocol 在未初始化时是同步 `return False`（不抛异常），
    旧代码把返回值直接丢掉、无条件 emit「▶ 播放」，外面那层 try/except 也
    接不到 —— 用户看到的是"在播放"，实际一个字节都没出去，也没有任何线索
    指向驱动。这正是报障里「音乐盒还是无法触发」的形状。
    """
    from pages.voice_output_page import VoiceOutputPage

    emitted, cleared, toasted = [], [], []
    fake_mgr = types.SimpleNamespace(
        is_initialized=False,
        get_sound_duration=lambda p: 3.0,
        play_audio_with_ptt_protocol=lambda **kw: False,
    )
    page = types.SimpleNamespace(
        soundboard_slots={0: {"audio": r"C:\x\music.mp3", "name": "music.mp3",
                              "volume": 1.0}},
        voice_manager=fake_mgr,
        ptt_key="v", ptt_enabled=True, ptt_delay=0,
        logger=types.SimpleNamespace(info=lambda *a: None, warning=lambda *a: None,
                                     error=lambda *a: None),
        _status_signal=types.SimpleNamespace(emit=emitted.append),
        _status_clear_signal=types.SimpleNamespace(emit=cleared.append),
        _toast_error_signal=types.SimpleNamespace(emit=toasted.append),
    )
    page._playback_refusal_reason = lambda p: VoiceOutputPage._playback_refusal_reason(page, p)

    VoiceOutputPage._trigger_slot(page, 0)

    assert emitted, "什么都没说 —— 用户按了键完全没有反馈"
    said = emitted[0]
    assert "▶ 播放" not in said, f"驱动没装却报告在播放：{said!r}"
    assert "VB-Cable" in said, f"没告诉用户真正的原因：{said!r}"
    # ⛔ 只写 status_label 不算数 —— 它在折叠线以下（见下一条判据）
    assert toasted, "只写了状态栏，而状态栏在滚动区折叠线以下，用户看不见"
    assert "VB-Cable" in toasted[0], f"浮层没说原因：{toasted[0]!r}"


# ── ⑦ 反馈不许只落在折叠线以下 ────────────────────────────
def test_the_failure_notice_does_not_hide_below_the_fold(qapp_offscreen):
    """播不出去的提示必须有一路是用户当场看得见的。

    ⭐ 实测：`status_label` 映射到整页坐标 y≈1009，而滚动区视口只有 746 ——
      它在折叠线**以下 200 多像素**。`isVisible()` 返回 True，`isHidden()`
      返回 False，两个都骗人（RN-673 同形，第二次）。
      用户按下音板快捷键时眼睛多半还在游戏里，更不会滚到页底去找。
    ⇒ 这条判据钉两件事：那个标签确实在折叠线以下（所以不能只靠它），
      且失败路径确实另走了一条浮层。
    """
    from pages.voice_output_page import VoiceOutputPage

    page = VoiceOutputPage()
    page.resize(1280, 800)
    page.show()
    qapp_offscreen.processEvents()
    lab = page.status_label
    bottom = lab.mapTo(page, lab.rect().bottomRight()).y()
    viewport_h = page.height()
    page.close()

    if bottom <= viewport_h:
        pytest.skip("status_label 已经挪进首屏了 —— 这条判据的前提不再成立，"
                    "请连同 _toast_error_signal 一起重新评估")
    assert hasattr(VoiceOutputPage, "_toast_playback_failure"), (
        f"状态栏底边在 y={bottom} 而视口只有 {viewport_h}（折叠线以下 "
        f"{bottom - viewport_h}px），却没有任何一条浮在界面上的反馈路径"
    )


# ── ⑥ 转发被拒也要在台账里留痕 ────────────────────────────
def test_a_refused_forward_leaves_a_trace_in_the_timeline():
    """自动转发被拒（总开关关着 / 没驱动）时，事件台账必须记一笔。

    `play_pygame_sound_to_voice` 这两种情况下是 `return False` + 一行 debug，
    而 audio_manager 两处调用都把返回值丢掉了（AST 扫出同族共 4 处，另两处
    在音板那边）。⇒ 排障时「队友没听到」和「根本没转发」在台账里长得一样。
    """
    import types as _t
    from core.audio.audio_manager import AudioManager

    mgr = AudioManager.__new__(AudioManager)
    recorded = []
    mgr._record_timeline_event = lambda **kw: recorded.append(kw)
    mgr.logger = _t.SimpleNamespace(error=lambda *a: None, info=lambda *a: None)

    info = _t.SimpleNamespace(loaded=True, sound=object())
    refusing = _t.SimpleNamespace(play_pygame_sound_to_voice=lambda *a, **k: False)

    # 只跑转发那一段（play_sound 的其余部分要真 mixer），逻辑与产品代码同构
    forwarded = refusing.play_pygame_sound_to_voice(info.sound, 1.0)
    if not forwarded:
        mgr._record_timeline_event(
            action="forward", key="k", channel_type="kill_sound",
            event_type="kill_sound", reason="voice_output_refused", success=False)

    assert recorded, "转发被拒却没记账"
    assert recorded[0]["success"] is False

    # 产品代码里这两处确实接住了返回值 —— 用 AST 钉住，别让它退回去
    import ast
    import pathlib
    src = pathlib.Path(AudioManager.__module__.replace(".", "/") + ".py")
    root = pathlib.Path(__file__).resolve().parents[1]
    tree = ast.parse((root / src).read_text(encoding="utf-8"))
    discarded = {id(n.value) for n in ast.walk(tree)
                 if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)}
    dropped = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Call)
               and getattr(n.func, "attr", "") == "play_pygame_sound_to_voice"
               and id(n) in discarded]
    assert not dropped, (
        f"audio_manager 第 {dropped} 行又把转发的返回值丢了 —— "
        "拒绝转发这件事会再次从台账里消失"
    )


# ══════════════ 第二轮（2026-09-23）══════════════════════════════
class _Snd:
    """假 pygame.Sound：只需要时长。"""

    def __init__(self, sec):
        self.sec = sec

    def get_length(self):
        return self.sec


@pytest.fixture
def forwarding(manager, monkeypatch):
    """走真实的 play_pygame_sound_to_voice（音效转发那条路）。"""
    from config import config

    for name, value in (("voice_output_enabled", True), ("voice_output_ptt_enabled", True),
                        ("voice_output_ptt_key", "v"), ("voice_output_also_local", False)):
        monkeypatch.setattr(config, name, value, raising=False)
    monkeypatch.setattr(vom, "pygame", types.SimpleNamespace(
        sndarray=types.SimpleNamespace(
            array=lambda s: np.zeros((int(48000 * s.sec), 2), dtype="int16")),
        mixer=types.SimpleNamespace(get_init=lambda: (48000, -16, 2))))
    manager.mixer_sample_rate = None
    return manager


def _cable_opens():
    return [t for d, t in _OPEN_LOG if d == CABLE_IDX]


def _tail(m) -> float:
    """⚠ 用 getattr 读：判据要能在**改前的代码**上跑出「行为上的红」，
    而不是红在「旧代码没有这个属性」—— 后一种证明不了任何事（破坏验证实测过）。"""
    return float(getattr(m, "PTT_HOLD_TAIL_S", 0.5))


# ── ⑧ 连续音效共用一次开麦 ────────────────────────────────
def test_back_to_back_sounds_share_one_press(forwarding):
    """两段音效隔 ~0.1 秒：只许按一次、松一次，中间麦不许断。

    ⛔ 以前租约一归零就立刻松键，两套"兜底"计时器只在键**还按着**时才动手
       （而那时早已松开），所以它们从没起到「刷新释放时间」的作用。
       上一轮的时间线里就摆着「1.11s 松开 → 1.30s 又按下」—— 用户原话
       「他会等关上再开麦」，游戏每次重新开麦都要吞掉一截开头。
    """
    m = forwarding
    m.play_pygame_sound_to_voice(_Snd(0.4))
    time.sleep(0.6)                          # 第一段 ~0.5s 收尾，间隔 ~0.1s
    m.play_pygame_sound_to_voice(_Snd(0.4))
    time.sleep(0.5 + _tail(m) +0.6)

    keys = m._test_keys
    assert len(_cable_opens()) == 2, "两段都该写进 VB-Cable（判据自己的前提）"
    assert len(keys.presses) == 1, f"连续两段音效之间松开又按下了：{keys.events}"
    assert len(keys.releases) == 1, f"最后没松开或松了多次：{keys.events}"


# ── ⑨ 尾巴结束后必须真的松开 ──────────────────────────────
def test_the_key_goes_up_after_the_tail(forwarding):
    """保持尾巴不许变成「一直按着」：最后一段结束后 尾巴+余量 之内必须松开。"""
    m = forwarding
    m.play_pygame_sound_to_voice(_Snd(0.3))
    time.sleep(0.3 + 0.1 + _tail(m) +0.4)

    assert m._test_keys.releases, "尾巴过完了键还按着 —— 游戏里麦一直开着"
    assert m.ptt_key_pressed is False and m.ptt_lease_counter == 0


# ── ⑭ 尾巴期间麦克风直通保持静音 ──────────────────────────
def test_the_room_mic_stays_muted_while_the_tail_holds_the_key(forwarding):
    """保持尾巴里键还被软件按着、音频已经播完 —— 这时麦克风直通不许放出来。

    ⚠ 这条是新设计自己带进来的风险，写判据前我先想到了它：开了「混音/自动」的
      用户，每播完一段音效就会把房间里的声音额外播给队友半秒。
    """
    m = forwarding
    m.microphone_passthrough_active = True        # 只立标志，不起真的直通线程
    try:
        m.play_pygame_sound_to_voice(_Snd(0.3))
        time.sleep(0.6)                           # 音频 ~0.4s 收尾，正在尾巴里
        assert m.ptt_key_pressed, "前提：此刻应在保持尾巴里"
        assert m.mute_microphone is True, "尾巴期间麦克风直通没静音 —— 房间里的声音会播给队友"
        time.sleep(_tail(m) + 0.3)
        assert m.ptt_key_pressed is False
        assert m.mute_microphone is False and m._mute_refcount == 0, (
            f"尾巴结束后静音没还回去（refcount={m._mute_refcount}）—— 用户自己的麦会一直哑着")
    finally:
        m.microphone_passthrough_active = False


# ── ⑮ 解除静音与读引用计数必须原子 ────────────────────────
def test_stop_playback_unmutes_only_under_the_refcount_lock(manager, monkeypatch):
    """stop_playback 读到「没人持有静音」之后解除静音，这两步必须在同一把锁里。

    ⚠ 这是上一轮修③时我自己引进来的竞态（auditor 对抗审查逮到）：读到 0 之后、
      解除之前，另一路转发恰好加上静音 —— 分开写就会把它刚加的静音强行解除，
      房间里的声音混进那段转发。
    """
    m = manager
    held_during_unmute = []
    real = m.set_microphone_mute

    def spy(mute):
        if not mute:
            held_during_unmute.append(m._mute_lock.locked())
        return real(mute)

    monkeypatch.setattr(m, "set_microphone_mute", spy)
    m.stop_playback()
    assert held_during_unmute, "前提：没人持有静音时 stop_playback 应当解除静音"
    assert all(held_during_unmute), "解除静音时没有持有引用计数那把锁 —— 会抢掉并发转发刚加的静音"


# ── ⑯ 看门狗不许被开麦键那把锁挡死 ────────────────────────
def test_shutdown_does_not_wait_forever_on_a_held_ptt_lock(manager):
    """主线程卡在 ptt_lock 里时，shutdown 必须按时返回，并且仍然尽力松开键。

    看门狗是「15 秒必退」的最后保险，它也会调 shutdown；不带超时地拿锁，
    看门狗就会永远卡在这里、走不到 os._exit（auditor 对抗审查逮到）。
    """
    m = manager
    assert m.press_ptt_key("v") == m.PTT_PRESSED
    release_holder = threading.Event()

    def hold_lock():
        with m.ptt_lock:
            release_holder.wait(5.0)

    holder = threading.Thread(target=hold_lock, daemon=True)
    holder.start()
    time.sleep(0.1)
    done = threading.Event()
    threading.Thread(target=lambda: (m.shutdown(lock_timeout=0.3), done.set()),
                     daemon=True).start()
    finished = done.wait(2.0)
    release_holder.set()
    holder.join(2.0)
    assert finished, "ptt_lock 被占着时 shutdown 一直等下去了 —— 看门狗会被它挡死"
    assert m._test_keys.releases, "拿不到锁也得尽力松开开麦键"


# ── ⑩ 开麦延迟在按下之后 ──────────────────────────────────
def test_the_lead_in_comes_after_the_press(manager):
    """ptt_delay 是「按下开麦键之后、出声之前」等的时间。键已按着就不等。

    ⛔ 旧代码是先睡再按、按下立刻出声 —— 游戏开麦要的那段时间照样吃掉
       音频开头，延迟等于白等。
    """
    m = manager
    t_call = time.time()
    m.play_audio_with_ptt_protocol(audio_path="a_2.0s.wav", mode="覆盖", also_local=False,
                                   ptt_key="v", ptt_delay=400, allow_overlap=True)
    time.sleep(1.0)
    t_second = time.time()
    m.play_audio_with_ptt_protocol(audio_path="b_0.3s.wav", mode="覆盖", also_local=False,
                                   ptt_key="v", ptt_delay=400, allow_overlap=True)
    time.sleep(2.2)

    press_at = m._test_keys._t0 + m._test_keys.presses[0][2]
    opens = _cable_opens()
    assert len(opens) == 2, f"两段都该开流：{opens}"
    assert press_at - t_call < 0.2, f"按键被往后拖了 {press_at - t_call:.2f}s —— 延迟又放到了按键前面"
    assert opens[0] - press_at >= 0.3, (
        f"按下后 {opens[0] - press_at:.2f}s 就出声了（应 ≥0.4s）—— 游戏还没开麦，开头会被吞")
    assert opens[1] - t_second < 0.2, (
        f"键已按着，第二段却又等了 {opens[1] - t_second:.2f}s —— 麦早就开了，不该再等")
    assert len(m._test_keys.presses) == 1


# ── ⑫ 同组新的一段取消旧的一段 ────────────────────────────
def test_a_newer_sound_in_the_same_group_cancels_the_older(manager):
    """回合音效本地共用一个通道、后来的顶掉先来的；语音那边必须同样。"""
    m = manager
    m.play_audio_with_ptt_protocol(audio_path="win_3.0s.wav", mode="覆盖", also_local=False,
                                   ptt_key="v", ptt_delay=0, allow_overlap=True, group="round_sound")
    time.sleep(0.6)
    m.play_audio_with_ptt_protocol(audio_path="mvp_0.5s.wav", mode="覆盖", also_local=False,
                                   ptt_key="v", ptt_delay=0, allow_overlap=True, group="round_sound")
    time.sleep(0.25)
    assert m._test_opened.count(CABLE_IDX) == 1, (
        f"同组的旧一段还在写 VB-Cable（{m._test_opened}）—— 队友听到两段叠在一起")
    time.sleep(0.5 + _tail(m) +0.4)
    assert m._group_cancel == {}, "播完之后组登记没清掉"


# ── ⑪ 回合音效必须转发 ────────────────────────────────────
def _fade_manager(monkeypatch, options):
    """只搭出 play_sound_with_fade 需要的字段（不跑 __init__，那会初始化 mixer）。"""
    import sys
    from collections import OrderedDict
    from threading import Lock

    import config as config_mod
    from core.audio.audio_manager import AudioManager

    calls = []

    class _Voice:
        def play_pygame_sound_to_voice(self, sound, volume, group=None):
            calls.append((sound, volume, group))
            return True

    fake_mod = types.ModuleType("voice_output_manager")
    fake_mod.get_voice_output_manager = lambda: _Voice()
    monkeypatch.setitem(sys.modules, "voice_output_manager", fake_mod)
    monkeypatch.setattr(config_mod, "config", types.SimpleNamespace(
        sfx_forwarding_enabled=True, sfx_forwarding_options=options,
        round_sound_volume=0.7, volume=1.0, audio_event_timeline_enabled=False))

    class _Channel:                      # 产品代码拿通道当字典键 ⇒ 必须可哈希
        def play(self, s):
            return None

        def get_busy(self):
            return False

        def stop(self):
            return None

    channel = _Channel()
    sound = types.SimpleNamespace(set_volume=lambda v: None, get_length=lambda: 0.05)
    mgr = AudioManager.__new__(AudioManager)
    mgr.logger = types.SimpleNamespace(error=lambda *a: None, info=lambda *a: None,
                                       warning=lambda *a: None, debug=lambda *a: None)
    mgr._lock = Lock()
    mgr._sounds = {"round_mvp_x": types.SimpleNamespace(loaded=True, sound=sound, last_used=0)}
    mgr._access_order = OrderedDict()
    mgr._volume = 1.0
    mgr._fade_seq = 0
    mgr.fade_owner, mgr.fade_timers, mgr.fade_threads = {}, {}, {}
    mgr._select_channel = lambda ct: channel
    mgr._admit_playback = lambda *a, **k: True
    mgr._resolve_play_volume = lambda cfg, ct, info=None: 0.7
    mgr._record_timeline_event = lambda **kw: None
    return mgr, calls


def test_round_sounds_reach_the_voice_channel(monkeypatch):
    """「回合音效」转发勾上了，MVP / 胜负 / 比赛结束就必须进语音。

    ⛔ 以前转发只写在 play_sound 里，而 8 个回合事件全部 fade=True、走
       play_sound_with_fade —— 那条路一行转发都没有，勾选框是假的。
       用户报的「音乐盒（MVP 音乐）无法触发」「跟游戏结束的音效重合播不出来」。
    """
    mgr, calls = _fade_manager(monkeypatch, {"round_sound": True})
    played = mgr.play_sound_with_fade("round_mvp_x", channel_type="round_sound",
                                      event_type="round_mvp")
    assert played is True, (
        f"play_sound_with_fade 返回 {played!r} —— 调用方据此判成败，"
        "真播出来了日志却写「未播出」")
    assert calls, "回合音效没有转发进语音"
    assert calls[0][2] == "round_sound", f"回合音效要按组转发（同组新的顶掉旧的）：{calls[0]}"


def test_round_sounds_stay_out_when_the_box_is_unticked(monkeypatch):
    """反方向：没勾「回合音效」就不许转发（别修成一律转发）。"""
    mgr, calls = _fade_manager(monkeypatch, {"round_sound": False})
    mgr.play_sound_with_fade("round_mvp_x", channel_type="round_sound", event_type="round_mvp")
    assert calls == []


# ── ⑬ 退出时松开开麦键 ────────────────────────────────────
def test_exit_lets_go_of_the_talk_key(forwarding, monkeypatch):
    """程序在开麦那一刻被关掉，键必须被松开，且之后不许再按下。

    ⛔ 以前没有任何退出步骤碰语音输出（`cleanup()` 全仓零调用），而退出链路
       末尾是 `os._exit(0)` —— 按下去的键再也没有配对的抬起，游戏里麦一直开着。
    """
    import inspect

    from gui_widget import MainWindow

    m = forwarding
    monkeypatch.setattr(vom, "_voice_output_manager", m)
    m.play_pygame_sound_to_voice(_Snd(3.0))
    time.sleep(0.4)                              # 正在播，键按着 —— 用户此刻关掉程序
    assert m.ptt_key_pressed, "前提：此刻键应当按着"

    MainWindow._release_voice_output_on_close(types.SimpleNamespace())

    assert m.ptt_key_pressed is False, "退出后开麦键还按着"
    assert len(m._test_keys.releases) == 1
    assert m.press_ptt_key("v") == m.PTT_FAILED, "退出清理之后还能按下 —— 那一下没人松"
    time.sleep(0.3)
    assert len(m._test_keys.presses) == 1, "退出之后播放线程又把键按下去了"

    steps_src = inspect.getsource(MainWindow._run_shutdown_steps)
    assert '("松开语音开麦键", self._release_voice_output_on_close)' in steps_src, (
        "退出步骤表里没有松开麦键这一步")
    assert steps_src.count("_release_voice_output_on_close") >= 2, (
        "看门狗那条路（直接 os._exit）也得松键")


# ══════════════ 第三轮（2026-09-23）══════════════════════════════
# ── ⑰ stop_playback 只管它自己取消的那一路本地播放 ─────────────
def test_stop_playback_neither_waits_on_nor_forgets_a_forward_still_playing(forwarding, monkeypatch):
    """音板点一下（stop_playback）时，正在本地播的转发音效：不许 join 它，也不许把它从表里抹掉。

    ⛔ 以前对表里**每一个**本地播放线程 join 0.1s、再 clear() 整张表 —— 而它只取消
       独占那一路，转发的没被取消、会一直播到完：每多一路就让音板那一下多卡 0.1s，
       clear() 之后退出清理（cleanup）再也等不到这些还在写设备的线程。
    """
    from config import config

    monkeypatch.setattr(config, "voice_output_also_local", True, raising=False)
    m = forwarding
    m.play_pygame_sound_to_voice(_Snd(2.0))
    deadline = time.time() + 2.0
    while time.time() < deadline and not m.local_playback_threads:
        time.sleep(0.01)
    forward_local = list(m.local_playback_threads)
    assert forward_local, "前提：转发的本地监听线程应已登记"

    joined = []
    for t in forward_local:
        real_join = t.join
        t.join = lambda timeout=None, _t=t, _j=real_join: (joined.append(_t), _j(0))

    m.stop_playback()

    alive = [t for t in forward_local if t.is_alive()]
    assert alive, "前提：2 秒长的转发此刻应还在本地播"
    assert not joined, "stop_playback 在等一路它根本没取消的转发 —— 音板每按一下多卡 0.1s"
    assert all(t in m.local_playback_threads for t in alive), (
        "还在播的转发被 stop_playback 从本地播放表里抹掉了 —— 退出清理再也等不到它")


# ── ⑱ 音效转发那句说明要说真话 ────────────────────────────
def test_forwarding_plays_in_override_whatever_the_page_mode_says(forwarding, monkeypatch):
    """转发的模式与页面上的「模式」下拉框无关 —— 下一条判据里那句话说的就是这件事。"""
    from config import config

    m = forwarding
    seen = []
    monkeypatch.setattr(m, "play_audio_with_ptt_protocol", lambda **kw: seen.append(kw["mode"]) or True)
    modes = ("覆盖", "混音", "自动")
    for mode in modes:
        monkeypatch.setattr(config, "voice_output_mode", mode, raising=False)
        m.play_pygame_sound_to_voice(_Snd(0.1))
    assert len(seen) == len(modes), f"转发只走了 {len(seen)}/{len(modes)} 次"
    assert set(seen) == {"覆盖"}, (
        f"转发的模式跟着页面走了：{seen} —— 那音效转发页签底部那句「与模式无关」就成了假话，一起改")


def test_the_forwarding_note_does_not_send_users_to_a_switch_that_does_nothing(qapp_offscreen):
    """⛔ 旧文案「建议在覆盖或自动模式下使用，混音模式可能会有回声」是假说明：
    转发的 mode 钉死「覆盖」（上一条判据），换模式什么也换不到。
    """
    from PySide6.QtWidgets import QLabel

    from pages.voice_output_page import VoiceOutputPage

    page = VoiceOutputPage()
    try:
        # 按模式**名字**认（帮助面板也同时提到「转发」和「播放模式」，但不点名哪一种）
        notes = [lab.text() for lab in page.findChildren(QLabel)
                 if "转发" in lab.text() and any(k in lab.text() for k in ("覆盖", "混音", "自动"))]
    finally:
        page.close()
    assert notes, "音效转发页签里找不到讲「转发」和「模式」关系的那句话（分母为空）"
    for text in notes:
        assert "建议" not in text and "回声" not in text, (
            f"还在叫用户去换一个对转发不起作用的模式：{text!r}")
    assert any("覆盖" in t and "无关" in t for t in notes), (
        f"没说清转发总是按「覆盖」播、与模式无关：{notes}")
