# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀反馈的三条通道（音效 / 语音 / 图标）必须各判各的。

**这是用户实战报回来的缺陷**（2026-08-18，死斗，日志在册）：
「有的时候击杀音效和图标什么都不播放，频率还挺高」。

查下来：112 次击杀里 8 次没有任何反馈，**8 次全是 `weapon_fiveseven`** ——
那把枪在他的配置里是「不启用」。而 `_emit_kill_feedback` 当时的写法是

    sound_key = self._get_weapon_kill_sound_key(...)
    if not sound_key:
        return False, ""          # ← 这把枪没配音效，直接走人
    played, used_key = self._play_kill_sound_with_retry(...)
    if played:                    # ← 图标和语音全被关在这个 if 里
        ...play_voice / play_images...

⇒ **击杀图标和击杀语音被「这把枪的击杀音效有没有成功播出」暗中门控。**
图标有自己的总开关、自己的素材、自己的设置页，和这把枪配没配音效毫无关系。

⭐ 这类缺陷最难查的地方在于**三个功能同时"坏"**，看起来像总线故障或者
GSI 断了，实际是耦合。用户的处理是把击杀图标总开关关掉 —— 一个正常人
面对这个现象会做的唯一动作，而它让缺陷看起来更像"图标功能是坏的"。

判据量的是**行为**：把音效那条路彻底堵死（武器不启用），图标和语音照样要出。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config  # noqa: E402


class _SpyImagePlayer:
    def __init__(self):
        self.calls = []

    def play_images(self, count, level, is_headshot=False):
        self.calls.append((count, level, is_headshot))


@pytest.fixture()
def handler(monkeypatch):
    import gsi_handler_kills as mod

    h = mod.GSIHandlerKills()
    h.image_player = _SpyImagePlayer()

    voices = []
    monkeypatch.setattr(mod.audio_manager, "play_voice",
                        lambda key: voices.append(key), raising=False)
    h._spy_voices = voices

    # 音效那条路彻底堵死：无论问什么武器都拿不到键（= 这把枪「不启用」）。
    monkeypatch.setattr(h, "_get_weapon_kill_sound_key",
                        lambda weapon, level, is_headshot=False: None)
    h.last_kill_weapon = "weapon_fiveseven"
    return h


def test_icon_still_fires_when_the_weapon_has_no_kill_sound(handler, monkeypatch):
    monkeypatch.setattr(config, "kill_icon_enabled", True, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)

    emitted, _key = handler._emit_kill_feedback(1, False, 0.0)

    assert handler.image_player.calls, (
        "这把枪没配击杀音效，击杀图标就不出了 —— 图标有自己的开关和素材，"
        "不该被音效配置门控（用户实战报回来的那条）。")
    assert emitted is True, "出了图标就算给过反馈，去重要认它"


def test_voice_still_fires_when_the_weapon_has_no_kill_sound(handler, monkeypatch):
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", True, raising=False)
    monkeypatch.setattr(handler, "_get_weapon_kill_voice_key",
                        lambda weapon, level, is_headshot=False: "voice-key")

    emitted, _key = handler._emit_kill_feedback(1, False, 0.0)

    assert handler._spy_voices == ["voice-key"], (
        "这把枪没配击杀音效，击杀语音就不播了 —— 语音是独立开关")
    assert emitted is True


def test_each_switch_still_turns_its_own_channel_off(handler, monkeypatch):
    """解耦不等于失控：各自的总开关必须仍然管用。"""
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)

    emitted, _key = handler._emit_kill_feedback(1, False, 0.0)

    assert not handler.image_player.calls, "图标开关关着还出图标"
    assert handler._spy_voices == [], "语音开关关着还播语音"
    assert emitted is False, "三条通道都没出东西，就不该算给过反馈"


def test_a_configured_sound_still_plays_and_is_reported(handler, monkeypatch):
    """正路不能改坏：配了风格就该播，且 `emitted` 为真。"""
    monkeypatch.setattr(handler, "_get_weapon_kill_sound_key",
                        lambda weapon, level, is_headshot=False: "kill-1")
    monkeypatch.setattr(handler, "_play_kill_sound_with_retry",
                        lambda key, level, is_headshot: (True, key))
    monkeypatch.setattr(config, "kill_icon_enabled", False, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", False, raising=False)

    emitted, used_key = handler._emit_kill_feedback(2, False, 123.0)

    assert emitted is True and used_key == "kill-1"
    assert handler.last_kill_sound_time == 123.0
