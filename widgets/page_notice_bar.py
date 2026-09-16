# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""页内提示条：一句话 + 可选「撤销」+「知道了」（2026-09-16）。

## 为什么不用弹窗

击杀图标页那条注释逐字写着理由：**导入一次要点两三个模态框，
是这一页最伤"亲民"的地方；提示条还能挂一个「撤销」——弹窗关掉就没了。**

⭐ 而资源导入比击杀图标更需要它：一次导入可能同时有
「认出了几类」「有几条会不响」「有几个冲突跳过了」三种话要说，
三个弹窗排队点过去，用户会把最后一个也当成"确定"点掉。

## 为什么做成组件

击杀图标页那份是**手搓**的（一个 QFrame 自己认领卡片那个 objectName），
而棘轮 `HANDROLLED_CARD_MAX` 只许减不许增。⇒ 再手搓一个就红。

⚠⚠ 上面这句话原本是照着那行代码**原样写**的，结果**被棘轮算成了第 49 处** ——
它数的是字面形态，分不出「这是在调用」还是「这是在注释里谈论它」。
⭐ 而那条棘轮的注释里逐字预言过这件事（批 16 同款，连数字都是 49）：
**一条按正则数「有没有做某件事」的棘轮，会把「谈论那件事」也算进去。**
⇒ 处置是改这句话，不是放宽棘轮 —— 写文档的人绕开一句话，比棘轮空出一格便宜。
⭐ 更要紧的是：手搓第二份意味着两条提示条会各自漂
（一个有撤销、一个没有；一个能换行、一个不能）。

⚠ 本组件**不叫 card**：它是一条细提示，不是卡片。
⛔ 这不是为了绕开棘轮 —— 真要当卡片用，该用 `SettingsCard`。
"""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class PageNoticeBar(QFrame):
    """页内提示条。默认隐藏，`show_message()` 才露面。"""

    def __init__(self, parent=None, undo_text="撤销", dismiss_text="知道了"):
        super().__init__(parent)
        self.setObjectName("noticeBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.label = QLabel("")
        self.label.setObjectName("hintLabel")
        # ⚠ 必须能换行：导入的提示话很长（"这套素材里认不出「拆除」那一声…"），
        #   不换行就会把整条撑出页面，而排版审计看不见"撑出去"这一类。
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)

        self.undo_btn = QPushButton(undo_text)
        self.undo_btn.setObjectName("secondaryButton")
        self.undo_btn.setFixedHeight(26)
        self.undo_btn.hide()
        layout.addWidget(self.undo_btn)

        self.dismiss_btn = QPushButton(dismiss_text)
        self.dismiss_btn.setObjectName("secondaryButton")
        self.dismiss_btn.setFixedHeight(26)
        self.dismiss_btn.clicked.connect(self.clear)
        layout.addWidget(self.dismiss_btn)

        self._undo_callback = None
        self.hide()

    def show_message(self, message: str, undo_callback=None) -> None:
        """`undo_callback` 给了才显示「撤销」。

        ⭐ 撤销按钮的有无**跟着能不能撤销走**，不跟着"这次是不是导入"走 ——
        一个点下去什么都不会发生的撤销按钮，比没有还糟。
        """
        self._undo_callback = undo_callback
        self.label.setText(str(message or ""))
        self.undo_btn.setVisible(callable(undo_callback))
        try:
            self.undo_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        if callable(undo_callback):
            self.undo_btn.clicked.connect(self._on_undo)
        self.show()

    def clear(self) -> None:
        self._undo_callback = None
        self.label.setText("")
        self.undo_btn.hide()
        self.hide()

    def _on_undo(self) -> None:
        callback = self._undo_callback
        # ⚠ 先摘钩子再执行：撤销本身会调 `show_message` 报结果，
        #   不摘的话那一次会把自己的回调又挂回去，点第二下就重复撤销。
        self._undo_callback = None
        self.undo_btn.hide()
        if callable(callback):
            callback()
