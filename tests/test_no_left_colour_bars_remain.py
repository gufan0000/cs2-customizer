# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-643（批 96 第三刀）：「左侧 3px 色条」这套语言整体退场。

## 它守的是什么

用户 2026-09-15 实机指着自定闪光页卡片左缘那根灰条：「把这个白色条条去掉，类似的这种很突兀很 AI 的都修一下」。
一查，同一套语言铺在 9 处：masterOff 卡、状态胶囊（4 个等级 + masterOffHost）、helpCard、
infoBox / warningBox、semantic warning / danger 卡、selected 卡。⭐ 批 16 用它替代「闭合轮廓」时是有实测依据的
（RN-103），但那轮的候选 C（纯文字）与胜出的 B 只差 1 票、在 RN-570 的地板之内 —— **票数分不出，分得出的是用户。**

## 怎么验

生成每个主题的样式表，找所有 `border-left: Npx solid <色>` 且 N ≥ 2 的规则：颜色必须等于该主题的 `bg_card`
（占位保留、颜色同底），否则就是一根还在的色条。1px 的分隔线（底栏、表头、分裂按钮）不在此列 —— 那是分隔，不是装饰。
"""
from __future__ import annotations

import re

import pytest

THEMES = ("dark", "light", "green", "purple", "ocean", "warm", "rose", "contrast")


def _rules_with_left_bar(qss: str):
    qss = re.sub(r"/\*.*?\*/", "", qss, flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", qss):
        sel = " ".join(m.group(1).split())
        for width, colour in re.findall(r"border-left:\s*(\d+)px\s+solid\s+(#[0-9a-fA-F]{6}|rgba?\([^)]*\))", m.group(2)):
            if int(width) >= 2:
                out.append((sel, int(width), colour.lower()))
    return out


@pytest.mark.parametrize("theme", THEMES)
def test_every_thick_left_border_is_the_card_colour(theme):
    from theme_manager import get_theme_manager
    t = get_theme_manager().themes[theme]
    bars = [(sel, w, col) for sel, w, col in _rules_with_left_bar(t.generate_stylesheet())
            if col != t.colors.bg_card.lower()]
    assert not bars, f"[{theme}] 还有 {len(bars)} 根左侧色条：{bars[:4]}"


def test_the_denominator_is_not_empty():
    """反面：占位那根 3px（`QFrame#card`）必须还在 —— 分母为 0 时上面那条什么都没查。"""
    from theme_manager import get_theme_manager
    t = get_theme_manager().themes["dark"]
    bars = _rules_with_left_bar(t.generate_stylesheet())
    assert any(sel.startswith("QFrame#card") and w == 3 for sel, w, _ in bars), "卡片那根 3px 占位不见了 —— 卡内子控件的 x 会跳 2px（见 R7/D-03 注释）"
