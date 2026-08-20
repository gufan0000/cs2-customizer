# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""crosshair 页 B 堆三条的判据（RN-114 / RN-115 / RN-116 / RN-119，2026-08-19 用户裁定）。

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
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QLayout, QScrollArea, QWidget,
)

from config import config
import pages.crosshair_page as crosshair_page_module


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(qapp, monkeypatch):
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    p = crosshair_page_module.CrosshairPage()
    yield p
    p.deleteLater()
    qapp.processEvents()


def _card_title(widget: QWidget) -> str:
    """一张卡片的标题 = 它里面第一个 `objectName == "cardTitle"` 的标签。

    ⚠ 判据**不许为了自己好写而要求产品加属性**。这些卡片本来就有标题标签，
    读它即可；给每张卡挂一个 `_card_title` 只是把判据的需求塞进产品代码里。
    """
    if not isinstance(widget, QFrame) or widget.objectName() != "card":
        return ""
    for label in widget.findChildren(QLabel):
        if label.objectName() == "cardTitle":
            return label.text().strip()
    return ""


def _titles_in_layout_order(root: QWidget) -> list[str]:
    """卡片标题，**按它们在版面上从上到下的顺序**。

    走布局树而不是 `findChildren`：后者按对象树顺序返回，那与屏幕顺序无关
    （版面顺序恰恰是这几条判据要管的东西）。
    """
    titles: list[str] = []

    def descend(w: QWidget):
        # ⚠ 滚动区的内容**不在布局树里**（`setWidget` 不是 `addWidget`）。
        # 第一版忘了这一层，整页扫出来是空的 —— 而"扫出来是空的"会让
        # 顺序判据全绿：空列表里当然不存在"样式排在参数后面"。
        if isinstance(w, QScrollArea) and w.widget() is not None:
            inner = w.widget()
            t = _card_title(inner)
            if t:
                titles.append(t)
            if inner.layout() is not None:
                walk(inner.layout())
        elif w.layout() is not None:
            walk(w.layout())

    def walk(layout: QLayout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget()
            if w is not None:
                title = _card_title(w)
                if title:
                    titles.append(title)
                descend(w)
            elif item.layout() is not None:
                walk(item.layout())

    if root.layout() is not None:
        walk(root.layout())
    return titles


def _order_in_scroll(page: QWidget) -> list[str]:
    return _titles_in_layout_order(page)


def _index(titles: list[str], name: str) -> int:
    assert name in titles, f"版面里找不到「{name}」卡片，现有：{titles}"
    return titles.index(name)


# ------------------------------------------------------------ RN-115 / RN-114


def test_style_and_color_come_before_the_numeric_parameters(page):
    """⭐ RN-115：**先让人选准心，再让人调参数。**

    改之前：完整档视口 546px，而「准心样式」卡从 y=630 起 —— 这一页最核心的
    选择在首屏之外；紧凑档视口只有 386px，连「大小与粗细」都被切在中间。
    外审两档 10 发都指着这块，措辞是"被截断/被遮挡"，实测机制是**可滚的首屏之外**。
    """
    titles = _order_in_scroll(page)
    assert _index(titles, "准心样式") < _index(titles, "大小与粗细"), (
        f"「准心样式」又排到参数后面去了：{titles}")
    assert _index(titles, "准心颜色") < _index(titles, "大小与粗细"), (
        f"「准心颜色」又排到参数后面去了：{titles}")


def test_the_left_column_is_not_a_hole_under_the_preview(page):
    """RN-114：预览卡下面那块 455×203 的空洞要被真内容填上。

    机制：预览卡只有 239px 高，而右边那一列 570px —— 差出来的部分在完整档里
    就是左半列一块什么都没有的方块。修法是把「动画效果」「击杀联动」挪进左列。
    """
    preview_col = getattr(page, "preview_column", None)
    assert preview_col is not None, "预览那一列没有留下可检查的引用（preview_column）"
    titles = _titles_in_layout_order(preview_col)
    assert "准心预览" in titles, titles
    assert len(titles) >= 2, (
        f"预览下面又空着了 —— 左列只有 {titles}，那块空洞会回来")


def test_every_card_still_present(page):
    """空转守卫：上面两条只管顺序，删掉一张卡它们照样绿。"""
    titles = _order_in_scroll(page)
    for name in ("准心预览", "大小与粗细", "准心样式", "准心颜色",
                 "动画效果", "击杀联动", "自定义准心"):
        assert name in titles, f"「{name}」卡片不见了：{titles}"


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
    """RN-119：导入入口必须说明**只认本软件导出的 json**。

    玩家手里的准心几乎都是 CS2 官方分享码（`CSGO-xxxxx-…`），
    而导入走 `validate_crosshair_import`，只认本软件的 json。
    不写清楚 = 点了才发现不支持。
    """
    hint = getattr(page, "custom_hint_label", None)
    assert hint is not None, "自定义准心卡片里没有可检查的说明标签"
    text = hint.text()
    assert "json" in text.lower(), f"没说清收什么格式：{text!r}"
    assert "分享" in text or "CSGO-" in text, (
        f"没提 CS2 分享码这件事 —— 那正是玩家会来试的东西：{text!r}")


def test_the_copy_does_not_promise_share_code_support(page):
    """反面守卫：**不许把没做的事写成做了**（RN-042 那一族）。

    如果哪天真做了分享码解码，这条判据会红 —— 那时连同上面一条一起改，
    而不是让文案先跑到实现前面去。
    """
    from core import io_validation

    supports_share_code = any(
        "csgo-" in str(getattr(io_validation, name, "")).lower()
        for name in dir(io_validation) if not name.startswith("__")
    )
    text = page.custom_hint_label.text()
    if not supports_share_code:
        for promise in ("支持分享码", "支持 CS2 分享码", "可直接粘贴分享码"):
            assert promise not in text, (
                f"文案承诺了分享码，而导入链路里没有任何解码实现：{text!r}")
