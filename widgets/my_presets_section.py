# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""「我的预设」UI 区块（UP-040）。

单独成文件而不是塞进 `preset_center_page.py`：那个文件已经 900 多行，
再往里堆 8 个方法只会让它更难读。这里用 mixin 的形式挂上去，
`PresetCenterPage` 只需要多继承一下、在布局里调一次 `build_my_presets_card()`。

依赖 `PresetCenterPage` 提供的三件东西（都是它已有的）：
`_selected_types()` / `_selected_type_labels()` / `_TYPE_CHECKBOX_SPEC` / `_set_compact_heights()`。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
)

# UP-100: 这一行横排时的最小宽实测 **883px**（下拉框钉了 220 下限 + 5 个按钮 + 间距），
# 加上页面留白 32px 与滚动条约 6px，需要页宽 ≥ 921px 才装得下。取 960 留 39px 余量。
#
# 紧凑模式（860×640）下页宽只有 860 —— 于是整页横向滚动，`preset_center` 在
# **8 主题 × 3 字号 24 个组合全中**，溢出 58~61px。这个模式用户点一下界面上的
# 「切换紧凑/完整模式」按钮就能进，而 R0~R10 十一轮审计跑的全是完整模式，
# 从来没量过这一档。
MY_PRESETS_ROW_MIN_WIDTH = 960


