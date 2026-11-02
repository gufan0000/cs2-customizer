# SPDX-License-Identifier: GPL-3.0-or-later
"""武器格：一把枪一格，枪名 + 风格下拉 + 试听（批 146 从一整行改成一格）。

点枪名做什么由页面决定（`nameClicked`）：四个音效页是把风格库选中的风格配给这把枪，
枪声页是让微调栏换到这把枪；特殊音效页的名字不做事（`name_is_action=False`）。
下拉留着做精确选择，试听的是这把枪现在配的那个风格。
样式全在 `theme_manager`（`_weapon_board_qss`）：39 格各调一次 `setStyleSheet` 是建页最慢的那一块。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QMenu, QPushButton, QSizePolicy, QStyle,
    QStyleOptionComboBox, QStylePainter, QToolButton,
)

#: 格子状态（`fp_state`）：配了 / 配的风格已经不在了 / 没配（空串）。
STATE_CONFIGURED = "configured"
STATE_STALE = "stale"
#: 手上有刷子时这一格能不能接（`fp_brush`）。
BRUSH_CAN = "can"
BRUSH_CANNOT = "cannot"


def _repolish(widget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


class FlatStyleCombo(QComboBox):
    """格子里的下拉：风格名放不下显示省略号，弹出的列表按内容放宽。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(3)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def paintEvent(self, _event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        field = self.style().subControlRect(
            QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self)
        option.currentText = self.fontMetrics().elidedText(
            option.currentText, Qt.ElideRight, max(0, field.width() - 2))
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)

    def showPopup(self):
        # 放在这里不放构造：`view()` 第一次调才建弹窗，39 格一起建白花时间
        view = self.view()
        view.setTextElideMode(Qt.ElideNone)
        view.setMinimumWidth(max(self.width(), view.sizeHintForColumn(0) + 24))
        super().showPopup()


class WeaponRowWidget(QFrame):
    """一把枪一格（类名没改：四个音效页和判据都按它找）。"""

    styleChanged = Signal(str)      # 风格改变（发送新风格）
    testClicked = Signal()          # 试听（默认档）
    testLevelClicked = Signal(int)  # 选档位试听（1-5 连杀）
    nameClicked = Signal()          # 点了枪名

    def __init__(self, weapon_name: str, weapon_key: str,
                 style_options: list, current_style: str = "不启用", parent=None,
                 *, test_levels: list | None = None, name_is_action: bool = True):
        super().__init__(parent)
        self.setObjectName("weaponCell")
        self.setProperty("fp_setting_row", True)  # 搜到枪名时高亮整格
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.weapon_name = weapon_name
        self.weapon_key = weapon_key
        self._test_levels = list(test_levels or [])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(0)

        self.name_button = QPushButton(weapon_name, self)
        self.name_button.setObjectName("weaponCellName")
        self.name_button.setAccessibleName(weapon_name)
        self.name_button.clicked.connect(self.nameClicked.emit)
        if not name_is_action:
            # 这一页点名字不做事：不占 Tab，也不假装能点
            self.name_button.setFocusPolicy(Qt.NoFocus)
            self.name_button.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.name_button)

        self.style_combo = FlatStyleCombo(self)
        self.style_combo.setObjectName("weaponCellCombo")
        self.style_combo.setAccessibleName(f"{weapon_name} 的风格")
        self.style_combo.addItems(style_options)
        self.style_combo.setCurrentText(current_style)
        self.style_combo.currentTextChanged.connect(self._on_style_changed)
        layout.addWidget(self.style_combo, 1)

        # 提供档位时用带下拉的分裂按钮（默认播 1 连杀，下拉选 2-5 连杀）
        if self._test_levels:
            self.test_button = QToolButton(self)
            self.test_button.setPopupMode(QToolButton.MenuButtonPopup)
            self.test_button.clicked.connect(self.testClicked.emit)
            menu = QMenu(self.test_button)
            for level in self._test_levels:
                action = menu.addAction(f"试听 {level} 连杀")
                action.triggered.connect(
                    lambda _checked=False, lv=int(level): self.testLevelClicked.emit(lv))
            self.test_button.setMenu(menu)
        else:
            self.test_button = QPushButton(self)
            self.test_button.clicked.connect(self.testClicked.emit)
        self.test_button.setObjectName("weaponCellTest")
        self.test_button.setText("试听")
        self.test_button.setAccessibleName(f"试听 {weapon_name}")
        # 没配风格时没东西可听：字退后一档，配上了再亮。⚠ 不禁用，点了照样有回应
        self.test_button.setProperty("fp_idle", "true")
        layout.addWidget(self.test_button)

        self._sync_combo_tooltip()

    def _on_style_changed(self, new_style: str):
        self._sync_combo_tooltip()
        self.styleChanged.emit(new_style)

    def _sync_combo_tooltip(self) -> None:
        # 窄格子里风格名可能只露一半。⚠ 置灰时 tooltip 归「为什么灰」（`community_library._set_dim`）
        if self.style_combo.isEnabled():
            self.style_combo.setToolTip(self.style_combo.currentText())

    def get_current_style(self) -> str:
        """获取当前选中的风格"""
        return self.style_combo.currentText()

    def set_current_style(self, style: str):
        """设置当前风格"""
        self.style_combo.setCurrentText(style)

    def update_style_options(self, options: list):
        """更新风格选项列表"""
        current = self.style_combo.currentText()
        self.style_combo.clear()
        self.style_combo.addItems(options)

        # 尝试恢复之前的选择
        if current in options:
            self.style_combo.setCurrentText(current)
        else:
            self.style_combo.setCurrentIndex(0)

    def set_cell_state(self, state: str) -> None:
        """配没配、配的还在不在。页面算好传进来，这里只管样子。"""
        if (self.property("fp_state") or "") == state:
            return
        self.setProperty("fp_state", state)
        self.test_button.setProperty("fp_idle", "" if state else "true")
        _repolish(self)
        _repolish(self.style_combo)
        _repolish(self.test_button)

    def cell_state(self) -> str:
        return self.property("fp_state") or ""

    def set_brush_state(self, value: str) -> None:
        """手上有刷子时这一格能不能接。空串 = 手上没有刷子。"""
        if (self.property("fp_brush") or "") == value:
            return
        self.setProperty("fp_brush", value)
        _repolish(self)
        _repolish(self.name_button)
        self.name_button.setCursor(
            Qt.PointingHandCursor if value == BRUSH_CAN else Qt.ArrowCursor)

    def set_selected(self, selected: bool) -> None:
        """枪声页：下面那条微调栏现在调的是这一把。"""
        value = "true" if selected else ""
        if (self.property("fp_selected") or "") == value:
            return
        self.setProperty("fp_selected", value)
        _repolish(self)

    def set_name_width(self, width: int) -> None:
        """枪名列宽由武器板统一给，这样上下左右的下拉都对得齐。"""
        self.name_button.setFixedWidth(width)

    def name_text_width(self) -> int:
        self.name_button.ensurePolished()
        return self.name_button.fontMetrics().horizontalAdvance(self.weapon_name)
