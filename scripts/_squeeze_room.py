# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""「这个标签还有没有地方可以变宽」——挤压审计的量尺（RN-505，2026-09-05 批 51）。

## 为什么单独拆出来

`squeezed_label_audit.py` 原来拿 **`parentWidget().width()`** 当可用宽度：

    spare = parent.width() - label.width()

而一个标签的可用宽度**不是它父控件的宽度**，是**它所在那一格的宽度**。
放在竖排里的标签，每一项本来就占满整列 —— 它的宽度由**同排的兄弟**或
布局的伸缩比决定，折行是设计，不是缺陷。用父控件宽度去量，这一类**必然全报**。

实测：这支审计从上线那天起就是 rc=1，报的两条**都是这一类**：

| 页 | 标签 | 真相 |
|---|---|---|
| `kill_icon` | `previewEffectCaption` | 页面显式 `setMaximumWidth(212)`，跟它上面那块 212px 宽的预览对齐 |
| `screen_effects` | `hintLabel` | 它在一个 `addLayout(column, 4)` 的竖排列里，宽度是伸缩比分的 |

⭐⭐ 一道长期 rc=1 的门禁，跑的人会开始把红当成常态 ——
那时它再逮到新问题也没人看得出来。⇒ **要么修掉，要么它量的就不是那件事。**
这次是后者。

## 改成量什么

**同一格里到底空着多少**：拿标签所在那个 `QLayout` 的几何，减掉
所有**实体项**（控件 / 子布局）占掉的宽度和间距 —— 剩下的才是没人要的空间。

⚠ **弹簧项（`addStretch` / spacer）不算占用**：它正是「这里空着」的表达方式。
原始那条真缺陷（crosshair 标题行：拿到 120px、需要 156px，同一行空着 928px）
就是靠弹簧空出来的 —— 把弹簧算进占用，这支审计就再也逮不到它了。
"""
from __future__ import annotations

QWIDGETSIZE_MAX = (1 << 24) - 1


def owning_layout(root, widget):
    """找出**直接**放着 `widget` 的那个布局；找不到返回 None。"""
    from PySide6.QtWidgets import QLayout

    for layout in root.findChildren(QLayout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is not None and item.widget() is widget:
                return layout
    return None


def declared_own_width(widget) -> bool:
    """页面有没有**显式声明过**这个标签的行长上限。

    `setMaximumWidth(212)` 是一句「我这一列就这么宽」的声明 ——
    撞着自己的声明折行，是意图，不是被挤。
    ⭐ 这是「用证据换例外」（RN-524），不是名单白名单：
    证据是产品代码里那一行声明，任何一页写了都算，谁都不用登记。

    ⚠⚠ **`setFixedWidth` 不算这种声明。** 它把 min 和 max 一起设死，
    在 Qt 里和「只设上限」长得一模一样 —— 而它多半是一句**摆位置的硬尺寸**，
    那正是这支审计要逮的东西（RN-442 逐字记着：全站 146 颗按钮的固定尺寸
    声明一个像素都不生效）。
    ⭐ 这条例外是本批新写这条判据时**当场被它自己逮住的**：第一版把
    `setFixedWidth(120)` 也当成了意图，于是它会把**原始那条真缺陷**一并放过。
    ⇒ 只有「上限 < 上限以外还能更窄」（min < max）才算声明行长。
    """
    cap = widget.maximumWidth()
    if not (0 < cap < QWIDGETSIZE_MAX):
        return False
    if widget.minimumWidth() >= cap:            # setFixedWidth：硬尺寸，不是行长意图
        return False
    return widget.width() >= cap - 1


def room_in_cell(layout) -> int:
    """`layout` 这一格里还空着多少宽度（没人要的那部分）。"""
    if layout is None:
        return 0
    margins = layout.contentsMargins()
    avail = layout.geometry().width() - margins.left() - margins.right()
    used = 0
    solid = 0
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        if item.widget() is not None or item.layout() is not None:
            used += item.geometry().width()
            solid += 1
    used += max(0, solid - 1) * max(0, layout.spacing())
    return max(0, avail - used)
