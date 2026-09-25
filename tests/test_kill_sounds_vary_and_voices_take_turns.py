# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 119（对标补课）：击杀音效。

- 一档只能一个文件：一局响几十次的击杀音听腻了只能换整套（对标对象的 issue #17 就是这个诉求）；
- 语音不过策略层、不进时间线 ⇒ 新一杀顶不掉上一杀的语音，回放页上也看不见；
- 淡入淡出那条路（回合音效唯一走的路）直接取配置音量，**不含响度归一**；
- 助攻：GSI 早就订阅了 match_stats，数据在手边没人读。
"""
from __future__ import annotations

from collections import OrderedDict
from threading import Lock

import pygame
import pytest

from core.audio.audio_manager import AudioManager
from core.audio.special_events import get_event


class _FakeSound:
    def __init__(self, path):
        self.path = str(path)
        self.volume = None

    def set_volume(self, v):
        self.volume = v

    def stop(self):
        pass


class _SilentLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


def _manager(tmp_path, monkeypatch):
    """同 test_gun_sound_variants_rotate：不跑 __init__（会占音频设备），只搭加载路径要的字段。"""
    monkeypatch.setattr(pygame.mixer, "Sound", _FakeSound)
    am = AudioManager.__new__(AudioManager)
    am.logger = _SilentLogger()
    am._lock = Lock()
    am._sounds = {}
    am._access_order = OrderedDict()
    am._max_sounds = 50
    am._gun_sound_variants = {}
    am._last_gun_sound_variant = {}
    am._on_loaded_callbacks = []
    am._mixer_ready = True
    am._volume = 0.7
    am._styles_scanned = True
    am.kill_sounds_dir = str(tmp_path / "kill_sounds")
    am._apply_loudness_normalization = lambda sound: (sound, 1.0)
    return am


def _files(d, *stems):
    d.mkdir(parents=True, exist_ok=True)
    for s in stems:
        (d / f"{s}.wav").write_bytes(b"RIFF")


# ──────────────────────────── 一档多条 ────────────────────────────

def test_numbered_files_become_variants_of_their_level(tmp_path, monkeypatch):
    am = _manager(tmp_path, monkeypatch)
    _files(tmp_path / "kill_sounds" / "嘻哈", "3", "3-2", "3-3", "3-headshot", "3-headshot-2", "4", "13")
    assert am.load_kill_sound("嘻哈", is_headshot=True, number=3)
    variants = am._variant_table()
    assert variants.get("kill-嘻哈-3") == ("kill-嘻哈-3", "kill-嘻哈-3#1", "kill-嘻哈-3#2"), variants
    assert variants.get("kill-嘻哈-3-headshot") == ("kill-嘻哈-3-headshot", "kill-嘻哈-3-headshot#1"), (
        "爆头档的第二条没被认出来")   # 上面那条精确相等也顺带挡住了「13 被当成 3 的第 N 条」


def test_a_level_with_one_file_has_no_variants(tmp_path, monkeypatch):
    am = _manager(tmp_path, monkeypatch)
    _files(tmp_path / "kill_sounds" / "单条", "1", "2")
    am.load_kill_sound("单条", number=1)
    assert "kill-单条-1" not in am._variant_table(), "只有一条也登记了变体（会让随机逻辑白跑）"


def test_playing_a_level_rotates_through_its_files(tmp_path, monkeypatch):
    am = _manager(tmp_path, monkeypatch)
    _files(tmp_path / "kill_sounds" / "嘻哈", "3", "3-2", "3-3")
    am.load_kill_sound("嘻哈", number=3)
    picks = [am._pick_gun_sound_variant("kill-嘻哈-3") for _ in range(30)]
    assert len(set(picks)) == 3, f"三条里没轮到全部：{set(picks)}"
    assert all(a != b for a, b in zip(picks, picks[1:])), "连着两次播了同一条"


# ──────────────────────────── 语音进策略层 ────────────────────────────

class _Channel:
    def __init__(self):
        self.played = []
        self.busy = False

    def play(self, sound):
        self.played.append(sound)
        self.busy = True

    def get_busy(self):
        return self.busy

    def stop(self):
        self.busy = False


def test_a_new_kill_voice_goes_through_the_policy_and_the_timeline(tmp_path, monkeypatch):
    from config import config
    am = _manager(tmp_path, monkeypatch)
    am._playback_lock = Lock()
    am._active_channel_requests = {}
    am.kill_voice_channel = _Channel()
    timeline = []
    am._record_timeline_event = lambda **kw: timeline.append(kw)
    monkeypatch.setattr(config, "sfx_forwarding_enabled", False, raising=False)
    admitted = []
    real_admit = AudioManager._admit_playback

    def spy(self, key, ch, channel_type, **kw):
        admitted.append((key, channel_type, kw.get("event_type")))
        return real_admit(self, key, ch, channel_type, **kw)

    monkeypatch.setattr(AudioManager, "_admit_playback", spy)
    _files(tmp_path / "kill_voices" / "播报", "1", "2")
    am.kill_voices_dir = str(tmp_path / "kill_voices")
    am.load_sound("voice-1", str(tmp_path / "kill_voices" / "播报" / "1.wav"), "kill_voice")
    am.load_sound("voice-2", str(tmp_path / "kill_voices" / "播报" / "2.wav"), "kill_voice")
    am.play_voice("voice-1")
    am.play_voice("voice-2")
    assert [a[1] for a in admitted] == ["kill_voice", "kill_voice"], "语音没过策略层"
    assert len(am.kill_voice_channel.played) == 2, "第二杀的语音被第一杀的挡住了（应当顶掉）"
    assert [e["action"] for e in timeline if e.get("action") == "play"] == ["play", "play"], (
        f"回放页看不见语音：{timeline}")


def test_the_fade_path_applies_loudness_normalization():
    """回合音效唯一走淡入淡出；那条路以前直接取配置音量，不含归一增益。"""
    import inspect
    src = inspect.getsource(AudioManager.play_sound_with_fade)
    assert "self._resolve_play_volume(config, channel_type, info)" in src, "淡入淡出又绕开了最终音量那一处"


# ──────────────────── 顺带：提示条上的按钮被压成 26px（RN-697） ────────────────────

@pytest.fixture
def main_window(qapp, monkeypatch):
    """真主窗口（同 test_master_switch_row）。⚠⚠ 必须是它：单独建页面、把样式挂在 app 或临时父控件上，
    写死的 26 会被样式表的 min-height 撑回 36 —— 缺陷复现不出来（批 119 回退验证当场逮到这条判据假绿）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    import _audit_neutralize as neutral
    from config import config

    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    neutral.apply(config)
    config.compact_mode = False
    monkeypatch.setattr("config.config.save_config", lambda: None, raising=False)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)          # §3：不许弹真窗口
    win.show()
    win.resize(1280, 800)
    qapp.processEvents()
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def test_notice_buttons_are_tall_enough_for_their_text_and_do_not_stretch(main_window, qapp):
    """`secondaryButton` 在样式表里自带 min-height≈36，提示条 / 进度条把它 `setFixedHeight(26)`
    ⇒ 字上下被切成碎片（外审 S3 6/6「按钮文字倒置 / 残缺」），还被横向撑满一整条。
    提示条默认隐藏 ⇒ 三道审计（都在默认状态下量）结构上看不见。
    量的是真主窗口里的两处宿主：击杀图标页自己的提示条、导入资源页用的全站共用提示条。"""
    from PySide6.QtWidgets import QPushButton

    holders = []
    for pid in ("kill_icon", "audio_import_wizard"):
        main_window.ensure_page_loaded(pid)
        main_window.show_page(pid, animated=False, force=True)
        qapp.processEvents()
        page = main_window.pages[pid]
        if pid == "kill_icon":
            page._show_notice("✓ 甲\n✗ 坏.zip")
            holders.append(page.notice_frame)
        else:
            page.notice_bar.show_message("已导入 3 个文件", undo_callback=lambda: None)
            holders.append(page.notice_bar)
        for _ in range(3):
            qapp.processEvents()
        checked = 0
        for b in holders[-1].findChildren(QPushButton):
            if not b.isVisible():
                continue
            checked += 1
            hint = b.sizeHint()
            assert b.height() >= hint.height(), f"{pid}「{b.text()}」高 {b.height()} < 需要 {hint.height()}：字会被切"
            assert b.width() <= hint.width() * 1.5, f"{pid}「{b.text()}」被撑到 {b.width()}（只要 {hint.width()}）"
        assert checked >= 1, f"{pid} 一颗可见按钮都没量到 —— 分母不对"


