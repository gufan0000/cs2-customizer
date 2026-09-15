# SPDX-License-Identifier: GPL-3.0-or-later
"""⛔ RN-063（批 78）：`flash` 页「效果预览」那一档，**一键那张卡必须排在前面**。

⭐⭐⭐ 立案说的是「卡片看起来是空的」，而成因不是控件缺失，是
**卡头在折线以上、控件在折线以下** —— 那比整张卡都在折线下更糟：
整张卡在折线下，用户只会觉得「还没滚到」；而标题露着、控件不露，
读起来就是「这张卡是空的」。

## 为什么是顺序，而不是别的

紧凑档（860×640）+ 音乐条展开（RN-195：放过一次音乐就永远在，占 127px）
之下，这一档的视口只剩 ~380px。两张卡：
  · 「快速触发」98px  —— 四颗一键按钮，**矮**
  · 「预览控制」146px —— 状态框 + 滑块 + 单选，**高**
矮的排前面，它就整张在折线以上；被切的换成滑块那张，而它即使被切
也露着状态框和按钮 ⇒ 一眼看得出可操作。

外审同一判断题（「有没有哪张卡只看得到标题和说明、看不到任何控件」）：
**改前 3/3 判「有」→ 改后 0/3**；同页三个没碰过的页签**改前改后逐字节相同**
（地板零位移，RN-570/594）。

## ⛔ 这条判据量的是「谁在布局里排前面」，不是源码里谁先写

⭐ 但两者必须一致：焦点链走**构造顺序**（批 38 `tab_order_audit`），
所以修法只能是真的移动那一段，不能只换 `addWidget` 的先后。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _card_titles_in_order(widget) -> list[str]:
    """按**布局顺序**列出这一档里每张卡的标题。"""
    from PySide6.QtWidgets import QLabel

    out = []
    layout = widget.layout()
    if layout is None:
        return out
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w = item.widget() if item else None
        if w is None:
            continue
        labels = [lab.text().strip() for lab in w.findChildren(QLabel)]
        for text in labels:
            if text in ("快速触发", "预览控制"):
                out.append(text)
                break
    return out


def test_the_quick_trigger_card_comes_before_the_preview_controls(qapp):
    from pages.flash_page import FlashPage

    page = FlashPage()
    try:
        from PySide6.QtWidgets import QWidget

        found = None
        for w in page.findChildren(QWidget):
            titles = _card_titles_in_order(w)
            if set(titles) == {"快速触发", "预览控制"}:
                found = titles
                break
        assert found is not None, (
            "分母塌了：在 `flash` 页里找不到同时装着「快速触发」和「预览控制」的那一档 —— "
            "卡片改名了、或者两张卡不再是兄弟，这条判据已经量不到它要量的东西了")
        assert found == ["快速触发", "预览控制"], (
            f"这一档的卡片顺序是 {found} —— 「快速触发」必须排在前面。\n"
            "⇒ 紧凑档 + 音乐条展开时视口只剩 ~380px：高的那张排前面，"
            "矮的那张就只剩标题和说明露在折线以上，读起来像一张空卡（RN-063）。")
    finally:
        page.deleteLater()


def test_the_quick_trigger_blurb_does_not_describe_the_layout(qapp):
    """⛔ RN-077 同族：那句说明**不许提位置**。

    原句写的是「不必先调**上面的**滑块」—— 而本批正好把这张卡挪到了滑块上面去。
    ⭐ **一句描述版面的文案，版面一动它就腐烂**，而它不报错、只是变成假话。
    """
    src = (REPO / "pages" / "flash_page.py").read_text(encoding="utf-8")
    i = src.find('"快速触发"')
    assert i > 0, "分母塌了：`flash_page.py` 里找不到「快速触发」这张卡"
    blurb = src[i:i + 400]
    for word in ("上面的滑块", "下面的滑块", "上方滑块", "下方滑块"):
        assert word not in blurb, (
            f"「快速触发」那句说明里出现了 {word!r} —— 那是在描述版面（RN-077）。\n"
            "⇒ 版面一动它就变成假话，而它不会报错。")
