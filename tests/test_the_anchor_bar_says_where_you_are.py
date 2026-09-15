# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""页内锚点条：说清「点了会怎样」和「现在在哪一段」（RN-443 / RN-431 / X2，批 66）。

## 两条账，一排控件

| 号 | 外审原话 | 改前实测 | 改后 |
|---|---|---|---|
| RN-443 | 「外观呈现分页 Tab 样式，误以为点击是在切换独立子页面」 | `magnifier` **0/6** 答对 | **6/6** |
| RN-431 | 「10 个密集标签缺乏激活态指示，**分不清是切页还是锚点**」 | `magnifier` 2/6 · `advanced` **0/6** | **6/6 · 6/6** |

## ⭐⭐⭐ 这一轮最值钱的一条：同一个改动，在两页上买到的东西完全不同

四档行为题（D 改前 / A 只加前导词 / B 只加当前态 / C 两样都有）：

- **`advanced`**：改前就 **6/6** 答对「本页内跳转」，前导词一分钱没买到（A ≡ D）。
- **`magnifier`**：改前 **0/6**（全部读成页签），**只加当前态仍 5/6 误读**，
  **加上前导词才 6/6**。

⇒ 我差一点因为 `advanced` 那一轮就把前导词撤掉（批 44 的铁约束：零收益的改动不留）。
⭐ **一个改动的价值，取决于你在哪一页量它** —— 两页的锚点名不一样：
   `advanced` 是「目录 / 外观 / 公告」（读起来像章节），
   `magnifier` 是「基础 / 倍率 / 热键」（读起来像页签）。

## 还有两条是实测逼出来的（都写在 `widgets/anchor_bar.py` 的 `_sync` 里）

⚠ **末尾那几段顶不上去**：点「配置」只能滚到底，若按「越过视口上沿的最后一段」算，
  高亮会停在「统计」上 —— **屏幕上的反馈说他点错了，其实是页面到头了**。
⚠ **并排的两段顶沿相同**：`magnifier` 的「倍率」「热键」实测同在 y=74，
  按「最后一个」算会变成点「倍率」却高亮「热键」。
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
os.environ.setdefault("CS2C_NO_GLOBAL_HOTKEYS", "1")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QPushButton, QScrollArea,
)

PAGES = ("advanced", "magnifier")
#: 调用点原来写的高度。⭐ 现在只有 `QPushButton#anchorChip` 的 QSS 一处声明它。
DECLARED_HEIGHT = 26


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    """⭐ 走 `show_page` 且**多转几拍**：锚点条由 `QTimer.singleShot(0, …)` 建，
    只 `processEvents()` 一次量到的是样式表还没 polish 上去的那一瞬
    （min=max=26，看起来完全正常），多等几拍才是真相。批 66 开工时我拿一支
    「量早了」的探针，差点把这条活着的 S3 判成不成立。"""
    import gui_widget
    from _audit_neutralize import apply as neutralize_apply
    from config import config

    neutralize_apply(config, list(PAGES))
    w = gui_widget.MainWindow()
    w.setAttribute(Qt.WA_DontShowOnScreen, True)   # ⛔ 不打扰前台
    w.resize(1280, 800)
    w.show()
    app.processEvents()
    for pid in PAGES:
        try:
            w.show_page(pid, animated=False)
        except Exception:  # noqa: BLE001
            pass
        for _ in range(6):
            app.processEvents()
    yield w
    w._force_exit = True
    w.close()


def _chips(win, pid):
    page = win.pages.get(pid)
    if page is None:
        return []
    return [b for b in page.findChildren(QPushButton)
            if b.objectName() == "anchorChip"]


def _scroll(win, pid):
    return win.pages[pid].findChild(QScrollArea)


