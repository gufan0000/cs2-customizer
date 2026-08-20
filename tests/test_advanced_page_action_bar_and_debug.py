# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""advanced 页两条 B 堆的判据（RN-132 / RN-133，2026-08-20 用户裁定）。

## RN-132：没有主路径动作时，就不要造一个出来

目录配好之后，底栏**唯一的紫色主按钮**是「备份设置」——一个低频动作。
而这一页的设置**改完立即生效**，根本没有"保存"这一步。
于是全页最抢眼的那个按钮，指向的是玩家最不需要按的东西；
外审两档 4 发都在说「新手会把它当成保存/生效去点」。

⇒ 跨页主题 RN-101 的标准样本。**这一页的修法是：不设主按钮。**

## RN-133：一个密码框摆在主区域，读起来像"软件没激活"

「内部调试」卡片带一个 `QLineEdit(EchoMode.Password)`，外审 5 发（两档都有）
说它让人以为"需要密码才能用"。它实际只在排查问题时用 ——
收进已有的**专家模式**（软件里本来就有这个开关，另外六个页面已经在用）。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from config import config
import pages.advanced_page as page_module


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    """这一页有 **29 处** QMessageBox（含重置确认），不拦会把 pytest 卡死。"""
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0), raising=False)


def _make_page(monkeypatch, *, expert: bool, dir_valid: bool):
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "ui_expert_mode", expert, raising=False)
    monkeypatch.setattr(page_module.AdvancedPage, "_is_valid_csgo_dir",
                        lambda self, d: dir_valid, raising=False)
    page = page_module.AdvancedPage()
    page.setAttribute(Qt.WA_DontShowOnScreen, True)
    return page


# ------------------------------------------------------------------- RN-132


def test_no_primary_button_once_the_directory_is_set(qapp, monkeypatch):
    """目录已配好 ⇒ 底栏不许再高亮任何东西。"""
    page = _make_page(monkeypatch, expert=False, dir_valid=True)
    try:
        primary = page.action_bar.primary_btn
        # ⚠ 不能用 `isVisible()`：页面没 show 过时它**恒为假**，那条断言等于没断
        # （第一版就是这么写的，当场假绿）。`isVisibleTo(page)` 问的是
        # "假如这一页显示出来，它会不会露面" —— 那才是要验的东西。
        assert not primary.isVisibleTo(page), (
            f"底栏又出现了主按钮「{primary.text()}」—— 这一页没有主路径动作，"
            "最抢眼的位置指向低频操作只会招来误点")
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_retry_button_stays_when_the_directory_is_missing(qapp, monkeypatch):
    """反面守卫：**目录没配好时那个主按钮必须还在。**

    那种情况下「重试自动检测」确实是主路径动作 —— 这条判据防的是
    "为了让上面那条变绿，把主按钮整个删掉"。
    """
    page = _make_page(monkeypatch, expert=False, dir_valid=False)
    try:
        primary = page.action_bar.primary_btn
        assert primary.text().strip(), "目录没配好时反而没有下一步动作了"
        assert "检测" in primary.text(), primary.text()
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_backup_is_still_reachable(qapp, monkeypatch):
    """空转守卫：拿掉主按钮不等于拿掉功能 —— 备份必须还在卡片里。"""
    page = _make_page(monkeypatch, expert=False, dir_valid=True)
    try:
        from PySide6.QtWidgets import QPushButton

        texts = [b.text().strip() for b in page.findChildren(QPushButton)]
        assert any("备份" in t for t in texts), f"备份功能整个不见了：{texts}"
    finally:
        page.deleteLater()
        qapp.processEvents()


# ------------------------------------------------------------------- RN-133


