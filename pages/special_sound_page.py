#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""特殊音效设置页面。"""

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import config, get_app_data_dir
from core.audio.runtime_audio import get_runtime_audio_manager
from core.audio.special_events import (
    config_defaults,
    events_in_group,
    sound_key,
    styles_attr,
)
from core.utils.logger import get_logger
from pages.audio_status_badge import (
    build_health_detail_tooltip,
    collect_category_health,
    count_enabled_styles,
    create_badge_label,
    render_badges,
)
from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
from widgets.page_header import PageHeader


class SpecialSoundPage(QWidget):
    """特殊音效配置页面。"""

    TAB_RESOURCE_SUBDIRS = {
        "投掷物": "grenade_sounds",
        "C4": "c4_sounds",
        "血量警告": "health_warning",
        "回合": "round_sounds",
    }

    GRENADE_TYPES = {
        "hegrenade": "手雷",
        "flashbang": "闪光弹",
        "smoke": "烟雾弹",
        "molotov": "燃烧瓶",
        "incgrenade": "燃烧弹",
        "decoy": "诱饵弹",
    }

    # 从事件表派生。这里原来是手写的第 N 份清单，加事件漏改这里的表现是
    # "下拉框里根本没有它"。见 core/audio/special_events。
    ROUND_TYPE_META = {
        event.key: (event.label, styles_attr(event), event.config_attr)
        for event in events_in_group("round")
    }
    C4_EVENTS = events_in_group("c4")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("SpecialSoundPage")
        self.audio_manager = get_runtime_audio_manager()

        self.grenade_combos = {}
        self.round_combos = {}
        self.c4_combos = {}
        self.grenade_cards = []
        self.round_cards = []

        self._ensure_config_defaults()
        self._refresh_special_sound_styles()

        self.init_ui()
        self.load_settings()

    def _ensure_config_defaults(self):
        if not hasattr(config, "grenade_sound_styles") or not isinstance(config.grenade_sound_styles, dict):
            config.grenade_sound_styles = {}

        for grenade_type in self.GRENADE_TYPES:
            config.grenade_sound_styles.setdefault(grenade_type, "0")

        defaults = {
            "grenade_sound_enabled": False,
            "c4_sound_enabled": False,
            "health_warning_enabled": False,
            "health_warning_threshold": 20,
            "health_warning_cooldown": 5.0,
            "round_sound_enabled": False,
            "round_sound_volume": 1.0,
            # 各事件的样式字段来自事件表，不再逐个写
            **config_defaults(),
        }
        for key, value in defaults.items():
            if not hasattr(config, key):
                setattr(config, key, value)

    def _refresh_special_sound_styles(self):
        try:
            self.audio_manager.ensure_styles_scanned()
            self.audio_manager.grenade_sound_styles = self.audio_manager.scan_grenade_sound_styles() or {}
            self.audio_manager.c4_sound_styles = self.audio_manager.scan_c4_sound_styles() or []
            self.audio_manager.health_warning_styles = self.audio_manager.scan_health_warning_styles() or []
            # scan_round_sound_styles 内部已经按事件表把每个 round_*_styles
            # 属性 setattr 回去了，这里再抄一遍就又成了一份要同步的清单。
            self.audio_manager.scan_round_sound_styles()
        except Exception as exc:
            self.logger.error(f"刷新特殊音效风格失败: {exc}")

    @staticmethod
    def _set_combo_data(combo: QComboBox, value):
        was_blocked = combo.blockSignals(True)
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(was_blocked)

    @staticmethod
    def _save_config():
        config.save_config()

    @staticmethod
    def _compact_text(text, fallback="未设置", max_length=14):
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    def _style_summary(self, style_value):
        if str(style_value or "").strip() == "0":
            return "未启用"
        return self._compact_text(style_value, "未启用", 18)

    def _count_enabled_modules(self):
        return sum(
            1
            for enabled in (
                getattr(config, "grenade_sound_enabled", False),
                getattr(config, "c4_sound_enabled", False),
                getattr(config, "health_warning_enabled", False),
                getattr(config, "round_sound_enabled", False),
            )
            if bool(enabled)
        )

    def _collect_style_values(self):
        style_values = list((config.grenade_sound_styles or {}).values())
        style_values.extend(getattr(config, attr, "0") for attr in config_defaults())
        return style_values


    @staticmethod
    def _row_card(horizontal=True):
        """卡片**内部**的一行小卡（`QFrame#card`）。

        本页原来有 8 处逐字重复的「建 QFrame、setObjectName("card")、配一个
        Layout」，R11 的手搓卡片棘轮（tests/test_closed_items_ratchet_r11）正是
        冲着这类重复来的。

        ⚠ 这里不能用 `SettingsCard.make()` 顶替：那个产出的是**带标题的整张
        卡片**，而这些是嵌在卡片里的行，换过去观感会变。所以正确的收敛方向是
        "本页只留一处手搓"，而不是"改用现成卡片"。
        """
        frame = QFrame()
        frame.setObjectName("card")
        layout = (QHBoxLayout if horizontal else QVBoxLayout)(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        return frame, layout

    @staticmethod
    def _create_summary_label():
        label = QLabel("")
        label.setObjectName("hintLabel")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _set_compact_heights(*controls, height=34):
        for control in controls:
            if control is not None:
                control.setMinimumHeight(height)

    @staticmethod
    def _reset_combo_items(combo: QComboBox, style_options, current_value):
        blocked = combo.blockSignals(True)
        combo.clear()
        combo.addItem("不启用", "0")
        for style in style_options:
            combo.addItem(style, style)
        combo.blockSignals(blocked)
        SpecialSoundPage._set_combo_data(combo, current_value)

    @staticmethod
    def _clear_grid_layout(grid: QGridLayout):
        while grid.count():
            item = grid.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().setParent(item.widget().parentWidget())

    @staticmethod
    def _apply_responsive_grid(grid: QGridLayout, cards, columns: int):
        SpecialSoundPage._clear_grid_layout(grid)
        total_columns = max(int(columns or 1), 1)
        for column in range(6):
            grid.setColumnStretch(column, 0)
        for index, card in enumerate(cards):
            row = index // total_columns
            column = index % total_columns
            grid.addWidget(card, row, column)
        for column in range(total_columns):
            grid.setColumnStretch(column, 1)

    def _responsive_columns_for_cards(self, count: int) -> int:
        if count <= 1:
            return 1
        width = max(self.width(), 0)
        if width >= 1380 and count >= 3:
            return 3
        if width >= 940 and count >= 2:
            return 2
        return 1

    def _refresh_responsive_grids(self):
        if hasattr(self, "grenade_grid"):
            self._apply_responsive_grid(
                self.grenade_grid,
                self.grenade_cards,
                self._responsive_columns_for_cards(len(self.grenade_cards)),
            )
        if hasattr(self, "round_grid"):
            self._apply_responsive_grid(
                self.round_grid,
                self.round_cards,
                self._responsive_columns_for_cards(len(self.round_cards)),
            )

    def _refresh_style_catalog(self):
        self._refresh_special_sound_styles()

        for grenade_type, combo in self.grenade_combos.items():
            styles = getattr(self.audio_manager, "grenade_sound_styles", {}).get(grenade_type, [])
            self._reset_combo_items(combo, styles, config.grenade_sound_styles.get(grenade_type, "0"))

        for event in self.C4_EVENTS:
            combo = self.c4_combos.get(event.key)
            if combo is not None:
                self._reset_combo_items(
                    combo,
                    getattr(self.audio_manager, "c4_sound_styles", []),
                    getattr(config, event.config_attr, "0"),
                )
        self._reset_combo_items(
            self.health_style_combo,
            getattr(self.audio_manager, "health_warning_styles", []),
            getattr(config, "health_warning_style", "0"),
        )

        for round_type, (_display_name, manager_attr, config_attr) in self.ROUND_TYPE_META.items():
            combo = self.round_combos.get(round_type)
            if combo is None:
                continue
            self._reset_combo_items(combo, getattr(self.audio_manager, manager_attr, []), getattr(config, config_attr, "0"))

        self._refresh_status_badge()
        self.logger.info("特殊音效风格列表已刷新")

    def _open_current_resource_root(self):
        current_tab = self.tab_widget.tabText(self.tab_widget.currentIndex()) if self.tab_widget.count() else ""
        subdir = self.TAB_RESOURCE_SUBDIRS.get(current_tab, "audio")
        path = get_app_data_dir(os.path.join("resources", "audio", subdir))
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "特殊音效设置",
            description="投掷物、C4、血量警告、回合结果四类音效都在这儿配，一类一个选项卡，随时试听。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        main_layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS.get("special_sound", ""))

        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(14, 12, 14, 12)
        status_card_layout.setSpacing(8)

        status_header = QHBoxLayout()
        status_header.setSpacing(10)
        status_title = QLabel("当前状态")
        status_title.setObjectName("statusLabel")
        status_header.addWidget(status_title)
        self.status_badge_label = create_badge_label()
        status_header.addWidget(self.status_badge_label, 1)
        status_header.addStretch()
        status_card_layout.addLayout(status_header)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        status_card_layout.addWidget(self.summary_label)
        main_layout.addWidget(self.status_card)

        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self._refresh_status_badge)
        main_layout.addWidget(self.tab_widget, 1)

        self._create_grenade_tab()
        self._create_c4_tab()
        self._create_health_tab()
        self._create_round_tab()

        self.action_bar = PageActionBar(self)
        self.action_bar.configure_secondary("刷新风格列表", self._refresh_style_catalog, visible=True)
        self.action_bar.configure_primary("打开当前资源", self._open_current_resource_root, visible=True)
        self.action_bar.secondary_btn.setMinimumWidth(148)
        self.action_bar.primary_btn.setMinimumWidth(148)
        main_layout.addWidget(self.action_bar, 0)

    def _create_grenade_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        header_card, header_layout = SettingsCard.make(
            "投掷物音效",
            "按投掷物类型分开选择音效风格，测试按钮用于快速确认映射是否顺耳。",
        )
        self.grenade_enabled_checkbox = QCheckBox("启用投掷物音效")
        self.grenade_enabled_checkbox.setChecked(bool(config.grenade_sound_enabled))
        self.grenade_enabled_checkbox.toggled.connect(self._on_grenade_enabled_toggled)
        header_layout.addWidget(self.grenade_enabled_checkbox)
        self.grenade_summary_label = self._create_summary_label()
        header_layout.addWidget(self.grenade_summary_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)

        # UP-100: 同 `_create_round_tab`——头部卡进滚动区。这一档的头部卡最小高 125px
        # （1.25 档 139px），滚动区视口被挤到 103px，内容 652px。
        scroll_layout.addWidget(header_card)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.grenade_grid = grid

        grenade_styles = getattr(self.audio_manager, "grenade_sound_styles", {})
        for index, (grenade_type, display_name) in enumerate(self.GRENADE_TYPES.items()):
            row = QFrame()
            row.setObjectName("card")
            row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(8)

            name_label = QLabel(display_name)
            name_label.setObjectName("statusLabel")
            row_layout.addWidget(name_label)

            controls_row = QHBoxLayout()
            controls_row.setContentsMargins(0, 0, 0, 0)
            controls_row.setSpacing(8)

            combo = QComboBox()
            combo.addItem("不启用", "0")
            for style in grenade_styles.get(grenade_type, []):
                combo.addItem(style, style)
            combo.setMinimumWidth(220)
            self._set_compact_heights(combo)
            combo.currentIndexChanged.connect(
                lambda _idx, g=grenade_type: self._on_grenade_style_changed(g)
            )
            controls_row.addWidget(combo, 1)

            test_btn = QPushButton("测试")
            test_btn.setObjectName("secondaryButton")
            test_btn.setFixedWidth(80)
            self._set_compact_heights(test_btn)
            test_btn.clicked.connect(lambda _checked=False, g=grenade_type: self._test_grenade_sound(g))
            controls_row.addWidget(test_btn, 0)

            row_layout.addLayout(controls_row)
            self.grenade_cards.append(row)
            self.grenade_combos[grenade_type] = combo

        self._apply_responsive_grid(grid, self.grenade_cards, self._responsive_columns_for_cards(len(self.grenade_cards)))
        scroll_layout.addLayout(grid)
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        self.tab_widget.addTab(tab, "投掷物")

    def _create_c4_tab(self):
        """C4 页签。

        UP-081（R10 复核纠正）：登记册原写的是「血量警告页签没有滚动区」——
        那条**早就修好了**（见 `_create_health_tab` 的注释），四个页签里真正
        没有滚动区的是这一个。当前排版审计全绿，因为这页内容确实少
        （一张卡：复选框 + 摘要 + 一行下拉），所以它是**潜伏风险**不是活缺陷。
        补上的理由与 `_create_health_tab` 当年一样：余量薄的地方，
        任何文案变长都会翻车，而文案是最常改的东西。
        """
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        tab_scroll = QScrollArea()
        tab_scroll.setWidgetResizable(True)
        tab_scroll.setFrameShape(QFrame.NoFrame)
        tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        card, card_layout = SettingsCard.make(
            "C4 音效",
            "安放、拆除、爆炸各配一个音效；三者共用同一个风格目录，靠文件名区分。",
        )
        self.c4_enabled_checkbox = QCheckBox("启用 C4 音效")
        self.c4_enabled_checkbox.setChecked(bool(config.c4_sound_enabled))
        self.c4_enabled_checkbox.toggled.connect(self._on_c4_enabled_toggled)
        card_layout.addWidget(self.c4_enabled_checkbox)
        self.c4_summary_label = self._create_summary_label()
        card_layout.addWidget(self.c4_summary_label)

        naming_hint = QLabel(
            "拆除和爆炸靠文件名认素材：文件名里带「拆除 / defuse」「爆炸 / explode」才会被选中，"
            "认不出来就保持安静——不会拿安放的音效顶替。"
        )
        naming_hint.setObjectName("hintLabel")
        naming_hint.setWordWrap(True)
        card_layout.addWidget(naming_hint)

        for event in self.C4_EVENTS:
            row, row_layout = self._row_card()

            name_label = QLabel(event.label)
            name_label.setFont(QFont("Microsoft YaHei", 12))
            name_label.setMinimumWidth(120)
            row_layout.addWidget(name_label)

            combo = QComboBox()
            combo.addItem("不启用", "0")
            for style in getattr(self.audio_manager, "c4_sound_styles", []):
                combo.addItem(style, style)
            combo.setMinimumWidth(220)
            self._set_compact_heights(combo)
            combo.currentIndexChanged.connect(
                lambda _idx, e=event: self._on_c4_style_changed(e)
            )
            row_layout.addWidget(combo, 1)

            test_btn = QPushButton("测试")
            test_btn.setObjectName("secondaryButton")
            test_btn.setFixedWidth(80)
            self._set_compact_heights(test_btn)
            test_btn.clicked.connect(lambda _checked=False, e=event: self._test_c4_sound(e))
            row_layout.addWidget(test_btn)
            card_layout.addWidget(row)
            self.c4_combos[event.key] = combo

        # 老属性名保留：放大镜页等处按名字读它
        self.c4_style_combo = self.c4_combos["planted"]
        layout.addWidget(card)
        layout.addStretch()

        tab_scroll.setWidget(content)
        outer.addWidget(tab_scroll)

        self.tab_widget.addTab(tab, "C4")

    def _create_health_tab(self):
        # UP-081: 这个页签原本**整个没有滚动区**（`addWidget(card)` + `addStretch()` 到底），
        # 与 UP-071 的 about/death_sound/utility 同类。当前不溢出，但纵向余量只有几十
        # 像素——R8-W5 期间一次让摘要多折一行的改动就把它顶出可视区 39px。
        # 余量这么薄本身就是缺陷：任何文案变长都会触发，而文案是最常改的东西。
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        tab_scroll = QScrollArea()
        tab_scroll.setWidgetResizable(True)
        tab_scroll.setFrameShape(QFrame.NoFrame)
        tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tab_body = QWidget()
        layout = QVBoxLayout(tab_body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        card, card_layout = SettingsCard.make(
            "血量警告",
            "把阈值和提示音效放在同一组里，方便边调触发线边试听警告强度。",
        )
        self.health_enabled_checkbox = QCheckBox("启用低血量警告")
        self.health_enabled_checkbox.setChecked(bool(config.health_warning_enabled))
        self.health_enabled_checkbox.toggled.connect(self._on_health_enabled_toggled)
        card_layout.addWidget(self.health_enabled_checkbox)
        self.health_summary_label = self._create_summary_label()
        card_layout.addWidget(self.health_summary_label)

        threshold_row, threshold_layout = self._row_card()

        threshold_label = QLabel("触发阈值")
        threshold_label.setFont(QFont("Microsoft YaHei", 12))
        threshold_label.setMinimumWidth(100)
        threshold_layout.addWidget(threshold_label)

        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(5, 50)
        self.threshold_slider.setValue(int(config.health_warning_threshold))
        self.threshold_slider.valueChanged.connect(self._on_threshold_changed)
        threshold_layout.addWidget(self.threshold_slider)

        self.threshold_value_label = QLabel(str(self.threshold_slider.value()))
        self.threshold_value_label.setMinimumWidth(50)
        self.threshold_value_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        threshold_layout.addWidget(self.threshold_value_label)

        style_row, style_layout = self._row_card()

        name_label = QLabel("警告音效")
        name_label.setFont(QFont("Microsoft YaHei", 12))
        name_label.setMinimumWidth(100)
        style_layout.addWidget(name_label)

        self.health_style_combo = QComboBox()
        self.health_style_combo.addItem("不启用", "0")
        for style in getattr(self.audio_manager, "health_warning_styles", []):
            self.health_style_combo.addItem(style, style)
        self.health_style_combo.setMinimumWidth(220)
        self._set_compact_heights(self.health_style_combo)
        self.health_style_combo.currentIndexChanged.connect(self._on_health_style_changed)
        style_layout.addWidget(self.health_style_combo, 1)

        test_btn = QPushButton("测试")
        test_btn.setObjectName("secondaryButton")
        test_btn.setFixedWidth(80)
        self._set_compact_heights(test_btn)
        test_btn.clicked.connect(self._test_health_warning)
        style_layout.addWidget(test_btn)

        cooldown_row, cooldown_layout = self._row_card()

        cooldown_label = QLabel("再次提醒间隔")
        cooldown_label.setFont(QFont("Microsoft YaHei", 12))
        cooldown_label.setMinimumWidth(100)
        cooldown_layout.addWidget(cooldown_label)

        # 以前这个值写死在 gsi_handler_special 里（5 秒），嫌吵和嫌少的都改不了
        self.cooldown_slider = QSlider(Qt.Horizontal)
        self.cooldown_slider.setRange(1, 30)
        self.cooldown_slider.setValue(int(float(getattr(config, "health_warning_cooldown", 5.0))))
        self.cooldown_slider.setToolTip("触发一次低血量警告后，至少隔这么久才会再响一次")
        self.cooldown_slider.valueChanged.connect(self._on_cooldown_changed)
        cooldown_layout.addWidget(self.cooldown_slider)

        self.cooldown_value_label = QLabel(f"{self.cooldown_slider.value()} 秒")
        self.cooldown_value_label.setMinimumWidth(50)
        self.cooldown_value_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        cooldown_layout.addWidget(self.cooldown_value_label)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(10)
        content_row.addWidget(threshold_row, 1)
        content_row.addWidget(style_row, 1)
        card_layout.addLayout(content_row)
        card_layout.addWidget(cooldown_row)
        layout.addWidget(card)
        layout.addStretch()

        tab_scroll.setWidget(tab_body)
        outer.addWidget(tab_scroll)
        self.tab_widget.addTab(tab, "血量警告")

    def _create_round_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        header_card, header_layout = SettingsCard.make(
            "回合音效",
            "把启用开关和总音量固定在上方，下面集中管理各阶段风格，便于快速试一整套节奏。",
        )
        self.round_enabled_checkbox = QCheckBox("启用回合音效")
        self.round_enabled_checkbox.setChecked(bool(config.round_sound_enabled))
        self.round_enabled_checkbox.toggled.connect(self._on_round_enabled_toggled)
        header_layout.addWidget(self.round_enabled_checkbox)
        self.round_summary_label = self._create_summary_label()
        header_layout.addWidget(self.round_summary_label)

        volume_row, volume_layout = self._row_card()

        volume_label = QLabel("回合音效音量")
        volume_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        volume_label.setMinimumWidth(140)
        volume_layout.addWidget(volume_label)

        self.round_volume_slider = QSlider(Qt.Horizontal)
        self.round_volume_slider.setRange(0, 100)
        self.round_volume_slider.setValue(int(float(config.round_sound_volume) * 100))
        self.round_volume_slider.valueChanged.connect(self._on_round_volume_changed)
        volume_layout.addWidget(self.round_volume_slider)

        self.round_volume_label = QLabel(f"{self.round_volume_slider.value()}%")
        self.round_volume_label.setMinimumWidth(55)
        self.round_volume_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        volume_layout.addWidget(self.round_volume_label)

        header_layout.addWidget(volume_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)

        # UP-100/UP-081②: 头部卡原本 `layout.addWidget(header_card)` 钉在滚动区**外面**。
        # 完整模式下看不出问题（可视 750px 富余），紧凑模式（860×640）下页签内容区
        # 只剩 186px，而这张头部卡自己的最小高就是 169px（1.25 档 188px）——
        # 于是滚动区被挤成一个**视口只有 62px 的舷窗**，里面装着 542px 的内容。
        # 判据报的"超出 71px"读起来像"滚一下就好"，实际是没法用。
        #
        # 改法与本文件里 `_create_c4_tab` / `_create_health_tab` 一致：整个页签
        # 只留一个滚动区，头部卡也进去。代价是窄窗口下往下滚时启用开关和总音量
        # 会滚出视野——但对照"62px 舷窗"，这个代价是划算的，而且完整模式下
        # 高度富余、根本不会滚，观感不变。
        scroll_layout.addWidget(header_card)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.round_grid = grid

        for index, (round_type, (display_name, manager_attr, config_attr)) in enumerate(self.ROUND_TYPE_META.items()):
            row = QFrame()
            row.setObjectName("card")
            row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(8)

            name_label = QLabel(display_name)
            name_label.setObjectName("statusLabel")
            row_layout.addWidget(name_label)

            controls_row = QHBoxLayout()
            controls_row.setContentsMargins(0, 0, 0, 0)
            controls_row.setSpacing(8)

            combo = QComboBox()
            combo.addItem("不启用", "0")
            for style in getattr(self.audio_manager, manager_attr, []):
                combo.addItem(style, style)
            combo.setMinimumWidth(220)
            self._set_compact_heights(combo)
            combo.currentIndexChanged.connect(
                lambda _idx, rt=round_type, ca=config_attr: self._on_round_style_changed(rt, ca)
            )
            controls_row.addWidget(combo, 1)

            test_btn = QPushButton("测试")
            test_btn.setObjectName("secondaryButton")
            test_btn.setFixedWidth(80)
            self._set_compact_heights(test_btn)
            test_btn.clicked.connect(lambda _checked=False, rt=round_type: self._test_round_sound(rt))
            controls_row.addWidget(test_btn, 0)

            row_layout.addLayout(controls_row)
            self.round_cards.append(row)
            self.round_combos[round_type] = combo

        self._apply_responsive_grid(grid, self.round_cards, self._responsive_columns_for_cards(len(self.round_cards)))
        scroll_layout.addLayout(grid)
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        self.tab_widget.addTab(tab, "回合")

    def _on_grenade_enabled_toggled(self, checked):
        config.grenade_sound_enabled = bool(checked)
        self._save_config()
        self._refresh_status_badge()
        self.logger.info(f"投掷物音效: {'启用' if checked else '禁用'}")

    def _on_grenade_style_changed(self, grenade_type):
        combo = self.grenade_combos.get(grenade_type)
        if combo is None:
            return
        style = combo.currentData()
        config.grenade_sound_styles[grenade_type] = style
        self._save_config()
        self._refresh_status_badge()
        self.logger.info(f"{grenade_type} 样式已更新: {style}")

    def _test_grenade_sound(self, grenade_type):
        style = config.grenade_sound_styles.get(grenade_type, "0")
        if style == "0":
            self.logger.info(f"{grenade_type} 当前未启用音效")
            return

        sound_key = f"grenade-{grenade_type}-{style}"
        self.logger.info(f"测试投掷物音效: {sound_key}")
        self.audio_manager.play_sound(sound_key, channel_type="grenade_sound")

    def _on_c4_enabled_toggled(self, checked):
        config.c4_sound_enabled = bool(checked)
        self._save_config()
        self._refresh_status_badge()
        self.logger.info(f"C4 音效: {'启用' if checked else '禁用'}")

    def _on_c4_style_changed(self, event):
        combo = self.c4_combos.get(event.key)
        if combo is None:
            return
        style = combo.currentData()
        setattr(config, event.config_attr, style)
        self._save_config()
        self._refresh_status_badge()
        self.logger.info(f"{event.label}样式已更新: {style}")

    def _test_c4_sound(self, event=None):
        event = event or self.C4_EVENTS[0]
        style = getattr(config, event.config_attr, "0")
        if style == "0":
            self.logger.info(f"{event.label}当前未启用音效")
            return

        key = sound_key(event, style)
        self.logger.info(f"测试 {event.label}: {key}")
        # 拆除/爆炸可能在这个风格目录里找不到对应文件——那时 play_sound 会返回
        # False 并记一条 drop。这正是设计：宁可不响也不拿安放的音效顶替。
        if not self.audio_manager.play_sound(key, channel_type="c4_sound"):
            self.logger.info(
                f"{event.label}没有匹配的素材（文件名需含 {' / '.join(event.filename_tokens[:2])}）"
            )

    def _on_health_enabled_toggled(self, checked):
        config.health_warning_enabled = bool(checked)
        self._save_config()
        self._refresh_status_badge()
        self.logger.info(f"血量警告: {'启用' if checked else '禁用'}")

    def _on_threshold_changed(self, value):
        config.health_warning_threshold = int(value)
        self.threshold_value_label.setText(str(value))
        self._save_config()
        self._refresh_status_badge()
        self.logger.info(f"血量阈值已更新: {value}")

    def _on_cooldown_changed(self, value):
        config.health_warning_cooldown = float(value)
        self.cooldown_value_label.setText(f"{value} 秒")
        self._save_config()
        self._refresh_status_badge()
        self.logger.info(f"血量警告冷却已更新: {value}s")

    def _on_health_style_changed(self, _index):
        style = self.health_style_combo.currentData()
        config.health_warning_style = style
        self._save_config()
        self._refresh_status_badge()
        self.logger.info(f"血量警告样式已更新: {style}")

    def _test_health_warning(self):
        style = getattr(config, "health_warning_style", "0")
        if style == "0":
            self.logger.info("血量警告当前未启用音效")
            return

        sound_key = f"health-warning-{style}"
        self.logger.info(f"测试血量警告音效: {sound_key}")
        self.audio_manager.play_sound(sound_key, channel_type="health_warning")

    def _on_round_enabled_toggled(self, checked):
        config.round_sound_enabled = bool(checked)
        self._save_config()
        self._refresh_status_badge()
        self.logger.info(f"回合音效: {'启用' if checked else '禁用'}")

    def _on_round_volume_changed(self, value):
        config.round_sound_volume = max(0.0, min(float(value) / 100.0, 1.0))
        self.round_volume_label.setText(f"{value}%")
        self._save_config()
        self._refresh_status_badge()
        self.logger.info(f"回合音效音量已更新: {value}%")

    def _on_round_style_changed(self, round_type, config_attr):
        combo = self.round_combos.get(round_type)
        if combo is None:
            return

        style = combo.currentData()
        setattr(config, config_attr, style)
        self._save_config()
        self._refresh_status_badge()
        self.logger.info(f"{round_type} 音效样式已更新: {style}")

    def _test_round_sound(self, round_type):
        meta = self.ROUND_TYPE_META.get(round_type)
        if not meta:
            return

        _display_name, _manager_attr, config_attr = meta
        style = getattr(config, config_attr, "0")
        if style == "0":
            self.logger.info(f"{round_type} 当前未启用音效")
            return

        sound_key = f"round-{round_type}-{style}"
        self.logger.info(f"测试回合音效: {sound_key}")
        self.audio_manager.play_sound(sound_key, channel_type="round_sound")

    def load_settings(self):
        for grenade_type, combo in self.grenade_combos.items():
            style = config.grenade_sound_styles.get(grenade_type, "0")
            self._set_combo_data(combo, style)

        for event in self.C4_EVENTS:
            combo = self.c4_combos.get(event.key)
            if combo is not None:
                self._set_combo_data(combo, getattr(config, event.config_attr, "0"))
        self._set_combo_data(self.health_style_combo, getattr(config, "health_warning_style", "0"))

        for round_type, (_display_name, _manager_attr, config_attr) in self.ROUND_TYPE_META.items():
            combo = self.round_combos.get(round_type)
            if combo is None:
                continue
            self._set_combo_data(combo, getattr(config, config_attr, "0"))
        self._refresh_status_badge()

        self.logger.info("特殊音效设置加载完成")

    def _refresh_status_badge(self):
        enabled_modules = self._count_enabled_modules()
        selected_count = count_enabled_styles(self._collect_style_values())
        grenade_selected = count_enabled_styles((config.grenade_sound_styles or {}).values())
        grenade_available = sum(
            len(styles)
            for styles in getattr(self.audio_manager, "grenade_sound_styles", {}).values()
        )
        round_selected = count_enabled_styles(
            [
                getattr(config, "round_start_style", "0"),
                getattr(config, "round_action_style", "0"),
                getattr(config, "round_win_style", "0"),
                getattr(config, "round_lose_style", "0"),
                getattr(config, "round_mvp_style", "0"),
            ]
        )
        round_volume = int(round(float(getattr(config, "round_sound_volume", 1.0)) * 100))
        health_threshold = int(getattr(config, "health_warning_threshold", 20))

        health = collect_category_health(("grenade_sounds", "c4_sounds", "health_warning", "round_sounds"))
        detail_tooltip = build_health_detail_tooltip(health)
        health_level = "success"
        if not health["ok"]:
            health_level = "danger"
        elif health["empty"]:
            health_level = "warn"

        badges = [
            ("success" if enabled_modules else "warn", f"模块 · {enabled_modules}/4"),
            ("success" if selected_count else "info", f"样式 · {selected_count}"),
            (
                "success" if getattr(config, "round_sound_enabled", False) else "info",
                f"回合音量 · {round_volume}%",
            ),
            (
                health_level,
                "资源 · 正常"
                if health["ok"]
                else f"资源 · 异常 {health['issue_count']}",
            ),
        ]
        detail_lines = [
            (
                f"投掷物：{'已启用' if getattr(config, 'grenade_sound_enabled', False) else '已关闭'}，"
                f"已选 {grenade_selected}/{len(self.GRENADE_TYPES)}"
            ),
            (
                f"C4：{'已启用' if getattr(config, 'c4_sound_enabled', False) else '已关闭'}，"
                f"样式 {self._style_summary(getattr(config, 'c4_sound_style', '0'))}"
            ),
            (
                f"低血量：{'已启用' if getattr(config, 'health_warning_enabled', False) else '已关闭'}，"
                f"阈值 {health_threshold}，"
                f"样式 {self._style_summary(getattr(config, 'health_warning_style', '0'))}"
            ),
            (
                f"回合：{'已启用' if getattr(config, 'round_sound_enabled', False) else '已关闭'}，"
                f"音量 {round_volume}%，已选 {round_selected}/{len(self.ROUND_TYPE_META)}"
            ),
        ]
        if detail_tooltip:
            detail_lines.append(detail_tooltip)

        summary_text = "\n".join(detail_lines)
        render_badges(self.status_badge_label, badges, detail_tooltip=summary_text)
        self.summary_label.setText(summary_text)
        self.summary_label.setToolTip(summary_text)
        self.status_card.setToolTip(summary_text)
        if hasattr(self, "grenade_summary_label"):
            self.grenade_summary_label.setText(
                f"当前已选 {grenade_selected}/{len(self.GRENADE_TYPES)} 类 · "
                f"{'模块已启用' if getattr(config, 'grenade_sound_enabled', False) else '模块已关闭'} · "
                f"可用风格 {grenade_available} 个"
            )
            self.grenade_summary_label.setToolTip(summary_text)
        if hasattr(self, "c4_summary_label"):
            self.c4_summary_label.setText(
                f"当前样式：{self._style_summary(getattr(config, 'c4_sound_style', '0'))} · "
                f"{'模块已启用' if getattr(config, 'c4_sound_enabled', False) else '模块已关闭'}"
            )
            self.c4_summary_label.setToolTip(summary_text)
        if hasattr(self, "health_summary_label"):
            self.health_summary_label.setText(
                f"阈值 {health_threshold} · "
                f"当前样式：{self._style_summary(getattr(config, 'health_warning_style', '0'))} · "
                f"{'模块已启用' if getattr(config, 'health_warning_enabled', False) else '模块已关闭'}"
            )
            self.health_summary_label.setToolTip(summary_text)
        if hasattr(self, "round_summary_label"):
            self.round_summary_label.setText(
                f"音量 {round_volume}% · 已选 {round_selected}/{len(self.ROUND_TYPE_META)} · "
                f"{'模块已启用' if getattr(config, 'round_sound_enabled', False) else '模块已关闭'}"
            )
            self.round_summary_label.setToolTip(summary_text)
        if hasattr(self, "action_bar") and hasattr(self, "tab_widget"):
            current_tab = self.tab_widget.tabText(self.tab_widget.currentIndex()) if self.tab_widget.count() else "特殊音效"
            if current_tab == "投掷物":
                action_message = f"当前标签：{current_tab} · 已选 {grenade_selected}/{len(self.GRENADE_TYPES)}，新增素材后可直接刷新风格列表。"
            elif current_tab == "C4":
                action_message = f"当前标签：{current_tab} · 样式 {self._style_summary(getattr(config, 'c4_sound_style', '0'))}。"
            elif current_tab == "血量警告":
                threshold = int(getattr(config, "health_warning_threshold", 20))
                action_message = f"当前标签：{current_tab} · 阈值 {threshold}，样式 {self._style_summary(getattr(config, 'health_warning_style', '0'))}。"
            elif current_tab == "回合":
                action_message = f"当前标签：{current_tab} · 音量 {round_volume}%，已选 {round_selected}/{len(self.ROUND_TYPE_META)}。"
            else:
                action_message = "新增素材后可直接刷新风格列表，底部快捷入口会按当前标签页打开对应资源目录。"
            self.action_bar.set_message(action_message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_responsive_grids()
