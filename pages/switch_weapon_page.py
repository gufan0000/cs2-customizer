# SPDX-License-Identifier: GPL-3.0-or-later
"""切枪音效页面。"""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QWidget,
)

from config import config
from core.audio.audio_file_utils import (
    DEFAULT_AUDIO_EXTENSIONS,
    find_first_audio_file,
    list_style_dirs_with_audio,
)
from core.audio.runtime_audio import get_runtime_audio_manager
from core.utils.logger import get_logger
from widgets.preview_feedback import PreviewFailure, report_preview_failure
from pages.audio_status_badge import (
    build_health_detail_tooltip,
    collect_category_health,
    count_enabled_styles,
    render_badges,
)
from pages.sound_page_base import SoundPageBase
from widgets.weapon_row_widget import WeaponRowWidget


class SwitchWeaponPage(SoundPageBase, QWidget):
    """切枪音效设置页面。"""
    #: UP-057 基类用它决定传给 StyleCreatorDialog 的类别
    SOUND_CATEGORY = "switch_weapon"


    DISABLED_STYLE_TEXT = "不启用"

    CATEGORIES = {
        "手枪": [
            "weapon_glock",
            "weapon_usp_silencer",
            "weapon_hkp2000",
            "weapon_p250",
            "weapon_fiveseven",
            "weapon_cz75a",
            "weapon_elite",
            "weapon_deagle",
            "weapon_revolver",
            "weapon_tec9",
        ],
        "冲锋枪": [
            "weapon_mac10",
            "weapon_mp9",
            "weapon_mp7",
            "weapon_ump45",
            "weapon_p90",
            "weapon_bizon",
            "weapon_mp5sd",
        ],
        "步枪": [
            "weapon_ak47",
            "weapon_m4a1",
            "weapon_m4a1_silencer",
            "weapon_famas",
            "weapon_galilar",
            "weapon_aug",
            "weapon_sg556",
        ],
        "狙击枪": ["weapon_awp", "weapon_ssg08", "weapon_scar20", "weapon_g3sg1"],
        "霰弹枪": ["weapon_nova", "weapon_xm1014", "weapon_mag7", "weapon_sawedoff"],
        "机枪": ["weapon_m249", "weapon_negev"],
        "投掷物": ["weapon_hegrenade", "weapon_molotov", "weapon_incgrenade"],
        "近战": ["weapon_knife", "weapon_taser"],
    }

    WEAPON_NAMES = {
        "weapon_glock": "格洛克-18",
        "weapon_usp_silencer": "USP消音版",
        "weapon_hkp2000": "P2000",
        "weapon_p250": "P250",
        "weapon_fiveseven": "Five-SeveN",
        "weapon_cz75a": "CZ75-Auto",
        "weapon_elite": "双持贝瑞塔",
        "weapon_deagle": "沙漠之鹰",
        "weapon_revolver": "R8左轮",
        "weapon_tec9": "Tec-9",
        "weapon_mac10": "MAC-10",
        "weapon_mp9": "MP9",
        "weapon_mp7": "MP7",
        "weapon_ump45": "UMP-45",
        "weapon_p90": "P90",
        "weapon_bizon": "PP-野牛",
        "weapon_mp5sd": "MP5-SD",
        "weapon_ak47": "AK-47",
        "weapon_m4a1": "M4A4",
        "weapon_m4a1_silencer": "M4A1消音版",
        "weapon_famas": "FAMAS",
        "weapon_galilar": "加利尔AR",
        "weapon_aug": "AUG",
        "weapon_sg556": "SG 553",
        "weapon_awp": "AWP",
        "weapon_ssg08": "SSG 08",
        "weapon_scar20": "SCAR-20",
        "weapon_g3sg1": "G3SG1",
        "weapon_nova": "Nova",
        "weapon_xm1014": "XM1014",
        "weapon_mag7": "MAG-7",
        "weapon_sawedoff": "截短霰弹枪",
        "weapon_m249": "M249",
        "weapon_negev": "内格夫",
        "weapon_hegrenade": "高爆手雷",
        "weapon_molotov": "燃烧瓶",
        "weapon_incgrenade": "燃烧弹",
        "weapon_knife": "刀",
        "weapon_taser": "宙斯 x27",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("SwitchWeaponPage")
        self.audio_manager = get_runtime_audio_manager()
        self.weapon_rows: dict[str, WeaponRowWidget] = {}
        self.weapon_switch_styles: dict[str, list[str]] = {}
        self._tab_groups = list(self.CATEGORIES.items())
        self._loading = False

        self.categories = self.CATEGORIES
        self.weapon_names = self.WEAPON_NAMES

        self._ensure_config_defaults()
        self.audio_manager.ensure_styles_scanned()
        self._scan_switch_weapon_styles()
        self._init_ui()
        self.load_settings()

        self.logger.info("切枪音效页面初始化完成")

        # UP-038: 直接把 mp3 拖到页面上就打开「新建风格」并预填文件。
        # StyleCreatorDialog 早就支持 initial_files 了,以前只是没人接这根线——
        # 用户想加一个音效得先找到菜单里的"新建风格…",再在对话框里选文件。
        try:
            from widgets.drop_import_mixin import enable_file_drop

            enable_file_drop(self, DEFAULT_AUDIO_EXTENSIONS, self._on_audio_files_dropped)
        except Exception:
            self.logger.exception("音频拖拽导入初始化失败(不影响其它功能)")

    def _ensure_config_defaults(self):
        if not hasattr(config, "weapon_switch_sounds") or not isinstance(config.weapon_switch_sounds, dict):
            config.weapon_switch_sounds = {}
        for weapons in self.CATEGORIES.values():
            for weapon in weapons:
                config.weapon_switch_sounds.setdefault(weapon, "0")
        if not hasattr(config, "switch_weapon_sound_enabled"):
            config.switch_weapon_sound_enabled = False

    def _get_current_tab_info(self) -> tuple[str, tuple[str, ...]]:
        if not hasattr(self, "tab_widget") or self.tab_widget.count() == 0 or not self._tab_groups:
            return ("未分组", tuple())
        index = self.tab_widget.currentIndex()
        if index < 0 or index >= len(self._tab_groups):
            index = 0
        name, weapons = self._tab_groups[index]
        return name, tuple(weapons)

    def _configured_count_for_weapons(self, weapons: tuple[str, ...] | list[str]) -> int:
        return sum(
            1
            for weapon in weapons
            if str((config.weapon_switch_sounds or {}).get(weapon, "0")).strip() not in {"", "0"}
        )

    def _configured_preview_names(self, max_items: int = 4) -> list[str]:
        names: list[str] = []
        configured = getattr(config, "weapon_switch_sounds", {}) or {}
        for weapons in self.CATEGORIES.values():
            for weapon in weapons:
                if str(configured.get(weapon, "0")).strip() not in {"", "0"}:
                    names.append(self.WEAPON_NAMES.get(weapon, weapon))
                if len(names) >= max_items:
                    return names
        return names

    # ------------------------------------------------ R9-D 基类钩子
    PAGE_TITLE = "切枪音效设置"
    PAGE_LEAD = "切枪音效页继续走紧凑列表路线，把分类切换、风格选择和测试入口都留在首屏，方便快速比对。"
    HELP_KEY = "switch_weapon"
    STYLE_TOOLS_MENU = False

    def _init_ui(self):
        self._build_sound_page_ui()

    def _weapon_styles(self, weapon: str) -> list[str]:
        return self.weapon_switch_styles.get(weapon, [])

    def _configured_style(self, weapon: str) -> str:
        return (config.weapon_switch_sounds or {}).get(weapon, "0")

    def _style_options_for(self, weapon: str) -> list[str]:
        all_options = list(self._get_style_options())
        for style in self._weapon_styles(weapon):
            if style not in all_options:
                all_options.append(style)
        return all_options

    def _test_weapon(self, weapon: str, level=None) -> None:
        self._test_switch_sound(weapon) if level is None else self._test_switch_sound(weapon, level)


    def _scan_switch_weapon_styles(self):
        if not hasattr(self.audio_manager, "switch_weapons_dir"):
            from resource_manager import ResourceManager

            self.audio_manager.switch_weapons_dir = ResourceManager.get_app_data_path("resources/audio/switch_weapons")

        switch_weapons_dir = getattr(self.audio_manager, "switch_weapons_dir", "")
        self.weapon_switch_styles = {}

        if not os.path.exists(switch_weapons_dir):
            self.logger.warning(f"切枪音效目录不存在: {switch_weapons_dir}")
            return

        for weapon in os.listdir(switch_weapons_dir):
            weapon_path = os.path.join(switch_weapons_dir, weapon)
            if os.path.isdir(weapon_path):
                self.weapon_switch_styles[weapon] = list_style_dirs_with_audio(
                    weapon_path,
                    extensions=DEFAULT_AUDIO_EXTENSIONS,
                    sort=True,
                )

    def _get_style_options(self) -> list[str]:
        return [self.DISABLED_STYLE_TEXT]

    def _refresh_style_catalog(self):
        self._scan_switch_weapon_styles()
        self._loading = True
        try:
            generic_options = self._get_style_options()
            for weapon, weapon_row in self.weapon_rows.items():
                all_options = list(generic_options)
                for style in self.weapon_switch_styles.get(weapon, []):
                    if style not in all_options:
                        all_options.append(style)
                weapon_row.update_style_options(all_options)
                weapon_row.set_current_style(
                    self._get_style_display_text((config.weapon_switch_sounds or {}).get(weapon, "0"), weapon)
                )
        finally:
            self._loading = False

        self._refresh_status_badge()
        self.logger.info("切枪音效风格列表已刷新")

    def _on_style_created(self, style_name: str, weapon: str):
        self._refresh_style_catalog()
        if weapon and weapon in self.weapon_rows:
            self.weapon_rows[weapon].set_current_style(style_name)
            self._on_weapon_style_changed(weapon, style_name)
        self.logger.info(f"新建风格已就绪: {style_name} (weapon={weapon})")

    def _get_style_display_text(self, style_value: str, weapon: str) -> str:
        normalized = str(style_value or "0").strip()
        if normalized in {"", "0"}:
            return self.DISABLED_STYLE_TEXT
        if normalized in self.weapon_switch_styles.get(weapon, []):
            return normalized
        return self.DISABLED_STYLE_TEXT

    def load_settings(self):
        self._loading = True
        try:
            for weapon, weapon_row in self.weapon_rows.items():
                style_value = (config.weapon_switch_sounds or {}).get(weapon, "0")
                display_style = self._get_style_display_text(style_value, weapon)
                weapon_row.set_current_style(display_style)
        finally:
            self._loading = False

        self._refresh_status_badge()
        self.logger.info("切枪音效设置加载完成")

    def _on_weapon_style_changed(self, weapon: str, style: str):
        if getattr(self, "_loading", False):
            return

        normalized = "0" if style == self.DISABLED_STYLE_TEXT else str(style or "0")
        old_style = (config.weapon_switch_sounds or {}).get(weapon, "0")
        if old_style == normalized:
            self._refresh_status_badge()
            return

        config.weapon_switch_sounds[weapon] = normalized
        config.save_config()
        self._refresh_status_badge()

        self.logger.info(f"武器 {weapon} 切枪音效更新: {old_style} -> {normalized}")

    def _test_switch_sound(self, weapon: str):
        style_value = (config.weapon_switch_sounds or {}).get(weapon, "0")
        if not style_value or style_value == "0":
            report_preview_failure(self, PreviewFailure.NO_STYLE, weapon)
            return

        sound_key = f"switch-{weapon}-{style_value}"
        sounds = getattr(self.audio_manager, "_sounds", {})

        if sound_key not in sounds:
            style_dir = os.path.join(getattr(self.audio_manager, "switch_weapons_dir", ""), weapon, style_value)
            if not os.path.exists(style_dir):
                self.logger.warning(f"切枪音效目录不存在: {style_dir}")
                report_preview_failure(self, PreviewFailure.NO_FILE, f"{weapon} · {style_value}")
                return

            sound_path = find_first_audio_file(style_dir, extensions=DEFAULT_AUDIO_EXTENSIONS)
            if not sound_path:
                self.logger.warning(f"目录中没有音频文件: {style_dir}")
                report_preview_failure(self, PreviewFailure.NO_FILE, f"{weapon} · {style_value}")
                return

            self.audio_manager.load_sound(
                sound_key,
                sound_path,
                "switch_weapon",
                weapon_id=weapon,
                style=style_value,
            )

        self.logger.info(f"测试切枪音效: {sound_key}")
        if not self.audio_manager.play_sound(sound_key, channel_type="switch_weapon"):
            report_preview_failure(self, PreviewFailure.DEVICE, f"{weapon} · {style_value}")

    def _refresh_status_badge(self, *_args):
        enabled = bool(getattr(config, "switch_weapon_sound_enabled", False))
        selected_count = count_enabled_styles((config.weapon_switch_sounds or {}).values())
        current_tab_name, current_weapons = self._get_current_tab_info()
        current_count = self._configured_count_for_weapons(current_weapons)

        health = collect_category_health(("switch_weapons",))
        detail_tooltip = build_health_detail_tooltip(health)
        health_level = "success"
        if not health["ok"]:
            health_level = "danger"
        elif health["empty"]:
            health_level = "warn"

        badges = [
            ("success" if enabled else "warn", f"开关 · {'已启用' if enabled else '未启用'}"),
            ("success" if selected_count else "info", f"已配置 · {selected_count}"),
            (
                "success" if current_count else "info",
                f"分类 · {self._compact_text(current_tab_name)} {current_count}/{len(current_weapons)}",
            ),
            (
                health_level,
                "资源 · 正常" if health["ok"] else f"资源 · 异常 {health['issue_count']}",
            ),
        ]

        detail_lines = [
            f"总开关：{'已启用' if enabled else '已关闭'}",
            f"当前分类：{current_tab_name}",
            f"当前分类已配置：{current_count}/{len(current_weapons)}",
            f"全部武器已配置：{selected_count}/{sum(len(weapons) for weapons in self.CATEGORIES.values())}",
            "测试策略：按需加载当前武器目录下的首个可用音频文件",
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
        preview_names = self._configured_preview_names()
        self.category_overview_title_label.setText(f"当前分类 · {current_tab_name}")
        self.category_overview_meta_label.setText(
            f"本分类已配置 {current_count}/{len(current_weapons)} · 全局已配置 {selected_count}/{sum(len(weapons) for weapons in self.CATEGORIES.values())}"
        )
        if preview_names:
            self.category_overview_hint_label.setText(
                f"已配置示例：{', '.join(preview_names)} · 测试会按需加载首个可用音频文件。"
            )
        else:
            self.category_overview_hint_label.setText("当前还没有启用切枪音效映射，可逐项试听后再配置。")
        if hasattr(self, "action_bar"):
            if enabled:
                action_message = (
                    f"当前分类：{current_tab_name} · 已配置 {current_count}/{len(current_weapons)}，"
                    "新增资源后可直接刷新风格列表。"
                )
            else:
                action_message = "总开关当前关闭，这里的映射会保留；如新增资源，可先刷新风格列表再回首页启用。"
            self.action_bar.set_message(action_message)
