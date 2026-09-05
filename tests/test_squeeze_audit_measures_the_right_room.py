# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""挤压审计量的必须是「**这一格**里还空着多少」，不是父控件有多宽（RN-505）。

## 缺陷

`scripts/squeezed_label_audit.py` 上线（批 40）那天起就是 **rc=1**，报 2 条：
`kill_icon` 的 `previewEffectCaption` 与 `screen_effects` 的 `hintLabel`。
批 43 用 `git stash` 复验过「不是我这一批引入的」，于是它就一直红着。

**两条都是假的。** 它拿 `parentWidget().width()` 当可用宽度，而一个标签
能不能变宽由**它所在那一格**说了算：
· `previewEffectCaption` 页面显式 `setMaximumWidth(212)`（跟上面 212px 的预览对齐）；
· `screen_effects` 那句在一个 `addLayout(column, 4)` 的**竖排列**里，宽度是伸缩比分的。
竖排里的每一项本来就占满整列 —— 拿父控件宽度去量，这一类**必然全报**。

⭐⭐ **一道长期 rc=1 的门禁，跑的人会开始把红当成常态** ——
那时它再逮到新问题也没人看得出来。

## 这条判据看着什么

量尺（`scripts/_squeeze_room.py`）本身：给它造真的 Qt 布局，
断言它在「同排真的空着」时报得出来、在「竖排本来就满」时不报。
⛔ 不在测试里重写一遍那套算法（RN-513：那样测的是测试自己的那一份）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from _squeeze_room import (  # noqa: E402
    declared_own_width,
    owning_layout,
    room_in_cell,
)

pytestmark = pytest.mark.usefixtures("qapp")


def _laid_out(build):
    """建一个 400px 宽的容器，跑完布局，返回 (容器, 你建的东西)。"""
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    made = build(host)
    host.resize(400, 200)
    host.show()
    host.hide()                       # 只要布局跑一遍，不要真出现在屏幕上
    host.layout().activate()
    return host, made


def test_a_label_in_a_row_with_slack_still_gets_reported():
    """⭐ 锚：原始那条真缺陷的形状 —— 横排里一句话被挤到折行，而同排空着一大片。

    这是这支审计**唯一**逮到过的真东西（crosshair 标题行：拿到 120px、
    需要 156px、同一行空着 928px）。改量尺之后它必须还报得出来，
    否则我不是修好了它，是把它弄瞎了。
    """
    from PySide6.QtWidgets import QHBoxLayout, QLabel

    def build(host):
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        label = QLabel("统一管理准心方案")
        label.setWordWrap(True)
        label.setFixedWidth(120)
        row.addWidget(label)
        row.addStretch(1)             # ⭐ 空着的那 280px 就是靠它表达的
        return label

    host, label = _laid_out(build)
    spare = room_in_cell(owning_layout(host, label))
    assert spare > 200, f"同排明明空着 ~280px，量出来只有 {spare}"
    assert not declared_own_width(label), "没写过 maximumWidth，不该算成声明"


def test_a_label_in_a_column_is_not_squeezed_just_because_the_page_is_wide():
    """竖排里的标签占满整列 —— 它折行是因为列窄，不是因为被挤。

    这正是 `screen_effects` 那条假报的形状。
    """
    from PySide6.QtWidgets import QLabel, QVBoxLayout

    def build(host):
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(QLabel("当前状态"))
        label = QLabel("打开总开关并勾选后，两个预览按钮才能用来直接验证观感。")
        label.setWordWrap(True)
        column.addWidget(label)
        column.addStretch(1)
        return label

    host, label = _laid_out(build)
    assert room_in_cell(owning_layout(host, label)) == 0, (
        "竖排每一项都占满整列，这一格没有空着的横向空间")


def test_an_explicit_max_width_is_a_declaration_not_a_squeeze():
    """`setMaximumWidth(212)` 是一句「我这一列就这么宽」——撞着它折行是意图。

    ⭐ 用**证据**换例外（RN-524 那次定的规矩），不是名单白名单：
    证据是产品代码里那一行声明，哪一页写了都算。
    """
    from PySide6.QtWidgets import QLabel, QVBoxLayout

    def build(host):
        column = QVBoxLayout(host)
        label = QLabel("总开关关着——这里画的东西，游戏里现在看不到。")
        label.setWordWrap(True)
        label.setMaximumWidth(212)
        column.addWidget(label)
        return label

    host, label = _laid_out(build)
    assert declared_own_width(label), "页面声明过宽度，应当算作意图"

    plain = QLabel("同一句话，没有声明宽度")
    assert not declared_own_width(plain)

    # ⚠⚠ `setFixedWidth` 把 min 和 max 一起设死，Qt 里和「只设上限」一模一样 ——
    #   而它多半是一句摆位置的硬尺寸，**正是这支审计要逮的东西**。
    # ⭐ 这一条是写完上面那一句当场被它自己逮住的：第一版会把
    #   原始那条真缺陷（固定宽 120px 的标题行提示）一并放过。
    fixed = QLabel("摆位置用的硬尺寸")
    fixed.setFixedWidth(120)
    assert not declared_own_width(fixed), "setFixedWidth 不是行长意图，不该免检"


def test_the_stretch_is_free_space_not_an_occupant():
    """⚠ 弹簧不算占用 —— 它**正是**「这里空着」的写法。

    把 `addStretch` 算进占用，这支审计就再也逮不到任何东西：
    真缺陷的那片空白全是弹簧撑出来的。
    """
    from PySide6.QtWidgets import QHBoxLayout, QLabel

    def build(host):
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        label = QLabel("短")
        label.setFixedWidth(100)
        row.addWidget(label)
        row.addStretch(1)
        return label

    host, label = _laid_out(build)
    assert room_in_cell(owning_layout(host, label)) == pytest.approx(300, abs=8)


def test_owning_layout_finds_the_cell_not_an_ancestor():
    """要的是**直接**放着它的那一格；拿到祖先布局就等于又回到「父宽」那套。"""
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

    def build(host):
        outer = QVBoxLayout(host)
        inner = QHBoxLayout()
        label = QLabel("我在内层")
        inner.addWidget(label)
        inner.addStretch(1)
        outer.addLayout(inner)
        outer.addStretch(1)
        return label, inner

    host, (label, inner) = _laid_out(build)
    assert owning_layout(host, label) is inner
