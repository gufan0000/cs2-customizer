#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
HUD 统一规则设置页面（简化版）
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cfg_utils import setup_autoexec
from config import config
from core.hud.rule_compiler import get_cfg_paths, get_initial_runtime_color, write_runtime_cfg
from core.hud.rule_model import HUD_COLORS, get_default_hud_rules, normalize_hud_rules, normalize_profile
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard

PROFILE_OPTIONS = [
    ("平衡默认（推荐）", "balanced_default"),
    ("竞技简洁", "competitive_simple"),
    ("炫彩增强", "flashy"),
    ("纯击杀", "kill_only"),
    ("战术信息", "tactical"),
]
COLOR_OPTIONS = [("不启用", -1)] + [(f"{name} ({value})", value) for value, (name, _) in HUD_COLORS.items()]
EFFECT_OPTIONS = [
    ("固定", "solid"),
    ("快闪", "flash"),
    ("闪烁", "blink"),
    ("脉冲", "pulse"),
]
EVENT_LABELS = [
    ("kill", "击杀变色"),
    ("death", "被击杀变色"),
]


class HudColorPage(QWidget):
    """统一 HUD 规则设置页面"""
    #: RN-175 / 批 24：**这一页不是自动保存的。** HUD 规则要点一下「保存 HUD 规则」才写进游戏的 cfg。
    #: ⚠ 底栏那条共用回执默认说「改动已自动保存，不用点任何按钮」——
    #:   而这一页同一行右边就摆着那颗必须点的按钮。实测 15 页里 2 页如此。
    #: ⭐ 共用件省的是重复，不是判断。
    SAVES_AUTOMATICALLY = False


    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("HudColorPage")
        self._is_loading = False
        self._dirty = False

        self.key_widgets = {}
        self.event_checkboxes = {}
        self.event_color_combos = {}
        self.event_effect_combos = {}

        self._init_ui()
        self._bind_dirty_signals()
        self._load_settings()
        self.logger.info("HUD 统一规则页面初始化完成")

    @staticmethod
    def _color_swatch(hex_color: str):
        """一枚 16×16 的色块图标。

        RN-127：色号对应的十六进制**本来就在** `HUD_COLORS` 里，
        只是从来没画出来 —— 一个挑颜色的下拉框只写「默认 (0)」这种代号，
        玩家没法预判游戏里会是什么颜色（外审两档 4 发都在说这件事）。
        """
        from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

        pm = QPixmap(16, 16)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(hex_color))
        painter.setPen(QColor(0, 0, 0, 90))
        painter.drawRoundedRect(0, 0, 15, 15, 3, 3)
        painter.end()
        return QIcon(pm)

    def _create_color_combo(self, allow_disabled=False):
        """颜色下拉。

        RN-128（用户裁定 2026-08-20）：**开关只有一个。** 数字键那一组原来
        既有复选框、又在下拉里放一个「不启用」——两套开关重叠，玩家不知道点哪个，
        而两者不一致时的行为从来没人定义过。现在下拉只管颜色，开关只管开关；
        未勾选时把下拉置灰（否则"改了也不生效"没有任何提示）。
        """
        combo = QComboBox()
        combo.setFixedWidth(130)
        combo.setFixedHeight(32)
        for name, value in COLOR_OPTIONS:
            if value < 0 and not allow_disabled:
                continue
            item_icon = self._color_swatch(HUD_COLORS[value][1]) if value in HUD_COLORS else None
            if item_icon is None:
                combo.addItem(name, value)
            else:
                combo.addItem(item_icon, name, value)
        return combo

    def _create_effect_combo(self):
        combo = QComboBox()
        combo.setFixedWidth(90)
        combo.setFixedHeight(32)
        for name, value in EFFECT_OPTIONS:
            combo.addItem(name, value)
        return combo

    def _set_combo_by_data(self, combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(0)

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        page_widget = QWidget()
        layout = QVBoxLayout(page_widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "HUD 颜色规则",
            description="让游戏里的 HUD 跟着局内事件自动变色。挑一个预设方案，再开你想要的事件即可。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["hud_color"])

        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(14, 12, 14, 12)
        status_card_layout.setSpacing(8)

        # RN-162：这一页的总开关**也**收进来（批 1 那七页同一个机制）。
        # ⚠ 批 1 当时**故意没扩到这一页** —— 它已关档、已锁基线，顺手改会让
        # 那一轮失去可比的基线。⭐ 范围按理由走，不按顺手走；
        # 而"以后补"这件事只有真的补了才算数。
        from widgets.master_switch_link import make_master_switch_row

        self.master_switch_row = make_master_switch_row(
            self, "hud_rules_enabled", "动态HUD")
        status_card_layout.addWidget(self.master_switch_row)

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

        preset_card, preset_layout = SettingsCard.make(
            "预设工作台",
            "先套一个配色预设定大方向，再单独改默认色和各个事件的颜色。", spacing=10
        )
        self.context_hint_label = QLabel("")
        self.context_hint_label.setObjectName("hintLabel")
        self.context_hint_label.setWordWrap(True)
        self.context_hint_label.hide()
        preset_layout.addWidget(self.context_hint_label)

        self.preset_content_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self.preset_content_layout.setSpacing(16)

        profile_column = QVBoxLayout()
        profile_column.setSpacing(8)
        profile_title = QLabel("效果预设")
        profile_title.setObjectName("statusLabel")
        profile_column.addWidget(profile_title)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(10)
        self.profile_combo = QComboBox()
        for label, value in PROFILE_OPTIONS:
            self.profile_combo.addItem(label, value)
        self.profile_combo.setFixedWidth(200)
        self.profile_combo.setFixedHeight(34)
        profile_row.addWidget(self.profile_combo)

        # ⚠⚠ RN-175（外审 4/6 票）：这颗按钮原来叫「**应用**预设」，
        # 而它的**行为**一直是对的 —— 只 `_apply_rules_to_ui` + `_set_dirty(True)`，
        # 一个字节都没写进游戏。错的是那个词：「应用」读起来像一次提交，
        # 于是它和底栏那颗「保存」构成**双重确认**，玩家分不清哪一步才算数。
        # ⭐ **一个动作只有一个生效点** —— 这一颗只负责把预设填进编辑区。
        self.apply_profile_btn = QPushButton("载入这套")
        self.apply_profile_btn.setObjectName("secondaryButton")
        self.apply_profile_btn.setMinimumHeight(34)
        self.apply_profile_btn.clicked.connect(self._apply_preset)
        profile_row.addWidget(self.apply_profile_btn)
        profile_row.addStretch()
        profile_column.addLayout(profile_row)

        profile_tip = QLabel(
            "载入只是把这套规则填进下面的编辑区，还没写进游戏；"
            "确认好了再点右下角保存。")
        profile_tip.setObjectName("hintLabel")
        profile_tip.setWordWrap(True)
        profile_column.addWidget(profile_tip)
        profile_column.addStretch(1)
        self.preset_content_layout.addLayout(profile_column, 5)

        default_column = QVBoxLayout()
        default_column.setSpacing(8)
        default_title = QLabel("默认 HUD 色")
        default_title.setObjectName("statusLabel")
        default_column.addWidget(default_title)

        default_row = QHBoxLayout()
        default_row.setSpacing(10)
        self.default_color_combo = self._create_color_combo()
        default_row.addWidget(self.default_color_combo)
        default_row.addStretch()
        default_column.addLayout(default_row)

        self.preset_summary_label = QLabel("")
        self.preset_summary_label.setObjectName("hintLabel")
        self.preset_summary_label.setWordWrap(True)
        default_column.addWidget(self.preset_summary_label)
        default_column.addStretch(1)
        self.preset_content_layout.addLayout(default_column, 4)

        preset_layout.addLayout(self.preset_content_layout)
        layout.addWidget(preset_card)

        key_card, key_card_layout = SettingsCard.make(
            "数字键颜色映射",
            "这一组会写进 cs2customizer.cfg，软件关闭后依然可用，适合放最常按的道具或武器切换颜色。", spacing=10
        )
        key_layout = QGridLayout()
        key_layout.setContentsMargins(8, 6, 8, 6)
        key_layout.setHorizontalSpacing(14)
        key_layout.setVerticalSpacing(8)
        for idx in range(1, 10):
            r = (idx - 1) // 3
            c = ((idx - 1) % 3) * 2
            enable_box = QCheckBox(f"键 {idx}")
            enable_box.setFixedWidth(60)
            color_combo = self._create_color_combo()      # RN-128：不带「不启用」
            color_combo.setEnabled(enable_box.isChecked())
            enable_box.toggled.connect(color_combo.setEnabled)
            key_layout.addWidget(enable_box, r, c)
            key_layout.addWidget(color_combo, r, c + 1)
            self.key_widgets[str(idx)] = {"enabled": enable_box, "color": color_combo}
        key_card_layout.addLayout(key_layout)

        event_card, event_card_layout = SettingsCard.make(
            "事件响应",
            "这部分需要软件在后台运行；适合只保留少量高价值事件，避免 HUD 反馈过于频繁。", spacing=10
        )
        eg = QVBoxLayout()
        eg.setContentsMargins(8, 6, 8, 6)
        eg.setSpacing(8)
        for key, label in EVENT_LABELS:
            row_frame = QFrame()
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(12)
            cb = QCheckBox(label)
            row_layout.addWidget(cb)
            row_layout.addWidget(QLabel("颜色:"))
            color_combo = self._create_color_combo()      # RN-128：同上，开关只由复选框管
            color_combo.setEnabled(cb.isChecked())
            cb.toggled.connect(color_combo.setEnabled)
            row_layout.addWidget(color_combo)
            row_layout.addWidget(QLabel("效果:"))
            effect_combo = self._create_effect_combo()
            row_layout.addWidget(effect_combo)
            row_layout.addStretch()
            eg.addWidget(row_frame)
            self.event_checkboxes[key] = cb
            self.event_color_combos[key] = color_combo
            self.event_effect_combos[key] = effect_combo

        event_tip = QLabel("其他参数（持续时间、间隔等）由预设方案决定。")
        event_tip.setObjectName("hintLabel")
        eg.addWidget(event_tip)
        event_card_layout.addLayout(eg)

        # RN-126（用户裁定 2026-08-20）：**核心在前。**
        # 这一页的主功能是「局内事件变色」，而它原来排在 9 个数字键（265px）之后：
        # 完整档视口折线 725、事件卡从 y=717 起 —— 只露 8px；紧凑档完全在首屏之外。
        # 外审两档 3/3 都在说「首屏全被数字键占满，核心功能主次颠倒」。
        # ⚠ 加进布局的顺序同时就是 Tab 焦点顺序（RN-122 的教训），两者在这里一致。
        layout.addWidget(event_card)
        layout.addWidget(key_card)

        layout.addStretch()
        page_scroll.setWidget(page_widget)
        outer.addWidget(page_scroll, 1)

        # 固定底部操作栏：统一组件，降低跨页面维护成本
        self.action_bar = PageActionBar(self)
        # ⚠ RN-427：这句话原来说的是「点保存，设置**才会生效**」——
        # 它把「写入」说成了「生效」，而这一页还有一颗总开关。外审原话：
        # 「让玩家误以为只要点击右侧保存按钮设置就会在游戏内生效，无需开启总开关」。
        # ⭐ 这一句只该说**它自己负责的那一步**（写入），
        #   「生不生效」由底栏那条共用回执回答 —— 两句话各说各的那一半。
        self.action_bar.set_message("HUD 规则要点一下保存才会写入")
        self.action_bar.configure_primary("保存 HUD 规则", self._save_hud_rules, visible=True)
        self.save_hint_label = self.action_bar.message_label
        self.save_btn = self.action_bar.primary_btn
        self.save_btn.setFixedWidth(180)
        outer.addWidget(self.action_bar, 0)
        self._update_preset_layout()

    def _compact_text(self, text, fallback="-", max_length=14):
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    def _count_enabled_key_rules(self):
        return sum(1 for widgets in self.key_widgets.values() if widgets["enabled"].isChecked())

    def _count_enabled_events(self):
        return sum(1 for cb in self.event_checkboxes.values() if cb.isChecked())

    def _update_preset_layout(self):
        if not hasattr(self, "preset_content_layout"):
            return
        direction = QBoxLayout.TopToBottom if self.width() < 1050 else QBoxLayout.LeftToRight
        if self.preset_content_layout.direction() != direction:
            self.preset_content_layout.setDirection(direction)

    def _refresh_preset_summary(self):
        if not hasattr(self, "preset_summary_label"):
            return
        self.preset_summary_label.setText(
            f"当前预设：{self.profile_combo.currentText()} · 默认色：{self.default_color_combo.currentText()} · "
            f"数字键 {self._count_enabled_key_rules()} 项 · 事件 {self._count_enabled_events()} 项"
        )

    def on_master_switch_synced(self):
        """总开关被别处拨动后，把本页那条状态文案重算一遍。

        ⭐ 全仓统一的钩子名（`widgets/master_switch_link` 调它）。
        少了这一下，开关动了而徽章不动 —— 同屏两处说法不一致，RN-107 族。
        """
        self._sync_status_strip()

    def _sync_status_strip(self):
        profile_text = self._compact_text(
            self.profile_combo.currentText() if hasattr(self, "profile_combo") else "",
            "未设置",
        )
        default_color = self._compact_text(
            self.default_color_combo.currentText() if hasattr(self, "default_color_combo") else "",
            "未设置",
            18,
        )
        key_count = self._count_enabled_key_rules()
        event_count = self._count_enabled_events()
        master_enabled = bool(getattr(config, "hud_rules_enabled", False))

        badges = [
            # ⚠ 这条原来写「总开关 · 开启」。开关搬进同一张卡之后，
            # 那就是**同一行里把一件事说两遍**（RN-163 在 kill_icon /
            # screen_effects 上逮到的那一条）。改成功能词。
            ("positive" if master_enabled else "warning",
             "生效 · 规则已启用" if master_enabled else "生效 · 规则未启用"),
            ("info", f"预设 · {profile_text}"),
            ("positive" if key_count else "info", f"数字键 · {key_count} 项"),
            ("positive" if event_count else "info", f"事件 · {event_count} 项"),
            # ⚠⚠ RN-426：原来写「保存 · 已同步 / 待同步」。
            # 那句话**在总开关关着时也是真话**（它由 `_dirty` 决定，说的是
            # 「你的改动已经写出去了」）—— 所以它不是假话，是**一词两义**：
            # 「同步」同时指「写盘」和「在游戏里跑起来」，而玩家读的是后一个。
            # ⭐⭐ **一句真话被读成另一件事，和一句假话，要用两种修法**：
            #   前者不能靠「改成正确的说法」修，它本来就正确；只能换掉那个词。
            ("warning" if self._dirty else "positive",
             "保存 · 有改动没存" if self._dirty else "保存 · 已存下"),
        ]

        detail_text = (
            f"HUD 总开关：{'已开启' if master_enabled else '已关闭'}\n"
            f"当前预设：{self.profile_combo.currentText() if hasattr(self, 'profile_combo') else '未设置'}\n"
            f"默认颜色：{default_color}\n"
            f"数字键映射：{key_count} 项\n"
            f"事件响应：{event_count} 项\n"
            # ⚠ 同 RN-426：这张卡的 tooltip 里也有一份，改的时候差点漏掉 ——
            #   ⭐ 判据扫的是整个 `_sync_status_strip` 的字面量，所以它没漏。
            f"保存状态：{'有改动没存' if self._dirty else '已存下'}\n"
            f"CFG 目录：{'已配置' if getattr(config, 'csgo_dir', '') else '未配置'}"
        )
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.summary_label.setText(detail_text)
        self.summary_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)
        self._refresh_preset_summary()
        self._refresh_context_hint(master_enabled)

    def _refresh_context_hint(self, master_enabled=None):
        if not hasattr(self, "context_hint_label"):
            return
        if master_enabled is None:
            master_enabled = bool(getattr(config, "hud_rules_enabled", False))

        if not master_enabled:
            # ⚠ 这句原来写「总开关在"基础设置 -> 动态HUD"」—— RN-163 那 13 处
            # 指路文案的**第 14 处**，只因为这一页当时还没有自己的开关，
            # 那条判据（"有自己开关的页才查"）就绕过去了。
            # ⭐ **条件式判据会在条件不成立的地方留下盲区**，而盲区不报错。
            self.context_hint_label.setText(
                "总开关没开：规则会继续保留，但不会在游戏里生效。")
            self.context_hint_label.show()
            return

        if not getattr(config, "csgo_dir", ""):
            self.context_hint_label.setText("当前还没配置 CS2 目录，规则可以先保存到软件配置，但暂时不会写出 cs2customizer.cfg。")
            self.context_hint_label.show()
            return

        self.context_hint_label.hide()

    def _bind_dirty_signals(self):
        self.profile_combo.currentIndexChanged.connect(self._mark_dirty)
        self.default_color_combo.currentIndexChanged.connect(self._mark_dirty)

        for widgets in self.key_widgets.values():
            widgets["enabled"].toggled.connect(self._mark_dirty)
            widgets["color"].currentIndexChanged.connect(self._mark_dirty)

        for cb in self.event_checkboxes.values():
            cb.toggled.connect(self._mark_dirty)
        for combo in self.event_color_combos.values():
            combo.currentIndexChanged.connect(self._mark_dirty)
        for combo in self.event_effect_combos.values():
            combo.currentIndexChanged.connect(self._mark_dirty)

    def _mark_dirty(self, *_args):
        if self._is_loading:
            return
        self._set_dirty(True)
        self._sync_status_strip()

    def _set_dirty(self, dirty):
        self._dirty = bool(dirty)
        self._refresh_dirty_ui()

    def _refresh_dirty_ui(self):
        if self._dirty:
            self.save_btn.setText("保存 HUD 规则 *")
            # ⚠⚠ 走 `set_message`，**不许直接对 message_label 写字**。
            # 实测（批 19）：直接 setText 会把批 16 那条共用回执**整句冲掉** ——
            # 拨完开关时回执还在，跑一次 `_refresh_dirty_ui()`（用户改任何一个
            # 设置都会触发）之后就只剩这一句了。
            # ⭐⭐ **守卫建在入口上，而这一页拿到了入口里面那个控件的引用。**
            # ⚠⚠ RN-131：这句必须回答「保存完之后，游戏里怎么才见效」——
            # 那条指令原来**只在保存成功的模态框里出现过一次**，关掉就没了，
            # 于是外审仍有 3 发在问「是自动生效还是要在控制台输入指令」。
            # ⭐ **一句只在模态框里出现过的说明，等于没有说明。**
            # ⚠ 措辞只描述代码真做过的事（`write_cs2customizer_cfg` + `setup_autoexec`）：
            #   ⛔ 不写「下次进游戏会自动生效」—— 那是**游戏**会不会执行 autoexec，
            #   我没有证据。⭐ **描述我们做了什么，不承诺别人会怎样**（RN-011 / RN-254）。
            self.action_bar.set_message(
                "有改动还没保存 —— 点保存写进游戏的 cfg（并挂进 autoexec）；"
                "当局要立刻见效，在游戏控制台敲 exec cs2customizer.cfg。")
            self.save_hint_label.setStyleSheet("color: #f7b955;")
        else:
            self.save_btn.setText("保存 HUD 规则")
            self.action_bar.set_message(
                "已写进游戏的 cfg（并挂进 autoexec）；"
                "当局要立刻见效，在游戏控制台敲 exec cs2customizer.cfg。")
            self.save_hint_label.setStyleSheet("")
        self._sync_status_strip()

    def _apply_rules_to_ui(self, profile, rules):
        self._is_loading = True
        try:
            self._set_combo_by_data(self.profile_combo, profile)
            self._set_combo_by_data(self.default_color_combo, rules.get("default_color", 0))

            for key, widgets in self.key_widgets.items():
                entry = rules.get("key_rules", {}).get(key, {})
                widgets["enabled"].setChecked(bool(entry.get("enabled", False)))
                self._set_combo_by_data(widgets["color"], entry.get("color", -1))

            for key, cb in self.event_checkboxes.items():
                rule = rules.get("event_rules", {}).get(key, {})
                cb.setChecked(bool(rule.get("enabled", False)))

            for key, combo in self.event_color_combos.items():
                rule = rules.get("event_rules", {}).get(key, {})
                self._set_combo_by_data(combo, rule.get("main", -1))

            for key, combo in self.event_effect_combos.items():
                rule = rules.get("event_rules", {}).get(key, {})
                self._set_combo_by_data(combo, rule.get("effect", "solid"))
        finally:
            self._is_loading = False

    def _load_settings(self):
        profile = normalize_profile(config.hud_rules_profile)
        rules = normalize_hud_rules(config.hud_rules, profile=profile)
        self._apply_rules_to_ui(profile, rules)
        self._set_dirty(False)
        # ⚠ 回读 config 的**实际值**再定开关的样子。总开关可能是在别处
        # （首页那颗、或 config 热重载）改的，本页那一颗不会自己知道。
        if hasattr(self, "master_switch_row"):
            self.master_switch_row.refresh()
        self._sync_status_strip()

    def can_leave_page(self):
        if not self._dirty:
            return True

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("未保存修改")
        msg.setText("HUD 规则有未保存修改，离开前是否保存？")
        save_btn = msg.addButton("保存并离开", QMessageBox.AcceptRole)
        discard_btn = msg.addButton("不保存离开", QMessageBox.DestructiveRole)
        msg.addButton("取消", QMessageBox.RejectRole)
        msg.setDefaultButton(save_btn)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == save_btn:
            return self._save_hud_rules(show_success_dialog=False)
        if clicked == discard_btn:
            self._load_settings()
            return True
        return False

    def _apply_preset(self):
        profile = normalize_profile(self.profile_combo.currentData())
        preset_rules = get_default_hud_rules(profile)

        current_rules = self._build_rules_from_ui()
        preset_rules["key_rules"] = current_rules.get("key_rules", preset_rules["key_rules"])
        preset_rules = normalize_hud_rules(preset_rules, profile=profile)

        self._apply_rules_to_ui(profile, preset_rules)
        self._set_dirty(True)
        # RN-129（用户裁定 2026-08-20）：**别弹确认框。**
        # 一个模态框在玩家眼里就是"这一步完成了"，而真正写进游戏的是底栏那个保存 ——
        # 外审两档 4 发都在问「应用预设之后到底还要不要点保存」。
        # 现在只留下"有未保存修改"这个状态（底栏那句提示由 `_refresh_dirty_ui` 负责）。

    def _build_rules_from_ui(self):
        profile = normalize_profile(self.profile_combo.currentData())
        rules = get_default_hud_rules(profile)
        rules["default_color"] = self.default_color_combo.currentData()

        for key, widgets in self.key_widgets.items():
            rules["key_rules"][key] = {
                "enabled": widgets["enabled"].isChecked(),
                "color": widgets["color"].currentData(),
            }

        for key, cb in self.event_checkboxes.items():
            rules["event_rules"][key]["enabled"] = cb.isChecked()

        for key, combo in self.event_color_combos.items():
            color = combo.currentData()
            if color >= 0:
                rules["event_rules"][key]["main"] = color

        for key, combo in self.event_effect_combos.items():
            rules["event_rules"][key]["effect"] = combo.currentData()

        return normalize_hud_rules(rules, profile=profile)

    def _legacy_map_from_rules(self, rules):
        dynamic_map = {"default": {"color": rules.get("default_color", 0), "effect": "solid", "alt_color": -1}}
        for key, entry in rules.get("event_rules", {}).items():
            if entry.get("enabled", False):
                dynamic_map[key] = {
                    "color": entry.get("main", -1),
                    "effect": entry.get("effect", "solid"),
                    "alt_color": entry.get("alt", -1),
                }
        for key, entry in rules.get("state_rules", {}).items():
            if entry.get("enabled", False):
                dynamic_map[key] = {
                    "color": entry.get("main", -1),
                    "effect": entry.get("effect", "solid"),
                    "alt_color": entry.get("alt", -1),
                }
        return dynamic_map

    def _save_hud_rules(self, show_success_dialog=True):
        try:
            profile = normalize_profile(self.profile_combo.currentData())
            rules = self._build_rules_from_ui()

            config.hud_rules_profile = profile
            config.hud_rules = rules
            config.hud_rules_version = rules.get("version", 1)
            config.hud_runtime_sync_mode = "safe"
            config.hud_keymap_enabled = {
                key: bool(rules["key_rules"].get(key, {}).get("enabled", False))
                for key in [str(i) for i in range(1, 10)]
            }

            # （Phase1-1.4：hud_color_enabled 已是 property 别名，无需手工镜像）
            config.hud_color_mode = "dynamic"
            config.hud_color_static = rules.get("default_color", 0)
            config.hud_color_dynamic_map = self._legacy_map_from_rules(rules)
            config.hud_color_kill_duration = rules["event_rules"]["kill"].get("duration_ms", 0) / 1000.0
            config.hud_color_headshot_duration = rules["event_rules"]["headshot_kill"].get("duration_ms", 0) / 1000.0
            config.hud_color_multi_kill_duration = rules["event_rules"]["multi_kill"].get("duration_ms", 0) / 1000.0
            config.hud_color_death_duration = rules["event_rules"]["death"].get("duration_ms", 0) / 1000.0
            config.hud_color_low_health_threshold = rules["event_rules"]["low_health"].get("threshold", 20)

            config.save_config()

            if not config.csgo_dir:
                # 没配游戏目录：软件配置这一半确实存住了，这就是这条路径的全部承诺。
                self._set_dirty(False)
                self._sync_status_strip()
                QMessageBox.warning(self, "提示", "规则已保存到软件配置，请先在高级设置中配置 CS2 目录后再写入 CFG。")
                return True

            from core.cfg_compiler import write_cs2customizer_cfg

            warnings = write_cs2customizer_cfg(config)
            if warnings:
                from ui_toast import toast_warning

                toast_warning("\n".join(warnings), 5000)

            _, runtime_cfg_path = get_cfg_paths(config.csgo_dir)
            write_runtime_cfg(runtime_cfg_path, get_initial_runtime_color(config))

            try:
                setup_autoexec(config.csgo_dir)
            except Exception as e:
                self.logger.warning(f"Setup autoexec failed: {e}")

            # ⚠ RN-130：**"未保存"标志要等到 CFG 真的写完了才清。**
            # 原来它清在 `save_config()` 之后、写 CFG 之前 —— 于是写 CFG 抛异常时，
            # 用户看到一个报错框、关掉，页面却显示"没有未保存修改"，切页也不再拦他。
            # 软件配置存住了、游戏里的 CFG 没写成，而界面上没有任何痕迹说明这件事。
            # ⇒ **"我干完了"这个标志，必须置在动作成功之后，不是动作开始时。**
            self._set_dirty(False)
            self._sync_status_strip()

            if show_success_dialog:
                cfg_path, _ = get_cfg_paths(config.csgo_dir)
                QMessageBox.information(
                    self,
                    "保存成功",
                    "HUD 规则已保存。\n\n"
                    f"cs2customizer.cfg: {cfg_path}\n"
                    f"cs2customizer_hud_runtime.cfg: {runtime_cfg_path}\n\n"
                    "游戏内执行: exec cs2customizer.cfg",
                )
            self.logger.info("HUD统一规则保存完成")
            return True
        except Exception as e:
            self.logger.error(f"保存HUD统一规则失败: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", "保存失败：配置可能被占用，请稍后重试。")
            self._sync_status_strip()
            return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preset_layout()
