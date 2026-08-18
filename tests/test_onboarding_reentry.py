# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-110（轻档）：三步上手引导必须**回得去**，关于页那句提示必须有落点。

外审报的是「没有首次运行引导」。核实后真相不一样：引导一直都有（P4.1 的
`OnboardingDialog`），但它**一辈子只弹一次**，关掉就再也找不回来 ——
对用户而言「没有引导」和「引导等于没有」是同一件事。

所以这一组钉的是三件事：
1. 关于页那句「请确保已正确选择 CS 文件夹」旁边有真正的入口（原先是句死提示）;
2. 基础设置页有一条能重新打开引导的引导条;
3. 自动弹和手动开**走同一个入口** —— 抄第二份的下场见 RN-002。

⚠ 用例里绝不真的构造 `OnboardingDialog`：它是模态窗，会打扰前台。
   一律打桩之后再点。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _method(name):
    src = (ROOT / "gui_widget.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"gui_widget.py 里找不到 {name}，判据失效了")


def test_auto_popup_and_manual_reopen_share_one_entry_point():
    """`_maybe_show_onboarding` 只负责判断该不该弹，弹本身交给共用入口。

    它自己再 `OnboardingDialog(...)` 一次的话，两条路就会各活各的：
    改了一边（比如加一句日志、换个父窗口）另一边不会报错，只会**悄悄不一样**。
    """
    node = _method("_maybe_show_onboarding")
    calls = [
        n for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_show_onboarding_dialog"
    ]
    assert calls, "`_maybe_show_onboarding` 没有走共用入口 `_show_onboarding_dialog`"

    constructs = [
        n for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "OnboardingDialog"
    ]
    assert not constructs, (
        "`_maybe_show_onboarding` 又自己构造了一次 OnboardingDialog —— "
        "自动弹和手动开就此分家，改一边忘一边不会报错")


def test_opening_the_guide_twice_reuses_the_same_window(qapp):
    """入口有三处（首启自动 / 基础设置页 / 关于页），但窗口只该有一个。

    `self._onboarding_dialog = dialog` 是**唯一**的防 GC 引用 —— 造第二个就会把
    第一个的引用覆盖掉，而第一个还显示在屏幕上。
    （实测这个窗是 ApplicationModal，正常操作开不出第二个；这条判据防的是
    「哪天有人把 modal 去掉」或者「多加一个入口」之后的那一步。）
    """
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        first = win._show_onboarding_dialog()
        qapp.processEvents()
        second = win._show_onboarding_dialog()
        qapp.processEvents()
        assert second is first, "又造了第二个引导窗，第一个的唯一引用被覆盖了"
        assert win._onboarding_dialog is first
    finally:
        dlg = getattr(win, "_onboarding_dialog", None)
        if dlg is not None:
            dlg.close()
        win.close()
        win.deleteLater()
        qapp.processEvents()


def test_about_page_hint_now_has_somewhere_to_go(qapp, monkeypatch):
    """「请确保已正确选择 CS 文件夹」旁边真的能点到引导。"""
    from pages.about_page import AboutPage

    opened = []
    host = QWidget()
    QVBoxLayout(host)
    page = AboutPage()
    host.layout().addWidget(page)
    host._show_onboarding_dialog = lambda: opened.append("guide")

    page_text = "".join(label.text() for label in page.findChildren(QLabel))
    assert "请确保已正确选择 CS 文件夹" in page_text, (
        "那句提示没了。它本身没问题，问题是它原先没有落点 —— "
        "删掉它并不能解决 RN-110，只会让新用户连「要做这件事」都不知道")

    page.goto_onboarding_button.click()
    assert opened == ["guide"], f"关于页的引导按钮没接上，实际调用 {opened}"


def test_about_page_button_says_where_to_go_when_it_cannot_open_the_guide(
        qapp, monkeypatch):
    """拿不到主窗口时**必须说话**，而且要说清替代路径。

    ⚠ 这里断言的是「高级设置」这四个字，不是「有没有弹提示」——
    只断言有反应的话，随便一句兜底话都能让判据变绿（RN-012/017 就是这么假绿的）。
    """
    import ui_toast
    from pages.about_page import AboutPage

    said = []
    monkeypatch.setattr(ui_toast, "toast_warning",
                        lambda msg, *a, **k: said.append(msg))

    page = AboutPage()  # 没有父窗口 ⇒ window() 就是它自己，拿不到那个方法
    page.goto_onboarding_button.click()

    assert said, "引导打不开时一声不吭，用户被扔在原地"
    assert any("高级设置" in m for m in said), (
        f"提示没说清「那到底该去哪儿设目录」，实际说的是 {said}")


def test_basic_page_carries_the_three_step_guide_bar(qapp, monkeypatch):
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        opened = []
        # 先打桩再点：真构造出来是个模态窗，会打扰前台
        monkeypatch.setattr(win, "_show_onboarding_dialog",
                            lambda: opened.append("guide"))

        assert "三步上手" in win.basic_onboarding_hint.text()
        win.basic_onboarding_btn.click()
        assert opened == ["guide"], f"基础设置页的引导按钮没接上，实际调用 {opened}"
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()