def test_the_denominator_is_both_pages(win):
    """分母守卫：锚点条建不出来时必须喊出来，而不是安静地全绿。"""
    counts = {pid: len(_chips(win, pid)) for pid in PAGES}
    assert all(n >= 4 for n in counts.values()), (
        f"锚点数不对：{counts}（批 66 实测 advanced 9 / magnifier 5）—— 分母塌了")


def test_anchor_chips_are_the_height_their_caller_declared(win):
    """RN-547 残余：**第一次进这一页**时那 14 颗渲染成 34px，比声明的 26px 高 31%。

    根因同 RN-442/547：通用 `QPushButton { min-height }` 是**内容盒**，
    加上 padding/border 折成 34；调用点的 `setFixedHeight(26)` 于是是一句死声明。
    ⇒ 高度收成一处（`QPushButton#anchorChip` 自己的 QSS），调用点不再写第二个数。
    """
    bad = []
    for pid in PAGES:
        for b in _chips(win, pid):
            if b.height() != DECLARED_HEIGHT:
                bad.append(f"[{pid}] {b.text()!r} 实高 {b.height()} "
                           f"(min={b.minimumHeight()} max={b.maximumHeight()})")
    assert not bad, ("这些锚点芯片没有按声明的 26px 渲染：\n  " + "\n  ".join(bad[:8]))


def test_the_current_section_is_marked(app, win):
    """RN-431：滚动时**当前在哪一段**要跟着变，而且不止一个值。"""
    for pid in PAGES:
        chips = _chips(win, pid)
        sb = _scroll(win, pid).verticalScrollBar()
        seen = set()
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            sb.setValue(int(sb.maximum() * frac))
            for _ in range(2):
                app.processEvents()
            checked = [c.text() for c in chips if c.isChecked()]
            assert len(checked) == 1, (
                f"[{pid}] 滚到 {frac:.0%} 时高亮了 {len(checked)} 颗：{checked} —— "
                "「当前在哪一段」只能有一个答案")
            seen.add(checked[0])
        assert len(seen) >= 2, (
            f"[{pid}] 从头滚到尾，高亮始终停在 {seen} —— 它没跟着滚动位置走")
        sb.setValue(0)
        app.processEvents()


def test_the_last_section_can_still_be_current(app, win):
    """⚠ 末尾那几段顶不上去（点它们只能滚到底）—— 滚到底时高亮必须落在最后一颗。

    否则用户点「配置」、屏幕滚到底、而高亮亮在「统计」上，
    **屏幕上的反馈说他点错了，其实是页面到头了**。
    """
    for pid in PAGES:
        chips = _chips(win, pid)
        sb = _scroll(win, pid).verticalScrollBar()
        sb.setValue(sb.maximum())
        for _ in range(3):
            app.processEvents()
        assert chips[-1].isChecked(), (
            f"[{pid}] 滚到底时高亮的是 "
            f"{[c.text() for c in chips if c.isChecked()]}，不是最后一段 "
            f"{chips[-1].text()!r}")
        sb.setValue(0)
        app.processEvents()


