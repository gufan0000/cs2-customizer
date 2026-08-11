#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
局内视角设置页面（持枪视角 + 准心回正）
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QLineEdit, QSlider, QCheckBox, QGridLayout, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal

from config import config, DEFAULT_VIEWMODEL_PRESETS
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from theme_manager import get_theme_manager
from cfg_utils import setup_autoexec
from page_theme_helper import style_as_primary_button
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
import keyboard
import time
import os


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

        # 注册主题变更回调
        get_theme_manager().register_theme_changed_callback(self._apply_theme_styles)
    
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
            description="把准心回正、循环切换和 CFG 同步收在首屏，预设区域继续保留完整编辑空间，方便边调边存。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        main_layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["viewmodel"])

        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(14, 12, 14, 12)
        status_card_layout.setSpacing(8)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_title = QLabel("当前状态")
        status_title.setObjectName("statusLabel")
        status_row.addWidget(status_title)
        self.status_badge_label = create_badge_label()
        status_row.addWidget(self.status_badge_label, 1)
        status_row.addStretch()
        status_card_layout.addLayout(status_row)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        status_card_layout.addWidget(self.summary_label)
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

        tools_row = QHBoxLayout()
        tools_row.setSpacing(10)

        left_column = QWidget()
        left_column.setSizePolicy(left_column.sizePolicy().horizontalPolicy(), left_column.sizePolicy().verticalPolicy())
        left_column_layout = QVBoxLayout(left_column)
        left_column_layout.setContentsMargins(0, 0, 0, 0)
        left_column_layout.setSpacing(10)

        crosshair_card, crosshair_layout = SettingsCard.make(
            "准心快速回正",
            "保留单独的快速回正开关，方便和持枪视角切换分开调试。",
        )
        self.crosshair_reset_checkbox = QCheckBox("启用准心快速回正")
        self.crosshair_reset_checkbox.setToolTip("开火时准心跟随后坐力，松开后瞬间回正（无曲线动画）")
        self.crosshair_reset_checkbox.stateChanged.connect(self._on_crosshair_reset_changed)
        crosshair_layout.addWidget(self.crosshair_reset_checkbox)

        self.crosshair_info = QLabel("原理：按下开火键时 cl_crosshair_recoil 1，松开时设为 0，实现准心瞬间回正")
        self.crosshair_info.setObjectName("hintLabel")
        self.crosshair_info.setWordWrap(True)
        crosshair_layout.addWidget(self.crosshair_info)
        self.crosshair_summary_label = QLabel("")
        self.crosshair_summary_label.setObjectName("hintLabel")
        self.crosshair_summary_label.setWordWrap(True)
        crosshair_layout.addWidget(self.crosshair_summary_label)
        left_column_layout.addWidget(crosshair_card)

        viewmodel_card, viewmodel_layout = SettingsCard.make(
            "持枪切换",
            "循环按键和自动切换参数集中在一起，改热键时不用来回找。",
        )
        self.viewmodel_summary_label = QLabel("")
        self.viewmodel_summary_label.setObjectName("hintLabel")
        self.viewmodel_summary_label.setWordWrap(True)
        viewmodel_layout.addWidget(self.viewmodel_summary_label)
        control_grid = QGridLayout()
        control_grid.setContentsMargins(0, 0, 0, 0)
        control_grid.setHorizontalSpacing(10)
        control_grid.setVerticalSpacing(8)

        control_grid.addWidget(QLabel("循环按键:"), 0, 0)
        self.cycle_key_input = QLineEdit()
        self.cycle_key_input.setMaximumWidth(100)
        self.cycle_key_input.setMinimumHeight(34)
        self.cycle_key_input.setText("CAPSLOCK")
        self.cycle_key_input.textChanged.connect(lambda: self._mark_unsaved())
        control_grid.addWidget(self.cycle_key_input, 0, 1)

        self.auto_switch_checkbox = QCheckBox("启用自动循环切换")
        self.auto_switch_checkbox.toggled.connect(self._on_auto_switch_toggled)
        control_grid.addWidget(self.auto_switch_checkbox, 0, 2, 1, 3)

        control_grid.addWidget(QLabel("激活按键:"), 1, 0)
        self.auto_switch_key_input = QLineEdit()
        self.auto_switch_key_input.setMaximumWidth(80)
        self.auto_switch_key_input.setMinimumHeight(34)
        self.auto_switch_key_input.setText("V")
        self.auto_switch_key_input.textChanged.connect(lambda: self._mark_unsaved())
        control_grid.addWidget(self.auto_switch_key_input, 1, 1)
        control_grid.addWidget(QLabel("切换间隔(秒):"), 1, 2)
        self.auto_switch_interval_input = QLineEdit()
        self.auto_switch_interval_input.setMaximumWidth(60)
        self.auto_switch_interval_input.setMinimumHeight(34)
        self.auto_switch_interval_input.setText("3.0")
        self.auto_switch_interval_input.textChanged.connect(lambda: self._mark_unsaved())
        control_grid.addWidget(self.auto_switch_interval_input, 1, 3)
        control_grid.setColumnStretch(4, 1)
        viewmodel_layout.addLayout(control_grid)
        viewmodel_card.setSizePolicy(viewmodel_card.sizePolicy().horizontalPolicy(), viewmodel_card.sizePolicy().verticalPolicy())

        cfg_card, cfg_layout = SettingsCard.make(
            "CFG 同步",
            "热键或预设改动先在这里确认状态，再手动写入 CFG，避免误覆盖当前配置。",
        )
        self.cfg_summary_label = QLabel("")
        self.cfg_summary_label.setObjectName("hintLabel")
        self.cfg_summary_label.setWordWrap(True)
        cfg_layout.addWidget(self.cfg_summary_label)

        save_btn = QPushButton("保存设置到CFG")
        # UP-070: 此前这颗按钮的"主操作"外观是 ui_style_applier 按文案里有"保存"
        # 二字猜出来的——全站唯一还在吃那条猜测的按钮。猜测逻辑已删，这里显式声明。
        # UP-080: 用 style_as_primary_button 而不是裸 setObjectName ——
        # 后者会让 `_apply_widget_style` 提前 return，把手型光标一起丢掉
        # （我最初正是这么写的，"观感变化为零"的说法因此是错的）。
        style_as_primary_button(save_btn)
        save_btn.setMinimumHeight(36)
        save_btn.clicked.connect(self._save_viewmodel_cfg)
        cfg_layout.addWidget(save_btn)

        self._cfg_status_label = QLabel("")
        self._cfg_status_label.setObjectName("cfgStatusLabel")
        self._cfg_status_label.setWordWrap(True)
        cfg_layout.addWidget(self._cfg_status_label)
        left_column_layout.addWidget(cfg_card)
        left_column_layout.addStretch(1)

        tools_row.addWidget(left_column, 4, Qt.AlignTop)
        tools_row.addWidget(viewmodel_card, 6, Qt.AlignTop)
        scroll_layout.addLayout(tools_row)

        presets_frame, presets_layout = SettingsCard.make(
            "视角预设",
            "5 组常用持枪参数继续保留完整编辑能力，滚动区域更紧凑一些。",
        )
        self.presets_summary_label = QLabel("")
        self.presets_summary_label.setObjectName("hintLabel")
        self.presets_summary_label.setWordWrap(True)
        presets_layout.addWidget(self.presets_summary_label)
        presets_scroll = QScrollArea()
        presets_scroll.setWidgetResizable(True)
        presets_scroll.setFrameShape(QFrame.NoFrame)
        presets_scroll.setMaximumHeight(320)
        presets_scroll_content = QWidget()
        presets_scroll_layout = QVBoxLayout(presets_scroll_content)
        presets_scroll_layout.setContentsMargins(0, 0, 0, 0)
        presets_scroll_layout.setSpacing(8)
        for i, preset in enumerate(self.presets):
            preset_card = self._create_preset_card(preset, i)
            presets_scroll_layout.addWidget(preset_card)
        presets_scroll_layout.addStretch()
        presets_scroll.setWidget(presets_scroll_content)
        presets_layout.addWidget(presets_scroll)
        scroll_layout.addWidget(presets_frame)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(132)
        self.action_bar.primary_btn.setMinimumWidth(140)
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

    def _toggle_auto_switch_from_bar(self):
        if hasattr(self, "auto_switch_checkbox"):
            self.auto_switch_checkbox.setChecked(not self.auto_switch_checkbox.isChecked())

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        cfg_text = self._cfg_status_label.text().strip() if hasattr(self, "_cfg_status_label") else ""
        is_dirty = ("未保存" in cfg_text) or ("已修改" in cfg_text)
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
        auto_enabled = self.auto_switch_checkbox.isChecked() if hasattr(self, "auto_switch_checkbox") else False
        preset_count = len(getattr(self, "preset_vars", []))

        self.action_bar.configure_secondary(
            "关闭自动切换" if auto_enabled else "启用自动切换",
            self._toggle_auto_switch_from_bar,
            visible=True,
        )
        self.action_bar.configure_primary("保存到CFG", self._save_viewmodel_cfg, visible=True)
        action_message = (
            f"当前状态：CFG{'待同步' if is_dirty else '已同步'} · 循环键 {cycle_key}"
            f" · 自动切换{'开启' if auto_enabled else '关闭'}"
            f"{f'（{auto_key}）' if auto_key != '-' else ''} · 共 {preset_count} 组预设。"
        )
        self.action_bar.set_message(action_message)

    def _sync_panel_summaries(self):
        cfg_text = self._cfg_status_label.text().strip() if hasattr(self, "_cfg_status_label") else ""
        is_dirty = ("未保存" in cfg_text) or ("已修改" in cfg_text)
        cycle_key = (
            self.cycle_key_input.text().strip()
            if hasattr(self, "cycle_key_input") and self.cycle_key_input.text().strip()
            else "CAPSLOCK"
        )
        auto_key = (
            self.auto_switch_key_input.text().strip()
            if hasattr(self, "auto_switch_key_input") and self.auto_switch_key_input.text().strip()
            else "-"
        )
        auto_interval = (
            self.auto_switch_interval_input.text().strip()
            if hasattr(self, "auto_switch_interval_input") and self.auto_switch_interval_input.text().strip()
            else "3.0"
        )
        auto_enabled = self.auto_switch_checkbox.isChecked() if hasattr(self, "auto_switch_checkbox") else False
        crosshair_enabled = self.crosshair_reset_checkbox.isChecked() if hasattr(self, "crosshair_reset_checkbox") else False
        preset_count = len(getattr(self, "preset_vars", []))

        preset_preview = []
        for preset in getattr(self, "preset_vars", [])[:3]:
            name = preset["name"].text().strip() or "未命名"
            key = preset["key"].text().strip() or "-"
            preset_preview.append(f"{name}({key})")
        preset_preview_text = " / ".join(preset_preview) if preset_preview else "等待配置"

        if hasattr(self, "crosshair_summary_label"):
            crosshair_text = f"当前准星回正：{'已启用' if crosshair_enabled else '未启用'}"
            self.crosshair_summary_label.setText(crosshair_text)
            self.crosshair_summary_label.setToolTip(crosshair_text)

        if hasattr(self, "viewmodel_summary_label"):
            viewmodel_text = (
                f"当前循环键：{cycle_key} · 自动切换{'已启用' if auto_enabled else '未启用'}"
                f"{f'（{auto_key} / {auto_interval} 秒）' if auto_enabled else ''}"
            )
            self.viewmodel_summary_label.setText(viewmodel_text)
            self.viewmodel_summary_label.setToolTip(viewmodel_text)

        if hasattr(self, "cfg_summary_label"):
            cfg_summary = (
                f"当前状态：CFG{'待同步' if is_dirty else '已同步'} · "
                f"写入后会同时刷新准星回正与 {preset_count} 组视角预设。"
            )
            self.cfg_summary_label.setText(cfg_summary)
            self.cfg_summary_label.setToolTip(cfg_summary)

        if hasattr(self, "presets_summary_label"):
            presets_text = f"当前共 {preset_count} 组预设 · 常用快捷键 {preset_preview_text}"
            self.presets_summary_label.setText(presets_text)
            self.presets_summary_label.setToolTip(presets_text)

    def _sync_status_strip(self):
        cfg_text = self._cfg_status_label.text().strip() if hasattr(self, "_cfg_status_label") else ""
        is_dirty = ("未保存" in cfg_text) or ("已修改" in cfg_text)
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
        self.summary_label.setText(detail_text)
        self.summary_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)
        self._sync_panel_summaries()
        self._sync_action_bar()
    
    
    def _apply_theme_styles(self):
        """应用主题样式（objectName 标签由 QSS 自动处理）"""
        pass

    def _create_preset_card(self, preset, index):
        """创建预设卡片"""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # 头部：名称和快捷键
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        preset_label = QLabel(f"预设 {index + 1}")
        preset_label.setObjectName("hintLabel")
        header_layout.addWidget(preset_label)
        
        name_label = QLabel("名称:")
        header_layout.addWidget(name_label)
        
        name_input = QLineEdit()
        name_input.setText(preset["name"])
        name_input.setMaximumWidth(110)
        name_input.textChanged.connect(lambda: self._mark_unsaved())
        header_layout.addWidget(name_input)

        header_layout.addWidget(QLabel("快捷键:"))

        key_input = QLineEdit()
        key_input.setText(preset["key"])
        key_input.setMaximumWidth(90)
        key_input.textChanged.connect(lambda: self._mark_unsaved())
        header_layout.addWidget(key_input)
        
        header_layout.addStretch()
        layout.addLayout(header_layout)

        slider_grid = QGridLayout()
        slider_grid.setContentsMargins(0, 0, 0, 0)
        slider_grid.setHorizontalSpacing(12)
        slider_grid.setVerticalSpacing(8)
        slider_grid.setColumnStretch(0, 1)
        slider_grid.setColumnStretch(1, 1)

        fov_value_label = QLabel(str(preset["fov"]))
        fov_value_label.setMinimumWidth(36)
        fov_slider = QSlider(Qt.Horizontal)
        fov_slider.setRange(54, 68)
        fov_slider.setSingleStep(1)
        fov_slider.setValue(preset["fov"])
        fov_slider.valueChanged.connect(lambda v, label=fov_value_label: label.setText(str(v)))
        fov_slider.valueChanged.connect(lambda: self._mark_unsaved())

        x_value_label = QLabel(f"{preset['x']:.1f}")
        x_value_label.setMinimumWidth(36)
        x_slider = QSlider(Qt.Horizontal)
        x_slider.setRange(-20, 25)
        x_slider.setSingleStep(5)
        x_slider.setValue(int(preset["x"] * 10))
        x_slider.valueChanged.connect(lambda v, label=x_value_label: label.setText(f"{v/10:.1f}"))
        x_slider.valueChanged.connect(lambda: self._mark_unsaved())

        y_value_label = QLabel(f"{preset['y']:.1f}")
        y_value_label.setMinimumWidth(36)
        y_slider = QSlider(Qt.Horizontal)
        y_slider.setRange(-20, 20)
        y_slider.setSingleStep(5)
        y_slider.setValue(int(preset["y"] * 10))
        y_slider.valueChanged.connect(lambda v, label=y_value_label: label.setText(f"{v/10:.1f}"))
        y_slider.valueChanged.connect(lambda: self._mark_unsaved())

        z_value_label = QLabel(f"{preset['z']:.1f}")
        z_value_label.setMinimumWidth(36)
        z_slider = QSlider(Qt.Horizontal)
        z_slider.setRange(-20, 20)
        z_slider.setSingleStep(5)
        z_slider.setValue(int(preset["z"] * 10))
        z_slider.valueChanged.connect(lambda v, label=z_value_label: label.setText(f"{v/10:.1f}"))
        z_slider.valueChanged.connect(lambda: self._mark_unsaved())

        slider_specs = [
            ("FOV", fov_value_label, fov_slider, 0, 0),
            ("X", x_value_label, x_slider, 0, 1),
            ("Y", y_value_label, y_slider, 1, 0),
            ("Z", z_value_label, z_slider, 1, 1),
        ]
        for title, value_label, slider, row, column in slider_specs:
            group = QFrame()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(4)
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(8)
            title_row.addWidget(QLabel(f"{title}:"))
            title_row.addStretch()
            title_row.addWidget(value_label)
            group_layout.addLayout(title_row)
            group_layout.addWidget(slider)
            slider_grid.addWidget(group, row, column)

        layout.addLayout(slider_grid)
        
        # 保存引用
        self.preset_vars.append({
            "name": name_input,
            "key": key_input,
            "fov": fov_slider,
            "x": x_slider,
            "y": y_slider,
            "z": z_slider
        })
        
        return card

    # ========== CFG 同步状态 ==========

    def _mark_unsaved(self):
        """标记设置已修改但未保存到 CFG"""
        if getattr(self, '_loading', True):
            return
        if hasattr(self, '_cfg_status_label'):
            self._cfg_status_label.setText("⚠ 设置已修改，未保存到CFG")
            self._cfg_status_label.setStyleSheet("color: #e6a23c; font-size: 12px;")
        self._sync_status_strip()

    def _mark_saved(self):
        """标记设置已同步到 CFG"""
        if hasattr(self, '_cfg_status_label'):
            self._cfg_status_label.setText("✓ 已同步到CFG")
            self._cfg_status_label.setStyleSheet("color: #67c23a; font-size: 12px;")
        self._sync_status_strip()

    def _on_crosshair_reset_changed(self, state):
        """准心快速回正开关变更"""
        config.crosshair_reset_enabled = self.crosshair_reset_checkbox.isChecked()
        config.save_config()
        self._mark_unsaved()
        self.logger.info(f"准心快速回正: {'启用' if config.crosshair_reset_enabled else '禁用'}")
    
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
    

    def cleanup(self):
        """清理资源"""
        from theme_manager import get_theme_manager
        get_theme_manager().unregister_theme_changed_callback(self._apply_theme_styles)
        self._stop_auto_switch()
