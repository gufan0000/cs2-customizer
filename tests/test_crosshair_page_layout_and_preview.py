# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""crosshair 页的版面和预览（RN-115 / RN-116 / RN-119，2026-08-19 用户裁定；批 146 改成舞台 + 参数栏）。

三条都是**用户能看见的行为**，所以判据全部落在行为上，不落在"源码里有没有那一行"。

## 为什么不用几何判据

RN-115 的原始证据是几何（完整档视口 546px、样式卡从 y=630 起）。但**几何判据
在测试环境里不可信**：`QT_QPA_PLATFORM=offscreen` 没有真实字体，控件宽高由
文字排出来，`page_fingerprint.py` 自己在字体库为空时就拒绝出具。
⇒ 这里改判**相对顺序**（样式在参数之前、动效在预览下面）——它由布局结构决定，
与字体无关；而"到底有没有落进首屏"由两档像素基线兜底。
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLayout, QScrollArea, QWidget

from config import config
import pages.crosshair_page as crosshair_page_module


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(qapp, monkeypatch):
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_animation", "none")
    p = crosshair_page_module.CrosshairPage()
    yield p
    p.deleteLater()
    qapp.processEvents()


def _widgets_in_layout_order(root: QWidget) -> list[QWidget]:
    """控件，**按它们在版面上的顺序**。

    走布局树而不是 `findChildren`：后者按对象树顺序返回，那与屏幕顺序无关
    （版面顺序恰恰是这几条判据要管的东西）。
    """
    found: list[QWidget] = []

    def descend(w: QWidget):
        # ⚠ 滚动区的内容**不在布局树里**（`setWidget` 不是 `addWidget`）。
        # 第一版忘了这一层，整页扫出来是空的 —— 而"扫出来是空的"会让
        # 顺序判据全绿：空列表里当然不存在"样式排在参数后面"。
        if isinstance(w, QScrollArea) and w.widget() is not None:
            found.append(w.widget())
            descend(w.widget())
        elif w.layout() is not None:
            walk(w.layout())

    def walk(layout: QLayout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget()
            if w is not None:
                found.append(w)
                descend(w)
            elif item.layout() is not None:
                walk(item.layout())

    if root.layout() is not None:
        walk(root.layout())
    return found


# ------------------------------------------------------------ RN-115 / 批 146


def test_style_and_color_come_before_the_numeric_parameters(page):
    """⭐ RN-115：**先让人选准心，再让人调参数。**

    改之前：完整档视口 546px，而「准心样式」卡从 y=630 起 —— 这一页最核心的
    选择在首屏之外。外审两档 10 发都指着这块。
    """
    order = _widgets_in_layout_order(page)
    style = page.style_group.buttons()[0]
    color = page.color_group.buttons()[0]
    assert style in order and color in order and page.size_slider in order
    assert order.index(style) < order.index(page.size_slider), "样式又排到参数后面去了"
    assert order.index(color) < order.index(page.size_slider), "颜色又排到参数后面去了"


def test_the_preview_stays_put_while_the_parameters_scroll(page):
    """批 146：这一页的结构就是这一条：调参数时预览一直在眼前。

    预览要是进了滚动区，矮窗口里一滚参数它就走了，那就回到了改版之前。
    """
    assert page.parameter_scroll.isAncestorOf(page.size_slider), "参数不在那一栏里"
    assert page.parameter_scroll.isAncestorOf(page.draw_button), "绘制准心不在那一栏里"
    assert not page.parameter_scroll.isAncestorOf(page.preview_frame)
    node = page.preview_frame.parentWidget()
    while node is not None and node is not page:
        assert not isinstance(node, QScrollArea), "预览进了滚动区：参数一滚它就不在眼前了"
        node = node.parentWidget()


def test_every_control_still_present(page):
    """空转守卫：上面两条只管位置，删掉一个控件它们照样绿。"""
    panel = page.parameter_scroll.widget()
    for attr in ("size_slider", "thickness_slider", "gap_slider", "outline_slider", "alpha_slider",
                 "dot_checkbox", "custom_color_btn", "animation_combo", "kill_effect_combo",
                 "sharecode_edit", "draw_button", "action_bar"):
        assert panel.isAncestorOf(getattr(page, attr)), f"「{attr}」不在参数栏里"
    assert len(page.style_group.buttons()) == 5
    assert len(page.color_group.buttons()) == 6


def test_the_scene_switch_really_changes_what_is_behind_the_crosshair(page, qapp):
    """亮、暗、烟雾三个底是拿来看准心清不清楚的：换了要真的换。"""
    from PySide6.QtCore import Qt

    page.setAttribute(Qt.WA_DontShowOnScreen, True)
    page.resize(1040, 700)
    page.show()
    qapp.processEvents()
    assert len(page.scene_group.buttons()) == 3
    seen = set()
    for button in page.scene_group.buttons():
        button.click()
        qapp.processEvents()
        image = page.preview_frame.grab().toImage()
        seen.add(image.pixelColor(image.width() // 2, image.height() // 3).rgb())
    assert len(seen) == 3, "三个底色画出来有一样的：切换没有生效"
    page.hide()


def test_scene_is_not_config(page, monkeypatch):
    """换底色只是看一眼，不写配置：它不影响游戏里的准心。"""
    saved = []
    monkeypatch.setattr(config, "save_config", lambda: saved.append(1), raising=False)
    for button in page.scene_group.buttons():
        button.click()
    assert not saved, "换预览底色触发了写配置"


def test_segments_and_swatches_are_clickable_everywhere(page, qapp):
    """分段按钮和色块整块都能点。色块没有文字：没有样式表（极简主题）时默认的点击区只有一个小圈。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from theme_manager import get_theme_manager

    previous = qapp.styleSheet()
    try:
        page.setAttribute(Qt.WA_DontShowOnScreen, True)
        page.resize(1040, 700)
        page.show()
        qapp.processEvents()
        swatch = page.color_group.buttons()[-1]
        QTest.mouseClick(swatch, Qt.LeftButton, Qt.NoModifier, QPoint(2, 2))
        assert swatch.isChecked(), "点色块的边上没反应"
        # ⚠ 分段按钮的内边距是样式表给的：不装上量不到
        qapp.setStyleSheet(get_theme_manager().themes["dark"].generate_stylesheet())
        qapp.processEvents()
        corner = page.style_group.buttons()[-1]
        QTest.mouseClick(corner, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
        assert corner.isChecked(), "点分段按钮的边上没反应"
    finally:
        page.hide()
        qapp.setStyleSheet(previous)


# ------------------------------------------------------------------- RN-116


def test_switching_animation_plays_a_short_preview_then_stops(page, qapp):
    """RN-116：换动画时预览要动一小段，然后**停回静止**。

    用户裁定（2026-08-19）：**不要常驻定时器**——播约 1.5 秒示意就停。
    所以这条判据两头都验：① 切换后确实在跑；② 到点必须停。
    """
    idx = page.animation_combo.findText("脉冲效果")
    assert idx >= 0, "下拉里没有「脉冲效果」，这条判据的前提就不成立"
    page.animation_combo.setCurrentIndex(idx)
    qapp.processEvents()

    assert page.preview_burst_timer.isActive(), (
        "换了动画之后预览没有动起来 —— 玩家仍然是盲选")
    assert page.preview_burst_timer.interval() > 0

    page._stop_preview_burst()          # 模拟"播够了"
    qapp.processEvents()
    assert not page.preview_burst_timer.isActive(), (
        "示意播完没停 —— 这就变成常驻定时器了，用户明确否决了那个方案")


def test_the_burst_is_bounded_in_time(page):
    """空转守卫：示意必须有**时限**，否则上面那条可以靠"永远不停"通过。"""
    assert 0 < page.PREVIEW_BURST_MS <= 4000, (
        f"示意时长 {page.PREVIEW_BURST_MS}ms 不合理（要有限、且别太久）")


def test_the_burst_stops_by_itself_when_time_is_up(page, qapp):
    """⚠ **到点必须自己停** —— 不是等谁来调 `_stop_preview_burst()`。

    这条是回退验证逼出来的：断点把「到点了吗」这个判断改成 `if False`
    （= 永远不停），而上面那条判据**照样绿** —— 因为它是自己动手调 stop 的。
    ⇒ 判据里那句"模拟播够了"，模拟掉的正是要验的东西。
      **凡是判据里出现「模拟」两个字，先问一遍：被模拟掉的是不是被测对象本身？**
    """
    idx = page.animation_combo.findText("脉冲效果")
    page.animation_combo.setCurrentIndex(idx)
    qapp.processEvents()
    assert page.preview_burst_timer.isActive(), "前提不成立：切换之后并没有在播"

    ticks = page.PREVIEW_BURST_MS // max(1, page.preview_burst_timer.interval()) + 2
    for _ in range(ticks):
        page._tick_preview_burst()
    assert not page.preview_burst_timer.isActive(), (
        f"跑满 {ticks} 拍（>{page.PREVIEW_BURST_MS}ms）还在转 —— 它变成常驻定时器了")


def test_leaving_the_page_stops_the_burst(page, qapp):
    """离开页面必须停 —— 不然它就是一个"藏起来的常驻定时器"。

    ⚠ 必须先 `show()` 再 `hide()`：Qt 只给**当前可见**的控件发 hideEvent，
    对一个从没显示过的控件调 hide() 什么都不会发生 —— 那样这条判据验的
    就是"默认没在跑"，而不是"离开会停"。
    `WA_DontShowOnScreen` 保证不真的弹窗（铁律：测试不许打扰前台）。
    """
    from PySide6.QtCore import Qt

    page.setAttribute(Qt.WA_DontShowOnScreen, True)
    page.show()
    qapp.processEvents()
    idx = page.animation_combo.findText("脉冲效果")
    page.animation_combo.setCurrentIndex(idx)
    qapp.processEvents()
    assert page.preview_burst_timer.isActive(), "前提不成立：切换之后并没有在播"
    page.hide()
    qapp.processEvents()
    assert not page.preview_burst_timer.isActive(), (
        "页面都不可见了还在跑定时器")


# ------------------------------------------------------------------- RN-119


def test_import_says_what_it_actually_accepts(page):
    """RN-119：导入入口必须说明**只认本软件导出的文件**。

    玩家手里的准心几乎都是 CS2 官方分享码（`CSGO-xxxxx-…`），
    而导入走 `validate_crosshair_import`，只认本软件的文件。
    不写清楚 = 点了才发现不支持。⭐ 说明挂在那颗按钮上：困惑就发生在那儿（RN-410）。
    """
    text = page.action_bar.extra_btn.toolTip()
    assert page.action_bar.extra_btn.text() == "导入准心"
    assert "json" in text.lower(), f"没说清收什么格式：{text!r}"
    assert "分享" in text or "CSGO-" in text, (
        f"没提 CS2 分享码这件事 —— 那正是玩家会来试的东西：{text!r}")


def test_the_share_code_row_does_what_the_hint_says(page, monkeypatch):
    """批 130 起真做了分享码（以前这里是反面守卫「没做就不许承诺」）。说明里指过去的那一栏
    必须真的能用：粘贴 → 导入 → 配置变；坏码 → 说出来且配置不动；导出 → 剪贴板里的码解得回去。"""
    from PySide6.QtGui import QGuiApplication

    from core import crosshair_sharecode as cs

    for key in ("crosshair_style", "crosshair_color_custom", "crosshair_alpha", "crosshair_thickness",
                "crosshair_gap", "crosshair_size", "crosshair_outline", "crosshair_dot", "crosshair_color"):
        monkeypatch.setattr(config, key, getattr(config, key), raising=False)
    monkeypatch.setattr(page, "_update_crosshair_system", lambda *a, **k: None)
    assert "分享码" in page.action_bar.extra_btn.toolTip()

    page.sharecode_edit.setText("CSGO-hLbCn-69VT6-Bok83-9MOqW-SWzwQ")   # 静态十字 #32FA32 gap4 len8 粗2 @1080
    monkeypatch.setattr(page, "_screen_height_px", lambda: 1080)
    page._import_sharecode()
    assert (config.crosshair_style, config.crosshair_color_custom, config.crosshair_gap,
            config.crosshair_size, config.crosshair_thickness) == ("crosshair", "#32FA32", 4, 24, 2)
    assert page.size_slider.value() == 24 and page.gap_slider.value() == 4, "控件没跟着配置刷新"
    assert "已导入" in page.sharecode_result_label.text()

    page.sharecode_edit.setText("CSGO-12345-12345-12345-12345-12345")
    page._import_sharecode()
    assert "没导入" in page.sharecode_result_label.text()
    assert config.crosshair_color_custom == "#32FA32", "坏码把配置改了"

    page._export_sharecode()
    code = QGuiApplication.clipboard().text()
    assert cs.to_cs2customizer(code, 1080)[0]["crosshair_size"] == 24
