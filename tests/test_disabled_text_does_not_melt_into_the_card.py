# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 155：透明底的禁用字（次要按钮、标签、武器格）不许融进卡片。

原来这几类直接用 `text_disabled`（暗色 #4f5360，压在卡片上 2.3:1），
外审看图说「导出准心」「应用 / 覆盖 / 改名」这些字像融进了卡片。
量的是控件拿到的颜色，不是样式表文本。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_every_theme_derives_a_readable_disabled_text():
    from core.utils.contrast import contrast_ratio
    from theme_manager import ThemeManager

    for name, theme in ThemeManager().themes.items():
        c = theme.colors
        ratio = contrast_ratio(c.text_on_disabled, c.bg_card)
        # 写死数，不读常量：常量改回 3.0 时门槛不能跟着降
        assert ratio >= 3.49, f"{name}: 禁用字在卡片上 {ratio:.2f}"
        # 弱化还得看得出来：和常态次要字拉开
        assert contrast_ratio(c.text_secondary, c.bg_card) - ratio >= 1.5, name


@pytest.mark.parametrize("make", ["secondary", "label", "checkbox"])
def test_a_disabled_control_gets_that_color(qapp, make):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QWidget

    from theme_manager import get_stylesheet, get_theme_manager

    colors = get_theme_manager().current_theme.colors
    host = QWidget()
    host.setStyleSheet(get_stylesheet())
    if make == "secondary":
        widget, role = QPushButton("导出准心", host), QPalette.ButtonText
        widget.setObjectName("secondaryButton")
    elif make == "label":
        widget, role = QLabel("100%", host), QPalette.WindowText
    else:
        widget, role = QCheckBox("显示中心点", host), QPalette.WindowText
    widget.setEnabled(False)
    widget.ensurePolished()
    got = widget.palette().color(QPalette.Disabled, role).name()
    assert got == colors.text_on_disabled.lower(), f"{make} 禁用字是 {got}，不是 text_on_disabled"
