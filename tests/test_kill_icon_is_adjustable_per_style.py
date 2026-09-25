# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 118（对标补课）：击杀图标可调。

- 14 个 kill_icon_* 键里只有风格名是按风格的 ⇒ 换一套素材就得重调位置，换回去再调一遍；
- 透明度 / 亮度都不可调，素材太亮太实会挡视线；
- 风格条就是 `os.listdir` 的顺序，装十几套后常用的可能排最后，也藏不掉；
- 调位置时「播完就没了，得再点一次」。
"""
from __future__ import annotations

import pytest

from config import config
from core.kill_icon_prefs import can_hide, layout_of, ordered_styles, remember_recent, with_layout


# ──────────────────────────── 纯逻辑 ────────────────────────────

def test_recent_styles_come_first_and_the_rest_are_sorted():
    styles = ["丙", "甲", "乙", "丁"]
    assert ordered_styles(styles) == sorted(styles), "没用过的应当按名字稳定排序，不是 listdir 顺序"
    assert ordered_styles(styles, recent=["丁", "乙"]) == ["丁", "乙"] + sorted(["丙", "甲"])
    assert "乙" not in ordered_styles(styles, hidden=["乙"])
    assert "乙" in ordered_styles(styles, hidden=["乙"], keep="乙"), "正在用的那套被藏了也不许从条上消失"


def test_recent_list_is_deduplicated_and_bounded():
    r = []
    for s in "甲乙丙甲丁戊己庚辛壬":
        r = remember_recent(r, s)
    assert r[0] == "壬" and len(r) == 8 and len(set(r)) == 8


def test_you_cannot_hide_your_way_out_of_every_style():
    assert not can_hide(["甲", "乙"], [], "甲", current="甲"), "不许藏正在用的"
    assert can_hide(["甲", "乙"], [], "乙", current="甲")
    assert not can_hide(["甲", "乙"], ["甲"], "乙", current="丙"), "藏完一套都不剩了"


def test_a_style_without_a_layout_inherits_the_current_one():
    current = {"x": 30, "y": -10, "scale": 1.2}
    assert layout_of({}, "新", current) == current, "老用户调好的全局位置作为初值，不许归零"
    stored = with_layout({}, "旧", 5, 6, 0.8)
    assert layout_of(stored, "旧", current) == {"x": 5, "y": 6, "scale": 0.8}


def test_garbage_in_config_does_not_break_loading():
    from config import Config
    c = Config.__new__(Config)
    c._load_kill_icon_prefs({"kill_icon_opacity": "abc", "kill_icon_style_layouts": [1, 2],
                             "kill_icon_hidden_styles": "甲", "kill_icon_recent_styles": None})
    assert (c.kill_icon_opacity, c.kill_icon_style_layouts, c.kill_icon_hidden_styles,
            c.kill_icon_recent_styles) == (1.0, {}, [], [])
    c._load_kill_icon_prefs({"kill_icon_opacity": 0.05})
    assert c.kill_icon_opacity == 0.3, "不透明度没夹下限 —— 调到 0 就是图标没了"


def test_the_overlay_multiplies_the_fade_by_the_user_opacity(monkeypatch):
    import kill_icon_player
    monkeypatch.setattr(config, "kill_icon_opacity", 0.5, raising=False)
    assert kill_icon_player.with_user_opacity(1.0) == 0.5
    assert kill_icon_player.with_user_opacity(0.4) == pytest.approx(0.2)


# ──────────────────────────── 页面 ────────────────────────────

@pytest.fixture()
def page(monkeypatch):
    from PySide6.QtWidgets import QApplication

    import pages.kill_icon_page as page_module
    from resource_manager import ResourceManager

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "save_config", lambda *a, **k: None, raising=False)
    for key, value in (("kill_icon_style", "甲"), ("kill_icon_offset_x", 0), ("kill_icon_offset_y", 0),
                       ("kill_icon_scale", 1.0), ("kill_icon_opacity", 1.0), ("kill_icon_style_layouts", {}),
                       ("kill_icon_hidden_styles", []), ("kill_icon_recent_styles", [])):
        monkeypatch.setattr(config, key, value, raising=False)
    monkeypatch.setattr(ResourceManager, "list_kill_icon_styles", staticmethod(lambda: ["乙", "甲", "丙"]))
    p = page_module.KillIconPage()
    yield p
    p.deleteLater()


def test_switching_styles_brings_back_each_ones_own_position(page, monkeypatch):
    """⭐ 升级场景：老用户的 +50 是升级前调的（没有任何风格存过档，也没动过滑条）。
    换乙调到 −20，换回甲应当还是 +50，再换乙还是 −20。"""
    monkeypatch.setattr(config, "kill_icon_offset_x", 50, raising=False)
    page._on_style_selected("乙")
    assert config.kill_icon_offset_x == 50, "没记过的风格应当沿用当前位置，不是归零"
    page.x_slider.setValue(-20)
    page._on_style_selected("甲")
    assert config.kill_icon_offset_x == 50 and page.x_slider.value() == 50, "换回甲，位置要重调"
    page._on_style_selected("乙")
    assert config.kill_icon_offset_x == -20


def test_the_strip_order_puts_the_recent_one_first(page):
    assert page.available_icon_styles == sorted(["乙", "甲", "丙"]), "没用过时应按名字排，不是 listdir 顺序"
    page._on_style_selected("丙")
    page._scan_icon_styles()
    assert page.available_icon_styles[0] == "丙", page.available_icon_styles


def test_a_style_can_be_hidden_and_brought_back(page):
    current = page._current_style()
    assert not [t for t, _ in page._style_menu_actions(current) if "藏起" in t], "正在用的那套也能藏"
    other = next(s for s in page.available_icon_styles if s != current)
    hide = next(fn for t, fn in page._style_menu_actions(other) if "藏起" in t)
    hide()
    assert other not in page.available_icon_styles and other in config.kill_icon_hidden_styles
    show = next(fn for t, fn in page._style_menu_actions(current) if "显示已隐藏" in t)
    show()
    assert other in page.available_icon_styles and not config.kill_icon_hidden_styles


def test_the_opacity_slider_drives_the_preview(page):
    page.opacity_slider.setValue(40)
    assert config.kill_icon_opacity == pytest.approx(0.4)
    assert page.hero_preview._user_opacity == pytest.approx(0.4)


class _Player:
    def __init__(self):
        self.is_playing = False
        self.plays = 0

    def play_icon(self, level):
        self.plays += 1
        self.is_playing = True

    def preview_position_and_scale(self, *a):      # 真的这条也是走 play_icon（见 kill_icon_player）
        self.plays += 1
        self.is_playing = True

    def update_position_offset(self, *a):
        pass

    def update_scale(self, *a):
        pass


def test_adjusting_the_position_replays_only_when_idle_and_only_on_this_page(page, monkeypatch):
    """拖位置 / 大小 ⇒ 图标没在播就再弹一发（不加开关：这一页控件封顶 10 个，KI-7）。"""
    player = _Player()
    page.kill_icon_player = player
    monkeypatch.setattr(page, "isVisible", lambda: True)
    page.x_slider.setValue(10)
    assert page._replay_timer.isActive(), "拖了位置滑条却没约下一发试播"
    page._replay_tick()
    assert player.plays == 1
    page._replay_tick()
    assert player.plays == 1, "上一发还在播就又弹了一发"
    player.is_playing = False
    page._replay_tick()
    assert player.plays == 2
    player.is_playing = False
    monkeypatch.setattr(page, "isVisible", lambda: False)
    page._replay_tick()
    assert player.plays == 2, "离开这一页还在往游戏画面上弹"
