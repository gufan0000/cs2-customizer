"""widget showcase — 一窗口展示 v5 Phase 2 抽出的 5 个核心组件.

用法:
    python scripts/widget_showcase.py

显示窗口让你目视检查 SettingsCard / PageHeader / SettingsRow /
按钮语义 / StatusChip 在当前主题下的视觉.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHBoxLayout, QMainWindow,
    QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from theme_manager import get_theme_manager
from page_theme_helper import (
    style_as_danger_button, style_as_ghost_button,
    style_as_primary_button, style_as_secondary_button,
)
from widgets import (
    PageHeader, SettingsCard, SettingsRow, StatusChip,
)


def _btn(text, helper_fn):
    """R8-W5：AppButton 已删（零引用 + 与 style_as_* 重叠），改用全站统一惯用法。"""
    from PySide6.QtWidgets import QPushButton
    b = QPushButton(text)
    helper_fn(b)
    return b


def _action_btn(text):
    from PySide6.QtWidgets import QPushButton
    b = QPushButton(text)
    b.setObjectName("actionButton")
    return b


def _icon_btn(text):
    from PySide6.QtWidgets import QPushButton
    b = QPushButton(text)
    b.setObjectName("iconButton")
    b.setFixedSize(36, 36)
    return b


def build_showcase() -> QWidget:
    root = QWidget()
    root.setObjectName("showcaseRoot")
    layout = QVBoxLayout(root)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(20)

    # ===== PageHeader =====
    layout.addWidget(PageHeader("Widget Showcase",
                                "v5 Phase 2 — 5 个核心组件目视检查"))

    # ===== StatusChip 一行 =====
    chip_row = QHBoxLayout()
    for level, text in [
        ("info", "主题・深色"),
        ("success", "配置・已保存"),
        ("positive", "运行・正常"),
        ("warning", "音频・需检查"),
        ("error", "GSI・异常"),
        ("neutral", "未配置"),
    ]:
        chip_row.addWidget(StatusChip(text, level=level))
    chip_row.addStretch()
    chip_wrapper = QWidget()
    chip_wrapper.setLayout(chip_row)
    layout.addWidget(chip_wrapper)

    # ===== SettingsCard 1:title only =====
    card1 = SettingsCard("仅有标题")
    card1.add_widget(SettingsRow("启用功能", control=QCheckBox()))
    card1.add_widget(SettingsRow("音量", control=QSlider(Qt.Horizontal), value="80%"))
    layout.addWidget(card1)

    # ===== SettingsCard 2:title + description + 多种行 =====
    card2 = SettingsCard(
        "完整卡片",
        "包含标题、描述、多种 SettingsRow,和卡内 action 按钮.",
    )
    # 加 title action
    card2.add_title_action(_btn("更多 ▾", style_as_ghost_button))

    combo = QComboBox()
    combo.addItems(["选项 A", "选项 B", "选项 C"])
    card2.add_widget(SettingsRow("下拉选择", control=combo))

    card2.add_widget(SettingsRow(
        "音量",
        control=QSlider(Qt.Horizontal),
        value="60%",
        hint="拖动调整,音量过大可能导致听力损伤.",
    ))

    card2.add_widget(SettingsRow(
        "紧凑开关",
        control=QCheckBox(),
        control_align="left",
    ))

    layout.addWidget(card2)

    # ===== SettingsCard 3:无标题,纯按钮排 =====
    card3 = SettingsCard()
    btn_row = QHBoxLayout()
    btn_row.addWidget(_btn("保存配置", style_as_primary_button))
    btn_row.addWidget(_btn("取消", style_as_secondary_button))
    btn_row.addWidget(_action_btn("测试"))
    btn_row.addWidget(_btn("删除全部", style_as_danger_button))
    btn_row.addStretch()
    btn_row.addWidget(_icon_btn("⟲"))
    btn_row.addWidget(_btn("更多", style_as_ghost_button))
    card3.add_layout(btn_row)
    layout.addWidget(card3)

    layout.addStretch()
    return root


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    # 应用主题(否则看不到 QSS 效果)
    tm = get_theme_manager()
    tm.apply_theme("dark")

    win = QMainWindow()
    win.setWindowTitle("帆派助手 - v5 Widget Showcase")
    win.resize(1100, 800)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(build_showcase())
    win.setCentralWidget(scroll)

    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
