# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-585：**「我现在在哪一页」这条信息，钉住它今天为真的那个来源。**

⚠⚠ 这条登记册条目立案时说的是「站在一页上时，它自己在侧栏里的那一项一点都看不见」，
并报了「28 页里 23 页露出 0%」。批 79 重新量下来，**三面全部不成立**：

| 立案说的 | 量出来的 |
|---|---|
| 23/28 露出 0% | 专家模式 **28/28 都高亮、露出 ≥96.7%**；普通模式 22/22 同样 |
| 证据那一屏（`config_snapshot`）侧栏没高亮 | 现象真、**机制错**：普通模式下这一页**根本没有导航项**（它是专家页），那一屏是工装 `force=True` 造出来的 |
| 侧栏组标题「开始」被切掉大半 | 全站全页 **0 处**组标题被切 |

⭐⭐⭐ 而立案原话「**不知道当前在哪个入口**」被顶栏证伪：`_compact_title`
**两种模式都显示**，28 页逐页量下来全部写着正确的页名。

⇒ 本条不落刀。留这支判据，是因为**「它为什么不成立」全靠三件今天恰好为真的事**，
而这三件事一条判据都没有：顶栏标题会跟着页走、专家模式下侧栏会滚到当前项、
当前项会高亮。任一条哪天坏掉，立案里那三面就**全部变成真的**。

⭐ 同 RN-063 的收尾口径：**把「为什么不成立」钉住，而不是把「不成立」写进档案就算完。**

（本项目测试逐文件跑：
 `python -m pytest tests/test_you_can_tell_which_page_you_are_on.py`）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import _audit_neutralize as _neutralize  # noqa: E402

#: 露出多少才算「看得见」。实测最低 96.7%（30px 高的按钮差 1px），留一档余量。
#: ⚠ 只量**竖向**：这台机器和 CI 的字体度量不同（RN-135 一族），
#:   而竖向 30px 来自布局，不来自字体宽度。
VISIBLE_ENOUGH = 90.0


def _build(expert: bool):
    """建一个离屏主窗。⚠ `ui_expert_mode` 必须在构造**之前**定（`_ui_mode.apply` 的原话）。"""
    from config import config

    kept = {k: getattr(config, k, None)
            for k in ("ui_expert_mode", "compact_mode")}
    # ⚠ 中和表也会写 config。**借了要还**，而「还」要走 finally（批 73 RN-572 的教训）。
    touched = {}
    win = None
    try:
        for page_id, overrides in _neutralize.NEUTRALIZE.items():
            for attr, value in overrides.items():
                touched.setdefault(attr, getattr(config, attr, None))
                setattr(config, attr, value)
        config.ui_expert_mode = bool(expert)
        config.compact_mode = False

        app = QApplication.instance() or QApplication([])
        import gui_widget

        win = gui_widget.MainWindow(auto_background_preload=False)
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.show()
        app.processEvents()
        win.setMinimumSize(1280, 800)
        win.resize(1280, 800)
        app.processEvents()
        yield win, app
    finally:
        if win is not None:
            win.close()
        for key, value in kept.items():
            setattr(config, key, bool(value))
        for attr, value in touched.items():
            setattr(config, attr, value)
        config.save_config_now()


@pytest.fixture(scope="module")
def normal_window():
    yield from _build(expert=False)


@pytest.fixture(scope="module")
def expert_window():
    yield from _build(expert=True)


def _goto(win, app, page_id):
    """切页。⚠ `force=True` 是要害：普通模式下六个专家页没有导航入口，
    不带 force 的 `show_page` **静默 return**，于是后面量的是上一页。"""
    win.show_page(page_id, animated=False, force=True)
    # ⚠⚠ 侧栏滚动的最后一步是 `QTimer.singleShot(0, ...)`（`_ensure_nav_button_visible`）。
    #   ⭐ **不把事件循环转够，那一步根本没跑** —— 量到的是「还没滚」的中间态。
    for _ in range(8):
        app.processEvents()


def _shown_pct(win, widget) -> float:
    """这个控件在侧栏视口里露出百分之多少。**走真滚动条位置。**

    ⛔ 不用 `mapTo(viewport)`：它读的是当下几何，而侧栏刚换过选中态，
      布局请求可能还挂在队列里。`mapTo(content)` 与滚动无关，减去
      `verticalScrollBar().value()` 才是屏幕上那个位置。
    """
    scroll = win._sidebar_scroll
    content = scroll.widget()
    top = scroll.verticalScrollBar().value()
    vh = scroll.viewport().height()
    y = widget.mapTo(content, QPoint(0, 0)).y()
    h = max(widget.height(), widget.sizeHint().height())
    if h <= 0:
        return 0.0
    return 100.0 * max(0, min(y + h, top + vh) - max(y, top)) / h


