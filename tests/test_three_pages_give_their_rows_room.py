# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 157：准心滑杆行距、HUD 下拉去编号、音乐空列表压矮。

批 155 codex 设计建议里留下的三条：
- 准心五根滑杆行距 6，名字贴着滑杆；拖到 100% 时数值变宽、滑杆被挤短一截。
- HUD 页一屏十个「默认 (0)」：括号里是 `cl_hud_color` 的编号，挪进 tooltip。
- 音乐页空列表也占 240px，把下面两张卡顶出第一屏。

⚠ 门槛都写死数，不读被测常量（批 155 回退验证逮过一次）。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGridLayout

from config import config


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_the_crosshair_sliders_have_room_between_rows(qapp, monkeypatch):
    import pages.crosshair_page as module

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_animation", "none")
    page = module.CrosshairPage()
    grid = next(g for g in page.findChildren(QGridLayout)
                if g.indexOf(page.size_slider) >= 0)
    assert grid.verticalSpacing() >= 12, f"滑杆行距又回到 {grid.verticalSpacing()}"
    assert grid.horizontalSpacing() >= 12
    label = page.alpha_value_label
    assert label.minimumWidth() >= label.fontMetrics().horizontalAdvance("100%"), \
        "数值列没按「100%」留宽：拖到头时滑杆被挤短"
    page.deleteLater()
    qapp.processEvents()


def test_the_hud_colour_names_carry_no_code_numbers(qapp, monkeypatch):
    import pages.hud_color_page as module

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    page = module.HudColorPage()
    combo = page._create_color_combo()
    names = [combo.itemText(i) for i in range(combo.count())]
    assert names and not any("(" in name for name in names), f"色名里又带了编号：{names}"
    tips = [combo.itemData(i, Qt.ToolTipRole) for i in range(combo.count())]
    assert all(tip and tip.startswith("cl_hud_color ") for tip in tips), \
        "编号挪进 tooltip，不能直接丢掉（手写 cfg 的人要它）"
    page.deleteLater()
    qapp.processEvents()


class _Player:
    current_playlist_name = "默认列表"
    current_index = -1
    is_playing = False
    is_paused = False
    on_playlist_update = None
    on_playlist_change = None

    def __init__(self, tracks):
        self.tracks = tracks

    def get_playlist(self):
        return list(self.tracks)

    def get_all_playlists(self):
        return ["默认列表"]

    def switch_playlist(self, name):
        return True

    def set_play_mode(self, mode):
        pass


def test_an_empty_playlist_does_not_take_a_whole_screen(qapp, monkeypatch):
    import pages.music_page as module

    player = _Player([])
    monkeypatch.setattr(module, "get_music_player", lambda: player)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    page = module.MusicPage()
    page.refresh_playlist_display()
    listing = page.playlist_widget
    assert listing.maximumHeight() <= 140, f"空列表还占 {listing.maximumHeight()}px"
    hint = listing.item(0)
    assert hint.sizeHint().height() >= 100, "提示没撑满列表，两行字挤在顶上"

    player.tracks = [{"title": f"第 {i} 首", "duration": 60} for i in range(6)]
    page.refresh_playlist_display()
    assert listing.minimumHeight() >= 180 and listing.maximumHeight() >= 300, \
        "有歌之后列表没恢复原来的高度"
    page.deleteLater()
    qapp.processEvents()
