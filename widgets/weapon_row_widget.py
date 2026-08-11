# SPDX-License-Identifier: GPL-3.0-or-later
"""
武器行组件 - 用于击杀音效和切枪音效页面
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox, QMenu, QPushButton, QSizePolicy, QToolButton
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont


class WeaponRowWidget(QWidget):
    """武器行组件：武器名 + 风格选择 + 测试按钮"""

    # 信号
    styleChanged = Signal(str)   # 风格改变信号（发送新风格）
    testClicked = Signal()       # 测试按钮点击信号（默认试听）
    testLevelClicked = Signal(int)  # v2.2.1: 选档位试听（1-5连杀）

    def __init__(self, weapon_name: str, weapon_key: str,
                 style_options: list, current_style: str = "不启用", parent=None,
                 *, test_levels: list | None = None):
        super().__init__(parent)

        self.weapon_name = weapon_name
        self.weapon_key = weapon_key
        self._test_levels = list(test_levels or [])

        self._init_ui(style_options, current_style)
    
    def _init_ui(self, style_options, current_style):
        """初始化UI"""
        from theme_manager import get_theme_manager

        self._apply_theme_styles()
        get_theme_manager().register_theme_changed_callback(self._apply_theme_styles)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        
        # 武器名称
        name_label = QLabel(self.weapon_name)
        name_label.setFont(QFont("Microsoft YaHei", 14))
        name_label.setMinimumWidth(124)
        name_label.setMaximumWidth(140)
        name_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        layout.addWidget(name_label)
        
        # 风格下拉框
        self.style_combo = QComboBox()
        self.style_combo.addItems(style_options)
        self.style_combo.setCurrentText(current_style)
        self.style_combo.setMinimumWidth(220)
        self.style_combo.setMinimumHeight(34)
        self.style_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.style_combo.currentTextChanged.connect(self._on_style_changed)
        layout.addWidget(self.style_combo, 1)
        
        # 测试按钮。v2.2.1: 提供档位时用带下拉的分裂按钮（默认播1连杀，
        # 下拉可选 2-5 连杀试听——旧版永远只能试听第 1 连杀）
        if self._test_levels:
            test_btn = QToolButton()
            test_btn.setObjectName("secondaryButton")
            test_btn.setText("测试")
            test_btn.setFixedWidth(84)
            test_btn.setMinimumHeight(34)
            test_btn.setPopupMode(QToolButton.MenuButtonPopup)
            test_btn.clicked.connect(self.testClicked.emit)
            menu = QMenu(test_btn)
            for level in self._test_levels:
                action = menu.addAction(f"试听 {level} 连杀")
                action.triggered.connect(lambda _checked=False, lv=int(level): self.testLevelClicked.emit(lv))
            test_btn.setMenu(menu)
            layout.addWidget(test_btn)
        else:
            test_btn = QPushButton("测试")
            test_btn.setObjectName("secondaryButton")
            test_btn.setFixedWidth(72)
            test_btn.setMinimumHeight(34)
            test_btn.clicked.connect(self.testClicked.emit)
            layout.addWidget(test_btn)
        
    
    def _on_style_changed(self, new_style: str):
        """风格改变处理"""
        self.styleChanged.emit(new_style)
    
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

    def _apply_theme_styles(self):
        """重新应用主题相关的内联样式"""
        # 父页面经 Qt 父子链析构（不走 deleteLater 覆盖）时回调不会被注销，
        # 此处检测到 C++ 对象已销毁就自行注销，否则回调表随页面重建无界增长
        import shiboken6
        if not shiboken6.isValid(self):
            from theme_manager import get_theme_manager
            get_theme_manager().unregister_theme_changed_callback(self._apply_theme_styles)
            return
        from theme_manager import get_color
        from ui_style_applier import keep_inline_style

        # UP-019: 这份样式是从 theme token 现算的,不是硬编码——
        # 打标豁免 apply_complete_system 的内联样式清理,否则首次进页
        # 分隔线和 hover 态会被抹掉,得切一次主题才回来。
        keep_inline_style(self)
        self.setStyleSheet(f"""
            WeaponRowWidget {{
                background-color: transparent;
                border-radius: 6px;
                border-bottom: 1px solid {get_color('border_secondary')};
                padding-bottom: 2px;
            }}
            WeaponRowWidget:hover {{
                background-color: {get_color('bg_tertiary')};
                border-bottom-color: {get_color('border_primary')};
            }}
        """)

    def deleteLater(self):
        """清理：注销主题回调"""
        from theme_manager import get_theme_manager
        get_theme_manager().unregister_theme_changed_callback(self._apply_theme_styles)
        super().deleteLater()
