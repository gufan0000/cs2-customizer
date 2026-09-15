# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-641（批 97）：「还没有任何可用风格」这条横幅，分母必须和下拉框一致。

用户真实配置下同一屏：横幅写「还没有任何可用风格 —— 本软件不带素材」，
而「整套套用」里有「21冠军」可选、状态条写「已配置 · 13」。
实测根因：kill_sound / kill_voice 的风格有**两个来源** —— 全局池
（`audio_manager.kill_sound_styles`，下拉框读它）与每把枪自己的目录
（`weapon_kill_sound_styles`）。`_library_is_empty` 原来只数后者；
用户把素材放在全局池里（全局 5 / per-weapon 0），于是 39 把枪全有得选、横幅却说没有。

⭐ 一句「没有」和一排「有得选」在同一屏上，用户信哪个都错。
判据造两种世界：只有全局池（横幅不许出现）、两处都空（横幅必须出现）。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config  # noqa: E402


class _DummyAudioManager:
    """只够把页面建起来的替身。两个池子都由参数给。"""

    def __init__(self, pool, per_weapon):
        self.kill_sound_styles = list(pool)
        self.weapon_kill_sound_styles = dict(per_weapon)
        self.kill_voice_styles = list(pool)
        self.weapon_kill_voice_styles = dict(per_weapon)
        self.weapon_sounds_dir = "sounds/weapon"
        self.kill_sounds_dir = "sounds/common"
        self.weapon_voices_dir = "voices/weapon"
        self.kill_voices_dir = "voices/common"
        self.played = []

    def ensure_styles_scanned(self):
        return None

    def scan_kill_sound_styles(self):
        return self.kill_sound_styles

    def scan_weapon_kill_sound_styles(self):
        return self.weapon_kill_sound_styles

    def scan_kill_voice_styles(self):
        return self.kill_voice_styles

    def scan_weapon_kill_voice_styles(self):
        return self.weapon_kill_voice_styles

    def play_sound(self, key, channel_type=None):
        self.played.append(key)
        return False

    def load_sound(self, *a, **k):
        return True


_HEALTH_OK = {"ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0}


def _build(qapp, monkeypatch, page_id: str, pool, per_weapon):
    if page_id == "kill_sound":
        import pages.kill_sound_page as mod
        cls, cfg_key, enabled_key = mod.KillSoundPage, "weapon_kill_sounds", "kill_sound_enabled"
    else:
        import pages.kill_voice_page as mod
        cls, cfg_key, enabled_key = mod.KillVoicePage, "weapon_kill_voices", "kill_voice_enabled"
    monkeypatch.setattr(mod, "get_runtime_audio_manager",
                        lambda: _DummyAudioManager(pool, per_weapon))
    monkeypatch.setattr(mod, "collect_category_health", lambda _roots: dict(_HEALTH_OK))
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, enabled_key, True, raising=False)
    monkeypatch.setattr(config, cfg_key, {}, raising=False)
    page = cls()
    qapp.processEvents()
    return page


def _has_route(page) -> bool:
    """没有社区站的发行版（开源版）横幅本来就不出现 —— `guide_empty_library` 先问 `has_category`。"""
    from widgets import community_library

    return bool(community_library.has_category(page.COMMUNITY_CATEGORY_KEY))


def _banner_is_up(page) -> bool:
    callout = getattr(page, "empty_callout", None)
    assert callout is not None, "这一页没有空库横幅控件 —— 判据锚点失效（RN-180）"
    return not callout.frame.isHidden()


@pytest.mark.parametrize("page_id", ["kill_sound", "kill_voice"])
def test_a_global_style_is_a_style(qapp, monkeypatch, page_id):
    """⭐ 主判据：素材只在全局池、每把枪自己的目录全空 ⇒ 下拉框有得选 ⇒ 横幅不许出现。

    这正是用户真实配置的形状（全局 5 / per-weapon 0）。
    """
    page = _build(qapp, monkeypatch, page_id, pool=["21冠军"], per_weapon={})
    try:
        weapons = list(page._get_all_weapons())
        assert weapons, "分母为空 —— 这一页一把枪都没有，判据在空集上恒真"
        pickable = [w for w in weapons
                    if any(o != page.DISABLED_STYLE_TEXT for o in page._style_options_for(w))]
        assert len(pickable) == len(weapons), "夹具没造出「全局池有风格」的世界"
        assert page._library_is_empty() is False, (
            "下拉框每把枪都有「21冠军」可选，`_library_is_empty` 却说空 —— "
            "横幅和下拉框用了两个分母（RN-641）")
        assert not _banner_is_up(page), "横幅还在：「还没有任何可用风格」与有得选的下拉框同屏"
    finally:
        page.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("page_id", ["kill_sound", "kill_voice"])
def test_a_per_weapon_style_still_counts(qapp, monkeypatch, page_id):
    """反向不许退：只有某一把枪自己的目录有风格，也不算空（这是修前就对的那一半）。"""
    page = _build(qapp, monkeypatch, page_id, pool=[], per_weapon={"weapon_ak47": ["ak-only"]})
    try:
        assert page._library_is_empty() is False
        assert not _banner_is_up(page)
    finally:
        page.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("page_id", ["kill_sound", "kill_voice"])
def test_truly_empty_still_shows_the_banner(qapp, monkeypatch, page_id):
    """阳性对照：两处都空 ⇒ 横幅必须出现。没有这条，上面两条可能绿在「横幅永远不出现」上。"""
    page = _build(qapp, monkeypatch, page_id, pool=[], per_weapon={})
    try:
        assert page._library_is_empty() is True
        if not _has_route(page):
            pytest.skip("这个发行版没有社区站，空库横幅本来就不出现")
        assert _banner_is_up(page), "真空库时横幅没出现 —— 修 RN-641 把空态一起修没了"
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_base_counts_options_not_directories():
    """文本守卫：`_library_is_empty` 的分母必须是 `_style_options_for`（下拉框的分母），
    不许退回只数 `_weapon_styles`（每把枪自己的目录）。"""
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "pages" / "sound_page_base.py"
           ).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_library_is_empty")
    called = {n.func.attr for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "_style_options_for" in called, (
        f"`_library_is_empty` 调的是 {sorted(called)} —— 分母必须是下拉框那一个（RN-641）")
