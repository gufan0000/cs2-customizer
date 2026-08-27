# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable fixed bottom action bar for settings pages."""

from __future__ import annotations

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
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)

        self.message_label = QLabel("")
        self.message_label.setObjectName("hintLabel")
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        layout.addWidget(self.message_label, 1)

        # v2.2.1: 第三按钮（如"新建风格"），与 secondary 同级样式
        self.extra_btn = QPushButton("")
        self.extra_btn.setObjectName("secondaryButton")
        self.extra_btn.setFixedHeight(36)
        self.extra_btn.hide()
        layout.addWidget(self.extra_btn, 0)

        self.secondary_btn = QPushButton("")
        self.secondary_btn.setObjectName("secondaryButton")
        self.secondary_btn.setFixedHeight(36)
        self.secondary_btn.hide()
        layout.addWidget(self.secondary_btn, 0)

        self.primary_btn = QPushButton("")
        self.primary_btn.setObjectName("primaryButton")
        self.primary_btn.setFixedHeight(38)
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

    def refresh_effect_state(self):
        """总开关动了 —— 把这一条回执重算一遍。"""
        self._render_message()

    def set_message(self, text: str):
        self._base_message = str(text or "")
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
        from widgets.master_switch_effect import (
            ACTION_BAR_OFF_TEXT, ACTION_BAR_ON_TEXT,
        )

        enabled = self._effect_state()
        parts = []
        if enabled is not None:
            parts.append(ACTION_BAR_ON_TEXT if enabled else ACTION_BAR_OFF_TEXT)
        if self._base_message:
            parts.append(self._base_message)
        message = "".join(parts)
        self.message_label.setText(message)
        self.message_label.setToolTip(message)

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
        self.extra_btn.setVisible(bool(visible))
