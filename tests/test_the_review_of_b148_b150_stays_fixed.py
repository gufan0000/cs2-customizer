# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 148~150 外审报过、核实成立的几条（批 151）。没改的和假的写在档案 B151 里。"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel

from config import config


@pytest.fixture
def win(qapp, monkeypatch):
    import gui_widget

    window = gui_widget.MainWindow(auto_background_preload=False)
    yield window
    window.deleteLater()


def _page(win, qapp, page_id):
    win.ensure_page_loaded(page_id)
    win.show_page(page_id, animated=False, force=True)
    qapp.processEvents()
    return win.pages[page_id]


def _label_texts(page):
    return [label.text() for label in page.findChildren(QLabel)]


def test_the_import_dialog_title_uses_the_title_style(qapp):
    """手写的粗体 QFont 被全局字号压回 13 px，八个字挤成一团。"""
    from dialogs.sprite_sheet_maker import SpriteSheetMaker

    dialog = SpriteSheetMaker()
    try:
        titles = [lb for lb in dialog.findChildren(QLabel) if lb.text() == "击杀图标高级导入"]
        assert titles
        assert titles[0].objectName() == "titleLabel"
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("switch_id,page_id", [
    ("death_sound", "death_sound"),
    ("dynamic_hud", "hud_color"),
    ("music", "music"),
    ("voice_output", "voice_output"),
])
def test_cards_and_sidebar_use_one_name(win, switch_id, page_id):
    card = win.feature_cards[switch_id]
    nav = win.nav_buttons[page_id].text().strip()
    assert card.name_label.property("fp_search_text") == nav


def test_the_utility_empty_state_says_where_the_button_is(win, qapp):
    """这个页签没有那颗按钮：要说去哪儿找。"""
    page = _page(win, qapp, "utility")
    hits = [t for t in _label_texts(page) if "打开道具文件夹" in t]
    assert hits
    assert all("第一个页签" in t for t in hits), hits


def test_flash_image_controls_follow_the_style(win, qapp):
    page = _page(win, qapp, "flash")
    combo = page.image_style_combo
    combo.addItem("测试风格", "probe_style")
    saved = config.flash_image_style
    try:
        combo.setCurrentIndex(combo.findData("none"))
        page._sync_image_controls()
        assert not page.image_display_card.isEnabled()
        assert not page.image_rotation_combo.isEnabled()
        combo.setCurrentIndex(combo.findData("probe_style"))
        assert page.image_display_card.isEnabled()
        assert page.image_rotation_combo.isEnabled()
    finally:
        combo.setCurrentIndex(combo.findData("none"))
        combo.removeItem(combo.findData("probe_style"))
        config.flash_image_style = saved


def test_a_missing_gsi_file_says_where_to_fix_it():
    from core.audio.audio_resource_health import format_audio_resource_health

    text = format_audio_resource_health({
        "gsi_cfg": {"status": "missing", "detail": "GSI 配置文件不存在: x"},
        "summary": {},
    })
    assert "高级设置" in text, text


@pytest.mark.parametrize("page_id,words", [
    ("voice_output", "开麦键要和游戏里的语音键一样"),
    ("viewmodel", "X 左右，Y 前后，Z 上下"),
    ("hud_color", "照常切枪"),
])
def test_the_missing_sentences_are_on_the_page(win, qapp, page_id, words):
    page = _page(win, qapp, page_id)
    assert any(words in t for t in _label_texts(page))
