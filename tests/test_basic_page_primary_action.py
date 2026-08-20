# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""基础设置页那颗紫色主按钮，得指向"还没做的下一步"（RN-139）。

## 缺陷长什么样

首次使用必需的「CS2 目录」被埋在侧栏倒数第二项「高级设置」里，
而这一页最抢眼的那颗紫色主按钮是**「载入音频」** ——
一个装完就已经做过了的动作（音频在启动时就载入过了）。
外审 advanced **6/6 票**、basic **5/6 票**，一致说
"新手会卡在这里 / 第一步就走错"。

⭐ **主按钮该指向"还没做的下一步"，不是"随时可以再做一次的动作"。**
一屏上只有一颗按钮是紫的，那颗紫的就是产品在替用户排序；
排错了的代价不是"少了个入口"，是**用户按着这个排序走了一遍**。

## 分寸

⚠ 别把这条讲成"前十七轮完全没看见"：RN-110 已经在这一页加了引导条和
「打开上手引导」按钮，只是它当时是一颗**普通按钮**，摆在紫色的
「载入音频」旁边。这一轮换的是**视觉主次**，不是补一个不存在的入口。

用户裁定（2026-08-21）：**只换首屏主按钮**，不动导航顺序。
⇒ 所以这份文件里有一条反面守卫盯着"别顺手把「载入音频」也改掉了"：
功能一个都不许动，动的只有"最想让你点哪一颗"。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

#: 这一页允许有几颗主按钮。**1** —— 两颗就等于零颗：
#: "主"是相对的，第二颗紫的一出现，第一颗就不再是"最抢眼的那个"。
MAX_PRIMARY_BUTTONS = 1


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    import gui_widget

    window = gui_widget.MainWindow(auto_background_preload=False)
    window.setAttribute(Qt.WA_DontShowOnScreen, True)   # 铁律：不许弹真窗口
    yield window
    window.close()
    window.deleteLater()
    qapp.processEvents()


def _primary_buttons(page):
    """这一页上 objectName 为 `primaryButton` 的按钮（就是紫色那一档）。"""
    return [b for b in page.findChildren(QPushButton)
            if b.objectName() == "primaryButton" and b.isVisibleTo(page)]


def test_the_only_purple_button_is_the_onboarding_guide(win, qapp):
    """⭐ 这一页唯一的主按钮是「打开上手引导」。"""
    page = win.pages["basic"]
    qapp.processEvents()
    primaries = _primary_buttons(page)
    assert [b.text() for b in primaries] == ["打开上手引导"], (
        f"基础设置页的主按钮是 {[b.text() for b in primaries]} —— "
        f"首次使用要做的是「选 CS2 目录 → 写 GSI → 试听」，"
        f"不是一个装完就已经做过的动作")
    assert primaries[0] is win.basic_onboarding_btn


def test_there_is_exactly_one_primary_button(win, qapp):
    """棘轮：主按钮只许有一颗。

    两颗紫的等于零颗 —— "主"是相对的。这条守的是**下一次**：
    往这一页加东西的人很容易顺手再 `primary=True` 一个。
    """
    page = win.pages["basic"]
    qapp.processEvents()
    primaries = _primary_buttons(page)
    assert len(primaries) <= MAX_PRIMARY_BUTTONS, (
        f"基础设置页有 {len(primaries)} 颗主按钮："
        f"{[b.text() for b in primaries]}。两颗紫的等于零颗。")


def test_reloading_audio_still_works_it_just_is_not_the_headline(qapp, monkeypatch):
    """⭐ 反面守卫：**功能一个都不许动。**

    这一轮只换视觉主次。「载入音频」必须还在、还能点、**还接在原来那条路上** ——
    降级最容易顺手做过头的三件事：顺便隐藏、顺便挪走、顺便把接线也断了。

    ⚠ 打桩必须在**建窗之前**、且打在**类**上：`clicked` 连的是建页那一刻的
    绑定方法，建完再 `monkeypatch.setattr(win, ...)` 是打不进去的 ——
    那样写的判据只能验到"点了不抛异常"，接线断掉照样绿。
    """
    import gui_widget

    called = []
    monkeypatch.setattr(gui_widget.MainWindow, "_reload_audio",
                        lambda self: called.append(1), raising=True)
    window = gui_widget.MainWindow(auto_background_preload=False)
    try:
        window.setAttribute(Qt.WA_DontShowOnScreen, True)
        button = window.home_reload_audio_btn
        assert button.text() == "载入音频"
        assert button.isEnabled()
        assert not button.isHidden(), "顺便把它藏起来了"
        assert button.objectName() != "primaryButton", "它不该再是主按钮了"
        button.click()
        assert called == [1], f"「载入音频」的接线断了，实际调用 {called}"
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_the_guide_button_is_still_wired_to_the_shared_entry(win, monkeypatch):
    """换了外观不许换接线：它还得走共用的那一个引导入口（RN-002 的教训）。"""
    opened = []
    # 先打桩再点：真构造出来是个模态窗，会打扰前台
    monkeypatch.setattr(win, "_show_onboarding_dialog", lambda: opened.append("guide"))
    win.basic_onboarding_btn.click()
    assert opened == ["guide"], f"引导按钮没接上，实际调用 {opened}"


def test_the_guide_button_did_not_grow_to_fill_the_row(win, qapp):
    """RN-110 留下的那条坑：这一行里的按钮会把剩下的空间全吃掉。

    原文记着：`secondaryButton` 的水平策略是 Minimum（**可以长大**），
    只写 addWidget 的话实测被撑到 312px，而 sizeHint 只有 118px ——
    **既不溢出也不截断，排版审计一路绿灯**。换成 `primaryButton` 之后
    这条性质得重新量一次，不能假设它跟着继承。
    """
    win.show()
    qapp.processEvents()
    win.resize(1280, 800)
    for _ in range(4):
        qapp.processEvents()
    button = win.basic_onboarding_btn
    hint = button.sizeHint().width()
    actual = button.width()
    assert actual <= hint + 40, (
        f"「打开上手引导」被撑到 {actual}px，而 sizeHint 只有 {hint}px —— "
        f"AlignRight 那一条在换成主按钮之后失效了")
