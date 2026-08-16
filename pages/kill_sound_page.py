# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀音效页面。"""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QWidget,
)

from config import config
from core.audio.audio_file_utils import (
    DEFAULT_AUDIO_EXTENSIONS,
    find_audio_by_stem,
    find_first_audio_file,
)
from core.audio.runtime_audio import get_runtime_audio_manager
from core.utils.logger import get_logger
from pages.audio_status_badge import (
    build_health_detail_tooltip,
    collect_category_health,
    count_enabled_styles,
    render_badges,
)
from pages.sound_page_base import SoundPageBase
from widgets.preview_feedback import PreviewFailure, report_preview_failure
from widgets.weapon_row_widget import WeaponRowWidget


class KillSoundPage(SoundPageBase, QWidget):
    """击杀音效设置页面。"""
    #: UP-057 基类用它决定传给 StyleCreatorDialog 的类别
    SOUND_CATEGORY = "kill_sound"


    DISABLED_STYLE_TEXT = "不启用"

    CATEGORIES = {
        "手枪": [
            "weapon_usp_silencer",
            "weapon_hkp2000",
            "weapon_glock",
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
        "近战": ["weapon_knife", "weapon_taser"],
        "手雷/道具": ["weapon_hegrenade", "weapon_molotov", "weapon_incgrenade"],
    }

    WEAPON_NAMES = {
        "weapon_usp_silencer": "USP-S",
        "weapon_hkp2000": "P2000",
        "weapon_glock": "Glock-18",
        "weapon_p250": "P250",
        "weapon_fiveseven": "Five-SeveN",
        "weapon_cz75a": "CZ75-Auto",
        "weapon_elite": "Dual Berettas",
        "weapon_deagle": "Desert Eagle",
        "weapon_revolver": "R8 Revolver",
        "weapon_tec9": "Tec-9",
        "weapon_mac10": "MAC-10",
        "weapon_mp9": "MP9",
        "weapon_mp7": "MP7",
        "weapon_ump45": "UMP-45",
        "weapon_p90": "P90",
        "weapon_bizon": "PP-Bizon",
        "weapon_mp5sd": "MP5-SD",
        "weapon_ak47": "AK-47",
        "weapon_m4a1": "M4A4",
        "weapon_m4a1_silencer": "M4A1-S",
        "weapon_famas": "FAMAS",
        "weapon_galilar": "Galil AR",
        "weapon_aug": "AUG",
        "weapon_sg556": "SG 553",
        "weapon_awp": "AWP",
        "weapon_ssg08": "SSG 08",
        "weapon_scar20": "SCAR-20",
        "weapon_g3sg1": "G3SG1",
        "weapon_nova": "Nova",
        "weapon_xm1014": "XM1014",
        "weapon_mag7": "MAG-7",
        "weapon_sawedoff": "Sawed-Off",
        "weapon_m249": "M249",
        "weapon_negev": "Negev",
        "weapon_knife": "刀",
        "weapon_taser": "电击枪",
        "weapon_hegrenade": "HE手雷",
        "weapon_molotov": "燃烧弹",
        "weapon_incgrenade": "燃烧瓶",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("KillSoundPage")
        self.audio_manager = get_runtime_audio_manager()
        self.weapon_rows: dict[str, WeaponRowWidget] = {}
        self._loading = False

        self._ensure_config_defaults()
        self.audio_manager.ensure_styles_scanned()

        self._init_ui()
        self.load_settings()

        self.logger.info("击杀音效页面初始化完成")

        # UP-038: 直接把 mp3 拖到页面上就打开「新建风格」并预填文件。
        # StyleCreatorDialog 早就支持 initial_files 了,以前只是没人接这根线——
        # 用户想加一个音效得先找到菜单里的"新建风格…",再在对话框里选文件。
        try:
            from widgets.drop_import_mixin import enable_file_drop

            enable_file_drop(self, DEFAULT_AUDIO_EXTENSIONS, self._on_audio_files_dropped)
        except Exception:
            self.logger.exception("音频拖拽导入初始化失败(不影响其它功能)")

    def _ensure_config_defaults(self):
        if not hasattr(config, "weapon_kill_sounds") or not isinstance(config.weapon_kill_sounds, dict):
            config.weapon_kill_sounds = {}
        for weapons in self.CATEGORIES.values():
            for weapon in weapons:
                config.weapon_kill_sounds.setdefault(weapon, "0")
        if not hasattr(config, "kill_sound_enabled"):
            config.kill_sound_enabled = False

    @staticmethod
    def _is_style_enabled(style_value) -> bool:
        return str(style_value or "").strip() not in {"", "0"}

    def _get_all_weapons(self) -> list[str]:
        weapons: list[str] = []
        for category_weapons in self.CATEGORIES.values():
            weapons.extend(category_weapons)
        return weapons

    def _get_current_category_name(self) -> str:
        if not hasattr(self, "tab_widget") or self.tab_widget.count() == 0:
            return next(iter(self.CATEGORIES.keys()), "未分组")
        index = self.tab_widget.currentIndex()
        if index < 0:
            index = 0
        return self.tab_widget.tabText(index)

    def _get_current_category_weapons(self) -> list[str]:
        return list(self.CATEGORIES.get(self._get_current_category_name(), []))

    def _configured_weapon_count(self, weapons: list[str] | None = None) -> int:
        target_weapons = weapons if weapons is not None else self._get_all_weapons()
        return sum(
            1 for weapon in target_weapons if self._is_style_enabled(config.weapon_kill_sounds.get(weapon, "0"))
        )

    def _configured_weapon_names(self, max_items: int = 4) -> list[str]:
        names = []
        for weapon in self._get_all_weapons():
            if self._is_style_enabled(config.weapon_kill_sounds.get(weapon, "0")):
                names.append(self.WEAPON_NAMES.get(weapon, weapon))
            if len(names) >= max_items:
                break
        return names

    # ------------------------------------------------ R9-D 基类钩子
    PAGE_TITLE = "击杀音效设置"
    # ⚠ 页面说明是**写给玩家看的**，不是写给做界面的人看的。
    # 原文「保持列表式效率，把分类切换和快速试听留在一屏里」讲的是版面决策，
    # 玩家读完既不知道这功能干什么、也不知道第一步该做什么。全站有十几处同病，
    # 判据见 tests/test_page_copy_is_user_facing.py。
    PAGE_LEAD = "击杀敌人时播放你自己的音效，可以按武器类别和连杀数分开配。先去「基础设置」打开总开关，再逐把枪选风格，点「测试」试听。"
    HELP_KEY = "kill_sound"
    TEST_LEVELS = [1, 2, 3, 4, 5]
    STYLE_TOOLS_MENU = True

    def _init_ui(self):
        self._build_sound_page_ui()

    def _weapon_styles(self, weapon: str) -> list[str]:
        return self.audio_manager.weapon_kill_sound_styles.get(weapon, [])

    def _configured_style(self, weapon: str) -> str:
        return config.weapon_kill_sounds.get(weapon, "0")

    def _style_options_for(self, weapon: str) -> list[str]:
        all_options = list(self._get_style_options())
        for style in self._weapon_styles(weapon):
            if style not in all_options:
                all_options.append(style)
        return all_options

    def _test_weapon(self, weapon: str, level=None) -> None:
        self._test_weapon_sound(weapon) if level is None else self._test_weapon_sound(weapon, level)


    def _get_style_options(self) -> list[str]:
        return [self.DISABLED_STYLE_TEXT, *list(getattr(self.audio_manager, "kill_sound_styles", []))]

    def _get_style_display_text(self, style_value: str, weapon: str | None = None) -> str:
        normalized = str(style_value or "0")
        if normalized == "0":
            return self.DISABLED_STYLE_TEXT

        if normalized in getattr(self.audio_manager, "kill_sound_styles", []):
            return normalized

        if weapon and normalized in self.audio_manager.weapon_kill_sound_styles.get(weapon, []):
            return normalized

        return self.DISABLED_STYLE_TEXT

    def _scan_style_catalog(self):
        self.audio_manager.ensure_styles_scanned()
        scan_global = getattr(self.audio_manager, "scan_kill_sound_styles", None)
        if callable(scan_global):
            scan_global()
        scan_weapon = getattr(self.audio_manager, "scan_weapon_kill_sound_styles", None)
        if callable(scan_weapon):
            scan_weapon()

    def _refresh_style_catalog(self):
        self._scan_style_catalog()
        self._loading = True
        try:
            generic_options = self._get_style_options()
            for weapon, weapon_row in self.weapon_rows.items():
                options = list(generic_options)
                for style in self.audio_manager.weapon_kill_sound_styles.get(weapon, []):
                    if style not in options:
                        options.append(style)
                weapon_row.update_style_options(options)
                weapon_row.set_current_style(
                    self._get_style_display_text(config.weapon_kill_sounds.get(weapon, "0"), weapon)
                )
        finally:
            self._loading = False

        self._refresh_status_badge()
        self.logger.info("击杀音效风格列表已刷新")

    def _on_style_created(self, style_name: str, weapon: str):
        self._refresh_style_catalog()
        # 武器专属风格：直接为该武器选中新风格；全局风格进入下拉供用户按需选择
        if weapon and weapon in self.weapon_rows:
            self.weapon_rows[weapon].set_current_style(style_name)
            self._on_weapon_style_changed(weapon, style_name)
        self.logger.info(f"新建风格已就绪: {style_name} (weapon={weapon or '全局'})")

    def _open_style_manager(self):
        """v2.2.1: 管理全局风格——重命名/安全删除，引用自动同步。"""
        from dialogs.style_manager_dialog import StyleManagerDialog

        styles = list(getattr(self.audio_manager, "kill_sound_styles", []))
        if not styles:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(self, "提示", "当前没有可管理的全局风格，可先通过“新建风格”创建。")
            return
        dialog = StyleManagerDialog("kill_sound", "击杀音效", styles, self)
        dialog.styles_changed.connect(self._on_styles_managed)
        dialog.exec()

    def _on_styles_managed(self):
        self._refresh_style_catalog()
        self.load_settings()

    def _on_weapon_style_changed(self, weapon: str, style_text: str):
        if self._loading:
            return

        old_style = config.weapon_kill_sounds.get(weapon, "0")
        new_style = "0" if style_text == self.DISABLED_STYLE_TEXT else style_text
        if old_style == new_style:
            self._refresh_status_badge()
            return

        if bool(getattr(config, "kill_sound_enabled", False)):
            if old_style != "0":
                self.audio_manager.unload_kill_sound_for_weapon(weapon, old_style)
            if new_style != "0":
                self.audio_manager.load_kill_sound_for_weapon(weapon, new_style, True)

        config.weapon_kill_sounds[weapon] = new_style
        config.save_config()
        self._refresh_status_badge()

        self.logger.info(f"武器 {weapon} 音效更新: {old_style} -> {new_style}")

    def _test_weapon_sound(self, weapon: str, level: int = 1):
        """试听武器音效。v2.2.1: level 支持 1-5 连杀档（旧版硬编码只播第 1 连杀）。"""
        weapon_row = self.weapon_rows.get(weapon)
        if weapon_row is None:
            return

        level = int(level) if int(level) in (1, 2, 3, 4, 5) else 1
        style_text = weapon_row.get_current_style()
        if style_text == self.DISABLED_STYLE_TEXT:
            # UP-037: 原来只写日志就 return —— 用户看到的是"点了没反应"
            report_preview_failure(self, PreviewFailure.NO_STYLE, weapon)
            return

        if style_text in getattr(self.audio_manager, "kill_sound_styles", []):
            sound_key = f"kill-{style_text}-{level}"
            sound_dir = os.path.join(self.audio_manager.kill_sounds_dir, style_text)
        elif style_text in self.audio_manager.weapon_kill_sound_styles.get(weapon, []):
            sound_key = f"kill-{weapon}-{style_text}-{level}"
            sound_dir = os.path.join(self.audio_manager.weapon_sounds_dir, weapon, style_text)
        else:
            sound_key = f"kill-{level}"
            sound_dir = None

        # 与 kill_voice 页对齐：试听前按需加载。总开关关闭时风格切换不会
        # 预载音频，不按需加载会静默无声（尤其第 1 连杀档无任何提示）
        if sound_dir:
            sound_file = find_audio_by_stem(sound_dir, str(level), DEFAULT_AUDIO_EXTENSIONS)
            if not sound_file and level == 1:
                sound_file = find_first_audio_file(sound_dir, extensions=DEFAULT_AUDIO_EXTENSIONS)
            if not sound_file:
                report_preview_failure(
                    self, PreviewFailure.NO_FILE,
                    f"{style_text} · {level} 连杀" if level > 1 else style_text)
                return
            current = self.audio_manager._sounds.get(sound_key)
            need_reload = not current or not current.loaded or getattr(current, "path", None) != sound_file
            if need_reload:
                if sound_file and os.path.exists(sound_file):
                    self.audio_manager.load_sound(sound_key, sound_file, "kill_sound", weapon, style_text)
                    self.logger.debug(f"加载音效文件: {sound_file}")
                else:
                    # UP-037: 这条以前只有日志,是"点试听没声音"最常见的静默出口
                    self.logger.warning(f"音效文件不存在或不可识别: {sound_dir}")
                    report_preview_failure(self, PreviewFailure.NO_FILE, style_text)
                    return

        self.logger.info(f"测试音效: {sound_key}")
        played = self.audio_manager.play_sound(sound_key, channel_type="kill_sound")
        if not played:
            # UP-037: 原来只在 level>1 时提示,第 1 连杀播放失败是完全静默的
            report_preview_failure(
                self, PreviewFailure.DEVICE,
                f"{style_text} · {level} 连杀" if level > 1 else style_text)

    def load_settings(self):
        self._loading = True
        try:
            for weapon, weapon_row in self.weapon_rows.items():
                display_style = self._get_style_display_text(config.weapon_kill_sounds.get(weapon, "0"), weapon)
                weapon_row.set_current_style(display_style)
        finally:
            self._loading = False

        self._refresh_status_badge()
        self.logger.info("击杀音效设置加载完成")

    def _refresh_status_badge(self, *_args):
        enabled = bool(getattr(config, "kill_sound_enabled", False))
        selected_count = count_enabled_styles((config.weapon_kill_sounds or {}).values())
        current_category = self._get_current_category_name()
        current_weapons = self._get_current_category_weapons()
        current_selected = self._configured_weapon_count(current_weapons)

        health = collect_category_health(("kill_sounds", "weapon_kill_sounds"))
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
                "success" if current_selected else "info",
                f"分类 · {self._compact_text(current_category, '未分组', 8)} {current_selected}/{len(current_weapons)}",
            ),
            (
                health_level,
                "资源 · 正常" if health["ok"] else f"资源 · 异常 {health['issue_count']}",
            ),
        ]

        detail_lines = [
            f"总开关：{'已启用' if enabled else '已关闭'}",
            f"当前分类：{current_category}",
            f"当前分类已配置：{current_selected}/{len(current_weapons)}",
            f"全部武器已配置：{selected_count}/{len(self._get_all_weapons())}",
        ]
        configured_names = self._configured_weapon_names()
        if configured_names:
            detail_lines.append(f"已配置示例：{', '.join(configured_names)}")
        if detail_tooltip:
            detail_lines.append(detail_tooltip)

        summary_text = "\n".join(detail_lines)
        render_badges(self.status_badge_label, badges, detail_tooltip=summary_text)
        self.summary_label.setText(summary_text)
        self.summary_label.setToolTip(summary_text)
        self.status_card.setToolTip(summary_text)
        configured_names = self._configured_weapon_names()
        self.category_overview_title_label.setText(f"当前分类 · {current_category}")
        self.category_overview_meta_label.setText(
            f"本分类已配置 {current_selected}/{len(current_weapons)} · 全局已配置 {selected_count}/{len(self._get_all_weapons())}"
        )
        if configured_names:
            self.category_overview_hint_label.setText(f"已配置示例：{', '.join(configured_names)}")
        else:
            self.category_overview_hint_label.setText("当前还没有启用击杀音效映射，可切分类逐项试听后再配置。")
        if hasattr(self, "action_bar"):
            if enabled:
                action_message = (
                    f"当前分类：{current_category} · 已配置 {current_selected}/{len(current_weapons)}，"
                    "新增资源后可直接刷新风格列表。"
                )
            else:
                action_message = "总开关当前关闭，这里的映射会保留；如新增资源，可先刷新风格列表再去「基础设置」打开总开关。"
            self.action_bar.set_message(action_message)
