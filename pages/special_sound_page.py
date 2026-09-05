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
    create_badge_label,
    render_badges,
    resolve_style,
    resource_badge,
    resource_hint,
)
from widgets.preview_feedback import PreviewFailure, report_preview_failure
from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
from widgets.page_header import PageHeader


#: RN-519：卡片说明要点名这颗按钮，而说明比按钮先建 —— 名字只留一份。
#: ⚠ 这一页有 4 颗同名的「测试」（四种投掷物各一颗），更不能各抄一份。
TEST_BUTTON_TEXT = "测试"


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

    # ── RN-046：三个口径统一到这一处 ───────────────────────────────────
    # 原状（探针实测，8 个回合事件全配上一个已删除的风格）：
    #
    #   回合摘要   「已选 5/8」          ← 分子手写 5 个字段、且数的是原始值
    #   八行下拉框 全是「不启用」        ← `findData` 找不到就退回第 0 项
    #
    # 两个错叠在一起：**分子上限 5、分母 8**（分母 `len(ROUND_TYPE_META)` 是
    # 从事件表派生的，2.2.4 加的 比赛开始/比赛结束/半场交换 只进了分母），
    # 外加 RN-026 那个"数原始值"的老病。
    # `core/audio/special_events` 的 docstring 开篇讲的就是"别再有第二份手写
    # 清单"，而徽章代码里躺着的正是第二份。

    def _available_styles(self, attr_or_grenade: str, *, grenade=False) -> list:
        if grenade:
            return (getattr(self.audio_manager, "grenade_sound_styles", {})
                    or {}).get(attr_or_grenade, []) or []
        return getattr(self.audio_manager, attr_or_grenade, []) or []

    def _effective_grenade_styles(self) -> dict:
        raw = config.grenade_sound_styles or {}
        return {g: resolve_style(raw.get(g, "0"), self._available_styles(g, grenade=True))
                for g in self.GRENADE_TYPES}

    def _effective_round_styles(self) -> dict:
        """回合各事件真正生效的风格。**键来自事件表，不是手写清单。**"""
        return {
            key: resolve_style(getattr(config, config_attr, "0"),
                               self._available_styles(manager_attr))
            for key, (_label, manager_attr, config_attr) in self.ROUND_TYPE_META.items()
        }

    def _effective_c4_styles(self) -> dict:
        available = self._available_styles("c4_sound_styles")
        return {event.key: resolve_style(getattr(config, event.config_attr, "0"), available)
                for event in self.C4_EVENTS}

    def _effective_health_style(self) -> str:
        return resolve_style(getattr(config, "health_warning_style", "0"),
                             self._available_styles("health_warning_styles"))

    @staticmethod
    def _selected(effective: dict) -> int:
        return sum(1 for value in effective.values() if value != "0")

    def _stale_total(self) -> int:
        """配过、但风格已经不在了的项数（四类合计）。"""
        raw_grenade = config.grenade_sound_styles or {}
        pairs = [(raw_grenade.get(g, "0"), v)
                 for g, v in self._effective_grenade_styles().items()]
        pairs += [(getattr(config, self.ROUND_TYPE_META[k][2], "0"), v)
                  for k, v in self._effective_round_styles().items()]
        pairs += [(getattr(config, e.config_attr, "0"), self._effective_c4_styles()[e.key])
                  for e in self.C4_EVENTS]
        pairs.append((getattr(config, "health_warning_style", "0"),
                      self._effective_health_style()))
        return sum(1 for configured, effective in pairs
                   if str(configured or "0").strip() not in ("", "0") and effective == "0")

    def _style_summary(self, style_value):
        if str(style_value or "").strip() == "0":
            return "未启用"
        return self._compact_text(style_value, "未启用", 18)

    def _module_state_note(self, enabled: bool, selected: int) -> str:
        """这一类的开关状态；**选了风格却没勾开关时额外挑明**。

        RN-051：这一页有**两层开关**（模块复选框 + 每一项的「不启用」）。
        外审 8 发截图里 4 发独立报「双重开关逻辑冲突，玩家容易只选下拉项而
        遗漏总开关，导致局内不生效」。加控件会让事情更复杂；
        真正缺的是**把当前状态说清楚**。

        ⚠ 第一版我写成"只在配了却没开时才说话"，其余情况返回空串 ——
        于是"模块已关闭且什么都没配"这个状态**一个字都没有了**，
        而原来的文案是会说「模块已关闭」的。
        既有判据 `test_special_sound_page_status_card_tracks_threshold_and_volume`
        当场逮住。⇒ **收敛文案时先问"原来说的哪句话被我弄没了"。**
        """
        if enabled:
            return " · 模块已启用"
        if selected:
            return " · 模块已关闭（配了也不会响）"
        return " · 模块已关闭"

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

    def _collect_effective_styles(self) -> list:
        """全页每一项**真正生效**的风格值。

        RN-046：原来这里收的是配置里的原始值（`config_defaults()` 的键逐个
        `getattr`），于是「样式 · N」这颗徽章数出来的 N 和屏幕上每一行显示的
        「不启用」永久对不上。
        """
        values = list(self._effective_grenade_styles().values())
        values.extend(self._effective_round_styles().values())
        values.extend(self._effective_c4_styles().values())
        values.append(self._effective_health_style())
        return values


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

        # RN-180：空库时的第一步放在状态卡正下方 —— 那一片置灰控件的上方，
        # 也就是困惑发生的位置。放底栏等于没放（CLAUDE.md 那条我自己写下又没照做的）。
        from widgets.community_library import EmptyLibraryCallout

        self.empty_callout = EmptyLibraryCallout(self)
        main_layout.addWidget(self.empty_callout.frame)

        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self._refresh_status_badge)
        main_layout.addWidget(self.tab_widget, 1)

        self._create_grenade_tab()
        self._create_c4_tab()
        self._create_health_tab()
        self._create_round_tab()

        self.action_bar = PageActionBar(self)
        # RN-165：记下 extra 的原样，空库态要借用这个位置。
        self._extra_default = (self.action_bar.extra_btn.text(),
                               self.action_bar._extra_callback,
                               self.action_bar.extra_btn.menu())
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
            f"每种投掷物各选一个风格，点「{TEST_BUTTON_TEXT}」就能听到实际效果。",
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

            test_btn = QPushButton(TEST_BUTTON_TEXT)
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

            test_btn = QPushButton(TEST_BUTTON_TEXT)
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
            "血量掉到设定值以下时提醒你一声。阈值和提醒间隔都可以自己调。",
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

        test_btn = QPushButton(TEST_BUTTON_TEXT)
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

        # RN-055：三行同级设置项原来是「两行并排半宽 + 一行通栏」，
        # 外审 S3 报「触发阈值与警告音效带独立边框包裹，而同级的再次提醒间隔
        # 通栏拉伸，容器样式与排版结构不一致」。
        # 核实：三行**都是** `_row_card()`（同一个 `QFrame#card`），
        # 所以"无边框"那半句是错的 —— 但**现象是真的**：同一层级的三个东西，
        # 两个半宽一个通栏，读起来像分了组，而它们并没有分组。
        # ⚠ 第一版我改成**三行等宽通栏**，容器是一致了，但卡片高了一行 ——
        # 改完复跑外审，紧凑档（860×640）当场报「警告音效下拉框与测试按钮
        # 被卡片容器底边截断」（高），而改之前紧凑档这一页是 NONE。
        # ⇒ **我用一个「中」换来了一个「高」，是笔亏本的交易。**
        #
        # 现在的改法不加高度：把**两个滑块**（阈值 / 间隔，同一类东西）并排，
        # 「选风格 + 试听」通栏单独一行。行数和原来一样是 2，
        # 而分组从"两个不同类的东西并排"变成"两个同类的东西并排" ——
        # 外审那条抱怨的根子是**视觉分组和语义分组不一致**，不是边框本身。
        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.setSpacing(10)
        slider_row.addWidget(threshold_row, 1)
        slider_row.addWidget(cooldown_row, 1)
        card_layout.addLayout(slider_row)
        card_layout.addWidget(style_row)
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
            "回合开始、结束、MVP 等时刻各播一段音效。逐项选风格，音量统一由上面这一条控制。",
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

            test_btn = QPushButton(TEST_BUTTON_TEXT)
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

    # ── RN-047：四个「测试」按钮原来都是"只写一行日志就 return" ─────────
    # 用户看到的是**点了没反应** —— 分不清是没配、文件没了，还是软件坏了。
    # UP-037 那一轮把其余各页都改了，这一页四个出口一个没改。
    # ⭐ 外审 8 发截图里 7 发独立报「测试按钮点击无反应易被误认为软件故障」。
    #   上一轮我把这类判成「现象真但机制已缓解（点了会给 toast）」——
    #   那个裁定对**有 toast 的页**成立，对这一页不成立。
    #   ⇒ 「已经修过」是按页成立的，不是按缺陷类型成立的。

    def _report_preview(self, configured: str, effective: str, label: str) -> bool:
        """没得播就报出来，返回 True 表示"已经报了、别再往下走"。"""
        if str(configured or "0").strip() in ("", "0"):
            report_preview_failure(self, PreviewFailure.NO_STYLE, label)
            return True
        if effective == "0":
            report_preview_failure(self, PreviewFailure.STALE_STYLE,
                                   f"{label} · {configured}")
            return True
        return False

    def _test_grenade_sound(self, grenade_type):
        configured = (config.grenade_sound_styles or {}).get(grenade_type, "0")
        style = self._effective_grenade_styles().get(grenade_type, "0")
        label = self.GRENADE_TYPES.get(grenade_type, grenade_type)
        if self._report_preview(configured, style, label):
            return

        sound_key = f"grenade-{grenade_type}-{style}"
        self.logger.info(f"测试投掷物音效: {sound_key}")
        if not self.audio_manager.play_sound(sound_key, channel_type="grenade_sound"):
            report_preview_failure(self, PreviewFailure.NO_FILE, f"{label} · {style}")

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
        configured = getattr(config, event.config_attr, "0")
        style = self._effective_c4_styles().get(event.key, "0")
        if self._report_preview(configured, style, event.label):
            return

        key = sound_key(event, style)
        self.logger.info(f"测试 {event.label}: {key}")
        # 拆除/爆炸可能在这个风格目录里找不到对应文件——那时 play_sound 会返回
        # False 并记一条 drop。这正是设计：宁可不响也不拿安放的音效顶替。
        # 但"设计上不响"也必须**说给用户听**：原来这里只写日志，
        # 于是用户点了拆除的测试、什么都没发生、也不知道该去改文件名。
        if not self.audio_manager.play_sound(key, channel_type="c4_sound"):
            report_preview_failure(
                self, PreviewFailure.NO_FILE,
                f"{event.label} · 风格「{style}」里没有文件名含 "
                f"{' / '.join(event.filename_tokens[:2])} 的音频")

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
        configured = getattr(config, "health_warning_style", "0")
        style = self._effective_health_style()
        if self._report_preview(configured, style, "低血量警告"):
            return

        sound_key = f"health-warning-{style}"
        self.logger.info(f"测试血量警告音效: {sound_key}")
        if not self.audio_manager.play_sound(sound_key, channel_type="health_warning"):
            report_preview_failure(self, PreviewFailure.NO_FILE, f"低血量警告 · {style}")

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

        display_name, _manager_attr, config_attr = meta
        configured = getattr(config, config_attr, "0")
        style = self._effective_round_styles().get(round_type, "0")
        if self._report_preview(configured, style, display_name):
            return

        sound_key = f"round-{round_type}-{style}"
        self.logger.info(f"测试回合音效: {sound_key}")
        if not self.audio_manager.play_sound(sound_key, channel_type="round_sound"):
            report_preview_failure(self, PreviewFailure.NO_FILE,
                                   f"{display_name} · {style}")

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

    #: 这一页在社区站的资源分类（RN-165，机制与 RN-153 的音效家族四页同源）。
    COMMUNITY_CATEGORY_KEY = "special_sound"

    def _library_is_empty(self) -> bool:
        """四大类（投掷物 / 回合 / C4 / 血量）**一个可用风格都没有**才叫空库。

        ⚠ 「没配」是用户的选择，「没得配」是软件不带素材 ——
        两者的修法完全相反：没配 ⇒ 去配；没得配 ⇒ 先去拿素材。
        """
        families = [self._available_styles(g, grenade=True)
                    for g in self.GRENADE_TYPES]
        families += [self._available_styles(meta[1])
                     for meta in self.ROUND_TYPE_META.values()]
        families.append(self._available_styles("c4_sound_styles"))
        families.append(self._available_styles("health_warning_styles"))
        return not any(families)

    def _sync_community_guidance(self) -> None:
        """空库时把底栏换成一条走得通的路（RN-165）。

        ⭐ **"打开一个空文件夹"不是一条路** —— 用户手上没有文件。
        空了该长什么样**全仓只有一份**（`widgets/community_library`）：
        这一页只回答「我空不空」，不自己决定空状态的样子。
        """
        bar = getattr(self, "action_bar", None)
        if bar is None:
            return
        from widgets import community_library

        # RN-179：先把「没得选」的下拉框和它那一行的试听按钮置灰。
        # ⚠ 放在 `guide_empty_library` **之前**：置灰与"这个发行版有没有社区站"无关，
        # 而那个函数在没有社区站时会直接回 False、走另一条分支。
        community_library.dim_controls_with_nothing_to_pick(
            self, reason=community_library.dim_reason("风格"))

        applied = community_library.guide_empty_library(
            bar,
            empty=self._library_is_empty(),
            category_key=self.COMMUNITY_CATEGORY_KEY,
            cta_text="去社区拿一套特殊音效",
            keep_text="打开当前资源",
            keep_callback=self._open_current_resource_root,
            message=community_library.empty_library_message("风格"),
            callout=getattr(self, "empty_callout", None),   # RN-180
            what="风格",
            refresh_label="刷新风格列表",
        )
        if not applied:
            # ⚠ **借了要还**：空库态借用了 extra 那个位置。
            bar.configure_primary("打开当前资源", self._open_current_resource_root,
                                  visible=True)
            text, callback, menu = getattr(
                self, "_extra_default", ("新建风格", None, None))
            bar.configure_extra(text, callback, visible=True)
            bar.extra_btn.setMenu(menu)

    def _refresh_status_badge(self):
        enabled_modules = self._count_enabled_modules()

        grenade_on = bool(getattr(config, "grenade_sound_enabled", False))
        c4_on = bool(getattr(config, "c4_sound_enabled", False))
        health_on = bool(getattr(config, "health_warning_enabled", False))
        round_on = bool(getattr(config, "round_sound_enabled", False))

        grenade_effective = self._effective_grenade_styles()
        round_effective = self._effective_round_styles()
        c4_effective = self._effective_c4_styles()
        health_effective = self._effective_health_style()

        grenade_selected = self._selected(grenade_effective)
        round_selected = self._selected(round_effective)
        c4_selected = self._selected(c4_effective)
        selected_count = len([v for v in self._collect_effective_styles() if v != "0"])
        stale_count = self._stale_total()
        grenade_total = len(self.GRENADE_TYPES)
        round_total = len(self.ROUND_TYPE_META)
        c4_total = len(self.C4_EVENTS)

        grenade_available = sum(
            len(styles)
            for styles in (getattr(self.audio_manager, "grenade_sound_styles", {}) or {}).values()
        )
        round_volume = int(round(float(getattr(config, "round_sound_volume", 1.0)) * 100))
        health_threshold = int(getattr(config, "health_warning_threshold", 20))

        health = collect_category_health(("grenade_sounds", "c4_sounds", "health_warning", "round_sounds"))
        detail_tooltip = build_health_detail_tooltip(health)

        style_text = f"风格 · {selected_count}"
        if stale_count:
            style_level, style_text = "warn", f"{style_text} · {stale_count} 项失效"
        else:
            style_level = "success" if selected_count else "info"

        # RN-053：第三颗徽章跟着当前页签走。
        # 原状：无论在哪个页签上那颗都写着「回合音量 · 100%」——
        # 在「血量警告」页签上它跟屏幕上的东西毫无关系。
        # 外审两发独立报「将其他标签页的回合音量混在全局状态栏展示」。
        # `gun_sound` 的「分类 · …」徽章早就是跟页签走的，照它做。
        current_tab = (self.tab_widget.tabText(self.tab_widget.currentIndex())
                       if hasattr(self, "tab_widget") and self.tab_widget.count() else "")
        tab_badge = {
            "投掷物": (grenade_on and grenade_selected,
                     f"投掷物 · {grenade_selected}/{grenade_total}"),
            "C4": (c4_on and c4_selected, f"C4 · {c4_selected}/{c4_total}"),
            "血量警告": (health_on and health_effective != "0",
                       f"阈值 · {health_threshold}"),
            "回合": (round_on, f"回合音量 · {round_volume}%"),
        }.get(current_tab, (enabled_modules, f"模块 · {enabled_modules}/4"))

        badges = [
            ("success" if enabled_modules else "warn", f"模块 · {enabled_modules}/4"),
            (style_level, style_text),
            ("success" if tab_badge[0] else "info", tab_badge[1]),
            # RN-035：分级收进 `resource_badge()` 一份 —— 七个音效页原先各抄一遍
            # 这段，七份都把"素材目录还没建"（全新安装的样子）报成**红色异常**。
            resource_badge(health),
        ]
        detail_lines = [
            (f"投掷物：{'已启用' if grenade_on else '已关闭'}，"
             f"已选 {grenade_selected}/{grenade_total}"),
            (f"C4：{'已启用' if c4_on else '已关闭'}，"
             f"已选 {c4_selected}/{c4_total}"),
            (f"低血量：{'已启用' if health_on else '已关闭'}，"
             f"阈值 {health_threshold}，"
             f"风格 {self._style_summary(health_effective)}"),
            (f"回合：{'已启用' if round_on else '已关闭'}，"
             f"音量 {round_volume}%，已选 {round_selected}/{round_total}"),
        ]
        if stale_count:
            detail_lines.append(f"有 {stale_count} 项配的风格已经不在了")
        if detail_tooltip:
            detail_lines.append(detail_tooltip)

        summary_text = "\n".join(detail_lines)
        render_badges(self.status_badge_label, badges, detail_tooltip=summary_text)
        self.summary_label.setText(summary_text)
        self.summary_label.setToolTip(summary_text)
        self.status_card.setToolTip(summary_text)

        stale_note = (f"（有 {stale_count} 项配的风格已被改名或删除，"
                      "下面显示成「不启用」，重新选一个即可）") if stale_count else ""

        if hasattr(self, "grenade_summary_label"):
            self.grenade_summary_label.setText(
                f"当前已选 {grenade_selected}/{grenade_total} 类 · 可用风格 {grenade_available} 个"
                f"{self._module_state_note(grenade_on, grenade_selected)}"
            )
            self.grenade_summary_label.setToolTip(summary_text)
        if hasattr(self, "c4_summary_label"):
            # RN-054：原文写「当前样式：X」，而 X 只是**安放**那一个事件的风格
            # （`c4_sound_style` 是 planted 的 config_attr）。拆除/爆炸是 2.2.4
            # 新增的两个独立事件，它们配了什么这行字从来没说。
            self.c4_summary_label.setText(
                f"已选 {c4_selected}/{c4_total} 项"
                f"{self._module_state_note(c4_on, c4_selected)}"
            )
            self.c4_summary_label.setToolTip(summary_text)
        if hasattr(self, "health_summary_label"):
            self.health_summary_label.setText(
                f"阈值 {health_threshold} · 当前风格：{self._style_summary(health_effective)}"
                f"{self._module_state_note(health_on, 1 if health_effective != '0' else 0)}"
            )
            self.health_summary_label.setToolTip(summary_text)
        if hasattr(self, "round_summary_label"):
            self.round_summary_label.setText(
                f"音量 {round_volume}% · 已选 {round_selected}/{round_total}"
                f"{self._module_state_note(round_on, round_selected)}{stale_note}"
            )
            self.round_summary_label.setToolTip(summary_text)
        if hasattr(self, "action_bar"):
            # ⚠ RN-168：这里原来传 `open_label="打开当前资源"`（RN-056 的遗产）。
            # RN-153 把那句提示改成**不再点名任何按钮**之后，这个参数就没人读了，
            # 而它照样传了三批没人发现 —— 是回退验证判它假绿才暴露的。
            hint = resource_hint(health)
            if stale_count:
                action_message = (f"有 {stale_count} 项配的风格已经不在了，"
                                  "在对应行重新选一个即可。")
            elif hint:
                action_message = hint
            elif current_tab == "投掷物":
                action_message = f"当前标签：{current_tab} · 已选 {grenade_selected}/{grenade_total}。"
            elif current_tab == "C4":
                action_message = f"当前标签：{current_tab} · 已选 {c4_selected}/{c4_total}。"
            elif current_tab == "血量警告":
                action_message = (f"当前标签：{current_tab} · 阈值 {health_threshold}，"
                                  f"风格 {self._style_summary(health_effective)}。")
            elif current_tab == "回合":
                action_message = (f"当前标签：{current_tab} · 音量 {round_volume}%，"
                                  f"已选 {round_selected}/{round_total}。")
            else:
                action_message = "新增素材后可直接刷新风格列表。"
            self.action_bar.set_message(action_message)
        # RN-165：空库引导（逻辑在 community_library，只有一份）
        self._sync_community_guidance()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_responsive_grids()
