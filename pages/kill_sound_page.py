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
    render_badges,
    resource_badge,
    resource_hint,
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

    def _get_current_category_name(self) -> str:
        """当前分类名。**按下标取 `CATEGORIES` 的键，不拿页签文字当数据键**（RN-028）。

        页签是按 `CATEGORIES` 的顺序建的，所以下标就是身份。
        原来读 `tabText(index)`：页签文案哪天加个计数后缀（「手枪 10/10」这类），
        查表就静默返回 `[]`，分类徽章变成 `0/0` 而**不报错**。
        —— 与 kill_voice 的 RN-020 是同一个缺陷，那页已修，这页一直还在。
        """
        names = list(self.CATEGORIES.keys())
        if not hasattr(self, "tab_widget") or self.tab_widget.count() == 0:
            return names[0] if names else "未分组"
        index = self.tab_widget.currentIndex()
        if index < 0:
            index = 0
        if index < len(names):
            return names[index]
        return self.tab_widget.tabText(index)

    def _get_current_category_weapons(self) -> list[str]:
        return list(self.CATEGORIES.get(self._get_current_category_name(), []))

    # ------------------------------------------------ R9-D 基类钩子
    PAGE_TITLE = "击杀音效设置"
    # ⚠ 页面说明是**写给玩家看的**，不是写给做界面的人看的。
    # 原文「保持列表式效率，把分类切换和快速试听留在一屏里」讲的是版面决策，
    # 玩家读完既不知道这功能干什么、也不知道第一步该做什么。全站有十几处同病，
    # 判据见 tests/test_page_copy_is_user_facing.py。
    # RN-034：原文无条件写「先去「基础设置」打开总开关」，而徽章上同时写着
    # 「开关 · 已启用」—— 自相矛盾。改成陈述总开关在哪；「现在开没开」交给
    # 徽章和底部操作条按状态说（那两处本来就是条件文案）。
    # RN-042：原文还写着「可以按武器类别和**连杀数**分开配」—— 那是做不到的。
    # `weapon_kill_sounds` 只有 weapon → style 一个维度，全仓**不存在**任何
    # 按连杀数分配的配置键（AST 查证）；连杀档位是**风格目录内部**按 1..5
    # 命名的文件，用户选的是整个风格，选不了"第 3 杀用另一套"。
    # 外审两发独立点出「提示可按连杀数分配，但界面上完全找不到入口」——
    # 承诺一件做不到的事，比少说一句更糟。
    PAGE_LEAD = "击杀敌人时播放你自己的音效，逐把枪选风格；一个风格里自带 1~5 连杀的不同音效。点「测试」可以按连杀档位试听；总开关在「基础设置」里。"
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
        # RN-027：这里原先在 `_refresh_style_catalog()` 之后又跟一句 `load_settings()`。
        # 前者已经把 39 把武器的下拉选项和当前值都重设了一遍，后者做的是同一件事的子集 ——
        # 39 把武器白跑一趟，**终态逐字节相同**，所以任何"查结果"的判据都发现不了。
        # 与 kill_voice 的 RN-015 逐字同形。
        self._refresh_style_catalog()

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
            # RN-029：走到这里说明下拉框里那个风格**在两张表里都找不到了** ——
            # 典型触发：在别的页用「管理风格」删掉一个风格，本页下拉还没刷新
            # （`audio_manager` 是跨页共享的运行时单例）。
            # 原来这里 `sound_dir=None` ⇒ 跳过文件检查直接播 ⇒ 播不出来报
            # 「音频设备不可用」，用户被指去查声卡驱动，而真实原因是风格没了。
            report_preview_failure(self, PreviewFailure.STALE_STYLE, style_text)
            return

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
        # RN-026：这里原来是 `count_enabled_styles(config.weapon_kill_sounds.values())`，
        # 数的是**配置里的原始值**；而下面每一行武器显示的是"能不能解析成现有风格"。
        # 两个口径 ⇒ 风格一丢，顶部「已配置 · 37」而列表里 39 把枪全是「不启用」。
        # 现在统一走 `_resolved_style()` 这一个真相源。
        resolved = self._resolved_styles()   # 全页只解析这一次，下面三个口径共用
        selected_count = self._configured_weapon_count(resolved=resolved)
        stale_count = self._stale_weapon_count(resolved)
        current_category = self._get_current_category_name()
        current_weapons = self._get_current_category_weapons()
        current_selected = self._configured_weapon_count(current_weapons, resolved=resolved)

        health = collect_category_health(("kill_sounds", "weapon_kill_sounds"))
        detail_tooltip = build_health_detail_tooltip(health)

        # RN-026：失效项不再被静默算进「已配置」，而是**在同一颗徽章上说出来**。
        # 不新开第五颗徽章是有意的：这一行已经四颗，再加会挤，而且这条信息
        # 只在出问题时才有意义。文案与"短到能单行"的理由都在基类 `_configured_badge`。
        badges = [
            ("success" if enabled else "warn", f"开关 · {'已启用' if enabled else '未启用'}"),
            self._configured_badge(selected_count, stale_count),
            (
                "success" if current_selected else "info",
                f"分类 · {self._compact_text(current_category, '未分组', 8)} {current_selected}/{len(current_weapons)}",
            ),
            # RN-035：资源那颗徽章的分级收进 `audio_status_badge.resource_badge()`
            # 一份（原先七个音效页各抄一遍，七份都把"素材目录还没建"报成红色异常）。
            resource_badge(health),
        ]

        detail_lines = [
            f"总开关：{'已启用' if enabled else '已关闭'}",
            f"当前分类：{current_category}",
            f"当前分类已配置：{current_selected}/{len(current_weapons)}",
            f"全部武器已配置：{selected_count}/{len(self._get_all_weapons())}",
        ]
        if stale_count:
            detail_lines.append(
                f"有 {stale_count} 把枪配的风格已经不在了（被改名或删除），"
                "列表里显示成「不启用」，重新选一个即可。")
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
        # RN-019：这里原本又算了一遍 `_configured_weapon_names()`，
        # 而上面十行之内没有任何东西改变过它的输入 —— 纯重复计算，与 kill_voice 的 RN-014 同形。
        self.category_overview_title_label.setText(f"当前分类 · {current_category}")
        self.category_overview_meta_label.setText(
            f"本分类已配置 {current_selected}/{len(current_weapons)} · 全局已配置 {selected_count}/{len(self._get_all_weapons())}"
        )
        # ⚠ 「怎么修」必须落在**可见**的这一行上。
        # 第一版只写进了 `summary_label` 和 tooltip —— 而 `summary_label` 正是
        # RN-009 那个「建出来就 hide、全仓无人再显示」的死控件，等于没写。
        # 外审复跑时报的「醒目报错却无修复引导，易让玩家误判为软件损坏」就是这个。
        # 优先级：失效项（可行动） > 资源状态（新用户第一次来就该看到的那句） > 已配置示例
        if stale_count:
            self.category_overview_hint_label.setText(self._stale_style_hint(stale_count))
        elif resource_hint(health):
            self.category_overview_hint_label.setText(resource_hint(health))
        elif configured_names:
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
