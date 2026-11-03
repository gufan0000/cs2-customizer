# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 159（RN-786）：侧栏组头的最小高度要装得下一行字，不能靠 sizeHint 撑。

原来写死 `min-height: 16px`，三档字号下这套字一行要 17 / 18 / 21。sizeHint 跟上字号时看不出来，
CI 上偶尔没跟上，排版审计就报「可用高 16 需 18」，时红时绿。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("scale", [1.0, 1.1, 1.25])
def test_the_group_header_floor_holds_one_line_at_every_scale(qapp, scale):
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
    block = qss[qss.index("QPushButton#navGroupHeader {"):]
    floor = int(re.search(r"min-height:\s*(\d+)px", block[:block.index("}")]).group(1))
    font = QFont(UI_FONT_FAMILY)
    font.setPixelSize(xs)
    font.setWeight(QFont.Medium)
    line = QFontMetrics(font).height()
    assert floor >= line, f"字号 {scale}：组头最少 {floor}px，一行字要 {line}px"


def test_the_line_height_constant_matches_the_font_generator():
    """行高常量是从生成脚本的上下伸抄来的：那边改了，这边不跟，组头又会差一两个像素。"""
    from core.utils.app_fonts import UI_FONT_LINE_EM

    tree = ast.parse((REPO / "build_tools" / "make_ui_fonts.py").read_text(encoding="utf-8"))
    ascent, descent = next(ast.literal_eval(node.value) for node in tree.body
                           if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Tuple)
                           and [t.id for t in node.targets[0].elts] == ["ASCENT", "DESCENT"])
    assert UI_FONT_LINE_EM == pytest.approx((ascent + descent) / 1000)
