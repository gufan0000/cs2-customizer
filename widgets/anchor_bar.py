# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""页内锚点条：一排「跳到本页某一段」的芯片（RN-443 / RN-431 / X2，批 66）。

## 为什么要有这一个共用件

`advanced` 与 `magnifier` 各写了一份 `_build_anchor_chips()`。
**分区怎么找**确实是两页各自的事（一个扫 `SettingsCard`，一个还要扫内层
`QFrame#card`），但**芯片长什么样、点下去怎么滚、当前在哪一段**这三件事
两页应该一模一样 —— 而实测它们不一样，且其中一份是错的：

⭐⭐⭐ **`magnifier` 的注释里逐字写着 `ensureWidgetVisible` 是错的跳法**
（「它只做最小滚动使其可见，对高卡片会滚到把**底部**露出来，
实测点第一个锚点反而向下滚了 83px，与『跳到这一节』的语义相反」），
**而 `advanced` 一直在用那个跳法**。批 66 实测：`advanced` 从页面底部点第一颗
「目录」，停在 **197** 而不是 0 —— 那一节的顶部还在视口上面。
⇒ **同一件事有两份实现，其中一份已经被另一份写下的字证明是错的。**

## 这一排要回答用户的两个问题

| 外审说的 | 这里的答案 |
|---|---|
| RN-443「外观呈现分页 Tab 样式，误以为点击是在切换独立子页面」（改前 12 发里 6 发判中/高） | 前面加一个**前导词**，直说这是「跳到」；芯片不再是一整排等宽方块 |
| RN-431「10 个密集标签缺乏激活态指示，**分不清是切页还是锚点**」 | 芯片可选中，**跟着滚动位置走** —— 当前在哪一段就高亮哪一颗 |

⚠ 高亮**不用定时器**：跟着 `valueChanged` 走（同 RN-146 那条 ——
「回到这一页」是一个确定的时刻，「每隔一秒」不是）。
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLabel, QPushButton

#: 芯片顶到视口上沿时留的余量（px）。两页原来一个写 12、一个写 16，
#: 差别没有理由 —— 收成一个数。
_JUMP_MARGIN = 12


def _section_top(widget, body) -> int:
    return widget.mapTo(body, QPoint(0, 0)).y()


def _is_ancestor(maybe_parent, widget) -> bool:
    node = widget.parentWidget()
    while node is not None:
        if node is maybe_parent:
            return True
        node = node.parentWidget()
    return False


def drop_container_sections(sections):
    """把「自己就装着别的锚点」的那几段去掉，只留叶子（RN-552）。

    ⚠ **不是「只留顶层」——两者方向正好相反**：`magnifier` 只扫顶层的话
      锚点只剩 2 个，而用户想直达的恰恰是那几个内层分区（调用方早否过那条路）。
    ⚠ 只在**这一排自己**的范围内判祖先。完整理由与实测见 `tests/test_the_bottom_bar_stops_shouting.py`。
    """
    widgets = [w for _t, _s, w in sections]
    return [
        (title, short, target) for title, short, target in sections
        if not any(other is not target and _is_ancestor(target, other)
                   for other in widgets)
    ]


def install_anchor_chips(bar_layout, scroll, sections, *, lead="跳到：") -> list:
    """把 `sections` 装成一排锚点芯片，返回芯片列表。

    参数
    ----
    bar_layout : 承载芯片的 layout（两页都是 FlowLayout）
    scroll     : 页面的 QScrollArea
    sections   : [(完整标题, 短标题, 目标控件), ...]，**顺序即滚动顺序**
    lead       : 前导词；给 None 就不加（留给方案对照用）

    ⚠ 目标控件必须在 `scroll.widget()` 里面 —— 滚动区外面的卡片
      做锚点点了也不会动（`magnifier` 的「当前状态」卡就在外面）。
    """
    body = scroll.widget()
    if body is None:
        return []

    # RN-552：装着别的锚点的那几段先去掉（见 `drop_container_sections`）。
    # ⚠ 放在这里而不是让两页各自去掉 —— 批 66 的教训逐字：
    #   「同一件事有两份实现，其中一份已经被另一份写下的字证明是错的」。
    sections = drop_container_sections(list(sections))

    if lead:
        tip = QLabel(lead)
        tip.setObjectName("anchorLead")
        bar_layout.addWidget(tip)

    chips = []
    for title, short, target in sections:
        chip = QPushButton(short)
        # UP-017：不复用 secondaryButton —— 那会吃到 min-width:80，白占宽还提前换行。
        # 高度也只在 QSS 里声明一次（RN-547 残余，批 66）。
        chip.setObjectName("anchorChip")
        chip.setCursor(Qt.PointingHandCursor)
        chip.setToolTip(f"跳到本页的「{title}」")
        # RN-431：可选中 = 屏幕上有「当前在哪一段」这件事。
        # ⚠ 不用 autoExclusive：那会让「点一下就一定选中」，
        #   而这里的选中态由**滚动位置**决定，不由点击决定。
        chip.setCheckable(True)
        chip.clicked.connect(
            lambda _=False, t=target: scroll.verticalScrollBar().setValue(
                max(0, _section_top(t, body) - _JUMP_MARGIN)
            )
        )
        bar_layout.addWidget(chip)
        chips.append((chip, target))

    if not chips:
        return []

    def _sync(_value=None):
        """当前所在的那一段。两条规矩都是实测逼出来的（批 66）：

        ⚠ **末尾那几段顶不上去。** `advanced` 最后 3 颗、`magnifier` 最后 1 颗
          的顶沿在「内容高 - 视口高」之下，点它们只能滚到底。
          若还按「越过视口上沿的最后一个」算，滚到底时高亮会停在**统计**上，
          而用户刚点的是**配置** —— ⭐ 屏幕上的反馈说他点错了，其实是页面到头了。
          ⇒ 滚到底时改问「顶沿还落在视口里的最后一段是谁」。

        ⚠ **并排的两段顶沿相同。** `magnifier` 的「倍率」和「热键」实测都在 y=74，
          按「最后一个」算会变成点「倍率」却高亮「热键」。⇒ 同高取第一个。
        """
        sb = scroll.verticalScrollBar()
        value = sb.value()
        at_bottom = sb.maximum() > 0 and value >= sb.maximum() - 1
        limit = (value + scroll.viewport().height()
                 if at_bottom else value + _JUMP_MARGIN + 1)

        current, current_top = 0, None
        for i, (_c, target) in enumerate(chips):
            y = _section_top(target, body)
            if y <= limit and (current_top is None or y > current_top):
                current, current_top = i, y
        for i, (chip, _t) in enumerate(chips):
            want = i == current
            if chip.isChecked() != want:
                chip.setChecked(want)

    scroll.verticalScrollBar().valueChanged.connect(_sync)
    _sync()
    return [c for c, _t in chips]
