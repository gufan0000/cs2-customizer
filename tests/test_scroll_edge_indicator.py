# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""滚动区要告诉用户「下面还有内容」（RN-120）。

## 缺陷

页面滚动区里有个 `ScrollShadow`，看着像已经把这件事办了。实际上：

  ① **它只画顶部，而且只在 `value > 0` 之后才显示** ——
     也就是**用户已经滚过了**才出现。可玩家要知道的是「下面还有没有」，
     **在他滚动之前**。外审在 crosshair 上 6 发、advanced 上 3/3 票都说
     「缺乏滚动提示、容易漏看」，而指示器一直好端端装在那儿 —— 它答的是另一个问题。
  ② **渐变写死成 `QColor(0, 0, 0, 30)`** —— 深色背景上叠黑色。
     实算九套主题：深色五套合成后对比 **1.000 ~ 1.030**，
     其中纯黑主题（`bg_primary = #000000`）是 **1.000** —— **一个像素都没变**。
  ③ **只连了 `valueChanged`**。页面刚建好时 value 恒为 0，而 `maximum` 是布局
     排完才定的 —— 于是「还没滚动、下面有内容」这个**最要紧的时刻**
     根本不会触发任何一次更新。

⭐ **一个装了却没人受益的提示，跟没装的区别只在于：它会让人以为已经装过了。**

## 而"补一条线"也不够

第一版补完之后截图实测：4px 渐变里**只有一行像素**真的看得出来
（y=713 亮度 33 / 背景 12，上面三行已经衰减到几乎透明）。
而外审 3/3 票抱怨的从来不是"没提示"，是**贴边那行字被齐腰切开** ——
一条细线不但解决不了，反而更像一道裁切线。

⇒ 最终做法：**用背景色做 18px 渐隐带**，让贴边的内容淡出而不是被切断。
颜色取背景色本身，九套主题自动都对。

## 判据

不去比像素（那要真实字体、还随主题走），而是钉住四件可算的事：
**方向对不对**、**信号连没连**、**颜色是不是背景色**、**够不够厚**。
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

from ui_effects import ScrollShadow, install_scroll_shadow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _scroll_area(qapp, content_height: int) -> QScrollArea:
    area = QScrollArea()
    inner = QWidget()
    lab = QLabel("x", inner)
    lab.setFixedSize(200, content_height)
    inner.setFixedSize(200, content_height)
    area.setWidget(inner)
    area.setFixedSize(200, 100)
    area.show()
    qapp.processEvents()
    return area


def _both(area):
    return area._scroll_shadow, area._scroll_shadow_bottom


def test_both_edges_get_an_indicator(qapp):
    """上下两侧都要有 —— 只有顶部那一条等于只回答了没人问的问题。"""
    area = _scroll_area(qapp, 600)
    try:
        install_scroll_shadow(area)
        top, bottom = _both(area)
        assert top._edge == ScrollShadow.EDGE_TOP
        assert bottom._edge == ScrollShadow.EDGE_BOTTOM
    finally:
        area.deleteLater()
        qapp.processEvents()


def test_the_bottom_one_lights_up_before_the_user_scrolls(qapp):
    """**没滚动过、下面有内容** —— 这就是那个最要紧的时刻。"""
    area = _scroll_area(qapp, 600)
    try:
        install_scroll_shadow(area)
        top, bottom = _both(area)
        assert area.verticalScrollBar().value() == 0, "前提：还没滚动"
        assert bottom.is_lit(), (
            "还没滚动、下面明明还有 500px 内容，底部指示却是灭的 —— "
            "玩家没有任何理由知道要往下滚（RN-120）")
        assert not top.is_lit(), "顶上什么都没有，不该亮"
    finally:
        area.deleteLater()
        qapp.processEvents()


def test_scrolling_to_the_end_turns_the_bottom_one_off(qapp):
    """反面守卫：滚到底了就不该再说「下面还有」，否则它变成一条恒亮的装饰。"""
    area = _scroll_area(qapp, 600)
    try:
        install_scroll_shadow(area)
        top, bottom = _both(area)
        bar = area.verticalScrollBar()
        bar.setValue(bar.maximum())
        qapp.processEvents()
        assert not bottom.is_lit(), "已经到底了还在说下面有内容"
        assert top.is_lit(), "滚下来了，上面该有内容了"
    finally:
        area.deleteLater()
        qapp.processEvents()


