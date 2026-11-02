# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 147：被击杀、枪声、特殊音效三页换成风格库和武器板（RN-739~741）。

全走真点击，一轮连做几次：缺陷常常在第二次操作才出现。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import config
from core.gun_sound_profiles import GUN_SOUND_PROFILES, SUPPORTED_GUN_SOUND_WEAPON_TYPES
from widgets import master_switch_effect as eff
from widgets.weapon_row_widget import STATE_CONFIGURED, STATE_STALE


def _settle(qapp, rounds=4):
    for _ in range(rounds):
        qapp.processEvents()


# ==================================================== 被击杀页


@pytest.fixture
def death(qapp, monkeypatch):
    import pages.death_sound_page as mod

    styles = ["甲", "乙", "丙"]
    plays = []
    monkeypatch.setattr(mod, "list_unique_audio_stems", lambda *_a, **_k: list(styles))
    monkeypatch.setattr(mod, "find_audio_by_stem", lambda *_a, **_k: "death.wav")
    monkeypatch.setattr(mod, "collect_category_health", lambda _roots: {
        "ok": True, "missing": [], "empty": [], "invalid": [], "issue_count": 0})
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "death_sound_style", "甲", raising=False)
    page = mod.DeathSoundPage()
    monkeypatch.setattr(page.audio_manager, "load_sound", lambda *_a, **_k: True)
    monkeypatch.setattr(page.audio_manager, "play_sound",
                        lambda key, **_k: plays.append(key) or True)
    page.styles_on_disk = styles
    page.plays = plays
    page.resize(1060, 700)
    page.show()
    _settle(qapp)
    yield page
    page.close()
    page.deleteLater()
    _settle(qapp)


def test_a_card_is_used_at_once_and_a_second_click_turns_it_off(death, qapp):
    library = death.style_library
    assert library.brush() == "甲"
    assert library.card("甲").meta_label.text() == "正在用"

    library.card("乙").click()
    _settle(qapp)
    assert config.death_sound_style == "乙"
    assert library.card("乙").isChecked() and not library.card("甲").isChecked()
    assert library.card("乙").meta_label.text() == "正在用"
    assert library.card("甲").meta_label.isHidden(), "没选中的卡不该留「正在用」"

    library.card("乙").click()
    _settle(qapp)
    assert config.death_sound_style == "0"
    assert not library.brush()
    assert not library.card("乙").isChecked()


def test_the_audition_on_a_card_changes_nothing(death, qapp):
    death.style_library.card("丙").play_button.click()
    _settle(qapp)
    assert death.plays == ["death-丙"]
    assert config.death_sound_style == "甲", "试听把配置改了"
    assert death.style_library.brush() == "甲"


def test_a_vanished_style_stays_in_the_config_and_comes_back(death, qapp):
    """风格没了不等于用户不要了：配置里留着名字，才说得出「原来选的 X 没了」，回来了也接得上。"""
    death.styles_on_disk[:] = ["乙", "丙"]
    death._refresh_style_catalog()
    _settle(qapp)
    assert config.death_sound_style == "甲", "刷新列表把用户的选择抹掉了"
    assert not death.style_library.brush()
    text = death.selection_state_label.text()
    assert "甲" in text and "重新选" in text, text
    assert death.selection_state_label.isVisible()

    death.styles_on_disk[:] = ["甲", "乙", "丙"]
    death._refresh_style_catalog()
    _settle(qapp)
    assert death.style_library.brush() == "甲", "风格回来了，卡片没接上"
    assert not death.selection_state_label.isVisible()


def test_a_new_style_is_used_right_away(death, qapp):
    death.styles_on_disk.append("新")
    death._on_style_created("新", "")
    _settle(qapp)
    assert config.death_sound_style == "新"
    assert death.style_library.card("新").isChecked()


def test_an_empty_library_shows_only_the_way_forward(qapp, monkeypatch):
    import pages.death_sound_page as mod

    monkeypatch.setattr(mod, "list_unique_audio_stems", lambda *_a, **_k: [])
    monkeypatch.setattr(config, "death_sound_style", "0", raising=False)
    page = mod.DeathSoundPage()
    page.resize(1060, 700)
    page.show()
    _settle(qapp)
    try:
        if not page.empty_callout.frame.isVisible():
            pytest.skip("这个发行版没有社区站")
        assert not page.style_library.isVisible()
        assert not page.library_hint.isVisible()
    finally:
        page.close()
        page.deleteLater()


