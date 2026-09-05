# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""状态卡是全站模式，撤掉它要有理由 —— 而这一页的理由已经写下来了（RN-496）。

## 这条判据存在的原因

批 52 撤掉了 `preset_center` 的「当前状态」卡。那是一次**有依据的例外**，
不是一条新的通则。⚠ 没有这条判据的话，下一个人撞上「第一屏放不下」时，
最省事的做法就是照着这一页再撤一张 —— 而别的页那张卡报的东西**别处看不到**。

## 依据：跨页普查（批 52 实测，完整 1280×800 与紧凑 860×640 各一遍）

- **28 / 28 页都有状态卡**，卡高 68 ~ 251px；
- 只有 `preset_center` **只剩一颗**胶囊，而那颗（「范围 · N/7 类」）数的正是它
  **正下方 12px** 那张卡上逐个画着的七个勾选框；
- 别的页报的是「GSI · 未运行」「驱动 · 待安装」「素材 · 待添加」「目录 · 已配置」
  这类**这一屏上别处看不到**的事。

⇒ 规则：**状态卡值它那 68~251px，条件是它至少报一件这一屏别处看不到的事。**
这条判据只钉得住其中机械可查的那一半（有没有胶囊），另一半靠人在撤之前回答。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

#: 唯一一页**故意**没有状态卡的。要往里加名字，先回答 RN-496 那个问题：
#: 「这一页的状态卡报的事，这一屏上别处看得到吗？」
DELIBERATELY_WITHOUT = {"preset_center"}


@pytest.fixture(scope="module")
def window(qapp):
    os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
    os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")
    # ⚠ `audio_health` 的胶囊是一次**异步扫盘**的产物：不给这个开关，
    #   建完页那一刻它一颗都还没有，这条判据会把它误报成「卡不见了」。
    # ⭐ 用产品自己那个钩子（批 48 / RN-146 就是为这件事加的），不靠 sleep。
    os.environ["CS2C_SYNC_HEALTH_SCAN"] = "1"
    from PySide6.QtCore import Qt

    import _audit_neutralize as neutral
    from config import config

    neutral.apply(config)
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        qapp.processEvents()
        neutral.apply(config, list(win._page_names.keys()))
        win.setMinimumSize(1280, 800)
        win.resize(1280, 800)
        qapp.processEvents()
        yield win
    finally:
        win.close()
        qapp.processEvents()


def _chips_on(page) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [w.text().strip() for w in page.findChildren(QLabel)
            if w.objectName() == "audioStatusChip" and w.isVisibleTo(page)
            and w.text().strip()]


def _pages(win):
    import _audit_neutralize as neutral

    return [p for p in win._page_names if p not in neutral.unsafe_pages()]


def test_every_other_page_still_has_its_status_card(qapp, window):
    """⭐ 反向守卫：这次的撤卡是**一页的例外**，不是全站的新做法。"""
    import _ui_mode

    pages = _pages(window)
    assert len(pages) >= 20, f"只扫到 {len(pages)} 页 —— 分母塌了"

    missing = []
    for pid in pages:
        if pid in DELIBERATELY_WITHOUT:
            continue
        _ui_mode.goto(window, pid)
        for _ in range(3):
            qapp.processEvents()
        page = window.pages.get(pid)
        if page is None:
            continue
        if not _chips_on(page):
            missing.append(pid)
    assert not missing, (
        "这些页的状态卡不见了：" + ", ".join(missing) + "\n"
        "⭐ 批 52 撤掉 `preset_center` 那张，靠的是「它那唯一一颗胶囊数的是"
        "正下方 12px 就画着的七个勾选框」。别的页报的是 GSI / 驱动 / 素材 / 目录"
        "这类**这一屏别处看不到**的事 —— 撤之前先回答那个问题。")


def test_the_page_that_dropped_it_really_has_none(qapp, window):
    """⭐ 正向守卫：名单里那一页必须**真的**没有胶囊。

    ⚠ 没有这一条，`DELIBERATELY_WITHOUT` 就是一张只会变长的豁免名单 ——
    而豁免名单一旦和事实脱节，上面那条就在替一件没发生的事作证。
    """
    import _ui_mode

    for pid in sorted(DELIBERATELY_WITHOUT):
        _ui_mode.goto(window, pid)
        for _ in range(3):
            qapp.processEvents()
        page = window.pages.get(pid)
        assert page is not None, f"{pid} 建不出来"
        chips = _chips_on(page)
        assert not chips, (
            f"{pid} 又长出状态胶囊了：{chips}\n"
            "⇒ 要么把它从 `DELIBERATELY_WITHOUT` 里拿掉（并说明这一颗报的事"
            "这一屏别处看不到），要么撤掉这一颗。")
