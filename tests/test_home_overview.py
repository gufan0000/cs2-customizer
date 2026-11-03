# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 148：总览页和侧栏（RN-742、RN-743）。

全走真点击，一轮连做两次：缺陷常常在第二次操作才出现。
状态条那一套是纯函数（`readiness_view`），逐状态问不用建窗口；接线另外走真窗口。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402

from config import config  # noqa: E402
from core.feature_summary import feature_summary  # noqa: E402
from core.runtime.system_status_service import (  # noqa: E402
    EXCLUSIVE_DETAIL,
    NO_CS2_DIR_HEADLINE,
    READINESS_HEADLINE,
    RuntimeStatus,
    readiness_view,
)
from widgets.home_overview import FEATURE_PANEL_GAP, FEATURE_PANEL_MIN_WIDTH  # noqa: E402
from widgets.nav_button import DOT_NONE, DOT_ON, DOT_WARN  # noqa: E402
from widgets.overlay_requirement import REQUIRED_WORDS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FEATURE_KEYS = (
    "kill_sound_enabled", "kill_voice_enabled", "kill_icon_enabled", "gun_sound_enabled", "death_sound_enabled",
    "switch_weapon_sound_enabled", "reload_sound_enabled", "crosshair_enabled", "magnifier_enabled", "flash_enabled",
    "hud_rules_enabled", "screen_effects_enabled", "music_enabled", "utility_guide_enabled", "voice_output_enabled",
    "fun_afterlife_enabled", "spectator_mode_mute",
    "grenade_sound_enabled", "c4_sound_enabled", "health_warning_enabled", "round_sound_enabled",
)


def _settle(qapp, rounds=6):
    for _ in range(rounds):
        qapp.processEvents()


