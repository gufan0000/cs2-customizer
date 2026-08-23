# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""说好一行的提示，不许被人偷偷改成折行（RN-121）。

## 缺陷

`crosshair` 标题行右侧那句提示（当时是「显示开关由基础设置统一控制」）**断在「统 / 一」中间**。
实测：它只拿到 **120px**，需要 **156px**，而同一行还空着 **928px**。

机制：**折行的 `QLabel` 在横排布局里会把自己的宽度报小**，布局就照那个窄宽给它。
⭐ **折行往往不是"空间不够"的结果，是"我说我能折行"的结果** ——
所以它躲得过一切"有没有溢出 / 有没有截断"的判据：那些判据眼里它一切正常。

## 为什么光 `setWordWrap(False)` 不管用

`ui_style_applier.fix_text_display()` 会在页面构造**之后**给每个 QLabel
无条件 `setWordWrap(True)`，把调用方的意图整个冲掉，而且**悄无声息**。

⚠ 我一开始是靠读代码推断"那行对这个标签无效"的（它上面有一条按 objectName
跳过的规则）—— **推错了**：那条规则在 `_apply_widget_style` 上，不在
`fix_text_display` 上。最后是**给 `QLabel.setWordWrap` 打桩、跑一遍真页面**
才看清谁在改它。
⭐ **"读代码觉得不会发生"和"跑一遍确认没发生"是两回事。**

而这件事和它正上方 UP-018 的注释是**同一个教训**（那条修的是尺寸：
「调用方明确表达过意图就该赢」），只是当时没顺手看一眼隔壁分支。

## 判据

不比像素（那要真实字体、还随主题和字号变），只钉**行为**：
这些标签在**页面完全建好之后**必须仍然是不折行的。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from ui_style_applier import StyleApplier

#: 明确声明过"我是一行"的提示：(建法, 认它的那段文字)
#: 加条目请连同**为什么它必须是一行**一起说清楚。
SINGLE_LINE_HINTS = (
    # ⚠ 2026-08-21（RN-163）：crosshair 那条原文是「显示开关由基础设置统一控制」——
    # 总开关搬进本页之后那句话变成假的了，改成了「调完直接进游戏看效果」。
    #
    # ⚠⚠ 2026-08-23（RN-174·批 10）：**那一格已删** —— 那条小字本身被删掉了。
    # 它和页头描述在说同一件事，而且犯同一个错（总开关关着时"直接进游戏就看到"
    # 是假的）；外审同一轮也报「顶部/卡片/底栏三处重复堆叠」。
    # ⭐ **控件没了，判据里那一格必须跟着删，不许留着空转** ——
    #   一条指着不存在的控件的判据，跑一万次也永远是绿的
    #   （同 RN-093「判据的锚点会随产品代码一起腐烂」）。
    # ⚠ 删了之后这张表只剩 1 条，所以下面加了一条**分母守卫**：
    #   表空掉时整条判据会静默地什么都不测。
    ("kill_icon", "还没有任何风格",
     "空状态引导，横排里独占一行；折行时它只拿到 232px 而同排空着 700 多 px"),
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _build(page_id, qapp):
    """按产品的真实路径建页 —— 必须包含 `fix_text_display` 那一步。

    只 `PageClass()` 是不够的：把 wordWrap 改回去的是**构造之后**那一步，
    判据要是绕过它，就正好绕过了要防的东西。
    """
    from ui_style_applier import get_style_applier

    if page_id == "crosshair":
        from pages.crosshair_page import CrosshairPage
        page = CrosshairPage()
    elif page_id == "kill_icon":
        from widgets.kill_icon_style_strip import KillIconStyleStrip
        page = KillIconStyleStrip()
    else:
        raise AssertionError(f"没有这一页的建法: {page_id}")
    page.setAttribute(Qt.WA_DontShowOnScreen, True)
    # 产品在 gui_widget 里对每个新建页面调 apply_unified_styles；
    # 而把 wordWrap 改回去的是 fix_text_display，走 apply_complete_system 那条。
    get_style_applier().apply_complete_system(page)
    qapp.processEvents()
    return page


@pytest.mark.parametrize("page_id,needle,why", SINGLE_LINE_HINTS)
def test_the_hint_is_still_one_line_after_the_page_is_fully_built(
        qapp, page_id, needle, why):
    page = _build(page_id, qapp)
    try:
        labels = [lb for lb in page.findChildren(QLabel) if needle in lb.text()]
        assert labels, (
            f"在 {page_id} 上找不到含「{needle}」的标签 —— 判据在空转。"
            "文案改了就把这里一起改，别让它静默失效。")
        for lb in labels:
            assert not lb.wordWrap(), (
                f"{page_id} 的这条提示又变成折行了：{lb.text()[:40]}\n"
                f"它必须是一行，因为：{why}\n"
                "⚠ 光 `setWordWrap(False)` 挡不住 —— `fix_text_display()` 会在页面"
                "构造之后无条件改回 True。要走 `ui_style_applier.keep_single_line()`。")
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_opt_out_marker_is_what_actually_holds(qapp):
    """正面钉住豁免机制本身 —— 不然上一条可能是靠别的原因侥幸绿的。"""
    lb = QLabel("随便一句挺长的提示文字，长到足以让人想给它开换行")
    lb.setWordWrap(False)
    get = __import__("ui_style_applier").get_style_applier()

    get.fix_text_display(lb)
    assert lb.wordWrap() is True, (
        "没打标记的标签居然没被开启换行 —— 那说明 `fix_text_display` 已经不做这件事了，"
        "上一条判据也就跟着失去意义，两边要一起看。")

    from ui_style_applier import keep_single_line

    lb2 = QLabel("同一句话，但这次打了标记")
    keep_single_line(lb2)
    get.fix_text_display(lb2)
    assert lb2.wordWrap() is False, "打了 keep_single_line 还是被改成折行了"
    assert lb2.property(StyleApplier.KEEP_WRAP_PROPERTY) is True


def test_the_table_is_not_empty():
    """分母守卫：这张表空掉时，上面那条参数化判据会**一个用例都不跑**。

    ⚠ 而 pytest 对「参数化了零个用例」是**静默通过**的 —— 报告上看不出区别。
    RN-174 那一轮删掉 crosshair 那一格时，表从 2 条掉到 1 条；
    再删一条就归零，而不会有任何东西提醒。
    ⭐ **一条会随产品一起缩小的清单，必须有人盯着它的下界。**
    """
    assert len(SINGLE_LINE_HINTS) >= 1, (
        "单行提示表空了 —— 上面那条判据现在什么都不测，"
        "而它看起来仍然是绿的")
    for page_id, text, why in SINGLE_LINE_HINTS:
        assert page_id and text and why, f"表里有一格没填全：{(page_id, text, why)}"
