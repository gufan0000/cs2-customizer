# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable fixed bottom action bar for settings pages."""

from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class PageActionBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageActionBar")
        self._primary_callback = None
        self._secondary_callback = None
        self._extra_callback = None
        # RN-407：页面自己写的那一截状态文案。回执由 `_effect_state()` 现算
        # （真源是那颗开关），不在这儿存第二份。
        self._base_message = ""
        #: 这一截是不是富文本（页面显式声明）。⛔ 默认 False —— 见 `set_message`。
        self._message_is_rich = False
        self._init_ui()

    #: 这一排按钮的高度。⭐ RN-549（批 66）：**同一排、同一角色的按钮，高度只有这一处声明。**
    #: 页面往这排里插按钮时走 `adopt_button()`，别自己写第二个数。
    SECONDARY_HEIGHT = 36
    PRIMARY_HEIGHT = 38

    def adopt_button(self, btn, *, primary: bool = False):
        """把页面自己造的按钮收进这一排，按这一排的规矩钉住高度。

        ⭐⭐⭐ RN-549 是这么来的：`gun_sound` 往这排里插了一颗
        「应用到全部武器…」，写的是 `setMinimumHeight(30)` —— **只给下限、不给上限**。
        而 `mark_compact_buttons()` 只认「调用点声明的 max 比 QSS 下限还小」的按钮，
        于是这一颗没被认出来，QSS 那条 `min-height: 36px`（内容盒，加 padding 8×2
        + border 1×2 折成 **54**）原样留在它身上 ⇒ 同一排 36 / 38 / **54**，
        紧凑档里肉眼可见地歪（外审 2/3 发独立报「同组控件高度与排版不一致」）。
        ⚠ 而这一排在批 63 之前是齐的（三颗都被那条下限顶到 54）——
        **是批 63 把认得出的那两颗降下来、认不出的这颗留在原地，那一排才歪的。**
        ⭐ 一次「把大部分修好」的改动，会把「全都一样地不对」变成「参差不齐」。
        """
        btn.setObjectName("primaryButton" if primary else "secondaryButton")
        btn.setFixedHeight(self.PRIMARY_HEIGHT if primary else self.SECONDARY_HEIGHT)
        return btn

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)

        self.message_label = QLabel("")
        self.message_label.setObjectName("hintLabel")
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        from widgets.page_route import wire_page_routes

        wire_page_routes(self.message_label)     # RN-528：接一次线就够
        # ⛔⛔ RN-589：**默认必须显式钉成 PlainText**，不许留给 Qt 的 `AutoText` 去猜 ——
        #   这条回执里过的多半是用户自己起的字。叙事与实测见
        #   `tests/test_the_bottom_bar_stops_shouting.py` 那条同名判据。
        self.message_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.message_label, 1)

        # v2.2.1: 第三按钮（如"新建风格"），与 secondary 同级样式
        self.extra_btn = QPushButton("")
        self.extra_btn.setObjectName("secondaryButton")
        self.extra_btn.setFixedHeight(self.SECONDARY_HEIGHT)
        self.extra_btn.hide()
        layout.addWidget(self.extra_btn, 0)

        self.secondary_btn = QPushButton("")
        self.secondary_btn.setObjectName("secondaryButton")
        self.secondary_btn.setFixedHeight(self.SECONDARY_HEIGHT)
        self.secondary_btn.hide()
        layout.addWidget(self.secondary_btn, 0)

        self.primary_btn = QPushButton("")
        self.primary_btn.setObjectName("primaryButton")
        self.primary_btn.setFixedHeight(self.PRIMARY_HEIGHT)
        self.primary_btn.hide()
        layout.addWidget(self.primary_btn, 0)

    def _effect_state(self) -> bool | None:
        """这一页的总开关现在是开是关；这一页没有总开关就返回 None。

        ⭐⭐ **回执的真源是那颗开关自己，不是「有没有人来通知过我」。**
        第一版是让 `MasterSwitchRow` 拨过来一个布尔存着，而那件事挂在一个
        `singleShot(0)` 上 —— 于是「页面建完但事件循环还没转过」的那一瞬间，
        底栏一个字都不说。三条既有判据当场逮到（crosshair 两条 + 排版一条）。
        ⚠ 那不是"少了一次刷新"，是**回执的正确性依赖了一次时序**。
        同 RN-417：量不稳的东西就别去量它的值，去量决定那个值的规则。
        """
        node = self.parentWidget()
        while node is not None:
            row = getattr(node, "master_switch_row", None)
            if row is not None and hasattr(row, "is_checked"):
                return bool(row.is_checked())
            node = node.parentWidget()
        return None

    def _owner_page(self):
        """沿父链找到**挂着总开关的那个节点** —— 那就是这一页。

        ⚠ 走的是和 `_effect_state()` 完全同一条路径，不另开一条 ——
        ⭐ 两条各自遍历的查找逻辑，会在某一天指向不同的对象，
          而那一天没有任何一处会报错（RN-002 那 9 份名单的形态）。
        """
        node = self.parentWidget()
        while node is not None:
            if getattr(node, "master_switch_row", None) is not None:
                return node
            node = node.parentWidget()
        return None

    def refresh_effect_state(self):
        """总开关动了 —— 把这一条回执重算一遍。"""
        self._render_message()

    def set_message(self, text: str, *, rich: bool = False):
        """底栏那一条回执。

        ⛔ `rich=True` 显式给，只给真嵌了 `page_route(...)` 链接的那几处（RN-528、RN-589）；
        富文本档下**调用方负责自己那一截是安全的 HTML**。
        """
        self._base_message = str(text or "")
        self._message_is_rich = bool(rich)
        self._render_message()

    def _render_message(self):
        """RN-407 第①件：把「改的东西现在生不生效」收进底栏这一条回执。

        ⚠⚠ 批 10 我在 crosshair 底栏写的是**无条件**的
        「改动已自动保存，不用点任何按钮。」——它在总开关开着时是真话，
        关着时是假话。外审对它的判词：现状 4/4 高、候选 C 6/6 高，
        是这条缺陷里票数最高的一项。
        ⭐ **一句只在某个状态下为真的回执，在别的状态里就是一句谎。**

        拼在这儿而不是让各页自己拼，是因为**页面会在任意时刻再调一次
        `set_message`**（各页的 `_sync_action_bar`）。让它自己拼的话，
        回执随时会被下一次刷新冲掉，而且不会有任何一处报错。
        ⭐⭐ 一条守卫的输入如果能被一次常规操作顺手改写，那条守卫就不是守卫。
        """
        # ⚠⚠ 批 24：这两句里都写着「自动保存 / 不用点任何按钮」，而批 16
        # 把它当成了**全站事实**。实测 15 页里 **2 页不是**（`hud_color` 摆着
        # 「保存 HUD 规则」、`magnifier` 摆着「应用」）—— 于是同一行底栏里，
        # 左边说「不用点任何按钮」，右边就是那颗必须点的按钮。
        # ⭐⭐ **一句被当成全站事实的话，只要有一页不成立，它在那一页就是假的** ——
        #   而共用件让它假得整整齐齐，15 页一个模子。
        # ⇒ 那句话跟着**这一页的真实行为**走（`SAVES_AUTOMATICALLY`）。
        from widgets.master_switch_effect import (
            ACTION_BAR_OFF_TEXT, ACTION_BAR_OFF_TEXT_MANUAL,
            ACTION_BAR_ON_TEXT, ACTION_BAR_ON_TEXT_MANUAL,
            saves_automatically,
        )

        enabled = self._effect_state()
        parts = []
        if enabled is not None:
            auto = saves_automatically(self._owner_page())
            if enabled:
                parts.append(ACTION_BAR_ON_TEXT if auto else ACTION_BAR_ON_TEXT_MANUAL)
            else:
                parts.append(ACTION_BAR_OFF_TEXT if auto else ACTION_BAR_OFF_TEXT_MANUAL)
        fixed = "".join(parts)          # 上面那句固定回执，是我们自己的常量
        body = self._base_message       # 页面给的那一截
        if self._message_is_rich:
            # 固定回执转义（它是纯文本），页面那截原样（调用方保证它是安全 HTML）。
            message = html.escape(fixed) + body
            self.message_label.setTextFormat(Qt.RichText)
            # ⛔⛔ tooltip 必须去标签：不然一嵌链接就多出一个**点不动的**副本（RN-578）。
            tooltip = html.unescape(re.sub(r"<[^>]+>", "", message))
        else:
            message = fixed + body
            self.message_label.setTextFormat(Qt.PlainText)
            tooltip = message
        self.message_label.setText(message)
        self.message_label.setToolTip(tooltip)

    def set_primary_pending(self, pending: bool | None):
        """这颗主按钮现在有没有「待提交的东西」（RN-504）。

        ⚠ 只有**提交型**按钮该调；「打开音频资源」那类**动作**按钮传 `None`
        或者干脆别调 —— **由页面自己声明，不靠猜文案**（批 50 RN-524）。
        完整理由见 `tests/test_the_bottom_bar_stops_shouting.py`。
        """
        btn = self.primary_btn
        value = None if pending is None else ("true" if pending else "false")
        if btn.property("fp_pending") == value:
            return
        btn.setProperty("fp_pending", value)
        # ⚠ 动态属性改完必须重新 polish，否则样式表不会重算（全仓惯例）
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()
        # ⛔⛔ RN-504（批 82 定案）：**没有待提交内容时，这颗按钮不出现。**
        #
        #   批 81 外审 6/6 逐字指认它就是承重物：「即使状态栏标注了『保存·已存下』，
        #   但右下角**常驻可点击的**『保存 HUD 规则』按钮依然会让玩家怀疑
        #   设置尚未自动保存完成」——⭐ 降色（`fp_pending=false`）只改了颜色，
        #   而**在场并可点**本身就是那句「还有一件必须做的事没做」。
        #
        #   ⭐⭐⭐ 批 82 三组 A/B 定案（票数与地板读数见档案
        #   `CS2 Customizer_翻新工程/档案/X_说明那件事的话不是那件事.md`）：
        #   **隐藏 不会 12/12 / 禁用（置灰）会 12/12 / 改前 会 12/12** ⇒
        #   **「在场但不可点」和「不在场」完全不是一回事，而那个差别就是全部的效果。**
        #   ⚠ 这正面证实了 RN-174 在册的反向证据（置灰的按钮会被当成保存/应用）。
        #   ⛔ 不改文案（RN-506）。⚠ 只对**提交型**按钮生效（动作按钮传 None，一律不碰）。
        if value is not None:
            btn.setVisible(value == "true")

    def configure_primary(self, text: str, callback=None, *, visible: bool = True):
        self.primary_btn.setText(str(text or ""))
        if self._primary_callback:
            try:
                self.primary_btn.clicked.disconnect(self._primary_callback)
            except Exception:
                pass
        if callback:
            self.primary_btn.clicked.connect(callback)
        self._primary_callback = callback
        self.primary_btn.setVisible(bool(visible))

    def configure_secondary(self, text: str, callback=None, *, visible: bool = True):
        self.secondary_btn.setText(str(text or ""))
        if self._secondary_callback:
            try:
                self.secondary_btn.clicked.disconnect(self._secondary_callback)
            except Exception:
                pass
        if callback:
            self.secondary_btn.clicked.connect(callback)
        self._secondary_callback = callback
        self.secondary_btn.setVisible(bool(visible))

    def configure_extra(self, text: str, callback=None, *, visible: bool = True):
        self.extra_btn.setText(str(text or ""))
        if self._extra_callback:
            try:
                self.extra_btn.clicked.disconnect(self._extra_callback)
            except Exception:
                pass
        if callback:
            self.extra_btn.clicked.connect(callback)
        self._extra_callback = callback
        # RN-649：空文本 = 没内容 = 藏（全仓无 icon-only 用法，判据守着这个前提）
        self.extra_btn.setVisible(bool(visible) and bool(str(text or "").strip()))
