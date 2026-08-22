# SPDX-License-Identifier: GPL-3.0-or-later
"""枪声设置页面。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import config, get_app_data_dir
from core.audio.audio_file_utils import DEFAULT_AUDIO_EXTENSIONS, list_style_dirs_with_audio
from core.audio.runtime_audio import get_runtime_audio_manager
from core.gun_sound_profiles import (
    GUN_SOUND_PROFILES,  # noqa: F401  本文件未直接用，但测试经 gun_sound_page.GUN_SOUND_PROFILES 访问
    SUPPORTED_GUN_SOUND_PROFILE_LIST,
    SUPPORTED_GUN_SOUND_PROFILES,  # noqa: F401  测试经 gun_sound_page.SUPPORTED_GUN_SOUND_PROFILES 访问
    SUPPORTED_GUN_SOUND_TAB_GROUPS,
    is_gun_sound_master_enabled,
    resolve_gun_sound_style,
)
from core.utils.logger import get_logger
from core.utils.format_utils import format_percent
from widgets.preview_feedback import PreviewFailure, report_preview_failure
from pages.audio_status_badge import (
    build_health_detail_tooltip,
    collect_category_health,
    create_badge_label,
    render_badges,
    resolve_style,
    resource_badge,
    resource_hint,
    stale_style_name,
)
from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar


class GunSoundPage(QWidget):
    """枪声设置页面。"""

    DISABLED_STYLE_TEXT = "不启用"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("GunSoundPage")
        self.audio_manager = get_runtime_audio_manager()
        self.audio_manager.ensure_styles_scanned()

        self.weapon_configs = {
            profile.gun_type: profile for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST
        }
        self.weapon_rows: dict[str, dict[str, object]] = {}
        self.weapon_styles: dict[str, list[str]] = {}
        self._tab_groups = list(SUPPORTED_GUN_SOUND_TAB_GROUPS)
        self._loading = False

        self._scan_gun_sounds()
        self._init_ui()
        self.load_settings()

        self.logger.info("枪声设置页面初始化完成")

    @staticmethod
    def _compact_text(text, fallback="未分组", max_length=8):
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    def _get_profile_style(self, profile) -> str:
        """配置里写着什么（只做别名归一，**不判风格还在不在**）。"""
        return resolve_gun_sound_style(getattr(config, profile.style_key, "0"))

    # ── RN-046：三个口径统一到下面这一处 ────────────────────────────────
    # 原状（探针实测，全新配置 + 两把枪配了已删除的风格）：
    #   徽章「已配置 · 2/18」「分类 · 手枪 2/9」，而那两行的下拉框都显示「不启用」
    #   —— 因为 `combo.findData("已被删除的风格")` 返回 -1，回落到第 0 项。
    # ⇒ 计数数的是配置原始值，界面显示的是解析后的值，两边永久对不上，无人报错。
    # 解析这件事本身走 `audio_status_badge.resolve_style()`（全仓唯一一份）。

    def _effective_style(self, profile) -> str:
        """这一行**真正在显示**的那个值。全页统计只准问它。"""
        return resolve_style(self._get_profile_style(profile),
                             self.weapon_styles.get(profile.gun_type, []))

    def _effective_styles(self) -> dict[str, str]:
        return {gun_type: self._effective_style(profile)
                for gun_type, profile in self.weapon_configs.items()}

    def _stale_names(self) -> list[str]:
        """配过、但那个风格已经不在了的武器显示名。"""
        names = []
        for gun_type, profile in self.weapon_configs.items():
            if stale_style_name(self._get_profile_style(profile),
                               self.weapon_styles.get(gun_type, [])):
                names.append(profile.display_name)
        return names

    def _get_profile_duck_ratio(self, profile) -> float:
        value = getattr(
            config,
            profile.duck_ratio_key,
            getattr(config, "gun_sound_duck_ratio", profile.default_duck_ratio),
        )
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return profile.default_duck_ratio

    def _get_profile_mute_duration(self, profile) -> float:
        value = getattr(config, profile.mute_duration_key, profile.default_mute_duration)
        try:
            return max(0.1, min(1.0, float(value)))
        except Exception:
            return profile.default_mute_duration

    def _get_current_tab_info(self) -> tuple[str, tuple[str, ...]]:
        if not hasattr(self, "tab_widget") or self.tab_widget.count() == 0 or not self._tab_groups:
            return ("未分组", tuple())
        index = self.tab_widget.currentIndex()
        if index < 0 or index >= len(self._tab_groups):
            index = 0
        return self._tab_groups[index]

    def _configured_count_for_weapons(self, weapon_types: tuple[str, ...] | list[str],
                                      effective: dict[str, str] | None = None) -> int:
        effective = self._effective_styles() if effective is None else effective
        return sum(1 for weapon_type in weapon_types
                   if effective.get(weapon_type, "0") != "0")

    def _configured_preview_names(self, max_items: int = 3,
                                  effective: dict[str, str] | None = None) -> list[str]:
        effective = self._effective_styles() if effective is None else effective
        names = []
        for weapon_type, profile in self.weapon_configs.items():
            if effective.get(weapon_type, "0") != "0":
                names.append(profile.display_name)
            if len(names) >= max_items:
                break
        return names

    @staticmethod
    def _format_ratio_range(values: list[float]) -> str:
        if not values:
            return "-"
        percentages = sorted(int(round(value * 100)) for value in values)
        if percentages[0] == percentages[-1]:
            return f"{percentages[0]}%"
        return f"{percentages[0]}%-{percentages[-1]}%"

    @staticmethod
    def _format_duration_range(values: list[float]) -> str:
        if not values:
            return "-"
        normalized = sorted(round(value, 1) for value in values)
        if normalized[0] == normalized[-1]:
            return f"{normalized[0]:.1f}秒"
        return f"{normalized[0]:.1f}-{normalized[-1]:.1f}秒"

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "枪声设置",
            description="开火后压住原始枪声、换成你自己的音效。目前只开放半自动武器（手枪 / 狙击枪 / 霰弹枪 / 宙斯），自动武器暂不支持。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["gun_sound"])

        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(14, 12, 14, 12)
        status_card_layout.setSpacing(8)

        # RN-189：就地总开关。首页「功能开关」里有「枪声替换」，而站在这一页上
        # 拨不到它 —— 实测首页 17 颗开关里有 8 颗是这个样子。
        # ⚠ 拨动一律走 `MainWindow.set_feature_enabled` ⇒ 首页那颗开关 ⇒ 一整串副作用。
        # **同一件事只能有一条链路**，这里绝不自己 `setattr(config, ...)`。
        from widgets.master_switch_link import make_master_switch_row

        self.master_switch_row = make_master_switch_row(
            self, "gun_sound_enabled", "枪声替换")
        status_card_layout.addWidget(self.master_switch_row)

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

        # RN-049：真正会显示的那一行。`summary_label` 是 RN-009 那个"建出来就
        # hide、全仓没人再显示"的死控件——往它写字等于没写（kill_sound 那轮
        # 我已经栽过一次）。所以这里另立一个，**空文案时才隐藏**。
        self.status_hint_label = QLabel("")
        self.status_hint_label.setObjectName("hintLabel")
        self.status_hint_label.setWordWrap(True)
        self.status_hint_label.hide()
        status_card_layout.addWidget(self.status_hint_label)
        layout.addWidget(self.status_card)

        # RN-180：空库时的第一步放在状态卡正下方 —— 那一片置灰控件的上方，
        # 也就是困惑发生的位置。放底栏等于没放（CLAUDE.md 那条我自己写下又没照做的）。
        from widgets.community_library import EmptyLibraryCallout

        self.empty_callout = EmptyLibraryCallout(self)
        layout.addWidget(self.empty_callout.frame)

        self.tab_widget = QTabWidget()
        for tab_name, weapon_types in self._tab_groups:
            tab = QWidget()
            self._create_weapon_tab(tab, weapon_types)
            self.tab_widget.addTab(tab, tab_name)
        # 先 addTab 再 connect：加首个 tab 会触发 currentChanged，
        # 此刻 action_bar 尚未创建，回调只靠 hasattr 守卫幸免
        self.tab_widget.currentChanged.connect(self._refresh_status_badge)
        layout.addWidget(self.tab_widget, 1)

        self.action_bar = PageActionBar(self)
        # RN-165：记下 extra 的原样，空库态要借用这个位置。
        self._extra_default = (self.action_bar.extra_btn.text(),
                               self.action_bar._extra_callback,
                               self.action_bar.extra_btn.menu())
        self.action_bar.configure_secondary("刷新风格列表", self._refresh_style_catalog, visible=True)
        self.action_bar.configure_primary("打开音频资源", self._open_audio_resource_root, visible=True)
        self.action_bar.secondary_btn.setMinimumWidth(148)
        self.action_bar.primary_btn.setMinimumWidth(148)
        layout.addWidget(self.action_bar, 0)

    def _create_weapon_tab(self, parent: QWidget, weapons: tuple[str, ...]):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(6, 6, 6, 6)
        scroll_layout.setSpacing(6)

        for weapon_type in weapons:
            profile = self.weapon_configs[weapon_type]
            styles = self.weapon_styles.get(weapon_type, [])
            scroll_layout.addWidget(self._create_compact_weapon_card(weapon_type, profile.display_name, styles))

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def _create_compact_weapon_card(self, weapon_type: str, display_name: str, styles: list[str]):
        card = QFrame()
        card.setObjectName("card")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        name_label = QLabel(display_name)
        name_label.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        name_label.setMinimumWidth(96)
        header_row.addWidget(name_label)

        style_hint_label = QLabel("风格:")
        style_hint_label.setObjectName("hintLabel")
        header_row.addWidget(style_hint_label)

        style_combo = QComboBox()
        style_combo.setMinimumWidth(230)
        style_combo.setMinimumHeight(34)
        style_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        style_combo.addItem(self.DISABLED_STYLE_TEXT, "0")
        for style in styles:
            style_combo.addItem(style, style)
        style_combo.currentIndexChanged.connect(
            lambda _index, weapon=weapon_type, combo=style_combo: self._on_weapon_style_changed(
                weapon, combo.currentData()
            )
        )
        header_row.addWidget(style_combo, 1)

        test_btn = QPushButton("测试")
        test_btn.setObjectName("secondaryButton")
        test_btn.setFixedWidth(72)
        test_btn.setMinimumHeight(34)
        test_btn.clicked.connect(lambda: self._test_gun_sound(weapon_type))
        header_row.addWidget(test_btn)
        card_layout.addLayout(header_row)

        # RN-049：这里原来挂一句「当前还没有检测到这个武器的可用风格资源，
        # 建议先保持"不启用"。」—— **每张卡一句，全新安装下就是 18 句**，
        # 一屏能看到 3 句，翻完 4 个页签 18 句一字不差。而顶部状态卡同一屏
        # 已经写着「素材 · 待添加」。
        # ⭐ 与上一轮那句 50 字辩解同一个病：当初写它是因为**别处没说**；
        # 别处说了，它就只是噪音。这次是 18 份。收到页级一条（见
        # `_refresh_status_badge` 里的 `status_hint_label`）。

        profile = self.weapon_configs[weapon_type]
        duck_ratio = self._get_profile_duck_ratio(profile)
        mute_duration = self._get_profile_mute_duration(profile)

        tuning_frame = QFrame()
        tuning_layout = QGridLayout(tuning_frame)
        tuning_layout.setContentsMargins(0, 0, 0, 0)
        tuning_layout.setHorizontalSpacing(10)
        tuning_layout.setVerticalSpacing(6)

        # RN-052：这两个词是音频工程术语，界面上原先没有任何解释。
        # 外审三发独立报「原声保留 / 静音覆盖 术语过于专业抽象，玩家无法直观
        # 理解对开火听感的影响」。加说明不能靠往 18 张卡里各塞一行字
        # （那正是 RN-049 刚删掉的东西），所以落在 tooltip 上：**零像素改动**。
        duck_caption = QLabel("原声保留:")
        duck_caption.setToolTip(
            "开火时游戏原本的枪声保留多少音量。0% = 完全听不到原声，"
            "只剩你换上的音效；调高就是两个声音叠在一起。")
        tuning_layout.addWidget(duck_caption, 0, 0)

        duck_slider = QSlider(Qt.Horizontal)
        duck_slider.setMinimum(0)
        duck_slider.setMaximum(100)
        duck_slider.setValue(int(round(duck_ratio * 100)))
        duck_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        duck_slider.valueChanged.connect(
            lambda value, weapon=weapon_type: self._on_weapon_duck_ratio_changed(weapon, value)
        )
        tuning_layout.addWidget(duck_slider, 0, 1)

        duck_value_label = QLabel(format_percent(duck_ratio))
        duck_value_label.setFixedWidth(46)
        tuning_layout.addWidget(duck_value_label, 0, 2)

        duration_caption = QLabel("静音覆盖:")
        duration_caption.setToolTip(
            "每次开火后压住原声的时长。太短会听到原声的尾巴，"
            "太长会盖掉下一枪；连发武器往短了调。")
        tuning_layout.addWidget(duration_caption, 0, 3)

        duration_slider = QSlider(Qt.Horizontal)
        duration_slider.setMinimum(1)
        duration_slider.setMaximum(10)
        duration_slider.setValue(int(round(mute_duration * 10)))
        duration_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        duration_slider.valueChanged.connect(
            lambda value, weapon=weapon_type: self._on_mute_duration_changed(weapon, value)
        )
        tuning_layout.addWidget(duration_slider, 0, 4)

        duration_value_label = QLabel(f"{mute_duration:.1f}秒")
        duration_value_label.setFixedWidth(52)
        tuning_layout.addWidget(duration_value_label, 0, 5)

        tuning_layout.setColumnStretch(1, 1)
        tuning_layout.setColumnStretch(4, 1)
        card_layout.addWidget(tuning_frame)

        self.weapon_rows[weapon_type] = {
            "style_combo": style_combo,
            "duck_slider": duck_slider,
            "duck_label": duck_value_label,
            "duration_slider": duration_slider,
            "duration_label": duration_value_label,
        }
        return card

    def _scan_gun_sounds(self):
        self.weapon_styles = {}
        gun_sounds_dir = getattr(self.audio_manager, "gun_sounds_dir", "")
        if not gun_sounds_dir:
            from resource_manager import ResourceManager

            gun_sounds_dir = ResourceManager.get_app_data_path("resources/audio/gun_sounds")
            self.audio_manager.gun_sounds_dir = gun_sounds_dir

        if not os.path.exists(gun_sounds_dir):
            self.logger.warning(f"枪声目录不存在: {gun_sounds_dir}")
            return

        for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST:
            weapon_dir = os.path.join(gun_sounds_dir, profile.gun_type)
            styles = []
            if os.path.exists(weapon_dir):
                styles = list_style_dirs_with_audio(
                    weapon_dir,
                    extensions=DEFAULT_AUDIO_EXTENSIONS,
                    sort=True,
                )
            self.weapon_styles[profile.gun_type] = styles

    def _refresh_style_catalog(self):
        self._scan_gun_sounds()
        self._loading = True
        try:
            for weapon_type, profile in self.weapon_configs.items():
                weapon_row = self.weapon_rows.get(weapon_type)
                if not weapon_row:
                    continue

                style_combo = weapon_row.get("style_combo")
                if style_combo is None:
                    continue

                style_combo.blockSignals(True)
                style_combo.clear()
                style_combo.addItem(self.DISABLED_STYLE_TEXT, "0")
                for style in self.weapon_styles.get(weapon_type, []):
                    style_combo.addItem(style, style)
                index = style_combo.findData(self._get_profile_style(profile))
                style_combo.setCurrentIndex(index if index >= 0 else 0)
                style_combo.blockSignals(False)
        finally:
            self._loading = False

        self._refresh_status_badge()
        self.logger.info("枪声风格列表已刷新")

    @staticmethod
    def _open_audio_resource_root():
        audio_root = get_app_data_dir(os.path.join("resources", "audio", "gun_sounds"))
        QDesktopServices.openUrl(QUrl.fromLocalFile(audio_root))

    def load_settings(self):
        self._loading = True
        try:
            for weapon_type, profile in self.weapon_configs.items():
                weapon_row = self.weapon_rows.get(weapon_type)
                if not weapon_row:
                    continue

                style = self._get_profile_style(profile)
                mute_duration = self._get_profile_mute_duration(profile)
                duck_ratio = self._get_profile_duck_ratio(profile)

                style_combo = weapon_row.get("style_combo")
                if style_combo is not None:
                    index = style_combo.findData(style)
                    style_combo.setCurrentIndex(index if index >= 0 else 0)

                duck_slider = weapon_row.get("duck_slider")
                duck_label = weapon_row.get("duck_label")
                if duck_slider is not None:
                    duck_slider.setValue(int(round(duck_ratio * 100)))
                if duck_label is not None:
                    duck_label.setText(format_percent(duck_ratio))

                duration_slider = weapon_row.get("duration_slider")
                duration_label = weapon_row.get("duration_label")
                if duration_slider is not None:
                    duration_slider.setValue(int(round(mute_duration * 10)))
                if duration_label is not None:
                    duration_label.setText(f"{mute_duration:.1f}秒")
        finally:
            self._loading = False

        self._refresh_status_badge()
        self.logger.info("枪声设置加载完成")

    def _on_weapon_style_changed(self, weapon_type: str, style: str):
        profile = self.weapon_configs.get(weapon_type)
        if not profile:
            return

        normalized_style = resolve_gun_sound_style(style)
        if getattr(self, "_loading", False):
            return

        old_style = self._get_profile_style(profile)
        setattr(config, profile.style_key, normalized_style)
        config.save_config()
        self.logger.info(f"{weapon_type} 风格更新: {old_style} -> {normalized_style}")
        self._refresh_status_badge()

    def _on_weapon_duck_ratio_changed(self, weapon_type: str, value: int):
        profile = self.weapon_configs.get(weapon_type)
        if not profile:
            return

        if weapon_type in self.weapon_rows:
            duck_label = self.weapon_rows[weapon_type].get("duck_label")
            if duck_label is not None:
                duck_label.setText(f"{value}%")

        if getattr(self, "_loading", False):
            return

        setattr(config, profile.duck_ratio_key, value / 100.0)
        config.save_config()
        self._refresh_status_badge()

    def _on_mute_duration_changed(self, weapon_type: str, value: int):
        profile = self.weapon_configs.get(weapon_type)
        if not profile:
            return

        duration = value / 10.0
        if weapon_type in self.weapon_rows:
            duration_label = self.weapon_rows[weapon_type].get("duration_label")
            if duration_label is not None:
                duration_label.setText(f"{duration:.1f}秒")

        if getattr(self, "_loading", False):
            return

        setattr(config, profile.mute_duration_key, duration)
        config.save_config()
        self._refresh_status_badge()

    def _test_gun_sound(self, weapon_type: str):
        profile = self.weapon_configs.get(weapon_type)
        if not profile:
            return

        configured = self._get_profile_style(profile)
        if configured == "0":
            report_preview_failure(self, PreviewFailure.NO_STYLE, weapon_type)
            return

        # RN-046：配过、但那个风格已经不在了 —— 原来这里会照旧去播一个不存在的
        # 音效键，落到下面的 NO_FILE，用户被告知"风格里找不到音频文件"，
        # 于是去翻那个目录 —— 而目录本身已经没了。RN-029 踩过一模一样的坑。
        style = self._effective_style(profile)
        if style == "0":
            report_preview_failure(self, PreviewFailure.STALE_STYLE,
                                   f"{profile.display_name} · {configured}")
            return

        sound_key = f"gun-{weapon_type}-{style}"
        played = self.audio_manager.play_sound(sound_key, channel_type="gun_sound")
        if not played:
            # UP-037: 原来只写日志。枪声没预载/文件缺失时这里是唯一出口,
            # 用户点了完全没反应
            self.logger.warning(f"测试枪声播放失败: {sound_key}")
            report_preview_failure(self, PreviewFailure.NO_FILE, f"{weapon_type} · {style}")

    #: 这一页在社区站的资源分类（RN-165，机制与 RN-153 的音效家族四页同源）。
    COMMUNITY_CATEGORY_KEY = "gun_sound"

    def _library_is_empty(self) -> bool:
        """**一把枪都没有可用风格**——这才叫空库（不是"没配"，是"根本没得配"）。

        ⚠ 「没配」是用户的选择，「没得配」是软件不带素材 ——
        两者的修法完全相反：没配 ⇒ 去配；没得配 ⇒ 先去拿素材。
        """
        return not any(self.weapon_styles.values())

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
            cta_text="去社区拿一套枪声",
            keep_text="打开音频资源",
            keep_callback=self._open_audio_resource_root,
            message=community_library.empty_library_message("风格"),
            callout=getattr(self, "empty_callout", None),   # RN-180
            what="风格",
            refresh_label="刷新风格列表",
        )
        if not applied:
            # ⚠ **借了要还**：空库态借用了 extra 那个位置。
            bar.configure_primary("打开音频资源", self._open_audio_resource_root,
                                  visible=True)
            text, callback, menu = getattr(
                self, "_extra_default", ("新建风格", None, None))
            # ⚠ `_extra_default` 是在 PageActionBar **刚 new 出来**时抓的快照
            # （见上面 __init__），那一刻 extra_btn 还是 `QPushButton("")` ——
            # 抓到的 text 是**空串**、callback 是 None。于是"还回去"的结果是
            # 一颗**没有文字、点了也没反应**的按钮杵在底栏上。
            # 空库时走的是另一条分支（「去社区拿一套枪声」），而**默认状态下库总是空的**
            # （软件不带素材），所以这颗空按钮只有配好素材的用户才看得见 ——
            # 是给官网造演示状态时才第一次撞见。
            # ⇒ 没有文字就别显示它。不凭空补个「新建风格」：这一页没有对应的实现，
            #   补了只会得到一颗点了没反应的按钮，比空着更糟。
            has_text = bool(str(text or "").strip())
            bar.configure_extra(text, callback, visible=has_text)
            bar.extra_btn.setMenu(menu)

    def on_master_switch_synced(self):
        """总开关被别处拨动后，把本页状态重算一遍（RN-189）。

        ⭐ 全仓统一的钩子名（`widgets/master_switch_link` 调它）。
        少了这一下，开关动了而徽章不动 —— 同屏两处说法不一致（RN-107 族）。
        """
        self._refresh_status_badge()

    def _refresh_status_badge(self, *_args):
        enabled = bool(is_gun_sound_master_enabled(config))
        effective = self._effective_styles()
        selected_count = sum(1 for value in effective.values() if value != "0")
        stale_names = self._stale_names()
        current_tab_name, current_weapon_types = self._get_current_tab_info()
        current_count = self._configured_count_for_weapons(current_weapon_types, effective)

        health = collect_category_health(("gun_sounds",))
        detail_tooltip = build_health_detail_tooltip(health)

        configured_text = f"已配置 · {selected_count}/{len(self.weapon_configs)}"
        if stale_names:
            configured_level, configured_text = (
                "warn", f"{configured_text} · {len(stale_names)} 项失效")
        else:
            configured_level = "success" if selected_count else "info"

        badges = [
            ("success" if enabled else "warn", f"开关 · {'已启用' if enabled else '未启用'}"),
            (configured_level, configured_text),
            (
                "success" if current_count else "info",
                f"分类 · {self._compact_text(current_tab_name)} {current_count}/{len(current_weapon_types)}",
            ),
            # RN-035：分级收进 `resource_badge()` 一份 —— 七个音效页原先各抄一遍
            # 这段，七份都把"素材目录还没建"（全新安装的样子）报成**红色异常**。
            resource_badge(health),
        ]

        current_profiles = [self.weapon_configs[weapon] for weapon in current_weapon_types if weapon in self.weapon_configs]
        ratio_values = [self._get_profile_duck_ratio(profile) for profile in current_profiles]
        duration_values = [self._get_profile_mute_duration(profile) for profile in current_profiles]

        detail_lines = [
            f"总开关：{'已启用' if enabled else '已关闭'}",
            f"当前分类：{current_tab_name}",
            f"当前分类已配置：{current_count}/{len(current_weapon_types)}",
            f"全局已配置：{selected_count}/{len(self.weapon_configs)}",
            f"原声保留范围：{self._format_ratio_range(ratio_values)}",
            f"静音覆盖范围：{self._format_duration_range(duration_values)}",
        ]

        preview_names = self._configured_preview_names()
        if preview_names:
            detail_lines.append(f"已配置示例：{', '.join(preview_names)}")
        if detail_tooltip:
            detail_lines.append(detail_tooltip)

        summary_text = "\n".join(detail_lines)
        # 屏幕上那一行：失效 > 资源状态。两者都没有就整行隐藏，不留空白。
        if stale_names:
            shown = "、".join(stale_names[:3])
            more = f" 等 {len(stale_names)} 把" if len(stale_names) > 3 else ""
            hint = (f"{shown}{more}配的风格已经不在了（被改名或删除），"
                    "下面显示成「不启用」，重新选一个即可。")
        else:
            hint = resource_hint(health)
        self.status_hint_label.setText(hint)
        self.status_hint_label.setVisible(bool(hint))

        render_badges(self.status_badge_label, badges, detail_tooltip=summary_text)
        self.summary_label.setText(summary_text)
        self.summary_label.setToolTip(summary_text)
        self.status_card.setToolTip(summary_text)
        if hasattr(self, "action_bar"):
            if enabled:
                action_message = (
                    f"当前分类：{current_tab_name} · 已配置 {current_count}/{len(current_weapon_types)}，"
                    "新增资源后可直接刷新风格列表。"
                )
            else:
                # RN-189：总开关已经在这一页的状态卡里，不必再把用户支去别处。
                action_message = "总开关当前关闭，这里的映射会保留；如新增资源，可先刷新风格列表，再打开总开关。"
            self.action_bar.set_message(action_message)
        # RN-165：空库引导（逻辑在 community_library，只有一份）
        self._sync_community_guidance()
