from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QComboBox, QLabel, QWidget, QHBoxLayout

import gui_widget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _Cfg:
    def __init__(self):
        self.ui_expert_mode = True
        self.saved = 0

    def save_config(self):
        self.saved += 1


def test_expert_mode_visibility_smoke(qapp):
    cfg = _Cfg()
    win = type("W", (), {})()
    win.config = cfg
    win._expert_only_pages = {"audio_health", "audio_replay"}
    win.nav_buttons = {
        "audio_health": QPushButton(),
        "audio_replay": QPushButton(),
        "basic": QPushButton(),
    }
    win.system_status_health_btn = QPushButton()
    win.system_status_open_health_btn = QPushButton()
    win.audio_task_panel_quick_btn = QPushButton()
    win.home_primary_tools_row = QWidget()
    QHBoxLayout(win.home_primary_tools_row).addWidget(QPushButton())
    win.home_expert_tools_row = QWidget()
    expert_row_layout = QHBoxLayout(win.home_expert_tools_row)
    expert_row_layout.addWidget(win.system_status_health_btn)
    expert_row_layout.addWidget(win.system_status_open_health_btn)
    expert_row_layout.addWidget(win.audio_task_panel_quick_btn)
    win._sync_home_tool_rows = lambda: gui_widget.MainWindow._sync_home_tool_rows(win)

    gui_widget.MainWindow._apply_expert_mode_visibility(win)
    assert win.nav_buttons["audio_health"].isVisible()
    assert win.home_expert_tools_row.isVisible()

    cfg.ui_expert_mode = False
    gui_widget.MainWindow._apply_expert_mode_visibility(win)
    assert not win.nav_buttons["audio_health"].isVisible()
    assert not win.system_status_health_btn.isVisible()
    assert not win.home_expert_tools_row.isVisible()


def test_ui_mode_change_updates_config(qapp):
    cfg = _Cfg()
    win = type("W", (), {})()
    win.config = cfg
    win._expert_only_pages = set()
    win.nav_buttons = {}
    win.pages = {}
    win.content_stack = type("S", (), {"currentWidget": lambda self: None})()
    win.ui_mode_combo = QComboBox()
    win.ui_mode_combo.addItem("专家", True)
    win.ui_mode_combo.addItem("新手", False)
    win.ui_mode_combo.setCurrentIndex(1)
    win._apply_expert_mode_visibility = lambda: None
    win.show_page = lambda *_args, **_kwargs: None

    gui_widget.MainWindow._on_ui_mode_changed(win, 1)
    assert cfg.ui_expert_mode is False
    assert cfg.saved == 1


def test_home_switch_target_page_mapping():
    assert gui_widget.MainWindow._get_home_switch_target_page("kill_sound") == "kill_sound"
    assert gui_widget.MainWindow._get_home_switch_target_page("dynamic_hud") == "hud_color"
    assert gui_widget.MainWindow._get_home_switch_target_page("spectator") is None


def test_home_switch_label_click_navigates_to_target_page(qapp):
    calls: list[str] = []
    win = type("W", (), {})()
    win._page_names = {"kill_sound": "击杀音效"}
    win.show_page = lambda pid: calls.append(pid)

    label = gui_widget.MainWindow._create_home_switch_label(win, "kill_sound", "击杀音效")

    assert isinstance(label, gui_widget.ClickableLabel)
    label.clicked.emit()
    assert calls == ["kill_sound"]


def test_home_switch_label_without_target_stays_plain_label(qapp):
    win = type("W", (), {})()
    win._page_names = {}
    win.show_page = lambda *_args, **_kwargs: None

    label = gui_widget.MainWindow._create_home_switch_label(win, "spectator", "观战静音")

    assert isinstance(label, QLabel)
    assert not isinstance(label, gui_widget.ClickableLabel)
