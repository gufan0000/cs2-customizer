# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""帮助面板的边缘提示器（RN-148）与视口折线（RN-159）。

## RN-148：一块 243px 在视口外的内容，**没有任何边缘提示器**

`ui_help_panel` 自己建了一个 `helpScrollArea`。全站的滚动区靠
`ui_style_applier._style_scrollarea()` 装上下两条边缘提示，
而探针实测它对这一个 **0 次调用** —— 不是被那句 `except Exception: pass`
吞了，是**压根没走到它**（这个面板不在那次遍历的树里）。

⭐ 那句静默的 `except` 是这件事能躺住的原因：
**「装没装上」永远不会有人知道**，因为失败和没走到长得一模一样。

⇒ 修法不是去修遍历，是**让这个面板自己装** ——
一个控件要不要有边缘提示，是它自己的事，不该取决于"有没有人恰好遍历到它"。

## 为什么这份文件里没有 RN-159（视口折线）

同一处「文字被裁切」外审报了三轮 15 发。我这次**实测了折线处的像素**：

    正常内容峰值亮度 233 → 折线那行字峰值 80 → 10px 内衰减到背景 12

⇒ **18px 渐隐带在工作**（那行字只有正常内容 1/3 的亮度，是淡出不是切断），
而 `ScrollShadow.THICKNESS` 的注释显示**上一轮已经为这件事把 4px 提到 18px**。

⇒ 机制已验证有效。再往下只剩一个**结构性**选项（让正文永远不跨折线），
那要动全站每一个滚动区的布局、重锁所有基线 —— 代价与证据不匹配。
⭐ **已验证有效的机制，不该因为它仍被报而再改一次** ——
那是拿票数覆盖原始证据。RN-159 因此留在册上记录测量结果，不在本轮动刀。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from ui_effects import ScrollShadow  # noqa: E402


# ==================================================== RN-148 帮助面板

@pytest.fixture
def help_panel(qapp):
    from ui_help_panel import HelpPanel

    panel = HelpPanel("测试帮助文案 " * 200)
    panel.setAttribute(Qt.WA_DontShowOnScreen, True)
    panel.resize(600, 200)
    panel.show()
    qapp.processEvents()
    yield panel
    panel.deleteLater()
    qapp.processEvents()


def _help_scroll(panel) -> QScrollArea:
    areas = [a for a in panel.findChildren(QScrollArea)
             if a.objectName() == "helpScrollArea"]
    assert len(areas) == 1, f"帮助面板里有 {len(areas)} 个 helpScrollArea"
    return areas[0]


def test_the_help_panel_has_edge_indicators_at_all(help_panel):
    """⭐ RN-148 本体：这块内容一直没有边缘提示器。

    ⚠ 判据盯的是**这个面板自己装上了**，不是"全站遍历会装" ——
    后者正是它躺了这么久的原因：失败和没走到长得一模一样。
    """
    scroll = _help_scroll(help_panel)
    shadows = scroll.findChildren(ScrollShadow)
    assert len(shadows) >= 2, (
        f"帮助面板的滚动区只有 {len(shadows)} 条边缘提示（要上下各一条）——"
        "它有几百 px 内容在视口外，而用户没有任何理由知道还能往下滚")
    edges = {s._edge for s in shadows}
    assert ScrollShadow.EDGE_TOP in edges and ScrollShadow.EDGE_BOTTOM in edges, (
        f"上下两条不齐：{edges}")


def test_the_panel_installs_them_itself_not_via_a_global_sweep():
    """⭐ AST：面板源码里必须**自己**调 `install_scroll_shadow`。

    上面那条行为判据在"全站遍历恰好也装上了"的情况下同样会绿。
    这一条钉的是**责任归属**：一个控件要不要有边缘提示，是它自己的事，
    不该取决于有没有人恰好遍历到它。
    """
    import ast

    src = (REPO / "ui_help_panel.py").read_text(encoding="utf-8")
    called = [n.func.id for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "install_scroll_shadow" in called, (
        "ui_help_panel 没有自己装边缘提示 —— 那它就又回到「靠别人遍历到」的状态了")


def test_the_bottom_indicator_is_lit_when_there_is_more_below(help_panel, qapp):
    """空转守卫 + 本体：内容确实溢出，且底部那条确实亮着。

    ⭐ 少了这条，帮助文案哪天变短（不再溢出）时上面两条依然绿，
    而判据实际上已经不测任何东西了。
    """
    scroll = _help_scroll(help_panel)
    qapp.processEvents()
    bar = scroll.verticalScrollBar()
    assert bar.maximum() > 0, (
        "夹具里的帮助文案没有溢出视口 —— 这条判据在空转，加长文案")
    bottom = next(s for s in scroll.findChildren(ScrollShadow)
                  if s._edge == ScrollShadow.EDGE_BOTTOM)
    assert bottom.is_lit(), "下面还有内容，底部提示却是灭的"
