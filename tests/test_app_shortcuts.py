# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R1-3 应用内快捷键:注册数量与目标绑定(离屏,不真实弹窗)。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_window(app):
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    return win


def test_shortcuts_registered(app):
    win = _make_window(app)
    try:
        # 每个侧栏分组一个 Alt+N,外加 F1 与 Esc
        assert hasattr(win, "_app_shortcuts")
        seqs = {sc.key().toString() for sc in win._app_shortcuts}
        # ⚠ 断言「每个分组都有」而不是断言个数:上限原先写死 4,恰好等于当时的分组数,
        # RN-108 加了一组之后最后一组悄悄没了快捷键,而写死 4 的判据照样绿。
        expected_alt = {f"Alt+{i + 1}" for i in range(len(win.nav_groups))}
        assert expected_alt <= seqs, f"有分组没拿到 Alt 快捷键: {expected_alt - seqs}"
        assert len(win._app_shortcuts) == len(win.nav_groups) + 2
        # Alt 而非 Ctrl:避免与音板槽位的 ctrl+数字全局热键双触发
        assert "Ctrl+1" not in seqs
        assert "F1" in seqs
        assert "Esc" in seqs
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_goto_nav_group_switches_page(app):
    win = _make_window(app)
    try:
        win._goto_nav_group(0)
        first_group = win.nav_groups[0]
        current_pid = None
        for pid, btn in win.nav_buttons.items():
            if btn.isChecked():
                current_pid = pid
                break
        assert current_pid is not None
        assert win._page_to_group[current_pid] is first_group
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()