def test_the_debug_card_is_hidden_for_normal_users(qapp, monkeypatch):
    """非专家模式下，整张调试卡片不许出现在页面上。

    ⚠ 判的是**卡片**，不是"那个密码框"。第一版按密码框写，在开源版里当场红了：
    那边**没有密码框**（源码公开之后口令校验没有意义，见该仓库同一处的说明）。
    ⇒ 判据要落在**这条裁定说的那件事**上（排错入口不该占主区域），
      而不是落在它在某一个仓库里的具体长相上。
    """
    page = _make_page(monkeypatch, expert=False, dir_valid=True)
    try:
        assert not page._debug_panel.isVisibleTo(page), (
            "普通模式下还能看到「内部调试」卡片 —— 排错入口占着主区域")
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_debug_card_is_there_in_expert_mode(qapp, monkeypatch):
    """反面守卫：**专家模式下必须还在** —— 否则这条修法等于删功能。"""
    page = _make_page(monkeypatch, expert=True, dir_valid=True)
    try:
        assert page._debug_panel.isVisibleTo(page), (
            "专家模式下调试入口也没了 —— 排查问题时进不去")
    finally:
        page.deleteLater()
        qapp.processEvents()


# ------------------------------------------------------------------- RN-138


def _anchor_texts(page, qapp) -> list[str]:
    """锚点 chip 是 `singleShot(0)` 建的，要转一次事件循环才拿得到。"""
    from PySide6.QtWidgets import QPushButton

    qapp.processEvents()
    return [b.text().strip() for b in page.findChildren(QPushButton)
            if b.objectName() == "anchorChip"]


def test_a_hidden_card_gets_no_anchor_chip(qapp, monkeypatch):
    """普通模式下不许有指向「内部调试」的锚点。

    RN-138：RN-133 把卡片藏了，锚点条却照样按标题扫出一颗「调试」——
    点下去 `ensureWidgetVisible` 作用在一个隐藏控件上，**画面纹丝不动**。
    普通用户看到的是一颗坏掉的按钮。
    ⭐ **把一块内容藏起来，指向它的东西不会跟着藏。**
    """
    page = _make_page(monkeypatch, expert=False, dir_valid=True)
    try:
        chips = _anchor_texts(page, qapp)
        assert chips, "一颗锚点都没建出来 —— 这条判据会空转，先修锚点条本身"
        assert "调试" not in chips, (
            f"普通模式下还有一颗指向隐藏卡片的锚点：{chips}")
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_anchor_chip_comes_back_in_expert_mode(qapp, monkeypatch):
    """反面守卫：专家模式下那颗锚点必须还在，否则是把导航修没了。"""
    page = _make_page(monkeypatch, expert=True, dir_valid=True)
    try:
        assert "调试" in _anchor_texts(page, qapp), (
            "专家模式下反而没有「调试」锚点了 —— 卡片在、跳不过去")
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_normal_users_are_not_told_about_a_feature_they_cannot_see(qapp, monkeypatch):
    """状态徽章与底部提示都不许提「调试模式」。

    挂一颗「调试 · 未启用」给看不到调试卡片的人，等于告诉他有个东西关着，
    却既不说那是什么、也没有任何地方能打开它。
    """
    page = _make_page(monkeypatch, expert=False, dir_valid=True)
    try:
        from PySide6.QtWidgets import QLabel

        texts = [lb.text() for lb in page.findChildren(QLabel)
                 if lb.objectName() == "audioStatusChip"]
        assert texts, "一颗状态徽章都没有 —— 这条判据会空转"
        assert not any("调试" in t for t in texts), f"徽章里还在报调试状态：{texts}"
        assert "调试" not in page.action_bar.message_label.text(), (
            f"底部提示里还在报调试状态：{page.action_bar.message_label.text()}")
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_expert_users_still_see_the_debug_state(qapp, monkeypatch):
    """反面守卫：专家模式下状态还得报 —— 不然开没开都看不出来。"""
    page = _make_page(monkeypatch, expert=True, dir_valid=True)
    try:
        from PySide6.QtWidgets import QLabel

        texts = [lb.text() for lb in page.findChildren(QLabel)
                 if lb.objectName() == "audioStatusChip"]
        assert any("调试" in t for t in texts), (
            f"专家模式下也不报调试状态了 —— 开没开全靠猜：{texts}")
    finally:
        page.deleteLater()
        qapp.processEvents()