# ==================================================== 枪声页


@pytest.fixture
def gun(qapp, monkeypatch):
    import pages.gun_sound_page as mod

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "gun_sound_enabled", True, raising=False)
    for gun_type in SUPPORTED_GUN_SOUND_WEAPON_TYPES:
        monkeypatch.setattr(config, f"{gun_type}_style", "0", raising=False)
    monkeypatch.setattr(config, "ak47_style", "甲", raising=False)
    monkeypatch.setattr(config, "awp_style", "已删除", raising=False)
    monkeypatch.setattr(config, "ak47_duck_ratio", 0.2, raising=False)
    monkeypatch.setattr(config, "awp_duck_ratio", 0.5, raising=False)
    monkeypatch.setattr(config, "ak47_mute_duration", 0.3, raising=False)
    monkeypatch.setattr(config, "awp_mute_duration", 0.6, raising=False)

    def scan(self):
        self.weapon_styles = {"ak47": ["甲", "乙"], "m4a1": ["甲"]}
        self.style_sample_counts = {}
        self.unknown_weapon_dirs = []

    monkeypatch.setattr(mod.GunSoundPage, "_scan_gun_sounds", scan)
    page = mod.GunSoundPage()
    page.resize(1060, 700)
    page.show()
    _settle(qapp)
    yield page
    page.close()
    page.deleteLater()
    _settle(qapp)


def test_every_gun_sits_on_one_board_without_tabs(gun):
    assert not gun.findChildren(QTabWidget), "页签又回来了"
    assert set(gun.weapon_rows) == set(SUPPORTED_GUN_SOUND_WEAPON_TYPES)
    assert {cell.weapon_key for cell in gun.weapon_board.cells()} == set(SUPPORTED_GUN_SOUND_WEAPON_TYPES)
    assert gun.weapon_board.columns() >= 3, "1060 宽应当排得下至少三列"


def test_clicking_a_name_moves_the_strip_and_writes_nothing(gun, qapp, monkeypatch):
    assert gun.tuning_weapon == "ak47"
    assert gun.duck_slider.value() == 20
    # ⚠ 光比配置的值量不到：滑条摆到这把枪的值上再写回去，值是一样的。要数写了几次。
    saves = []
    monkeypatch.setattr(config, "save_config", lambda: saves.append(1), raising=False)

    gun.weapon_rows["awp"].name_button.click()
    _settle(qapp)
    assert not saves, "换枪只是把滑条摆过去，不该写配置"
    assert gun.tuning_weapon == "awp"
    assert gun.tuning_name_label.text() == GUN_SOUND_PROFILES["awp"].display_name
    assert gun.duck_slider.value() == 50 and gun.duck_label.text() == "50%"
    assert gun.duration_slider.value() == 60 and gun.duration_label.text() == "0.60秒"
    assert gun.weapon_rows["awp"].property("fp_selected") == "true"
    assert gun.weapon_rows["ak47"].property("fp_selected") in (None, ""), "上一把还标着选中"
    # 换枪只是把滑条摆过去：不许把上一把的值写给这一把，也不许写回配置
    assert config.ak47_duck_ratio == pytest.approx(0.2)
    assert config.awp_duck_ratio == pytest.approx(0.5)
    assert config.ak47_mute_duration == pytest.approx(0.3)
    assert config.awp_mute_duration == pytest.approx(0.6)


def test_the_strip_labels_are_filled_when_the_slider_has_nowhere_to_move(qapp, monkeypatch):
    """这把枪刚好是 0% / 0.10 秒：滑条本来就停在那儿，不发信号，只靠回调刷的话标签一直是空的。"""
    import pages.gun_sound_page as mod

    monkeypatch.setattr(config, "ak47_duck_ratio", 0.0, raising=False)
    monkeypatch.setattr(config, "ak47_mute_duration", 0.1, raising=False)
    page = mod.GunSoundPage()
    try:
        assert page.tuning_weapon == "ak47"
        assert page.duck_slider.value() == 0 and page.duck_label.text() == "0%"
        assert page.duration_slider.value() == 10 and page.duration_label.text() == "0.10秒"
    finally:
        page.deleteLater()
        _settle(qapp)


