# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀语音页面。"""

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
    render_badges,
    resource_badge,
    resource_hint,
)
from pages.sound_page_base import SoundPageBase
from widgets.preview_feedback import PreviewFailure, report_preview_failure
from widgets.weapon_row_widget import WeaponRowWidget


class KillVoicePage(SoundPageBase, QWidget):
    """击杀语音设置页面。"""
    #: UP-057 基类用它决定传给 StyleCreatorDialog 的类别
    SOUND_CATEGORY = "kill_voice"


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
        # RN-016：这一整个分类原先是缺的 —— 「击杀音效」页有近战、这一页没有，
        # 于是**刀杀和电人能配音效、不能配语音**，而这恰恰是最想要播报的两种击杀。
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
        self.logger = get_logger("KillVoicePage")
        self.audio_manager = get_runtime_audio_manager()
        self.weapon_rows: dict[str, WeaponRowWidget] = {}
        self._loading = False

        self._ensure_config_defaults()
        self.audio_manager.ensure_styles_scanned()

        self._init_ui()
        self.load_settings()

        self.logger.info("击杀语音页面初始化完成")

        # UP-038: 直接把 mp3 拖到页面上就打开「新建风格」并预填文件。
        # StyleCreatorDialog 早就支持 initial_files 了,以前只是没人接这根线——
        # 用户想加一个音效得先找到菜单里的"新建风格…",再在对话框里选文件。
        try:
            from widgets.drop_import_mixin import enable_file_drop

            enable_file_drop(self, DEFAULT_AUDIO_EXTENSIONS, self._on_audio_files_dropped)
        except Exception:
            self.logger.exception("音频拖拽导入初始化失败(不影响其它功能)")

    def _ensure_config_defaults(self):
        if not hasattr(config, "weapon_kill_voices") or not isinstance(config.weapon_kill_voices, dict):
            config.weapon_kill_voices = {}
        for weapons in self.CATEGORIES.values():
            for weapon in weapons:
                config.weapon_kill_voices.setdefault(weapon, "0")
        if not hasattr(config, "kill_voice_enabled"):
            config.kill_voice_enabled = False

    def _get_current_category_name(self) -> str:
        # ⚠ RN-020：原先这里拿 `tab_widget.tabText(index)` 当 `CATEGORIES` 的键。
        # 页签**文字**和数据键是两回事 —— 哪天给页签加个计数后缀（「手枪 3/10」
        # 这类很自然的改动），查表就静默返回 `[]`，分类徽章变成 `0/0` 而不报任何错。
        # 页签是按 `CATEGORIES` 的顺序建的（见基类 `_build_sound_page_ui`），
        # 所以按下标取键才是可靠的；取不到时才退回读文字。
        names = list(self.CATEGORIES.keys())
        if not hasattr(self, "tab_widget") or self.tab_widget.count() == 0:
            return names[0] if names else "未分组"
        index = self.tab_widget.currentIndex()
        if index < 0:
            index = 0
        if 0 <= index < len(names):
            return names[index]
        return self.tab_widget.tabText(index)

    def _get_current_category_weapons(self) -> list[str]:
        return list(self.CATEGORIES.get(self._get_current_category_name(), []))

    # ------------------------------------------------ R9-D 基类钩子
    PAGE_TITLE = "击杀语音设置"
    # RN-034：原文无条件写「先去「基础设置」打开总开关」，而徽章上同时写着
    # 「开关 · 已启用」—— 自相矛盾。改成陈述总开关在哪。
    PAGE_LEAD = "击杀时播报一句语音，连杀会递进（Double Kill、Triple Kill）。逐把枪选风格，点「测试」试听；总开关在「基础设置」里。"
    HELP_KEY = "kill_voice"
    TEST_LEVELS = [1, 2, 3, 4, 5]
    STYLE_TOOLS_MENU = True

    def _init_ui(self):
        self._build_sound_page_ui()

    def _weapon_styles(self, weapon: str) -> list[str]:
        return self.audio_manager.weapon_kill_voice_styles.get(weapon, [])

    def _configured_style(self, weapon: str) -> str:
        return config.weapon_kill_voices.get(weapon, "0")

    def _style_options_for(self, weapon: str) -> list[str]:
        all_options = list(self._get_style_options())
        for style in self._weapon_styles(weapon):
            if style not in all_options:
                all_options.append(style)
        return all_options

    def _test_weapon(self, weapon: str, level=None) -> None:
        self._test_weapon_voice(weapon) if level is None else self._test_weapon_voice(weapon, level)


    def _get_style_options(self) -> list[str]:
        return [self.DISABLED_STYLE_TEXT, *list(getattr(self.audio_manager, "kill_voice_styles", []))]

    def _get_style_display_text(self, style_value: str, weapon: str | None = None) -> str:
        normalized = str(style_value or "0")
        if normalized == "0":
            return self.DISABLED_STYLE_TEXT

        if normalized in getattr(self.audio_manager, "kill_voice_styles", []):
            return normalized

        if weapon and normalized in self.audio_manager.weapon_kill_voice_styles.get(weapon, []):
            return normalized

        return self.DISABLED_STYLE_TEXT

    def _scan_style_catalog(self):
        self.audio_manager.ensure_styles_scanned()
        scan_global = getattr(self.audio_manager, "scan_kill_voice_styles", None)
        if callable(scan_global):
            scan_global()
        scan_weapon = getattr(self.audio_manager, "scan_weapon_kill_voice_styles", None)
        if callable(scan_weapon):
            scan_weapon()

    def _refresh_style_catalog(self):
        self._scan_style_catalog()
        self._loading = True
        try:
            generic_options = self._get_style_options()
            for weapon, weapon_row in self.weapon_rows.items():
                options = list(generic_options)
                for style in self.audio_manager.weapon_kill_voice_styles.get(weapon, []):
                    if style not in options:
                        options.append(style)
                weapon_row.update_style_options(options)
                weapon_row.set_current_style(
                    self._get_style_display_text(config.weapon_kill_voices.get(weapon, "0"), weapon)
                )
        finally:
            self._loading = False

        self._refresh_status_badge()
        self.logger.info("击杀语音风格列表已刷新")

    def _on_style_created(self, style_name: str, weapon: str):
        self._refresh_style_catalog()
        if weapon and weapon in self.weapon_rows:
            self.weapon_rows[weapon].set_current_style(style_name)
            self._on_weapon_style_changed(weapon, style_name)
        self.logger.info(f"新建风格已就绪: {style_name} (weapon={weapon or '全局'})")

    def _open_style_manager(self):
        """v2.2.1: 管理全局风格——重命名/安全删除，引用自动同步。"""
        from dialogs.style_manager_dialog import StyleManagerDialog

        styles = list(getattr(self.audio_manager, "kill_voice_styles", []))
        if not styles:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(self, "提示", "当前没有可管理的全局风格，可先通过“新建风格”创建。")
            return
        dialog = StyleManagerDialog("kill_voice", "击杀语音", styles, self)
        dialog.styles_changed.connect(self._on_styles_managed)
        dialog.exec()

    def _on_styles_managed(self):
        # ⚠ 原先这里还跟一句 `self.load_settings()`，是**整整一遍重复工作**：
        # `_refresh_style_catalog()` 已经逐把武器 `set_current_style(
        # _get_style_display_text(...))` 过一遍、并在末尾刷了状态区，
        # 而 `load_settings()` 做的是**同一个表达式的同一件事**，
        # 36 把武器白跑一趟、状态区白刷一次，终态一模一样。
        self._refresh_style_catalog()

    def _on_weapon_style_changed(self, weapon: str, style_text: str):
        if self._loading:
            return

        old_style = config.weapon_kill_voices.get(weapon, "0")
        new_style = "0" if style_text == self.DISABLED_STYLE_TEXT else style_text
        if old_style == new_style:
            self._refresh_status_badge()
            return

        if bool(getattr(config, "kill_voice_enabled", False)):
            if old_style != "0":
                self.audio_manager.unload_kill_voice_for_weapon(weapon, old_style)
            if new_style != "0":
                self.audio_manager.load_kill_voice_for_weapon(weapon, new_style)

        config.weapon_kill_voices[weapon] = new_style
        config.save_config()
        self._refresh_status_badge()

        self.logger.info(f"武器 {weapon} 语音更新: {old_style} -> {new_style}")

    def _test_weapon_voice(self, weapon: str, level: int = 1):
        """试听击杀语音。v2.2.1: level 支持 1-5 连杀档（旧版硬编码只播第 1 连杀）。"""
        weapon_row = self.weapon_rows.get(weapon)
        if weapon_row is None:
            return

        level = int(level) if int(level) in (1, 2, 3, 4, 5) else 1
        style_text = weapon_row.get_current_style()
        if style_text == self.DISABLED_STYLE_TEXT:
            # RN-040：这里原来**只写一行日志就返回** —— 用户看到的是"点了没反应"。
            # 同 UP-037 那一类（其余各页早就改成给提示了，这页漏下了）。
            # 而且要分清两种情况：真没配 vs 配过但风格已经不在了 ——
            # 后者说「还没选风格」是错的，用户明明选过。
            configured = self._configured_style(weapon)
            if self._is_style_enabled(configured):
                report_preview_failure(self, PreviewFailure.STALE_STYLE,
                                       f"{weapon} · {configured}")
            else:
                report_preview_failure(self, PreviewFailure.NO_STYLE, weapon)
            return

        is_weapon_specific = style_text in self.audio_manager.weapon_kill_voice_styles.get(weapon, [])
        if is_weapon_specific:
            sound_key = f"voice-{weapon}-{style_text}-{level}"
            voice_dir = os.path.join(self.audio_manager.weapon_voices_dir, weapon, style_text)
        else:
            sound_key = f"voice-{style_text}-{level}"
            voice_dir = os.path.join(self.audio_manager.kill_voices_dir, style_text)

        voice_file = find_audio_by_stem(voice_dir, str(level), DEFAULT_AUDIO_EXTENSIONS)
        if not voice_file and level == 1:
            voice_file = find_first_audio_file(voice_dir, extensions=DEFAULT_AUDIO_EXTENSIONS)
        # ⚠ RN-017：原先只有 2~5 连杀会给提示，**第 1 连杀找不到文件时是静默 return 的**
        # （只写一行日志）。同一个「测试」按钮，1 档点了毫无反应、2 档点了有提示 ——
        # 用户只会以为软件坏了。两档一视同仁。
        if not voice_file:
            if level > 1:
                self.action_bar.set_message(
                    f"「{style_text}」这套风格里没有 {level} 连杀的语音文件（{level}.mp3），试听未播放。")
            else:
                self.action_bar.set_message(
                    f"「{style_text}」这套风格的目录里没有可用的语音文件，试听未播放。")
            return

        self.logger.info(f"测试语音: {sound_key}")

        current = self.audio_manager._sounds.get(sound_key)
        need_reload = not current or not current.loaded or current.path != voice_file
        if need_reload:
            if voice_file and os.path.exists(voice_file):
                self.audio_manager.load_sound(sound_key, voice_file, "kill_voice", weapon, style_text)
                self.logger.debug(f"加载语音文件: {voice_file}")
            else:
                # 同 RN-017：文件在扫描后被删/改名时也别静默，用户得知道为什么没声。
                self.logger.warning(f"语音文件不存在或不可识别: {voice_dir}")
                self.action_bar.set_message(
                    f"「{style_text}」的语音文件读不到了（可能已被移动或删除），试听未播放。")
                return

        self.audio_manager.play_voice(sound_key)

    def load_settings(self):
        self._loading = True
        try:
            for weapon, weapon_row in self.weapon_rows.items():
                display_style = self._get_style_display_text(config.weapon_kill_voices.get(weapon, "0"), weapon)
                weapon_row.set_current_style(display_style)
        finally:
            self._loading = False

        self._refresh_status_badge()
        self.logger.info("击杀语音设置加载完成")

    def _refresh_status_badge(self, *_args):
        enabled = bool(getattr(config, "kill_voice_enabled", False))
        # RN-033：本页与 kill_sound 同病 —— `selected_count` 数的是**配置里的原始值**，
        # 而下面每一行显示的是 `_get_style_display_text()`（解析不出来显示「不启用」）。
        # 风格目录一动，顶部「已配置 · N」和列表里一片「不启用」永久对不上，无人报错。
        # 这一页 2026-08-17 关过档，当时 RN-026 还没被发现，所以漏在了这里。
        resolved = self._resolved_styles()
        selected_count = self._configured_weapon_count(resolved=resolved)
        stale_count = self._stale_weapon_count(resolved)
        current_category = self._get_current_category_name()
        current_weapons = self._get_current_category_weapons()
        current_selected = self._configured_weapon_count(current_weapons, resolved=resolved)

        health = collect_category_health(("kill_voices", "weapon_kill_voices"))
        detail_tooltip = build_health_detail_tooltip(health)

        badges = [
            ("success" if enabled else "warn", f"开关 · {'已启用' if enabled else '未启用'}"),
            self._configured_badge(selected_count, stale_count),
            (
                "success" if current_selected else "info",
                f"分类 · {self._compact_text(current_category, '未分组', 8)} {current_selected}/{len(current_weapons)}",
            ),
            # RN-035：分级收进 `resource_badge()` 一份（七页原先各抄一遍，
            # 七份都把"素材目录还没建"报成红色异常）。
            resource_badge(health),
        ]

        detail_lines = [
            f"总开关：{'已启用' if enabled else '已关闭'}",
            f"当前分类：{current_category}",
            f"当前分类已配置：{current_selected}/{len(current_weapons)}",
            f"全部武器已配置：{selected_count}/{len(self._get_all_weapons())}",
            "试听策略：优先匹配 1.*，找不到时回退到目录首个可用音频",
        ]
        configured_names = self._configured_weapon_names(resolved=resolved)
        if configured_names:
            detail_lines.append(f"已配置示例：{', '.join(configured_names)}")
        if detail_tooltip:
            detail_lines.append(detail_tooltip)

        summary_text = "\n".join(detail_lines)
        render_badges(self.status_badge_label, badges, detail_tooltip=summary_text)
        self.summary_label.setText(summary_text)
        self.summary_label.setToolTip(summary_text)
        self.status_card.setToolTip(summary_text)
        # ⚠ 这里原先又算了一遍 `configured_names`：上面第 391 行已经算过，
        # 两次之间没有任何东西会改变它的输入（`config.weapon_kill_voices` 没动过），
        # 所以两次结果必然逐字相同。删掉的是**纯重复计算**，不是行为。
        self.category_overview_title_label.setText(f"当前分类 · {current_category}")
        self.category_overview_meta_label.setText(
            f"本分类已配置 {current_selected}/{len(current_weapons)} · 全局已配置 {selected_count}/{len(self._get_all_weapons())}"
        )
        # RN-033/RN-035：优先级 失效项 > 资源状态 > 已配置示例（见 kill_sound 同处注释）
        if stale_count:
            self.category_overview_hint_label.setText(self._stale_style_hint(stale_count))
        elif resource_hint(health):
            self.category_overview_hint_label.setText(resource_hint(health))
        elif configured_names:
            self.category_overview_hint_label.setText(f"已配置示例：{', '.join(configured_names)}")
        else:
            self.category_overview_hint_label.setText("当前还没有启用击杀语音映射，可切分类逐项试听后再配置。")
        if hasattr(self, "action_bar"):
            if enabled:
                action_message = (
                    f"当前分类：{current_category} · 已配置 {current_selected}/{len(current_weapons)}，"
                    "新增资源后可直接刷新风格列表。"
                )
            else:
                action_message = "总开关当前关闭，这里的映射会保留；如新增资源，可先刷新风格列表再去「基础设置」打开总开关。"
            self.action_bar.set_message(action_message)
