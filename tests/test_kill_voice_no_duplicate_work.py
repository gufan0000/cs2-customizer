# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-014 / RN-015：击杀语音页里两处「同一件事做两遍」，只许做一遍。

⚠ **这两条没法靠基线守住**：重复工作的终态和做一遍完全一样 ——
结构、指纹、两档像素逐字节等同，建页耗时的差别也淹在噪声里。
所以清掉之后必须补计次判据，否则它随时能悄悄长回来，而且长回来的那天
所有基线依然全绿。**A 堆的清理靠基线证「没改坏」，靠这类判据证「没长回来」。**

两条各自防的东西：
- `_on_styles_managed`：原先 `_refresh_style_catalog()` 之后又跟一句
  `load_settings()`，而前者已经逐把武器 `set_current_style(同一个表达式)` 过一遍。
  36 把武器白跑一趟、状态区白刷一次。
- `_refresh_status_badge`：`_configured_weapon_names()` 被算了两遍，
  两次之间没有任何东西改变它的输入。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config  # noqa: E402


class _DummyAudioManager:
    """只够把页面建起来的最小替身——不碰真实音频设备。"""

    def __init__(self):
        self.kill_voice_styles = ["styleV"]
        self.weapon_kill_voice_styles = {"weapon_ak47": ["ak-voice"]}
        self.weapon_voices_dir = "voices/weapon"
        self.kill_voices_dir = "voices/common"
        self._sounds = {}

    def ensure_styles_scanned(self):
        return None

    def scan_kill_voice_styles(self):
        return self.kill_voice_styles

    def scan_weapon_kill_voice_styles(self):
        return self.weapon_kill_voice_styles


@pytest.fixture()
def page(qapp, monkeypatch):
    import pages.kill_voice_page as mod

    monkeypatch.setattr(mod, "get_runtime_audio_manager", lambda: _DummyAudioManager())
    monkeypatch.setattr(
        mod, "collect_category_health",
        lambda _roots: {"ok": True, "missing": [], "empty": [], "invalid": [],
                        "issue_count": 0})
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_voice_enabled", True, raising=False)
    monkeypatch.setattr(config, "weapon_kill_voices",
                        {"weapon_glock": "styleV", "weapon_ak47": "ak-voice"},
                        raising=False)
    p = mod.KillVoicePage()
    yield p
    p.deleteLater()
    qapp.processEvents()


def test_managing_styles_touches_each_weapon_row_exactly_once(page, qapp):
    """风格管理完之后刷新一次就够，别把 36 把武器再走一遍。"""
    calls = []
    for weapon, row in page.weapon_rows.items():
        original = row.set_current_style

        def spy(value, _w=weapon, _orig=original):
            calls.append(_w)
            return _orig(value)

        row.set_current_style = spy

    page._on_styles_managed()
    qapp.processEvents()

    # 空转守卫：一次都没调到的话，下面那条"没有重复"是白绿的。
    assert calls, "刷新之后一把武器都没被更新，判据在空转"
    duplicated = sorted({w for w in calls if calls.count(w) > 1})
    assert not duplicated, (
        f"这些武器的下拉框被重复设置了：{duplicated}\n"
        "`_refresh_style_catalog()` 已经逐把设过一遍，后面别再跟一句 `load_settings()` —— "
        "终态一样，纯粹白跑一趟，而且所有基线都照样绿。")


def test_status_badge_computes_the_configured_names_once(page):
    """状态区刷新时，已配置武器名单只许算一次。"""
    hits = []
    original = page._configured_weapon_names

    def spy(*a, **kw):
        hits.append(1)
        return original(*a, **kw)

    page._configured_weapon_names = spy
    page._refresh_status_badge()

    assert hits, "一次都没算，判据在空转"
    assert len(hits) == 1, (
        f"`_configured_weapon_names()` 在一次状态刷新里被算了 {len(hits)} 遍。"
        "两次之间没有任何东西会改变它的输入，结果必然逐字相同。")