class MyPresetsMixin:
    """给预设中心页加上「我的预设」能力。"""

    def build_my_presets_card(self, parent_layout):
        """构建卡片并追加到给定布局。"""
        from widgets.settings_card import SettingsCard

        card, layout = SettingsCard.make(
            "我的预设",
            "把上面勾选的几类配置存成一套具名预设，之后一键切回来。"
            "应用前会自动建快照，可在配置快照页回滚。",
            spacing=10,
        )

        # UP-100: 原本是一个 QHBoxLayout 把下拉框和 5 个按钮平铺到底，最小宽 883px，
        # 窄窗口下顶穿。改成「下拉框」+「按钮子行」两段，外层用 QBoxLayout 以便按页宽
        # 切方向（`_update_my_presets_layout`）——横排时布局与改之前**逐像素相同**
        # （stretch 仍是 1，按钮仍按原顺序紧跟其后），只有窄到装不下时才竖过来。
        row = QBoxLayout(QBoxLayout.LeftToRight)
        row.setSpacing(8)
        self.my_preset_row = row

        self.my_preset_combo = QComboBox()
        self.my_preset_combo.setFixedHeight(34)
        self.my_preset_combo.setMinimumWidth(220)
        row.addWidget(self.my_preset_combo, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setContentsMargins(0, 0, 0, 0)

        self.my_preset_apply_btn = QPushButton("应用")
        self.my_preset_apply_btn.setObjectName("secondaryButton")
        self.my_preset_apply_btn.clicked.connect(self._apply_my_preset)
        btn_row.addWidget(self.my_preset_apply_btn)

        self.my_preset_save_btn = QPushButton("存为新预设")
        self.my_preset_save_btn.setObjectName("secondaryButton")
        self.my_preset_save_btn.clicked.connect(self._save_my_preset)
        btn_row.addWidget(self.my_preset_save_btn)

        self.my_preset_overwrite_btn = QPushButton("覆盖")
        self.my_preset_overwrite_btn.setObjectName("secondaryButton")
        self.my_preset_overwrite_btn.clicked.connect(self._overwrite_my_preset)
        btn_row.addWidget(self.my_preset_overwrite_btn)

        self.my_preset_rename_btn = QPushButton("改名")
        self.my_preset_rename_btn.setObjectName("secondaryButton")
        self.my_preset_rename_btn.clicked.connect(self._rename_my_preset)
        btn_row.addWidget(self.my_preset_rename_btn)

        # D-06: dangerButton 只给"不可逆数据丢失"用——删预设正是其中之一
        self.my_preset_delete_btn = QPushButton("删除")
        self.my_preset_delete_btn.setObjectName("dangerButton")
        self.my_preset_delete_btn.clicked.connect(self._delete_my_preset)
        btn_row.addWidget(self.my_preset_delete_btn)

        row.addLayout(btn_row, 0)

        if hasattr(self, "_set_compact_heights"):
            self._set_compact_heights(
                self.my_preset_apply_btn, self.my_preset_save_btn,
                self.my_preset_overwrite_btn, self.my_preset_rename_btn,
                self.my_preset_delete_btn,
            )
        layout.addLayout(row)

        self.my_preset_hint_label = QLabel("")
        self.my_preset_hint_label.setObjectName("hintLabel")
        self.my_preset_hint_label.setWordWrap(True)
        layout.addWidget(self.my_preset_hint_label)

        self.my_preset_combo.currentIndexChanged.connect(self._sync_my_preset_hint)
        self.refresh_my_presets()
        parent_layout.addWidget(card)
        return card

    def _update_my_presets_layout(self, width):
        """按页宽切换「我的预设」那一行的方向（UP-100）。

        宿主页面在 `resizeEvent` 里调它。放在 mixin 里而不是页面里，是因为
        这一行的最小宽是这个文件决定的——判据和阈值应该跟着决定它的代码走，
        否则改了按钮文案却忘了改另一个文件里的阈值，缺陷会静悄悄回来。

        竖排时把下拉框的 stretch 归 0：QBoxLayout 竖过来之后 stretch 管的是**高**，
        而下拉框 `setFixedHeight(34)` 长不了，留着 stretch=1 只会在它下面撑出一段空隙。
        """
        row = getattr(self, "my_preset_row", None)
        if row is None:
            return
        vertical = width < MY_PRESETS_ROW_MIN_WIDTH
        direction = QBoxLayout.TopToBottom if vertical else QBoxLayout.LeftToRight
        if row.direction() != direction:
            row.setDirection(direction)
            row.setStretch(0, 0 if vertical else 1)

    # ------------------------------------------------------------------ 数据

    def refresh_my_presets(self):
        """重建下拉列表，尽量保住当前选中项。"""
        from core.presets.my_presets import list_presets

        keep = self.my_preset_combo.currentData()
        self.my_preset_combo.blockSignals(True)
        self.my_preset_combo.clear()
        items = list_presets()
        for item in items:
            self.my_preset_combo.addItem(f"{item.name}（{len(item.types)} 类）", item.preset_id)
            self.my_preset_combo.setItemData(
                self.my_preset_combo.count() - 1,
                f"更新于 {item.updated_at}", Qt.ToolTipRole)
        if keep:
            idx = self.my_preset_combo.findData(keep)
            if idx >= 0:
                self.my_preset_combo.setCurrentIndex(idx)
        self.my_preset_combo.blockSignals(False)

        # 一条都没有时，除了"存为新预设"其余全禁用——
        # 让按钮点不动比点了弹"请先选择"友好（UP-022 已让禁用态看得出来）
        has = bool(items)
        for btn in (self.my_preset_apply_btn, self.my_preset_overwrite_btn,
                    self.my_preset_rename_btn, self.my_preset_delete_btn):
            btn.setEnabled(has)
        self._sync_my_preset_hint()

    def _sync_my_preset_hint(self, *_args):
        from core.presets.my_presets import list_presets

        pid = self.my_preset_combo.currentData()
        if not pid:
            self.my_preset_hint_label.setText(
                "还没有保存过预设。先在上面勾选要包含的类别，再点「存为新预设」。")
            return
        for item in list_presets():
            if item.preset_id == pid:
                labels = "、".join(self._my_preset_type_label(t) for t in item.types) or "（空）"
                self.my_preset_hint_label.setText(f"包含：{labels} ｜ 更新于 {item.updated_at}")
                return
        self.my_preset_hint_label.setText("")

    def _my_preset_type_label(self, type_id):
        for _attr, tid, label in getattr(self, "_TYPE_CHECKBOX_SPEC", ()):
            if tid == type_id:
                return label
        return type_id

    def _current_my_preset(self):
        """返回 (preset_id, 展示名)；没有选中返回 (None, "")。"""
        pid = self.my_preset_combo.currentData()
        if not pid:
            return None, ""
        return pid, self.my_preset_combo.currentText().split("（")[0]

    # ------------------------------------------------------------------ 动作

    def _save_my_preset(self):
        from core.presets.my_presets import MAX_NAME_LEN, save_preset

        types = self._selected_types()
        if not types:
            self._my_preset_toast("请先勾选至少一类配置", "warning")
            return
        prompt = (
            f"给这套配置起个名字（最多 {MAX_NAME_LEN} 字）：\n"
            f"将包含：{'、'.join(self._selected_type_labels())}"
        )
        name, ok = QInputDialog.getText(self, "存为新预设", prompt)
        if not ok or not str(name).strip():
            return
        try:
            item = save_preset(name, types)
        except Exception as exc:
            self.logger.exception("保存我的预设失败")
            self._my_preset_toast(f"保存失败：{exc}", "error")
            return
        self.refresh_my_presets()
        idx = self.my_preset_combo.findData(item.preset_id)
        if idx >= 0:
            self.my_preset_combo.setCurrentIndex(idx)
        self._my_preset_toast(f"已保存预设「{item.name}」", "success")

    def _overwrite_my_preset(self):
        from core.presets.my_presets import save_preset

        pid, name = self._current_my_preset()
        if not pid:
            return
        types = self._selected_types()
        if not types:
            self._my_preset_toast("请先勾选至少一类配置", "warning")
            return
        question = f"用当前配置覆盖预设「{name}」？\n\n原内容会被替换，且不可撤销。"
        if QMessageBox.question(self, "确认覆盖", question,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            save_preset(name, types, overwrite_id=pid)
        except Exception as exc:
            self.logger.exception("覆盖我的预设失败")
            self._my_preset_toast(f"覆盖失败：{exc}", "error")
            return
        self.refresh_my_presets()
        self._my_preset_toast(f"已用当前配置覆盖「{name}」", "success")

    def _apply_my_preset(self):
        from core.presets.my_presets import apply_preset

        pid, name = self._current_my_preset()
        if not pid:
            return
        try:
            result = apply_preset(pid)
        except Exception as exc:
            self.logger.exception("应用我的预设失败")
            self._my_preset_toast(f"应用失败：{exc}", "error")
            return
        if not result.ok:
            detail = "；".join(result.errors) or "预设内容不合法"
            self._my_preset_toast(f"应用失败：{detail}", "error")
            return
        # 走的是 apply_bundle：应用前已自动建快照，且已广播配置重载(UP-035)，
        # 所以此刻已打开的页面已经刷成新值，用户再动控件不会把预设写回旧值。
        # QA-013: 但"已自动建快照"不是必然成立的 —— 建失败时 apply_bundle 会往
        # warnings 里放话。这时候还说"可在配置快照页回滚"就是骗人。
        if result.warnings:
            self._my_preset_toast(
                f"已应用「{name}」，但{'；'.join(result.warnings)}", "warning")
            return
        self._my_preset_toast(f"已应用「{name}」，可在配置快照页回滚", "success")

    def _rename_my_preset(self):
        from core.presets.my_presets import rename_preset

        pid, old = self._current_my_preset()
        if not pid:
            return
        name, ok = QInputDialog.getText(self, "重命名预设", "新名字：", text=old)
        if not ok or not str(name).strip():
            return
        try:
            rename_preset(pid, name)
        except Exception as exc:
            self.logger.exception("重命名我的预设失败")
            self._my_preset_toast(f"重命名失败：{exc}", "error")
            return
        self.refresh_my_presets()
        self._my_preset_toast(f"已重命名为「{str(name).strip()}」", "success")

    def _delete_my_preset(self):
        from core.presets.my_presets import delete_preset

        pid, name = self._current_my_preset()
        if not pid:
            return
        # 说清楚它和配置快照的区别——快照能回滚，这个删了就没了
        question = f"删除预设「{name}」？\n\n这个操作不可撤销（它不是配置快照，删了就没了）。"
        if QMessageBox.question(self, "确认删除", question,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        if delete_preset(pid):
            self.refresh_my_presets()
            self._my_preset_toast(f"已删除「{name}」", "success")
        else:
            self._my_preset_toast("删除失败，文件可能已被移走", "error")

    def _my_preset_toast(self, message, level="info"):
        """统一出提示；toast 不可用就退回 action bar，不让反馈整个丢掉。"""
        try:
            from ui_toast import toast_error, toast_info, toast_success, toast_warning

            handler = {"success": toast_success, "warning": toast_warning,
                       "error": toast_error}.get(level, toast_info)
            handler(message, 3600)
        except Exception:
            bar = getattr(self, "action_bar", None)
            if bar is not None and hasattr(bar, "set_message"):
                bar.set_message(message)
