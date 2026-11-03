# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""总览页的零件：就绪状态卡、功能面板和面板里的功能行（批 148；批 153 改成三块面板）。

开关还是 `MainWindow` 那 17 颗 ToggleSwitch，拨它走的还是 `_on_switch_changed`：这里只管长相。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QBoxLayout,
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

#: 一块面板最窄多宽：再窄，「死亡刷短视频 ›」和开关就挤在一起了。
FEATURE_PANEL_MIN_WIDTH = 240
FEATURE_PANEL_GAP = 16
FEATURE_ROW_HEIGHT = 52
FEATURE_ICON_SIZE = 18
FEATURE_CHIP_SIZE = 32
READINESS_BADGE_SIZE = 44
READINESS_BADGE_ICON_SIZE = 22
READINESS_CHECK_ICON_SIZE = 14

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
    """面板里的一行。整行点进那一页（没有对应页面的只留开关），右边那颗就是总开关。"""

    def __init__(self, name: str, toggle, *, icon_name: str, has_page: bool, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._on = False
        self.setObjectName("featureCard")
        self.setAccessibleName(name)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 搜索落到这一行，不是落到整页（`_find_setting_row`）。
        self.setProperty("fp_setting_row", True)
        self.setProperty("fp_link", "true" if has_page else "")
        if has_page:
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.TabFocus)
        else:
            self.setFocusPolicy(Qt.NoFocus)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 12, 0)
        layout.setSpacing(12)

        # 图标放在一块小方底上：开着是淡紫底紫图标，关着是灰底灰图标，扫一眼就分得出哪几项开着
        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("featureIconChip")
        self.icon_label.setProperty("on", "false")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedSize(FEATURE_CHIP_SIZE, FEATURE_CHIP_SIZE)
        self.icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.icon_label, 0, Qt.AlignVCenter)

        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(1)
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
        hint.setHeight(max(hint.height(), self.fontMetrics().height() * 2 + 12, FEATURE_ROW_HEIGHT))
        return hint

    def set_state(self, on: bool, summary: str, tone: str = "") -> None:
        self.meta_label.set_full_text(summary)
        self.setAccessibleDescription(summary)
        if self.meta_label.property("tone") != tone:
            self.meta_label.setProperty("tone", tone)
            _repolish(self.meta_label)
        if on != self._on or self.icon_label.pixmap().isNull():
            self._on = on
            self.icon_label.setProperty("on", "true" if on else "false")
            _repolish(self.icon_label)
            self.refresh_icon()

    def refresh_icon(self) -> None:
        """图标是位图，开关一变、主题一换都要重画。"""
        icon = get_themed_icon(self._icon_name, role="accent" if self._on else "muted",
                               size=FEATURE_ICON_SIZE)
        self.icon_label.setPixmap(icon.pixmap(QSize(FEATURE_ICON_SIZE, FEATURE_ICON_SIZE)))


