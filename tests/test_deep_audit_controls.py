# SPDX-License-Identifier: GPL-3.0-or-later
"""真实 Qt 控件的重载、键盘、辅助技术与重置持久化。"""
import json
import threading

import pytest


def test_toggle_keyboard_and_accessible_check_state(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAccessible
    from PySide6.QtTest import QTest
    from ui_toggle_switch import ToggleSwitch
    widget = ToggleSwitch()
    widget.setAccessibleName("测试功能")
    observed = []
    widget.toggled.connect(observed.append)
    try:
        interface = QAccessible.queryAccessibleInterface(widget)
        assert interface.state().checkable and not interface.state().checked
        assert widget.focusPolicy() == Qt.StrongFocus
        QTest.keyClick(widget, Qt.Key_Space)
        assert widget.isChecked() and interface.state().checked
        assert observed == [True]
        widget.setChecked(False, animated=False)
        assert not interface.state().checked and observed == [True]
        widget.setEnabled(False)
        QTest.keyClick(widget, Qt.Key_Space)
        assert not widget.isChecked()
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("alpha", [0, 1, 128, 255])
def test_crosshair_reload_keeps_exact_config_values(qapp, monkeypatch, alpha):
    from config import config
    from pages.crosshair_page import CrosshairPage
    page = CrosshairPage()
    def forbidden_save():
        raise AssertionError("refresh must not write configuration")
    try:
        monkeypatch.setattr(config, "crosshair_alpha", alpha)
        monkeypatch.setattr(config, "crosshair_style", "circle")
        monkeypatch.setattr(config, "crosshair_color", "blue")
        monkeypatch.setattr(config, "save_config", forbidden_save)
        page.load_settings()
        assert config.crosshair_alpha == alpha
        assert page.alpha_slider.value() == alpha * 100 // 255
        assert page.style_group.checkedButton().property("style_value") == "circle"
        assert page.color_group.checkedButton().property("color_value") == "blue"
    finally:
        page.deleteLater()


def test_crosshair_construction_does_not_save_or_quantize_config(qapp, monkeypatch):
    from config import config
    from pages.crosshair_page import CrosshairPage
    writes = []
    monkeypatch.setattr(config, "crosshair_alpha", 128)
    monkeypatch.setattr(config, "crosshair_style", "circle")
    monkeypatch.setattr(config, "save_config", lambda: writes.append(True))
    page = CrosshairPage()
    try:
        assert not writes
        assert config.crosshair_alpha == 128 and config.crosshair_style == "circle"
    finally:
        page.deleteLater()


def test_private_loader_is_included_and_control_signals_are_blocked(qapp):
    from PySide6.QtWidgets import QWidget, QSlider
    from widgets.config_reload import reload_page_settings
    page = QWidget()
    slider = QSlider(page)
    writes = []
    slider.valueChanged.connect(writes.append)
    page._load_settings = lambda: slider.setValue(24)
    assert reload_page_settings(page)
    assert slider.value() == 24 and not writes
    slider.setValue(25)
    assert writes == [25]
    page.deleteLater()


def test_settings_row_labels_control(qapp):
    from PySide6.QtWidgets import QComboBox
    from widgets.settings_row import SettingsRow
    control = QComboBox()
    row = SettingsRow("播放模式", control)
    assert control.accessibleName() == "播放模式"
    assert row.label_widget.buddy() is control
    row.deleteLater()


def test_reset_survives_debounce_and_exit_flush(tmp_path, monkeypatch):
    import config as mod
    cfg = mod.Config.__new__(mod.Config)
    cfg._save_lock = threading.RLock()
    cfg._save_timer = None
    path = tmp_path / "config.json"
    path.write_text('{"crosshair_size": 35}', encoding="utf-8")
    monkeypatch.setattr(mod, "get_config_path", lambda: str(path))
    cfg.reset_for_restart()
    cfg.save_config()
    assert cfg.save_config_now()
    assert cfg.save_config_on_exit(attempts=1)
    assert json.loads(path.read_text()) == {}
    assert cfg._save_timer is None


def test_reset_failure_keeps_original_and_does_not_disable_saving(tmp_path, monkeypatch):
    """分母：直接读取本测试刚创建的单个文件，没有扫描集合。"""
    import config as mod
    from core import io_validation
    cfg = mod.Config.__new__(mod.Config)
    cfg._save_lock = threading.RLock()
    cfg._save_timer = None
    path = tmp_path / "config.json"
    path.write_text('{"original": true}', encoding="utf-8")
    monkeypatch.setattr(mod, "get_config_path", lambda: str(path))
    def fail(*args):
        raise OSError("injected replacement failure")
    monkeypatch.setattr(io_validation, "replace_with_retry", fail)
    with pytest.raises(OSError):
        cfg.reset_for_restart()
    assert not getattr(cfg, "_reset_pending", False)
    assert json.loads(path.read_text()) == {"original": True}
