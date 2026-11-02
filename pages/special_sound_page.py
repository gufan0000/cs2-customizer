#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""特殊音效设置页面。"""

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import config, get_app_data_dir
from core.audio.runtime_audio import get_runtime_audio_manager
from widgets.drop_import_mixin import enable_pack_drop, rescan_if_imported
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
from ui_style_applier import keep_single_line
from widgets.page_action_bar import PageActionBar
from widgets.page_header import PageHeader
from widgets.status_strip import StatusStrip
from widgets.weapon_board import BoardScrollArea, WeaponBoard
from widgets.weapon_row_widget import STATE_CONFIGURED, STATE_STALE, WeaponRowWidget

#: 格子不多，三列刚好：再多就拉成窄窄一排，风格名露不全。
SPECIAL_BOARD_COLUMNS = 3
SLIDER_VALUE_MIN_WIDTH = 56


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
        #: 配置值 → 格子，算「配了 / 配的没了」用：[(格子, 配置原始值的读法, 生效值的读法)]
        self._cells: list[tuple] = []
        #: 页签名 → 这个页签的内容。空库时只留上面那块引导。
        self._tab_bodies: dict[str, list[QWidget]] = {}

        self._ensure_config_defaults()
        self._refresh_special_sound_styles()

        self.init_ui()
        self.load_settings()
        enable_pack_drop(self)          # 批 123：下好的整包拖进来 ⇒ 转交「导入资源」

    def showEvent(self, event):
        super().showEvent(event)
        rescan_if_imported(self, self._refresh_style_catalog)     # 批 123：刚导过包回来就看得见

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
    #   八行下拉框 全是「未选风格」      ← `findData` 找不到就退回第 0 项
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

    def _stale_by_tab(self) -> dict[str, int]:
        """配过、但风格已经不在了的项数，按页签分。"""
        raw_grenade = config.grenade_sound_styles or {}
        pairs = {
            "投掷物": [(raw_grenade.get(g, "0"), v)
                    for g, v in self._effective_grenade_styles().items()],
            "C4": [(getattr(config, e.config_attr, "0"), self._effective_c4_styles()[e.key])
                   for e in self.C4_EVENTS],
            "血量警告": [(getattr(config, "health_warning_style", "0"),
                      self._effective_health_style())],
            "回合": [(getattr(config, self.ROUND_TYPE_META[k][2], "0"), v)
                   for k, v in self._effective_round_styles().items()],
        }
        return {tab: sum(1 for configured, effective in items
                         if str(configured or "0").strip() not in ("", "0") and effective == "0")
                for tab, items in pairs.items()}

    def _stale_total(self) -> int:
        return sum(self._stale_by_tab().values())

    def _style_summary(self, style_value):
        if str(style_value or "").strip() == "0":
            return "未启用"
        return self._compact_text(style_value, "未启用", 18)

    def _module_state_note(self, enabled: bool, selected: int) -> str:
        """选了风格却没勾开关时挑明；别的时候不说话，开关和格子自己看得见（批 147）。

        RN-051：这一页有**两层开关**（模块复选框 + 每一项的「未选风格」）。
        外审 8 发截图里 4 发独立报「玩家容易只选下拉项而遗漏总开关，导致局内不生效」。
        """
        return "配了也不会响：上面的开关还关着。" if selected and not enabled else ""

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
        「未选风格」永久对不上。
        """
        values = list(self._effective_grenade_styles().values())
        values.extend(self._effective_round_styles().values())
        values.extend(self._effective_c4_styles().values())
        values.append(self._effective_health_style())
        return values


    def _create_summary_label(self):
        """有事才出现的一行：开关没开、配的风格没了（可能带去社区的链接，RN-197）。"""
        from widgets import community_library as _cl

        label = QLabel("")
        label.setObjectName("hintLabel")
        label.setWordWrap(True)
        label.hide()
        _cl.wire_stale_route(label, lambda: self.COMMUNITY_CATEGORY_KEY)
        return label

    @staticmethod
    def _reset_combo_items(combo: QComboBox, style_options, current_value):
        blocked = combo.blockSignals(True)
        combo.clear()
        # 这一页上面有「启用」开关：格子再写「不启用」，勾上之后读着像没勾上（外审 S4）
        combo.addItem("未选风格", "0")
        for style in style_options:
            combo.addItem(style, style)
        combo.blockSignals(blocked)
        SpecialSoundPage._set_combo_data(combo, current_value)

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

        # 操作放在标题这一行：不多占一行，四个页签都够得着。
        self.action_bar = PageActionBar(self, inline=True)
        # RN-165：记下 extra 的原样，空库态要借用这个位置。
        self._extra_default = (self.action_bar.extra_btn.text(),
                               self.action_bar._extra_callback,
                               self.action_bar.extra_btn.menu())
        self.action_bar.configure_secondary("刷新风格列表", self._refresh_style_catalog, visible=True)
        self.action_bar.configure_primary("打开音频资源", self._open_current_resource_root, visible=True)
        header.dock_beside_title(self.action_bar)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS.get("special_sound", ""))

        self.status_card = StatusStrip()
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(0, 0, 0, 0)
        status_card_layout.setSpacing(8)

        status_header = QHBoxLayout()
        status_header.setSpacing(10)
        self.status_badge_label = create_badge_label()
        status_header.addWidget(self.status_badge_label, 1)
        status_header.addStretch()
        status_card_layout.addLayout(status_header)

        main_layout.addWidget(self.status_card)

        # RN-180：空库时的第一步放在页签上面 —— 那一片控件的上方，也就是困惑发生的位置。
        from widgets.community_library import EmptyLibraryCallout

        self.empty_callout = EmptyLibraryCallout(self, large=True)
        main_layout.addWidget(self.empty_callout.frame)

        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self._refresh_status_badge)
        main_layout.addWidget(self.tab_widget, 1)

        self._create_grenade_tab()
        self._create_c4_tab()
        self._create_health_tab()
        self._create_round_tab()

    def _make_tab(self, tab_name: str, head: QWidget):
        """一个页签：滚动区里顶上是开关那一行（`head`），下面一竖排。返回（滚动区，那一竖排）。

        空库时藏的是那一竖排，开关留着：先开着没有坏处，搜索也要落得到它。
        """
        scroll = BoardScrollArea()
        content = QWidget(scroll)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 12, 0, 12)
        outer.setSpacing(10)
        head.setProperty("fp_setting_row", True)
        outer.addWidget(head)
        body = QWidget(content)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        outer.addWidget(body)
        outer.addStretch(1)
        scroll.setWidget(content)
        self._tab_bodies[tab_name] = [body]
        self.tab_widget.addTab(scroll, tab_name)
        return scroll, layout

    def _make_cell(self, name: str, key: str, styles, current: str, read_configured, read_effective,
                   on_changed, on_test) -> WeaponRowWidget:
        """一格：名字 + 风格下拉 + 试听。`read_*` 现读这一格的配置值和生效值。"""
        cell = WeaponRowWidget(name, key, [], name_is_action=False)
        self._reset_combo_items(cell.style_combo, styles, current)
        cell.style_combo.currentIndexChanged.connect(lambda _index: on_changed())
        cell.testClicked.connect(on_test)
        self._cells.append((cell, read_configured, read_effective))
        return cell

    def _make_board(self, scroll: BoardScrollArea, cells: list) -> WeaponBoard:
        board = WeaponBoard(max_columns=SPECIAL_BOARD_COLUMNS)
        board.add_group("", cells)
        scroll.availableWidthChanged.connect(board.set_available_width)
        return board

    @staticmethod
    def _make_slider_row(label_text: str, slider: QSlider, value_label: QLabel) -> QWidget:
        holder = QWidget()
        holder.setProperty("fp_setting_row", True)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(keep_single_line(QLabel(label_text)))
        row.addWidget(slider, 1)
        value_label.setMinimumWidth(SLIDER_VALUE_MIN_WIDTH)
        row.addWidget(value_label)
        return holder

    def _create_grenade_tab(self):
        self.grenade_enabled_checkbox = QCheckBox("启用投掷物音效")
        self.grenade_enabled_checkbox.setChecked(bool(config.grenade_sound_enabled))
        self.grenade_enabled_checkbox.toggled.connect(self._on_grenade_enabled_toggled)
        scroll, layout = self._make_tab("投掷物", self.grenade_enabled_checkbox)

        grenade_styles = getattr(self.audio_manager, "grenade_sound_styles", {})
        cells = []
        for grenade_type, display_name in self.GRENADE_TYPES.items():
            cell = self._make_cell(
                display_name, grenade_type,
                grenade_styles.get(grenade_type, []),
                config.grenade_sound_styles.get(grenade_type, "0"),
                lambda g=grenade_type: (config.grenade_sound_styles or {}).get(g, "0"),
                lambda g=grenade_type: self._effective_grenade_styles()[g],
                lambda g=grenade_type: self._on_grenade_style_changed(g),
                lambda g=grenade_type: self._test_grenade_sound(g),
            )
            self.grenade_combos[grenade_type] = cell.style_combo
            cells.append(cell)
        layout.addWidget(self._make_board(scroll, cells))

        self.grenade_summary_label = self._create_summary_label()
        layout.addWidget(self.grenade_summary_label)

        # ⭐⭐ RN-664（社区问「怎么导入手雷的音效」「没有教程和命名格式」）：
        # 六个类型目录名原来只存在于源码里。全文在帮助面板，这里说一句它在哪。
        naming_hint = QLabel("自己加素材：grenade_sounds / 类型 / 风格名 / ，文件名随便起；类型只认六个英文名，见右上角「?」。")
        naming_hint.setObjectName("hintLabel")
        naming_hint.setWordWrap(True)
        layout.addWidget(naming_hint)

    def _create_c4_tab(self):
        self.c4_enabled_checkbox = QCheckBox("启用 C4 音效")
        self.c4_enabled_checkbox.setChecked(bool(config.c4_sound_enabled))
        self.c4_enabled_checkbox.toggled.connect(self._on_c4_enabled_toggled)
        scroll, layout = self._make_tab("C4", self.c4_enabled_checkbox)

        cells = []
        for event in self.C4_EVENTS:
            cell = self._make_cell(
                event.label, event.key,
                getattr(self.audio_manager, "c4_sound_styles", []),
                getattr(config, event.config_attr, "0"),
                lambda e=event: getattr(config, e.config_attr, "0"),
                lambda e=event: self._effective_c4_styles()[e.key],
                lambda e=event: self._on_c4_style_changed(e),
                lambda e=event: self._test_c4_sound(e),
            )
            self.c4_combos[event.key] = cell.style_combo
            cells.append(cell)
        # 老属性名保留：放大镜页等处按名字读它
        self.c4_style_combo = self.c4_combos["planted"]
        layout.addWidget(self._make_board(scroll, cells))

        self.c4_summary_label = self._create_summary_label()
        layout.addWidget(self.c4_summary_label)

        naming_hint = QLabel(
            "每个事件各选一个风格，可以选同一个。拆除和爆炸靠文件名认素材：文件名里带「拆除 / defuse」"
            "「爆炸 / explode」才会被选中，认不出来就保持安静 —— 不会拿安放的音效顶替。"
        )
        naming_hint.setObjectName("hintLabel")
        naming_hint.setWordWrap(True)
        layout.addWidget(naming_hint)

    def _create_health_tab(self):
        self.health_enabled_checkbox = QCheckBox("启用低血量警告")
        self.health_enabled_checkbox.setChecked(bool(config.health_warning_enabled))
        self.health_enabled_checkbox.toggled.connect(self._on_health_enabled_toggled)
        scroll, layout = self._make_tab("血量警告", self.health_enabled_checkbox)

        cell = self._make_cell(
            "警告音效", "health_warning",
            getattr(self.audio_manager, "health_warning_styles", []),
            getattr(config, "health_warning_style", "0"),
            lambda: getattr(config, "health_warning_style", "0"),
            self._effective_health_style,
            lambda: self._on_health_style_changed(0),
            self._test_health_warning,
        )
        self.health_style_combo = cell.style_combo
        layout.addWidget(self._make_board(scroll, [cell]))

        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(5, 50)
        self.threshold_slider.setValue(int(config.health_warning_threshold))
        self.threshold_slider.valueChanged.connect(self._on_threshold_changed)
        self.threshold_value_label = QLabel(str(self.threshold_slider.value()))

        # 以前这个值写死在 gsi_handler_special 里（5 秒），嫌吵和嫌少的都改不了
        self.cooldown_slider = QSlider(Qt.Horizontal)
        self.cooldown_slider.setRange(1, 30)
        self.cooldown_slider.setValue(int(float(getattr(config, "health_warning_cooldown", 5.0))))
        self.cooldown_slider.setToolTip("触发一次低血量警告后，至少隔这么久才会再响一次")
        self.cooldown_slider.valueChanged.connect(self._on_cooldown_changed)
        self.cooldown_value_label = QLabel(f"{self.cooldown_slider.value()} 秒")

        # RN-055：两根滑条（同一类东西）并排，分组和语义一致。
        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.setSpacing(24)
        slider_row.addWidget(self._make_slider_row(
            "触发阈值", self.threshold_slider, self.threshold_value_label), 1)
        slider_row.addWidget(self._make_slider_row(
            "再次提醒间隔", self.cooldown_slider, self.cooldown_value_label), 1)
        layout.addLayout(slider_row)

        self.health_summary_label = self._create_summary_label()
        layout.addWidget(self.health_summary_label)

    def _create_round_tab(self):
        # ⭐ RN-669：开关和总音量**并成一行**：总音量本来就属于「启不启用」那一档，
        #   不是和八个逐项风格并列的第九件事。
        head = QWidget()
        control_row = QHBoxLayout(head)
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(12)

        self.round_enabled_checkbox = QCheckBox("启用回合音效")
        self.round_enabled_checkbox.setChecked(bool(config.round_sound_enabled))
        self.round_enabled_checkbox.toggled.connect(self._on_round_enabled_toggled)
        control_row.addWidget(self.round_enabled_checkbox)
        control_row.addSpacing(12)

        # 不写裸的「音量」：搜这个词要先到总览的主音量，这一格只管回合音效
        volume_caption = keep_single_line(QLabel("回合音量"))
        control_row.addWidget(volume_caption)

        self.round_volume_slider = QSlider(Qt.Horizontal)
        self.round_volume_slider.setRange(0, 100)
        self.round_volume_slider.setValue(int(float(config.round_sound_volume) * 100))
        self.round_volume_slider.setMaximumWidth(320)
        self.round_volume_slider.valueChanged.connect(self._on_round_volume_changed)
        control_row.addWidget(self.round_volume_slider, 1)

        self.round_volume_label = QLabel(f"{self.round_volume_slider.value()}%")
        self.round_volume_label.setMinimumWidth(SLIDER_VALUE_MIN_WIDTH)
        control_row.addWidget(self.round_volume_label)
        control_row.addStretch(1)
        scroll, layout = self._make_tab("回合", head)
        self._tab_bodies["回合"] += [volume_caption, self.round_volume_slider, self.round_volume_label]

        cells = []
        for round_type, (display_name, manager_attr, config_attr) in self.ROUND_TYPE_META.items():
            cell = self._make_cell(
                display_name, round_type,
                getattr(self.audio_manager, manager_attr, []),
                getattr(config, config_attr, "0"),
                lambda ca=config_attr: getattr(config, ca, "0"),
                lambda rt=round_type: self._effective_round_styles()[rt],
                lambda rt=round_type, ca=config_attr: self._on_round_style_changed(rt, ca),
                lambda rt=round_type: self._test_round_sound(rt),
            )
            self.round_combos[round_type] = cell.style_combo
            cells.append(cell)
        layout.addWidget(self._make_board(scroll, cells))

        self.round_summary_label = self._create_summary_label()
        layout.addWidget(self.round_summary_label)

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

    def _current_tab_is_empty(self) -> bool:
        """当前页签那一类一个可用风格都没有才算空（RN-650；整页口径见 `_library_is_empty`）。"""
        tab = (self.tab_widget.tabText(self.tab_widget.currentIndex())
               if hasattr(self, "tab_widget") and self.tab_widget.count() else "")
        families = {
            "投掷物": lambda: [self._available_styles(g, grenade=True) for g in self.GRENADE_TYPES],
            "C4": lambda: [self._available_styles("c4_sound_styles")],
            "血量警告": lambda: [self._available_styles("health_warning_styles")],
            "回合": lambda: [self._available_styles(meta[1]) for meta in self.ROUND_TYPE_META.values()],
        }
        if tab not in families:
            return self._library_is_empty()
        return not any(families[tab]())

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
            empty=self._current_tab_is_empty(),   # RN-650：按页签算空
            category_key=self.COMMUNITY_CATEGORY_KEY,
            cta_text="去社区拿一套特殊音效",
            keep_text="打开音频资源",
            keep_callback=self._open_current_resource_root,
            message=community_library.empty_library_message("风格"),
            callout=getattr(self, "empty_callout", None),   # RN-180
            what="风格",
            refresh_label="刷新风格列表",
        )
        # 空库时当前页签只留开关和上面那块引导：一片全灰的格子只是噪音（批 145，RN-734）。
        current = self.tab_widget.tabText(self.tab_widget.currentIndex())
        for name, widgets in self._tab_bodies.items():
            for widget in widgets:
                widget.setVisible(not (applied and name == current))
        if not applied:
            # ⚠ **借了要还**：空库态借用了 extra 那个位置。
            bar.configure_primary("打开音频资源", self._open_current_resource_root,
                                  visible=True)
            text, callback, menu = getattr(
                self, "_extra_default", ("", None, None))
            bar.configure_extra(text, callback, visible=bool(text))
            bar.extra_btn.setMenu(menu)

    def _sync_cell_states(self) -> None:
        """格子上看得出来：配了、配的风格没了。"""
        for cell, read_configured, read_effective in self._cells:
            configured = str(read_configured() or "0").strip()
            effective = read_effective()
            if effective != "0":
                cell.set_cell_state(STATE_CONFIGURED)
            elif configured not in ("", "0"):
                cell.set_cell_state(STATE_STALE)
            else:
                cell.set_cell_state("")

    def _sync_sidebar_dot(self) -> None:
        window = self.window()
        if hasattr(window, "sync_nav_dots"):
            window.sync_nav_dots()

    def _refresh_status_badge(self):
        self._sync_sidebar_dot()
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
        }.get(current_tab, (enabled_modules, f"功能 · {enabled_modules}/4"))

        badges = [
            ("success" if enabled_modules else "warn", f"功能 · {enabled_modules}/4"),
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
        self.status_card.setToolTip(summary_text)

        from widgets import community_library as _cl  # RN-197

        stale = self._stale_by_tab()

        def stale_note(tab: str) -> str:
            if not stale[tab]:
                return ""
            return (f"有 {stale[tab]} 项配的风格已被改名或删除，那一格显示成「未选风格」，重新选一个即可。"
                    + _cl.stale_style_route(self.COMMUNITY_CATEGORY_KEY))

        self._sync_cell_states()
        notes = {
            "grenade_summary_label": (self._module_state_note(grenade_on, grenade_selected)
                                      + stale_note("投掷物")),
            "c4_summary_label": self._module_state_note(c4_on, c4_selected) + stale_note("C4"),
            "health_summary_label": (self._module_state_note(
                health_on, 1 if health_effective != "0" else 0) + stale_note("血量警告")),
            "round_summary_label": self._module_state_note(round_on, round_selected) + stale_note("回合"),
        }
        for name, note in notes.items():
            label = getattr(self, name, None)
            if label is not None:
                label.setText(note)
                label.setVisible(bool(note))
                label.setToolTip(summary_text)
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