class FeaturePanel(QFrame):
    """一组功能：抬头写组名和开了几项，下面一行一个功能。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("featurePanel")
        self.cards: list[FeatureCard] = []
        # 竖向能长：并排时三块一样高，短的那块底下留白，不在格子里上下居中
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 14, 6, 8)
        layout.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(12, 0, 12, 8)
        head.setSpacing(8)
        self.title_label = keep_single_line(QLabel(title, self))
        self.title_label.setObjectName("featurePanelTitle")
        head.addWidget(self.title_label)
        head.addStretch(1)
        self.count_label = keep_single_line(QLabel("", self))
        self.count_label.setObjectName("featurePanelCount")
        self.count_label.setProperty("fp_index_skip", True)  # 当前值：索引随包发布（RN-568）
        head.addWidget(self.count_label)
        layout.addLayout(head)
        layout.addStretch(1)
        self._rows = layout

    def add_card(self, card: FeatureCard) -> None:
        card.setParent(self)
        self.cards.append(card)
        self._rows.insertWidget(self._rows.count() - 1, card)


class FeatureGrid(QWidget):
    """几块功能面板并排；宽度不够三块并排就上下摞起来，不排成二加一。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels: list[FeaturePanel] = []
        self._cols = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(FEATURE_PANEL_GAP)
        self._grid.setVerticalSpacing(FEATURE_PANEL_GAP)

    def add_panel(self, panel: FeaturePanel) -> None:
        panel.setParent(self)
        self._panels.append(panel)
        self._cols = 0
        self._reflow()

    def panels(self) -> list[FeaturePanel]:
        return list(self._panels)

    def columns(self) -> int:
        return self._cols

    def columns_for(self, width: int) -> int:
        count = max(1, len(self._panels))
        side_by_side = count * FEATURE_PANEL_MIN_WIDTH + (count - 1) * FEATURE_PANEL_GAP
        return count if width >= side_by_side else 1

    def minimumSizeHint(self):
        # 只算一块：按当前列数算的话，列数一多就把自己撑住，窗口变窄也退不回来
        hint = super().minimumSizeHint()
        hint.setWidth(FEATURE_PANEL_MIN_WIDTH)
        return hint

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        cols = self.columns_for(self.width())
        if cols == self._cols:
            return
        for col in range(self._grid.columnCount()):
            self._grid.setColumnStretch(col, 0)
        for panel in self._panels:
            self._grid.removeWidget(panel)
        for index, panel in enumerate(self._panels):
            # 并排时三块一样高：短的那块底下留白，不让三块的下沿参差
            self._grid.addWidget(panel, index // cols, index % cols)
        for col in range(cols):
            self._grid.setColumnStretch(col, 1)
        self._cols = cols


class SplitRow(QWidget):
    """两块并排，宽度不够就上下摞。并排时按 `stretch` 分宽、两块一样高。"""

    #: 两块都放得下表单和两列滑条的宽度；再窄就摞起来，不把滑条挤成一截
    SIDE_BY_SIDE_WIDTH = 860

    def __init__(self, first: QWidget, second: QWidget, *, stretch=(1, 1), spacing=FEATURE_PANEL_GAP, parent=None):
        super().__init__(parent)
        self._first, self._second = first, second
        self._stretch = stretch
        self._box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(spacing)
        self._box.addWidget(first, stretch[0])
        self._box.addWidget(second, stretch[1])
        self._side_by_side = True

    def is_side_by_side(self) -> bool:
        return self._side_by_side

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(max(self._first.minimumSizeHint().width(), self._second.minimumSizeHint().width()))
        return hint

    def resizeEvent(self, event):
        super().resizeEvent(event)
        side_by_side = self.width() >= self.SIDE_BY_SIDE_WIDTH
        if side_by_side == self._side_by_side:
            return
        self._side_by_side = side_by_side
        self._box.setDirection(QBoxLayout.LeftToRight if side_by_side else QBoxLayout.TopToBottom)
        for widget, stretch in ((self._first, self._stretch[0]), (self._second, self._stretch[1])):
            self._box.setStretchFactor(widget, stretch if side_by_side else 0)


class ReadinessCheck(QFrame):
    """状态卡下面一枚小签：图标 + 名称 + 值。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("readinessCheck")
        self._tone = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 12, 4)
        layout.setSpacing(6)
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
    """总览第一块：现在能不能进游戏。大字说结论，下面一句说还差什么，再下面几枚小签是依据。"""

    def __init__(self, action_button, parent=None):
        super().__init__(parent)
        self.setObjectName("readinessStrip")
        self._level = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        self._top = QHBoxLayout()
        self._top.setSpacing(16)
        outer.addLayout(self._top)

        self.badge = QLabel(self)
        self.badge.setObjectName("readinessBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedSize(READINESS_BADGE_SIZE, READINESS_BADGE_SIZE)
        self._top.addWidget(self.badge, 0, Qt.AlignVCenter)

        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(2)
        self.headline = keep_single_line(QLabel(self))
        self.headline.setObjectName("readinessTitle")
        self.headline.setProperty("fp_index_skip", True)
        words.addWidget(self.headline)
        self.detail_label = QLabel(self)
        self.detail_label.setObjectName("readinessDetail")
        self.detail_label.setProperty("fp_index_skip", True)
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextFormat(Qt.RichText)
        self.detail_label.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
        words.addWidget(self.detail_label)
        self._top.addLayout(words, 1)

        self.action_button = action_button
        action_button.setParent(self)
        self._top.addWidget(action_button, 0, Qt.AlignVCenter)

        # 依据排在结论下面、和大字左对齐：一行看完结论，再往下才是细节
        self.checks_row = QWidget(self)
        checks_layout = QHBoxLayout(self.checks_row)
        checks_layout.setContentsMargins(READINESS_BADGE_SIZE + 16, 0, 0, 0)
        checks_layout.setSpacing(8)
        self.checks = [ReadinessCheck(self.checks_row) for _ in range(3)]
        for check in self.checks:
            checks_layout.addWidget(check)
        checks_layout.addStretch(1)
        outer.addWidget(self.checks_row)
        self._outer = outer

    def set_state(self, level: str, headline: str) -> None:
        self.headline.setText(headline)
        if level != self._level:
            self._level = level
            for widget in (self, self.badge):
                widget.setProperty("tone", level)
                _repolish(widget)
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
