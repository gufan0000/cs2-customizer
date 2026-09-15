# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""名字叫「高度」的令牌，说的就是屏幕上那个高度（RN-551 / X2，批 67）。

## 根因

⭐⭐⭐ **设计系统的高度令牌被当成 QSS 的「内容盒」发出去了。**
`ButtonSpec.secondary_height = 36`、`InputSpec.combobox_height = 34` 这些名字都叫
「高度」，说的是**整个控件**占多大；而 Qt 样式表跟 CSS 一样，`min-height` / `min-width`
量的是**内容盒**，padding 与 border 在它之外。于是发出去的 36，屏幕上是
**36 + padding 8×2 + border 1×2 = 54**（高 50%）。

后果不是「差一点」，是**调用点写下的高度全成了死信**：`setFixedHeight(32)` 把 max
定到 32，样式表把 min 顶到 50，**Qt 在 min > max 时取 min** ⇒ 50。
⭐ **规格与调用点两处独立声明写着同一个数，而屏幕给的是第三个数。**

## 批 67 实测（全站 28 页 342 个受管控件，完整档）

| 量 | 改前 | 改后 |
|---|---|---|
| `minimumHeight()` **正好落在令牌上** | **4 / 342** | **314 / 342** |
| 下限比令牌高 16~18px | **252** | 0 |
| 下限被 `fp_short` 清成 0（下游补丁） | 82 | 24 |
| **min > max（调用点的声明成死信）** | **39** | **0** |

⚠ RN-442（宽 133 颗）与 RN-547（高 161 颗）都是它的表征 —— 当时的修法是给按钮打
`fp_narrow` / `fp_short` 把**下限清零**，那是在下游一颗一颗补，而清零之后规格下限
对那些按钮也一起没了。⭐ 根因修好之后那两条补丁**变小了但没消失**（82 → 24）：
剩下的是**真冲突**（调用点要的比规格下限还矮），不是单位错配 —— 两者以前长得一样。

