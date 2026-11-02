# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""总览页的零件：就绪状态条、功能卡和它们的网格（批 148）。

开关还是 `MainWindow` 那 17 颗 ToggleSwitch，拨它走的还是 `_on_switch_changed`：这里只管长相。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui_style_applier import keep_single_line
from widgets.icon_provider import get_themed_icon
from widgets.style_library import ElidedLabel

FEATURE_CARD_MIN_WIDTH = 230
FEATURE_CARD_GAP = 8
FEATURE_ICON_SIZE = 20
READINESS_BADGE_ICON_SIZE = 20
READINESS_CHECK_ICON_SIZE = 14
#: 放得下「三项检查 + 按钮」的宽度，再窄检查项就换到第二行。
READINESS_WIDE_WIDTH = 900

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"

_BADGE_ICON = {
    LEVEL_OK: ("mdi.check", "success"),
    LEVEL_WARN: ("mdi.alert-outline", "warning"),
    LEVEL_ERROR: ("mdi.close", "error"),
}
_CHECK_ICON = {
    "ok": ("mdi.check", "success"),
    "warn": ("mdi.alert-outline", "warning"),
    "": ("mdi.minus", "muted"),
}


def _repolish(widget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class FeatureCard(QPushButton):
    """一张功能卡。整张点进那一页（没有对应页面的只留开关），右边那颗就是总开关。"""

    def __init__(self, name: str, toggle, *, icon_name: str, has_page: bool, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._on = False
        self.setObjectName("featureCard")
        self.setAccessibleName(name)
        self.setMinimumWidth(FEATURE_CARD_MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 搜索落到这一张卡，不是落到整页（`_find_setting_row`）。
        self.setProperty("fp_setting_row", True)
        self.setProperty("fp_link", "true" if has_page else "")
        if has_page:
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.TabFocus)
        else:
            self.setFocusPolicy(Qt.NoFocus)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)

        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("featureCardIcon")
        self.icon_label.setFixedSize(FEATURE_ICON_SIZE, FEATURE_ICON_SIZE)
        self.icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.icon_label, 0, Qt.AlignVCenter)

        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(0)
        words.addStretch(1)
        # ⚠ 两行字都要 keep_single_line，理由同 StyleCard：折行的标签会绕过下面的 sizeHint。
        # › 是静态看得见的「能点进去」（RN-235：只靠悬停才说话的能力，在屏幕上等于不存在）。
        self.name_label = keep_single_line(QLabel(f"{name} ›" if has_page else name, self))
        self.name_label.setProperty("fp_search_text", name)
        self.name_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        words.addWidget(self.name_label)
        self.meta_label = keep_single_line(ElidedLabel("", self))
        self.meta_label.setObjectName("featureCardMeta")
        self.meta_label.setProperty("fp_index_skip", True)  # 当前值：索引随包发布（RN-568）
        self.meta_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        words.addWidget(self.meta_label)
        words.addStretch(1)
        layout.addLayout(words, 1)

        self.toggle = toggle
        toggle.setParent(self)
        layout.addWidget(toggle, 0, Qt.AlignVCenter)

    def sizeHint(self):
        # 按钮的 sizeHint 不看里面的布局。平时高度由样式表给，极简主题没有样式表。
        hint = super().sizeHint()
        hint.setHeight(max(hint.height(), self.fontMetrics().height() * 2 + 12))
        return hint

    def set_state(self, on: bool, summary: str, tone: str = "") -> None:
        self.meta_label.set_full_text(summary)
        self.setAccessibleDescription(summary)
        if self.meta_label.property("tone") != tone:
            self.meta_label.setProperty("tone", tone)
            _repolish(self.meta_label)
        if on != self._on or self.icon_label.pixmap().isNull():
            self._on = on
            self.refresh_icon()

    def refresh_icon(self) -> None:
        """图标是位图，开关一变、主题一换都要重画。"""
        icon = get_themed_icon(self._icon_name, role="accent" if self._on else "muted",
                               size=FEATURE_ICON_SIZE)
        self.icon_label.setPixmap(icon.pixmap(QSize(FEATURE_ICON_SIZE, FEATURE_ICON_SIZE)))