def test_nothing_lights_up_when_there_is_nothing_to_scroll(qapp):
    """内容装得下的时候两条都得灭 —— 否则每一页都平白多两条线。"""
    area = _scroll_area(qapp, 40)
    try:
        install_scroll_shadow(area)
        top, bottom = _both(area)
        assert not top.is_lit()
        assert not bottom.is_lit()
    finally:
        area.deleteLater()
        qapp.processEvents()


def test_the_range_signal_is_connected(qapp):
    """③ 只连 `valueChanged` 会错过「还没滚动」那一刻。

    直接验行为：**在装好之后**才把内容撑高（value 一直是 0，只有 range 变），
    指示器必须跟上。只连 valueChanged 的话这里一定灭着。
    """
    area = _scroll_area(qapp, 40)
    try:
        install_scroll_shadow(area)
        _top, bottom = _both(area)
        assert not bottom.is_lit(), "前提：一开始装得下"

        inner = area.widget()
        inner.setFixedHeight(800)
        inner.findChild(QLabel).setFixedHeight(800)
        qapp.processEvents()

        assert area.verticalScrollBar().value() == 0, "前提：全程没滚动过"
        assert bottom.is_lit(), (
            "内容长出来了、指示器却没反应 —— range 变化没被监听（RN-120）。"
            "⚠ 这里必须认 is_lit()（paintEvent 卡的状态），不能认 "
            "has_content_beyond()：后者是现算的纯函数，跟信号连没连无关，"
            "第一版就是这么写的，回退验证当场 0/1。")
    finally:
        area.deleteLater()
        qapp.processEvents()


# --------------------------------------------------------------------------
# ② 颜色：**用背景色渐隐**，让贴边的字淡出，而不是被切断
# --------------------------------------------------------------------------


def test_the_mask_fades_into_the_background_in_every_theme(qapp):
    """九套主题逐个走：渐隐带的颜色必须就是该主题的 `bg_primary`。

    ⚠ 这条判据前后改过两次口径，两次都是**实测把我打回来的**：

      ① 一开始它断言"颜色要跟背景拉开对比"。那是在画**一条线** ——
         截图实测 4px 渐变里只有**一行像素**看得出来；
      ② 而外审 3/3 票抱怨的从来不是"没提示"，是**贴边那行字被齐腰切开**。
         一条细线解决不了，反而更像一道裁切线。

    ⇒ 改成向背景渐隐：贴边的字淡出，天然读作"还没完"。
    那么该钉的就变成 **"渐隐带的颜色 == 背景色"** —— 颜色不对的话，
    深色主题上会出现一条浅色横带，比不画还糟。
    """
    from PySide6.QtGui import QColor

    from theme_manager import get_theme_manager

    tm = get_theme_manager()
    names = list(getattr(tm, "themes", {}) or {})
    assert names, "一套主题都枚举不到，这条判据在空转"

    saved = tm.current_theme_name
    checked, bad = 0, []
    try:
        for name in names:
            try:
                tm.set_theme(name)
            except Exception:
                continue
            bg = QColor(tm.current_theme.colors.bg_primary)
            if not bg.isValid():
                continue
            probe = ScrollShadow.__new__(ScrollShadow)   # 只借 _edge_color，不建控件
            fg = ScrollShadow._edge_color(probe)
            checked += 1
            if (fg.red(), fg.green(), fg.blue()) != (bg.red(), bg.green(), bg.blue()):
                bad.append(f"{name}: 背景 {bg.name()} 渐隐带却是 {fg.name()}")
            if fg.alpha() < 200:
                bad.append(f"{name}: 贴边那端只有 alpha {fg.alpha()}，盖不住，字还是被切断的")
    finally:
        tm.set_theme(saved)

    assert checked >= 4, f"只算了 {checked} 套主题，判据在空转"
    assert not bad, (
        "渐隐带的颜色跟背景对不上 —— 那会画出一条横带，比不画更糟：\n  "
        + "\n  ".join(bad))


def test_the_mask_is_tall_enough_to_fade_a_line_of_text(qapp):
    """反面守卫：**高度不够就退化成一条线**，而线正是要避免的东西。

    实测过一次 4px：截图里只有一行像素真的看得出来。
    """
    assert ScrollShadow.THICKNESS >= 12, (
        f"渐隐带只有 {ScrollShadow.THICKNESS}px —— 太薄，会退化成一条细线，"
        "既盖不住贴边那行字，还更像一道裁切线（实测 4px 只剩一行像素可见）。")