@pytest.fixture
def win(qapp, monkeypatch):
    import gui_widget

    monkeypatch.setattr(config, "save_config", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(config, "ui_expert_mode", False, raising=False)
    monkeypatch.setattr(config, "compact_mode", False, raising=False)
    monkeypatch.setattr(config, "weapon_kill_sounds", {}, raising=False)
    for key in FEATURE_KEYS:
        monkeypatch.setattr(config, key, False, raising=False)
    window = gui_widget.MainWindow(auto_background_preload=False)
    window.setAttribute(Qt.WA_DontShowOnScreen, True)
    window.resize(1280, 800)
    window.show()
    _settle(qapp)
    window.show_page("basic", animated=False, force=True)
    _settle(qapp)
    yield window
    window._force_exit = True
    window.close()
    window.deleteLater()
    _settle(qapp)


def _click_switch(toggle, qapp):
    QTest.mouseClick(toggle, Qt.LeftButton, Qt.NoModifier, toggle.rect().center())
    _settle(qapp)


def _click_card(card, qapp):
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, QPoint(card.height(), card.height() // 2))
    QTest.qWait(30)
    _settle(qapp)


# ==================================================== 功能卡


def test_every_switch_sits_on_exactly_one_card(win):
    assert len(win.switches) == 17, "总开关的个数变了，这页的分组要跟着看一遍"
    assert set(win.feature_cards) == set(win.switches)
    for switch_id, card in win.feature_cards.items():
        assert win.switches[switch_id].parentWidget() is card
    grouped = [switch_id for _label, switch_ids in win._feature_group_labels for switch_id in switch_ids]
    assert sorted(grouped) == sorted(win.switches), "有开关不在任何一组里，或者在两组里"


def test_the_card_opens_the_page_and_the_switch_stays_home(win, qapp):
    card, toggle = win.feature_cards["gun_sound"], win.switches["gun_sound"]
    _click_switch(toggle, qapp)
    assert config.gun_sound_enabled is True
    assert win._current_page_id == "basic", "点开关把人带走了"
    _click_switch(toggle, qapp)
    assert config.gun_sound_enabled is False
    assert win._current_page_id == "basic"

    for _ in range(2):
        _click_card(card, qapp)
        assert win._current_page_id == "gun_sound", "点卡片没进那一页"
        win.show_page("basic", animated=False)
        _settle(qapp)
    assert config.gun_sound_enabled is False, "点卡片改了开关"


def test_a_card_with_no_page_says_so_and_only_has_its_switch(win, qapp):
    card = win.feature_cards["spectator"]
    assert "›" not in card.name_label.text()
    assert card.focusPolicy() == Qt.NoFocus
    assert "›" in win.feature_cards["gun_sound"].name_label.text(), "能点进去的卡要静态看得出来（RN-235）"
    _click_card(card, qapp)
    assert win._current_page_id == "basic"


def test_the_current_nav_item_is_heavier(win, qapp):
    """批 155：样式表 `:checked` 里的字重从没生效过（Qt 不按伪状态改控件字体），选中项和别的一样细。"""
    for page in ("gun_sound", "basic", "gun_sound"):
        win.show_page(page, animated=False, force=True)
        qapp.processEvents()
        weights = {pid: button.font().weight() for pid, button in win.nav_buttons.items()}
        assert weights[page] == QFont.Medium, (page, weights[page])
        assert {w for pid, w in weights.items() if pid != page} == {QFont.Normal}


def _assert_meta_line(card, qapp, *, shown):
    """批 155：关着的那一行不写「已关闭」（开关已经说了），名字在行里上下居中；读屏照样读到。"""
    qapp.processEvents()
    assert card.meta_label.isVisibleTo(card) is shown
    assert card.accessibleDescription() == card.meta_label.full_text()
    if not shown:
        name = card.name_label.geometry()
        assert abs(name.center().y() - card.rect().center().y()) <= 2, (name, card.rect())


def test_the_card_follows_its_switch_both_ways(win, qapp):
    """摘要、名字颜色、分组计数、状态条那句「已开」、侧栏小点，开关动一下全跟。"""
    card, toggle = win.feature_cards["gun_sound"], win.switches["gun_sound"]
    head = next(label for label, ids in win._feature_group_labels if "gun_sound" in ids)
    win._sync_home_readiness(readiness_view(_status()))
    assert card.meta_label.full_text() == "已关闭"
    assert card.name_label.objectName() == "switchLabelOff"
    assert head.text() == "已开 0 / 6"
    assert "已开 0 / 17" in win.system_status_label.text()
    _assert_meta_line(card, qapp, shown=False)

    for _ in range(2):
        _click_switch(toggle, qapp)
        _assert_meta_line(card, qapp, shown=True)
        assert card.meta_label.full_text() == "还没配枪"
        assert card.accessibleDescription() == "还没配枪"
        assert card.name_label.objectName() == "switchLabelOn"
        assert head.text() == "已开 1 / 6"
        assert "已开 1 / 17" in win.system_status_label.text()
        assert win.nav_buttons["gun_sound"].status_dot() == DOT_ON
        _click_switch(toggle, qapp)
        assert card.meta_label.full_text() == "已关闭"
        _assert_meta_line(card, qapp, shown=False)
        assert head.text() == "已开 0 / 6"
        assert win.nav_buttons["gun_sound"].status_dot() == DOT_NONE


def test_a_change_from_another_page_reaches_the_card(win, qapp):
    """配置被别处改了（RN-089）：开关和卡片都要跟，不走 `_on_switch_changed`。"""
    config.kill_sound_enabled = True
    assert win.sync_feature_switch("kill_sound_enabled")
    _settle(qapp)
    assert win.switches["kill_sound"].isChecked()
    assert win.feature_cards["kill_sound"].meta_label.full_text() == "还没配枪"
    assert win.nav_buttons["kill_sound"].status_dot() == DOT_ON


def test_a_rolled_back_switch_leaves_the_card_off(win, qapp, monkeypatch):
    """准心少组件时开关弹回去：卡片不能停在开着的样子。"""
    import PySide6.QtWidgets as widgets

    monkeypatch.setattr(win, "_crosshair_win32_available", False, raising=False)
    monkeypatch.setattr(widgets.QMessageBox, "warning", staticmethod(lambda *_a, **_k: None))
    _click_switch(win.switches["crosshair"], qapp)
    assert not win.switches["crosshair"].isChecked()
    card = win.feature_cards["crosshair"]
    assert card.meta_label.full_text() == "已关闭"
    assert card.name_label.objectName() == "switchLabelOff"
    assert win.nav_buttons["crosshair"].status_dot() == DOT_NONE


def test_an_expert_page_opened_from_a_link_fits_the_sidebar(win, qapp):
    """普通模式从链接进专家页，侧栏临时多一项：不出滚动条，「关于软件」不被挤出视野。"""
    win.resize(1280, 800)
    _settle(qapp)
    win.show_page("preset_center", animated=False, force=True)
    _settle(qapp)
    assert win.nav_buttons["preset_center"].isVisible()
    scroll = win._sidebar_scroll
    assert scroll.verticalScrollBar().maximum() == 0, (
        f"内容 {scroll.widget().sizeHint().height()}，视口 {scroll.viewport().height()}")
    about = win.nav_buttons["about"]
    assert about.visibleRegion().boundingRect().height() == about.height(), "「关于软件」被挤出视野了"


def test_the_sidebar_breathes_when_the_window_is_tall_and_still_fits_when_it_is_not(win, qapp):
    """批 153：窗口够高导航项放宽到 28；默认 800 高放不下宽松档就收回 24。两档都不用滚，来回两次。

    组头也要跟着换档重算高度：属性换了不发 StyleChange，组头留着上一档缓存的 sizeHint。
    """
    from PySide6.QtWidgets import QPushButton

    from theme_manager import NAV_GROUP_PAD, NAV_GROUP_PAD_DENSE, NAV_ITEM_HEIGHT, NAV_ITEM_HEIGHT_DENSE

    scroll = win._sidebar_scroll
    win.setMinimumSize(1200, 600)
    for _ in range(2):
        header_heights = []
        for height, item in ((1000, NAV_ITEM_HEIGHT), (800, NAV_ITEM_HEIGHT_DENSE)):
            win.resize(1280, height)
            _settle(qapp, 12)
            shown = [button for button in win.nav_buttons.values() if button.isVisible()]
            assert len(shown) >= 20, f"只有 {len(shown)} 项可见，分母不对"
            assert {button.height() for button in shown} == {item}, height
            assert scroll.verticalScrollBar().maximum() == 0, (
                height, scroll.widget().sizeHint().height(), scroll.viewport().height())
            headers = {h.height() for h in scroll.widget().findChildren(QPushButton, "navGroupHeader") if h.isVisible()}
            assert len(headers) == 1, (height, headers)
            header_heights.append(headers.pop())
        assert header_heights[0] - header_heights[1] == sum(NAV_GROUP_PAD) - sum(NAV_GROUP_PAD_DENSE), header_heights


def test_the_sidebar_density_does_not_flip_back_and_forth_at_the_threshold(win, qapp):
    """临界高度上来回翻是这套算法最可能的坏法：逐 2px 扫过门槛，每档落定后再自己算一遍，档位不许变。"""
    win.setMinimumSize(1200, 600)
    seen = []
    for height in range(870, 950, 2):
        win.resize(1280, height)
        _settle(qapp, 8)
        state = win.sidebar.property("navDense")
        win._apply_nav_density()
        _settle(qapp, 8)
        assert win.sidebar.property("navDense") == state, height
        assert win._sidebar_scroll.verticalScrollBar().maximum() == 0, height
        seen.append(state)
    assert True in seen and False in seen, "门槛不在扫的这一段里，这条判据什么也没量到"


def test_coming_back_shows_what_was_changed_elsewhere(win, qapp):
    _click_switch(win.switches["kill_sound"], qapp)
    win.show_page("gun_sound", animated=False)
    _settle(qapp)
    config.weapon_kill_sounds = {"weapon_ak47": "甲", "weapon_awp": "0", "weapon_m4a1": "乙"}
    win.show_page("basic", animated=False)
    _settle(qapp)
    meta = win.feature_cards["kill_sound"].meta_label.full_text()
    assert meta in ("已配 2 把枪", "2 项风格失效"), meta


def test_cards_stay_tall_in_the_theme_without_a_stylesheet(qapp):
    """两行字叠在一起的那个坑（批 147 风格卡）：全局开折行后高度按宽度算，布局不再问 sizeHint。"""
    from ui_style_applier import get_style_applier
    from widgets.home_overview import FeatureCard

    previous = qapp.styleSheet()
    card = FeatureCard("甲", QWidget(), icon_name="mdi.volume-off", has_page=True)
    try:
        # ⚠ 建页时全局开折行只碰有字的标签：小字是空的就量不到
        card.set_state(True, "已配 2 把枪")
        get_style_applier().apply_complete_system(card)
        assert not card.name_label.wordWrap()
        assert not card.meta_label.wordWrap()
        assert not card.hasHeightForWidth()
        qapp.setStyleSheet("")
        assert card.sizeHint().height() >= card.fontMetrics().height() * 2 + 12
    finally:
        qapp.setStyleSheet(previous)
        card.deleteLater()


def test_the_grid_follows_the_width_both_ways(qapp):
    """三块面板够宽就并排，不够就一列摞起来，不排成二加一（批 153）。"""
    from widgets.home_overview import FeatureCard, FeatureGrid, FeaturePanel

    # ⚠ 放在父控件里：顶层窗口的最小尺寸由布局说了算，窄不下去，量的就不是产品里的样子
    holder = QWidget()
    holder.setAttribute(Qt.WA_DontShowOnScreen, True)
    grid = FeatureGrid(holder)
    for title in ("甲", "乙", "丙"):
        panel = FeaturePanel(title)
        for index in range(2):
            panel.add_card(FeatureCard(f"{title}{index}", QWidget(), icon_name="mdi.volume-off", has_page=False))
        grid.add_panel(panel)
    holder.resize(1200, 500)
    holder.show()
    three = FEATURE_PANEL_MIN_WIDTH * 3 + FEATURE_PANEL_GAP * 2
    try:
        for width, columns in ((1100, 3), (three, 3), (three - 1, 1), (FEATURE_PANEL_MIN_WIDTH, 1), (1100, 3)):
            grid.resize(width, 400)
            _settle(qapp)
            assert grid.columns() == columns, width
            assert grid._grid.count() == 3, "换列时掉了面板"
    finally:
        holder.close()
        holder.deleteLater()


def test_the_grid_never_pushes_the_page_sideways(win, qapp):
    """列数按自己的宽度算：最小宽要是跟着列数走，就把滚动区撑出横向滚动条，窗口变窄也退不回来。"""
    from PySide6.QtWidgets import QScrollArea

    grid = win.feature_grid
    scroll = win.pages["basic"].findChild(QScrollArea)
    win.setMinimumSize(860, 480)
    seen = []
    for width in (1280, 900, 1280, 900):
        win.resize(width, 800)
        _settle(qapp, 12)
        assert scroll.horizontalScrollBar().maximum() == 0, width
        assert scroll.widget().width() == scroll.viewport().width(), width
        assert grid.columns() == grid.columns_for(grid.width()), width
        seen.append(grid.columns())
    assert seen[0] == seen[2] == 3, seen
    assert seen[1] == seen[3] == 1, seen


def test_the_overview_is_a_status_card_three_panels_and_two_cards(win, qapp):
    """批 153 的总览：状态卡 → 三块功能面板并排 → 音量和偏好两张卡并排；窄了各自摞起来。来回两次。"""
    grid, split = win.feature_grid, win.home_split_row
    assert [panel.title_label.text() for panel in grid.panels()] == ["声音", "画面", "媒体与工具"]
    assert sum(len(panel.cards) for panel in grid.panels()) == len(win.switches)
    page = win.pages["basic"]
    order = [widget.mapTo(page, QPoint(0, 0)).y() for widget in (win.basic_status_card, grid, split)]
    assert order == sorted(order), f"块的上下顺序不对：{order}"
    win.setMinimumSize(860, 480)
    for width, wide in ((1280, True), (900, False), (1280, True), (900, False)):
        win.resize(width, 800)
        _settle(qapp, 12)
        panels = grid.panels()
        tops = {panel.mapTo(grid, QPoint(0, 0)).y() for panel in panels}
        assert (len(tops) == 1) == wide, (width, tops)
        if wide:
            assert len({panel.height() for panel in panels}) == 1, "并排的三块下沿参差"
        assert split.is_side_by_side() == wide, width


def test_the_overview_draws_no_loud_borders_in_any_theme():
    """批 153：总览原来一屏二十来道 border_primary 亮框（17 张卡 + 状态条），用户说「密密麻麻」。

    状态卡和面板只描最软那档边，功能行不描边：换哪个主题都一样。
    """
    import re

    from theme_manager import get_theme_manager

    def body(qss, selector):
        match = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{(.*?)\}", qss, re.S)
        assert match, f"样式表里找不到 {selector}"
        return match.group(1)

    checked = 0
    for name, theme in get_theme_manager().themes.items():
        qss = theme.generate_stylesheet()
        if "QFrame#featurePanel" not in qss:
            continue  # 极简主题没有样式表
        soft = f"border: 1px solid {theme.colors.border_secondary}"
        for selector in ("QFrame#readinessStrip", "QFrame#featurePanel"):
            assert soft in body(qss, selector), (name, selector)
        rows = "QPushButton#featureCard, QPushButton#featureCard:hover, QPushButton#featureCard:pressed"
        assert "border: none" in body(qss, rows), name
        checked += 1
    assert checked >= 5, f"只量了 {checked} 个主题，分母不对"


def test_the_brand_row_carries_the_app_mark(win, qapp):
    """批 153：侧栏顶上原来只有四个字，和任务栏、窗口上那个图标对不上号。名字左边挂应用图标，两者垂直居中。"""
    from PySide6.QtWidgets import QLabel

    from gui_widget import BrandMark

    marks = win.sidebar.findChildren(BrandMark)
    assert len(marks) == 1, f"侧栏里有 {len(marks)} 个品牌图标"
    mark, title = marks[0], win.sidebar.findChild(QLabel, "sidebarTitleLabel")
    assert mark.isVisible() and title is not None
    box, words = (w.rect().translated(w.mapTo(win.sidebar, QPoint(0, 0))) for w in (mark, title))
    assert box.right() < words.left(), (box, words)
    assert abs(box.center().y() - words.center().y()) <= 2, (box, words)
    # 真画出来了：一块纯底色只有一两种颜色
    image = mark.grab().toImage()
    colors = {image.pixel(x, y) for x in range(image.width()) for y in range(image.height())}
    assert len(colors) >= 4, f"图标那块只有 {len(colors)} 种颜色 —— 没画出来"


# ==================================================== 卡上那行字


@pytest.mark.parametrize("switch_id,attrs,expected", [
    ("kill_sound", {"weapon_kill_sounds": {"a": "甲", "b": "0", "c": "不启用", "d": "乙"}}, "已配 2 把枪"),
    ("kill_voice", {"weapon_kill_voices": {}}, "还没配枪"),
    ("switch_weapon", {"weapon_switch_sounds": {"a": "甲"}}, "已配 1 把枪"),
    ("reload_sound", {"weapon_reload_sounds": None}, "还没配枪"),
    ("gun_sound", {"ak47_style": "甲", "awp_style": "0"}, "已配 1 把枪"),
    ("death_sound", {"death_sound_style": "冰河"}, "风格：冰河"),
    ("death_sound", {"death_sound_style": "0"}, "还没选风格"),
    ("kill_icon", {"kill_icon_style": ""}, "还没选风格"),
    ("crosshair", {"crosshair_size": 3}, "大小 3"),
    ("magnifier", {"magnifier": {"zoom_factor": 2.5, "hotkey": "F"}}, "2.5 倍 · F"),
    ("flash", {"flash_max_opacity": 0.75}, "不透明度 75%"),
    ("music", {"music_playlists": {"默认": ["a", "b"]}, "music_current_playlist": "默认"}, "2 首歌"),
    ("music", {"music_playlists": {}, "music_current_playlist": "默认"}, "列表是空的"),
    ("voice_output", {"voice_output_slots": {"1": {"audio": "x"}, "2": {"audio": ""}}}, "1 段语音"),
    ("voice_output", {"voice_output_slots": {}}, "还没配语音"),
    ("fun_afterlife", {"fun_afterlife_platform": "custom"}, "自定义网址"),
    ("fun_afterlife", {"fun_afterlife_platform": "douyin"}, "抖音"),
    ("utility", {"utility_guide_hotkey": "F6"}, "按 F6 呼出"),
    ("spectator", {}, "观战时不出声"),
])
def test_the_line_on_each_card(switch_id, attrs, expected):
    assert feature_summary(switch_id, SimpleNamespace(**attrs)) == (expected, "")


def test_a_gone_style_outranks_the_usual_line():
    assert feature_summary("kill_sound", SimpleNamespace(weapon_kill_sounds={"a": "甲"}), stale=3) == (
        "3 项风格失效", "warning")


def test_every_field_the_lines_read_is_a_real_config_field():
    """这些字段都带默认值，写错名字不会报错，只会永远显示默认值。"""
    tree = ast.parse((ROOT / "core" / "feature_summary.py").read_text(encoding="utf-8"))
    names = {node.args[1].value for node in ast.walk(tree)
             if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "getattr"
             and isinstance(node.args[1], ast.Constant)}
    assert len(names) >= 10, "解析器瞎了"
    assert not [name for name in names if not hasattr(config, name)]

    from core.feature_summary import WEAPON_TABLES

    assert not [name for name in WEAPON_TABLES.values() if not hasattr(config, name)]


# ==================================================== 状态条


def _status(link="no_game", cfg="ok", error="", dirty=False, audio=None):
    return RuntimeStatus(gsi={"startup_error": error}, audio_health=audio or {"ok": True}, config_dirty=dirty,
                         last_error=error, level="ok", gsi_link=link, gsi_cfg={"status": cfg})


@pytest.mark.parametrize("link", sorted(READINESS_HEADLINE))
def test_every_state_of_the_link_says_what_is_wrong_and_what_to_do(link):
    view = readiness_view(_status(link, error="端口 3000 被占用" if link == "failed" else ""))
    assert view.headline == READINESS_HEADLINE[link]
    if link in ("connected", "no_game"):
        assert view.level == "ok" and not view.detail and not view.needs_setup
    else:
        assert view.level in ("warn", "error") and view.detail
    if link == "failed":
        assert view.level == "error" and "端口 3000 被占用" in view.detail


def test_no_cs2_directory_is_the_next_step():
    view = readiness_view(_status("cfg_missing", "not_configured"))
    assert (view.headline, view.level, view.needs_setup) == (NO_CS2_DIR_HEADLINE, "warn", True)
    assert ("CS2 目录", "未设置") in [check[:2] for check in view.checks]

    # 服务起不来比没选目录要紧，得先说这个
    assert readiness_view(_status("failed", "not_configured", error="x")).level == "error"
    # 已经在收数据就是连上了，目录没记上不耽误，不能喊「还差一步」
    connected = readiness_view(_status("connected", "not_configured"))
    assert (connected.level, connected.needs_setup) == ("ok", False)
    assert connected.headline == READINESS_HEADLINE["connected"]


def test_a_bare_install_is_not_reported_as_broken():
    """批 145 外审：「音频 · 需检查12」开屏就吓人。素材目录没建不是故障。"""
    view = readiness_view(_status(audio={"ok": False, "missing_directories": 12}))
    assert view.level == "ok" and not view.detail
    assert "音频" not in view.headline and all("音频" not in check[0] for check in view.checks)


def test_exclusive_fullscreen_matters_only_when_something_draws_on_the_game():
    quiet = readiness_view(_status(), "exclusive", overlay_on=False)
    assert quiet.level == "ok" and not quiet.detail
    loud = readiness_view(_status(), "exclusive", overlay_on=True)
    assert loud.level == "warn" and loud.detail == EXCLUSIVE_DETAIL
    assert loud.detail.startswith("先去 CS2"), "动作在前、后果在后（RN-429 的语序）"
    assert "盖住" in loud.headline, "大字只说「可以进游戏了」，下面又说先去改，两句打架"
    assert "盖住" in readiness_view(_status("connected"), "exclusive", overlay_on=True).headline
    assert quiet.headline == READINESS_HEADLINE["no_game"]
    for word in REQUIRED_WORDS:
        assert word in loud.detail
    assert ("显示模式", "独占全屏") in [check[:2] for check in loud.checks]

    assert len(readiness_view(_status(), None).checks) == 2, "读不到就不摆，不能当成没问题"
    borderless = readiness_view(_status(), "borderless", overlay_on=True)
    assert borderless.level == "ok" and borderless.checks[-1][2] == "ok"


def test_unsaved_changes_are_said_only_when_nothing_is_more_urgent():
    assert "未保存" in readiness_view(_status(dirty=True)).detail
    assert "未保存" not in readiness_view(_status("silent", dirty=True)).detail


def test_the_guide_is_the_main_button_only_while_there_is_a_step_left(win, qapp):
    """RN-139：主按钮指向还没做的下一步。来回两次：换 objectName 要重新 polish。"""
    button = win.basic_onboarding_btn
    for _ in range(2):
        win._sync_home_readiness(readiness_view(_status("cfg_missing", "not_configured")))
        assert button.objectName() == "primaryButton"
        win._sync_home_readiness(readiness_view(_status()))
        assert button.objectName() == "secondaryButton"
        assert button.isVisibleTo(win.basic_status_card), "入口要一直在"


def test_the_strip_says_the_fix_instead_of_the_count_when_there_is_one(win):
    win._sync_home_readiness(readiness_view(_status("silent")))
    text = win.system_status_label.text()
    assert "重启一次 CS2" in text and "个功能" not in text
    assert win.basic_status_card.headline.text() == READINESS_HEADLINE["silent"]
    win._sync_home_readiness(readiness_view(_status()))
    assert "个功能" in win.system_status_label.text()


def test_a_real_refresh_goes_through_the_whole_chain(win, qapp, monkeypatch):
    """不替换任何状态函数走一遍：名字写错、参数对不上，只有这样才红。"""
    monkeypatch.setenv("CS2C_CS2_DISPLAY_MODE", "exclusive")
    win._refresh_system_status_strip()
    strip = win.basic_status_card
    assert strip.headline.text() and strip.headline.text() != "状态刷新失败", win.system_status_label.text()
    assert strip.checks[2].value_label.text() == "独占全屏"

    monkeypatch.setenv("CS2C_CS2_DISPLAY_MODE", "unknown")
    win._refresh_system_status_strip()
    assert strip.checks[2].isHidden(), "读不到显示模式时那一项还摆着"


def test_the_checks_line_up_under_the_text_at_every_width(win, qapp):
    """批 153：依据固定排在结论下面、和大字左对齐；宽窄来回拉也不换位置（原来按宽窄在一行两行之间跳）。"""
    strip = win.basic_status_card
    win._sync_home_readiness(readiness_view(_status("silent")))
    win.setMinimumSize(860, 480)
    for width in (860, 1280, 860, 1280):
        win.resize(width, 800)
        _settle(qapp, 12)
        first = next(check for check in strip.checks if check.isVisible())
        text_left = strip.headline.mapTo(strip, QPoint(0, 0)).x()
        assert first.mapTo(strip, QPoint(0, 0)).x() == text_left, width
        above = strip.detail_label if strip.detail_label.isVisible() else strip.headline
        assert first.mapTo(strip, QPoint(0, 0)).y() >= above.mapTo(strip, QPoint(0, above.height())).y(), width


# ==================================================== 失效的风格


@pytest.fixture
def audio_root(tmp_path, monkeypatch):
    import core.audio.audio_resource_health as health

    monkeypatch.setattr(health.ResourceManager, "get_app_data_path", staticmethod(lambda _rel: str(tmp_path)))
    monkeypatch.setattr(config, "grenade_sound_styles", {}, raising=False)
    monkeypatch.setattr(config, "weapon_kill_sounds", {}, raising=False)
    monkeypatch.setattr(config, "weapon_kill_voices", {}, raising=False)
    monkeypatch.setattr(config, "weapon_switch_sounds", {}, raising=False)
    monkeypatch.setattr(config, "weapon_reload_sounds", {}, raising=False)
    monkeypatch.setattr(config, "death_sound_style", "0", raising=False)
    from core.audio.special_events import SOUND_EVENTS
    from core.gun_sound_profiles import SUPPORTED_GUN_SOUND_WEAPON_TYPES

    for event in SOUND_EVENTS:
        monkeypatch.setattr(config, event.config_attr, "0", raising=False)
    for gun in SUPPORTED_GUN_SOUND_WEAPON_TYPES:
        monkeypatch.setattr(config, f"{gun}_style", "0", raising=False)
    return tmp_path


def _audio(root, *parts):
    path = root.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF")


def test_stale_styles_are_counted_per_feature_and_the_config_is_left_alone(audio_root, monkeypatch):
    from core.audio.audio_resource_health import count_stale_styles

    _audio(audio_root, "switch_weapons", "weapon_ak47", "在", "a.wav")
    _audio(audio_root, "gun_sounds", "ak47", "在", "a.wav")
    _audio(audio_root, "kill_sounds", "在", "1.wav")
    _audio(audio_root, "death", "在.wav")
    (audio_root / "reload_sounds" / "weapon_ak47" / "空目录").mkdir(parents=True)
    table = {"weapon_ak47": "在", "weapon_awp": "没了", "weapon_m4a1": "0"}
    monkeypatch.setattr(config, "weapon_switch_sounds", dict(table), raising=False)
    monkeypatch.setattr(config, "weapon_reload_sounds", {"weapon_ak47": "空目录"}, raising=False)
    monkeypatch.setattr(config, "weapon_kill_sounds", {"weapon_ak47": "在", "weapon_awp": "没了"}, raising=False)
    monkeypatch.setattr(config, "ak47_style", "在", raising=False)
    monkeypatch.setattr(config, "awp_style", "没了", raising=False)
    monkeypatch.setattr(config, "death_sound_style", "没了", raising=False)
    monkeypatch.setattr(config, "c4_sound_style", "没了", raising=False)
    monkeypatch.setattr(config, "grenade_sound_styles", {"hegrenade": "没了"}, raising=False)

    stale = count_stale_styles()
    assert stale == {"kill_sound": 1, "kill_voice": 0, "switch_weapon": 1, "reload_sound": 1, "gun_sound": 1,
                     "death_sound": 1, "special_sound": 2}
    assert config.weapon_switch_sounds == table, "只数不动（RN-033：回来了还接得上）"
    assert config.awp_style == "没了"

    monkeypatch.setattr(config, "death_sound_style", "在", raising=False)
    assert count_stale_styles()["death_sound"] == 0


def test_a_gone_style_shows_on_the_card_the_strip_and_the_sidebar(win, qapp, monkeypatch):
    import core.audio.audio_resource_health as health

    counts = {"gun_sound": 2}
    monkeypatch.setattr(health, "count_stale_styles", lambda: dict(counts))
    win._sync_home_readiness(readiness_view(_status()))
    win._refresh_home_cards()
    card = win.feature_cards["gun_sound"]
    assert card.meta_label.full_text() == "已关闭", "关着的功能没东西要处理"
    assert win.nav_buttons["gun_sound"].status_dot() == DOT_NONE
    assert "href" not in win.system_status_label.text()

    _click_switch(win.switches["gun_sound"], qapp)
    win._refresh_home_cards()
    assert card.meta_label.full_text() == "2 项风格失效"
    assert card.meta_label.property("tone") == "warning"
    assert win.nav_buttons["gun_sound"].status_dot() == DOT_WARN
    text = win.system_status_label.text()
    assert 'href="gun_sound"' in text and "枪声替换有 2 项风格失效了" in text

    win.system_status_label.linkActivated.emit("gun_sound")
    QTest.qWait(30)
    _settle(qapp)
    assert win._current_page_id == "gun_sound", "那条链接没接上"

    counts.clear()
    win.show_page("basic", animated=False)
    _settle(qapp)
    assert card.meta_label.full_text() == "还没配枪"
    assert card.meta_label.property("tone") == ""
    assert win.nav_buttons["gun_sound"].status_dot() == DOT_ON
    assert "href" not in win.system_status_label.text()


def test_special_sound_has_a_dot_and_a_link_without_a_master_switch(win, qapp, monkeypatch):
    import core.audio.audio_resource_health as health

    monkeypatch.setattr(health, "count_stale_styles", lambda: {"special_sound": 1})
    win._sync_home_readiness(readiness_view(_status()))
    win._refresh_home_cards()
    assert win.nav_buttons["special_sound"].status_dot() == DOT_NONE

    win.show_page("special_sound", animated=False)
    _settle(qapp)
    config.round_sound_enabled = True
    win.pages["special_sound"]._refresh_status_badge()
    assert win.nav_buttons["special_sound"].status_dot() == DOT_WARN, "这一页拨开关，侧栏没跟"
    assert 'href="special_sound"' in win.system_status_label.text() or win._first_stale_feature()[0] == "special_sound"

    config.round_sound_enabled = False
    win.pages["special_sound"]._refresh_status_badge()
    assert win.nav_buttons["special_sound"].status_dot() == DOT_NONE


# ==================================================== 侧栏


def test_the_overview_is_named_and_the_old_name_still_finds_it(win):
    assert win.nav_buttons["basic"].text().strip() == "总览"
    from core.settings_search import search_pages

    for query in ("基础设置", "总览"):
        results = search_pages(query)
        assert results and results[0][0] == "basic", (query, results[:3])


def test_an_expert_page_opened_from_a_link_lights_up_while_it_is_open(win, qapp):
    """批 145 外审：普通模式从链接或搜索进工具页，侧栏没有一项是亮的，看不出人在哪。"""
    button = win.nav_buttons["audio_health"]
    assert button.isHidden()
    for _ in range(2):
        win.show_page("audio_health", animated=False, force=True)
        _settle(qapp)
        assert not button.isHidden() and button.isChecked()
        win.show_page("basic", animated=False)
        _settle(qapp)
        assert button.isHidden(), "离开了还留在侧栏"


def test_the_dot_is_painted_only_when_there_is_one(qapp):
    from widgets.nav_button import NavButton

    button = NavButton(" 甲")
    button.resize(160, 32)
    try:
        def pixel():
            return button.grab().toImage().pixelColor(button.width() - 12, button.height() // 2).rgb()

        empty = pixel()
        repaints = []
        original = button.update
        button.update = lambda *a: (repaints.append(1), original(*a))
        button.set_status_dot(DOT_ON)
        assert pixel() != empty, "点没画上去"
        assert button.toolTip() and button.accessibleDescription()
        button.set_status_dot(DOT_ON)
        assert len(repaints) == 1, "状态条每 15 秒刷一遍，没变不重绘"
        button.set_status_dot(DOT_NONE)
        assert pixel() == empty and not button.toolTip()
    finally:
        button.deleteLater()


# ==================================================== 主音量


@pytest.mark.parametrize("volume,shown", [(0.0, "已静音"), (0.1, "偏低"), (0.5, ""), (1.0, "")])
def test_the_volume_only_speaks_when_it_is_hard_to_hear(win, monkeypatch, volume, shown):
    """默认音量就是 100%：那一头说话，每个新用户一进来都先被提醒一句。"""
    monkeypatch.setattr(config, "volume", volume, raising=False)
    win._refresh_volume_hint()
    label = win.volume_hint_label
    assert label.isHidden() == (not shown)
    assert shown in label.text()
