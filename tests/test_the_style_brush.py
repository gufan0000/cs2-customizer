# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 146：风格库 + 武器板。选一个风格当刷子，再点枪名就配上。

R8 的账（`docs/ui-perf/04_设计约束与红线.md`）：改一把枪 2 次点击、同一风格再改一把 1 次，
39 把枪一块板，不再切分类页签。这里全部走真点击，**一轮连做几次操作**：
缺陷多半出在第二次（`endtoend-beats-unit-judges`）。
"""
from __future__ import annotations

import wave
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTabWidget

from config import config

STYLES = ("刷子判据甲", "刷子判据乙")


def _make_wav(path: Path, made: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 400)
    made.append(path)


@pytest.fixture
def styles_on_disk():
    """全局风格（kill_sound）+ 只有四把枪才有的 per-weapon 风格（reload_sound）。"""
    from core.audio.runtime_audio import get_runtime_audio_manager
    from resource_manager import ResourceManager

    root = Path(ResourceManager.get_app_data_path("resources/audio"))
    made: list[Path] = []
    for style in STYLES:
        for level in range(1, 6):
            _make_wav(root / "kill_sounds" / style / f"{level}.wav", made)
        for weapon in ("weapon_ak47", "weapon_m4a1", "weapon_awp", "weapon_glock"):
            _make_wav(root / "reload_sounds" / weapon / style / "a.wav", made)
    manager = get_runtime_audio_manager()
    manager._styles_scanned = False
    manager.ensure_styles_scanned()
    yield manager
    for path in made:
        path.unlink(missing_ok=True)
    manager._styles_scanned = False
    manager.ensure_styles_scanned()


@pytest.fixture
def page(qapp, styles_on_disk, monkeypatch):
    from pages.kill_sound_page import KillSoundPage

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "weapon_kill_sounds", {}, raising=False)
    p = KillSoundPage()
    p.setAttribute(Qt.WA_DontShowOnScreen, True)
    p.resize(1040, 720)
    p.show()
    qapp.processEvents()
    p._refresh_style_catalog()
    qapp.processEvents()
    yield p
    p.hide()
    p.deleteLater()
    qapp.processEvents()


def test_a_card_stays_tall_after_switching_to_the_theme_without_a_stylesheet(qapp):
    """极简主题没有样式表，高度只能靠 sizeHint。
    ⚠ 第一版用 setMinimumHeight：样式表里写过 min-height，换到极简主题时 Qt 把它清零，
    卡片压成一条，两行字叠在一起（9 个主题的图上才看得到）。
    ⚠ 第二版 sizeHint 写对了，产品里还是压扁：建页后全局给标签开折行，卡片的高度变成
    「按宽度算」，布局不再问 sizeHint。所以这里要走同一步，光建控件量不到。"""
    from ui_style_applier import get_style_applier
    from widgets.style_library import StyleLibrary

    previous = qapp.styleSheet()
    library = StyleLibrary()
    try:
        library.set_styles([("甲", "正在用")])
        get_style_applier().apply_complete_system(library)
        assert not library.card("甲").hasHeightForWidth()
        library.resize(300, 200)
        qapp.setStyleSheet("QPushButton#styleCard { min-height: 52px; }")
        library.show()
        qapp.processEvents()
        qapp.setStyleSheet("")
        qapp.processEvents()
        card = library.card("甲")
        assert card.height() >= card.fontMetrics().height() * 2, card.height()
    finally:
        qapp.setStyleSheet(previous)
        library.close()
        library.deleteLater()
        qapp.processEvents()


def _click(widget) -> None:
    QTest.mouseClick(widget, Qt.LeftButton)


def test_two_clicks_for_one_weapon_then_one_more_for_the_next(page, qapp):
    """R8 的账：第一把枪 2 次，同一风格再配一把 1 次；配上了全页都要跟着变。"""
    card = page.style_library.card(STYLES[0])
    assert card is not None, f"风格库里没有造好的风格：{page.style_library.styles()}"

    _click(card)
    assert page.style_library.brush() == STYLES[0]
    assert page.apply_all_combo.currentText() == STYLES[0], "刷子和「应用到全部武器」要的是同一个风格"

    first = page.weapon_rows["weapon_ak47"]
    _click(first.name_button)
    qapp.processEvents()
    assert config.weapon_kill_sounds.get("weapon_ak47") == STYLES[0], "点枪名没有写进配置"
    assert first.get_current_style() == STYLES[0], "格子里的下拉没跟上"
    assert first.cell_state() == "configured"
    assert card.meta_label.text() == "用在 1 把枪上"
    assert page.weapon_count_label.text().startswith("已配置 1 /")

    second = page.weapon_rows["weapon_awp"]
    _click(second.name_button)
    qapp.processEvents()
    assert config.weapon_kill_sounds.get("weapon_awp") == STYLES[0], "第二把枪要再选一次风格？刷子没留住"
    assert card.meta_label.text() == "用在 2 把枪上"
    assert page.weapon_count_label.text().startswith("已配置 2 /")


def test_clicking_a_configured_weapon_again_cancels_it(page, qapp):
    _click(page.style_library.card(STYLES[0]))
    cell = page.weapon_rows["weapon_ak47"]
    _click(cell.name_button)
    _click(cell.name_button)
    qapp.processEvents()
    assert cell.get_current_style() == page.DISABLED_STYLE_TEXT
    assert not page._is_style_enabled(config.weapon_kill_sounds.get("weapon_ak47", "0"))
    assert cell.cell_state() == ""
    assert page.style_library.card(STYLES[0]).meta_label.text() == "未使用"


def test_changing_the_brush_overwrites_with_the_new_style(page, qapp):
    """换刷子后再点同一把枪：改成新风格，不是取消。"""
    _click(page.style_library.card(STYLES[0]))
    cell = page.weapon_rows["weapon_ak47"]
    _click(cell.name_button)
    _click(page.style_library.card(STYLES[1]))
    _click(cell.name_button)
    qapp.processEvents()
    assert config.weapon_kill_sounds.get("weapon_ak47") == STYLES[1]
    assert page.style_library.card(STYLES[0]).meta_label.text() == "未使用"
    assert page.style_library.card(STYLES[1]).meta_label.text() == "用在 1 把枪上"


def test_no_brush_means_clicking_a_name_changes_nothing(page, qapp):
    """刚进页面没有刷子：手滑点枪名不许改掉已经配好的枪。"""
    cell = page.weapon_rows["weapon_ak47"]
    cell.set_current_style(STYLES[0])
    qapp.processEvents()
    assert page.style_library.brush() == ""
    _click(cell.name_button)
    qapp.processEvents()
    assert config.weapon_kill_sounds.get("weapon_ak47") == STYLES[0]


def test_clicking_the_same_card_puts_the_brush_down(page, qapp):
    card = page.style_library.card(STYLES[0])
    _click(card)
    cell = page.weapon_rows["weapon_ak47"]
    assert cell.property("fp_brush") == "can"
    _click(card)
    assert page.style_library.brush() == ""
    assert not card.isChecked()
    assert not cell.property("fp_brush"), "放下刷子后格子还是可刷的样子"
    assert "枪名" in page.library_hint.text()


def test_the_combo_in_a_cell_still_works(page, qapp):
    """下拉是精确选择的路，和刷子走同一条落盘，页面状态一样要跟。"""
    cell = page.weapon_rows["weapon_awp"]
    cell.style_combo.setCurrentText(STYLES[1])
    qapp.processEvents()
    assert config.weapon_kill_sounds.get("weapon_awp") == STYLES[1]
    assert cell.cell_state() == "configured"
    assert page.style_library.card(STYLES[1]).meta_label.text() == "用在 1 把枪上"


def test_the_card_play_button_plays_that_style_and_assigns_nothing(page, styles_on_disk, monkeypatch, qapp):
    played = []
    monkeypatch.setattr(styles_on_disk, "play_sound", lambda key, **_k: played.append(key) or True)
    monkeypatch.setattr(page.audio_manager, "play_sound", lambda key, **_k: played.append(key) or True)
    _click(page.style_library.card(STYLES[1]).play_button)
    qapp.processEvents()
    assert played and all(STYLES[1] in key for key in played), f"试听的不是这张卡的风格：{played}"
    assert page.style_library.brush() == "", "点试听把刷子也选上了"
    assert not any(page._is_style_enabled(v) for v in config.weapon_kill_sounds.values()), "试听改了配置"


def test_a_style_that_disappears_takes_the_brush_with_it(page, qapp):
    """刷子指着的风格被删了：不能留着一把刷不出东西的刷子。"""
    _click(page.style_library.card(STYLES[0]))
    assert page.weapon_rows["weapon_ak47"].property("fp_brush") == "can"
    page.style_library.set_styles([(STYLES[1], "未使用")])
    qapp.processEvents()
    assert page.style_library.brush() == ""
    assert not page.weapon_rows["weapon_ak47"].property("fp_brush")
    assert page.style_library.card(STYLES[0]) is None


def test_refreshing_the_list_keeps_the_brush(page, qapp):
    """风格没变时刷新列表不许把手上的刷子弄丢。"""
    _click(page.style_library.card(STYLES[0]))
    card_before = page.style_library.card(STYLES[0])
    page._refresh_style_catalog()
    qapp.processEvents()
    assert page.style_library.brush() == STYLES[0]
    assert page.style_library.card(STYLES[0]) is card_before, "风格没变却把卡片重建了（键盘焦点会丢）"
    assert page.weapon_rows["weapon_ak47"].property("fp_brush") == "can"


def test_a_weapon_without_that_style_refuses_the_brush(qapp, styles_on_disk, monkeypatch):
    """per-weapon 的页：这把枪没有这个风格，点了不能写一个解析不出来的值（RN-026 族）。"""
    from PySide6.QtWidgets import QToolTip

    from pages.reload_sound_page import ReloadSoundPage

    said = []
    monkeypatch.setattr(QToolTip, "showText", staticmethod(lambda _pos, text, *_rest: said.append(text)))
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "weapon_reload_sounds", {}, raising=False)
    page = ReloadSoundPage()
    try:
        page.setAttribute(Qt.WA_DontShowOnScreen, True)
        page.resize(1040, 720)
        page.show()
        qapp.processEvents()
        page._refresh_style_catalog()
        qapp.processEvents()
        _click(page.style_library.card(STYLES[0]))
        has_it = page.weapon_rows["weapon_ak47"]
        lacks_it = page.weapon_rows["weapon_famas"]
        assert has_it.property("fp_brush") == "can"
        assert lacks_it.property("fp_brush") == "cannot"
        _click(lacks_it.name_button)
        qapp.processEvents()
        assert said and STYLES[0] in said[-1], "点了没反应，也不说为什么"
        assert lacks_it.get_current_style() == page.DISABLED_STYLE_TEXT
        assert "weapon_famas" not in config.weapon_reload_sounds or not page._is_style_enabled(
            config.weapon_reload_sounds["weapon_famas"])
        _click(has_it.name_button)
        qapp.processEvents()
        assert has_it.cell_state() == "configured"
    finally:
        page.hide()
        page.deleteLater()
        qapp.processEvents()


def test_the_master_switch_dims_configured_cells_for_real(page, qapp):
    """总开关关着：配了的格子退成中性。量像素：属性设上了而屏幕没变的事批 16 出过（RN-407）。"""
    from theme_manager import get_theme_manager
    from widgets.master_switch_effect import apply_effect_state

    cell = page.weapon_rows["weapon_ak47"]
    cell.set_current_style(STYLES[0])
    qapp.processEvents()

    def corner_colour():
        image = cell.grab().toImage()
        return image.pixelColor(image.width() // 2, 2).rgb()

    previous = qapp.styleSheet()
    # ⚠ 单独建的页面没有全局样式表，不装上量到的是系统默认色，两态自然一样
    qapp.setStyleSheet(get_theme_manager().themes["dark"].generate_stylesheet())
    try:
        apply_effect_state(page, True)
        qapp.processEvents()
        assert page.weapon_board.property("masterOff") in (None, "", False)
        lit = corner_colour()
        apply_effect_state(page, False)
        qapp.processEvents()
        assert page.weapon_board.property("masterOff") == "true"
        assert corner_colour() != lit, "总开关关着，配了的格子一个像素都没变"
        apply_effect_state(page, True)
        qapp.processEvents()
        assert corner_colour() == lit, "开回来颜色没回来"
    finally:
        qapp.setStyleSheet(previous)


def test_without_a_stylesheet_nothing_is_squashed_or_pushed_out(page, qapp):
    """极简主题没有样式表：风格卡不压扁，武器板不撑出页面（批 146 看九个主题时逮到）。"""
    previous = qapp.styleSheet()
    qapp.setStyleSheet("")
    try:
        for _ in range(6):
            qapp.processEvents()
        card = page.style_library.card(STYLES[0])
        lines = card.fontMetrics().height() * 2
        assert card.height() >= lines, f"风格卡高 {card.height()}，两行字要 {lines}"
        room = page.content_scroll.viewport().width()
        assert page.content_scroll.widget().width() <= room, (
            f"内容宽 {page.content_scroll.widget().width()} > 视口 {room}：横向滚动条关着，右边的控件够不着")
        cell = page.weapon_rows["weapon_ak47"]
        assert cell.width() >= cell.minimumSizeHint().width()
        # 系统样式的控件有多宽各机器不一样，这里直接撑到比样式表里宽得多
        for cell in page.weapon_board.cells():
            cell.style_combo.setMinimumWidth(320)
        page.weapon_board.set_available_width(room)
        for _ in range(6):
            qapp.processEvents()
        assert page.content_scroll.widget().width() <= room, "列数没跟着控件的真实下限走"
    finally:
        qapp.setStyleSheet(previous)


def test_the_group_labels_fit_whatever_they_say(page, qapp):
    """分类名那一列按字现算：写死的 62 宽在 1.25 档放不下「手雷/道具」，折成两行被裁。"""
    label = page.weapon_board._groups[0][0]
    label.setText("A very long group name, far wider than any fixed column")   # 离屏没有中文字体
    page.weapon_board._sync_layout()
    qapp.processEvents()
    assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())
    assert not label.wordWrap(), "分类名会折行"


def _load_tab_audit():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "tab_order_audit", Path(__file__).resolve().parents[1] / "scripts" / "tab_order_audit.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["tab_order_audit"] = module
    spec.loader.exec_module(module)
    return module


def test_tab_goes_through_the_library_before_the_weapons(page, qapp):
    """风格卡是刷新列表时才建的：不接回去，Tab 要走完整块武器板才到风格库。"""
    audit = _load_tab_audit()

    def assert_in_order():
        chain = audit.focusable_chain(page)
        moves = audit.min_moves(chain, audit.reading_order(chain, page))
        assert moves == 0, f"焦点链和阅读顺序差 {moves} 处：{[getattr(w, 'text', str)() for w in chain][:12]}"
        first_weapon = page.weapon_rows["weapon_glock"].name_button
        for style in page.style_library.styles():
            assert chain.index(page.style_library.card(style)) < chain.index(first_weapon)

    assert_in_order()
    # 换一批风格（卡片重建）之后也要接回去
    page.style_library.set_styles([(STYLES[1], "未使用")])
    qapp.processEvents()
    assert_in_order()


def test_an_empty_library_does_not_claim_it_takes_effect(qapp, monkeypatch):
    """开关开着、一个素材都没有：不说「当场生效」（批 145 外审：「误导玩家以为进游戏就能直接用」）。"""
    from pages.kill_sound_page import KillSoundPage

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "kill_sound_enabled", True, raising=False)
    page = KillSoundPage()
    try:
        page.setAttribute(Qt.WA_DontShowOnScreen, True)
        page.resize(1040, 720)
        page.show()
        qapp.processEvents()
        monkeypatch.setattr(page, "_library_is_empty", lambda: True)
        page._sync_community_guidance()
        qapp.processEvents()
        if not page.empty_callout.frame.isVisibleTo(page):
            pytest.skip("这个发行版没有社区站，引导卡不出现")
        assert page.master_switch_row.saved_hint.isHidden(), "空库还在说「当场生效」"
        monkeypatch.setattr(page, "_library_is_empty", lambda: False)
        page._sync_community_guidance()
        qapp.processEvents()
        assert not page.master_switch_row.saved_hint.isHidden(), "有素材了那句话没回来"
    finally:
        page.hide()
        page.deleteLater()
        qapp.processEvents()


def test_there_are_no_category_tabs_any_more(page):
    """分类页签是这批要去掉的那一步（R8）。"""
    assert not page.findChildren(QTabWidget), "武器又分进页签了：配一把枪要多一次切换"
    groups = {label.text() for label, _cells in page.weapon_board._groups}
    assert set(page.CATEGORIES) == groups, "分类不见了：分类还在，只是不用切"
    assert len(page.weapon_board.cells()) == len(page.weapon_rows)