def test_the_strip_writes_to_the_gun_it_shows(gun, qapp):
    gun.weapon_rows["awp"].name_button.click()
    gun.duck_slider.setValue(35)
    gun.duration_slider.setValue(40)
    _settle(qapp)
    assert config.awp_duck_ratio == pytest.approx(0.35)
    assert config.awp_mute_duration == pytest.approx(0.4)
    assert config.ak47_duck_ratio == pytest.approx(0.2), "改到别的枪头上了"

    gun.weapon_rows["ak47"].name_button.click()
    assert gun.duck_slider.value() == 20
    gun.weapon_rows["awp"].name_button.click()
    assert gun.duck_slider.value() == 35, "第二次回来，滑条没摆到这把枪的值上"


def test_touching_a_gun_brings_the_strip_along(gun, qapp, monkeypatch):
    cell = gun.weapon_rows["m4a1"]
    cell.style_combo.activated.emit(1)
    _settle(qapp)
    assert gun.tuning_weapon == "m4a1", "动过下拉，微调栏没跟过来"

    played = []
    monkeypatch.setattr(gun, "_test_gun_sound", played.append)
    gun.weapon_rows["ak47"].test_button.click()
    _settle(qapp)
    assert gun.tuning_weapon == "ak47" and played == ["ak47"]


def test_apply_all_does_not_move_the_strip(gun, qapp, monkeypatch):
    """整套套用改的是很多把，微调栏不跟着乱跳（下拉走 `activated`，代码改值不发它）。"""
    gun.weapon_rows["awp"].name_button.click()
    gun.weapon_rows["ak47"].style_combo.setCurrentIndex(2)
    _settle(qapp)
    assert config.ak47_style == "乙"
    assert gun.tuning_weapon == "awp"


def test_the_cells_show_configured_and_gone(gun, qapp):
    assert gun.weapon_rows["ak47"].cell_state() == STATE_CONFIGURED
    assert gun.weapon_rows["awp"].cell_state() == STATE_STALE
    assert gun.weapon_rows["m4a1"].cell_state() == ""
    assert "1 / " in gun.weapon_count_label.text()

    gun.weapon_rows["m4a1"].style_combo.setCurrentIndex(1)
    _settle(qapp)
    assert gun.weapon_rows["m4a1"].cell_state() == STATE_CONFIGURED
    assert "2 / " in gun.weapon_count_label.text()


def test_the_spray_sentence_stays_next_to_the_slider(gun, qapp):
    """外审判断题「玩家会不会知道扫射时会留一点原声」12/12 答不会：那句话埋在页头长句末尾。"""
    text = gun.tuning_hint_label.text()
    assert "扫射" in text and "原声" in text
    assert len(text) <= 40, f"句子太长（批 100 改后复跑 20/20 仍不会，理由就是太长）：{text}"
    assert gun.tuning_hint_label.isVisible()

    assert "扫射" in gun.duck_caption.toolTip() and "扫射" in gun.duck_slider.toolTip()
    gun.weapon_rows["awp"].name_button.click()
    assert "扫射" not in gun.duck_caption.toolTip(), "AWP 不是全自动，那句话在它身上不成立"


def test_the_strip_dims_with_the_master_switch(gun, qapp):
    """微调栏钉在滚动区外面：参数区的判定不能只看滚动区。"""
    controls = eff.parameter_area_controls(gun)
    assert gun.duck_slider in controls and gun.duration_slider in controls
    eff.apply_effect_state(gun, False)
    assert gun.duck_slider.property(eff.CARD_DIM_PROPERTY) == "true"
    eff.apply_effect_state(gun, True)
    assert gun.duck_slider.property(eff.CARD_DIM_PROPERTY) is None


