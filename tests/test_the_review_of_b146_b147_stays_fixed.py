# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 146、147 外审 S4 反复报、核实成立的几条（改起来不动结构，别的判据钉不到）。

⚠ 没改的和查实是假的写在两批的档案里，这里只钉改过的。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from config import config
from theme_manager import get_theme_manager
from widgets.weapon_row_widget import WeaponRowWidget


def _cell(name="AK-47"):
    return WeaponRowWidget(name, f"weapon_{name}", ["甲", "乙"], name_is_action=False)


def test_a_cell_without_a_style_steps_back_but_still_answers(qapp):
    """「不启用却亮着试听」跨页报了约 20 条。⚠ 退后不等于禁用：点了照样有回应。"""
    cell = _cell()
    try:
        button = cell.test_button
        assert button.property("fp_idle") == "true"
        assert button.isEnabled()
        answered = []
        cell.testClicked.connect(lambda: answered.append(True))
        button.click()
        assert answered, "没配风格的格子点试听没有回应"

        cell.set_cell_state("configured")
        assert not button.property("fp_idle"), "配上风格之后试听还是退后的"
        cell.set_cell_state("")
        assert button.property("fp_idle") == "true"
    finally:
        cell.deleteLater()


def test_the_selected_cell_stands_out_from_the_configured_ones(qapp):
    """配了的格子边框都是紫的，选中的再是紫的，就看不出微调栏调的是哪一把。"""
    previous = qapp.styleSheet()
    qapp.setStyleSheet(get_theme_manager().themes["dark"].generate_stylesheet())
    host = QWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen, True)
    layout = QVBoxLayout(host)
    configured, selected = _cell("甲"), _cell("乙")
    for cell in (configured, selected):
        cell.set_cell_state("configured")
        layout.addWidget(cell)
    selected.set_selected(True)
    host.resize(400, 120)
    host.show()
    qapp.processEvents()
    try:
        def border(cell):
            image = cell.grab().toImage()
            return image.pixelColor(image.width() // 2, 0).name()

        assert border(configured) != border(selected)
    finally:
        host.close()
        host.deleteLater()
        qapp.setStyleSheet(previous)


@pytest.fixture
def special_page(qapp, monkeypatch):
    from pages.special_sound_page import SpecialSoundPage

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    page = SpecialSoundPage()
    yield page
    page.deleteLater()
    qapp.processEvents()


def test_an_empty_special_cell_does_not_say_disabled(special_page):
    """这一页上面有「启用」开关：勾上之后格子还写「不启用」，读着像没勾上（8 条以上，多为高）。"""
    from core.audio.special_events import events_in_group

    must_see = 0
    for event in events_in_group("round"):
        combo = special_page.round_combos[event.key]
        assert combo.itemText(0) == "未选风格"
        assert combo.itemData(0) == "0", "只改显示的字，配置里存的值不能变"
        must_see += 1
    assert must_see >= 3


def test_a_style_folder_cannot_take_the_name_of_the_placeholder():
    from core.audio.style_creator import validate_style_name

    assert validate_style_name("未选风格"), "风格叫这个名字，那一格就分不清是没选还是选了它"


def test_the_special_page_names_its_button_like_the_other_pages(special_page):
    """「打开当前资源」没人懂，别的音效页都叫「打开音频资源」。"""
    from widgets.page_action_bar import PageActionBar

    bars = special_page.findChildren(PageActionBar)
    texts = {bar.primary_btn.text() for bar in bars}
    assert "打开音频资源" in texts, texts
    assert "打开当前资源" not in texts, texts


def test_the_c4_note_does_not_contradict_its_three_combos(special_page):
    """三个下拉配一句「共用同一个目录」，读着矛盾（5 条高）。"""
    notes = [label.text() for label in special_page.findChildren(QLabel) if "拆除和爆炸靠文件名" in label.text()]
    assert len(notes) == 1, notes
    assert "每个事件各选一个风格" in notes[0]
    assert "共用" not in notes[0]


def test_the_gun_page_does_not_contradict_its_header(qapp, monkeypatch):
    """页头说改动自动保存，批量行说「不点按钮不会写入」，两句打架（3 条高）。"""
    from pages.gun_sound_page import GunSoundPage

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    page = GunSoundPage()
    try:
        page.apply_all_combo.setEnabled(True)
        page.apply_all_combo.setCurrentIndex(0)
        page._sync_apply_all_hint()
        text = page.apply_all_hint.text()
        assert "不会写入" not in text, text
        assert page.apply_all_btn.text() in text, text
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_mode_button_does_not_read_like_a_paid_version(qapp, monkeypatch):
    """「完整」被读成「付费解锁完整版」（跨页 8 条）。"""
    import gui_widget

    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    was_compact = config.compact_mode
    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    qapp.processEvents()
    try:
        assert win._sidebar_mode_btn.text() == "紧凑界面"
        for _ in range(2):
            win._toggle_compact_mode()
            qapp.processEvents()
            assert win._mode_toggle_btn.text().endswith("界面"), win._mode_toggle_btn.text()
    finally:
        config.compact_mode = was_compact
        win._force_exit = True
        win.close()
        win.deleteLater()
        qapp.processEvents()
        config.save_config_now()