def test_a_jump_lands_on_the_section_top(app, win):
    """点一颗锚点，要把那一段顶到视口上沿 —— **从哪儿点都一样**。

    ⚠ `advanced` 原来用 `ensureWidgetVisible`，那是「最小滚动使其可见」：
      实测从页面底部点第一颗「目录」停在 **197** 而不是 0，那一节的顶部还在视口上面。
    ⭐ 而 `magnifier` 的注释里**早就逐字写着**这个跳法是错的 ——
      同一件事有两份实现，其中一份已经被另一份写下的字证明是错的。
    """

    for pid in PAGES:
        scroll = _scroll(win, pid)
        sb = scroll.verticalScrollBar()
        chips = _chips(win, pid)
        landed = []
        for chip in chips:
            sb.setValue(sb.maximum())        # ⭐ 从最远处点，「最小滚动」那种跳法才露馅
            app.processEvents()
            chip.click()
            for _ in range(2):
                app.processEvents()
            landed.append(sb.value())
        sb.setValue(0)
        app.processEvents()

        assert landed == sorted(landed), (
            f"[{pid}] 从底部逐颗点下来，落点不是单调递增的：{landed} —— "
            "要么芯片顺序和滚动顺序对不上，要么跳法是「最小滚动使其可见」")
        assert landed[0] < landed[-1], (
            f"[{pid}] 第一颗和最后一颗落到同一处：{landed}")

        # ⭐⭐⭐ 「最小滚动」这件事的**直接**测法：同一颗芯片，从上面点和从下面点，
        # 落点必须一模一样。`ensureWidgetVisible` 的定义就是「滚到刚好可见」，
        # 于是它从上面来和从下面来会停在不同的地方；而
        # `setValue(段顶 - margin)` 与来路无关。
        #
        # ⚠⚠ 这一条是替换掉一条**尺子刻在巧合上**的断言（批 69）。原来写的是
        #   `landed[0] <= _JUMP_MARGIN + 1 or landed[0] < landed[1]`，
        #   意思是「第一颗应该把你带到最顶上」—— 而那只在**第一颗恰好是
        #   最顶上那个容器**时才成立。RN-552 把容器段从锚点条里去掉之后
        #   （父级「基础」装着子级「倍率」「热键」「偏移」），第一颗变成 `倍率`，
        #   它和 `热键` 并排、顶沿同为 y=488 ⇒ `landed[0] == landed[1] == 53`，
        #   两个分支同时不成立，判据**报了一次退步，而那次改动是对的**。
        # ⭐ 同批 67 那一族：**一条判据的尺子刻在偶然事实上时，
        #   等那个偶然消失的那天，它报的是一次退步。**
        for chip, from_bottom in zip(chips, landed):
            sb.setValue(0)
            app.processEvents()
            chip.click()
            for _ in range(2):
                app.processEvents()
            from_top = sb.value()
            assert from_top == from_bottom, (
                f"[{pid}]「{chip.text()}」从顶部点落在 {from_top}、"
                f"从底部点落在 {from_bottom} —— **落点取决于你从哪儿来**，"
                "那正是「最小滚动使其可见」的指纹（`advanced` 改前实测从底部点"
                "第一颗停在 197 而不是 0）。跳法必须是 `setValue(段顶 - margin)`。")
        sb.setValue(0)
        app.processEvents()


def test_the_bar_says_the_jump_stays_in_this_page(win):
    """RN-443：前导词。⭐ 它在 `advanced` 上一分钱没买到（A ≡ D，都是 6/6），
    在 `magnifier` 上却是**决定性的那一样**（只加当前态 1/6 → 加上前导词 6/6）。
    ⇒ **一个改动的价值，取决于你在哪一页量它。**"""
    for pid in PAGES:
        page = win.pages[pid]
        leads = [t for t in page.findChildren(QLabel)
                 if t.objectName() == "anchorLead" and t.text().strip()]
        assert len(leads) == 1, (
            f"[{pid}] 锚点条前面找到 {len(leads)} 个前导词 —— "
            "改前 magnifier 6/6 把这排读成「切换到另一个页面」")


def test_there_is_only_one_anchor_bar_implementation():
    """两页都走共用件，谁都不许再自己造 `anchorChip`。

    ⭐ 这条判据护的是本轮那个发现：**`advanced` 一直用着 `magnifier` 早已
    写下「这是错的」的那个跳法** —— 两份实现不会跟着彼此变，而漂了不报错。
    """
    for pid in ("advanced", "magnifier"):
        src = (REPO / "pages" / f"{pid}_page.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        calls = {n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "install_anchor_chips" in calls, (
            f"{pid}_page.py 不再走共用件 `install_anchor_chips`")
        assert 'setObjectName("anchorChip")' not in src, (
            f"{pid}_page.py 又自己造 anchorChip 了 —— 共用件白抽了")
