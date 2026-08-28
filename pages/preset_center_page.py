#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Preset center page (HUD + Screen Effects + Special Sounds)."""

from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.presets.preset_center import apply_bundle, export_bundle, validate_bundle
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from resource_manager import ResourceManager
from page_theme_helper import style_as_danger_button
from widgets.dirty_page_mixin import DirtyPageMixin
from widgets.page_action_bar import PageActionBar
from widgets.my_presets_section import MyPresetsMixin
from widgets.settings_card import SettingsCard
from widgets.page_header import PageHeader

#: RN-429：本页两跳能够到 `ui_osd`，但那是**切预设时顺带弹的提示**，不是玩家在这一页配置的产出物。⭐ 判据问的是「这一页配的东西会不会画到游戏上」，不是「能不能够到覆盖层」。
DRAWS_OVER_THE_GAME = False


class PresetCenterPage(MyPresetsMixin, QWidget, DirtyPageMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("PresetCenterPage")
        self._current_bundle = None
        self.init_dirty_state()
        self._init_ui()
        self._render_preview()

    @staticmethod
    def _set_compact_heights(*controls, height=34):
        for control in controls:
            if control is not None:
                control.setMinimumHeight(height)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
        header = PageHeader(
            "预设中心",
            description="把一整套设置打包成「预设」，可一键切换或导出分享给朋友。点右上角「?」看用法。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["preset_center"])

        status_card, card_layout = SettingsCard.make("当前状态", spacing=10)
        self.status_card = status_card

        self.status_badge_label = create_badge_label()
        card_layout.addWidget(self.status_badge_label)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        card_layout.addWidget(self.summary_label)
        layout.addWidget(status_card)

        workbench_card, workbench_layout = SettingsCard.make(
            "预设工作台",
            "勾选要打包的范围，然后导出成文件发给别人；导入别人的预设也在这儿。", spacing=10
        )
        workbench_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.workbench_content_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self.workbench_content_layout.setSpacing(16)

        scope_column = QVBoxLayout()
        scope_column.setSpacing(8)
        scope_title = QLabel("打包范围")
        scope_title.setObjectName("statusLabel")
        scope_column.addWidget(scope_title)
        scope_hint = QLabel("先勾选要打包的模块，范围越清晰，导入导出时越不容易误操作。")
        scope_hint.setObjectName("hintLabel")
        scope_hint.setWordWrap(True)
        scope_column.addWidget(scope_hint)
        selection_row = QHBoxLayout()
        selection_row.setSpacing(8)
        self.cb_hud = QCheckBox("HUD 规则")
        self.cb_hud.setChecked(True)
        self.cb_screen = QCheckBox("屏幕特效")
        self.cb_screen.setChecked(True)
        self.cb_special = QCheckBox("特殊音效")
        self.cb_special.setChecked(True)
        selection_row.addWidget(self.cb_hud)
        selection_row.addWidget(self.cb_screen)
        selection_row.addWidget(self.cb_special)
        selection_row.addStretch()
        scope_column.addLayout(selection_row)
        # R2-1 schema v2:四个纯配置域
        selection_row2 = QHBoxLayout()
        selection_row2.setSpacing(8)
        self.cb_crosshair = QCheckBox("准心")
        self.cb_crosshair.setChecked(True)
        self.cb_flash = QCheckBox("自定闪光")
        self.cb_flash.setChecked(True)
        self.cb_viewmodel = QCheckBox("局内视角")
        self.cb_viewmodel.setChecked(False)
        self.cb_magnifier = QCheckBox("开镜放大")
        self.cb_magnifier.setChecked(False)
        for cb in (self.cb_crosshair, self.cb_flash, self.cb_viewmodel, self.cb_magnifier):
            selection_row2.addWidget(cb)
        selection_row2.addStretch()
        scope_column.addLayout(selection_row2)
        scope_column.addStretch(1)
        self.workbench_content_layout.addLayout(scope_column, 4)

        mode_column = QVBoxLayout()
        mode_column.setSpacing(8)
        mode_title = QLabel("导入策略")
        mode_title.setObjectName("statusLabel")
        mode_column.addWidget(mode_title)
        mode_static_hint = QLabel("合并适合保留已有配置，覆盖适合一键替换整套体验。")
        mode_static_hint.setObjectName("hintLabel")
        mode_static_hint.setWordWrap(True)
        mode_column.addWidget(mode_static_hint)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addWidget(QLabel("导入模式"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("合并 (merge)", "merge")
        self.mode_combo.addItem("覆盖 (replace)", "replace")
        self.mode_combo.setFixedWidth(180)
        self.mode_combo.setFixedHeight(34)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch()
        mode_column.addLayout(mode_row)

        self.mode_hint_label = QLabel("")
        self.mode_hint_label.setObjectName("hintLabel")
        self.mode_hint_label.setWordWrap(True)
        mode_column.addWidget(self.mode_hint_label)
        mode_column.addStretch(1)
        self.workbench_content_layout.addLayout(mode_column, 3)

        actions_column = QVBoxLayout()
        actions_column.setSpacing(8)
        actions_title = QLabel("快速操作")
        actions_title.setObjectName("statusLabel")
        actions_column.addWidget(actions_title)
        actions_hint = QLabel("导出、导入和应用放在一起，连续处理预设包时更顺手。")
        actions_hint.setObjectName("hintLabel")
        actions_hint.setWordWrap(True)
        actions_column.addWidget(actions_hint)
        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        self.export_btn = QPushButton("导出预设包")
        self.export_btn.setObjectName("secondaryButton")
        self.export_btn.clicked.connect(self._export_bundle_to_file)
        self.export_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        actions.addWidget(self.export_btn, 0, 0)

        self.import_btn = QPushButton("导入预设包")
        self.import_btn.setObjectName("secondaryButton")
        self.import_btn.clicked.connect(self._import_bundle_from_file)
        self.import_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        actions.addWidget(self.import_btn, 0, 1)

        # R2-1: .cs2customizer 分享文件(zip 容器,带安检与确认)
        self.share_export_btn = QPushButton("导出分享文件")
        self.share_export_btn.setObjectName("secondaryButton")
        self.share_export_btn.clicked.connect(self._export_share_file)
        self.share_export_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        actions.addWidget(self.share_export_btn, 1, 0)

        self.share_import_btn = QPushButton("导入分享文件")
        self.share_import_btn.setObjectName("secondaryButton")
        self.share_import_btn.clicked.connect(self._import_share_file_dialog)
        self.share_import_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        actions.addWidget(self.share_import_btn, 1, 1)

        self.apply_btn = QPushButton("应用当前预设")
        self.apply_btn.setObjectName("secondaryButton")
        self.apply_btn.clicked.connect(self._save_changes)
        self.apply_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._set_compact_heights(
            self.export_btn, self.import_btn,
            self.share_export_btn, self.share_import_btn, self.apply_btn,
        )
        actions.addWidget(self.apply_btn, 2, 0, 1, 2)
        actions_column.addLayout(actions)
        actions_column.addStretch(1)
        self.workbench_content_layout.addLayout(actions_column, 4)

        workbench_layout.addLayout(self.workbench_content_layout)
        layout.addWidget(workbench_card)

        # UP-040: 「我的预设」——命名保存/一键应用/改名/删除。
        # 在此之前换一整套配置只能「导出文件再导入文件」，等于软件把
        # 它自己该做的事（记住几套具名配置）推给了文件系统。
        self.build_my_presets_card(layout)

        # R2-2: 内置精选包(纯内置资源,零外部素材)
        starter_card, starter_layout = SettingsCard.make(
            "内置精选",
            "三套开箱即用的体验包,应用前自动备份当前配置,可在配置快照页回滚。",
            spacing=10,
        )
        starter_row = QHBoxLayout()
        starter_row.setSpacing(8)
        self.starter_combo = QComboBox()
        self.starter_combo.setFixedHeight(34)
        self.starter_combo.setMinimumWidth(200)
        from core.presets.starter_packs import list_packs

        for pid, name, desc in list_packs():
            self.starter_combo.addItem(name, pid)
            self.starter_combo.setItemData(self.starter_combo.count() - 1, desc, Qt.ToolTipRole)
        starter_row.addWidget(self.starter_combo)

        self.starter_apply_btn = QPushButton("一键应用")
        self.starter_apply_btn.setObjectName("secondaryButton")
        self.starter_apply_btn.clicked.connect(self._apply_starter_pack)
        starter_row.addWidget(self.starter_apply_btn)
        starter_row.addStretch()
        self._set_compact_heights(self.starter_apply_btn)
        starter_layout.addLayout(starter_row)

        self.starter_desc_label = QLabel("")
        self.starter_desc_label.setObjectName("hintLabel")
        self.starter_desc_label.setWordWrap(True)
        starter_layout.addWidget(self.starter_desc_label)
        self.starter_combo.currentIndexChanged.connect(self._sync_starter_desc)
        self._sync_starter_desc()
        layout.addWidget(starter_card)

        # R2-4: 按地图自动切预设
        map_card, map_layout = SettingsCard.make(
            "按地图自动切换",
            "把当前勾选范围保存成某张图的预设;进图时 GSI 自动套用(merge 模式,应用前自动快照)。",
            spacing=10,
        )
        self.map_auto_check = QCheckBox("启用按地图自动切换")
        from config import config as _config

        self.map_auto_check.setChecked(bool(getattr(_config, "map_preset_enabled", False)))
        self.map_auto_check.toggled.connect(self._on_map_auto_toggled)
        map_layout.addWidget(self.map_auto_check)

        map_row = QHBoxLayout()
        map_row.setSpacing(8)
        self.map_combo = QComboBox()
        self.map_combo.setEditable(True)
        for m in ("de_dust2", "de_mirage", "de_inferno", "de_nuke", "de_ancient",
                  "de_anubis", "de_vertigo", "de_overpass", "de_train"):
            self.map_combo.addItem(m)
        self.map_combo.setFixedHeight(34)
        self.map_combo.setMinimumWidth(180)
        map_row.addWidget(self.map_combo)

        self.map_save_btn = QPushButton("保存当前范围为该图预设")
        self.map_save_btn.setObjectName("secondaryButton")
        self.map_save_btn.clicked.connect(self._on_map_rule_save)
        map_row.addWidget(self.map_save_btn)

        self.map_delete_btn = QPushButton("删除该图预设")
        # R7/D-06: 直接删掉地图→预设绑定，**连确认对话框都没有**
        # （_on_map_rule_delete 直接 delete_rule 然后弹「已删除」）
        style_as_danger_button(self.map_delete_btn)
        self.map_delete_btn.clicked.connect(self._on_map_rule_delete)
        map_row.addWidget(self.map_delete_btn)
        map_row.addStretch()
        self._set_compact_heights(self.map_save_btn, self.map_delete_btn)
        map_layout.addLayout(map_row)

        self.map_rules_label = QLabel("")
        self.map_rules_label.setObjectName("hintLabel")
        self.map_rules_label.setWordWrap(True)
        map_layout.addWidget(self.map_rules_label)
        layout.addWidget(map_card)
        self._refresh_map_rules_label()

        preview_card, preview_layout = SettingsCard.make(
            "预设预览",
            "预览区域展示当前打包结果，方便在导出或应用前快速确认内容范围。", spacing=10
        )
        self.preview_meta_label = QLabel("")
        self.preview_meta_label.setObjectName("hintLabel")
        self.preview_meta_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_meta_label)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(340)
        preview_layout.addWidget(self.preview_text)
        layout.addWidget(preview_card)

        layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll)

        self.action_bar = PageActionBar(self)
        self.action_bar.set_message("支持 HUD / 屏幕特效 / 特殊音效 三域预设。")
        self.action_bar.configure_primary("应用当前预设", self._save_changes, visible=True)
        self.action_bar.configure_secondary("重新预览", self._render_preview, visible=True)
        root.addWidget(self.action_bar, 0)

        for checkbox in (
            self.cb_hud, self.cb_screen, self.cb_special,
            self.cb_crosshair, self.cb_flash, self.cb_viewmodel, self.cb_magnifier,
        ):
            checkbox.toggled.connect(self._on_selection_changed)
        self.mode_combo.currentIndexChanged.connect(self._on_selection_changed)
        self._update_compact_layout()

        # R2-1: 拖 .cs2customizer 进页面即走导入确认流程
        try:
            from widgets.drop_import_mixin import enable_file_drop

            enable_file_drop(self, (".cs2customizer",), self._on_share_file_dropped)
        except Exception:
            self.logger.exception("分享文件拖拽初始化失败")

    _TYPE_CHECKBOX_SPEC = (
        ("cb_hud", "hud_rules", "HUD"),
        ("cb_screen", "screen_effects", "屏幕特效"),
        ("cb_special", "special_sound", "特殊音效"),
        ("cb_crosshair", "crosshair", "准心"),
        ("cb_flash", "flash", "自定闪光"),
        ("cb_viewmodel", "viewmodel", "局内视角"),
        ("cb_magnifier", "magnifier", "开镜放大"),
    )

    def _selected_types(self):
        return [
            type_id
            for attr, type_id, _label in self._TYPE_CHECKBOX_SPEC
            if getattr(self, attr).isChecked()
        ]

    def _selected_type_labels(self):
        return [
            label
            for attr, _type_id, label in self._TYPE_CHECKBOX_SPEC
            if getattr(self, attr).isChecked()
        ]

    def _mode_label_text(self):
        return "覆盖" if str(self.mode_combo.currentData() or "merge") == "replace" else "合并"

    def _update_compact_layout(self):
        # UP-100: 这一页有**两处**需要按页宽换向，阈值不同（工作台三列 1120，
        # 「我的预设」那一行 960），因为它们的最小宽本来就不一样。
        # 以前只切了工作台，于是紧凑模式（页宽 860）下工作台竖过来了、
        # 「我的预设」那一行仍横着占 883px，整页横向滚动，24 个主题×字号组合全中。
        self._update_my_presets_layout(self.width())
        if not hasattr(self, "workbench_content_layout"):
            return
        direction = QBoxLayout.TopToBottom if self.width() < 1120 else QBoxLayout.LeftToRight
        if self.workbench_content_layout.direction() != direction:
            self.workbench_content_layout.setDirection(direction)

    def _sync_status_strip(self, bundle: dict | None = None):
        bundle = bundle or self._current_bundle or {}
        selected_labels = self._selected_type_labels()
        item_count = len((bundle or {}).get("items", []) or [])
        dirty = self.is_dirty()

        badges = [
            ("positive" if selected_labels else "warning", f"范围 · {len(selected_labels)} 类"),
            ("info", f"模式 · {self._mode_label_text()}"),
            ("positive" if item_count else "warning", f"内容 · {item_count} 项"),
            ("warning" if dirty else "positive", f"状态 · {'待应用' if dirty else '已同步'}"),
        ]

        if selected_labels:
            scope_text = " / ".join(selected_labels)
        else:
            scope_text = "当前未选择任何预设范围"
        detail_text = (
            f"当前选择范围：{scope_text}。"
            f"导入模式为“{self._mode_label_text()}”，"
            f"预览包内共 {item_count} 项。"
            f"{'还有未应用的改动。' if dirty else '当前预览已同步。'}"
        )
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.summary_label.setText(detail_text)
        self.summary_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)
        if hasattr(self, "preview_meta_label"):
            self.preview_meta_label.setText(
                f"当前预览范围：{scope_text} · 项数 {item_count} · 导入模式 {self._mode_label_text()}。"
            )
        if hasattr(self, "mode_hint_label"):
            self.mode_hint_label.setText(
                "合并会尽量保留现有配置，仅覆盖预设包中包含的字段。"
                if self._mode_label_text() == "合并"
                else "覆盖会直接替换对应模块，适合整套迁移。"
            )

    def _on_selection_changed(self):
        self.mark_dirty()
        self._render_preview()

    def _render_preview(self):
        bundle = export_bundle(self._selected_types())
        self._current_bundle = bundle
        self.preview_text.setPlainText(json.dumps(bundle, ensure_ascii=False, indent=2))
        self._sync_status_strip(bundle)

    def _load_settings(self):
        self._render_preview()

    def _refresh_dirty_ui(self):
        if self.is_dirty():
            self.action_bar.set_message("有未应用的预设变更。")
        else:
            self.action_bar.set_message("预设已同步。")
        self._sync_status_strip()

    def _save_changes(self):
        bundle = self._current_bundle or export_bundle(self._selected_types())
        validation = validate_bundle(bundle)
        if not validation.ok:
            QMessageBox.warning(self, "预设校验失败", "\n".join(validation.errors))
            return False
        result = apply_bundle(bundle, mode=self.mode_combo.currentData() or "merge")
        if not result.ok:
            QMessageBox.warning(self, "应用失败", "\n".join(result.errors))
            return False
        self.clear_dirty()
        # QA-013: 应用前的自动快照建失败时 warnings 里会有话，不能只报喜
        tail = ("\n\n" + "；".join(result.warnings)) if result.warnings else ""
        QMessageBox.information(
            self, "应用成功",
            f"已应用类型: {', '.join(result.applied_types) or '无'}{tail}")
        return True

    def _export_bundle_to_file(self):
        bundle = export_bundle(self._selected_types())
        default_dir = ResourceManager.get_app_data_path("presets")
        os.makedirs(default_dir, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出预设包",
            os.path.join(default_dir, "preset_bundle_v1.json"),
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(bundle, handle, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "导出成功", path)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

    def _import_bundle_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入预设包",
            ResourceManager.get_app_data_path("presets"),
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                bundle = json.load(handle)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return

        validation = validate_bundle(bundle)
        if not validation.ok:
            QMessageBox.warning(self, "校验失败", "\n".join(validation.errors))
            return
        self._current_bundle = bundle
        self.preview_text.setPlainText(json.dumps(bundle, ensure_ascii=False, indent=2))
        self.mark_dirty()
        self._sync_status_strip(bundle)

    # ---------------- R2-2: 内置精选包 ----------------

    def _sync_starter_desc(self):
        from core.presets.starter_packs import list_packs

        pid = self.starter_combo.currentData()
        for p, _name, desc in list_packs():
            if p == pid:
                self.starter_desc_label.setText(desc)
                return
        self.starter_desc_label.setText("")

    def _apply_starter_pack(self):
        from core.presets.starter_packs import get_pack_bundle

        pid = self.starter_combo.currentData()
        if not pid:
            return
        try:
            bundle = get_pack_bundle(pid)
        except KeyError:
            return
        reply = QMessageBox.question(
            self, "应用精选包?",
            f"将应用「{self.starter_combo.currentText()}」(merge 模式,应用前自动备份)。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        result = apply_bundle(bundle, mode="merge")
        if result.ok:
            self._render_preview()
            try:
                from ui_toast import toast_success, toast_warning

                name = self.starter_combo.currentText()
                if result.warnings:      # QA-013
                    toast_warning(f"已应用「{name}」，但{'；'.join(result.warnings)}")
                else:
                    toast_success(f"已应用「{name}」")
            except Exception:
                QMessageBox.information(self, "完成", "已应用")
        else:
            QMessageBox.warning(self, "应用失败", "\n".join(result.errors))

    # ---------------- R2-4: 按地图自动切预设 ----------------

    def _on_map_auto_toggled(self, checked):
        from config import config as _config

        _config.map_preset_enabled = bool(checked)
        _config.save_config()
        self.logger.info(f"按地图自动切预设: {'开' if checked else '关'}")

    def _on_map_rule_save(self):
        from core.presets.map_rules import save_rule

        map_name = self.map_combo.currentText()
        types = self._selected_types()
        if not types:
            QMessageBox.information(self, "提示", "请先在上方勾选要打包的范围")
            return
        if save_rule(map_name, types):
            self._refresh_map_rules_label()
            QMessageBox.information(self, "已保存", f"进入 {map_name.strip().lower()} 时将自动套用这套配置")
        else:
            QMessageBox.warning(self, "保存失败", "地图名为空或范围为空")

    def _on_map_rule_delete(self):
        from core.presets.map_rules import delete_rule

        map_name = self.map_combo.currentText()
        if delete_rule(map_name):
            self._refresh_map_rules_label()
            QMessageBox.information(self, "已删除", f"{map_name.strip().lower()} 的绑定已移除")
        else:
            QMessageBox.information(self, "提示", "该地图没有已保存的绑定")

    def _refresh_map_rules_label(self):
        from core.presets.map_rules import list_rules

        rules = list_rules()
        self.map_rules_label.setText(
            "已绑定: " + ", ".join(rules) if rules else "尚无地图绑定。勾选范围 → 选图 → 保存即可。"
        )

    # ---------------- R2-1: .cs2customizer 分享文件 ----------------

    def _export_share_file(self):
        from core.presets.share_file import SHARE_EXT, write_share_file

        types = self._selected_types()
        if not types:
            QMessageBox.information(self, "提示", "请先勾选要打包的范围")
            return
        bundle = export_bundle(types)
        default_dir = ResourceManager.get_app_data_path("presets")
        os.makedirs(default_dir, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出分享文件",
            os.path.join(default_dir, f"我的配置{SHARE_EXT}"),
            f"CS2 Customizer 分享文件 (*{SHARE_EXT})",
        )
        if not path:
            return
        if not path.lower().endswith(SHARE_EXT):
            path += SHARE_EXT
        try:
            write_share_file(path, bundle, title=os.path.splitext(os.path.basename(path))[0])
            QMessageBox.information(
                self, "导出成功",
                f"{path}\n\n把这个文件发给朋友,拖进对方的预设中心即可导入。",
            )
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

    def _import_share_file_dialog(self):
        from core.presets.share_file import LEGACY_SHARE_EXTS, SHARE_EXT

        patterns = " ".join(f"*{ext}" for ext in (SHARE_EXT, *LEGACY_SHARE_EXTS))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入分享文件",
            ResourceManager.get_app_data_path("presets"),
            f"CS2 Customizer 分享文件 ({patterns})",
        )
        if path:
            self._import_share_path(path)

    def _on_share_file_dropped(self, paths):
        if paths:
            self._import_share_path(paths[0])

    def _import_share_path(self, path):
        """读取→安检→预览确认→应用(应用前 preset_center 自动建快照)。"""
        from core.presets.share_file import describe, read_share_file

        result = read_share_file(path)
        if not result.ok:
            QMessageBox.warning(self, "无法导入", "\n".join(result.errors))
            self.logger.warning(f"分享文件被拒: {path} -> {result.errors}")
            return

        mode = self.mode_combo.currentData() or "merge"
        text = describe(result)
        if result.warnings:
            text += "\n\n注意: " + "; ".join(result.warnings)
        text += f"\n\n导入模式: {self._mode_label_text()}(应用前会自动备份当前配置,可在配置快照页回滚)"
        reply = QMessageBox.question(
            self, "确认导入这份配置?", text,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        apply_result = apply_bundle(result.bundle, mode=mode)
        if not apply_result.ok:
            QMessageBox.warning(self, "应用失败", "\n".join(apply_result.errors))
            return
        self._current_bundle = result.bundle
        self.preview_text.setPlainText(json.dumps(result.bundle, ensure_ascii=False, indent=2))
        self.clear_dirty()
        self._sync_status_strip(result.bundle)
        self.logger.info(f"分享文件导入成功: {path} -> {apply_result.applied_types}")
        try:
            from ui_toast import toast_success, toast_warning

            # QA-013: 这句话直接承诺"可回滚"，快照没建成时必须换口径，别骗用户
            if apply_result.warnings:
                toast_warning(
                    f"已导入 {len(apply_result.applied_types)} 类配置，"
                    f"但{'；'.join(apply_result.warnings)}")
            else:
                toast_success(
                    f"已导入 {len(apply_result.applied_types)} 类配置,删错可去配置快照页回滚")
        except Exception:
            QMessageBox.information(self, "导入成功", f"已应用: {', '.join(apply_result.applied_types)}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_compact_layout()
