# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import gc
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLabel

import gui_widget
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _dispose_widgets(app, *widgets):
    """Phase1: 测试创建的无父级 widget 必须在 QApplication 存活期内经
    deleteLater 体面销毁——否则解释器退出阶段由 GC 乱序析构会触发
    原生堆损坏 (0xC0000374)，用例全过但进程崩溃。"""
    for w in widgets:
        try:
            w.deleteLater()
        except RuntimeError:
            pass
    for _ in range(3):
        app.processEvents()
    gc.collect()
    app.processEvents()


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


def test_system_status_strip_render_smoke(qapp, monkeypatch):
    monkeypatch.setattr(
        gui_widget,
        "collect_runtime_status",
        lambda _mw: SimpleNamespace(
            gsi={"running": True},
            audio_health={"ok": True, "missing_directories": 0, "invalid_config_refs": 0},
            config_dirty=False,
            last_error="",
            level="ok",
        ),
    )

    dummy = SimpleNamespace(
        system_status_label=QLabel(),
        basic_status_badge_label=create_badge_label(),
        basic_gsi_badge=QLabel(),
        basic_audio_badge=QLabel(),
        basic_config_badge=QLabel(),
        logger=get_logger("UITestSystemStatus"),
    )
    dummy._set_badge_label_state = (
        lambda label, text, tone="info": gui_widget.MainWindow._set_badge_label_state(dummy, label, text, tone)
    )
    dummy._update_basic_status_summary_label = (
        lambda: gui_widget.MainWindow._update_basic_status_summary_label(dummy)
    )
    gui_widget.MainWindow._refresh_system_status_strip(dummy)
    text = dummy.system_status_label.text()
    assert "联动服务已就绪" in text
    assert dummy.basic_gsi_badge.text() == "GSI · 运行中"
    assert dummy.basic_audio_badge.text() == "音频 · 正常"
    chips = _visible_audio_status_chip_texts(dummy.basic_status_badge_label)
    assert "GSI · 运行中" in chips
    assert "音频 · 正常" in chips

    _dispose_widgets(
        qapp,
        dummy.system_status_label,
        dummy.basic_status_badge_label,
        dummy.basic_gsi_badge,
        dummy.basic_audio_badge,
        dummy.basic_config_badge,
    )


def test_home_player_label_elides_long_id(qapp):
    long_id = "76561198012345678"
    win = type("W", (), {})()
    win.config = SimpleNamespace(player_steamid=long_id)
    win.player_label = QLabel()
    win.player_label.resize(118, 28)
    win._home_player_label_text = (
        lambda player_id=None: gui_widget.MainWindow._home_player_label_text(win, player_id)
    )

    gui_widget.MainWindow._refresh_home_player_label(win)

    assert win.player_label.toolTip() == f"当前玩家ID: {long_id}"
    assert win.player_label.text().startswith("当前")
    assert len(win.player_label.text()) < len(win.player_label.toolTip())

    _dispose_widgets(qapp, win.player_label)