⚠ 收益要如实说：全站溢出总量 12333 → 10844px（完整档 **−12.1%**）、
16389 → 14488px（紧凑档 −11.6%），而**溢出页数一页都没变**（25/28、28/28）。
⭐ **控件矮 16~18px 买到的是「少滚」，不是「不用滚」** —— 紧凑档第一屏装不下
（RN-529）不是控件高度一家的事，那条「记录不做」的裁定因此站得更稳。
"""
from __future__ import annotations

import os
import re
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
    QApplication, QComboBox, QLineEdit, QPushButton, QWidget,
)

#: Qt 的「没有上限」哨兵；PySide6 不导出 `QWIDGETSIZE_MAX`，用它的值。
NO_MAX = (1 << 24) - 1

#: 这一版真窗量到的页面（挑的是下拉框/输入框/按钮都齐的几页）
PAGES = ("basic", "hud_color", "advanced")


def test_qss_box_converts_and_never_goes_negative():
    """换算函数本身：减掉两边的 padding 与 border，且不许为负。"""
    from ui_design_system import qss_box

    assert qss_box(36, 8, 1) == 18          # secondaryButton
    assert qss_box(34, 7, 1) == 18          # QComboBox / QLineEdit
    assert qss_box(36, 8) == 20             # primaryButton（border: none）
    assert qss_box(80, 18) == 44            # min-width 同一套单位
    assert qss_box(10, 8, 1) == 0, "padding 比总高还大时必须夹到 0，不能发负数给 QSS"


def test_no_rule_emits_a_raw_height_token_as_a_content_box():
    """⭐ 最硬的一条：**源码里不许再把「总高」令牌直接发给 `min-*`**。

    这条判的是写法而不是渲染结果 —— 渲染结果会被别的规则、别的标记盖住，
    而「把令牌原样发出去」这个动作在源码里是唯一且明确的。
    ⚠ 手调的字面量（`min-height: 38px` 这类照屏幕调出来的）不在管辖内：
      它们没有「声明与屏幕不一致」这个病，因为它们本来就是照屏幕写的。
    """
    src = (REPO / "theme_manager.py").read_text(encoding="utf-8")
    # ⚠ 管辖范围只包括「整个控件多大」的令牌，逐个点名。
    #   `scrollbar.handle_min_height` 故意不在内：它说的是**把手最短多长**，
    #   那条规则本来就没有 padding / border，不存在内容盒与总高的差别。
    TOTAL_SIZE = (r"\.(?:primary|secondary|action|danger)_height"
                  r"|\.icon_size|\.combobox_height|\.text_height"
                  r"|\.primary_min_width|height\.(?:xs|sm|md|lg|xl)")
    bad = re.findall(
        r"(?:min|max)-(?:height|width): \{[a-z_]+(?:" + TOTAL_SIZE + r")\}px", src)
    assert not bad, (
        f"theme_manager 里还有 {len(bad)} 处把「总高/总宽」令牌直接发给 QSS 的 "
        f"min-*/max-*：{bad}\n"
        "⇒ QSS 量的是内容盒，必须走 `ui_design_system.qss_box(总数, padding, border)`。")
    # 阳性对照：换算过的写法确实存在，否则上面那条会在「一处都没有」时空转
    assert src.count("qss_box(") >= 10, (
        f"只找到 {src.count('qss_box(')} 处换算 —— 批 67 落地时是 16 处，分母塌了")


def test_the_generated_stylesheet_puts_the_token_back_together():
    """语义判据：把发出去的内容盒数**加回 padding 与 border**，必须等于令牌。

    这条盯的是「换算用错了参数」——比如把 border 漏掉、或者拿了另一个组件的 padding。
    源码判据看不见那一类（写法对了，参数错了）。
    """
    from theme_manager import get_theme_manager
    from ui_design_system import get_design_system

    ds = get_design_system()
    b, i = ds.button, ds.input
    qss = get_theme_manager().get_stylesheet()

    # 选择器 → (令牌, padding_vertical, border_width)
    CASES = {
        "QPushButton#primaryButton": (b.primary_height, b.primary_padding_vertical, 0),
        "QPushButton#secondaryButton": (b.secondary_height, b.secondary_padding_vertical,
                                        b.secondary_border_width),
        "QPushButton#dangerButton": (b.danger_height, b.danger_padding_vertical, 0),
        "QPushButton#actionButton": (b.action_height, b.action_padding_vertical, 1),
        "QPushButton#ghostButton": (b.action_height, b.action_padding_vertical, 1),
        "QComboBox": (i.combobox_height, i.combobox_padding_vertical, i.combobox_border_width),
    }
    bad, checked = [], 0
    for sel, (token, pad, border) in CASES.items():
        # ⚠ 同一个选择器在样式表里不止一块（还有若干覆盖块）；
        #   要的是**声明高度的那一块**，不是第一块。
        blocks = [m.group(1) for m in
                  re.finditer(re.escape(sel) + r" \{([^}]*)\}", qss)]
        assert blocks, f"样式表里找不到 {sel} —— 分母塌了"
        sized = [b for b in blocks if "min-height:" in b]
        assert len(sized) == 1, (
            f"{sel} 有 {len(sized)} 块声明了 min-height（共 {len(blocks)} 块）"
            f" —— 高度应当只有一处声明")
        mh = re.search(r"min-height: (\d+)px", sized[0])
        checked += 1
        total = int(mh.group(1)) + 2 * pad + 2 * border
        if total != token:
            bad.append(f"{sel}: 发出 {mh.group(1)} + padding {pad}×2 + border {border}×2 "
                       f"= **{total}**，而令牌写的是 {token}")
    assert checked == len(CASES)
    assert not bad, "换算的参数对不上：\n  " + "\n  ".join(bad)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    """⚠⚠ 批 66 的教训：走用户真走的那条路。

    既有判据长期绿在 `ensure_page_loaded` + 不 `show()` + 只转一拍上 ——
    **结构上看不见「第一次进这一页」那一态**，而样式表在那之后还会再 polish 一次。
    ⇒ `show()` + `show_page()` + 多转几拍，量到的才是屏幕上那个数。
    """
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


def _managed(win):
    """受设计系统管高度的控件：(控件, 令牌)。"""
    from ui_design_system import get_design_system

    ds = get_design_system()
    names = {
        "primaryButton": ds.button.primary_height,
        "secondaryButton": ds.button.secondary_height,
        "actionButton": ds.button.action_height,
        "dangerButton": ds.button.danger_height,
    }
    out = []
    for page in win.pages.values():
        for w in page.findChildren(QWidget):
            if not w.isVisibleTo(page):
                continue
            if isinstance(w, QComboBox):
                out.append((w, ds.input.combobox_height))
            elif isinstance(w, QLineEdit) and w.objectName() == "input":
                out.append((w, ds.input.text_height))
            elif isinstance(w, QPushButton) and w.objectName() in names:
                out.append((w, names[w.objectName()]))
    return out


def test_a_widget_minimum_lands_on_its_token(win):
    """真窗行为：受管控件的**下限**不许高过以它命名的那个令牌。

    ⚠ 只判「不许高过」，不判「必须相等」—— 下限被调用点或 `fp_short` 压**低**
    是另一件事（那是真冲突，见模块头那张表），而**高过**才是单位错配。
    """
    got = _managed(win)
    assert len(got) >= 20, (
        f"只量到 {len(got)} 个受管控件（批 67 实测三页 ≥20）—— 这条判据在空转")
    bad = [f"{type(w).__name__}#{w.objectName() or '-'} 下限 {w.minimumHeight()} > 令牌 {tok}"
           for w, tok in got if w.minimumHeight() > tok]
    assert not bad, (
        f"{len(bad)}/{len(got)} 个控件的下限高过它自己的令牌（单位错配又回来了）：\n  "
        + "\n  ".join(bad[:12]))


def test_no_declared_height_is_a_dead_letter(win):
    """调用点写下的高度上限，不许被样式表的下限吃掉（min > max 时 Qt 取 min）。

    改前全站 **39** 处死信；批 67 之后 **0**。其中 16 处是下拉框 ——
    `mark_compact_buttons()` 只管 `QAbstractButton`，从来够不着它们，
    于是那 4 行 `setFixedHeight(30/32)` **从写下那天起就没生效过**，已删。
    ⭐ **一句从没生效过的声明，留着就是留一句谎话。**
    """
    got = _managed(win)
    assert got, "一个受管控件都没量到 —— 这条判据在空转"
    dead = [f"{type(w).__name__}#{w.objectName() or '-'} min={w.minimumHeight()} "
            f"> max={w.maximumHeight()}（令牌 {tok}）"
            for w, tok in got
            if w.maximumHeight() < NO_MAX and w.minimumHeight() > w.maximumHeight()]
    assert not dead, (
        f"{len(dead)} 处调用点声明成了死信：\n  " + "\n  ".join(dead[:12])
        + "\n⇒ 要么把那句没生效过的声明删掉，要么让规格下限跟着它降。")
