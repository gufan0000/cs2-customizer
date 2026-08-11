# SPDX-License-Identifier: GPL-3.0-or-later
"""IconLabel — icon + 文字的紧凑组合 widget.

v5 Phase 5 起替代页面里散在的 "QLabel + 不带 icon" 标题/badge 组合.

用法:
    icon_label = IconLabel("mdi.crosshairs", "准心设置", role="primary", icon_size=18)
    layout.addWidget(icon_label)

    # 仅 icon
    icon_label = IconLabel("mdi.flash", "")
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from widgets.icon_provider import get_themed_icon


class IconLabel(QWidget):
    """icon + 文字横排."""

    def __init__(
        self,
        icon: str,
        text: str = "",
        role: str = "secondary",
        icon_size: int = 16,
        spacing: int = 6,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon
        self._role = role
        self._icon_size = icon_size

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(icon_size, icon_size)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self._apply_icon()
        layout.addWidget(self.icon_label)

        self.text_label = QLabel(text)
        if text:
            layout.addWidget(self.text_label)
        else:
            self.text_label.hide()

        layout.addStretch()

    def _apply_icon(self) -> None:
        """渲染 icon 到 QLabel.pixmap."""
        if not self._icon_name:
            return
        icon = get_themed_icon(self._icon_name, role=self._role, size=self._icon_size)
        if icon.isNull():
            return
        pixmap = icon.pixmap(QSize(self._icon_size, self._icon_size))
        self.icon_label.setPixmap(pixmap)

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)
        self.text_label.setVisible(bool(text))

    def set_icon(self, icon: str, role: str | None = None) -> None:
        self._icon_name = icon
        if role is not None:
            self._role = role
        self._apply_icon()

    def refresh_icon(self) -> None:
        """主题切换后调用,重新渲染 icon 颜色."""
        self._apply_icon()
