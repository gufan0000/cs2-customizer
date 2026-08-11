# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from config import config
import pages.crosshair_page as crosshair_page_module


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _visible_audio_status_chip_texts(status_bar) -> list[str]:
    layout = status_bar.layout()
    if layout is None:
        return []
    texts: list[str] = []
    for idx in range(layout.count()):
        item = layout.itemAt(idx)
        widget = item.widget() if item else None
        if (
            isinstance(widget, QLabel)
            and widget.objectName() == "audioStatusChip"
            and not widget.isHidden()
        ):
            texts.append(widget.text())
    return texts


def test_crosshair_page_overview_badges_sync(qapp, monkeypatch):
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_enabled", True, raising=False)
    monkeypatch.setattr(config, "crosshair_size", 28, raising=False)
    monkeypatch.setattr(config, "crosshair_thickness", 4, raising=False)
    monkeypatch.setattr(config, "crosshair_color", "yellow", raising=False)
    monkeypatch.setattr(config, "crosshair_style", "circle", raising=False)
    monkeypatch.setattr(config, "crosshair_custom_data", [(14, 15), (15, 15), (16, 15)], raising=False)
    monkeypatch.setattr(config, "crosshair_animation", "pulse", raising=False)
    monkeypatch.setattr(config, "crosshair_kill_effect", "x_flash", raising=False)

    page = crosshair_page_module.CrosshairPage()

    assert page.page_lead_label.objectName() == "pageLeadLabel"
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 6
    assert any(text == "显示 · 已启用" for text in chips)
    assert any(text == "样式 · 圆圈" for text in chips)
    assert any(text == "颜色 · 黄色" for text in chips)
    assert any(text == "大小 · 28 / 4" for text in chips)
    assert any(text == "动效 · 脉冲效果" for text in chips)
    assert any(text == "联动 · X形闪烁" for text in chips)
    assert page.crosshair_summary_label.text() == "圆圈 · 黄色 · 28/4 · X形闪烁 · 脉冲效果"
    assert "击杀联动为“X形闪烁”" in page.crosshair_summary_label.toolTip()
    assert "击杀联动为“X形闪烁”" in page.status_card.toolTip()

    monkeypatch.setattr(config, "crosshair_enabled", False, raising=False)
    page._sync_overview_status()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "显示 · 未启用" for text in chips)
    assert page.crosshair_summary_label.text().startswith("显示关闭 ·")

    page._on_style_changed("custom")
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "样式 · 自定义" for text in chips)
    assert "自定义 3 点" in page.crosshair_summary_label.text()
    assert "已保存 3 个自定义像素点" in page.crosshair_summary_label.toolTip()

    none_index = page.animation_combo.findText("无动画")
    page.animation_combo.setCurrentIndex(none_index)
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "动效 · 无动画" for text in chips)

    page.deleteLater()
    qapp.processEvents()