def test_the_top_bar_always_says_which_page_you_are_on(normal_window):
    """⭐⭐⭐ 这是「我在哪」这条信息**唯一全程为真**的来源。

    普通模式下六个专家页在侧栏上没有任何表示（那是设计），
    顶栏是那一刻屏幕上仅剩的答案 —— 而在这条判据之前它没有任何守卫。
    """
    win, app = normal_window
    title = getattr(win, "_compact_title", None)
    assert title is not None, "顶栏标题控件没了 —— 「我在哪」这条信息就只剩侧栏一个来源了"

    checked = []
    for page_id, page_name in win._page_names.items():
        _goto(win, app, page_id)
        assert title.isVisible(), (
            f"切到 {page_id} 之后顶栏标题不可见 —— RN-585 立案里那三面会全部变成真的")
        assert title.text() == page_name, (
            f"{page_id}：顶栏写着 {title.text()!r}，而这一页叫 {page_name!r}")
        checked.append(page_id)

    # ⭐ 分母守卫：本仓三次被「分母塌了」骗过（批 68 / 76 / 78）。
    # ⚠ 批 98：下限 27 而不是 28 —— 开源版没有账号页（RN-543 同步时验收门逮到的）。
    assert len(checked) >= 27, f"只量到 {len(checked)} 页，分母塌了"


def test_in_expert_mode_the_sidebar_marks_the_page_you_are_on(expert_window):
    """专家模式 = 侧栏里 28 页都有项，**那才是真实用户看得到的那一屏**。

    ⚠ 立案的证据截图是**普通模式**下强达专家页拍的 —— 那一屏用户到不了
      （普通模式下 `show_page` 不带 force 会静默 return）。⭐ 同 RN-134 一族：
      **工装造出一个用户看不到的画面，外审照着它报了一条缺陷。**
    """
    win, app = expert_window

    measured, bad = [], []
    for page_id in win._page_names:
        _goto(win, app, page_id)
        btn = win.nav_buttons.get(page_id)
        assert btn is not None, f"专家模式下 {page_id} 在侧栏里没有导航项"
        assert btn.isVisible(), f"专家模式下 {page_id} 的导航项是隐藏的"
        assert btn.isChecked(), f"站在 {page_id} 上，它自己的导航项没有高亮"
        pct = _shown_pct(win, btn)
        measured.append(page_id)
        if pct < VISIBLE_ENOUGH:
            bad.append(f"{page_id}({pct:.1f}%)")

    assert not bad, ("这几页的导航项没滚进视口 —— RN-585 立案说的就是这件事："
                     + ", ".join(bad))
    assert len(measured) >= 27, f"只量到 {len(measured)} 页，分母塌了"   # 同上：开源版 27 页


def test_this_ruler_can_actually_see_a_sidebar_that_stopped_scrolling(expert_window):
    """⭐⭐ 上面那条绿着，可能是因为侧栏真的滚了，**也可能是因为这把尺子瞎了**。

    ⚠ 立案时那支探针报「28 页里 23 页露出 0%」，其中包括 `utility` ——
      而 `utility` 的截图上它明明又高亮又可见。⭐ 探针与图矛盾时，错的是探针。
    ⇒ 这一条把滚动条按回 0 再量最后一页：量得动就该读出「看不见」。
      读不出来，说明上面那条的绿是**绿在尺子上**，不是绿在产品上。

    ⭐ 同 RN-598（批 78）：**判据得自己制造最坏的起点**，
      否则它的敏感度取决于它跑起来那一刻碰巧是什么状态。
    """
    win, app = expert_window
    last = list(win._page_names)[-1]
    _goto(win, app, last)
    btn = win.nav_buttons[last]
    assert _shown_pct(win, btn) >= VISIBLE_ENOUGH, "前提就不成立：最后一页本来就没滚进来"

    win._sidebar_scroll.verticalScrollBar().setValue(0)
    app.processEvents()
    assert _shown_pct(win, btn) < VISIBLE_ENOUGH, (
        "把侧栏按回顶部之后，这把尺子仍然说最后一页的导航项看得见 —— "
        "它量的不是屏幕上那个位置，上面两条的绿不作数")
