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
    count_enabled_styles,
    create_badge_label,
    render_badges,
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
        return resolve_gun_sound_style(getattr(config, profile.style_key, "0"))

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

    def _configured_count_for_weapons(self, weapon_types: tuple[str, ...] | list[str]) -> int:
        count = 0
        for weapon_type in weapon_types:
            profile = self.weapon_configs.get(weapon_type)
            if profile and self._get_profile_style(profile) != "0":
                count += 1
        return count

    def _configured_preview_names(self, max_items: int = 3) -> list[str]:
        names = []
        for weapon_type, profile in self.weapon_configs.items():
            if self._get_profile_style(profile) != "0":
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
            description="枪声页更适合先定风格，再快速微调原声保留和静音覆盖，让不同枪型的试听节奏更统一。",
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
        layout.addWidget(self.status_card)

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

    def _create_weapon_card(self, weapon_type: str, display_name: str, styles: list[str]):
        card = QFrame()
        card.setObjectName("card")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        name_label = QLabel(display_name)
        name_label.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        name_label.setMinimumWidth(96)
        title_row.addWidget(name_label)
        style_hint_label = QLabel("镜声风格:")
        style_hint_label.setObjectName("hintLabel")
        title_row.addWidget(style_hint_label)

        style_frame = QFrame()
        style_layout = QHBoxLayout(style_frame)
        style_layout.setContentsMargins(0, 0, 0, 0)
        style_layout.setSpacing(8)

        style_layout.addWidget(QLabel("枪声风格:"))

        style_combo = QComboBox()
        style_combo.setMinimumWidth(220)
        style_combo.setMinimumHeight(34)
        style_combo.addItem(self.DISABLED_STYLE_TEXT, "0")
        for style in styles:
            style_combo.addItem(style, style)
        style_combo.currentIndexChanged.connect(
            lambda _index, weapon=weapon_type, combo=style_combo: self._on_weapon_style_changed(
                weapon, combo.currentData()
            )
        )
        style_layout.addWidget(style_combo)

        test_btn = QPushButton("测试")
        test_btn.setObjectName("secondaryButton")
        test_btn.setFixedWidth(80)
        test_btn.setMinimumHeight(34)
        test_btn.clicked.connect(lambda: self._test_gun_sound(weapon_type))
        style_layout.addWidget(test_btn)

        style_layout.addStretch()
        card_layout.addWidget(style_frame)

        if not styles:
            empty_hint = QLabel("当前没有检测到该武器的可用风格资源，建议先保持“不启用”。")
            empty_hint.setObjectName("hintLabel")
            empty_hint.setWordWrap(True)
            card_layout.addWidget(empty_hint)

        profile = self.weapon_configs[weapon_type]
        duck_ratio = self._get_profile_duck_ratio(profile)
        mute_duration = self._get_profile_mute_duration(profile)

        tuning_frame = QFrame()
        tuning_layout = QGridLayout(tuning_frame)
        tuning_layout.setContentsMargins(0, 0, 0, 0)
        tuning_layout.setHorizontalSpacing(12)
        tuning_layout.setVerticalSpacing(8)

        duck_row = QHBoxLayout()
        duck_row.setSpacing(8)
        duck_row.addWidget(QLabel("原声保留:"))

        duck_slider = QSlider(Qt.Horizontal)
        duck_slider.setMinimum(0)
        duck_slider.setMaximum(100)
        duck_slider.setValue(int(round(duck_ratio * 100)))
        duck_slider.setFixedWidth(140)
        duck_slider.valueChanged.connect(
            lambda value, weapon=weapon_type: self._on_weapon_duck_ratio_changed(weapon, value)
        )
        duck_row.addWidget(duck_slider)

        duck_value_label = QLabel(format_percent(duck_ratio))
        duck_value_label.setFixedWidth(50)
        duck_row.addWidget(duck_value_label)
        duck_row.addStretch()
        tuning_layout.addLayout(duck_row, 0, 0)

        duration_row = QHBoxLayout()
        duration_row.setSpacing(8)
        duration_row.addWidget(QLabel("静音覆盖时长:"))

        duration_slider = QSlider(Qt.Horizontal)
        duration_slider.setMinimum(1)
        duration_slider.setMaximum(10)
        duration_slider.setValue(int(round(mute_duration * 10)))
        duration_slider.setFixedWidth(140)
        duration_slider.valueChanged.connect(
            lambda value, weapon=weapon_type: self._on_mute_duration_changed(weapon, value)
        )
        duration_row.addWidget(duration_slider)

        duration_value_label = QLabel(f"{mute_duration:.1f}秒")
        duration_value_label.setFixedWidth(55)
        duration_row.addWidget(duration_value_label)
        duration_row.addStretch()
        tuning_layout.addLayout(duration_row, 0, 1)
        card_layout.addWidget(tuning_frame)

        self.weapon_rows[weapon_type] = {
            "style_combo": style_combo,
            "duck_slider": duck_slider,
            "duck_label": duck_value_label,
            "duration_slider": duration_slider,
            "duration_label": duration_value_label,
        }
        return card

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

        if not styles:
            empty_hint = QLabel("当前还没有检测到这个武器的可用风格资源，建议先保持“不启用”。")
            empty_hint.setObjectName("hintLabel")
            empty_hint.setWordWrap(True)
            card_layout.addWidget(empty_hint)

        profile = self.weapon_configs[weapon_type]
        duck_ratio = self._get_profile_duck_ratio(profile)
        mute_duration = self._get_profile_mute_duration(profile)

        tuning_frame = QFrame()
        tuning_layout = QGridLayout(tuning_frame)
        tuning_layout.setContentsMargins(0, 0, 0, 0)
        tuning_layout.setHorizontalSpacing(10)
        tuning_layout.setVerticalSpacing(6)

        tuning_layout.addWidget(QLabel("原声保留:"), 0, 0)

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

        tuning_layout.addWidget(QLabel("静音覆盖:"), 0, 3)

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

        style = self._get_profile_style(profile)
        if style == "0":
            report_preview_failure(self, PreviewFailure.NO_STYLE, weapon_type)
            return

        sound_key = f"gun-{weapon_type}-{style}"
        played = self.audio_manager.play_sound(sound_key, channel_type="gun_sound")
        if not played:
            # UP-037: 原来只写日志。枪声没预载/文件缺失时这里是唯一出口,
            # 用户点了完全没反应
            self.logger.warning(f"测试枪声播放失败: {sound_key}")
            report_preview_failure(self, PreviewFailure.NO_FILE, f"{weapon_type} · {style}")

    def _refresh_status_badge(self, *_args):
        enabled = bool(is_gun_sound_master_enabled(config))
        style_values = [
            self._get_profile_style(profile)
            for profile in self.weapon_configs.values()
        ]
        selected_count = count_enabled_styles(style_values)
        current_tab_name, current_weapon_types = self._get_current_tab_info()
        current_count = self._configured_count_for_weapons(current_weapon_types)

        health = collect_category_health(("gun_sounds",))
        detail_tooltip = build_health_detail_tooltip(health)
        health_level = "success"
        if not health["ok"]:
            health_level = "danger"
        elif health["empty"]:
            health_level = "warn"

        badges = [
            ("success" if enabled else "warn", f"开关 · {'已启用' if enabled else '未启用'}"),
            ("success" if selected_count else "info", f"已配置 · {selected_count}/{len(self.weapon_configs)}"),
            (
                "success" if current_count else "info",
                f"分类 · {self._compact_text(current_tab_name)} {current_count}/{len(current_weapon_types)}",
            ),
            (
                health_level,
                "资源 · 正常" if health["ok"] else f"资源 · 异常 {health['issue_count']}",
            ),
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
                action_message = "总开关当前关闭，这里的映射会保留；如新增资源，可先刷新风格列表再回首页启用。"
            self.action_bar.set_message(action_message)
