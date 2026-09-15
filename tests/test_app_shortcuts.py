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
        # ⭐⭐ 2026-09-06 批 58（RN-025）：分母从 `nav_groups` 换成
        #   `_nav_groups_in_view()` —— 前者**只装静态分组**，不含 `insertWidget(0)`
        #   插进去的「常用」。于是这两条断言一直绿着，而屏幕上**最后一组没有快捷键**：
        #   发了 len(nav_groups)=5 个，而视图里有 6 组。
        #   ⭐ 这条判据当时断言的正是那个有毛病的不变量（「快捷键数 == 静态分组数」）。
        groups = win._nav_groups_in_view()
        expected_alt = {f"Alt+{i + 1}" for i in range(len(groups))}
        assert expected_alt <= seqs, f"有分组没拿到 Alt 快捷键: {expected_alt - seqs}"
        assert len(win._app_shortcuts) == len(groups) + 2
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
        # ⭐ RN-025：第一组是**屏幕上**的第一组，不是 `nav_groups[0]`。
        first_group = win._nav_groups_in_view()[0]
        current_pid = getattr(win, "_current_page_id", None)
        assert current_pid is not None
        assert win._first_page_of_group(first_group) == current_pid, (
            f"Alt+1 落在 {current_pid}，而屏幕上第一组的第一页是 "
            f"{win._first_page_of_group(first_group)}")
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()
