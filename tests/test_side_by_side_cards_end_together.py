# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 36 顺带 · **并排的两张卡，底部对不齐。**

## 这条是外审报的，而我差点照它说的维度去改

外审 S3 在 `utility` 上连报两轮（改前 5 发、改后 3 发）：
「『快捷与模式』与『快速操作』两张并排卡片高度不一致，底部未对齐」。

按 CLAUDE.md 那条（**凡是它报几何问题，一律实测复量再定性**）量了一遍 —— **这次是真的**：

    快捷与模式   x= 24 y=350  383x158  bottom=508
    快速操作     x=419 y=350  637x192  bottom=542      ← 差 34px

⭐ 而**同一轮里它报的另一条几何问题是假的**：
「『当前配置』被一条横线贯穿（疑似删除线/分割线重叠）」，4~5 发都这么说。
放大到 8 倍看原图：**没有任何线**。
「当」「前」「配」「置」**四个字每一个都有一道贯通字宽的横画**，
在这个字号下它们落在同一条 y 上，连成了一条肉眼可见的横带。
⭐⭐ **中文里「文字被横线贯穿」是一类系统性假阳性** ——
它感知到的东西真实存在，只是那东西是字本身。
（同 memory 里那条：**「不整齐」可信，「哪个维度不整齐」不可信** ——
这一轮两条几何问题，一真一假，而它们的措辞一样自信。）

## 成因：`AlignTop` + `QSizePolicy.Maximum`

    top_cards_row.addWidget(settings_frame, 3, Qt.AlignTop)
    top_cards_row.addWidget(button_frame,   5, Qt.AlignTop)
    settings_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

`Maximum` 的意思是「sizeHint 就是上限，别往上长」，`AlignTop` 再把它按在顶上 ⇒
两张卡各自按自己的内容取高，谁内容少谁就短一截。
⭐ 两句都**各自正确**（不想让卡无限拉伸、想让它贴顶），
合在一起才产出「同排不齐」—— 又一次「两条各自正确的规则在交集处出错」（批 25）。

## 分母：**28 页里有 10 排并排卡，5 排不齐**

    crosshair     y=271  [194, 251]   差  57px
    viewmodel     y=175  [237, 719]   差 482px
    magnifier     y=338  [284, 364]   差  80px
    voice_output  y=219  [170, 182]   差  12px
    utility       y=308  [158, 192]   差  34px      ← 批 36 修这一条

⚠⚠ **这支扫描的第一版，分母是错的** —— 它用 `win.pages.keys()` 当页面清单，
而那是**懒加载已经建出来的页**，开窗时只有 `basic` 一页。
于是它报「1 排并排卡、0 排不齐」，**一个填满了的、看起来完全正常的结论**。
⭐⭐⭐ 这正是批 34 那条：**一个分母错了的普查，产出的不是「不知道」，是一个错的答案。**
而我是**带着那条教训**在写这支扫描的，仍然踩了同一个坑 ——
⭐ 正确的分母是产品自己的导航注册表 `win._page_names`（`test_one_primary_button_per_screen`
里逐字写着这件事）。

## ⛔ 它**不是**一条「同排必须齐」的铁规