def test_an_empty_gun_library_shows_only_the_way_forward(qapp, monkeypatch):
    import pages.gun_sound_page as mod

    monkeypatch.setattr(mod.GunSoundPage, "_scan_gun_sounds",
                        lambda self: setattr(self, "weapon_styles", {}))
    page = mod.GunSoundPage()
    page.resize(1060, 700)
    page.show()
    _settle(qapp)
    try:
        if not page.empty_callout.frame.isVisible():
            pytest.skip("这个发行版没有社区站")
        assert not page.weapon_section.isVisible()
        assert not page.tuning_strip.isVisible()
    finally:
        page.close()
        page.deleteLater()


# ==================================================== 特殊音效页


@pytest.fixture
def special(qapp, monkeypatch):
    import pages.special_sound_page as mod

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "grenade_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "grenade_sound_styles",
                        {"hegrenade": "甲", "flashbang": "已删除"}, raising=False)
    monkeypatch.setattr(config, "c4_sound_style", "0", raising=False)
    monkeypatch.setattr(config, "health_warning_style", "0", raising=False)
    for _key, (_label, _attr, cfg) in mod.SpecialSoundPage.ROUND_TYPE_META.items():
        monkeypatch.setattr(config, cfg, "0", raising=False)

    def refresh(self):
        am = self.audio_manager
        am.grenade_sound_styles = {g: ["甲", "乙"] for g in self.GRENADE_TYPES}
        am.c4_sound_styles = ["甲"]
        am.health_warning_styles = ["甲"]
        for _key, (_label, attr, _cfg) in self.ROUND_TYPE_META.items():
            setattr(am, attr, ["甲"])

    monkeypatch.setattr(mod.SpecialSoundPage, "_refresh_special_sound_styles", refresh)
    page = mod.SpecialSoundPage()
    page.resize(1060, 700)
    page.show()
    _settle(qapp)
    yield page
    page.close()
    page.deleteLater()
    _settle(qapp)


def test_there_are_no_cards_inside_cards(special):
    cards = [f for f in special.findChildren(QFrame)
             if f.objectName() == "card" and f is not special.empty_callout.frame]
    assert not cards, f"又有卡片了：{len(cards)} 张"
    assert special.tab_widget.count() == 4


@pytest.mark.parametrize("tab_name, attr", [
    ("投掷物", "grenade_combos"), ("C4", "c4_combos"), ("回合", "round_combos"),
])
def test_every_event_fits_in_three_rows(special, qapp, tab_name, attr):
    """状态写「已选 0/8」，那八个就得一屏摆得下（RN-665、RN-669）。"""
    tabs = [special.tab_widget.tabText(i) for i in range(special.tab_widget.count())]
    special.tab_widget.setCurrentIndex(tabs.index(tab_name))
    _settle(qapp)
    combos = list(getattr(special, attr).values())
    rows = {combo.parentWidget().y() for combo in combos}
    assert len(rows) <= 3, f"{tab_name}：{len(combos)} 项排了 {len(rows)} 行"
    for combo in combos:
        cell = combo.parentWidget()
        bottom = cell.mapTo(special, cell.rect().bottomLeft()).y()
        assert bottom <= special.height(), f"{tab_name} 有一格在折线下面"


def test_tab_reaches_the_bar_before_the_help_button(special):
    """操作条摆在问号左边，Tab 也要先到它：Tab 走的是建控件的先后，不是摆放的先后。"""
    from PySide6.QtWidgets import QPushButton, QWidget

    chain, node = [], special.nextInFocusChain()
    while node is not None and node is not special:
        chain.append(node)
        node = node.nextInFocusChain()
    help_button = special.findChild(QWidget, "helpButton")
    bar = special.action_bar
    buttons = [b for b in bar.findChildren(QPushButton) if b.isVisibleTo(bar)]
    assert help_button in chain and buttons
    assert chain.index(help_button) > max(chain.index(b) for b in buttons), "Tab 的顺序和眼睛反着"


def test_the_names_on_this_page_are_not_buttons(special):
    """这一页点名字不做事：不占 Tab，也不接鼠标。"""
    cell = special.grenade_combos["hegrenade"].parentWidget()
    assert cell.name_button.focusPolicy() == Qt.NoFocus
    assert cell.name_button.testAttribute(Qt.WA_TransparentForMouseEvents)