# ──────────────────────────── 助攻 ────────────────────────────

ME = "76561190000000001"


def _frame(assists, round_no=3):
    return {"provider": {"steamid": ME}, "map": {"round": round_no, "phase": "live"},
            "round": {"phase": "live"},
            "player": {"steamid": ME, "activity": "playing",
                       "state": {"health": 100}, "match_stats": {"assists": assists, "mvps": 0}}}


@pytest.fixture()
def special(monkeypatch):
    import gsi_handler_special
    from config import config
    for key, value in (("round_sound_enabled", True), ("spectator_mode_mute", False),
                       ("player_steamid", ME), ("grenade_sound_enabled", False), ("c4_sound_enabled", False),
                       ("health_warning_enabled", False), ("round_assist_style", "嘻哈")):
        monkeypatch.setattr(config, key, value, raising=False)
    h = gsi_handler_special.GSIHandlerSpecial()
    played = []
    monkeypatch.setattr(h, "_play_event", lambda group, key: played.append((group, key)) or True)
    monkeypatch.setattr(h, "_process_round_sounds", lambda data: None)
    return h, played


def test_an_assist_plays_once_and_the_first_frame_only_seeds(special):
    h, played = special
    h.process_data(_frame(4))
    assert played == [], "中途启动时读到的 4 次助攻被当成一次新助攻"
    h.process_data(_frame(4))
    h.process_data(_frame(5))
    assert played == [("round", "assist")]


def test_assists_counted_while_the_switch_was_off_do_not_fire_later(special, monkeypatch):
    from config import config
    h, played = special
    h.process_data(_frame(1))                       # 开着：播种 1
    monkeypatch.setattr(config, "round_sound_enabled", False, raising=False)
    h.process_data(_frame(3))                       # 关着：计数照涨
    monkeypatch.setattr(config, "round_sound_enabled", True, raising=False)
    h.process_data(_frame(3))
    assert played == [], "关着时攒下的助攻，一打开开关就补播了"


def test_assist_is_an_event_in_the_one_table_and_off_by_default():
    event = get_event("round", "assist")
    assert event is not None and event.default_style == "0" and not event.fade
