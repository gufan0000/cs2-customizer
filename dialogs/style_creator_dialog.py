# SPDX-License-Identifier: GPL-3.0-or-later
"""v2.2.1: 一步式"新建音效风格"对话框。

输入风格名 → 拖入/选择任意命名的音频文件 → 自动改名落盘 → 触发重扫。
彻底消灭"手动开目录、建文件夹、逐个改名成 1.mp3~5.mp3、手动刷新"的旧流程。
核心落盘逻辑在 core/audio/style_creator.py（可单测）。
"""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.audio.audio_file_utils import DEFAULT_AUDIO_EXTENSIONS
from core.audio.style_creator import (
    CATEGORY_TEMPLATES,
    MAX_NUMBERED_SLOTS,
    create_style,
    style_exists,
    validate_style_name,
)
from core.utils.logger import get_logger


class StyleCreatorDialog(QDialog):
    """新建音效风格向导。

    style_created(style_name, weapon) —— 创建成功后发出，供页面刷新并自动选中。
    """

    style_created = Signal(str, str)

    def __init__(
        self,
        category: str,
        parent=None,
        *,
        weapons: dict[str, str] | None = None,
        preselect_weapon: str = "",
        audio_manager=None,
        initial_files: list[str] | None = None,
    ):
        super().__init__(parent)
        self.logger = get_logger("StyleCreator")
        self.category = category
        self.template = CATEGORY_TEMPLATES[category]
        self.weapons = weapons or {}
        self.audio_manager = audio_manager
        self._files: list[str] = []

        self.setWindowTitle(f"新建{self.template.label}风格")
        self.setAcceptDrops(True)
        self.setMinimumWidth(460)
        self._init_ui(preselect_weapon)
        if initial_files:
            self._add_files(list(initial_files))

    # ---------- UI ----------

    def _init_ui(self, preselect_weapon: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 风格名
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("风格名称"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：我的音效包")
        self.name_edit.textChanged.connect(self._refresh_state)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        # 作用域（仅击杀音效/语音支持 全局/武器专属）
        self.scope_combo = None
        self.weapon_combo = None
        if self.category in ("kill_sound", "kill_voice"):
            scope_row = QHBoxLayout()
            scope_row.addWidget(QLabel("作用范围"))
            self.scope_combo = QComboBox()
            self.scope_combo.addItems(["全局（所有武器可选）", "指定武器专属"])
            self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
            scope_row.addWidget(self.scope_combo, 1)
            self.weapon_combo = QComboBox()
            for weapon_id, display in self.weapons.items():
                self.weapon_combo.addItem(display, weapon_id)
            self.weapon_combo.setVisible(False)
            scope_row.addWidget(self.weapon_combo, 1)
            layout.addLayout(scope_row)
            if preselect_weapon and preselect_weapon in self.weapons:
                index = list(self.weapons.keys()).index(preselect_weapon)
                self.weapon_combo.setCurrentIndex(index)
        elif self.category in ("switch_weapon", "reload_sound"):
            weapon_row = QHBoxLayout()
            weapon_row.addWidget(QLabel("适用武器"))
            self.weapon_combo = QComboBox()
            for weapon_id, display in self.weapons.items():
                self.weapon_combo.addItem(display, weapon_id)
            weapon_row.addWidget(self.weapon_combo, 1)
            layout.addLayout(weapon_row)
            if preselect_weapon and preselect_weapon in self.weapons:
                index = list(self.weapons.keys()).index(preselect_weapon)
                self.weapon_combo.setCurrentIndex(index)

        # 文件列表
        if self.template.layout == "numbered":
            tip = (
                f"拖入或添加音频文件（最多 {MAX_NUMBERED_SLOTS} 个），"
                "按顺序对应 1~5 连杀，程序会自动改名，无需手动命名。"
            )
        else:
            tip = "拖入或添加 1 个音频文件，程序会自动放到正确位置。"
        tip_label = QLabel(tip)
        tip_label.setObjectName("hintLabel")
        tip_label.setWordWrap(True)
        layout.addWidget(tip_label)

        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(140)
        self.file_list.currentRowChanged.connect(self._refresh_state)
        layout.addWidget(self.file_list, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加文件…")
        add_btn.clicked.connect(self._choose_files)
        btn_row.addWidget(add_btn)
        self.up_btn = QPushButton("上移")
        self.up_btn.clicked.connect(lambda: self._move_selected(-1))
        btn_row.addWidget(self.up_btn)
        self.down_btn = QPushButton("下移")
        self.down_btn.clicked.connect(lambda: self._move_selected(1))
        btn_row.addWidget(self.down_btn)
        self.remove_btn = QPushButton("移除")
        self.remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(self.remove_btn)
        self.preview_btn = QPushButton("试听")
        self.preview_btn.clicked.connect(self._preview_selected)
        btn_row.addWidget(self.preview_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("hintLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("创建")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._do_create)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        layout.addWidget(buttons)

        self._refresh_state()

    # ---------- 拖拽 ----------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self._add_files(paths)
        event.acceptProposedAction()

    # ---------- 文件操作 ----------

    def _choose_files(self):
        patterns = " ".join(f"*{ext}" for ext in DEFAULT_AUDIO_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(self, "选择音频文件", "", f"音频文件 ({patterns})")
        self._add_files(paths)

    def _add_files(self, paths: list[str]):
        rejected: list[str] = []
        for path in paths or []:
            if not path:
                continue
            if not str(path).lower().endswith(tuple(DEFAULT_AUDIO_EXTENSIONS)):
                rejected.append(os.path.basename(path))
                continue
            if path in self._files:
                continue
            if len(self._files) >= self.template.max_files:
                rejected.append(os.path.basename(path) + "（超出数量上限）")
                continue
            self._files.append(path)
        self._rebuild_list()
        if rejected:
            self.status_label.setText("未添加：" + "、".join(rejected[:5]))

    def _rebuild_list(self):
        self.file_list.clear()
        for index, path in enumerate(self._files, start=1):
            if self.template.layout == "numbered":
                label = f"{index} 连杀  ←  {os.path.basename(path)}"
            else:
                label = os.path.basename(path)
            item = QListWidgetItem(label)
            item.setToolTip(path)
            self.file_list.addItem(item)
        self._refresh_state()

    def _move_selected(self, delta: int):
        row = self.file_list.currentRow()
        new_row = row + delta
        if row < 0 or not (0 <= new_row < len(self._files)):
            return
        self._files[row], self._files[new_row] = self._files[new_row], self._files[row]
        self._rebuild_list()
        self.file_list.setCurrentRow(new_row)

    def _remove_selected(self):
        row = self.file_list.currentRow()
        if 0 <= row < len(self._files):
            self._files.pop(row)
            self._rebuild_list()

    def _preview_selected(self):
        row = self.file_list.currentRow()
        if not (0 <= row < len(self._files)):
            return
        path = self._files[row]
        played = False
        try:
            if self.audio_manager is not None and hasattr(self.audio_manager, "preview_file"):
                played = bool(self.audio_manager.preview_file(path))
        except Exception:
            played = False
        if not played:
            try:
                import pygame

                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                pygame.mixer.Sound(path).play()
            except Exception as exc:
                self.logger.warning(f"试听失败: {exc}")
                self.status_label.setText("试听失败：文件可能损坏或格式不支持")

    # ---------- 状态与创建 ----------

    def _selected_weapon(self) -> str:
        if self.category in ("kill_sound", "kill_voice"):
            if self.scope_combo is None or self.scope_combo.currentIndex() == 0:
                return ""
        if self.weapon_combo is not None and self.weapon_combo.count() > 0:
            return str(self.weapon_combo.currentData() or "")
        return ""

    def _on_scope_changed(self, index: int):
        if self.weapon_combo is not None:
            self.weapon_combo.setVisible(index == 1)
        self._refresh_state()

    def _refresh_state(self, *_args):
        name = self.name_edit.text().strip()
        problems: list[str] = []
        name_error = validate_style_name(name) if name else "请输入风格名称"
        if name_error:
            problems.append(name_error)
        elif style_exists(self.category, name, self._selected_weapon()):
            problems.append(f"风格“{name}”已存在，创建时将询问是否覆盖")
        if not self._files:
            problems.append("请添加音频文件")
        if problems:
            self.status_label.setText("；".join(problems))
        else:
            self.status_label.setText("就绪：点击“创建”完成落盘并自动刷新风格列表")
        self.ok_button.setEnabled(not name_error and bool(self._files))
        has_row = self.file_list.currentRow() >= 0
        multi = self.template.layout == "numbered"
        self.up_btn.setVisible(multi)
        self.down_btn.setVisible(multi)
        self.up_btn.setEnabled(has_row)
        self.down_btn.setEnabled(has_row)
        self.remove_btn.setEnabled(has_row)
        self.preview_btn.setEnabled(has_row)

    def _do_create(self):
        name = self.name_edit.text().strip()
        weapon = self._selected_weapon()
        overwrite = False
        if style_exists(self.category, name, weapon):
            answer = QMessageBox.question(
                self,
                "风格已存在",
                f"风格“{name}”已存在，是否覆盖其中的同名文件？\n（覆盖不会删除原有的其它文件）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            overwrite = True

        result = create_style(self.category, name, list(self._files), weapon=weapon, overwrite=overwrite)
        if not result.ok:
            QMessageBox.warning(self, "创建未完成", result.message)
            return

        self.logger.info(
            f"新建{self.template.label}风格: {result.style_name} "
            f"(weapon={weapon or '全局'}, files={len(result.created_files)})"
        )
        QMessageBox.information(self, "创建成功", result.message)
        self.style_created.emit(result.style_name, weapon)
        self.accept()