def test_the_cells_say_configured_and_gone(special, qapp):
    assert special.grenade_combos["hegrenade"].parentWidget().cell_state() == STATE_CONFIGURED
    assert special.grenade_combos["flashbang"].parentWidget().cell_state() == STATE_STALE
    assert special.grenade_combos["smoke"].parentWidget().cell_state() == ""

    combo = special.grenade_combos["smoke"]
    combo.setCurrentIndex(combo.findData("乙"))
    _settle(qapp)
    assert config.grenade_sound_styles["smoke"] == "乙"
    assert combo.parentWidget().cell_state() == STATE_CONFIGURED

    combo.setCurrentIndex(0)
    _settle(qapp)
    assert config.grenade_sound_styles["smoke"] == "0"
    assert combo.parentWidget().cell_state() == ""


def test_the_gone_note_sits_on_the_tab_where_it_is_gone(special, qapp):
    """那一句「配的风格没了」只说这一类的事（第一版四类合计、只写在回合页签上：
    这里的 flashbang 没了，投掷物页签一句不说，回合页签说「有 1 项」，用户去回合页签找不到）。"""
    text = special.grenade_summary_label.text()
    assert "有 1 项" in text and "重新选" in text, text
    assert special.round_summary_label.text() == ""
    assert special.c4_summary_label.text() == ""


def test_the_note_only_appears_when_there_is_something_to_do(special, qapp):
    """开关关着又配了东西才说话；开关自己的状态它自己看得见。"""
    label = special.grenade_summary_label
    assert label.isVisible() and "开关" in label.text(), label.text()
    box = special.grenade_enabled_checkbox
    assert isinstance(box, QCheckBox)
    box.setChecked(True)
    _settle(qapp)
    assert "开关" not in label.text(), label.text()
    assert config.grenade_sound_enabled is True
    box.setChecked(False)
    _settle(qapp)
    assert "开关" in label.text(), "第二次关上，那句话没回来"


def test_a_cell_can_be_found_before_its_tab_was_ever_shown(qapp, monkeypatch):
    """格子第一次拿到宽度才摆进网格的话，没显示过的页签里一个下拉都找不到：
    置灰、搜索、总开关降权全都看不见它们（空库判据的「反面」逮到的）。"""
    import pages.special_sound_page as mod

    page = mod.SpecialSoundPage()
    try:
        cell = page.round_combos[next(iter(page.round_combos))].parentWidget()
        assert page.isAncestorOf(cell), "格子还没有父控件"
        assert cell.style_combo in page.findChildren(QComboBox)
    finally:
        page.deleteLater()
        _settle(qapp)


def test_a_search_lands_on_the_row_not_the_whole_tab(qapp, monkeypatch):
    """这一页没有卡片了：往上走两级就是整个页签，高亮整页等于没定位。"""
    from types import SimpleNamespace

    import gui_widget
    import pages.special_sound_page as mod

    def refresh(self):
        am = self.audio_manager
        am.grenade_sound_styles = {g: ["甲"] for g in self.GRENADE_TYPES}
        am.c4_sound_styles = ["甲"]
        am.health_warning_styles = ["甲"]
        for _key, (_label, attr, _cfg) in self.ROUND_TYPE_META.items():
            setattr(am, attr, ["甲"])

    monkeypatch.setattr(mod.SpecialSoundPage, "_refresh_special_sound_styles", refresh)
    page = mod.SpecialSoundPage()
    page.tab_widget.setCurrentIndex(3)
    find = gui_widget.MainWindow._find_setting_row
    try:
        row = find(SimpleNamespace(), page, "启用回合音效")
        assert page.round_enabled_checkbox.parentWidget() is row, row
        assert page.round_volume_slider.parentWidget() is row, "开关和音量是一行"

        page.tab_widget.setCurrentIndex(2)
        row = find(SimpleNamespace(), page, "再次提醒间隔")
        assert page.cooldown_slider.parentWidget() is row, row
        assert page.threshold_slider.parentWidget() is not row, "两根滑条是两行"

        page.tab_widget.setCurrentIndex(0)
        row = find(SimpleNamespace(), page, "启用投掷物音效")
        assert row is page.grenade_enabled_checkbox, row
    finally:
        page.deleteLater()
        _settle(qapp)


