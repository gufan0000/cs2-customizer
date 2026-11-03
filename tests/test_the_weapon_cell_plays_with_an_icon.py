# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 156：武器格的试听是播放图标，不是「试听」二字。

批 155 外审：击杀音效页一屏「试听」31 次、枪声页 34 次，是剩下最显眼的重复文字。
改成和风格卡同一个播放图标；字留在 tooltip 和读屏名字里（置灰逻辑也按读屏名字认它）。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _icon_color(button):
    """图标中心那一圈最亮的像素：没配是 muted，配了是 accent。"""
    image = button.icon().pixmap(18, 18).toImage()
    best = max((image.pixelColor(x, y) for x in range(18) for y in range(18)),
               key=lambda c: (c.alpha(), c.lightness()))
    return best.name()


def test_the_cell_shows_an_icon_and_keeps_the_word_for_tips_and_readers(qapp):
    from widgets.weapon_row_widget import STATE_CONFIGURED, WeaponRowWidget

    cell = WeaponRowWidget("AK-47", "ak47", ["不启用", "冰河"])
    button = cell.test_button
    assert button.text() == "", f"格子上又写了字：{button.text()!r}"
    assert not button.icon().isNull()
    assert button.toolTip() == "试听"
    assert button.accessibleName() == "试听 AK-47"

    idle = _icon_color(button)
    cell.set_cell_state(STATE_CONFIGURED)
    lit = _icon_color(button)
    assert idle != lit, "配上风格后图标没亮起来"
    cell.set_cell_state("")
    assert _icon_color(button) == idle


def test_the_dimming_still_finds_the_icon_button(qapp):
    """置灰逻辑原来按按钮上的字认「试听」：字没了它就漏掉这颗，空库时又变成可点却没反应（RN-179）。"""
    from PySide6.QtWidgets import QWidget, QVBoxLayout

    from widgets.community_library import dim_controls_with_nothing_to_pick
    from widgets.weapon_row_widget import WeaponRowWidget

    page = QWidget()
    QVBoxLayout(page).addWidget(WeaponRowWidget("AK-47", "ak47", ["不启用"], parent=page))
    cell = page.findChild(WeaponRowWidget)
    assert dim_controls_with_nothing_to_pick(page, reason="还没有风格") == 2
    assert not cell.test_button.isEnabled()
