# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""风格库空着的时候，那句写好的引导必须**真的显示出来**（RN-124）。

## 缺陷长什么样

全新用户第一次打开「击杀图标」页：风格库里只有一张「＋ 导入」卡，右边一大片
纯黑，**没有任何文字说明该干什么**。而代码里写着一句正对这个情况的引导：

    self.empty_label = QLabel("还没有任何风格，点右边的「＋ 导入」装一套。")

它从来没显示过。

## 根因：一句"没变化就早退"，把"初始状态"当成了"没变化"

    self._order = []                     # 初始值
    ...
    def set_styles(self, styles, ...):
        if styles == self._order:        # 全新用户：[] == []
            self.set_selected(...)
            return                       # ← 直接走了
        ...
        self.empty_label.setVisible(not styles)   # ← 永远到不了这里

⭐ **这条引导唯一存在的理由，正好是它唯一到不了的那个分支。**
同族的还有 RN-009（建出来就 `hide()` 的 `summary_label`）：
**「写了但显示不出来」和「没写」对用户完全等价，而对代码审查完全不等价** ——
读代码的人看到那句文案，会以为这个情况已经处理过了。

⇒ 可复用的问法：**「没变化就早退」这类优化，第一次调用算不算"有变化"？**
   初始状态恰恰是最需要处理的那一次。

## 这条缺陷是怎么被逮到的

外审 3 发说「风格库没有任何内置图标，新手卡住」。我第一反应是假阳性 ——
我自己机器上装着 5 套风格，探针跑出来卡片渲染得好好的。
**差别在于配置**：截图脚本跑的是隔离的**全新用户配置**，而我的探针读到了我自己的库。
⇒ ⭐ **"我这儿是好的"从来不是证据，除非先说清楚"我这儿"是哪一种用户。**
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from widgets.kill_icon_style_strip import KillIconStyleStrip


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def strip(qapp):
    w = KillIconStyleStrip()
    w.setAttribute(Qt.WA_DontShowOnScreen, True)   # 铁律：测试不许弹真窗口
    w.show()
    qapp.processEvents()
    yield w
    w.deleteLater()
    qapp.processEvents()


def test_a_brand_new_strip_that_gets_no_styles_shows_the_hint(strip, qapp):
    """⭐ 全新用户那一路：第一次就拿到空列表，引导必须出来。"""
    strip.set_styles([])
    qapp.processEvents()
    assert strip.empty_label.isVisible(), (
        "风格库空着却不显示引导 —— 全新用户看到的是一片纯黑，"
        "而那句「还没有任何风格…」就写在代码里，只是没人显示它")


def test_the_hint_goes_away_once_a_style_exists(strip, qapp):
    """反面守卫：有风格了就不许再喊空 —— 否则上面那条可以靠"一直显示"通过。"""
    strip.set_styles([])
    qapp.processEvents()
    strip.set_styles(["默认"])
    qapp.processEvents()
    assert not strip.empty_label.isVisible(), "已经有风格了还在喊「还没有任何风格」"
    assert "默认" in strip.cards


def test_going_back_to_empty_shows_it_again(strip, qapp):
    """删光之后要能再喊一次（这条路本来就是通的，钉住别改坏）。"""
    strip.set_styles(["默认"])
    qapp.processEvents()
    strip.set_styles([])
    qapp.processEvents()
    assert strip.empty_label.isVisible()


def test_the_early_return_still_saves_work_when_nothing_changed(strip, qapp):
    """修法不许把「没变化就早退」整条拆掉 —— 那会让缩略图每次重建。

    ⚠ 这条是防"矫枉过正"：`set_styles` 的注释写着"已经在的卡不重建——
    重建会把已装好的缩略图一起丢掉"。修 RN-124 时要保住这个性质。
    """
    strip.set_styles(["默认", "神威天绫"])
    qapp.processEvents()
    first = strip.cards["默认"]
    strip.set_styles(["默认", "神威天绫"])
    qapp.processEvents()
    assert strip.cards["默认"] is first, "同一份列表又重建了一遍卡片，缩略图会被丢掉"
