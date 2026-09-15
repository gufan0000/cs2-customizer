# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-566：**同一张卡里各行的第一个控件，左边缘必须对齐。**

2026-09-08 批 70。`magnifier` 上实测（1280×800，改前）：

* 「热键与触发」卡：`主武器热键:` 比 `手枪热键:` / `触发方式:` 宽 14px ⇒
  它那一行的下拉在 **693**，另外两行在 **679**；
* 「倍率与灵敏度」卡：`放大倍率:` 那一行的下拉在 **116**，
  而 `基础灵敏度:` / `联动倍率:` 的输入框在 **132**（差 16px）。

机制：每一行是各自独立的 `QHBoxLayout`，标签按自己的文字撑开。
⭐ **同一张卡里的行只要不共用一个布局列，就没有任何东西让它们对齐** ——
而「对齐」正是读者默认会有的预期，所以缺了它一眼就看得出别扭，
却又说不清哪里别扭（外审就说错了维度，见下）。

修法：把每张卡的行并进**一个 `QGridLayout`**，第 0 列放行首标签，
由布局取最宽的那个当列宽。⚠ 每格给 `AlignLeft | AlignVCenter`：
只借列宽做对齐，**不让控件被拉到列宽**（不给的话第 1 列会被那条 180px 的滑块
撑开，三个下拉跟着变成 180px —— 那是「对齐」顺手改掉了控件尺寸）。

⚠⚠ **两条弯路，都值得写下来：**

1. 外审点名的是「`基础灵敏度` / `联动倍率` 两行输入框左边缘不齐」——
   **那半句是假的**：两行都在 132，它们本来就在同一个 `QGridLayout` 的第 0 列里。
   真正错开的是它们**和 `放大倍率` 那一行**。
   ⭐ 第三次印证 CLAUDE.md 那条：**「不整齐」可信，「哪个维度不整齐」不可信。**
2. 我第一版写了个「量一遍再 `setMinimumWidth`」的助手。构造期 `sizeHint()`
   量的是**还没套应用样式表**那一档字体，偏小；改挂到 `QEvent.Polish` 上重量，
   **一样偏小**。结果 16px 只缩到 13px。
   ⭐⭐⭐ **一个在错误时刻做的正确测量，给出的是一个看起来很像成功的失败。**
   ⇒ 那个助手已删除（留着就是给下一个调用者挖坑）。
   **凡是「让若干控件对齐」，交给布局，别自己量像素。**

⚠ 分母目前只有 `magnifier`。⛔ 没有直接铺到全站，理由是「同一行里并排的
两组标签+输入」（本页底部的 `X:` / `Y:` 就是）是**合法的**不齐，
一铺开就要配白名单 —— 而**一张没有理由的白名单跟没有判据是一回事**
（RN-420 那条原话）。⇒ 拓宽分母另立一条，不在本批硬塞。

（本项目测试逐文件跑：
 `python -m pytest tests/test_rows_in_one_card_start_at_one_left_edge.py`）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

#: 一行之内的纵向容差：同一行的控件 y 可能差几像素（高度不同、居中方式不同）。
_ROW_BAND = 12


@pytest.fixture(scope="module")
def magnifier_page():
    """按 `layout_overflow_audit.py` 同一档建窗（1280×800，离屏，不打扰前台）。"""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from _audit_neutralize import apply as neutralize_apply
    from _audit_neutralize import enable_audit_mode
    import _ui_mode as _um
    from config import config

    enable_audit_mode()
    app = QApplication.instance() or QApplication([])
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()
    win.setMinimumSize(1280, 800)
    win.resize(1280, 800)
    app.processEvents()
    neutralize_apply(config, ["magnifier"])
    _um.goto(win, "magnifier")
    app.processEvents()
    page = win.pages.get("magnifier")
    assert page is not None, "拿不到 magnifier 页"
    yield page
    win.close()


def _card_of(w):
    """往上找最近的 `QFrame#card`，返回 (卡片控件, 卡片标题)。

    ⚠ 标题挂的是 `statusLabel` 而不是 `cardTitle` —— 这一页的卡由
    `_create_inner_panel_card` 造，第一个 QLabel 用 `statusLabel`。
    ⭐ **第一版我按 x 区间划卡，当场被逮到**：左半边纵向叠着两张卡
    （倍率与灵敏度 / 偏移校准），区间把它们并成了一张，
    于是判据报「不齐」而实际上那是两张不同卡的两行。
    ⇒ 分卡这件事只能问控件树，不能问坐标。
    """
    from PySide6.QtWidgets import QFrame, QLabel

    p = w.parent()
    while p is not None:
        if isinstance(p, QFrame) and p.objectName() == "card":
            for lab in p.findChildren(QLabel):
                if lab.objectName() == "statusLabel":
                    return p, lab.text()[:16]
            return p, "<无题卡>"
        p = p.parent()
    return None, "<不在卡里>"


