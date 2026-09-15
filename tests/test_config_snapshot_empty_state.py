# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-526：**一份快照都没有时，那张表是一大片全黑空表格。**

外审两个视口 **6/6 判高**，逐字「缺乏空状态占位与引导，极易被误认为数据加载
失败或软件卡死」。

⭐ 修法照 `audio_replay_page` 那个**已有先例**（空时藏表、显一句话），
**不另起一套** —— 那一页解决的正是「表空了怎么办」这同一个形状。
⛔ 而这里**不加按钮**：本页 RN-102/506 已裁定「三个动作全留在「快照操作」卡里、
底栏一颗不放」，空态再放一颗「创建快照」就是那条裁定要防的纯副本。
⇒ 只给一句**点名那颗按钮**的话，且**按钮名从按钮上读**（批 48 那条）。

⚠⚠ **回退验证当场把本文件判成假绿**（批 74，585/586）：我把四条断言写成
`assert X.isVisible() or not page.isVisible()` —— 而测试里这一页**从不显示**，
于是 `not page.isVisible()` 恒真，**四条断言一条都没有在断言**。
⭐⭐⭐ **一条判据查的东西，和它声称查的东西，可以不是一件事** —— 这次
「不是一件事」的**载体是那个我自己加的免责短路**。
⇒ 一律改用 `isVisibleTo(page)`：它问的是「若祖先显示出来，它会不会露脸」，
**不需要真的显示**。⚠ 本仓 `test_advanced_page_action_bar_and_debug.py:60`
早就写着同一句教训（「第一版就是这么写的，当场假绿」）——**我又写了一遍**。

（本项目测试逐文件跑：
 `python -m pytest tests/test_config_snapshot_empty_state.py`）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


@pytest.fixture(scope="module")
def page():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    sys.path.insert(0, str(REPO / "scripts"))
    from _audit_neutralize import enable_audit_mode

    enable_audit_mode()
    app = QApplication.instance() or QApplication([])
    from pages.config_snapshot_page import ConfigSnapshotPage

    p = ConfigSnapshotPage()
    yield p
    p.deleteLater()
    app.processEvents()


def _empty(page, monkeypatch):
    """把它推成「一份快照都没有」那一档。

    ⭐ **钉 = 推到那个状态，不是碰巧就是**（RN-571 那条）。
    ⚠ 我第一版只把 `page._snapshots` 清空就调 `_reload()` —— 而 `_reload()`
      **自己会再去磁盘取一遍**，于是这台机器上真有快照时它当场把非空塞回来，
      判据报「那句话是空的」。⭐ 要钉的是**它的输入**，不是它的输出。
    """
    import pages.config_snapshot_page as mod

    monkeypatch.setattr(mod, "list_snapshots", lambda: [])
    page._reload()
    return page


def test_the_empty_list_says_what_to_do(page, monkeypatch):
    """⭐ 空态必须**说话**，而且那张空表要让位 —— 否则玩家看到的是一片黑。"""
    _empty(page, monkeypatch)
    assert page.empty_hint_label.isVisibleTo(page), (
        "一份快照都没有，而那句空态提示没显示出来")
    assert not page.table.isVisibleTo(page), (
        "空表还占着位置 —— 那正是被读成「加载失败 / 卡死」的那一片黑")
    text = page.empty_hint_label.text()
    assert "还没有快照" in text, f"空态那句话不再说「还没有快照」：{text!r}"


def test_the_sentence_reads_the_button_name_from_the_button(page, monkeypatch):
    """⚠ 批 48：改了按钮名而点名它的这句话留在原地，两处同时出现、指的是同一颗。"""
    _empty(page, monkeypatch)
    text = page.empty_hint_label.text()
    label = page.create_btn.text()
    assert f"「{label}」" in text, (
        f"空态那句话点名的按钮是硬写的，不是从按钮上读的 —— "
        f"按钮现在叫「{label}」，而句子是：{text!r}")


def test_the_empty_state_adds_no_fourth_button(page, monkeypatch):
    """⛔ 空态**不许**再放一颗按钮 —— 本页 RN-102/506 已裁定三个动作全留在卡里。

    ⭐ 空态该给出路没错，但这一页的出路**就在同一屏上**，再放一颗就是纯副本
    （而「同一屏两颗同名按钮」本身就是缺陷，RN-416 撤过一次）。
    """
    from PySide6.QtWidgets import QPushButton

    _empty(page, monkeypatch)
    names = [b.text() for b in page.findChildren(QPushButton) if b.text()]
    # ⭐ 分母守卫：一颗按钮都扫不到时它必然全绿，而「分母为空」和「真的没重名」
    #   在报告上一模一样。这一页的「快照操作」卡里本来就有三颗。
    assert len(names) >= 3, (
        f"这一页只扫到 {len(names)} 颗按钮 —— 「快照操作」卡里本来有三颗"
        f"（创建 / 恢复 / 刷新）。扫描瞎了：{names}")
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"空态多出了重名按钮：{sorted(dupes)}（全部按钮：{names}）"


def test_the_table_comes_back_when_there_is_something(page, monkeypatch):
    """⚠ 反向也要看：有快照时表必须回来、提示必须让位 —— 否则这条修法只做了一半。

    ⚠⚠ 我第一版是**手工 `setVisible` 再断言** —— 那测的是我自己算出来的值，
    不是产品的行为（RN-197 逐字教过：「断言一个我自己算出来的值，
    证明不了页面做了什么」）。⇒ 钉住**输入**，让 `_reload()` 自己去决定。
    """
    import pages.config_snapshot_page as mod

    class _Snap:
        snapshot_id, created_at, reason = "snap-1", "2026-09-10 00:00:00", "手动"
        size, sha256 = 123, "a" * 64

    monkeypatch.setattr(mod, "list_snapshots", lambda: [_Snap()])
    page._reload()
    assert page.table.isVisibleTo(page), "有快照了表却没回来"
    assert not page.empty_hint_label.isVisibleTo(page), (
        "有快照了，那句「还没有快照」还留在屏幕上")
    assert page.table.rowCount() == 1, (
        f"表里应当有 1 行，实际 {page.table.rowCount()} 行")
