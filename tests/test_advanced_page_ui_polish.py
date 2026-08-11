from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from config import config
import pages.advanced_page as advanced_page_module


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


def _create_valid_cs2_root(tmp_path: Path) -> Path:
    root = tmp_path / "Counter-Strike Global Offensive"
    (root / "game" / "csgo" / "cfg").mkdir(parents=True, exist_ok=True)
    return root


def test_advanced_page_overview_badges_sync(qapp, tmp_path, monkeypatch):
    cs2_root = _create_valid_cs2_root(tmp_path)

    monkeypatch.setattr(config, "csgo_dir", str(cs2_root), raising=False)
    monkeypatch.setattr(config, "debug_mode", False, raising=False)
    monkeypatch.setattr(config, "ui_theme", "dark", raising=False)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(advanced_page_module, "find_cfg_path", lambda: None)

    page = advanced_page_module.AdvancedPage()

    assert page.page_lead_label.objectName() == "pageLeadLabel"
    assert page.summary_label.isHidden() is True
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert len(chips) == 4
    assert any(text == "目录 · 已配置" for text in chips)
    assert any(text == "来源 · 手动设置" for text in chips)
    assert any(text == "调试 · 未启用" for text in chips)
    assert any(text == "主题 · 深色主题" for text in chips)
    assert page.debug_status_label.objectName() == "statusLabel"
    assert "正常使用状态" in page.debug_status_label.text()
    assert str(cs2_root) in page.csgo_dir_text.toolTip()
    assert str(cs2_root) in page.status_card.toolTip()

    page.debug_mode = True
    page._update_debug_status()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "调试 · 已启用" for text in chips)
    assert "已启用调试模式" in page.debug_status_label.text()

    light_index = page.theme_combo.findData("light")
    page._on_theme_changed(light_index)
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "主题 · 浅色主题" for text in chips)

    page._auto_detected = True
    page._sync_overview_status()
    chips = _visible_audio_status_chip_texts(page.status_badge_label)
    assert any(text == "来源 · 自动检测" for text in chips)

    page.deleteLater()
    qapp.processEvents()