def _cards_with_rows(page):
    """返回 {卡片标题: [每行第一个控件的 (y, x, 控件)]}。

    ⭐ 每行只取最靠左那个：一行里并排的第二组（本页底部的 `X:` / `Y:`）
    本来就该错开，算进来会造出一条永远红的判据 —— 永远红和永远绿一样没用。
    """
    from PySide6.QtWidgets import QComboBox, QLineEdit, QSlider

    per_card: dict[str, list] = {}
    for w in (page.findChildren(QComboBox) + page.findChildren(QLineEdit)
              + page.findChildren(QSlider)):
        if not w.isVisibleTo(page):
            continue
        card, title = _card_of(w)
        if card is None:
            continue
        tl = w.mapTo(page, w.rect().topLeft())
        per_card.setdefault(title, []).append((tl.y(), tl.x(), w))

    out = {}
    for title, pts in per_card.items():
        rows: list[list] = []
        for y, x, w in sorted(pts):
            if rows and abs(rows[-1][0][0] - y) <= _ROW_BAND:
                rows[-1].append((y, x, w))
            else:
                rows.append([(y, x, w)])
        out[title] = [min(r, key=lambda t: t[1]) for r in rows]
    return out


@pytest.mark.parametrize("card", ["倍率与灵敏度", "热键与触发"])
def test_every_row_in_a_card_starts_at_the_same_left_edge(magnifier_page, card):
    cards = _cards_with_rows(magnifier_page)
    assert card in cards, (
        f"认不出「{card}」这张卡（认出来的是 {sorted(cards)}）——"
        f"识别规则或页面结构变了，这条判据在空转。")
    firsts = cards[card]
    assert len(firsts) >= 3, (
        f"「{card}」只认出 {len(firsts)} 行控件（至少该有 3 行）——"
        f"识别规则或页面结构变了，这条判据在空转。")
    edges = sorted({x for _, x, _ in firsts})
    assert len(edges) == 1, (
        f"「{card}」里各行的第一个控件左边缘有 {len(edges)} 种取值：{edges}\n"
        f"逐行：{[(w.__class__.__name__, x, y) for y, x, w in firsts]}\n"
        f"⭐ 同一张卡里的行只要不共用一个布局列，就没有任何东西让它们对齐。\n"
        f"⇒ 把这几行并进同一个 QGridLayout（第 0 列放行首标签），"
        f"**别用「量一遍再 setMinimumWidth」** —— 构造期和 Polish 期量到的都是"
        f"还没套样式表那一档字体，偏小，会给出一个很像成功的失败。")


def test_the_controls_keep_their_own_widths(magnifier_page):
    """对齐**不许**顺手改掉控件尺寸 —— 反向守卫。

    「左边缘全都一样」有一种很廉价的达成方式：把所有控件拉成同一个宽度。
    ⭐ 那在上面那条判据眼里是**满分通过**的，所以要一条盯结果的绊线。

    ⚠⚠ **这条判据的由来值得写下来。** 我原本以为它防的是
    「并进 QGridLayout 时不给 `AlignLeft`，下拉会被那条 180px 的滑块撑开」——
    破坏验证当场证明**那个机制是假的**：把 11 处 `AlignLeft` 全拿掉，
    几何逐字节不变。⇒ 这条判据留下来了，但它的理由换了：
    它不是「`AlignLeft` 的守卫」，是**「控件宽度」这个结果本身的绊线**，
    对任何把下拉拉宽的改法都有效（破坏验证用 `setMinimumWidth(200)` 构造）。
    ⭐⭐⭐ **一条判据可以是对的，而我给它写的理由是错的** ——
    两者都要验，而只有破坏验证能分开它们。
    """
    from PySide6.QtWidgets import QComboBox

    widths = sorted(w.width() for w in magnifier_page.findChildren(QComboBox)
                    if w.isVisibleTo(magnifier_page))
    assert widths, "一个可见下拉都没有 —— 判据在空转"
    assert max(widths) <= 150, (
        f"有下拉被拉宽到 {max(widths)}px（全部：{widths}）——"
        f"疑似 QGridLayout 的列宽被滑块撑开后灌给了下拉。"
        f"每一格都要给 `Qt.AlignLeft | Qt.AlignVCenter`。")


