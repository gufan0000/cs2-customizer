# SPDX-License-Identifier: GPL-3.0-or-later
"""枪声设置页面。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import config, get_app_data_dir
from core.audio.audio_file_utils import (
    DEFAULT_AUDIO_EXTENSIONS,
    list_audio_files,
    list_style_dirs_with_audio,
)
from core.audio.runtime_audio import get_runtime_audio_manager
from widgets.drop_import_mixin import enable_pack_drop, rescan_if_imported
from core.gun_sound_series import find_series, group_style_series
from core.gun_sound_profiles import (
    GUN_SOUND_PROFILES,  # noqa: F401  本文件未直接用，但测试经 gun_sound_page.GUN_SOUND_PROFILES 访问
    MAX_GUN_SOUND_VARIANTS,
    SUPPORTED_GUN_SOUND_PROFILE_LIST,
    SUPPORTED_GUN_SOUND_PROFILES,  # noqa: F401  测试经 gun_sound_page.SUPPORTED_GUN_SOUND_PROFILES 访问
    SUPPORTED_GUN_SOUND_TAB_GROUPS,
    is_gun_sound_master_enabled,
    resolve_gun_sound_style,
    unrecognised_gun_dirs,
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
from ui_style_applier import keep_single_line
from widgets.master_switch_effect import PARAMETER_AREA_PROPERTY
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
from widgets.status_strip import StatusStrip
from widgets.weapon_board import BoardScrollArea, WeaponBoard
from widgets.weapon_row_widget import BRUSH_CAN, STATE_CONFIGURED, STATE_STALE, WeaponRowWidget

#: 微调栏一进来调的是这把（玩家最熟的枪，又是全自动：滑条上那句扫射说明也看得到）。
DEFAULT_TUNING_WEAPON = "ak47"
#: 数值那一列的最小宽：拖滑条时数字位数变了，旁边的滑条不跟着抖。
TUNING_VALUE_MIN_WIDTH = 56


class GunSoundPage(QWidget):
    """枪声设置页面。"""

    DISABLED_STYLE_TEXT = "不启用"
    APPLY_ALL_PLACEHOLDER = "选一套…"

    # ⭐⭐ 类级空默认，不是给「好看」用的：`_scan_gun_sounds` 才是填它们的地方，
    # 而**那个方法可能压根没被调**（三条既有判据自己接管了扫描那一步，实测当场
    # AttributeError）。RN-675 的 `_skipped_unsure` 教训再进一格：那次学到的是
    # 「只写一次、要在任何 return 之前」，这次是「**写在方法里还不够，方法本身
    # 可能不跑**」。⇒ 只读方 `_style_label` / `_unknown_dir_hint` 永远有东西可读。
    style_sample_counts: dict = {}
    unknown_weapon_dirs: list = []
    #: 微调栏现在调的是哪把枪。
    tuning_weapon: str = ""

    @property
    def SAVES_AUTOMATICALLY(self) -> bool:  # noqa: N802  共用回执按这个名字读（master_switch_effect）
        """这一页的改动平时都是自动保存的 —— **除了「整套套用」选了一套还没点按钮的那一刻**。
        外审批 101 第六轮 3/3：底栏常驻的那句自动保存回执 + 预览，玩家以为那一套已经配上了。
        ⇒ 那一刻共用回执让位，底栏改说「还没写入」（`_action_bar_message`）。"""
        return not self._series_pending()

    def _series_pending(self) -> bool:
        combo = getattr(self, "apply_all_combo", None)
        return bool(combo is not None and combo.isEnabled() and combo.currentData())

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("GunSoundPage")
        self.audio_manager = get_runtime_audio_manager()
        self.audio_manager.ensure_styles_scanned()

        self.weapon_configs = {
            profile.gun_type: profile for profile in SUPPORTED_GUN_SOUND_PROFILE_LIST
        }
        self.weapon_rows: dict[str, WeaponRowWidget] = {}
        self.weapon_styles: dict[str, list[str]] = {}
        self._loading = False

        self._scan_gun_sounds()
        self._init_ui()
        self.load_settings()
        enable_pack_drop(self)          # 批 123：下好的整包拖进来 ⇒ 转交「导入资源」

        self.logger.info("枪声设置页面初始化完成")

    def showEvent(self, event):
        super().showEvent(event)
        rescan_if_imported(self, self._refresh_style_catalog)     # 批 123：刚导过包回来就看得见

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
        """页头 → 有事才出现的状态条 → 一个滚动区（武器板）→ 微调栏。结构同四个音效页。

        这一页的风格按枪不同（每把枪一个目录），所以没有风格库，「整套套用」按套系配。
        原声保留、静音覆盖原来是一把枪两根滑条，35 把 70 根；现在一条微调栏，点枪名换一把。
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "枪声设置",
            description="开火后压住原始枪声、换成你自己的音效。手枪、冲锋枪、步枪、狙击枪、霰弹枪、机枪都能换；扫射时会留一点原声当节奏。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["gun_sound"])

        self.status_card = StatusStrip()
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(0, 0, 0, 0)
        status_card_layout.setSpacing(8)

        # RN-189：就地总开关。首页「功能开关」里有「枪声替换」，而站在这一页上
        # 拨不到它 —— 实测首页 17 颗开关里有 8 颗是这个样子。
        # ⚠ 拨动一律走 `MainWindow.set_feature_enabled` ⇒ 首页那颗开关 ⇒ 一整串副作用。
        # **同一件事只能有一条链路**，这里绝不自己 `setattr(config, ...)`。
        from widgets.master_switch_link import make_master_switch_row

        self.master_switch_row = make_master_switch_row(
            self, "gun_sound_enabled", "枪声替换")

        status_header = QHBoxLayout()
        status_header.setSpacing(10)
        self.status_badge_label = create_badge_label()
        status_header.addWidget(self.status_badge_label, 1)
        status_header.addStretch()
        status_card_layout.addLayout(status_header)


        # RN-049：真正会显示的那一行。`summary_label` 是 RN-009 那个"建出来就
        # hide、全仓没人再显示"的死控件——往它写字等于没写（kill_sound 那轮
        # 我已经栽过一次）。所以这里另立一个，**空文案时才隐藏**。
        self.status_hint_label = QLabel("")
        self.status_hint_label.setObjectName("hintLabel")
        self.status_hint_label.setWordWrap(True)
        self.status_hint_label.hide()
        from widgets import community_library as _cl  # RN-197 出口接线

        _cl.wire_stale_route(self.status_hint_label,
                             lambda: self.COMMUNITY_CATEGORY_KEY)
        status_card_layout.addWidget(self.status_hint_label)
        layout.addWidget(self.status_card)

        self.content_scroll = BoardScrollArea(self)
        content = QWidget(self.content_scroll)
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 12)
        body.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        title = QLabel("武器")
        title.setObjectName("cardTitle")
        head.addWidget(title)
        self.weapon_count_label = keep_single_line(QLabel(""))
        self.weapon_count_label.setObjectName("hintLabel")
        self.weapon_count_label.setProperty("fp_index_skip", True)  # 当前值，不进索引（RN-568）
        head.addWidget(self.weapon_count_label)

        self.action_bar = PageActionBar(content, inline=True)
        # RN-165：记下 extra 的原样，空库态要借用这个位置。
        self._extra_default = (self.action_bar.extra_btn.text(),
                               self.action_bar._extra_callback,
                               self.action_bar.extra_btn.menu())
        self.action_bar.configure_secondary("刷新风格列表", self._refresh_style_catalog, visible=True)
        self.action_bar.configure_primary("打开音频资源", self._open_audio_resource_root, visible=True)
        head.addWidget(self.action_bar, 1)
        body.addLayout(head)

        # RN-180：空库时的第一步放在这里 —— 困惑发生的位置。
        from widgets.community_library import EmptyLibraryCallout

        self.empty_callout = EmptyLibraryCallout(content, large=True)
        body.addWidget(self.empty_callout.frame)

        self.weapon_section = QWidget(content)
        section = QVBoxLayout(self.weapon_section)
        section.setContentsMargins(0, 0, 0, 0)
        section.setSpacing(8)
        # ⭐⭐⭐ RN-181（批 50）：这一页正是立案原文点名的那个「34 把枪逐个下拉」。
        # ⚠ 而它**不继承 `SoundPageBase`** —— 改基类那一刀天生落不到它头上，
        #   实测四页里只有它没拿到。⇒ 这里单独实现一份，行为与基类那份对齐。
        section.addLayout(self._build_apply_all_row())
        self.weapon_board = self._build_weapon_board()
        section.addWidget(self.weapon_board)
        body.addWidget(self.weapon_section)
        body.addStretch(1)

        self.content_scroll.setWidget(content)
        self.content_scroll.availableWidthChanged.connect(self.weapon_board.set_available_width)
        layout.addWidget(self.content_scroll, 1)

        self.tuning_strip = self._build_tuning_strip()
        layout.addWidget(self.tuning_strip)
        self._select_tuning_weapon(DEFAULT_TUNING_WEAPON if DEFAULT_TUNING_WEAPON in self.weapon_rows
                                   else next(iter(self.weapon_rows)))

    def _build_weapon_board(self) -> WeaponBoard:
        board = WeaponBoard()
        for group_name, weapon_types in SUPPORTED_GUN_SOUND_TAB_GROUPS:
            board.add_group(group_name, [self._build_weapon_cell(weapon) for weapon in weapon_types])
        return board

    def _build_weapon_cell(self, weapon_type: str) -> WeaponRowWidget:
        cell = WeaponRowWidget(self.weapon_configs[weapon_type].display_name, weapon_type, [])
        cell.set_brush_state(BRUSH_CAN)     # 点枪名有反应：手型光标和悬停描边
        combo = cell.style_combo
        combo.addItem(self.DISABLED_STYLE_TEXT, "0")
        for style in self.weapon_styles.get(weapon_type, []):
            combo.addItem(self._style_label(weapon_type, style), style)
        combo.currentIndexChanged.connect(
            lambda _index, weapon=weapon_type, box=combo: self._on_weapon_style_changed(
                weapon, box.currentData()
            )
        )
        # 动过哪一把，微调栏就跟到哪一把
        combo.activated.connect(lambda _index, weapon=weapon_type: self._select_tuning_weapon(weapon))
        cell.nameClicked.connect(lambda weapon=weapon_type: self._select_tuning_weapon(weapon))
        cell.testClicked.connect(lambda weapon=weapon_type: self._on_cell_test(weapon))
        self.weapon_rows[weapon_type] = cell
        return cell

    def _on_cell_test(self, weapon_type: str) -> None:
        self._select_tuning_weapon(weapon_type)
        self._test_gun_sound(weapon_type)

    def _build_tuning_strip(self) -> QFrame:
        """微调栏：钉在滚动区外面，翻到哪都够得着。"""
        strip = QFrame(self)
        strip.setObjectName("tuningStrip")
        strip.setProperty(PARAMETER_AREA_PROPERTY, True)   # 总开关关着时跟着降权
        box = QVBoxLayout(strip)
        box.setContentsMargins(0, 10, 0, 0)
        box.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.tuning_name_label = keep_single_line(QLabel(""))
        self.tuning_name_label.setObjectName("cardTitle")
        self.tuning_name_label.setMinimumWidth(110)
        row.addWidget(self.tuning_name_label)

        # RN-052：这两个词是音频工程术语，所以解释挂在 tooltip 上（`_select_tuning_weapon`）。
        self.duck_caption = keep_single_line(QLabel("原声保留"))
        row.addWidget(self.duck_caption)
        self.duck_slider = QSlider(Qt.Horizontal)
        self.duck_slider.setMinimum(0)
        self.duck_slider.setMaximum(100)
        self.duck_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.duck_slider.valueChanged.connect(
            lambda value: self._on_weapon_duck_ratio_changed(self.tuning_weapon, value)
        )
        row.addWidget(self.duck_slider, 1)
        self.duck_label = keep_single_line(QLabel(""))
        self.duck_label.setMinimumWidth(TUNING_VALUE_MIN_WIDTH)
        row.addWidget(self.duck_label)

        duration_tip = ("每次开火后压住原声的时长。太短会听到原声的尾巴，"
                        "太长会盖掉下一枪；点得快的枪往短了调。")
        self.duration_caption = keep_single_line(QLabel("静音覆盖"))
        self.duration_caption.setToolTip(duration_tip)
        row.addWidget(self.duration_caption)
        self.duration_slider = QSlider(Qt.Horizontal)
        self.duration_slider.setMinimum(10)
        self.duration_slider.setMaximum(100)
        self.duration_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.duration_slider.setToolTip(duration_tip)
        self.duration_slider.valueChanged.connect(
            lambda value: self._on_mute_duration_changed(self.tuning_weapon, value)
        )
        row.addWidget(self.duration_slider, 1)
        self.duration_label = keep_single_line(QLabel(""))
        self.duration_label.setMinimumWidth(TUNING_VALUE_MIN_WIDTH)
        row.addWidget(self.duration_label)
        box.addLayout(row)

        # 2026-09-17 外审判断题「玩家会不会知道扫射时会留一点原声」12/12 答不会：
        # 那句话埋在页头长句末尾，而滑条本身一个字没提扫射。⇒ 贴着滑条说，一句话说完。
        self.tuning_hint_label = QLabel("点上面的枪名换一把。全自动枪扫射时会留一点原声当节奏，不是整段换掉。")
        self.tuning_hint_label.setObjectName("hintLabel")
        self.tuning_hint_label.setWordWrap(True)
        box.addWidget(self.tuning_hint_label)
        return strip

    def _select_tuning_weapon(self, weapon_type: str) -> None:
        profile = self.weapon_configs.get(weapon_type)
        if profile is None:
            return
        previous = self.weapon_rows.get(self.tuning_weapon)
        if previous is not None:
            previous.set_selected(False)
        self.tuning_weapon = weapon_type
        self.weapon_rows[weapon_type].set_selected(True)
        self.tuning_name_label.setText(profile.display_name)

        duck_tip = ("开火时游戏原本的枪声保留多少音量。0% = 完全听不到原声，"
                    "只剩你换上的音效；调高就是两个声音叠在一起。")
        if profile.automatic:
            # 外审判断题（批 100）：玩家只看控件名 ⇒ 扫射那句也挂在控件上，零像素。
            duck_tip += "扫射时实际会留到这个值的约 1.1 倍当节奏，不是整段换掉。"
        self.duck_caption.setToolTip(duck_tip)
        self.duck_slider.setToolTip(duck_tip)
        self._sync_tuning_values()

    def _sync_tuning_values(self) -> None:
        """把滑条摆到这把枪的值上。⚠ 这不是用户在调，不落配置。"""
        profile = self.weapon_configs.get(self.tuning_weapon)
        if profile is None:
            return
        duck_ratio = self._get_profile_duck_ratio(profile)
        mute_duration = self._get_profile_mute_duration(profile)
        was_loading = self._loading
        self._loading = True
        try:
            self.duck_slider.setValue(int(round(duck_ratio * 100)))
            self.duration_slider.setValue(int(round(mute_duration * 100)))
        finally:
            self._loading = was_loading
        self.duck_label.setText(format_percent(duck_ratio))
        self.duration_label.setText(f"{mute_duration:.2f}秒")

    def _sync_weapon_board(self, effective: dict[str, str]) -> None:
        for weapon_type, cell in self.weapon_rows.items():
            if stale_style_name(self._get_profile_style(self.weapon_configs[weapon_type]),
                                self.weapon_styles.get(weapon_type, [])):
                cell.set_cell_state(STATE_STALE)
            else:
                cell.set_cell_state(STATE_CONFIGURED if effective.get(weapon_type, "0") != "0" else "")
        count = sum(1 for style in effective.values() if style != "0")
        self.weapon_count_label.setText(f"已配置 {count} / {len(self.weapon_configs)}")

    def _style_label(self, weapon_type: str, style: str) -> str:
        """下拉里那一项的文字：风格名 + 取样数（RN-676，叙事在档案）。

        ⭐ 落点是下拉**选项**，不是卡片上新加一行 —— RN-049 刚删掉「每张卡一句」
        （全新安装 18 句一字不差）。⛔ 1 个取样不标：那是默认情形，标了就是 18 份噪音。
        """
        count = int((self.style_sample_counts.get(weapon_type) or {}).get(style, 0))
        if count <= 1:
            return style
        if count <= MAX_GUN_SOUND_VARIANTS:
            return f"{style} · {count} 个取样"
        return f"{style} · {count} 个取样（只用前 {MAX_GUN_SOUND_VARIANTS} 个）"

    def _unknown_dir_hint(self) -> str:
        """「装着素材但代号不对」的目录 ⇒ 屏幕上那一句。没有就空串。"""
        unknown = getattr(self, "unknown_weapon_dirs", None) or []
        if not unknown:
            return ""
        shown = "、".join(name for name, _near in unknown[:2])
        more = f" 等 {len(unknown)} 个" if len(unknown) > 2 else ""
        fixes = [f"{name} 大概想写 {near}" for name, near in unknown[:2] if near]
        tail = ("；" + "、".join(fixes)) if fixes else ""
        return (f"资源目录里的 {shown}{more} 装着素材，但它不是任何一把枪的代号，"
                f"所以这一页读不到、进游戏也不会响{tail}。"
                "目录名必须用武器代号（例如 ak47、m4a1_silencer），"
                "点「打开音频资源」可以对照现有目录改名。")

    def _scan_gun_sounds(self):
        self.weapon_styles = {}
        self.style_sample_counts = {}
        self.unknown_weapon_dirs = []
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
            counts = {}
            if os.path.exists(weapon_dir):
                styles = list_style_dirs_with_audio(
                    weapon_dir,
                    extensions=DEFAULT_AUDIO_EXTENSIONS,
                    sort=True,
                )
                for style in styles:
                    counts[style] = len(list_audio_files(
                        os.path.join(weapon_dir, style),
                        extensions=DEFAULT_AUDIO_EXTENSIONS,
                        sort=False,
                    ))
            self.weapon_styles[profile.gun_type] = styles
            self.style_sample_counts[profile.gun_type] = counts

        self.unknown_weapon_dirs = unrecognised_gun_dirs(gun_sounds_dir)

    def _refresh_style_catalog(self):
        self._scan_gun_sounds()
        self._loading = True
        try:
            for weapon_type, profile in self.weapon_configs.items():
                weapon_row = self.weapon_rows.get(weapon_type)
                if weapon_row is None:
                    continue

                style_combo = weapon_row.style_combo
                style_combo.blockSignals(True)
                style_combo.clear()
                style_combo.addItem(self.DISABLED_STYLE_TEXT, "0")
                for style in self.weapon_styles.get(weapon_type, []):
                    style_combo.addItem(self._style_label(weapon_type, style), style)
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
                if weapon_row is None:
                    continue
                style_combo = weapon_row.style_combo
                index = style_combo.findData(self._get_profile_style(profile))
                style_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self._loading = False

        self._sync_tuning_values()
        self._refresh_status_badge()
        self.logger.info("枪声设置加载完成")

    # ---- 整套套用（按套系，2026-09-17 批 101）：枪声风格是 per-gun 目录、各枪名字不同，
    # 按名字套只能配到 1 把 ⇒ 下拉放**套系**（`core/gun_sound_series`），各枪各配各的。
    # ⚠ 按钮仍叫「应用到全部武器」（批 50 行为题玩家自己说的词，判据钉着）。

    def _build_apply_all_row(self):
        """「整套套用」那一行（RN-181）：选一个**套系** → 各枪各配各的。"""
        from PySide6.QtWidgets import QHBoxLayout

        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)
        self.apply_all_row = row

        self.apply_all_label = QLabel("整套套用")
        self.apply_all_label.setToolTip(
            "套系 = 名字开头相同的一组风格。素材作者给每把枪起的名字不一样"
            "（离子AK、离子战神、离子大狙…），按开头归成一套，各枪各配各的。")
        row.addWidget(self.apply_all_label)
        self.apply_all_combo = QComboBox()
        self.apply_all_combo.setMinimumWidth(170)
        self.apply_all_combo.setMinimumHeight(32)
        self.apply_all_combo.setToolTip(self.apply_all_label.toolTip())
        row.addWidget(self.apply_all_combo)

        self.apply_all_btn = QPushButton("应用到全部武器")
        self.apply_all_btn.setObjectName("secondaryButton")
        self.apply_all_btn.setMinimumHeight(32)
        self.apply_all_btn.clicked.connect(self._apply_style_to_all_weapons)
        self.apply_all_combo.currentIndexChanged.connect(
            lambda _i: self._sync_apply_all_hint())
        row.addWidget(self.apply_all_btn)

        self.apply_all_hint = QLabel("")
        self.apply_all_hint.setObjectName("hintLabel")
        self.apply_all_hint.setWordWrap(True)
        row.addWidget(self.apply_all_hint, 1)
        return row

    def _sync_apply_all_visibility(self) -> None:
        # 一个可用的风格都没有时这一行整个不出现：上面那条空库引导已经在说
        # （下拉第一项永远是占位，所以是 > 1）
        inline = self.apply_all_combo.count() > 1
        for w in (getattr(self, "apply_all_label", None), self.apply_all_combo,
                  self.apply_all_btn, self.apply_all_hint):
            if w is not None:
                w.setVisible(inline)
        # ⚠ 光把控件 hide 掉，布局仍会为这一行留下 spacing ⇒ 间距也一并收掉。
        row = getattr(self, "apply_all_row", None)
        if row is not None:
            row.setSpacing(8 if inline else 0)
            row.setContentsMargins(0, 0, 0, 0)

    def _style_series(self):
        """磁盘上现有的风格按套系归好（每次从 `weapon_styles` 现算，35 把 × 几个名字，很便宜）。"""
        disabled = getattr(self, "DISABLED_STYLE_TEXT", "不启用")
        catalog = {g: [s for s in (self.weapon_styles.get(g, []) or []) if s and s != disabled]
                   for g in self.weapon_configs}
        return group_style_series(catalog)

    def _current_series(self):
        key = self.apply_all_combo.currentData() if hasattr(self, "apply_all_combo") else None
        return find_series(self._style_series(), key) if key else None

    def _series_targets(self, series) -> dict[str, str]:
        """这一套会配到的枪 → 风格（只算这一页真有的枪）。"""
        if series is None:
            return {}
        return {g: s for g, s in series.picks.items() if g in self.weapon_configs}

    def _sync_apply_all_row(self) -> None:
        if not hasattr(self, "apply_all_combo"):
            return
        series = self._style_series()
        keep = self.apply_all_combo.currentData()
        self.apply_all_combo.blockSignals(True)
        self.apply_all_combo.clear()
        # 外审批 101 第二轮 3/3：预选着「离子 · 9 把」+ 底栏那句自动保存回执，
        # 玩家会以为这一套已经配上了 ⇒ 第一项是占位，不选就什么都不预览、按钮也不亮。
        self.apply_all_combo.addItem(self.APPLY_ALL_PLACEHOLDER, None)
        for item in series:
            self.apply_all_combo.addItem(item.label, item.key)
        index = self.apply_all_combo.findData(keep) if keep else -1
        self.apply_all_combo.setCurrentIndex(index if index >= 0 else 0)
        self.apply_all_combo.blockSignals(False)

        usable = bool(series)
        self.apply_all_combo.setEnabled(usable)
        self._sync_apply_all_visibility()
        if usable:
            self._sync_apply_all_hint()
        else:
            self.apply_all_btn.setEnabled(False)
            self.apply_all_hint.setText("还没有可用的风格 —— 先导入或新建一个")

    def _describe_series(self, series, *, limit: int = 3) -> str:
        """提示句：**点下去谁会配上哪个**，最多点 `limit` 把的名，其余说一个数。

        外审批 101 第一轮：下拉预选着「离子 · 9 把」而下面全是「不启用」，2/2 报
        「误以为已生效」⇒ 句子以「点右边按钮会…」开头，它是预告不是状态。
        """
        targets = self._series_targets(series)
        if not targets:
            return ""
        rest = len(self.weapon_configs) - len(targets)
        names = {g: self.weapon_configs[g].display_name for g in targets}
        ordered = [g for g in self.weapon_configs if g in targets]
        # 例子里名字不重复：「AK-47→离子AK、M4A4→离子AK、Galil→离子AK…」读起来像所有枪都配同一个。
        shown, seen = [], set()
        for g in ordered:
            if targets[g] not in seen:
                shown.append(g)
                seen.add(targets[g])
            if len(shown) >= limit:
                break
        shown += [g for g in ordered if g not in shown][: limit - len(shown)]
        more = "…" if len(ordered) > limit else ""
        verb = f"还没配上。点「{self.apply_all_btn.text()}」"
        if len(targets) == 1:
            head = f"{verb}只会给 {names[ordered[0]]} 配上「{targets[ordered[0]]}」"
        elif len(set(targets.values())) == 1:
            head = (f"{verb}会给 {len(targets)} 把都配上「{targets[ordered[0]]}」："
                    + "、".join(names[g] for g in shown) + more)
        else:
            head = (f"{verb}会给 {len(targets)} 把配上："
                    + "、".join(f"{names[g]}→{targets[g]}" for g in shown) + more)
        tail = f"；其余 {rest} 把保持原样。" if rest else "。"
        return head + tail

    def _series_mapping_lines(self, series) -> list[str]:
        targets = self._series_targets(series)
        return [f"{self.weapon_configs[g].display_name} → {targets[g]}"
                for g in self.weapon_configs if g in targets]

    def _sync_apply_all_hint(self) -> None:
        if not hasattr(self, "apply_all_hint") or not self.apply_all_combo.isEnabled():
            return
        series = self._current_series()
        # 没选就不预览、按钮不亮：亮着的按钮 + 一段预览，看起来像「已经配好了」。
        self.apply_all_btn.setEnabled(series is not None)
        self.apply_all_hint.setText(self._describe_series(series)
                                    or f"选一套，再点「{self.apply_all_btn.text()}」；每把枪用这一套里自己的声音。")
        # 完整映射挂在提示句上（零像素）：例子只举三把，想看全的悬停就有。
        self.apply_all_hint.setToolTip("\n".join(self._series_mapping_lines(series)))
        # 底栏那条回执跟着走（选了一套 ⇒ 这一页此刻有一件事要点按钮）。
        bar = getattr(self, "action_bar", None)
        if bar is not None:
            bar.set_message(self._action_bar_message())

    def _action_bar_message(self) -> str:
        series = self._current_series() if self._series_pending() else None
        if series is not None:
            return (f"「整套套用」选了「{series.key}」这一套，还没写入 —— "
                    f"点「{self.apply_all_btn.text()}」才会配上；别的改动照旧自动保存。")
        enabled = bool(is_gun_sound_master_enabled(config))
        if enabled:
            count = sum(1 for style in self._effective_styles().values() if style != "0")
            return (f"已配置 {count}/{len(self.weapon_configs)}，"
                    "新增资源后可直接刷新风格列表。")
        # RN-189：总开关已经在这一页的状态卡里，不必再把用户支去别处。
        return "总开关当前关闭，这里的映射会保留；如新增资源，可先刷新风格列表，再打开总开关。"

    def _apply_style_to_all_weapons(self) -> None:
        """⚠ 会覆盖能用它的每一把枪已有的设置（RN-506 的破坏性那一侧）⇒ 先问，且逐把列出谁配哪个。"""
        from PySide6.QtWidgets import QMessageBox

        series = self._current_series()
        gun_types = list(self.weapon_configs)
        targets = self._series_targets(series)
        if series is None or not gun_types:
            return
        skipped = len(gun_types) - len(targets)
        if not targets:
            QMessageBox.information(
                self, "没有武器能用这一套",
                f"这 {len(gun_types)} 把武器都没有「{series.key}」这一套的素材。")
            return

        effective = {g: self._effective_style(self.weapon_configs[g]) for g in targets}
        already = sum(1 for g, s in targets.items() if effective[g] == s)
        changing = len(targets) - already
        # 「覆盖」只算真配过别的风格的那几把；从「不启用」配上去的不叫覆盖。
        overwriting = sum(1 for g, s in targets.items() if effective[g] not in ("0", s))
        if changing == 0:
            QMessageBox.information(
                self, "无需改动",
                f"「{series.key}」这一套能配的那 {len(targets)} 把武器已经全都配好了。")
            return

        ordered = [g for g in gun_types if g in targets]
        lines = []
        for g, line in zip(ordered, self._series_mapping_lines(series)):
            alt = [s for s in series.alternatives.get(g, ()) if s != targets[g]]
            if alt:
                line += f"（还有 {'、'.join(alt)} 可选，套完可以再换）"
            lines.append(line)
        if len(lines) > 12:
            lines = lines[:12] + [f"…等 {len(ordered)} 把"]
        skipped_line = (f"\n另有 {skipped} 把武器没有这一套的素材，会保持原样。"
                        if skipped else "")
        reply = QMessageBox.question(
            self, "应用到全部武器？",
            f"会把「{series.key}」这一套配给 {len(targets)} 把武器"
            + (f"，其中 {overwriting} 把已配过别的风格、会被覆盖：\n" if overwriting
               else f"（这 {changing} 把目前都没配）：\n")
            + "\n".join(lines) + skipped_line + "\n\n继续吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for gun_type, style in targets.items():
            row = self.weapon_rows.get(gun_type)
            combo = row.style_combo if row is not None else None
            # ⛔ 按 data 找，不按文字：RN-676 之后多取样的项写成「风格 · N 个取样」，
            #    setCurrentText(风格) 对不上就静默不动 ⇒ 确认框说配了、一把都没配。断点 `--only SWEEP`。
            index = combo.findData(style) if combo is not None else -1
            if index >= 0:
                combo.setCurrentIndex(index)   # 经既有信号走落盘
            else:
                self._on_weapon_style_changed(gun_type, style)
        # 动作做完 ⇒ 下拉回到占位：留着「离子 · 9 把」选着，它又成了一个像状态的东西。
        self.apply_all_combo.setCurrentIndex(0)
        self._refresh_status_badge()
        self._sync_apply_all_row()

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

        if weapon_type == self.tuning_weapon:
            self.duck_label.setText(f"{value}%")

        if getattr(self, "_loading", False):
            return

        setattr(config, profile.duck_ratio_key, value / 100.0)
        config.save_config()
        self._refresh_status_badge()

    def _on_mute_duration_changed(self, weapon_type: str, value: int):
        profile = self.weapon_configs.get(weapon_type)
        if not profile:
            return

        duration = value / 100.0
        if weapon_type == self.tuning_weapon:
            self.duration_label.setText(f"{duration:.2f}秒")

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
        # 空库时只留那一块引导：一块全灰的武器板只是噪音，开关也没有东西可管（批 145，RN-734）。
        self.weapon_section.setVisible(not applied)
        self.tuning_strip.setVisible(not applied)
        self.weapon_count_label.setVisible(not applied)
        self.master_switch_row.set_has_content(not applied)
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
        # 风格清单可能刚变过 ⇒「整套套用」的选项跟着走。
        try:
            self._sync_apply_all_row()
        except Exception:
            self.logger.exception("同步「整套套用」那一行失败")
        enabled = bool(is_gun_sound_master_enabled(config))
        effective = self._effective_styles()
        selected_count = sum(1 for value in effective.values() if value != "0")
        stale_names = self._stale_names()
        self._sync_weapon_board(effective)

        health = collect_category_health(("gun_sounds",))
        detail_tooltip = build_health_detail_tooltip(health)

        configured_text = f"已配置 · {selected_count}/{len(self.weapon_configs)}"
        if stale_names:
            configured_level, configured_text = (
                "warn", f"{configured_text} · {len(stale_names)} 项失效")
        else:
            configured_level = "success" if selected_count else "info"

        unknown_hint = self._unknown_dir_hint()
        # RN-035：分级收进 `resource_badge()` 一份 —— 七个音效页原先各抄一遍那段，
        # 七份都把"素材目录还没建"（全新安装的样子）报成**红色异常**。
        resource = resource_badge(health)
        if unknown_hint:
            # ⭐⭐⭐ 外审改后复跑逮到的、**我自己引进来的**：提示行说有个目录读不到，
            # 而这颗徽章还写「资源 · 正常」—— 同屏两处说法不一致（RN-107 族），
            # 且改前没有这个矛盾（那时两处都不说）。⛔ 不改共用函数（七页共用），本页降级。
            resource = ("warn", f"资源 · {len(self.unknown_weapon_dirs)} 个目录读不到")

        badges = [
            ("success" if enabled else "warn", f"开关 · {'已开启' if enabled else '未开启'}"),
            (configured_level, configured_text),
            resource,
        ]

        profiles = list(self.weapon_configs.values())
        ratio_values = [self._get_profile_duck_ratio(profile) for profile in profiles]
        duration_values = [self._get_profile_mute_duration(profile) for profile in profiles]

        detail_lines = [
            f"总开关：{'已开启' if enabled else '未开启'}",
            f"已配置：{selected_count}/{len(self.weapon_configs)}",
            f"原声保留范围：{self._format_ratio_range(ratio_values)}",
            f"静音覆盖范围：{self._format_duration_range(duration_values)}",
        ]

        preview_names = self._configured_preview_names()
        if preview_names:
            detail_lines.append(f"已配置示例：{', '.join(preview_names)}")
        if detail_tooltip:
            detail_lines.append(detail_tooltip)

        if unknown_hint:
            detail_lines.append(unknown_hint)   # 屏幕那一行是择一的，详情永远写全

        summary_text = "\n".join(detail_lines)
        # 屏幕上那一行：代号不对 > 失效 > 资源状态。都没有就整行隐藏，不留空白。
        # ⭐ 代号不对排最前（「你以为装好了」）；压掉的「失效」在徽章里有 warn 色，不会静默。
        if unknown_hint:
            hint = unknown_hint
        elif stale_names:
            shown = "、".join(stale_names[:3])
            more = f" 等 {len(stale_names)} 把" if len(stale_names) > 3 else ""
            from widgets import community_library as _cl  # RN-197

            hint = (f"{shown}{more}配的风格已经不在了（被改名或删除），"
                    "那一格显示成「不启用」，重新选一个即可。"
                    + _cl.stale_style_route(self.COMMUNITY_CATEGORY_KEY))
        elif (health or {}).get("invalid") or (health or {}).get("empty"):
            hint = resource_hint(health)
        else:
            hint = ""   # 还没有素材：上面那条空库引导已经在说
        self.status_hint_label.setText(hint)
        self.status_hint_label.setVisible(bool(hint))

        render_badges(self.status_badge_label, badges, detail_tooltip=summary_text)
        self.status_card.setToolTip(summary_text)
        if hasattr(self, "action_bar"):
            self.action_bar.set_message(self._action_bar_message())
        # RN-165：空库引导（逻辑在 community_library，只有一份）
        self._sync_community_guidance()
