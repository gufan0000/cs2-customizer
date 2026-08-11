from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import config
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from screen_effect_overlay import DEFAULT_SCREEN_EFFECT_PRESET, SCREEN_EFFECT_PRESETS
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
from widgets.page_header import PageHeader


PRESET_ORDER = [
    "lite_competitive",
    "impact_sparks",
    "frenzy_kill",
    "blue_storm",
    "neon_pulse",
    "toxic_surge",
    "amber_overdrive",
    "frost_shock",
]

PLAY_MODE_OPTIONS = [
    ("稳定演出", "steady"),
    ("连杀增强（推荐）", "streak"),
    ("狂欢随机", "chaos"),
]

SPAWN_MODE_LABELS = {
    "edges": "四边扩散",
    "left_right": "左右夹击",
    "center": "中心脉冲",
    "top_bottom": "上下扫过",
    "corners": "四角爆发",
}

PLAY_MODE_DESCRIPTIONS = {
    "steady": "稳定演出会保持每次触发手感接近，适合长期常驻。",
    "streak": "连杀增强会在节奏拉高时自动加强，兼顾稳定和反馈层次。",
    "chaos": "狂欢随机会在预设范围内波动，适合更张扬的观感。",
}


class ScreenEffectsPage(QWidget):
    def __init__(self, overlay_manager=None, parent=None):
        super().__init__(parent)
        self.logger = get_logger("ScreenEffectsPage")
        self.overlay_manager = overlay_manager
        self._loading = False
        self._init_ui()
        self._load_settings()

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
            "屏幕特效",
            description="击杀或爆头时在屏幕边缘播放一段特效，增强反馈。点右上角「?」看用法。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["screen_effects"])

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
        layout.addWidget(self.status_card)

        overview_card, overview_layout = SettingsCard.make(
            "快速控制台",
            "把边缘触发和当前方案概况收进同一块工作台，首屏判断会更直接，也更省空间。",
        )

        self.top_overview_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self.top_overview_layout.setSpacing(16)

        trigger_column = QVBoxLayout()
        trigger_column.setSpacing(8)

        trigger_title = QLabel("触发开关")
        trigger_title.setObjectName("statusLabel")
        trigger_column.addWidget(trigger_title)

        self.master_state_label = QLabel()
        self.master_state_label.setObjectName("hintLabel")
        self.master_state_label.setWordWrap(True)
        self.master_state_label.hide()
        trigger_column.addWidget(self.master_state_label)

        self.enable_edge_flash_checkbox = QCheckBox("击杀触发屏幕边缘特效")
        trigger_column.addWidget(self.enable_edge_flash_checkbox)

        trigger_tip = QLabel("底部工具栏会保留普通击杀和爆头预览，改完后可以直接验证观感。")
        trigger_tip.setObjectName("hintLabel")
        trigger_tip.setWordWrap(True)
        trigger_column.addWidget(trigger_tip)
        trigger_column.addStretch(1)
        self.top_overview_layout.addLayout(trigger_column, 4)

        summary_column = QVBoxLayout()
        summary_column.setSpacing(8)

        summary_title = QLabel("当前方案概况")
        summary_title.setObjectName("statusLabel")
        summary_column.addWidget(summary_title)

        self.preset_summary_name_label = QLabel("")
        self.preset_summary_name_label.setObjectName("statusLabel")
        summary_column.addWidget(self.preset_summary_name_label)

        self.preset_summary_meta_label = QLabel("")
        self.preset_summary_meta_label.setObjectName("hintLabel")
        self.preset_summary_meta_label.setWordWrap(True)
        summary_column.addWidget(self.preset_summary_meta_label)

        self.preset_summary_hint_label = QLabel("")
        self.preset_summary_hint_label.setObjectName("hintLabel")
        self.preset_summary_hint_label.setWordWrap(True)
        summary_column.addWidget(self.preset_summary_hint_label)
        summary_column.addStretch(1)
        self.top_overview_layout.addLayout(summary_column, 5)

        overview_layout.addLayout(self.top_overview_layout)
        overview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout.addWidget(overview_card)

        card, card_layout = SettingsCard.make(
            "预设与演出",
            "预设负责整体风格，演出模式负责触发节奏；修改后会自动保存，可直接用底部工具栏预览。",
        )

        controls_grid = QGridLayout()
        controls_grid.setHorizontalSpacing(12)
        controls_grid.setVerticalSpacing(8)

        preset_label = QLabel("特效预设:")
        controls_grid.addWidget(preset_label, 0, 0)
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(220)
        self.preset_combo.setMaximumWidth(280)
        self.preset_combo.setMinimumHeight(34)
        self.preset_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        for key in PRESET_ORDER:
            preset = SCREEN_EFFECT_PRESETS.get(key, {})
            label = preset.get("label", key)
            self.preset_combo.addItem(label, key)
        controls_grid.addWidget(self.preset_combo, 0, 1)

        mode_label = QLabel("演出模式:")
        controls_grid.addWidget(mode_label, 0, 2)
        self.play_mode_combo = QComboBox()
        self.play_mode_combo.setMinimumWidth(220)
        self.play_mode_combo.setMaximumWidth(280)
        self.play_mode_combo.setMinimumHeight(34)
        self.play_mode_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        for label, value in PLAY_MODE_OPTIONS:
            self.play_mode_combo.addItem(label, value)
        controls_grid.addWidget(self.play_mode_combo, 0, 3)
        controls_grid.setColumnStretch(4, 1)
        card_layout.addLayout(controls_grid)

        tip = QLabel("说明：动画仅在触发时渲染，优先保证反馈清晰和性能稳定，不再单独暴露零碎参数。")
        tip.setObjectName("hintLabel")
        tip.setWordWrap(True)
        card_layout.addWidget(tip)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        layout.addWidget(card)
        layout.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll)

        self.action_bar = PageActionBar(self)
        self.action_bar.set_message("本页修改自动保存。")
        self.action_bar.configure_secondary("预览击杀", self._preview_normal, visible=True)
        self.action_bar.configure_primary("预览爆头", self._preview_headshot, visible=True)
        self.action_bar.primary_btn.setMinimumWidth(150)
        self.action_bar.secondary_btn.setMinimumWidth(150)
        root.addWidget(self.action_bar, 0)

        self.enable_edge_flash_checkbox.toggled.connect(self._on_setting_changed)
        self.preset_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.play_mode_combo.currentIndexChanged.connect(self._on_setting_changed)
        self._update_compact_layout()

    def _compact_text(self, text, fallback="-", max_length=16):
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    def _sync_status_strip(self):
        master_enabled = bool(getattr(config, "screen_effects_enabled", False))
        edge_enabled = master_enabled and self.enable_edge_flash_checkbox.isChecked()
        preset_text = self._compact_text(
            self.preset_combo.currentText() if hasattr(self, "preset_combo") else "",
            "未设置",
        )
        mode_text = self._compact_text(
            self.play_mode_combo.currentText() if hasattr(self, "play_mode_combo") else "",
            "未设置",
        )

        badges = [
            ("positive" if master_enabled else "warning", f"总开关 · {'开启' if master_enabled else '关闭'}"),
            ("positive" if edge_enabled else "info", f"边缘特效 · {'开启' if edge_enabled else '关闭'}"),
            ("info", f"预设 · {preset_text}"),
            ("info", f"模式 · {mode_text}"),
        ]

        detail_text = (
            f"总开关：{'已开启' if master_enabled else '已关闭'}\n"
            f"边缘特效：{'已开启' if edge_enabled else '已关闭'}\n"
            f"当前预设：{self.preset_combo.currentText() if hasattr(self, 'preset_combo') else '未设置'}\n"
            f"演出模式：{self.play_mode_combo.currentText() if hasattr(self, 'play_mode_combo') else '未设置'}\n"
            f"保存方式：自动保存"
        )
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.summary_label.setText(detail_text)
        self.summary_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)
        self._refresh_preset_overview()

    def _update_compact_layout(self):
        if not hasattr(self, "top_overview_layout"):
            return
        direction = QBoxLayout.TopToBottom if self.width() < 1080 else QBoxLayout.LeftToRight
        if self.top_overview_layout.direction() != direction:
            self.top_overview_layout.setDirection(direction)

    def _current_preset_config(self):
        preset_key = self.preset_combo.currentData() if hasattr(self, "preset_combo") else None
        return SCREEN_EFFECT_PRESETS.get(preset_key or DEFAULT_SCREEN_EFFECT_PRESET, {})

    def _current_mode_value(self):
        if not hasattr(self, "play_mode_combo"):
            return "streak"
        return str(self.play_mode_combo.currentData() or "streak")

    def _refresh_preset_overview(self):
        if not hasattr(self, "preset_summary_name_label"):
            return

        preset_label = self.preset_combo.currentText() if hasattr(self, "preset_combo") else "未设置"
        preset_cfg = self._current_preset_config()
        spawn_mode = SPAWN_MODE_LABELS.get(str(preset_cfg.get("spawn_mode", "edges")), "自适应")
        duration = int(preset_cfg.get("duration_ms", 0))
        particle_count = int(preset_cfg.get("particle_count", 0))
        edge_ratio = int(round(float(preset_cfg.get("edge_ratio", 0.0)) * 100))
        headshot_scale = int(round((float(preset_cfg.get("headshot_particle_scale", 1.0)) - 1.0) * 100))
        mode_value = self._current_mode_value()

        self.preset_summary_name_label.setText(preset_label)
        self.preset_summary_meta_label.setText(
            f"时长 {duration}ms · 粒子 {particle_count} · 覆盖 {edge_ratio}% · 生成 {spawn_mode}"
        )
        self.preset_summary_hint_label.setText(
            f"{PLAY_MODE_DESCRIPTIONS.get(mode_value, PLAY_MODE_DESCRIPTIONS['streak'])}"
            f" 爆头场景会额外抬高约 {max(headshot_scale, 0)}% 的冲击感。"
        )

    def _set_combo_by_data(self, combo, target_value):
        index = combo.findData(target_value)
        if index < 0 and isinstance(target_value, str):
            index = combo.findData(target_value.strip().lower())
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _load_settings(self):
        self._loading = True
        try:
            self.enable_edge_flash_checkbox.setChecked(bool(getattr(config, "screen_edge_flash_enabled", True)))
            preset = getattr(config, "screen_effects_preset", DEFAULT_SCREEN_EFFECT_PRESET)
            if self.preset_combo.findData(preset) < 0:
                preset = DEFAULT_SCREEN_EFFECT_PRESET
            self._set_combo_by_data(self.preset_combo, preset)
            mode = getattr(config, "screen_effects_play_mode", "streak")
            self._set_combo_by_data(self.play_mode_combo, mode)
        except Exception as e:
            self.logger.warning(f"Load screen effects settings failed: {e}")
        finally:
            self._loading = False
            self._sync_enabled_state()
            self._sync_status_strip()

    def refresh_master_state(self):
        self._sync_enabled_state()

    def _sync_enabled_state(self):
        master_enabled = bool(getattr(config, "screen_effects_enabled", False))
        edge_enabled = master_enabled and self.enable_edge_flash_checkbox.isChecked()

        if not master_enabled:
            self.master_state_label.setText("总开关已关闭，请先到基础设置开启“屏幕特效”。")
            self.master_state_label.show()
            self.action_bar.set_message("总开关已关闭，当前页面设置不会生效。")
        elif not self.enable_edge_flash_checkbox.isChecked():
            self.master_state_label.setText("边缘特效已关闭，底部预览按钮当前不可用。")
            self.master_state_label.show()
            self.action_bar.set_message("边缘特效已关闭，可重新勾选后再预览。")
        else:
            self.master_state_label.hide()
            self.action_bar.set_message("本页修改自动保存。")

        self.enable_edge_flash_checkbox.setEnabled(master_enabled)
        self.preset_combo.setEnabled(edge_enabled)
        self.play_mode_combo.setEnabled(edge_enabled)
        self.action_bar.secondary_btn.setEnabled(edge_enabled)
        self.action_bar.primary_btn.setEnabled(edge_enabled)
        self._sync_status_strip()

    def _on_setting_changed(self):
        if self._loading:
            return

        config.screen_edge_flash_enabled = self.enable_edge_flash_checkbox.isChecked()
        selected_preset = self.preset_combo.currentData() or DEFAULT_SCREEN_EFFECT_PRESET
        config.screen_effects_preset = selected_preset
        config.screen_effects_play_mode = self.play_mode_combo.currentData() or "streak"
        config.save_config()

        if self.overlay_manager:
            self.overlay_manager.update_settings_from_config()

        self.action_bar.set_message("已自动保存。")
        self._sync_enabled_state()
        self._sync_status_strip()

    def _preview_normal(self):
        if self.overlay_manager:
            self.overlay_manager.preview(is_headshot=False)

    def _preview_headshot(self):
        if self.overlay_manager:
            self.overlay_manager.preview(is_headshot=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_compact_layout()
