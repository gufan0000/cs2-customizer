#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
局内视角设置页面（持枪视角 + 准心回正）
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QLineEdit, QSlider, QCheckBox, QGridLayout, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal

from config import config, DEFAULT_VIEWMODEL_PRESETS
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from cfg_utils import setup_autoexec
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from ui_style_applier import keep_single_line
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
from widgets.settings_row import plain_row
from widgets.status_strip import StatusStrip
import keyboard
import time
import os

#: 预设表前两列是名称和快捷键，从这一列起是滑条。
PRESET_FIRST_SLIDER_COLUMN = 2


def _slider_value_label(text):
    """滑条后面的数值：定宽右对齐，拖动时一列不抖。"""
    label = keep_single_line(QLabel(text))
    label.setFixedWidth(32)
    label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return label


class AutoSwitchWorker(QThread):
    """自动切换工作线程"""
    status_changed = Signal(bool)  # 状态改变信号
    
    def __init__(self, switch_key, interval, cycle_key, parent=None):
        super().__init__(parent)
        self.switch_key = switch_key.lower()
        self.interval = interval
        self.cycle_key = cycle_key.lower()
        self.is_running = False
        self.is_active = False
        
    def run(self):
        """运行自动切换"""
        self.is_running = True
        try:
            # 以启动瞬间状态作为基线，避免启动时误触发一次切换
            last_switch_pressed = keyboard.is_pressed(self.switch_key)
        except Exception:
            last_switch_pressed = False
        while self.is_running:
            try:
                switch_pressed = keyboard.is_pressed(self.switch_key)
                # 仅在按键“按下沿”时切换状态，避免长按/抖动导致反复触发
                if switch_pressed and not last_switch_pressed:
                    self.is_active = not self.is_active
                    self.status_changed.emit(self.is_active)
                last_switch_pressed = switch_pressed

                if self.is_active:
                    keyboard.press_and_release(self.cycle_key)
                    # 可中断等待：stop() 置位后最多约 0.05s 退出，
                    # 避免退出软件/关闭开关时卡满一个切换间隔
                    self._interruptible_sleep(max(0.1, float(self.interval)))
                else:
                    time.sleep(0.05)
            except Exception:
                time.sleep(0.1)

    def stop(self):
        """停止工作线程"""
        self.is_running = False
        self.is_active = False

    def _interruptible_sleep(self, seconds):
        """把长等待切成 0.05s 小片，is_running 置 False 后立即跳出，
        避免 _stop_auto_switch 的 wait() 长时间阻塞 UI。"""
        end = time.monotonic() + max(0.0, float(seconds))
        while self.is_running and time.monotonic() < end:
            time.sleep(0.05)