`viewmodel` 那 482px 是一张长列表卡挨着一张短设置卡 ——
把短的拉到 719px 会造出一张 480px 全空的卡，**那不是修好，是换一种难看**。
⇒ 所以这条只做**棘轮**：不齐的排数**只许变少**，
逐排怎么修（拉伸 / 换行 / 重新分组）得一排一排看。
"""
from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))


#: 同排卡片「底部不齐」的排数上限。**只许调小。**
#: 2026-08-31 批 36：全站 10 排并排卡，**5 排不齐**；本批修掉 `utility` 那一排 ⇒ **4**。
#: ⚠ 调小它的唯一正当方式是**真的把那一排修齐**，不是把某一页排除在扫描外。
MAX_RAGGED_ROWS = 4

#: 至少要看见这么多排并排卡，否则说明扫描器自己瞎了（RN-169）。
MIN_ROWS_SEEN = 8

#: 至少要走到这么多页，否则分母又错了（见 docstring 里那一段）。
MIN_PAGES_SEEN = 25

#: 差多少像素才算「不齐」。1~2px 是取整噪声，不当缺陷。
TOLERANCE_PX = 4


@pytest.fixture(scope="module")
def sitewide_card_rows(qapp):
    """建一次窗、走一遍全站，收每页「同一个 y 上并排的 card」。

    ⚠ 分母走 `win._page_names`（产品自己的导航注册表），**不是** `win.pages`
      —— 后者只有懒加载已经建出来的页。
    ⚠ 切页必须走 `_ui_mode.goto`（`force=True`），否则普通模式下 6 个专家页
      静默不切，工装拿着上一页继续量。
    """
    os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
    os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

    import _audit_neutralize as neutral
    import _ui_mode
    from config import config

    neutral.apply(config)
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        qapp.processEvents()
        win.setMinimumSize(1280, 800)
        win.resize(1280, 800)
        qapp.processEvents()

        page_ids = list(win._page_names.keys())
        neutral.apply(config, page_ids)
        page_ids = [p for p in page_ids if p not in neutral.unsafe_pages()]

        rows: list[tuple[str, int, list[int]]] = []
        seen_pages = 0
        for page_id in page_ids:
            _ui_mode.goto(win, page_id)
            for _ in range(4):
                qapp.processEvents()
            page = win.pages.get(page_id)
            if page is None:
                continue
            seen_pages += 1
            by_top: dict[int, list[int]] = {}
            for w in page.findChildren(QWidget):
                if w.objectName() != "card" or not w.isVisibleTo(page):
                    continue
                top = w.mapTo(page, w.rect().topLeft()).y()
                by_top.setdefault(top, []).append(w.height())
            for top, heights in sorted(by_top.items()):
                if len(heights) >= 2:
                    rows.append((page_id, top, sorted(heights)))
        yield rows, seen_pages
    finally:
        win.close()
        qapp.processEvents()


def _ragged(rows):
    return [(pid, top, hs) for pid, top, hs in rows
            if hs[-1] - hs[0] > TOLERANCE_PX]


def test_the_scan_walked_the_whole_product(sitewide_card_rows):
    """⭐⭐⭐ 先证明分母是对的 —— 这条判据的第一版正是死在这里（分母 1 页）。

    **一个分母错了的普查，产出的不是「不知道」，是一个错的答案。**
    """
    rows, seen_pages = sitewide_card_rows
    assert seen_pages >= MIN_PAGES_SEEN, (
        f"只走到 {seen_pages} 页 —— 分母又错了。\n"
        "⚠ 别用 `win.pages`（懒加载，开窗时只有 `basic` 一页），"
        "用 `win._page_names`；切页走 `_ui_mode.goto`。"
    )
    assert len(rows) >= MIN_ROWS_SEEN, (
        f"只扫出 {len(rows)} 排并排卡片 —— 这支扫描多半瞎了"
        f"（`objectName == \"card\"` 的约定改了？）。实测应有 10 排。"
    )


def test_side_by_side_cards_do_not_get_more_ragged(sitewide_card_rows):
    """棘轮：同排卡片「底部不齐」的排数只许变少。

    ⛔ 它**不**主张「同排必须齐」—— `viewmodel` 那一排差 482px，
    是长列表挨着短设置卡，硬拉齐会造出一张 480px 全空的卡。
    ⇒ 这条只挡「变多」，逐排怎么修得一排一排看。
    """
    rows, _ = sitewide_card_rows
    bad = _ragged(rows)
    assert len(bad) <= MAX_RAGGED_ROWS, (
        f"同排卡片底部不齐的排数从 {MAX_RAGGED_ROWS} 涨到了 {len(bad)} 排：\n"
        + "\n".join(f"  {pid:14s} y={top:4d} 高度 {hs} 差 {hs[-1]-hs[0]}px"
                    for pid, top, hs in bad)
        + "\n⇒ 常见成因：`addWidget(card, n, Qt.AlignTop)` 配上 "
        "`setSizePolicy(..., QSizePolicy.Maximum)` —— 两句各自正确，"
        "合在一起就是「谁内容少谁短一截」。"
    )
    assert len(bad) >= MAX_RAGGED_ROWS, (
        f"实际只剩 {len(bad)} 排，把 MAX_RAGGED_ROWS 收到这个数 —— "
        "棘轮不收紧等于没有棘轮。"
    )


def test_the_page_under_review_is_actually_flush(sitewide_card_rows):
    """⭐ 棘轮只说「没变多」，说不出「批 36 那一排修好了没有」。

    ⚠ 这两条**不能合并**：棘轮的数从 5 掉到 4，可能是我修好了 `utility`，
    也可能是我修好了 `magnifier` 而 `utility` 原样不动 ——
    **同一个数，两件不同的事。**
    """
    rows, _ = sitewide_card_rows
    mine = [(top, hs) for pid, top, hs in rows if pid == "utility"]
    assert mine, "`utility` 上一排并排卡都没扫到 —— 这条判据已经瞎了"
    ragged = [(top, hs) for top, hs in mine if hs[-1] - hs[0] > TOLERANCE_PX]
    assert not ragged, (
        "`utility` 的「快捷与模式」/「快速操作」还是不齐：\n"
        + "\n".join(f"  y={top} 高度 {hs} 差 {hs[-1]-hs[0]}px" for top, hs in ragged)
    )