class FeatureGrid(QWidget):
    """功能卡的网格，列数跟宽度走。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: list[FeatureCard] = []
        self._cols = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(FEATURE_CARD_GAP)

    def add_card(self, card: FeatureCard) -> None:
        card.setParent(self)
        self._cards.append(card)
        self._cols = 0
        self._reflow()

    def columns(self) -> int:
        return self._cols

    def minimumSizeHint(self):
        # 只算一张卡：按当前列数算的话，列数一多就把自己撑住，窗口变窄也退不回来
        hint = super().minimumSizeHint()
        hint.setWidth(FEATURE_CARD_MIN_WIDTH)
        return hint

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        cols = max(1, (self.width() + FEATURE_CARD_GAP) // (FEATURE_CARD_MIN_WIDTH + FEATURE_CARD_GAP))
        if cols == self._cols:
            return
        for col in range(self._grid.columnCount()):
            self._grid.setColumnStretch(col, 0)
        for card in self._cards:
            self._grid.removeWidget(card)
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // cols, index % cols)
        for col in range(cols):
            self._grid.setColumnStretch(col, 1)
        self._cols = cols


class ReadinessCheck(QWidget):
    """状态条右边一项：图标 + 名称 + 值。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tone = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(READINESS_CHECK_ICON_SIZE, READINESS_CHECK_ICON_SIZE)
        layout.addWidget(self.icon_label, 0, Qt.AlignVCenter)
        self.name_label = keep_single_line(QLabel(self))
        self.name_label.setObjectName("readinessCheckName")
        layout.addWidget(self.name_label)
        self.value_label = keep_single_line(QLabel(self))
        self.value_label.setObjectName("readinessCheckValue")
        self.value_label.setProperty("fp_index_skip", True)
        layout.addWidget(self.value_label)

    def set_check(self, name: str, value: str, tone: str, tooltip: str = "") -> None:
        self.name_label.setText(name)
        self.value_label.setText(value)
        self.setToolTip(tooltip)
        if tone != self._tone:
            self._tone = tone
            self.refresh_icon()

    def refresh_icon(self) -> None:
        icon_name, role = _CHECK_ICON.get(self._tone or "", _CHECK_ICON[""])
        icon = get_themed_icon(icon_name, role=role, size=READINESS_CHECK_ICON_SIZE)
        self.icon_label.setPixmap(icon.pixmap(QSize(READINESS_CHECK_ICON_SIZE, READINESS_CHECK_ICON_SIZE)))


class ReadinessStrip(QFrame):
    """总览第一行：现在能不能进游戏。大字说结论，下面一句说还差什么，右边三项是依据。"""

    def __init__(self, action_button, parent=None):
        super().__init__(parent)
        self.setObjectName("readinessStrip")
        self._level = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        self._top = QHBoxLayout()
        self._top.setSpacing(12)
        outer.addLayout(self._top)

        self.badge = QLabel(self)
        self.badge.setObjectName("readinessBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedSize(36, 36)
        self._top.addWidget(self.badge, 0, Qt.AlignVCenter)

        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(0)
        self.headline = keep_single_line(QLabel(self))
        self.headline.setObjectName("readinessTitle")
        self.headline.setProperty("fp_index_skip", True)
        words.addWidget(self.headline)
        self.detail_label = QLabel(self)
        self.detail_label.setObjectName("hintLabel")
        self.detail_label.setProperty("fp_index_skip", True)
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextFormat(Qt.RichText)
        self.detail_label.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
        words.addWidget(self.detail_label)
        self._top.addLayout(words, 1)

        self.checks_row = QWidget(self)
        checks_layout = QHBoxLayout(self.checks_row)
        checks_layout.setContentsMargins(0, 0, 0, 0)
        checks_layout.setSpacing(16)
        self.checks = [ReadinessCheck(self.checks_row) for _ in range(3)]
        for check in self.checks:
            checks_layout.addWidget(check)
        checks_layout.addStretch(1)
        self._outer = outer
        self._wide = True
        self._top.addWidget(self.checks_row, 0, Qt.AlignVCenter)

        self.action_button = action_button
        action_button.setParent(self)
        self._top.addWidget(action_button, 0, Qt.AlignVCenter)

    def set_state(self, level: str, headline: str) -> None:
        self.headline.setText(headline)
        if level != self._level:
            self._level = level
            self.badge.setProperty("tone", level)
            _repolish(self.badge)
            self.refresh_icons()

    def set_checks(self, checks) -> None:
        """`[(名称, 值, 语气, tooltip), ...]`。读不到的项不摆。"""
        for index, check in enumerate(self.checks):
            if index < len(checks):
                check.set_check(*checks[index])
                check.show()
            else:
                check.hide()

    def refresh_icons(self) -> None:
        icon_name, role = _BADGE_ICON.get(self._level or LEVEL_OK, _BADGE_ICON[LEVEL_OK])
        icon = get_themed_icon(icon_name, role=role, size=READINESS_BADGE_ICON_SIZE)
        self.badge.setPixmap(icon.pixmap(QSize(READINESS_BADGE_ICON_SIZE, READINESS_BADGE_ICON_SIZE)))
        for check in self.checks:
            check.refresh_icon()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wide = self.width() >= READINESS_WIDE_WIDTH
        if wide == self._wide:
            return
        self._wide = wide
        if wide:
            self._outer.removeWidget(self.checks_row)
            self._top.insertWidget(self._top.count() - 1, self.checks_row, 0, Qt.AlignVCenter)
        else:
            self._top.removeWidget(self.checks_row)
            self._outer.addWidget(self.checks_row)
