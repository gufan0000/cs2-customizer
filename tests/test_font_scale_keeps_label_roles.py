# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""放大界面字号后，普通标签不能被认成标题。

判据按档位量：以 110% 启动再切 125% 时，枪声页的 `Glock-18`、`18%` 变成 35px，
数值被截断、枪名被折断（批 143 真窗口实测）。
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from ui_design_system import apply_font_scale
from ui_style_applier import StyleApplier


@pytest.fixture(autouse=True)
def _qt_and_scale():
    QApplication.instance() or QApplication([])
    yield
    apply_font_scale(1.0)


def _styled(text, pixel_size):
    label = QLabel(text)
    font = label.font()
    font.setPixelSize(pixel_size)
    label.setFont(font)
    StyleApplier._style_label(StyleApplier.__new__(StyleApplier), label)
    return label.objectName()


def test_body_sized_labels_stay_labels_at_every_scale():
    for scale, body in [(1.0, 14), (1.1, 15), (1.25, 18)]:
        apply_font_scale(scale)
        assert _styled("Glock-18", body) == "label", scale


def test_a_really_big_label_is_still_a_title():
    for scale in (1.0, 1.1, 1.25):
        apply_font_scale(scale)
        assert _styled("大标题", 28) == "titleLabel", scale
