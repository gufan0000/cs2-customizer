# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-650（批 98）：特殊音效页的空库引导按**当前页签**算，不按整页算。

用户真实配置：C4 / 血量各有一个 `default` 风格，投掷物六种全空。整页「任一有风格」⇒ 不空 ⇒
底栏写「打开当前资源」、没有社区引导；而用户站在「投掷物」页签上看到的是六种全部「不启用」、
测试置灰（外审 S4 两档 2/2：「可用风格 0 个却无获取指引」）。
flash 页早就是按页签（图片 / 音频）各一份引导，这里照它做。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config  # noqa: E402


def _make_page(monkeypatch, *, grenade, c4, health, round_):
    from core.audio.special_events import events_in_group, styles_attr
    import pages.special_sound_page as mod

    def _inject(self):
        self.audio_manager.grenade_sound_styles = {g: list(grenade) for g in self.GRENADE_TYPES}
        self.audio_manager.c4_sound_styles = list(c4)
        self.audio_manager.c4_defused_styles = list(c4)
        self.audio_manager.c4_exploded_styles = list(c4)
        self.audio_manager.health_warning_styles = list(health)
        for event in events_in_group("round"):
            setattr(self.audio_manager, styles_attr(event), list(round_))
        for event in events_in_group("c4"):
            setattr(self.audio_manager, styles_attr(event), list(c4))

    monkeypatch.setattr(mod.SpecialSoundPage, "_refresh_special_sound_styles", _inject)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    return mod.SpecialSoundPage()


def _tab(page, name: str) -> None:
    names = [page.tab_widget.tabText(i) for i in range(page.tab_widget.count())]
    page.tab_widget.setCurrentIndex(names.index(name))


def _has_route() -> bool:
    """没有社区站的发行版（开源版）引导本来就不出现 —— `guide_empty_library` 先问 `has_category`。"""
    from widgets import community_library

    return bool(community_library.has_category("special_sound"))


def _guided(page) -> bool:
    callout = getattr(page, "empty_callout", None)
    return bool(callout is not None and not callout.frame.isHidden())


def test_the_real_shape_guides_on_the_grenade_tab_only(qapp, monkeypatch):
    """用户真实配置的形状：C4 / 血量有风格、投掷物全空、回合全空。"""
    if not _has_route():
        pytest.skip("这个发行版没有社区站，引导本来就不出现")
    page = _make_page(monkeypatch, grenade=[], c4=["default"], health=["default"], round_=[])
    try:
        qapp.processEvents()
        assert page._library_is_empty() is False, "夹具：整页应当不空（C4 / 血量有风格）"
        _tab(page, "投掷物")
        qapp.processEvents()
        assert page._current_tab_is_empty() is True
        assert _guided(page), "投掷物页签六种全空却没有社区引导（RN-650）"
        _tab(page, "C4")
        qapp.processEvents()
        assert page._current_tab_is_empty() is False
        assert not _guided(page), "C4 有风格还挂着引导 —— 引导没跟页签走"
        _tab(page, "回合")
        qapp.processEvents()
        assert _guided(page), "回合页签全空却没有引导"
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_a_page_with_everything_never_guides(qapp, monkeypatch):
    page = _make_page(monkeypatch, grenade=["a"], c4=["a"], health=["a"], round_=["a"])
    try:
        for name in ("投掷物", "C4", "血量警告", "回合"):
            _tab(page, name)
            qapp.processEvents()
            assert not _guided(page), f"{name} 有风格却挂着引导"
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_a_page_with_nothing_guides_everywhere(qapp, monkeypatch):
    """阳性对照：四类全空 ⇒ 哪个页签都引导（这是修前就对的那一半，不许退）。"""
    if not _has_route():
        pytest.skip("这个发行版没有社区站，引导本来就不出现")
    page = _make_page(monkeypatch, grenade=[], c4=[], health=[], round_=[])
    try:
        assert page._library_is_empty() is True
        for name in ("投掷物", "C4", "血量警告", "回合"):
            _tab(page, name)
            qapp.processEvents()
            assert _guided(page), f"{name} 全空却没有引导"
    finally:
        page.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("name", ["投掷物", "C4", "血量警告", "回合"])
def test_every_tab_has_a_family(name):
    """`_current_tab_is_empty` 的页签表必须覆盖四个页签 —— 少一个就退回整页口径，悄悄失效。"""
    import inspect
    import pages.special_sound_page as mod

    src = inspect.getsource(mod.SpecialSoundPage._current_tab_is_empty)
    assert f'"{name}":' in src, f"页签「{name}」不在 _current_tab_is_empty 的表里"