def test_an_empty_tab_shows_only_the_way_forward(qapp, monkeypatch):
    import pages.special_sound_page as mod

    def refresh(self):
        am = self.audio_manager
        am.grenade_sound_styles = {g: [] for g in self.GRENADE_TYPES}
        am.c4_sound_styles = ["甲"]
        am.health_warning_styles = []
        for _key, (_label, attr, _cfg) in self.ROUND_TYPE_META.items():
            setattr(am, attr, [])

    monkeypatch.setattr(mod.SpecialSoundPage, "_refresh_special_sound_styles", refresh)
    page = mod.SpecialSoundPage()
    page.resize(1060, 700)
    page.show()
    _settle(qapp)
    try:
        if not page.empty_callout.frame.isVisible():
            pytest.skip("这个发行版没有社区站")
        assert not page.grenade_combos["smoke"].isVisible()
        assert page.grenade_enabled_checkbox.isVisible(), "开关要留着：搜索要落得到它"
        page.tab_widget.setCurrentIndex(1)     # C4 有风格
        _settle(qapp)
        assert page.c4_style_combo.isVisible(), "这一类有风格，不该藏"
        assert not page.empty_callout.frame.isVisible()
        page.tab_widget.setCurrentIndex(0)
        _settle(qapp)
        assert not page.grenade_combos["smoke"].isVisible(), "切回来，空的那一类又露出来了"
        page.tab_widget.setCurrentIndex(3)     # 回合也是空的：音量没有东西可调
        _settle(qapp)
        assert not page.round_volume_slider.isVisible()
        assert page.round_enabled_checkbox.isVisible()
    finally:
        page.close()
        page.deleteLater()


# ==================================================== 搜索跳到格子（RN-744）


@pytest.fixture
def seeded_win(qapp, monkeypatch):
    """真窗口，枪声和特殊音效有内容（打桩，不写文件）。"""
    import gui_widget
    import pages.gun_sound_page as gun_mod
    import pages.special_sound_page as special_mod

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "ui_expert_mode", True, raising=False)

    def scan(self):
        self.weapon_styles = {"ak47": ["甲", "乙"], "m4a1": ["甲"]}
        self.style_sample_counts = {}
        self.unknown_weapon_dirs = []

    def refresh(self):
        am = self.audio_manager
        am.grenade_sound_styles = {g: ["甲"] for g in self.GRENADE_TYPES}
        am.c4_sound_styles = ["甲"]
        am.health_warning_styles = ["甲"]
        for _key, (_label, attr, _cfg) in self.ROUND_TYPE_META.items():
            setattr(am, attr, ["甲"])

    monkeypatch.setattr(gun_mod.GunSoundPage, "_scan_gun_sounds", scan)
    monkeypatch.setattr(special_mod.SpecialSoundPage, "_refresh_special_sound_styles", refresh)
    win = gui_widget.MainWindow(auto_background_preload=False)
    win.resize(1280, 800)
    win.show()
    _settle(qapp)
    yield win
    win.close()
    win.deleteLater()
    _settle(qapp)


def _gun_cell(win, name):
    return next(c for c in win.pages["gun_sound"].weapon_rows.values() if c.weapon_name == name)


def _special_cell(win, name):
    return next(cell for cell, *_ in win.pages["special_sound"]._cells if cell.weapon_name == name)


def test_search_lands_on_the_cell_and_the_second_search_moves_it(seeded_win, qapp):
    win = seeded_win
    win._goto_search_result("gun_sound", "Zeus x27", "")
    _settle(qapp)
    zeus = _gun_cell(win, "Zeus x27")
    assert win._search_hit_target is zeus, win._search_hit_target
    assert zeus.property("searchHit") == "true"

    win._goto_search_result("gun_sound", "AK-47", "")
    _settle(qapp)
    assert win._search_hit_target is _gun_cell(win, "AK-47"), win._search_hit_target
    assert zeus.property("searchHit") is None, "上一格的高亮没撤"


