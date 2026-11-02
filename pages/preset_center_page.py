#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Preset center page (HUD + Screen Effects + Special Sounds)."""

# 注释来历：docs/notes/代码注释的来历_preset_center_page.md
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
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

from core.presets.preset_center import (
    TYPE_LABELS,
    apply_bundle,
    export_bundle,
    mode_affects_result,
    validate_bundle,
)
from core.utils.logger import get_logger
from resource_manager import ResourceManager
from page_theme_helper import style_as_danger_button
from widgets.flow_layout import make_flow_container
from widgets.page_action_bar import PageActionBar
from widgets.my_presets_section import MyPresetsMixin
from widgets.settings_card import SettingsCard
from widgets.settings_row import PLAIN_CONTROL_WIDTH
from widgets.page_header import PageHeader

#: RN-429：切预设的 OSD 提示不算本页配置的游戏画面产出。
DRAWS_OVER_THE_GAME = False


#: RN-519：卡片说明要点名这颗按钮，而说明比按钮先建 —— 名字只留一份。
STARTER_APPLY_BUTTON_TEXT = "一键应用"


class PresetCenterPage(MyPresetsMixin, QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("PresetCenterPage")
        self._current_bundle = None
        self._init_ui()
        self._render_preview()

    @staticmethod
    def _chain_tab_order(cards):
        """卡内构造顺序已等于阅读顺序，只需按卡片摆放顺序重串焦点链。"""
        chain = []
        for card in cards:
            chain += [w for w in card.findChildren(QWidget)
                      if w.focusPolicy() != Qt.NoFocus and w.isVisibleTo(card)]
        for previous, following in zip(chain, chain[1:]):
            QWidget.setTabOrder(previous, following)

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

        # UP-047：沿用本页字号与间距，保持现有布局。
        from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
        header = PageHeader(
            "预设中心",
            description="把一整套设置打包成「预设」，可一键切换或导出分享给朋友。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["preset_center"])

        # ⛔⛔ RN-496（批 52）：**这一页不再有「当前状态」卡。**
        #
        # 跨页普查（两档各一遍）：28/28 页都有状态卡、卡高 68~251px，而这一页是
        # **唯一一页只剩一颗胶囊**的 —— 别的页报的是 GSI 连没连、总开关关没关、
        # 驱动装没装、素材缺不缺，那些确实无处可看。
        # 而这一页那唯一一颗「范围 · 5/7 类」，数的正是它**正下方 12px**
        # 那张卡上逐个画着的七个勾选框；外审 12/12 报它
        # 「顶部黄金位置被不可交互的抽象参数占据」，是全轮最高频项。
        #
        # ⭐⭐ 更要紧的是**它当初为什么留下来**：批 40 的注释逐字写着
        #   「本批的重排把那七个勾选框挪到了折线以下，第一屏上只剩这颗胶囊」——
        #   它是那七个勾选框**看不见时的替身**。而同一批后来又把范围卡提到第 3 位
        #   （实测完整档 top=399、底 542，远在折线 710 之上）。
        #   ⇒ **替身的理由过期了，替身没走。**
        #   这不是一次新的取舍，是收一笔重排那天就该收的账。
        #
        # 撤掉换来（实测，两档 × 音乐条两态）：完整档 + 音乐条那两颗交换按钮
        # **29% → 100%** —— 那正是 RN-486 当初只结了一半的那一笔。

        # RN-477：范围控制导出、具名预设和地图保存，独立成页级卡。
        scope_card, scope_layout = SettingsCard.make(
            "保存/导出的范围",
            "导出文件、存为预设、按地图保存，都按这里勾的来。"
            "读入别人的文件时按文件里写的来，不看这里。",
            spacing=10,
        )
        # 七个一行，放不下才折，避免固定分排时列不齐。
        selection_wrap, selection_flow = make_flow_container(h_spacing=16, v_spacing=8)
        self.cb_hud = QCheckBox("HUD 规则")
        self.cb_hud.setChecked(True)
        self.cb_screen = QCheckBox("屏幕特效")
        self.cb_screen.setChecked(True)
        self.cb_special = QCheckBox("特殊音效")
        self.cb_special.setChecked(True)
        # R2-1 schema v2:四个纯配置域
        self.cb_crosshair = QCheckBox("准心")
        self.cb_crosshair.setChecked(True)
        self.cb_flash = QCheckBox("自定闪光")
        self.cb_flash.setChecked(True)
        self.cb_viewmodel = QCheckBox("局内视角")
        self.cb_viewmodel.setChecked(False)
        self.cb_magnifier = QCheckBox("开镜放大")
        self.cb_magnifier.setChecked(False)
        for cb in (self.cb_hud, self.cb_screen, self.cb_special,
                   self.cb_crosshair, self.cb_flash, self.cb_viewmodel, self.cb_magnifier):
            selection_flow.addWidget(cb)
        scope_layout.addWidget(selection_wrap)
        layout.addWidget(scope_card)

        # RN-484：导入模式仅在确认文件时有意义，且只在两种模式结果不同时询问。
        workbench_card, workbench_layout = SettingsCard.make(
            "和朋友交换配置",
            "把你这一套存成文件发给朋友；或者打开朋友发来的文件，直接用那一套。",
            spacing=10
        )
        workbench_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        # RN-478：两种文件共用导入/导出入口，容器格式在幕后分派。
        actions = QHBoxLayout()
        actions.setSpacing(8)
        # RN-485：按钮文案不含句子标点，否则搜索索引会丢弃它。
        self.export_btn = QPushButton("导出成文件发给朋友")
        self.export_btn.setObjectName("secondaryButton")
        self.export_btn.clicked.connect(self._export_config_file)
        actions.addWidget(self.export_btn)

        self.import_btn = QPushButton("打开一份配置文件")
        self.import_btn.setObjectName("secondaryButton")
        self.import_btn.setToolTip("两种文件都能打开：.cs2customizer（推荐，带说明和安检）和 .json。")
        self.import_btn.clicked.connect(self._open_config_file)
        actions.addWidget(self.import_btn)
        actions.addStretch()

        # RN-478：导入直接确认并应用，不保留待应用状态或 DirtyPageMixin。
        workbench_layout.addLayout(actions)
        layout.addWidget(workbench_card)

        my_presets_card = self.build_my_presets_card(layout)

        # R2-2: 内置精选包(纯内置资源,零外部素材)
        starter_card, starter_layout = SettingsCard.make(
            "内置精选",
            # 自动快照说明在同屏底栏统一展示，避免卡片重复承诺。
            "三套开箱即用的设置，选一套点"
            f"「{STARTER_APPLY_BUTTON_TEXT}」就换过去。",
            spacing=10,
        )
        starter_row = QHBoxLayout()
        starter_row.setSpacing(8)
        self.starter_combo = QComboBox()
        self.starter_combo.setFixedWidth(PLAIN_CONTROL_WIDTH)
        from core.presets.starter_packs import list_packs

        for pid, name, desc in list_packs():
            self.starter_combo.addItem(name, pid)
            self.starter_combo.setItemData(self.starter_combo.count() - 1, desc, Qt.ToolTipRole)
        starter_row.addWidget(self.starter_combo)

        self.starter_apply_btn = QPushButton(STARTER_APPLY_BUTTON_TEXT)
        self.starter_apply_btn.setObjectName("secondaryButton")
        self.starter_apply_btn.clicked.connect(self._apply_starter_pack)
        starter_row.addWidget(self.starter_apply_btn)
        starter_row.addStretch()
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
            "把「保存/导出的范围」勾中的类别存成某张图的预设；进这张图时自动套用。",
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
        self.map_combo.setFixedWidth(PLAIN_CONTROL_WIDTH)
        map_row.addWidget(self.map_combo)

        self.map_save_btn = QPushButton("保存当前范围为该图预设")
        self.map_save_btn.setObjectName("secondaryButton")
        self.map_save_btn.clicked.connect(self._on_map_rule_save)
        map_row.addWidget(self.map_save_btn)

        self.map_delete_btn = QPushButton("删除该图预设")
        # R7/D-06：删除无需确认，使用危险按钮样式。
        style_as_danger_button(self.map_delete_btn)
        self.map_delete_btn.clicked.connect(self._on_map_rule_delete)
        map_row.addWidget(self.map_delete_btn)
        map_row.addStretch()
        map_layout.addLayout(map_row)

        self.map_rules_label = QLabel("")
        self.map_rules_label.setObjectName("hintLabel")
        self.map_rules_label.setWordWrap(True)
        map_layout.addWidget(self.map_rules_label)
        layout.addWidget(map_card)
        # 换一张图 ⇒「删除该图预设」能不能点得跟着变（`_refresh_map_rules_label`）。
        self.map_combo.currentTextChanged.connect(
            lambda *_a: self._refresh_map_rules_label())
        self._refresh_map_rules_label()

        # RN-476：默认展示摘要，原始 JSON 仅在主动展开时显示。
        preview_card, preview_layout = SettingsCard.make(
            "范围里现在的内容",
            "下面这几行就是导出文件里会带走的东西，也是「存为新预设」会记住的东西。",
            spacing=10,
        )
        self.preview_summary_label = QLabel("")
        self.preview_summary_label.setObjectName("hintLabel")
        self.preview_summary_label.setWordWrap(True)
        self.preview_summary_label.setTextFormat(Qt.PlainText)
        preview_layout.addWidget(self.preview_summary_label)

        self.raw_toggle_btn = QPushButton("查看原始内容")
        self.raw_toggle_btn.setObjectName("secondaryButton")
        self.raw_toggle_btn.setCheckable(True)
        self.raw_toggle_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.raw_toggle_btn.toggled.connect(self._on_raw_toggled)
        preview_layout.addWidget(self.raw_toggle_btn)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(340)
        # RN-009：原始内容由上方开关重新显示，并非永久隐藏的控件。
        self.preview_text.setVisible(False)
        preview_layout.addWidget(self.preview_text)
        layout.addWidget(preview_card)

        # RN-477/486：精选与范围、交换入口优先于空的个人预设；范围不控制精选应用。
        # 共用件已自行入队，需统一重排；从页头后插入，避免把页头挤到底部。
        card_order = (starter_card, scope_card,
                      workbench_card, my_presets_card, map_card, preview_card)
        first = layout.indexOf(header) + 1
        for offset, card in enumerate(card_order):
            layout.removeWidget(card)
            layout.insertWidget(first + offset, card)

        # Qt 焦点链默认按构造顺序，重排卡片后必须显式同步 Tab 顺序。
        self._chain_tab_order(card_order)

        layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll)

        self.action_bar = PageActionBar(self)
        # RN-281/452：应用在导入确认时完成，底栏不再提供重复的应用按钮。
        self.action_bar.configure_primary("", None, visible=False)
        # 预览随勾选刷新；单独重预览会覆盖 _current_bundle。
        root.addWidget(self.action_bar, 0)
        self._refresh_bottom_message()

        for checkbox in (
            self.cb_hud, self.cb_screen, self.cb_special,
            self.cb_crosshair, self.cb_flash, self.cb_viewmodel, self.cb_magnifier,
        ):
            checkbox.toggled.connect(self._on_selection_changed)
        self._update_compact_layout()

        # R2-1: 拖 .cs2customizer 进页面即走导入确认流程
        try:
            from widgets.drop_import_mixin import enable_file_drop

            # 后缀取共享常量，兼容开源子集及其旧格式。
            from core.presets.share_file import LEGACY_SHARE_EXTS, SHARE_EXT

            enable_file_drop(
                self, (SHARE_EXT, *LEGACY_SHARE_EXTS, ".json"),
                self._on_share_file_dropped)
        except Exception:
            self.logger.exception("分享文件拖拽初始化失败")

    _TYPE_CHECKBOX_SPEC = (
        # 预览与勾选框使用同一类别名。
        ("cb_hud", "hud_rules", "HUD 规则"),
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


    def _update_compact_layout(self):
        # UP-100：工作台只剩一列，仅个人预设行需要随页宽换向。
        self._update_my_presets_layout(self.width())

    def _on_selection_changed(self):
        # 勾选只决定保存/导出范围，不改配置，也不产生未保存状态。
        self._render_preview()
        # 个人预设提示包含当前勾选，范围变化时必须同步。
        self._sync_my_preset_hint()

    def _on_raw_toggled(self, checked: bool):
        self.preview_text.setVisible(bool(checked))
        self.raw_toggle_btn.setText("收起原始内容" if checked else "查看原始内容")

    def _render_preview(self):
        """预览始终反映当前配置，不保留待应用的导入包。"""
        bundle = export_bundle(self._selected_types())
        self._current_bundle = bundle
        self.preview_summary_label.setText(self._summary_text(bundle))
        self.preview_text.setPlainText(json.dumps(bundle, ensure_ascii=False, indent=2))

    @staticmethod
    def _summary_text(bundle: dict) -> str:
        """RN-476：摘要内容统一由 core.presets.preset_center 决定，此处仅负责排版。"""
        from core.presets.preset_center import describe_bundle

        rows = describe_bundle(bundle)
        if not rows:
            return "一类都没勾，这一套现在是空的。到上面「保存/导出的范围」勾上至少一类。"
        return "\n".join(f"· {label}：{detail}" for label, detail in rows)

    def showEvent(self, event):
        # RN-489：自动快照开关可能在别页改变，每次显示都需更新底栏承诺。
        super().showEvent(event)
        self._refresh_bottom_message()


    def _refresh_bottom_message(self):
        # RN-283：首屏与后续刷新共用此出口；自动快照可关闭，说明必须跟随开关。
        from config import config as _cfg

        # 所有应用通路均为 merge，只修改预设覆盖到的键。
        auto_snapshot = bool(getattr(_cfg, "config_snapshot_auto_before_risky_ops", True))
        if auto_snapshot:
            from widgets import page_route as _pr

            target = _pr.page_route("config_snapshot",
                                    _pr.page_label(self, "config_snapshot"))
            tail = f"；动手前会自动存一份快照，可以在{target}页回滚。"
        else:
            tail = "。你把「危险操作前自动快照」关掉了，这一次改过去就回不来了。"
        self.action_bar.set_message(
            "应用一套预设，会立刻改掉这套预设覆盖到的那几类设置，别的不动" + tail,
            rich=auto_snapshot, important=True)

    # ---------------- RN-478：一个动作一颗按钮，两种文件都吃 ----------------

    def _export_config_file(self):
        """导出共用一个入口，文件类型由保存对话框选择。"""
        from core.presets.share_file import SHARE_EXT, write_share_file

        types = self._selected_types()
        if not types:
            QMessageBox.information(
                self, "提示", "「保存/导出的范围」一类都没勾，导出来会是个空文件。")
            return
        bundle = export_bundle(types)
        default_dir = ResourceManager.get_app_data_path("presets")
        os.makedirs(default_dir, exist_ok=True)
        path, chosen = QFileDialog.getSaveFileName(
            self,
            "导出这一套配置",
            os.path.join(default_dir, f"我的配置{SHARE_EXT}"),
            f"CS2 Customizer 分享文件 (*{SHARE_EXT});;JSON 文件 (*.json)",
        )
        if not path:
            return
        if not path.lower().endswith((SHARE_EXT, ".json")):
            path += ".json" if "json" in (chosen or "").lower() else SHARE_EXT
        try:
            if path.lower().endswith(".json"):
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(bundle, handle, ensure_ascii=False, indent=2)
            else:
                write_share_file(
                    path, bundle, title=os.path.splitext(os.path.basename(path))[0])
            QMessageBox.information(
                self, "导出成功",
                f"{path}\n\n把这个文件发给朋友，拖进对方的预设中心即可导入。")
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

    def _open_config_file(self):
        # 开源子集的旧后缀由 LEGACY_SHARE_EXTS 统一声明。
        from core.presets.share_file import LEGACY_SHARE_EXTS, SHARE_EXT

        patterns = " ".join(f"*{ext}" for ext in (SHARE_EXT, *LEGACY_SHARE_EXTS))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开一份配置文件",
            ResourceManager.get_app_data_path("presets"),
            f"配置文件 ({patterns} *.json)",
        )
        if path:
            self._import_config_path(path)

    def _read_config_file(self, path):
        """按扩展名读取并统一返回 (bundle, 说明, warnings)；失败返回 (None, 原因, [])。"""
        from core.presets.share_file import (
            LEGACY_SHARE_EXTS,
            SHARE_EXT,
            describe,
            read_share_file,
        )

        # 兼容旧分享后缀，避免把 ZIP 误当 JSON 读取。
        if path.lower().endswith((SHARE_EXT, *LEGACY_SHARE_EXTS)):
            result = read_share_file(path)
            if not result.ok:
                return None, "\n".join(result.errors), []
            return result.bundle, describe(result), list(result.warnings)

        # RN-488：JSON 与分享包共用体积上限，统一下游不能绕过上游安检。
        try:
            from core.presets.share_file import MAX_ARCHIVE_BYTES

            size = os.path.getsize(path)
            if size > MAX_ARCHIVE_BYTES:
                return None, (
                    f"这个文件有 {size // 1024 // 1024} MB，超过了 "
                    f"{MAX_ARCHIVE_BYTES // 1024 // 1024} MB 的上限，没有打开。"
                ), []
            with open(path, "r", encoding="utf-8") as handle:
                bundle = json.load(handle)
        except Exception as exc:
            return None, f"这个文件读不开：{exc}", []
        validation = validate_bundle(bundle)
        if not validation.ok:
            return None, "\n".join(validation.errors), []
        # 导入空包不读本页勾选，不能复用指向导出范围的空态说明。
        items = bundle.get("items", []) or []
        if not items:
            return bundle, "这份文件里一类配置都没有，导入它不会改变任何设置。", list(
                validation.warnings)
        rows = self._summary_text(bundle)
        return bundle, f"包含 {len(items)} 类配置:\n{rows}", list(
            validation.warnings)

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
            self, "应用精选预设?",
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
            QMessageBox.information(
                self, "提示", "「保存/导出的范围」一类都没勾，没有东西可以存给这张图。")
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

        # 删除只针对当前地图；其他地图有绑定不能让这颗按钮可用。
        btn = getattr(self, "map_delete_btn", None)
        if btn is None:
            return
        current = str(self.map_combo.currentText()).strip().lower()
        bound = current in {str(r).strip().lower() for r in rules}
        btn.setEnabled(bound)
        btn.setToolTip(
            f"删掉「{current}」的绑定，进这张图时不再自动套用。"
            if bound else
            f"「{current or '这张图'}」还没有绑定过预设，没有可删的东西。")

    # ---------------- 打开一份配置文件：两种扩展名汇成一条路 ----------------

    def _on_share_file_dropped(self, paths):
        if paths:
            self._import_config_path(paths[0])

    def _import_config_path(self, path):
        """两种格式统一读取、确认、应用；快照结果由 apply_bundle 返回。"""
        bundle, text, warnings = self._read_config_file(path)
        if bundle is None:
            QMessageBox.warning(self, "无法导入", text)
            self.logger.warning(f"配置文件被拒: {path} -> {text}")
            return

        if warnings:
            text += "\n\n注意: " + "; ".join(warnings)
        text += "\n\n应用前会自动备份当前设置，可在「软件设置快照」页回滚。"

        # RN-484：仅当该文件使 merge/replace 结果不同时才询问模式。
        conflicts = mode_affects_result(bundle)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("确认导入这份配置?")
        box.setText(text)
        if conflicts:
            names = "、".join(sorted({TYPE_LABELS.get(t, t) for t, _k in conflicts}))
            box.setInformativeText(
                f"这份文件里有{names}的自定义条目，和你现在的条目不是同一批。\n"
                "要怎么处理你自己加的那些？"
            )
            box.addButton("留着，只补上文件里的", QMessageBox.AcceptRole)
            replace_btn = box.addButton("清掉，只要文件里的", QMessageBox.DestructiveRole)
        else:
            box.addButton("导入", QMessageBox.AcceptRole)
            replace_btn = None
        cancel_btn = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None or clicked is cancel_btn:
            return
        mode = "replace" if (replace_btn is not None and clicked is replace_btn) else "merge"

        apply_result = apply_bundle(bundle, mode=mode)
        if not apply_result.ok:
            QMessageBox.warning(self, "应用失败", "\n".join(apply_result.errors))
            return
        # 应用后按当前勾选重新导出，保持预览始终反映当前配置。
        self._render_preview()
        self.logger.info(f"配置文件导入成功: {path} -> {apply_result.applied_types}")
        try:
            from ui_toast import toast_success, toast_warning

            # QA-013: 这句话直接承诺"可回滚"，快照没建成时必须换口径，别骗用户
            if apply_result.warnings:
                toast_warning(
                    f"已导入 {len(apply_result.applied_types)} 类配置，"
                    f"但{'；'.join(apply_result.warnings)}")
            else:
                toast_success(
                    f"已导入 {len(apply_result.applied_types)} 类配置，删错可去「软件设置快照」页回滚")
        except Exception:
            QMessageBox.information(self, "导入成功", f"已应用: {', '.join(apply_result.applied_types)}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_compact_layout()
