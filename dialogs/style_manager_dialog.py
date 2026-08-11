"""v2.2.1: 全局风格管理对话框——重命名 / 安全删除 / 查看文件与完整性。

配合各音效页的"管理风格"入口使用。删除只移入 _trash 回收区，可手动找回；
重命名与删除都会同步更新武器映射配置。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.audio.style_creator import delete_style, list_style_files, rename_style
from core.utils.logger import get_logger
# R7/D-06 加了 style_as_danger_button(...) 调用却漏了这行 import ——
# 打开"风格管理"对话框会当场 NameError。ruff 的 F821 早就报了，
# 但 CI 的 lint 步骤本来就红着（13 处既有错误），信号被噪声淹没。
from page_theme_helper import style_as_danger_button


class StyleManagerDialog(QDialog):
    """管理某类别的全局风格。styles_changed 在任何改动后发出，供页面刷新。"""

    styles_changed = Signal()

    def __init__(self, category: str, category_label: str, styles: list[str], parent=None):
        super().__init__(parent)
        self.logger = get_logger("StyleManager")
        self.category = category
        self.category_label = category_label
        self._changed = False

        self.setWindowTitle(f"管理{category_label}风格")
        self.setMinimumSize(440, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        tip = QLabel(
            "重命名会同步更新已配置的武器映射；删除仅移入回收区（_trash 目录），"
            "对应武器映射会重置为“不启用”。"
        )
        tip.setObjectName("hintLabel")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.style_list = QListWidget()
        for style in styles:
            self.style_list.addItem(QListWidgetItem(style))
        self.style_list.currentRowChanged.connect(self._refresh_detail)
        layout.addWidget(self.style_list, 1)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("hintLabel")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        btn_row = QHBoxLayout()
        self.rename_btn = QPushButton("重命名…")
        self.rename_btn.clicked.connect(self._rename_selected)
        btn_row.addWidget(self.rename_btn)
        self.delete_btn = QPushButton("删除（移入回收区）")
        # R7/D-06: 文件虽移入 _trash 可手动找回，但**引用该风格的武器映射会被重置为
        # 「不启用」，这部分配置改动不可逆**。
        style_as_danger_button(self.delete_btn)
        self.delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._refresh_detail()

    def _selected_style(self) -> str:
        item = self.style_list.currentItem()
        return item.text() if item else ""

    def _refresh_detail(self, *_args):
        style = self._selected_style()
        has_selection = bool(style)
        self.rename_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        if not has_selection:
            self.detail_label.setText("选择一个风格查看内容")
            return
        files = list_style_files(self.category, style)
        present_levels = {f.split(".")[0] for f in files}
        missing = [str(i) for i in range(1, 6) if str(i) not in present_levels]
        detail = f"包含文件：{('、'.join(files) if files else '（空目录）')}"
        if missing:
            detail += f"\n缺少 {'、'.join(missing)} 连杀文件，触发时将回退或静音"
        self.detail_label.setText(detail)

    def _rename_selected(self):
        style = self._selected_style()
        if not style:
            return
        new_name, ok = QInputDialog.getText(self, "重命名风格", f"把“{style}”改为：", text=style)
        if not ok or not new_name.strip() or new_name.strip() == style:
            return
        result = rename_style(self.category, style, new_name.strip())
        if not result.ok:
            QMessageBox.warning(self, "重命名未完成", result.message)
            return
        self.logger.info(f"风格重命名: {style} -> {result.style_name} ({self.category})")
        item = self.style_list.currentItem()
        if item is not None:
            item.setText(result.style_name)
        self._changed = True
        self.styles_changed.emit()
        QMessageBox.information(self, "完成", result.message)
        self._refresh_detail()

    def _delete_selected(self):
        style = self._selected_style()
        if not style:
            return
        answer = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除风格“{style}”？\n文件会移入回收区（_trash 目录），可手动找回；"
            "使用该风格的武器会重置为“不启用”。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        result = delete_style(self.category, style)
        if not result.ok:
            QMessageBox.warning(self, "删除未完成", result.message)
            return
        self.logger.info(f"风格已删除(移入回收区): {style} ({self.category})")
        row = self.style_list.currentRow()
        self.style_list.takeItem(row)
        self._changed = True
        self.styles_changed.emit()
        QMessageBox.information(self, "完成", result.message)
        self._refresh_detail()
