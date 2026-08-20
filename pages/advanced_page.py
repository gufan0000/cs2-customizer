#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
高级设置页面 - PySide6 Widgets版本
功能：CS:GO目录设置、调试模式、配置管理
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QFileDialog, QMessageBox,
    QComboBox, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
import os
import shutil

from config import config
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from theme_manager import get_theme_manager
from page_theme_helper import style_as_danger_button, style_as_primary_button, style_as_secondary_button
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from cfg_utils import find_cfg_path
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard


class AdvancedPage(QWidget):
    """高级设置页面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("AdvancedPage")
        self.theme_manager = get_theme_manager()
        self.debug_mode = config.debug_mode if hasattr(config, 'debug_mode') else False
        self._auto_detected = False  # 标记是否已自动检测过

        self._create_ui()
        self._load_settings()
        self._try_auto_detect_cs2()

        self.logger.info("高级设置页面初始化完成")

    def _create_ui(self):
        """创建UI"""
        # 主布局：外层承载滚动区（修复窗口变矮时卡片被压扁 / 控件被裁切）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page_widget = QWidget()
        layout = QVBoxLayout(page_widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 页面标题
        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "高级设置",
            description="CS2 目录、界面主题、GSI 服务状态和维护操作。首次使用必须先在这儿设好 CS2 安装目录，其余一般用不着动。",
            title_font_size=None,
            spacing=10,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["advanced"])

        status_card = QFrame()
        status_card.setObjectName("card")
        status_card.setFrameShape(QFrame.StyledPanel)
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(14, 12, 14, 12)
        status_layout.setSpacing(8)
        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_title = QLabel("当前状态")
        status_title.setObjectName("statusLabel")
        status_row.addWidget(status_title)
        self.status_badge_label = create_badge_label()
        status_row.addWidget(self.status_badge_label, 1)
        status_row.addStretch()
        status_layout.addLayout(status_row)
        self.status_card = status_card

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        status_layout.addWidget(self.summary_label)
        layout.addWidget(status_card)

        # 2.2.0 信息架构:页内锚点导航——10 张卡一长列,翻到底才找到热键/权限。
        # 自动扫描卡片标题生成跳转 chips,新增卡片零维护。
        #
        # UP-017: 原本用 QHBoxLayout。QHBoxLayout 的最小宽度是**所有子项之和**,
        # 10 个 chip 各带 QSS 的 min-width:80 → 把整页最小宽度顶到 1284px。
        # 而本页滚动区又 setHorizontalScrollBarPolicy(AlwaysOff)(见上面 page_scroll),
        # 于是 1200/1280 宽的窗口下右侧 23 个交互控件**永久够不到**,
        # 连一条横向滚动条都没有,用户根本不知道内容被截断了。
        # 换成 FlowLayout:最小宽度只等于最宽的那个 chip,窄窗口自动换行。
        from widgets.flow_layout import make_flow_container

        anchor_wrap, self._anchor_bar = make_flow_container(h_spacing=6, v_spacing=6)
        layout.addWidget(anchor_wrap)
        from PySide6.QtCore import QTimer as _QT

        _QT.singleShot(0, self._build_anchor_chips)

        directory_card, directory_layout = SettingsCard.make(
            "CS2 配置目录",
            "建议直接选择 Counter-Strike 根目录，软件会自动校验 `game/csgo/cfg` 并据此写入后续配置。",
        )
        self._create_csgo_dir_section(directory_layout)
        layout.addWidget(directory_card)

        # v5 Phase 7: "内部测试"和"界面主题"原本横排但密度悬殊,改为垂直堆叠各占全宽.
        # RN-133：调试卡片收进专家模式。本仓库这里没有密码框（见下面调试小节的说明），
        # 但「排错入口占据主区域」这件事一样成立。
        # ⚠ 卡片照常建、只是不显示 —— 不建的话 `_update_debug_status` /
        # `_load_settings` 全都会撞上 AttributeError。
        self._create_debug_section(layout)
        self._debug_panel.setVisible(bool(getattr(config, "ui_expert_mode", False)))
        self._create_theme_section(layout)
        self._create_system_integration_section(layout)
        self._create_osd_section(layout)
        self._create_usage_report_section(layout)
        self._create_permission_section(layout)
        self._create_hotkey_overview_section(layout)

        config_card, config_layout = SettingsCard.make(
            "配置文件管理",
            "大改动前建议先备份；重置会恢复默认值，并在确认后自动退出程序。",
        )
        self._create_config_section(config_layout)
        layout.addWidget(config_card)
        layout.addStretch(1)

        page_scroll.setWidget(page_widget)
        outer.addWidget(page_scroll, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(116)
        self.action_bar.primary_btn.setMinimumWidth(132)
        outer.addWidget(self.action_bar, 0)

    def _is_valid_csgo_dir(self, directory):
        if not directory:
            return False
        expected_path = os.path.join(directory, "game", "csgo", "cfg")
        return os.path.isdir(expected_path)

    def _current_theme_text(self):
        theme_map = {
            "dark": "深色主题",
            "light": "浅色主题",
            "green": "墨绿主题",
            "purple": "紫夜主题",
            "ocean": "深海主题",
            "warm": "暖橙主题",
            "rose": "玫瑰主题",
            "contrast": "高对比主题",
            "minimal": "极简主题",
        }
        theme_name = str(getattr(config, "ui_theme", "") or "").strip().lower()
        return theme_map.get(theme_name, "深色主题")

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        csgo_dir = str(getattr(config, "csgo_dir", "") or "").strip()
        dir_valid = self._is_valid_csgo_dir(csgo_dir)

        self.action_bar.configure_secondary("选择目录", self._browse_for_csgo_dir, visible=True)
        if dir_valid:
            # RN-132：目录配好之后**不设主按钮**。这一页的设置改完立即生效，
            # 没有「保存」这个动作，而原来高亮的是低频的「备份设置」——
            # 全页最抢眼的位置指向玩家最不需要按的东西。备份仍在卡片里。
            self.action_bar.configure_primary("", None, visible=False)
            action_message = (
                f"当前目录已配置 · 主题 {self._current_theme_text()} · 调试模式"
                f"{'已启用' if self.debug_mode else '未启用'}，建议大改前先备份设置。"
            )
        else:
            self.action_bar.configure_primary("重试自动检测", self._try_auto_detect_cs2, visible=True)
            action_message = (
                f"当前目录{'未设置' if not csgo_dir else '需重新检查'} · 主题 {self._current_theme_text()} · "
                "可先手动选择目录，或尝试再次自动检测。"
            )
        self.action_bar.set_message(action_message)

    def _sync_overview_status(self):
        csgo_dir = str(getattr(config, "csgo_dir", "") or "").strip()
        has_dir = bool(csgo_dir)
        dir_valid = self._is_valid_csgo_dir(csgo_dir)

        if dir_valid:
            dir_badge = ("positive", "目录 · 已配置")
        elif has_dir:
            dir_badge = ("warning", "目录 · 需检查")
        else:
            dir_badge = ("warning", "目录 · 未设置")

        if dir_valid and self._auto_detected:
            source_badge = ("info", "来源 · 自动检测")
        elif dir_valid:
            source_badge = ("info", "来源 · 手动设置")
        else:
            source_badge = ("warning", "来源 · 待设置")

        debug_badge = (
            ("positive", "调试 · 已启用")
            if self.debug_mode
            else ("info", "调试 · 未启用")
        )
        theme_badge = ("info", f"主题 · {self._current_theme_text()}")

        badges = [dir_badge, source_badge, debug_badge, theme_badge]

        if dir_valid:
            if self._auto_detected:
                summary = (
                    f"当前使用的 CS2 目录：{csgo_dir}。软件已自动识别该路径，如需切换到其他盘符，可直接手动重新选择。"
                )
            else:
                summary = f"当前使用的 CS2 目录：{csgo_dir}。目录校验通过，后续功能会按这个位置写入和读取配置。"
        elif has_dir:
            summary = f"当前目录：{csgo_dir}。该路径还没有通过校验，请重新选择包含 game/csgo/cfg 的安装目录。"
        else:
            summary = "尚未设置 CS2 目录。软件启动时会尝试自动识别，也可以在下方直接手动指定。"

        render_badges(self.status_badge_label, badges, detail_tooltip=summary)
        self.summary_label.setText(summary)
        self.summary_label.setToolTip(summary)
        self.status_card.setToolTip(summary)
        if hasattr(self, "csgo_dir_text"):
            self.csgo_dir_text.setToolTip(summary)
        if hasattr(self, "directory_meta_label"):
            source_text = "自动检测" if dir_valid and self._auto_detected else "手动设置" if dir_valid else "待设置"
            verify_text = "已通过" if dir_valid else "需检查" if has_dir else "未设置"
            self.directory_meta_label.setText(f"来源：{source_text}  |  校验：{verify_text}")
            self.directory_meta_label.setToolTip(summary)
        self._sync_action_bar()
    
    def _create_csgo_dir_section(self, parent_layout):
        """创建CS:GO目录设置区域"""
        section_layout = QVBoxLayout()
        section_layout.setSpacing(8)
        
        # 目录显示和浏览按钮
        dir_layout = QHBoxLayout()
        dir_layout.setSpacing(12)
        
        self.csgo_dir_text = QLineEdit()
        self.csgo_dir_text.setReadOnly(True)
        self.csgo_dir_text.setMinimumHeight(36)
        self.csgo_dir_text.setPlaceholderText("尚未设置目录")
        dir_layout.addWidget(self.csgo_dir_text)
        
        browse_button = QPushButton("选择目录")
        browse_button.setFixedSize(108, 36)
        browse_button.setFont(QFont("Arial", 12))
        style_as_secondary_button(browse_button)
        browse_button.clicked.connect(self._browse_for_csgo_dir)
        dir_layout.addWidget(browse_button)
        
        section_layout.addLayout(dir_layout)
        self.directory_meta_label = QLabel("")
        self.directory_meta_label.setObjectName("hintLabel")
        self.directory_meta_label.setWordWrap(True)
        section_layout.addWidget(self.directory_meta_label)
        parent_layout.addLayout(section_layout)
    
    def _create_debug_section(self, parent_layout):
        """创建调试模式区域"""
        panel, section_layout = SettingsCard.make(
            "内部调试",
            "仅在排查异常或联动问题时使用，平时保持关闭即可。",
        )
        self._debug_panel = panel      # RN-133：显示与否由专家模式决定

        self.debug_status_label = QLabel()
        self.debug_status_label.setObjectName("statusLabel")
        self.debug_status_label.setWordWrap(True)
        self._update_debug_status()
        section_layout.addWidget(self.debug_status_label)
        
        # 开源版：直接开关，不设密码。
        # 闭源版这里是一道口令验证（源码里存 SHA256），目的是让"开调试"这件事
        # 走一次客服。源码公开之后这道门失去意义——任何人都能读到校验逻辑并绕过，
        # 而留在仓库里的哈希反倒是维护者一个口令的离线爆破样本。
        debug_layout = QHBoxLayout()
        debug_layout.setSpacing(12)
        debug_layout.addStretch(1)

        debug_button = QPushButton()
        debug_button.setMinimumHeight(36)
        debug_button.setFont(QFont("Arial", 12))
        style_as_secondary_button(debug_button)
        debug_button.clicked.connect(self._toggle_debug_mode)
        self.debug_button = debug_button
        debug_layout.addWidget(debug_button)

        section_layout.addLayout(debug_layout)
        self._update_debug_status()
        
        parent_layout.addWidget(panel)
    
    def _create_theme_section(self, parent_layout):
        """创建主题切换区域"""
        panel, section_layout = SettingsCard.make(
            "界面主题",
            "切换后会立即应用到整个应用程序，适合在不同显示环境下快速挑一个更顺眼的主题。",
        )
        
        # 主题选择
        theme_layout = QHBoxLayout()
        theme_layout.setSpacing(12)
        
        theme_label = QLabel("选择主题:")
        theme_layout.addWidget(theme_label)
        
        self.theme_combo = QComboBox()
        self.theme_combo.setMinimumWidth(208)
        self.theme_combo.setFixedHeight(36)
        self.theme_combo.addItem("深色主题", "dark")
        self.theme_combo.addItem("浅色主题", "light")
        self.theme_combo.addItem("墨绿主题", "green")
        self.theme_combo.addItem("紫夜主题", "purple")
        self.theme_combo.addItem("深海主题", "ocean")
        self.theme_combo.addItem("暖橙主题", "warm")
        self.theme_combo.addItem("玫瑰主题", "rose")
        self.theme_combo.addItem("高对比主题", "contrast")
        self.theme_combo.addItem("极简主题", "minimal")
        
        # 设置当前主题
        current_theme = config.ui_theme if hasattr(config, 'ui_theme') else "dark"
        index = self.theme_combo.findData(current_theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_layout.addWidget(self.theme_combo, 1)
        
        section_layout.addLayout(theme_layout)

        # R1-1: 界面字号(与主题同卡——都是"外观"维度,避免高级页再多一张卡)
        font_layout = QHBoxLayout()
        font_layout.setSpacing(12)
        font_label = QLabel("界面字号:")
        font_layout.addWidget(font_label)

        self.font_scale_combo = QComboBox()
        self.font_scale_combo.setMinimumWidth(208)
        self.font_scale_combo.setFixedHeight(36)
        self.font_scale_combo.addItem("标准(默认)", 1.0)
        self.font_scale_combo.addItem("偏大(110%)", 1.1)
        self.font_scale_combo.addItem("大(125%)", 1.25)

        from ui_design_system import normalize_font_scale
        current_scale = normalize_font_scale(getattr(config, "ui_font_scale", 1.0))
        for i in range(self.font_scale_combo.count()):
            if abs(float(self.font_scale_combo.itemData(i)) - current_scale) < 0.01:
                self.font_scale_combo.setCurrentIndex(i)
                break

        self.font_scale_combo.currentIndexChanged.connect(self._on_font_scale_changed)
        font_layout.addWidget(self.font_scale_combo, 1)
        section_layout.addLayout(font_layout)

        # R1-6: 侧栏「常用」分组开关
        from PySide6.QtWidgets import QCheckBox

        self.nav_frequent_check = QCheckBox("侧栏显示「常用」分组(按使用频次自动排序,重启后生效)")
        self.nav_frequent_check.setChecked(bool(getattr(config, "nav_frequent_enabled", True)))
        self.nav_frequent_check.toggled.connect(self._on_nav_frequent_toggled)
        section_layout.addWidget(self.nav_frequent_check)

        parent_layout.addWidget(panel)

    def _on_nav_frequent_toggled(self, checked):
        config.nav_frequent_enabled = bool(checked)
        config.save_config()
        self.logger.info(f"常用分组: {'开启' if checked else '关闭'}(重启生效)")

    def _build_anchor_chips(self):
        """扫描页内 SettingsCard 标题,生成一行跳转 chips(点击滚动定位)。"""
        try:
            from PySide6.QtWidgets import QPushButton, QScrollArea

            from widgets.settings_card import SettingsCard

            scroll = self.findChild(QScrollArea)
            if scroll is None:
                return
            cards = [
                c for c in self.findChildren(SettingsCard)
                if getattr(c, "title_label", None) is not None
            ]
            seen = set()
            for card in cards:
                title = card.title_label.text().strip()
                # 章节名压缩到 4 字内,chips 一行放得下
                short = {
                    "CS2 配置目录": "目录",
                    "内部调试": "调试",
                    "界面主题": "外观",
                    "更新公告": "公告",
                    "系统集成": "系统",
                    "游戏内提示(OSD)": "OSD",
                    "匿名使用统计": "统计",
                    "运行权限": "权限",
                    "全局热键总览": "热键",
                    "配置文件管理": "配置",
                }.get(title, title[:4])
                if not title or short in seen:
                    continue
                seen.add(short)
                chip = QPushButton(short)
                # UP-017: 原来复用 secondaryButton,连带吃到 QSS 的 min-width:80。
                # 锚点 chip 只有 2~4 个汉字,80px 是纯浪费,而且会让换行提前发生。
                # 给它自己的 objectName + QSS(见 theme_manager 的 anchorChip)。
                chip.setObjectName("anchorChip")
                chip.setFixedHeight(26)
                chip.setCursor(Qt.PointingHandCursor)
                chip.setToolTip(f"跳到「{title}」")
                chip.clicked.connect(
                    lambda _=False, c=card: scroll.ensureWidgetVisible(c, 0, 16)
                )
                self._anchor_bar.addWidget(chip)
            # 注意:FlowLayout 没有 addStretch —— 它本来就是左对齐 + 自动换行,
            # 不需要尾部弹簧。原先那句 addStretch() 在这里会抛 AttributeError,
            # 被外层 except 吞掉后表现为"锚点条整个不出现"。
        except Exception:
            self.logger.exception("锚点导航生成失败(不影响页面)")

    def _create_osd_section(self, parent_layout):
        """R2-3: 游戏内 OSD 提示(切地图预设等瞬时反馈)。"""
        from PySide6.QtWidgets import QCheckBox

        panel, section_layout = SettingsCard.make(
            "游戏内提示(OSD)",
            "功能状态变化时(如按地图自动切预设)在屏幕角落弹 1.6 秒提示。"
            "CS2 需使用无边框窗口模式;全屏独占下不可见。",
        )

        self.osd_enabled_check = QCheckBox("启用游戏内提示")
        self.osd_enabled_check.setChecked(bool(getattr(config, "osd_enabled", True)))
        self.osd_enabled_check.toggled.connect(self._on_osd_toggled)
        section_layout.addWidget(self.osd_enabled_check)

        corner_layout = QHBoxLayout()
        corner_layout.setSpacing(12)
        corner_layout.addWidget(QLabel("显示位置:"))
        self.osd_corner_combo = QComboBox()
        self.osd_corner_combo.setMinimumWidth(208)
        self.osd_corner_combo.setFixedHeight(36)
        self.osd_corner_combo.addItem("右下角(默认)", "bottom_right")
        self.osd_corner_combo.addItem("左下角", "bottom_left")
        self.osd_corner_combo.addItem("右上角", "top_right")
        self.osd_corner_combo.addItem("左上角", "top_left")
        idx = self.osd_corner_combo.findData(getattr(config, "osd_corner", "bottom_right"))
        if idx >= 0:
            self.osd_corner_combo.setCurrentIndex(idx)
        self.osd_corner_combo.currentIndexChanged.connect(self._on_osd_corner_changed)
        corner_layout.addWidget(self.osd_corner_combo, 1)
        section_layout.addLayout(corner_layout)

        preview_btn = QPushButton("预览一下")
        style_as_secondary_button(preview_btn)
        preview_btn.setFixedHeight(32)
        preview_btn.setMaximumWidth(140)
        preview_btn.clicked.connect(self._on_osd_preview)
        section_layout.addWidget(preview_btn)

        parent_layout.addWidget(panel)

    def _on_osd_toggled(self, checked):
        config.osd_enabled = bool(checked)
        config.save_config()
        self.logger.info(f"OSD 提示: {'开' if checked else '关'}")

    def _on_osd_corner_changed(self, index):
        config.osd_corner = self.osd_corner_combo.itemData(index) or "bottom_right"
        config.save_config()

    def _on_osd_preview(self):
        try:
            from ui_osd import notify_osd

            notify_osd("CS2 Customizer:游戏内提示就长这样")
        except Exception:
            self.logger.exception("OSD 预览失败")

    def _create_usage_report_section(self, parent_layout):
        """R3-3: 匿名使用统计(默认关,内容可一键查看)。"""
        from PySide6.QtWidgets import QCheckBox

        panel, section_layout = SettingsCard.make(
            "匿名使用统计",
            "默认关闭。开启后每天最多上报一次:匿名安装ID、版本、各页面打开次数、"
            "功能开关状态。不含账号、昵称、系统标识或任何文件路径。",
        )

        row = QHBoxLayout()
        row.setSpacing(12)
        self.usage_report_check = QCheckBox("愿意上报匿名使用统计,帮助改进软件")
        self.usage_report_check.setChecked(bool(getattr(config, "usage_report_enabled", False)))
        self.usage_report_check.toggled.connect(self._on_usage_report_toggled)
        row.addWidget(self.usage_report_check, 1)

        view_btn = QPushButton("查看将上报的内容")
        style_as_secondary_button(view_btn)
        view_btn.setFixedHeight(32)
        view_btn.clicked.connect(self._show_usage_payload)
        row.addWidget(view_btn)
        section_layout.addLayout(row)
        parent_layout.addWidget(panel)

    def _on_usage_report_toggled(self, checked):
        config.usage_report_enabled = bool(checked)
        if checked:
            from core.usage_reporter import ensure_install_id

            ensure_install_id()
        config.save_config()
        self.logger.info(f"匿名使用统计: {'开' if checked else '关'}")

    def _show_usage_payload(self):
        import json as _json

        from core.usage_reporter import build_payload

        try:
            payload = build_payload()
            text = _json.dumps(payload, ensure_ascii=False, indent=2)
        except Exception as exc:
            text = f"(组装失败: {exc})"
        box = QMessageBox(self)
        box.setWindowTitle("将上报的全部内容")
        box.setText("开启后,每天最多发送一次以下数据(白名单之外什么都不会发):")
        box.setDetailedText(text)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

    def _on_font_scale_changed(self, index):
        """切换界面字号:缩放 token → 重应用当前主题(QSS 重生成)→ 持久化。"""
        from ui_design_system import apply_font_scale

        scale = apply_font_scale(self.font_scale_combo.itemData(index))
        # set_theme 会重新生成并广播 stylesheet,所有已建页面即时生效
        self.theme_manager.set_theme(getattr(config, "ui_theme", "dark") or "dark")
        config.ui_font_scale = scale
        config.save_config()
        self.logger.info(f"界面字号已切换: {int(scale * 100)}%")

    def _create_system_integration_section(self, parent_layout):
        """系统集成（对标主流）：关闭行为 / 开机自启 / 窗口记忆。"""
        from PySide6.QtWidgets import QCheckBox

        panel, section_layout = SettingsCard.make(
            "系统集成",
            "把 CS2 Customizer 当常驻工具用：关闭按钮可改为收进系统托盘，开机自启免去手动启动，窗口大小位置自动记忆。",
        )

        # 关闭行为
        close_row = QHBoxLayout()
        close_row.setSpacing(12)
        close_row.addWidget(QLabel("点击关闭按钮时:"))
        self.close_action_combo = QComboBox()
        self.close_action_combo.setMinimumWidth(208)
        self.close_action_combo.setFixedHeight(36)
        self.close_action_combo.addItem("每次询问（默认）", "ask")
        self.close_action_combo.addItem("最小化到系统托盘", "tray")
        self.close_action_combo.addItem("直接退出程序", "exit")
        _ca = str(getattr(config, "close_action", "ask") or "ask")
        _idx = self.close_action_combo.findData(_ca)
        self.close_action_combo.setCurrentIndex(_idx if _idx >= 0 else 0)
        self.close_action_combo.currentIndexChanged.connect(self._on_close_action_changed)
        close_row.addWidget(self.close_action_combo, 1)
        section_layout.addLayout(close_row)

        # 开机自启（真实来源 = 注册表，勾选状态启动时读取）
        self.autostart_checkbox = QCheckBox("开机自动启动 CS2 Customizer")
        try:
            from core.utils.autostart import is_enabled, is_supported

            self.autostart_checkbox.setEnabled(is_supported())
            self.autostart_checkbox.setChecked(is_enabled())
        except Exception:
            self.autostart_checkbox.setEnabled(False)
        self.autostart_checkbox.toggled.connect(self._on_autostart_toggled)
        section_layout.addWidget(self.autostart_checkbox)

        # 窗口记忆
        self.remember_window_checkbox = QCheckBox("记住窗口大小和位置")
        self.remember_window_checkbox.setChecked(bool(getattr(config, "use_saved_size", True)))
        self.remember_window_checkbox.toggled.connect(self._on_remember_window_toggled)
        section_layout.addWidget(self.remember_window_checkbox)

        parent_layout.addWidget(panel)

    def _on_close_action_changed(self, index):
        choice = str(self.close_action_combo.itemData(index) or "ask")
        config.close_action = choice
        config.save_config()
        self.logger.info(f"关闭行为已设置: {choice}")

    def _on_autostart_toggled(self, checked):
        try:
            from core.utils.autostart import is_enabled, set_enabled

            ok = set_enabled(bool(checked))
            if not ok:
                from ui_toast import toast_warning

                toast_warning("设置开机自启失败，请重试", 3200)
                # 回读真实状态，避免勾选框与注册表不一致
                self.autostart_checkbox.blockSignals(True)
                self.autostart_checkbox.setChecked(is_enabled())
                self.autostart_checkbox.blockSignals(False)
            else:
                self.logger.info(f"开机自启: {'开启' if checked else '关闭'}")
        except Exception:
            self.logger.exception("切换开机自启异常")

    def _on_remember_window_toggled(self, checked):
        config.use_saved_size = bool(checked)
        if not checked:
            config.window_geometry = []
        config.save_config()
        self.logger.info(f"窗口记忆: {'开启' if checked else '关闭'}")

    def _create_permission_section(self, parent_layout):
        """运行权限：2.1.3 起默认普通权限启动，这里提供状态与提权重启入口。"""
        from core.utils.elevation import is_admin

        admin_now = is_admin()
        panel, section_layout = SettingsCard.make(
            "运行权限",
            "默认以普通权限运行即可使用全部功能（含开镜放大）。仅当放大初始化失败、"
            "或游戏以管理员身份运行导致热键无响应时，才需要提权重启。",
        )

        row = QHBoxLayout()
        row.setSpacing(12)

        self.permission_status_label = QLabel(
            f"当前权限：{'管理员' if admin_now else '普通用户（推荐）'}"
        )
        row.addWidget(self.permission_status_label, 1)

        restart_admin_button = QPushButton("以管理员身份重启")
        restart_admin_button.setFixedHeight(36)
        restart_admin_button.setMinimumWidth(148)
        restart_admin_button.setFont(QFont("Microsoft YaHei", 12))
        style_as_secondary_button(restart_admin_button)
        restart_admin_button.clicked.connect(self._restart_as_admin)
        restart_admin_button.setEnabled(not admin_now)
        if admin_now:
            restart_admin_button.setToolTip("当前已是管理员权限")
        row.addWidget(restart_admin_button)

        section_layout.addLayout(row)
        parent_layout.addWidget(panel)

    def _create_hotkey_overview_section(self, parent_layout):
        """P2.1: 全局热键总览——所有功能域当前绑定的键一目了然。"""
        panel, section_layout = SettingsCard.make(
            "全局热键总览",
            "汇总开镜放大 / 语音输出音板 / 道具瞄点等功能当前注册的全局按键。"
            "改键时若与其他功能撞键，对应页面会给出冲突提示。",
        )

        self.hotkey_overview_label = QLabel("（点击「刷新」查看当前绑定）")
        self.hotkey_overview_label.setObjectName("hintLabel")
        self.hotkey_overview_label.setWordWrap(True)
        self.hotkey_overview_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        section_layout.addWidget(self.hotkey_overview_label)

        refresh_row = QHBoxLayout()
        refresh_row.addStretch(1)
        refresh_btn = QPushButton("刷新")
        refresh_btn.setFixedHeight(32)
        refresh_btn.setMinimumWidth(96)
        style_as_secondary_button(refresh_btn)
        refresh_btn.clicked.connect(self._refresh_hotkey_overview)
        refresh_row.addWidget(refresh_btn)
        section_layout.addLayout(refresh_row)

        parent_layout.addWidget(panel)
        # 页面创建时先填一次
        self._refresh_hotkey_overview()

    def _refresh_hotkey_overview(self):
        try:
            from core.hotkeys import registry as hotkey_registry

            rows = hotkey_registry.list_bindings()
        except Exception:
            self.hotkey_overview_label.setText("热键注册中心不可用。")
            return
        if not rows:
            self.hotkey_overview_label.setText(
                "当前没有已注册的全局热键（相关功能未开启，或尚未加载对应页面）。"
            )
            return
        kind_text = {"key": "按键", "hotkey": "组合键", "mouse": "鼠标", "hook": "监听", "interest": "声明"}
        lines = []
        for r in rows:
            suffix = " ·吞键" if r.get("suppress") else ""
            note = f"（{r['note']}）" if r.get("note") else ""
            lines.append(f"• [{r['owner']}] {kind_text.get(r['kind'], r['kind'])}: {r['key']}{suffix} {note}")
        self.hotkey_overview_label.setText("\n".join(lines))

    def _restart_as_admin(self):
        """确认后以管理员身份重启程序。"""
        from PySide6.QtWidgets import QApplication
        from core.utils.elevation import restart_as_admin

        reply = QMessageBox.question(
            self,
            "以管理员身份重启",
            "将弹出系统 UAC 确认窗口，确认后程序会自动重启。\n继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if restart_as_admin():
            self.logger.info("已请求管理员重启，当前实例退出")
            QApplication.quit()
        else:
            QMessageBox.information(
                self, "提示", "提权被取消或失败，程序继续以普通权限运行。"
            )

    def _create_config_section(self, parent_layout):
        """创建配置文件管理区域"""
        section_layout = QVBoxLayout()
        section_layout.setSpacing(8)
        
        # 按钮
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(12)
        
        reset_button = QPushButton("重置所有设置")
        # R7/D-06 头号点名项：os.remove(config.json) + QApplication.quit()，当场不可逆。
        # R6 加的重置前快照是**带外补救**（要重启、要进快照页），不改变按钮本身的危险性。
        # 注意它原本被 ui_style_applier 按文案猜成了 actionButton（不红）——
        # 全站最不可逆的操作反而是灰的，正是 D-06 要修的东西。
        reset_button.setFixedHeight(38)
        reset_button.setMinimumWidth(148)
        reset_button.setFont(QFont("Microsoft YaHei", 12))
        # 必须放在最后：这一行原本是 style_as_secondary_button，
        # 谁在后面谁说了算（两者都是 setObjectName）。
        style_as_danger_button(reset_button)
        reset_button.clicked.connect(self._reset_all_settings)

        action_hint = QLabel("建议先备份，再重置。")
        action_hint.setObjectName("hintLabel")
        action_hint.setWordWrap(True)
        buttons_layout.addWidget(action_hint, 1)
        buttons_layout.addStretch()
        buttons_layout.addWidget(reset_button)

        backup_button = QPushButton("备份设置")
        backup_button.setFixedHeight(38)
        backup_button.setMinimumWidth(132)
        backup_button.setFont(QFont("Microsoft YaHei", 12))
        style_as_primary_button(backup_button)
        backup_button.clicked.connect(self._backup_settings)
        buttons_layout.addWidget(backup_button)
        
        section_layout.addLayout(buttons_layout)
        parent_layout.addLayout(section_layout)
    
    def _browse_for_csgo_dir(self):
        """选择CS:GO目录"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择 CS:GO 安装目录",
            config.csgo_dir if hasattr(config, 'csgo_dir') and config.csgo_dir else ""
        )
        
        if directory:
            if self._validate_csgo_dir(directory):
                self._auto_detected = False
                config.csgo_dir = directory
                config.save_config()
                self._update_csgo_dir_display()
                
                # 确保配置文件存在
                try:
                    from cfg_utils import ensure_all_cfg
                    ensure_all_cfg(config.csgo_dir)
                except ImportError:
                    self.logger.warning("cfg_utils 模块未找到，跳过配置文件创建")
                except Exception as e:
                    self.logger.error(f"创建配置文件失败: {e}")
                
                QMessageBox.information(self, "成功", "CS:GO 目录设置成功！")
                self.logger.info(f"CS:GO 目录已设置: {directory}")
            else:
                QMessageBox.critical(
                    self,
                    "错误",
                    "无效的 CS:GO 目录！\n\n请确保选择的目录包含: game/csgo/cfg 文件夹。"
                )
                self.logger.warning(f"无效的 CS:GO 目录: {directory}")
    
    def _validate_csgo_dir(self, directory):
        """验证CS:GO目录"""
        is_valid = self._is_valid_csgo_dir(directory)
        self.logger.info(f"验证 CS:GO 目录: {directory}, 有效={is_valid}")
        return is_valid
    
    def _update_csgo_dir_display(self):
        """更新CS:GO目录显示"""
        csgo_dir = config.csgo_dir if hasattr(config, 'csgo_dir') and config.csgo_dir else "未设置"
        self.csgo_dir_text.setText(csgo_dir)
        self.csgo_dir_text.setCursorPosition(0)
        self._sync_overview_status()
        self.logger.debug(f"更新目录显示: {csgo_dir}")
    
    def _toggle_debug_mode(self):
        """切换调试模式（开源版：无口令，直接开关）。"""
        self.debug_mode = not self.debug_mode
        config.debug_mode = self.debug_mode
        config.save_config()
        self._update_debug_status()
        self.logger.info(f"调试模式已{'启用' if self.debug_mode else '关闭'}")

    def _update_debug_status(self):
        """更新调试状态显示"""
        if self.debug_mode:
            self.debug_status_label.setText("当前状态：已启用调试模式。排查完成后建议关闭。")
        else:
            self.debug_status_label.setText("当前状态：正常使用状态。如需排查异常或联动问题，可临时开启。")
        button = getattr(self, "debug_button", None)
        if button is not None:
            button.setText("关闭调试模式" if self.debug_mode else "开启调试模式")
        self._sync_overview_status()
    
    def _on_theme_changed(self, index):
        """主题切换事件"""
        theme_name = self.theme_combo.itemData(index)

        self.theme_manager.set_theme(theme_name)

        config.ui_theme = theme_name
        config.save_config()
        self._sync_overview_status()

        self.logger.info(f"主题已切换至: {self.theme_manager.current_theme.name}")

        # 同步首页主题下拉框
        main_window = self.window()
        if hasattr(main_window, 'theme_combo'):
            main_window.theme_combo.blockSignals(True)
            idx = main_window.theme_combo.findData(theme_name)
            if idx >= 0:
                main_window.theme_combo.setCurrentIndex(idx)
            main_window.theme_combo.blockSignals(False)
    
    def _reset_all_settings(self):
        """重置所有设置。

        UP-036: 这是全软件**最不可逆**的操作（直接删配置文件），
        原本却是唯一一个**不做自动快照**的危险操作——而危险性远低于它的
        「应用预设」反倒每次都建快照。现在执行前先建一份，
        并在两个对话框里都把"能回滚"这件事说清楚，否则用户不知道有退路。
        """
        snapshot_hint = ""
        try:
            from core.config_snapshot_manager import list_snapshots
            _ = list_snapshots  # 只为确认快照子系统可用
            snapshot_hint = "\n\n执行前会自动保存一份配置快照，重启后可在「配置快照」页恢复。"
        except Exception:
            snapshot_hint = "\n\n⚠ 快照子系统不可用，本次重置**无法回滚**。"

        reply = QMessageBox.question(
            self,
            "确认重置",
            "确定要重置所有设置吗？\n\n这将恢复所有默认值，程序将自动关闭。" + snapshot_hint,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # 先建快照再删文件——顺序反了就什么都没了
            snapshot_ok = False
            try:
                from core.config_snapshot_manager import create_snapshot, prune_snapshots

                create_snapshot("before_reset_all")
                prune_snapshots(int(getattr(config, "config_snapshot_max_keep", 20) or 20))
                snapshot_ok = True
                self.logger.info("[重置] 已创建重置前快照 before_reset_all")
            except Exception:
                self.logger.exception("[重置] 创建快照失败")

            if not snapshot_ok:
                # 建不了快照就把选择权交回用户，别默默做不可逆的事
                again = QMessageBox.warning(
                    self, "无法创建快照",
                    "创建配置快照失败，继续重置将**无法回滚**。\n\n仍要继续吗？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if again != QMessageBox.Yes:
                    self.logger.info("[重置] 用户在快照失败后取消了重置")
                    return

            try:
                # 删除配置文件
                config_path = config.get_config_path()
                if os.path.exists(config_path):
                    os.remove(config_path)
                    self.logger.info(f"配置文件已删除: {config_path}")

                # 提示重启程序
                QMessageBox.information(
                    self,
                    "成功",
                    "设置已重置！\n\n程序将自动关闭，请重新启动以应用更改。"
                    + ("\n\n如需找回旧配置：重启后到「配置快照」页恢复 "
                       "`before_reset_all`。" if snapshot_ok else ""),
                )

                # 关闭程序
                from PySide6.QtWidgets import QApplication
                QApplication.quit()
            except Exception as e:
                self.logger.error(f"重置设置失败: {e}")
                QMessageBox.critical(self, "错误", "重置设置失败：配置文件可能被占用，请关闭相关程序后重试。")
    
    def _backup_settings(self):
        """备份设置"""
        try:
            # 获取保存位置
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "保存设置备份",
                "cs2customizer_config_backup.json",
                "JSON文件 (*.json)"
            )
            
            if not filename:
                return
            
            # 拷贝配置文件
            config_path = config.get_config_path()
            if not os.path.exists(config_path):
                QMessageBox.warning(self, "警告", "配置文件不存在！")
                return
            
            shutil.copy2(config_path, filename)
            self.logger.info(f"设置已备份到: {filename}")
            
            QMessageBox.information(
                self,
                "成功",
                f"设置已成功备份到:\n\n{filename}"
            )
        except Exception as e:
            self.logger.error(f"备份设置失败: {e}")
            QMessageBox.critical(self, "错误", "备份设置失败：目标位置可能无写入权限，请换个位置后重试。")
    
    def _load_settings(self):
        """加载设置"""
        self._update_csgo_dir_display()
        self._update_debug_status()
        self._sync_overview_status()
        self.logger.info("高级设置已加载")

    def _try_auto_detect_cs2(self):
        """尝试自动检测CS2目录（仅首次运行时）"""
        # 如果已经配置过目录，不自动检测
        if config.csgo_dir and os.path.exists(config.csgo_dir):
            return

        # 尝试自动检测
        detected_path = find_cfg_path()
        if detected_path:
            # 从 cfg 路径提取 CS2 根目录
            # detected_path 格式: Steam/steamapps/common/Counter-Strike Global Offensive/game/csgo/cfg/xxx.cfg
            cs2_dir = detected_path
            for _ in range(4):  # 向上4级: cfg -> csgo -> game -> CS2根目录
                cs2_dir = os.path.dirname(cs2_dir)

            if os.path.exists(cs2_dir):
                config.csgo_dir = cs2_dir
                config.save_config()
                self._auto_detected = True
                self._update_csgo_dir_display()
                self.logger.info(f"自动检测到CS2目录: {cs2_dir}")

                try:
                    from cfg_utils import ensure_all_cfg
                    ensure_all_cfg(cs2_dir)
                except Exception as e:
                    self.logger.warning(f"自动检测后补齐CFG失败: {e}")

                # 显示提示消息
                QMessageBox.information(
                    self,
                    "自动检测成功",
                    f"已自动检测到CS2安装目录：\n\n{cs2_dir}\n\n"
                    "如需修改，请在高级设置页面手动选择。"
                )
