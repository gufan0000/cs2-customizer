# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-102 在 `config_snapshot` 上的实例 + RN-506：**一颗会变身的主按钮。**

## 一、实测的三对重复

批 31 建的存量债表里，`config_snapshot` 记着 **3 处**「底栏与卡内绑同一个方法」：
`_create_snapshot` / `_reload` / `_restore_selected`。

⚠ 而截图上只看得见 **2 颗**底栏按钮 —— 因为底栏那颗主按钮是**状态相关**的：

    没选中条目 ⇒ 「创建快照」
    选中了条目 ⇒ 「**恢复选中**」

⭐ 债表的 3 是对的，我数的 2 是错的 —— **一张图里看不见的东西不会被报**
  （CLAUDE.md 的拍图工艺第 5 条，这次咬的是我自己的读图）。

## ⭐⭐⭐ 二、RN-506：那颗按钮把「创建」和「覆盖」放在了同一个像素上

「创建快照」是**安全**动作（多存一份）。
「恢复选中」是**破坏性**动作（覆盖当前全部设置，本页副标题自己写着
「恢复前请确认这就是要回退的版本」）。

而它们共用底栏右下角**同一个位置**，取决于列表里有没有选中项 ——
⇒ 一个刚点过「创建快照」的人，在选中一行之后，**同一个像素**上变成了「恢复」。
⭐⭐⭐ **肌肉记忆记的是位置，不是文案。**

⚠ 这不是 RN-139（一屏两颗紫的）那一族，方向相反：
  它只有一颗紫的，而**那一颗的含义会变**。

⇒ 修法：底栏主按钮**固定为「创建快照」**（安全动作恒定），
  「恢复选中」只留卡内那一颗（危险动作留在离列表最近、有语境的地方），
  底栏那颗纯副本「刷新快照」撤掉，卡内撤掉重复的「创建快照」。

  ⇒ 每个动作恰好一个入口：创建=底栏、恢复=卡内、刷新=卡内。

## ⚠ 批 31 的两条规则在这一页怎么用

① 撤的是**副本**，不是动作本身 —— 三个动作一个都没少（下面第三条判据钉住）。
② **留离它作用的对象最近的那一颗** —— 「恢复选中」作用的对象是列表里选中那一行，
   所以它留在「快照操作」卡（紧挨着列表卡），不留在底栏。
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QPushButton

from _denominator import must_scan

PAGE_ID = "config_snapshot"

#: 破坏性动作：点下去会覆盖用户当前的全部设置。
DESTRUCTIVE = ("恢复",)


@pytest.fixture()
def page(qapp):
    import os

    os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
    from pages.config_snapshot_page import ConfigSnapshotPage

    p = ConfigSnapshotPage()
    p.resize(1042, 720)
    p.show()
    for _ in range(4):
        qapp.processEvents()
    try:
        yield p
    finally:
        p.hide()
        p.deleteLater()
        qapp.processEvents()


def _buttons(page):
    return [b for b in page.findChildren(QPushButton)
            if (b.text() or "").strip() and b.isVisibleTo(page)]


def _bar_texts(page):
    bar = page.action_bar
    return [b.text().strip() for b in (bar.primary_btn, bar.secondary_btn)
            if b.isVisibleTo(bar) and (b.text() or "").strip()]


def test_each_action_has_exactly_one_entrance(page, qapp):
    """① 三个动作各**恰好一个**入口 —— 卡内与底栏不许同时出现同一个动作。"""
    texts = [t for t in (b.text().strip() for b in _buttons(page)) if t != "?"]
    must_scan(texts, "这一页上可见的按钮文案", least=3)

    bar = set(_bar_texts(page))
    card = {t for t in texts if t not in bar}
    # 「刷新」/「刷新快照」是同一个动作的两个说法 —— 按动作归一，不按文案。
    def norm(t):
        return "刷新" if "刷新" in t else ("创建" if "创建" in t else
                                         ("恢复" if "恢复" in t else t))

    dup = sorted({norm(t) for t in bar} & {norm(t) for t in card})
    assert not dup, (
        f"这些动作在底栏和卡内各有一个入口：{dup}\n"
        f"  底栏：{sorted(bar)}\n  卡内：{sorted(card)}\n"
        "⭐ 批 31 规则①：撤的是副本，不是动作本身；"
        "规则②：留离它作用的对象最近的那一颗。"
    )