def test_a_typed_query_finds_the_cell_too(seeded_win, qapp):
    """从页面级结果跳过去时，手上只有用户敲的词，不是格子上一字不差的名字。"""
    win = seeded_win
    win.settings_search_box.setText("zeus")
    win._goto_search_result("gun_sound")
    _settle(qapp)
    assert win._search_hit_target is _gun_cell(win, "Zeus x27"), win._search_hit_target


def test_searching_a_c4_item_opens_its_tab_and_finds_the_cell(seeded_win, qapp):
    """真走搜索框。「C4」这个页签名曾被索引生成器滤掉，这一页签里的项都切不过去。"""
    win = seeded_win
    win.settings_search_box.setText("C4 拆除")
    win._on_search_text_edited("C4 拆除")
    _settle(qapp)
    win._on_search_return()
    _settle(qapp)
    page = win.pages["special_sound"]
    assert page.tab_widget.tabText(page.tab_widget.currentIndex()) == "C4"
    assert win._search_hit_target is _special_cell(win, "C4 拆除"), win._search_hit_target


def test_a_name_beats_a_switch_that_merely_resembles_it(qapp):
    """索引给的是格子上的原名：排在前面、只是沾边的开关不该抢走它。"""
    import gui_widget

    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addWidget(QCheckBox("启用手雷音效"))
    button = QPushButton("手雷")
    layout.addWidget(button)
    try:
        assert gui_widget.MainWindow._find_setting_row(None, page, "手雷") is button
    finally:
        page.deleteLater()


def test_a_card_title_outranks_a_button_that_resembles_it(seeded_win, qapp):
    from widgets.settings_card import SettingsCard

    win = seeded_win
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addWidget(QPushButton("声音设置向导"))
    card = SettingsCard("声音设置")
    layout.addWidget(card)
    win.pages["__probe"] = page
    try:
        win._highlight_search_target("__probe", "声音")
        assert win._search_hit_target is card, win._search_hit_target
    finally:
        del win.pages["__probe"]
        win._clear_search_highlight()
        page.deleteLater()


def test_the_highlight_shows_on_a_cell_in_every_state(seeded_win, qapp):
    """格子自己带 id 规则，通用的 `QWidget[searchHit]` 压不过它。抓图比，不查样式表文字。"""
    win = seeded_win
    win._goto_search_result("gun_sound")
    _settle(qapp)
    cell = _gun_cell(win, "AK-47")
    board = win.pages["gun_sound"].weapon_board

    def shot(hit):
        cell.setProperty("searchHit", hit)
        cell.style().unpolish(cell)
        cell.style().polish(cell)
        return cell.grab().toImage()

    for master_off in ("", "true"):
        board.setProperty("masterOff", master_off)
        for state in ("", STATE_CONFIGURED, STATE_STALE):
            cell.set_cell_state(state)
            plain, lit, fading = shot(None), shot("true"), shot("fade")
            label = f"masterOff={master_off!r} state={state!r}"
            assert lit != plain, f"高亮看不出来：{label}"
            assert fading != plain and fading != lit, f"渐隐那一档看不出来：{label}"
    board.setProperty("masterOff", "")
    shot(None)


def test_the_scroll_area_that_holds_the_cell_is_the_one_that_moves(seeded_win, qapp):
    """一页好几个滚动区（每个页签一个），滚第一个滚不动别的页签里的格子。"""
    win = seeded_win
    win._goto_search_result("special_sound", "", "回合")
    _settle(qapp)
    page = win.pages["special_sound"]
    scroll = page.tab_widget.currentWidget()
    scroll.setFixedHeight(90)
    _settle(qapp)
    win._goto_search_result("special_sound", "比赛结束", "回合")
    _settle(qapp)
    cell = _special_cell(win, "比赛结束")
    top = cell.mapTo(scroll.viewport(), QPoint(0, 0)).y()
    assert 0 <= top and top + cell.height() <= scroll.viewport().height(), (top, scroll.viewport().height())


def test_the_weapon_count_is_not_a_search_term(seeded_win, qapp):
    """「已配置 3 / 35」是这一刻的值，进了索引就是一份过期数据（RN-568）。"""
    win = seeded_win
    for page_id in ("gun_sound", "kill_sound"):
        win.ensure_page_loaded(page_id)
        assert win.pages[page_id].weapon_count_label.property("fp_index_skip"), page_id
