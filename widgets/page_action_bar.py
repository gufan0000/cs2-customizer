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

    def set_message(self, text: str):
        message = str(text or "")
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
