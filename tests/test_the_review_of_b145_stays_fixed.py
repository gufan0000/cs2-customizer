# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 145 外审 S3 查出来、批 146 顺手修的小问题，别的判据都钉不到。"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from config import config
from theme_manager import get_theme_manager


def _themes() -> list[str]:
    return [name for name in get_theme_manager().themes if name != "minimal"]


@pytest.mark.parametrize("theme_name", _themes())
def test_the_spin_box_buttons_show_an_arrow(theme_name):
    """原来是两块叠在一起的深色圆角块，里面没有箭头，看不出是按钮。"""
    sheet = get_theme_manager().themes[theme_name].generate_stylesheet()
    for part in ("up", "down"):
        rule = sheet.split(f"QSpinBox::{part}-arrow, QDoubleSpinBox::{part}-arrow {{", 1)[1].split("}", 1)[0]
        assert "image: url(" in rule, f"{theme_name}：数值框的{part}箭头没有图"


def test_the_microphone_label_stays_next_to_its_combo(qapp, monkeypatch):
    """下拉有 `max-width`，多出来的宽度不能分给旁边的标签：字和下拉隔开一大段就看不出是一行。"""
    from pages.voice_output_page import VoiceOutputPage
    from widgets.settings_row import PLAIN_LABEL_WIDTH

    monkeypatch.setenv("CS2C_NO_GLOBAL_HOTKEYS", "1")
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    previous = qapp.styleSheet()
    qapp.setStyleSheet(get_theme_manager().themes["dark"].generate_stylesheet())
    page = VoiceOutputPage()
    try:
        page.setAttribute(Qt.WA_DontShowOnScreen, True)
        page.resize(1040, 720)
        page.show()
        for _ in range(6):
            qapp.processEvents()
        row = page.mic_combo.parentWidget()
        label = next(w for w in row.findChildren(QLabel) if w.text().startswith("麦克风"))
        # 批 150：标签列定宽 120，和上面几行的控件对齐；隔得比这一列还远才算撑开
        gap = page.mic_combo.x() - (label.x() + label.fontMetrics().horizontalAdvance(label.text()))
        assert gap <= PLAIN_LABEL_WIDTH, f"「麦克风」和它的下拉隔了 {gap}px"
    finally:
        page.hide()
        page.deleteLater()
        qapp.processEvents()
        qapp.setStyleSheet(previous)