class ViewmodelPage(QWidget):
    """局内视角设置页面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("ViewmodelPage")
        
        # 默认预设（与 config 共用 DEFAULT_VIEWMODEL_PRESETS，避免 UI / config 两套默认值分叉）
        self.presets = [dict(p) for p in DEFAULT_VIEWMODEL_PRESETS]
        
        # 预设控件引用
        self.preset_vars = []
        
        # 自动切换线程
        self.auto_switch_thread = None

        # 加载中标志（防止 load_settings 触发未保存提示）
        self._loading = True

        # CFG 脏标记的唯一真源（RN-452，见 `_cfg_is_dirty` 的注释）
        self._cfg_dirty = False

        # 初始化UI
        self._init_ui()

        # 加载设置
        self.load_settings()
        self._loading = False

        # 配置为"自动切换已启用"时要真正拉起线程：load 期间 setChecked
        # 触发的 _on_auto_switch_toggled 被 _loading 短路，勾选态与线程
        # 状态会不一致（显示已开但功能未跑）
        if getattr(config, "viewmodel_auto_switch_enabled", False):
            self._start_auto_switch()

    
    def _init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        
        # 标题
        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "局内视角设置",
            description="调局内武器模型的位置和视角，可存成预设一键切换，改完同步进 CFG。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        main_layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["viewmodel"])

        self.status_card = StatusStrip()
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(0, 0, 0, 0)
        status_card_layout.setSpacing(8)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.status_badge_label = create_badge_label()
        status_row.addWidget(self.status_badge_label, 1)
        status_row.addStretch()
        status_card_layout.addLayout(status_row)

        # ⚠ RN-009：这里原来有一个 `self.summary_label` —— 建出来就 `hide()`，
        # 全仓没有任何一处让它显示回来，而每次状态同步还照给它 `setText` 七行详情。
        # 那七行本来就已经由徽章的 detail_tooltip 和 `status_card.setToolTip()` 给出，
        # 删掉不丢任何信息。别再往这张卡里加第三份看不见的副本。
        main_layout.addWidget(self.status_card)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        # 滚动内容容器
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 6, 0)
        scroll_layout.setSpacing(10)

        # RN-083、RN-177：预设是这一页最要紧的东西，排最前面，五组要在首屏看全。
        # 批 150：原来每组一张内层卡（5 × 112 px），现在一组一行、共用一个网格，列自然对齐。
        # 卡片的先后就是屏幕的先后：Tab 焦点链走构造顺序，不用 setTabOrder（RN-069）。
        presets_frame, presets_layout = SettingsCard.make("视角预设")
        presets_grid = QGridLayout()
        presets_grid.setContentsMargins(0, 0, 0, 0)
        presets_grid.setHorizontalSpacing(16)
        presets_grid.setVerticalSpacing(8)
        for column, title in enumerate(("名称", "快捷键", "FOV", "X", "Y", "Z")):
            heading = keep_single_line(QLabel(title))
            heading.setObjectName("hintLabel")
            presets_grid.addWidget(heading, 0, column)
            if column >= PRESET_FIRST_SLIDER_COLUMN:
                presets_grid.setColumnStretch(column, 1)
        for i, preset in enumerate(self.presets):
            self._add_preset_row(presets_grid, preset, i + 1)
        presets_layout.addLayout(presets_grid)
        axes_hint = QLabel("X 左右，Y 前后，Z 上下；FOV 越大枪看着越小。")
        axes_hint.setObjectName("hintLabel")
        presets_layout.addWidget(axes_hint)
        scroll_layout.addWidget(presets_frame)

        switch_card, switch_layout = SettingsCard.make(
            "持枪切换",
            "按循环按键切到下一组预设。开了自动循环：按激活按键开始或暂停，每隔几秒自动切一组。",
        )
        self.cycle_key_input = QLineEdit()
        self.cycle_key_input.setText("CAPSLOCK")
        self.cycle_key_input.textChanged.connect(lambda: self._mark_unsaved())
        switch_layout.addWidget(plain_row("循环按键", self.cycle_key_input))

        self.auto_switch_checkbox = QCheckBox("启用自动循环切换")
        self.auto_switch_checkbox.toggled.connect(self._on_auto_switch_toggled)
        switch_layout.addWidget(plain_row("", self.auto_switch_checkbox, width=None))

        self.auto_switch_key_input = QLineEdit()
        self.auto_switch_key_input.setText("V")
        self.auto_switch_key_input.textChanged.connect(lambda: self._mark_unsaved())

        self.auto_switch_interval_input = QLineEdit()
        self.auto_switch_interval_input.setFixedWidth(72)
        self.auto_switch_interval_input.setText("3.0")
        self.auto_switch_interval_input.textChanged.connect(lambda: self._mark_unsaved())
        switch_layout.addWidget(plain_row(
            "激活按键", self.auto_switch_key_input,
            QLabel("切换间隔"), self.auto_switch_interval_input, QLabel("秒")))
        scroll_layout.addWidget(switch_card)

        crosshair_card, crosshair_layout = SettingsCard.make("准心快速回正")
        self.crosshair_reset_checkbox = QCheckBox("启用准心快速回正")
        self.crosshair_reset_checkbox.setToolTip("开火时准心跟随后坐力，松开后瞬间回正（无曲线动画）")
        self.crosshair_reset_checkbox.stateChanged.connect(self._on_crosshair_reset_changed)
        crosshair_layout.addWidget(self.crosshair_reset_checkbox)

        self.crosshair_info = QLabel(
            "开火时准心跟随后坐力，松开瞬间回正。只对你自己生效，队友和 demo 里看不到。"
        )
        self.crosshair_info.setObjectName("hintLabel")
        self.crosshair_info.setWordWrap(True)
        crosshair_layout.addWidget(self.crosshair_info)

        self.crosshair_attack_key_edit = QLineEdit()
        self.crosshair_attack_key_edit.setPlaceholderText("mouse1")
        self.crosshair_attack_key_edit.setToolTip(
            "改过开火键的话填这里，默认 mouse1。填了识别不了的名字会自动退回 mouse1。"
        )
        self.crosshair_attack_key_edit.editingFinished.connect(self._on_crosshair_attack_key_changed)

        self.crosshair_secondary_checkbox = QCheckBox("副开火键也回正（R8 左轮右键）")
        self.crosshair_secondary_checkbox.setToolTip(
            "默认关。CFG 没有计数器，两个开火键同时按住时先松开的那个会提前回正；"
            "实战里很少同时按，介意的话保持关闭。"
        )
        self.crosshair_secondary_checkbox.stateChanged.connect(self._on_crosshair_secondary_changed)
        crosshair_layout.addWidget(plain_row(
            "开火键", self.crosshair_attack_key_edit, self.crosshair_secondary_checkbox))
        scroll_layout.addWidget(crosshair_card)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area, 1)

        self.action_bar = PageActionBar(self)
        main_layout.addWidget(self.action_bar, 0)


    def _create_badge_label(self):
        badge = QLabel()
        badge.setObjectName("badgeLabel")
        badge.setAlignment(Qt.AlignCenter)
        return badge

    def _set_badge_state(self, label, text, tone="info"):
        label.setText(text)
        label.setProperty("tone", tone)
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()

    def _compact_badge_text(self, value, fallback="-", max_length=12):
        text = str(value or "").strip() or fallback
        if len(text) > max_length:
            return text[: max_length - 1] + "…"
        return text

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        is_dirty = self._cfg_is_dirty()
        self.action_bar.configure_primary("保存到CFG", self._save_viewmodel_cfg, visible=True)
        # RN-504：CFG 已同步的时候这颗按钮别再喊
        self.action_bar.set_primary_pending(is_dirty)
        # 批 150：「CFG 同步」卡撤了，写没写进去就说在这颗按钮旁边（RN-404：保存这个动作归底栏）。
        # RN-452：这句话从 `_cfg_dirty` 渲染，别再反过来拿它算状态。
        state = "改动还没写进 CFG；写进之后" if is_dirty else "这一页的设置已经写进 CFG，"
        self.action_bar.set_message(
            f"{state}下一局自动生效；当局要立刻见效，在游戏控制台敲 exec cs2customizer.cfg。",
            important=True)

    def _sync_status_strip(self):
        is_dirty = self._cfg_is_dirty()
        cycle_key = self._compact_badge_text(
            self.cycle_key_input.text() if hasattr(self, "cycle_key_input") else "",
            "CAPSLOCK",
            10,
        )
        auto_key = self._compact_badge_text(
            self.auto_switch_key_input.text() if hasattr(self, "auto_switch_key_input") else "",
            "-",
            8,
        )
        auto_interval = self._compact_badge_text(
            self.auto_switch_interval_input.text() if hasattr(self, "auto_switch_interval_input") else "",
            "-",
            6,
        )
        auto_enabled = self.auto_switch_checkbox.isChecked() if hasattr(self, "auto_switch_checkbox") else False
        crosshair_enabled = (
            self.crosshair_reset_checkbox.isChecked()
            if hasattr(self, "crosshair_reset_checkbox")
            else False
        )
        preset_count = len(getattr(self, "preset_vars", []))
        badges = [
            ("warning" if is_dirty else "positive", "CFG · 待同步" if is_dirty else "CFG · 已同步"),
            ("positive" if crosshair_enabled else "info", f"准星回正 · {'开' if crosshair_enabled else '关'}"),
            ("positive" if auto_enabled else "info", f"自动切换 · {'开' if auto_enabled else '关'}"),
            ("info", f"循环键 · {cycle_key}"),
            ("positive", f"预设 · {preset_count} 组"),
        ]

        detail_text = (
            f"CFG 状态：{'待同步' if is_dirty else '已同步'}\n"
            f"准星回正：{'已启用' if crosshair_enabled else '未启用'}\n"
            f"自动切换：{'已启用' if auto_enabled else '未启用'}\n"
            f"自动切换键：{auto_key}\n"
            f"自动切换间隔：{auto_interval} 秒\n"
            f"循环切换键：{cycle_key}\n"
            f"预设数量：{preset_count} 组"
        )
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.status_card.setToolTip(detail_text)
        self._sync_action_bar()


    def _add_preset_row(self, grid, preset, row):
        """预设表的一行：名称、快捷键、四根滑条。"""
        name_input = QLineEdit()
        name_input.setText(preset["name"])
        name_input.setFixedWidth(110)
        name_input.textChanged.connect(lambda: self._mark_unsaved())
        grid.addWidget(name_input, row, 0)

        key_input = QLineEdit()
        key_input.setText(preset["key"])
        key_input.setFixedWidth(72)
        key_input.textChanged.connect(lambda: self._mark_unsaved())
        grid.addWidget(key_input, row, 1)

        fov_value_label = _slider_value_label(str(preset["fov"]))
        fov_slider = QSlider(Qt.Horizontal)
        fov_slider.setRange(54, 68)
        fov_slider.setSingleStep(1)
        fov_slider.setValue(preset["fov"])
        fov_slider.valueChanged.connect(lambda v, label=fov_value_label: label.setText(str(v)))
        fov_slider.valueChanged.connect(lambda: self._mark_unsaved())

        x_value_label = _slider_value_label(f"{preset['x']:.1f}")
        x_slider = QSlider(Qt.Horizontal)
        x_slider.setRange(-20, 25)
        x_slider.setSingleStep(5)
        x_slider.setValue(int(preset["x"] * 10))
        x_slider.valueChanged.connect(lambda v, label=x_value_label: label.setText(f"{v/10:.1f}"))
        x_slider.valueChanged.connect(lambda: self._mark_unsaved())

        y_value_label = _slider_value_label(f"{preset['y']:.1f}")
        y_slider = QSlider(Qt.Horizontal)
        y_slider.setRange(-20, 20)
        y_slider.setSingleStep(5)
        y_slider.setValue(int(preset["y"] * 10))
        y_slider.valueChanged.connect(lambda v, label=y_value_label: label.setText(f"{v/10:.1f}"))
        y_slider.valueChanged.connect(lambda: self._mark_unsaved())

        z_value_label = _slider_value_label(f"{preset['z']:.1f}")
        z_slider = QSlider(Qt.Horizontal)
        z_slider.setRange(-20, 20)
        z_slider.setSingleStep(5)
        z_slider.setValue(int(preset["z"] * 10))
        z_slider.valueChanged.connect(lambda v, label=z_value_label: label.setText(f"{v/10:.1f}"))
        z_slider.valueChanged.connect(lambda: self._mark_unsaved())

        cells = ((fov_slider, fov_value_label), (x_slider, x_value_label),
                 (y_slider, y_value_label), (z_slider, z_value_label))
        for column, (slider, value_label) in enumerate(cells, PRESET_FIRST_SLIDER_COLUMN):
            cell = QHBoxLayout()
            cell.setSpacing(8)
            cell.addWidget(slider, 1)
            cell.addWidget(value_label)
            grid.addLayout(cell, row, column)

        # 保存引用
        self.preset_vars.append({
            "name": name_input,
            "key": key_input,
            "fov": fov_slider,
            "x": x_slider,
            "y": y_slider,
            "z": z_slider,
            "fov_label": fov_value_label,
            "x_label": x_value_label,
            "y_label": y_value_label,
            "z_label": z_value_label,
        })

    # ========== CFG 同步状态 ==========

    def _cfg_is_dirty(self):
        """这一页的改动写进 CFG 了没有 —— **唯一真源**。

        RN-452：整页状态原来靠对一句屏幕文案做子串匹配算，润色一次文字，脏和净就反了。
        ⇒ 真源是这个布尔，文案从它渲染，方向是单向的。
        """
        return bool(getattr(self, "_cfg_dirty", False))

    def _mark_unsaved(self):
        """标记设置已修改但未保存到 CFG"""
        if getattr(self, '_loading', True):
            return
        self._cfg_dirty = True
        self._sync_status_strip()

    def _mark_saved(self):
        """标记设置已同步到 CFG。"""
        self._cfg_dirty = False
        self._sync_status_strip()

    def _on_crosshair_reset_changed(self, state):
        """准心快速回正开关变更"""
        config.crosshair_reset_enabled = self.crosshair_reset_checkbox.isChecked()
        config.save_config()
        self._mark_unsaved()
        self.logger.info(f"准心快速回正: {'启用' if config.crosshair_reset_enabled else '禁用'}")
    
    def _on_crosshair_attack_key_changed(self):
        """开火键变更。

        这里存**用户原样输入**，合法性由 core.crosshair_reset 在编译时判定并
        在非法时退回 mouse1 —— 判定规则只该有一份，页面不重复实现一遍。
        输入框回填的是编译器实际会用的那个键，所以用户能立刻看出自己填废了。
        """
        from core.crosshair_reset import resolve_attack_key

        config.crosshair_reset_attack_key = self.crosshair_attack_key_edit.text().strip()
        effective = resolve_attack_key(config)
        if effective != config.crosshair_reset_attack_key:
            config.crosshair_reset_attack_key = effective
            self.crosshair_attack_key_edit.setText(effective)
        config.save_config()
        self._mark_unsaved()
        self.logger.info(f"准心回正开火键: {effective}")

    def _on_crosshair_secondary_changed(self, _state):
        config.crosshair_reset_secondary_enabled = self.crosshair_secondary_checkbox.isChecked()
        config.save_config()
        self._mark_unsaved()
        self.logger.info(
            f"准心回正副开火键: {'启用' if config.crosshair_reset_secondary_enabled else '禁用'}"
        )

    def _on_auto_switch_toggled(self, checked):
        """自动切换开关变更"""
        if getattr(self, "_loading", False):
            return

        # 保存到配置
        config.viewmodel_auto_switch_enabled = checked
        config.save_config()
        self.logger.info(f"自动循环切换: {'启用' if checked else '禁用'}")
        
        if checked:
            self._start_auto_switch()
        else:
            self._stop_auto_switch()
        self._mark_unsaved()
    
    def _start_auto_switch(self):
        """启动自动切换"""
        if self.auto_switch_thread and self.auto_switch_thread.isRunning():
            return
        try:
            interval = float(self.auto_switch_interval_input.text())
            switch_key = self.auto_switch_key_input.text().strip()
            cycle_key = self.cycle_key_input.text().strip()
            if not switch_key or not cycle_key:
                raise ValueError("按键不能为空")
            
            self.auto_switch_thread = AutoSwitchWorker(switch_key, interval, cycle_key)
            self.auto_switch_thread.status_changed.connect(self._on_auto_switch_status_changed)
            self.auto_switch_thread.start()
            self.logger.info("自动切换已启动")
        except ValueError:
            QMessageBox.warning(self, "错误", "切换间隔必须是数字，且按键不能为空")
            self.auto_switch_checkbox.blockSignals(True)
            self.auto_switch_checkbox.setChecked(False)
            self.auto_switch_checkbox.blockSignals(False)
    
    def _stop_auto_switch(self):
        """停止自动切换"""
        if self.auto_switch_thread:
            self.auto_switch_thread.stop()
            # 加超时兜底：可中断等待让线程通常很快退出；万一卡住也不无限阻塞 UI（最多 1.5 秒）
            if not self.auto_switch_thread.wait(1500):
                self.logger.warning("自动切换线程未在超时内退出")
            self.auto_switch_thread = None
            self.logger.info("自动切换已停止")
    
    def _on_auto_switch_status_changed(self, is_active):
        """自动切换状态变更"""
        status = "激活" if is_active else "暂停"
        self.logger.info(f"自动切换状态: {status}")
    
        self._sync_status_strip()

    def _save_viewmodel_cfg(self):
        """保存视角设置到CFG文件"""
        try:
            config.crosshair_reset_enabled = self.crosshair_reset_checkbox.isChecked()

            cycle_key = self.cycle_key_input.text().strip() or "CAPSLOCK"
            config.viewmodel_auto_switch_enabled = self.auto_switch_checkbox.isChecked()
            config.viewmodel_auto_switch_key = self.auto_switch_key_input.text()
            try:
                config.viewmodel_auto_switch_interval = float(self.auto_switch_interval_input.text())
            except ValueError:
                config.viewmodel_auto_switch_interval = 3.0
            config.viewmodel_cycle_key = cycle_key

            for key_val, func_name in [(cycle_key, "持枪动作切换"), (self.auto_switch_key_input.text(), "持枪自动切换")]:
                conflict = config.check_hotkey_conflict(key_val, func_name)
                if conflict:
                    from ui_toast import toast_warning
                    toast_warning(f"快捷键 {key_val} 已被「{conflict}」使用", 4000)

            config.viewmodel_presets = []
            for preset_var in self.preset_vars:
                config.viewmodel_presets.append({
                    "name": preset_var["name"].text(),
                    "key": preset_var["key"].text(),
                    "fov": preset_var["fov"].value(),
                    "x": preset_var["x"].value() / 10.0,
                    "y": preset_var["y"].value() / 10.0,
                    "z": preset_var["z"].value() / 10.0
                })
            config.save_config()

            if not str(getattr(config, "csgo_dir", "") or "").strip():
                # 批 129：没设 CS2 目录时 `write_cs2customizer_cfg` 一个文件都不写，而下面照样弹
                # 「已保存到 game/csgo/cfg/cs2customizer.cfg」（拿空串拼出来的相对路径）。
                QMessageBox.warning(
                    self, "还没设置 CS2 目录",
                    "这些设置已经记在软件里了，但还没写进游戏：\n"
                    "CS2 Customizer 还不知道 CS2 装在哪。\n\n"
                    "去「高级设置」选一下 CS2 目录，再回来点一次保存。")
                self._mark_saved()
                return

            from core.cfg_compiler import write_cs2customizer_cfg
            warnings = write_cs2customizer_cfg(config)
            if warnings:
                from ui_toast import toast_warning
                toast_warning("\n".join(warnings), 5000)

            try:
                setup_autoexec(config.csgo_dir)
            except Exception as e:
                self.logger.warning(f"Setup autoexec failed: {e}")

            crosshair_status = "已启用" if self.crosshair_reset_checkbox.isChecked() else "未启用"
            cfg_path = os.path.join(config.csgo_dir, "game", "csgo", "cfg", "cs2customizer.cfg")
            QMessageBox.information(
                self,
                "保存成功",
                f"局内视角设置已保存到:\n{cfg_path}\n\n"
                f"准心快速回正: {crosshair_status}\n"
                f"视角预设数量: {len(self.preset_vars)}\n\n"
                "游戏内输入 exec cs2customizer.cfg 加载配置"
            )
            self.logger.info("局内视角设置已保存")
            self._mark_saved()

        except Exception as e:
            self.logger.error(f"保存CFG失败: {e}")
            QMessageBox.critical(self, "错误", "保存 CFG 失败：可能是 CS2 配置目录无写入权限或文件被占用，请确认目录设置后重试。")
    
    def load_settings(self):
        """加载设置"""
        try:
            if hasattr(config, 'crosshair_reset_enabled'):
                self.crosshair_reset_checkbox.setChecked(config.crosshair_reset_enabled)

            from core.crosshair_reset import resolve_attack_key

            # 回填的是编译器实际会用的键，不是配置里存的原始字符串——
            # 存量配置里可能有非法值，让用户看见真实生效的那个
            self.crosshair_attack_key_edit.setText(resolve_attack_key(config))
            self.crosshair_secondary_checkbox.setChecked(
                bool(getattr(config, "crosshair_reset_secondary_enabled", False))
            )


            if hasattr(config, 'viewmodel_auto_switch_enabled'):
                self.auto_switch_checkbox.setChecked(config.viewmodel_auto_switch_enabled)
            
            if hasattr(config, 'viewmodel_auto_switch_key'):
                self.auto_switch_key_input.setText(config.viewmodel_auto_switch_key)
            
            if hasattr(config, 'viewmodel_auto_switch_interval'):
                self.auto_switch_interval_input.setText(str(config.viewmodel_auto_switch_interval))
            
            if hasattr(config, 'viewmodel_cycle_key'):
                self.cycle_key_input.setText(config.viewmodel_cycle_key)
            
            if hasattr(config, 'viewmodel_presets') and config.viewmodel_presets:
                for i, preset in enumerate(config.viewmodel_presets):
                    if i < len(self.preset_vars):
                        self.preset_vars[i]["name"].setText(preset.get("name", f"preset{i+1}"))
                        self.preset_vars[i]["key"].setText(preset.get("key", f"F{i+5}"))
                        self.preset_vars[i]["fov"].setValue(preset.get("fov", 68))
                        self.preset_vars[i]["x"].setValue(int(preset.get("x", 2.0) * 10))
                        self.preset_vars[i]["y"].setValue(int(preset.get("y", 2.0) * 10))
                        self.preset_vars[i]["z"].setValue(int(preset.get("z", -1.0) * 10))

            self._mark_saved()
            
            self.logger.info("视角设置已加载")
        except Exception as e:
            self.logger.error(f"加载设置失败: {e}")

    def sync_after_config_reload(self):
        """配置被整体恢复后补同步：数值标签和自动切换线程（重载时信号被挡住）。"""
        for preset in self.preset_vars:
            preset["fov_label"].setText(str(preset["fov"].value()))
            for axis in ("x", "y", "z"):
                preset[f"{axis}_label"].setText(f"{preset[axis].value() / 10:.1f}")
        if self.auto_switch_checkbox.isChecked():
            self._start_auto_switch()
        else:
            self._stop_auto_switch()

    def cleanup(self):
        """清理资源"""
        self._stop_auto_switch()
