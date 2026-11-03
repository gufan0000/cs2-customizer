# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 159：灰字的对比度门槛跟着字重回到 400 一起抬。

批 158 之前，原生平台上全站正文其实按 700 画（RN-787），说明字和禁用字的门槛是在粗笔画上定的。
回到 400 以后细笔画被抗锯齿吃掉一截，外审 3/3 说「不启用」、禁用的「默认」、页头说明偏淡。
门槛写死在这里，不引用产品常量：常量改回去，这里要红。
"""
from __future__ import annotations

import pytest

from core.utils.contrast import contrast_ratio, worst_contrast

MUTED_FLOOR = 5.5
DISABLED_FLOOR = 4.2
SECONDARY_FLOOR = 6.5
TIER_GAP = 0.8


def _themes():
    from theme_manager import get_theme_manager

    # minimal 走系统原生样式，颜色只是占位
    return [(n, t) for n, t in get_theme_manager().themes.items() if n != "minimal"]


@pytest.mark.parametrize("name, theme", _themes())
def test_hint_text_reads_with_thin_strokes(name, theme):
    c = theme.colors
    ratio = worst_contrast(c.text_muted, (c.bg_primary, c.bg_secondary, c.bg_card))
    assert ratio >= MUTED_FLOOR, f"{name} 说明字 {c.text_muted} 只有 {ratio:.2f}:1"


@pytest.mark.parametrize("name, theme", _themes())
def test_disabled_text_reads_on_its_own_background(name, theme):
    """「不启用」、禁用下拉的「默认」、禁用按钮都是这一档；禁用底是 bg_tertiary@90 叠在卡片上。"""
    c = theme.colors
    disabled_bg = theme._blend_hex(c.bg_tertiary, 90, c.bg_card)
    ratio = worst_contrast(c.text_on_disabled, (disabled_bg, c.bg_card))
    assert ratio >= DISABLED_FLOOR, f"{name} 禁用字 {c.text_on_disabled} 只有 {ratio:.2f}:1"


@pytest.mark.parametrize("name, theme", _themes())
def test_the_three_grey_tiers_stay_apart(name, theme):
    """只抬说明字的话，绿 / 紫 / 海洋三套里它会追上次要字，两档就分不开了。"""
    c = theme.colors
    secondary, muted, disabled = (contrast_ratio(getattr(c, t), c.bg_card)
                                  for t in ("text_secondary", "text_muted", "text_on_disabled"))
    assert worst_contrast(c.text_secondary, (c.bg_primary, c.bg_secondary, c.bg_card)) >= SECONDARY_FLOOR
    assert secondary - muted >= TIER_GAP and muted - disabled >= TIER_GAP, (name, secondary, muted, disabled)
