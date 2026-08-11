# SPDX-License-Identifier: GPL-3.0-or-later
"""SettingsRow — label + 控件 + 可选 hint 的统一横排.

最常见的设置项布局:
    [启用功能]      [toggle]    [hint 文字]
    [声音音量]   [滑块]   [80%]
    [自定义路径]  [输入框]                [浏览]

替代每个 page 反复写:
    row = QHBoxLayout()
    row.addWidget(QLabel("启用"))
    row.addStretch()
    row.addWidget(toggle)
    layout.addLayout(row)

新写法:
    row = SettingsRow("启用功能", control=my_toggle)
    layout.addWidget(row)

    # 或带值显示和 hint:
    row = SettingsRow("音量", control=slider, value="80%", hint="拖动调整")
    layout.addWidget(row)
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QVBoxLayout, QWidget
)


class SettingsRow(QWidget):
    """单行设置项.

    构造:
        SettingsRow(label, control=None, value=None, hint=None,
                    label_min_width=None, control_align="right", parent=None)

    属性:
        label_widget: QLabel
        control_widget: QWidget | None
        value_widget: QLabel | None
        hint_widget: QLabel | None
        row: QHBoxLayout  — 主横排,允许进一步 add_widget

    control_align 取值:
        "right" — label 靠左,控件靠右(中间 stretch),最常见
        "left" — label + 控件 紧挨在左,右侧 stretch(如 toggle 紧贴 label)
    """

    def __init__(
        self,
        label: str,
        control: QWidget | None = None,
        value: str | None = None,
        hint: str | None = None,
        label_min_width: int | None = None,
        control_align: str = "right",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        self.row = QHBoxLayout()
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(8)

        self.label_widget = QLabel(label)
        if label_min_width:
            self.label_widget.setMinimumWidth(label_min_width)
        self.row.addWidget(self.label_widget)

        self.control_widget = control
        self.value_widget: QLabel | None = None
        self.hint_widget: QLabel | None = None

        if control_align == "right":
            self.row.addStretch()
            if control is not None:
                self.row.addWidget(control)
            if value is not None:
                self.value_widget = QLabel(value)
                self.value_widget.setObjectName("valueLabel")
                self.value_widget.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.row.addWidget(self.value_widget)
        else:  # "left"
            if control is not None:
                self.row.addWidget(control)
            if value is not None:
                self.value_widget = QLabel(value)
                self.value_widget.setObjectName("valueLabel")
                self.row.addWidget(self.value_widget)
            self.row.addStretch()

        outer.addLayout(self.row)

        if hint:
            self.hint_widget = QLabel(hint)
            self.hint_widget.setObjectName("hintLabel")
            self.hint_widget.setWordWrap(True)
            outer.addWidget(self.hint_widget)

    def set_value(self, text: str) -> None:
        if self.value_widget is not None:
            self.value_widget.setText(text)

    def set_hint(self, text: str) -> None:
        if self.hint_widget is not None:
            self.hint_widget.setText(text)

    def add_widget(self, widget: QWidget) -> None:
        """往主行追加 widget(如多控件横排)."""
        self.row.addWidget(widget)
