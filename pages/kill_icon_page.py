# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标设置页面"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSlider, QFrame, QScrollArea, QMessageBox, QBoxLayout, QSizePolicy
)
from PySide6.QtCore import Qt

from config import config
from resource_manager import ResourceManager
from core.utils.logger import get_logger
from core.utils.format_utils import format_percent
from pages.audio_status_badge import create_badge_label, render_badges
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard


class KillIconPage(QWidget):
    """击杀图标设置页面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("KillIconPage")
        self.kill_icon_player = None  # 将在外部设置
        
        self.available_icon_styles = []
        self.fps_vars = {}
        self.fps_sliders = {}
        self.fps_labels = {}
        self.fps_modified = False
        self._loading = False  # 防止 load_settings 触发 _on_style_changed
        
        self._scan_icon_styles()
        self._init_ui()
        self.load_settings()
        
        # 预加载当前风格的图标
        if self.kill_icon_player and config.kill_icon_style != "0":
            self.kill_icon_player.load_style(config.kill_icon_style)
        
        self.logger.info("击杀图标页面初始化完成")
    
    def set_kill_icon_player(self, player):
        """设置kill_icon_player引用"""
        self.kill_icon_player = player
        
        # 预加载当前风格的图标
        if player and config.kill_icon_style != "0":
            player.load_style(config.kill_icon_style)
            self.logger.info(f"预加载击杀图标风格: {config.kill_icon_style}")
        
        # 重新加载FPS设置
        if player and hasattr(self, 'style_combo'):
            style = self.style_combo.currentData()
            if style and style != "":
                self._update_fps_display(style)
        self._sync_status_strip()
    
    def _init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        
        # 页面标题
        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "击杀图标设置",
            description="这里保留风格、偏移、缩放和 FPS 四个高频入口，尽量让击杀图标的调整过程更像一块紧凑工具面板。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        main_layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["kill_icon"])

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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(10)
        
        self.style_card = self._create_style_card()
        self.tool_card = self._create_tool_card()
        self.style_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.tool_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.tool_card.setMinimumWidth(320)
        self.tool_card.setMaximumWidth(360)

        self.top_content_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self.top_content_layout.setSpacing(10)
        self.top_content_layout.addWidget(self.style_card, 1, Qt.AlignTop)
        self.top_content_layout.addWidget(self.tool_card, 0, Qt.AlignTop)
        scroll_layout.addLayout(self.top_content_layout)
        
        # 位置和大小调整卡片
        adjust_card = self._create_adjust_card()
        scroll_layout.addWidget(adjust_card)
        
        # FPS设置卡片
        fps_card = self._create_fps_card()
        scroll_layout.addWidget(fps_card)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(124)
        self.action_bar.primary_btn.setMinimumWidth(140)
        main_layout.addWidget(self.action_bar, 0)
        self._sync_status_strip()
        self._update_compact_layout()

    def _compact_text(self, text, fallback="未设置", max_length=14):
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    def _current_fps_summary(self):
        if not self.fps_sliders:
            return "未载入"
        values = [self.fps_sliders[kills].value() for kills in sorted(self.fps_sliders)]
        if not values:
            return "未载入"
        return f"{values[0]}-{values[-1]}"

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        style_text = self.style_combo.currentText() if hasattr(self, "style_combo") else getattr(config, "kill_icon_style", "")
        player_ready = self.kill_icon_player is not None
        fps_text = "待同步" if self.fps_modified else self._current_fps_summary()

        if player_ready:
            self.action_bar.configure_secondary("测试 1 杀", lambda: self._test_kill_icon(1), visible=True)
            self.action_bar.configure_primary(
                "保存FPS设置" if self.fps_modified else "预览当前设置",
                self._save_fps_settings if self.fps_modified else self._preview_settings,
                visible=True,
            )
        else:
            self.action_bar.configure_secondary("打开制作工具", self._open_sprite_maker, visible=True)
            self.action_bar.configure_primary(
                "保存FPS设置",
                self._save_fps_settings,
                visible=bool(self.fps_modified),
            )

        action_message = (
            f"当前风格：{self._compact_text(style_text, '未设置', 16)}"
            f" · FPS {fps_text} · 偏移 {getattr(config, 'kill_icon_offset_x', 0)}/{getattr(config, 'kill_icon_offset_y', 0)}"
            f" · 缩放 {format_percent(getattr(config, 'kill_icon_scale', 1.0), hi=2.0)}"
            f" · 预览{'已连接' if player_ready else '未连接'}。"
        )
        self.action_bar.set_message(action_message)

    def _sync_status_strip(self):
        style_text = self._compact_text(
            self.style_combo.currentText() if hasattr(self, "style_combo") else getattr(config, "kill_icon_style", ""),
            "未设置",
        )
        position_text = f"{getattr(config, 'kill_icon_offset_x', 0)}/{getattr(config, 'kill_icon_offset_y', 0)}"
        scale_text = format_percent(getattr(config, 'kill_icon_scale', 1.0), hi=2.0)
        fps_text = "待同步" if self.fps_modified else self._current_fps_summary()
        player_ready = self.kill_icon_player is not None

        badges = [
            (
                "positive" if getattr(config, "kill_icon_style", "0") not in ("", "0") else "warning",
                f"风格 · {style_text}",
            ),
            ("info", f"偏移 · {position_text}"),
            ("info", f"缩放 · {scale_text}"),
            ("warning" if self.fps_modified else "positive", f"FPS · {fps_text}"),
            ("positive" if player_ready else "warning", f"预览 · {'已连接' if player_ready else '未连接'}"),
        ]

        detail_text = (
            f"当前风格：{self.style_combo.currentText() if hasattr(self, 'style_combo') else getattr(config, 'kill_icon_style', '未设置')}\n"
            f"可用风格：{len(self.available_icon_styles)} 项\n"
            f"位置偏移：X {getattr(config, 'kill_icon_offset_x', 0)} / Y {getattr(config, 'kill_icon_offset_y', 0)}\n"
            f"图标缩放：{scale_text}\n"
            f"FPS 状态：{'待同步' if self.fps_modified else '已同步'}\n"
            f"FPS 范围：{self._current_fps_summary()}\n"
            f"预览组件：{'已连接' if player_ready else '未连接'}"
        )
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.summary_label.setText(detail_text)
        self.summary_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)
        if hasattr(self, "style_summary_label"):
            style_summary = (
                f"当前风格：{self.style_combo.currentText() if hasattr(self, 'style_combo') else getattr(config, 'kill_icon_style', '未设置')}"
                f" · 已扫描 {len(self.available_icon_styles)} 套风格 · 预览{'已连接' if player_ready else '未连接'}"
            )
            self.style_summary_label.setText(style_summary)
            self.style_summary_label.setToolTip(detail_text)

        if hasattr(self, "adjust_summary_label"):
            adjust_summary = f"当前位置：X {getattr(config, 'kill_icon_offset_x', 0)} / Y {getattr(config, 'kill_icon_offset_y', 0)} · 缩放 {scale_text}"
            self.adjust_summary_label.setText(adjust_summary)
            self.adjust_summary_label.setToolTip(detail_text)

        if hasattr(self, "fps_summary_label"):
            fps_summary = f"当前 FPS：{self._current_fps_summary()} · {'尚未保存到风格配置' if self.fps_modified else '已同步到当前风格'}"
            self.fps_summary_label.setText(fps_summary)
            self.fps_summary_label.setToolTip(detail_text)

        if hasattr(self, "tool_summary_label"):
            tool_summary = (
                f"资源状态：已扫描 {len(self.available_icon_styles)} 套风格"
                if self.available_icon_styles
                else "资源状态：还没有可用风格，建议先打开制作工具生成一套资源"
            )
            self.tool_summary_label.setText(tool_summary)
            self.tool_summary_label.setToolTip(detail_text)
        self._sync_action_bar()


    def _create_style_card(self):
        """创建风格选择卡片"""
        card, card_layout = SettingsCard.make(
            "图标风格",
            "切换风格后会立即同步到预览；下方击杀测试适合快速确认节奏和画面密度。",
        )

        self.style_summary_label = QLabel("")
        self.style_summary_label.setObjectName("hintLabel")
        self.style_summary_label.setWordWrap(True)
        card_layout.addWidget(self.style_summary_label)

        style_layout = QHBoxLayout()
        style_layout.setSpacing(8)
        style_layout.addWidget(QLabel("当前风格:"))

        self.style_combo = QComboBox()
        self.style_combo.setMinimumWidth(220)
        self.style_combo.setFixedHeight(34)
        for style in self.available_icon_styles:
            self.style_combo.addItem(style, style)
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        style_layout.addWidget(self.style_combo)
        style_layout.addStretch()
        card_layout.addLayout(style_layout)

        styles_label = QLabel(f"已扫描到 {len(self.available_icon_styles)} 套风格，支持 Sprite Sheet 动画资源。")
        styles_label.setObjectName("hintLabel")
        styles_label.setWordWrap(True)
        card_layout.addWidget(styles_label)

        quick_test_layout = QHBoxLayout()
        quick_test_layout.setSpacing(8)
        quick_test_label = QLabel("快速测试:")
        quick_test_label.setMinimumWidth(64)
        quick_test_layout.addWidget(quick_test_label)

        for i in range(1, 6):
            test_btn = QPushButton(f"{i} 杀")
            test_btn.setObjectName("secondaryButton")
            test_btn.setFixedHeight(34)
            test_btn.setFixedWidth(72)
            test_btn.clicked.connect(lambda checked, k=i: self._test_kill_icon(k))
            quick_test_layout.addWidget(test_btn)

        quick_test_layout.addStretch()
        card_layout.addLayout(quick_test_layout)

        return card
    
    def _create_adjust_card(self):
        """创建位置和大小调整卡片"""
        card, card_layout = SettingsCard.make(
            "位置与缩放",
            "偏移和比例改动会立即写入当前配置，预览按钮会按当前设置直接触发一次图标动画。",
        )

        self.adjust_summary_label = QLabel("")
        self.adjust_summary_label.setObjectName("hintLabel")
        self.adjust_summary_label.setWordWrap(True)
        card_layout.addWidget(self.adjust_summary_label)

        # 水平位置
        x_frame = QFrame()
        x_layout = QHBoxLayout(x_frame)
        x_layout.setContentsMargins(0, 0, 0, 0)
        x_layout.setSpacing(8)
        
        x_label = QLabel("水平位置:")
        x_label.setFixedWidth(80)
        x_layout.addWidget(x_label)
        
        self.x_slider = QSlider(Qt.Horizontal)
        self.x_slider.setMinimum(-200)
        self.x_slider.setMaximum(200)
        self.x_slider.setValue(config.kill_icon_offset_x)
        self.x_slider.valueChanged.connect(lambda v: self._on_x_position_changed(v))
        x_layout.addWidget(self.x_slider)
        
        self.x_value_label = QLabel(f"{config.kill_icon_offset_x} px")
        self.x_value_label.setFixedWidth(60)
        x_layout.addWidget(self.x_value_label)
        
        card_layout.addWidget(x_frame)
        
        # 垂直位置
        y_frame = QFrame()
        y_layout = QHBoxLayout(y_frame)
        y_layout.setContentsMargins(0, 0, 0, 0)
        y_layout.setSpacing(8)
        
        y_label = QLabel("垂直位置:")
        y_label.setFixedWidth(80)
        y_layout.addWidget(y_label)
        
        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.setMinimum(-200)
        self.y_slider.setMaximum(200)
        self.y_slider.setValue(config.kill_icon_offset_y)
        self.y_slider.valueChanged.connect(lambda v: self._on_y_position_changed(v))
        y_layout.addWidget(self.y_slider)
        
        self.y_value_label = QLabel(f"{config.kill_icon_offset_y} px")
        self.y_value_label.setFixedWidth(60)
        y_layout.addWidget(self.y_value_label)
        
        card_layout.addWidget(y_frame)
        
        # 图标大小
        scale_frame = QFrame()
        scale_layout = QHBoxLayout(scale_frame)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.setSpacing(8)
        
        scale_label = QLabel("图标大小:")
        scale_label.setFixedWidth(80)
        scale_layout.addWidget(scale_label)
        
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setMinimum(50)  # 0.5 * 100
        self.scale_slider.setMaximum(200)  # 2.0 * 100
        self.scale_slider.setValue(int(config.kill_icon_scale * 100))
        self.scale_slider.valueChanged.connect(lambda v: self._on_scale_changed(v))
        scale_layout.addWidget(self.scale_slider)
        
        self.scale_value_label = QLabel(format_percent(config.kill_icon_scale, hi=2.0))
        self.scale_value_label.setFixedWidth(60)
        scale_layout.addWidget(self.scale_value_label)
        
        card_layout.addWidget(scale_frame)
        
        # 按钮行
        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 4, 0, 0)
        button_layout.setSpacing(10)
        
        reset_btn = QPushButton("重置位置和大小")
        reset_btn.setObjectName("secondaryButton")
        reset_btn.setFixedHeight(36)
        # UP-094: 原本是 setFixedWidth(146)，文字可用区 108px 但需要 112px，
        # 在 6 个主题×字号组合里有 2 个会被打省略号。改成**下限**：
        # 文字装得下时宽度与原来一样（sizeHint < 146），放大字号时才跟着长。
        reset_btn.setMinimumWidth(146)
        reset_btn.clicked.connect(self._reset_position_and_scale)
        button_layout.addWidget(reset_btn)
        
        preview_btn = QPushButton("预览当前设置")
        preview_btn.setObjectName("actionButton")
        preview_btn.setFixedHeight(36)
        preview_btn.setFixedWidth(138)
        preview_btn.clicked.connect(self._preview_settings)
        button_layout.addWidget(preview_btn)
        
        button_layout.addStretch()
        card_layout.addWidget(button_frame)
        
        return card
    
    def _create_fps_card(self):
        """创建FPS设置卡片"""
        card, card_layout = SettingsCard.make(
            "播放速度 (FPS)",
            "每个击杀级别都可以独立设定动画帧率；改动后需要手动保存才会落到风格配置里。",
        )

        self.fps_summary_label = QLabel("")
        self.fps_summary_label.setObjectName("hintLabel")
        self.fps_summary_label.setWordWrap(True)
        card_layout.addWidget(self.fps_summary_label)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)
        header_layout.addStretch()

        self.save_fps_btn = QPushButton("保存FPS设置")
        self.save_fps_btn.setObjectName("actionButton")
        self.save_fps_btn.setFixedHeight(36)
        # UP-094: 原本是 setFixedWidth(120)，可用区 86px 但需要 92px。
        # 这个按钮还会在有未保存改动时把文案换成「保存FPS设置 *」——更宽，
        # 写死的宽度在那个状态下更不够。同样改成下限。
        self.save_fps_btn.setMinimumWidth(120)
        self.save_fps_btn.clicked.connect(self._save_fps_settings)
        header_layout.addWidget(self.save_fps_btn)
        card_layout.addLayout(header_layout)
        
        # 为每个击杀数创建FPS设置
        for kills in range(1, 6):
            kills_frame = QFrame()
            kills_layout = QHBoxLayout(kills_frame)
            kills_layout.setContentsMargins(0, 0, 0, 0)
            kills_layout.setSpacing(8)
            
            kills_label = QLabel(f"{kills}杀:")
            kills_label.setFixedWidth(54)
            kills_layout.addWidget(kills_label)
            
            fps_slider = QSlider(Qt.Horizontal)
            fps_slider.setMinimum(1)
            fps_slider.setMaximum(60)
            fps_slider.setValue(30)  # 默认值
            fps_slider.valueChanged.connect(lambda v, k=kills: self._on_fps_changed(k, v))
            kills_layout.addWidget(fps_slider)
            
            fps_label = QLabel("30 FPS")
            fps_label.setFixedWidth(64)
            kills_layout.addWidget(fps_label)
            
            card_layout.addWidget(kills_frame)
            
            self.fps_sliders[kills] = fps_slider
            self.fps_labels[kills] = fps_label
        
        return card

    def _create_tool_card(self):
        card, card_layout = SettingsCard.make(
            "资源工具",
            "如果还没有可用风格，可以直接打开 Sprite Sheet 制作工具生成图集与配置文件。",
        )

        self.tool_summary_label = QLabel("")
        self.tool_summary_label.setObjectName("hintLabel")
        self.tool_summary_label.setWordWrap(True)
        card_layout.addWidget(self.tool_summary_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        tool_btn = QPushButton("打开 Sprite Sheet 制作工具")
        tool_btn.setObjectName("actionButton")
        tool_btn.setFixedHeight(36)
        tool_btn.setMinimumWidth(220)
        tool_btn.clicked.connect(self._open_sprite_maker)
        button_row.addWidget(tool_btn, 1)

        card_layout.addLayout(button_row)
        return card

    def _update_compact_layout(self):
        if not hasattr(self, "top_content_layout"):
            return

        direction = QBoxLayout.TopToBottom if self.width() < 1180 else QBoxLayout.LeftToRight
        if self.top_content_layout.direction() != direction:
            self.top_content_layout.setDirection(direction)

        if hasattr(self, "tool_card"):
            if direction == QBoxLayout.TopToBottom:
                self.tool_card.setMinimumWidth(0)
                self.tool_card.setMaximumWidth(16777215)
            else:
                self.tool_card.setMinimumWidth(320)
                self.tool_card.setMaximumWidth(360)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_compact_layout()

    def _scan_icon_styles(self):
        """扫描可用的图标风格"""
        self.available_icon_styles = ResourceManager.list_kill_icon_styles()
        
        if not self.available_icon_styles:
            self.logger.warning("未扫描到任何击杀图标风格")
        
        self.logger.info(f"扫描到的击杀图标风格: {self.available_icon_styles}")
    
    def load_settings(self):
        """加载设置"""
        self._loading = True
        try:
            # 设置当前风格
            current_style = config.kill_icon_style
            index = self.style_combo.findData(current_style)
            if index >= 0:
                self.style_combo.setCurrentIndex(index)
            elif self.style_combo.count() > 0:
                self.style_combo.setCurrentIndex(0)

            # 更新FPS显示
            if current_style and self.kill_icon_player:
                self._update_fps_display(current_style)

            self.logger.debug("加载击杀图标设置完成")
        finally:
            self._loading = False
            self._sync_status_strip()
    
    def _update_fps_display(self, style):
        """更新FPS显示"""
        if not self.kill_icon_player:
            return
        
        for kills in range(1, 6):
            fps = self.kill_icon_player.get_style_fps(style, kills)
            if kills in self.fps_sliders:
                was_blocked = self.fps_sliders[kills].blockSignals(True)
                self.fps_sliders[kills].setValue(fps)
                self.fps_sliders[kills].blockSignals(was_blocked)
            if kills in self.fps_labels:
                self.fps_labels[kills].setText(f"{fps} FPS")
        self.fps_modified = False
        if hasattr(self, "save_fps_btn"):
            self.save_fps_btn.setText("保存FPS设置")
        self._sync_status_strip()
    
    def _on_style_changed(self):
        """风格改变"""
        if self._loading:
            return
        style = self.style_combo.currentData()
        if not style:
            return
        
        config.kill_icon_style = style
        config.save_config()
        
        self.logger.info(f"击杀图标风格更新: {style}")
        
        # 重新加载图标
        if self.kill_icon_player:
            self.kill_icon_player.load_style(style)
            self._update_fps_display(style)
        self._sync_status_strip()
    
    def _on_x_position_changed(self, value):
        """水平位置改变"""
        config.kill_icon_offset_x = value
        config.save_config()
        self.x_value_label.setText(f"{value} px")
        
        # 通知图标播放器更新位置
        if self.kill_icon_player:
            self.kill_icon_player.update_position_offset(
                config.kill_icon_offset_x,
                config.kill_icon_offset_y
            )
        self._sync_status_strip()
    
    def _on_y_position_changed(self, value):
        """垂直位置改变"""
        config.kill_icon_offset_y = value
        config.save_config()
        self.y_value_label.setText(f"{value} px")
        
        # 通知图标播放器更新位置
        if self.kill_icon_player:
            self.kill_icon_player.update_position_offset(
                config.kill_icon_offset_x,
                config.kill_icon_offset_y
            )
        self._sync_status_strip()
    
    def _on_scale_changed(self, value):
        """大小改变"""
        scale = value / 100.0
        config.kill_icon_scale = scale
        config.save_config()
        self.scale_value_label.setText(f"{value}%")
        
        # 通知图标播放器更新缩放
        if self.kill_icon_player:
            self.kill_icon_player.update_scale(scale)
        self._sync_status_strip()
    
    def _reset_position_and_scale(self):
        """重置位置和大小"""
        config.kill_icon_offset_x = 0
        config.kill_icon_offset_y = 0
        config.kill_icon_scale = 1.0
        config.save_config()
        
        # 更新UI
        self.x_slider.setValue(0)
        self.y_slider.setValue(0)
        self.scale_slider.setValue(100)
        self.x_value_label.setText("0 px")
        self.y_value_label.setText("0 px")
        self.scale_value_label.setText("100%")
        
        # 通知图标播放器
        if self.kill_icon_player:
            self.kill_icon_player.update_position_offset(0, 0)
            self.kill_icon_player.update_scale(1.0)
        self._sync_status_strip()
        
        self.logger.info("重置位置和大小")
    
    def _preview_settings(self):
        """预览当前设置"""
        if self.kill_icon_player:
            # 使用1杀图标预览3秒
            self.kill_icon_player.preview_position_and_scale(1, 3)
            self.logger.info("预览击杀图标设置")
        else:
            QMessageBox.warning(self, "提示", "图标播放器未初始化")
    
    def _on_fps_changed(self, kills, value):
        """FPS改变"""
        if kills in self.fps_labels:
            self.fps_labels[kills].setText(f"{value} FPS")
        
        self.fps_modified = True
        self._sync_status_strip()
        self.save_fps_btn.setText("保存FPS设置 *")
    
    def _save_fps_settings(self):
        """保存FPS设置"""
        if not self.kill_icon_player:
            QMessageBox.warning(self, "提示", "图标播放器未初始化")
            return
        
        style = config.kill_icon_style
        saved_count = 0
        
        for kills in range(1, 6):
            if kills in self.fps_sliders:
                fps = self.fps_sliders[kills].value()
                if self.kill_icon_player.update_fps_for_style(style, kills, fps):
                    saved_count += 1
        
        if saved_count > 0:
            QMessageBox.information(self, "保存成功", f"已保存 {saved_count} 个击杀等级的FPS设置")
            self.save_fps_btn.setText("保存FPS设置")
            self.fps_modified = False
            self.logger.info(f"保存了 {saved_count} 个FPS设置")
        else:
            QMessageBox.warning(self, "保存失败", "未能保存FPS设置")
    
        self._sync_status_strip()

    def _test_kill_icon(self, kills):
        """测试击杀图标"""
        if self.kill_icon_player:
            if kills in self.fps_sliders:
                fps = self.fps_sliders[kills].value()
            else:
                fps = 30
            
            self.kill_icon_player.play_icon(kills, fps)
            self.logger.info(f"测试 {kills} 杀图标, FPS: {fps}")
        else:
            QMessageBox.warning(self, "提示", "图标播放器未初始化")
    
    def _open_sprite_maker(self):
        """打开Sprite Sheet制作工具"""
        try:
            from dialogs import SpriteSheetMaker
            maker = SpriteSheetMaker(self)
            maker.exec()
            self.logger.info("打开Sprite Sheet制作工具")
        except Exception as e:
            QMessageBox.warning(self, "错误", "无法打开制作工具，请稍后重试。")
            self.logger.error(f"打开制作工具失败: {e}")
