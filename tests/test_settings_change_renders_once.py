# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-010：改一次设置，状态区只许渲染一遍。

**这条是补账的**。RN-010 在 M1 就已经"已结"（把 `_on_setting_changed` 末尾那次
多余的 `_sync_status_strip()` 删掉），但**当时只删了代码，没留判据**——
2026-08-18 的关档自查里，66 条已结项交叉核对回退验证，它是两条
「改了产品代码却没有任何东西钉住」之一。

⚠ 为什么"删掉的东西"也需要判据：这类重复调用是**顺手加回来的**。
`_sync_enabled_state()` 末尾自己会调 `_sync_status_strip()` 这件事，
从调用点上完全看不出来；下一个人在 `_on_setting_changed` 里想"改完刷新一下状态"
是再自然不过的念头，于是它就回潮了。**A 堆的清理不留判据，等于没清。**

判据量的是**行为**（真的调了几次），不是源码里出现几次 ——
后者会被"换个名字调"或"经由第三个函数调"绕过去。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config  # noqa: E402


@pytest.fixture()
def effects_page(qapp, monkeypatch):
    import pages.screen_effects_page as mod

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "screen_effects_enabled", True, raising=False)
    monkeypatch.setattr(config, "screen_edge_flash_enabled", True, raising=False)
    page = mod.ScreenEffectsPage(overlay_manager=None)
    qapp.processEvents()
    yield page
    page.deleteLater()
    qapp.processEvents()


def _count_strip_renders(page, qapp, call):
    """数一次用户操作引发了几次状态区渲染。"""
    calls = []
    original = page._sync_status_strip

    def counting():
        calls.append(1)
        return original()

    page._sync_status_strip = counting
    try:
        call()
        qapp.processEvents()
    finally:
        page._sync_status_strip = original
    return len(calls)


def test_toggling_a_setting_renders_the_status_strip_exactly_once(effects_page, qapp):
    page = effects_page
    box = page.enable_edge_flash_checkbox

    n = _count_strip_renders(page, qapp, lambda: box.setChecked(not box.isChecked()))

    assert n == 1, (
        f"改一次设置把状态区渲染了 {n} 遍。\n"
        "RN-010：`_sync_enabled_state()` 末尾自己就会调 `_sync_status_strip()`，\n"
        "`_on_setting_changed` 里不要再调一次——每多一次就是一遍徽章重绘 + 三处 tooltip 重设。")


def test_changing_the_preset_renders_the_status_strip_exactly_once(effects_page, qapp):
    """换个入口再量一次：同一条缺陷在三个信号上都接了 `_on_setting_changed`。"""
    page = effects_page
    combo = page.preset_combo
    if combo.count() < 2:
        pytest.skip("预设不足两项，换不了（宁可跳过也不假绿）")

    target = (combo.currentIndex() + 1) % combo.count()
    n = _count_strip_renders(page, qapp, lambda: combo.setCurrentIndex(target))

    assert n == 1, f"换预设把状态区渲染了 {n} 遍（应为 1）。"