def test_the_bottom_primary_never_turns_into_a_destructive_action(page, qapp):
    """② **RN-506**：底栏那颗主按钮不许变身成破坏性动作。

    ⚠ 这条要在**两种状态**下都问一遍（没选中 / 选中了）——
      而「选中了」那一支正是原来会变成「恢复选中」的那一支。
    ⭐⭐⭐ **肌肉记忆记的是位置，不是文案。**
    """
    from core.config_snapshot_manager import create_snapshot

    seen = []
    # 状态 A：没选中
    page.table.clearSelection()
    page._sync_action_bar()
    qapp.processEvents()
    seen.append(("没选中", page.action_bar.primary_btn.text().strip()))

    # 状态 B：造一行并选中它
    #
    # ⚠⚠ 批 47：这里原来只 `setRowCount(1)` + `setItem(...)` —— **伪造了表格，没伪造数据**。
    # 而 `_selected_snapshot_id()` 判的是 `row >= len(self._snapshots)`：
    # `_snapshots` 是空的时候它返回 ""，于是「选中了」这一支**根本没被走到**，
    # 判据在没有快照的环境里对 RN-506 完全瞎。
    # ⭐ 它之所以一直显得有效，是因为本机那个**跨轮次累积**的共享配置目录里
    #   躺着 21 份旧快照（RN-141 / RN-473 说的正是这件事）。并行化给每路换了
    #   一个全新的配置目录，它当场露馅：回退验证报「没逮住」。
    # ⭐⭐⭐ **一条靠环境里碰巧攒下的东西才成立的判据，在干净机器上是哑的** ——
    #   而"干净机器"正是 CI 和新同事的机器。
    # ⇒ 用真 API 造一份真快照，让页面自己把表格填出来。
    create_snapshot("b47_judge_probe")
    page._reload()
    qapp.processEvents()
    must_scan(page._snapshots, "页面读到的快照", least=1)

    page.table.selectRow(0)
    page._sync_action_bar()
    qapp.processEvents()
    assert page._selected_snapshot_id(), (
        "选中第一行之后 `_selected_snapshot_id()` 仍是空 —— "
        "「选中了」这一支没被真正走到，下面那个断言问的是另一条动线。")
    seen.append(("选中了", page.action_bar.primary_btn.text().strip()))

    must_scan(seen, "底栏主按钮在两种状态下的文案", least=2)
    bad = [(state, txt) for state, txt in seen
           if any(w in txt for w in DESTRUCTIVE)]
    assert not bad, (
        "底栏那颗主按钮在这些状态下变成了破坏性动作：\n  "
        + "\n  ".join(f"{s}：「{t}」" for s, t in bad)
        + "\n⭐⭐⭐ 「创建快照」是安全动作，「恢复选中」会覆盖当前全部设置 ——"
          "它们共用右下角同一个像素时，肌肉记忆会替用户按下后者。\n"
        + f"（实测两态：{seen}）"
    )
    assert len({t for _s, t in seen}) == 1, (
        f"底栏主按钮的文案随状态变了：{seen}\n"
        "⭐ 一颗位置固定、含义会变的按钮，比两颗按钮更难防。"
    )


def test_no_action_was_removed_along_with_its_copy(page, qapp):
    """③ **反面守卫**：撤重复最容易犯的错是把两颗一起删掉。

    ⭐ 批 31 那一批就为此配了一张反面表 —— 三个动作在这一页上必须都还够得到。
    """
    texts = {t for t in (b.text().strip() for b in _buttons(page)) if t}
    texts |= set(_bar_texts(page))
    must_scan(texts, "这一页上够得到的按钮文案", least=3)
    for action in ("创建", "恢复", "刷新"):
        assert any(action in t for t in texts), (
            f"「{action}」这个动作在这一页上一个入口都不剩了 —— "
            f"撤副本撤过头了。现有按钮：{sorted(texts)}")
