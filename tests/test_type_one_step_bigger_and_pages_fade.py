# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 160：字整体大一档、卡片顶边一道光、切页旧页淡出。

用户原话：「我希望字能稍微大一点……还有现代化的感觉布局的设计，动画的过渡，性能的优化」。
三件事各钉住一条用户看得见的行为；切页那条还钉住「永远不许变成等待」的时长上限和退出路径。
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget


def test_the_type_ladder_is_one_step_bigger():
    """正文 15、次要 14、提示 13、小节标题 16、页标题 22；按钮跟正文走。"""
    from ui_design_system import ButtonSpec, FontSize

    f = FontSize()
    assert (f.xs, f.sm, f.md, f.lg, f.h1) == (13, 14, 15, 16, 22)
    for role in ("primary", "secondary", "action", "danger"):
        assert getattr(ButtonSpec(), f"{role}_font_size") == f.md, role


@pytest.mark.parametrize("scale", [1.0, 1.1, 1.25])
@pytest.mark.parametrize("selector", ["QTabBar::tab {", "QPushButton#anchorChip {"])
def test_short_rows_still_hold_one_line_of_the_bigger_type(qapp, scale, selector):
    """页签原来写死 20、锚点 chip 写死 20：字大一档后 1.25 倍下一行要 22，审计报「20 需 22」。"""
    import re

    from PySide6.QtGui import QFont, QFontMetrics

    from core.utils.app_fonts import UI_FONT_FAMILY, load_ui_fonts
    from theme_manager import ThemeManager
    from ui_design_system import apply_font_scale, get_design_system

    assert load_ui_fonts()
    apply_font_scale(scale)
    try:
        xs = get_design_system().font_size.xs
        qss = ThemeManager().themes["dark"].generate_stylesheet()
    finally:
        apply_font_scale(1.0)
    block = qss[qss.index(selector):]
    block = block[:block.index("}")]
    floor = int(re.search(r"min-height:\s*(\d+)px", block).group(1))
    ceiling = re.search(r"max-height:\s*(\d+)px", block)
    font = QFont(UI_FONT_FAMILY)
    font.setPixelSize(xs)
    line = QFontMetrics(font).height()
    assert floor >= line, f"{selector} 字号 {scale}：最少 {floor}px，一行字要 {line}px"
    assert ceiling is None or int(ceiling.group(1)) >= floor, f"{selector}：上限比下限还小"


def test_dark_cards_catch_light_on_the_top_edge_only():
    from theme_manager import ThemeManager

    themes = ThemeManager().themes
    dark, light = themes["dark"], themes["light"]
    edge = dark._card_top_edge()
    assert edge != dark.colors.border_secondary
    assert _luma(edge) > _luma(dark.colors.border_secondary)
    assert light._card_top_edge() == light.colors.border_secondary, "浅色主题不加这道光"
    qss = dark.generate_stylesheet()
    card = qss[qss.index("QFrame#card {"):]
    assert f"border-top-color: {edge}" in card[:card.index("}")]


def _luma(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    return sum(int(h[i:i + 2], 16) for i in (0, 2, 4))


@pytest.fixture
def stack(qapp):
    host = QStackedWidget()
    host.resize(400, 300)
    a, b, c = QWidget(), QWidget(), QWidget()
    for w in (a, b, c):
        host.addWidget(w)
    host.show()
    qapp.processEvents()
    yield host, (a, b, c)
    host.deleteLater()
    qapp.processEvents()


def test_the_fade_is_short_and_never_a_wait():
    import ui_transitions

    assert 0 < ui_transitions.FADE_MS <= ui_transitions.FADE_MS_MAX <= 150


def test_offscreen_switches_land_at_once(stack):
    """截图、测试、离屏审计要的是切完就定格的那一帧：这里不许起动画。"""
    from ui_transitions import PageTransitionManager

    host, (a, b, _c) = stack
    pt = PageTransitionManager(host)
    pt.switch_page(b)
    assert host.currentWidget() is b
    assert pt.current_animation is None and not pt.is_animating


def test_the_fade_overlay_lets_clicks_through_and_goes_away(stack, monkeypatch, qapp):
    from PySide6.QtCore import QElapsedTimer, Qt

    from ui_transitions import PageTransitionManager

    host, (a, b, c) = stack
    pt = PageTransitionManager(host)
    monkeypatch.setattr(pt, "_can_animate", lambda: True)
    pt.switch_page(b)
    assert host.currentWidget() is b, "新页立即就位，不等动画"
    first = pt.current_animation
    assert first is not None and pt.is_animating
    overlay = pt._overlay
    assert overlay.isVisible() and overlay.testAttribute(Qt.WA_TransparentForMouseEvents)

    pt.switch_page(c)   # 连续切换：上一段立刻停，以最后一次为准
    assert host.currentWidget() is c
    assert pt.current_animation is not first

    timer = QElapsedTimer()
    timer.start()
    while pt.is_animating and timer.elapsed() < 2000:
        qapp.processEvents()
    assert not pt.is_animating, "动画没在 2 秒内收尾"
    assert not overlay.isVisible() and overlay.pixmap is None, "收尾后覆盖层还挂着旧页快照"


def test_cleanup_stops_a_running_fade(stack, monkeypatch):
    """退出链路调 cleanup：跑到一半的淡出要停干净，不留定时器。"""
    from ui_transitions import PageTransitionManager

    host, (_a, b, _c) = stack
    pt = PageTransitionManager(host)
    monkeypatch.setattr(pt, "_can_animate", lambda: True)
    pt.switch_page(b)
    assert pt.is_animating
    pt.cleanup()
    assert pt.current_animation is None and not pt.is_animating
    assert not pt._overlay.isVisible()


def test_the_crosshair_panel_widens_when_its_content_does(qapp, monkeypatch):
    """栏里内容变宽不会发 StyleChange：只在换主题、换字号时重算栏宽，填进数据后预览会被挤出页面（批 160 审计逮到 18px）。"""
    from config import config
    import pages.crosshair_page as crosshair_page_module

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_animation", "none")
    page = crosshair_page_module.CrosshairPage()
    try:
        page.resize(1100, 700)
        page.show()
        qapp.processEvents()
        wide = QWidget()
        wide.setMinimumWidth(520)
        page.parameter_scroll.widget().layout().addWidget(wide)
        for _ in range(3):
            qapp.processEvents()
        assert page.parameter_scroll.width() >= 520, page.parameter_scroll.width()
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_draw_button_alone_on_its_row_keeps_its_height(qapp, monkeypatch):
    """「绘制准心」独占一行后没有同排按钮撑高度：留着 `fp_short` 的低下限，改后图里被压成 23px（同排的 32）。"""
    from config import config
    import pages.crosshair_page as crosshair_page_module
    from theme_manager import get_theme_manager
    from ui_style_applier import mark_compact_buttons

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_animation", "none")
    page = crosshair_page_module.CrosshairPage()
    try:
        page.setStyleSheet(get_theme_manager().get_stylesheet())
        page.resize(1100, 500)
        page.show()
        qapp.processEvents()
        mark_compact_buttons(page)
        qapp.processEvents()
        assert not page.draw_button.property("fp_short")
        assert page.draw_button.minimumHeight() == page.action_bar.extra_btn.height(), (
            page.draw_button.minimumHeight(), page.action_bar.extra_btn.height())
    finally:
        page.deleteLater()
        qapp.processEvents()


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])