#: RN-569：热键卡里同一列的三个下拉。左边缘由 QGridLayout 管（上面那条判据），
#: **右边缘由它们的宽度管，而宽度以前是三处各写各的**（116 / 116 / 120）。
_ONE_COLUMN_COMBOS = ("primary_hotkey_combo", "secondary_hotkey_combo",
                      "trigger_mode_combo")


def test_no_hotkey_combo_has_an_unexplained_width(magnifier_page):
    """RN-569：同一列的三个下拉，宽度差**必须解释得清**。

    ⭐⭐⭐ 这条缺陷是 RN-566 **修好之后**才第一次被报出来的：左边缘拉齐以前，
    三个下拉起点各不相同（693 / 679 / 679），4px 的右缘差淹在里面看不见；
    左边缘一齐，那 4px 就成了唯一的不齐。
    ⇒ 同 RN-011 / RN-150 那一族：**一条修法会让另一条既有缺陷第一次变得可见。**
    ⚠ 外审那一发说的是「触发方式下拉异常横向拉伸占满整行」——
    实测左边缘 538/538/538 已齐、宽度 116/116/120，「占满整行」是假的（滑块 180
    才是列宽），「不一致」是真的。第四次印证「不整齐可信，哪个维度/多少不可信」。

    ⚠⚠ **这条判据为什么不是「右边缘必须相等」：** 三个下拉都是
    `AdjustToContents`，实际宽 = `max(minimumWidth, sizeHint)`。实测同一份代码——

        原生（177 个字体家族）：120 / 120 / 120   ← 修好了
        offscreen（假度量）  ：125 / 125 / 120   ← 内容撑的，不是缺陷

    ⭐⭐⭐ **一条按像素写死的判据，在没有真字体的环境里守不住这条修法。**
    真正守得住的是下面那条 AST 判据（「同出一源」）；这一条守的是**别的东西
    在偷偷撑宽它们**（比如列宽灌进来）。两条一起才覆盖得住。
    """
    facts = {}
    for name in _ONE_COLUMN_COMBOS:
        combo = getattr(magnifier_page, name, None)
        assert combo is not None, f"拿不到 {name} —— 判据在空转"
        assert combo.isVisibleTo(magnifier_page), f"{name} 不可见 —— 判据在空转"
        facts[name] = (combo.width(), combo.minimumWidth(),
                       combo.sizeHint().width())

    unexplained = {n: f for n, f in facts.items()
                   if f[0] != max(f[1], f[2])}
    assert not unexplained, (
        f"这几个下拉的宽度既不是它自己的下限、也不是它的内容宽：{unexplained}\n"
        f"（全部 名字:(宽, 下限, 内容宽) = {facts}）\n"
        f"⇒ 有别的东西在撑它们 —— 最可能是 QGridLayout 的列宽被那条 180px "
        f"的滑块撑开后灌了进来。每一格都要给 `Qt.AlignLeft | Qt.AlignVCenter`。")

    mins = sorted({f[1] for f in facts.values()})
    assert len(mins) == 1, (
        f"三个下拉的**下限**有 {len(mins)} 种取值：{mins}（{facts}）\n"
        f"⇒ 这正是 RN-569 的原状（116 / 116 / 120）。下限要同出一源。")


def test_that_one_width_really_has_one_source(magnifier_page):
    """反向绊线：宽度**恰好相等**和**同出一源**是两件事。

    ⭐ 上面那条判据在「三处各写 120」时也是满分通过的 —— 而那正是缺陷的原状
    （三处各写各的，只是当时其中一处写岔了 4px）。
    ⇒ 这条查的是**源**：那三行 `setMinimumWidth` 的实参必须是同一个名字。
    """
    import ast
    from pathlib import Path

    src = Path(magnifier_page.__class__.__module__.replace(".", "/"))
    path = REPO / f"{src}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    args = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setMinimumWidth"):
            continue
        target = node.func.value
        if not (isinstance(target, ast.Attribute)
                and target.attr in _ONE_COLUMN_COMBOS):
            continue
        arg = node.args[0] if node.args else None
        args[target.attr] = (arg.id if isinstance(arg, ast.Name)
                             else f"字面量 {getattr(arg, 'value', arg)!r}")

    assert set(args) == set(_ONE_COLUMN_COMBOS), (
        f"只找到 {sorted(args)} 的 setMinimumWidth —— 判据在空转")
    sources = set(args.values())
    assert len(sources) == 1 and not next(iter(sources)).startswith("字面量"), (
        f"三个下拉的最小宽度不是同一个来源：{args}\n"
        f"⭐ 三处各写一个数，即使今天恰好相等，下一次改动也只会改一处 —— "
        f"RN-569 就是这么来的（116 / 116 / 120）。")
