# SPDX-License-Identifier: GPL-3.0-or-later
"""被击杀音效页面。"""

from __future__ import annotations

import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from config import config, get_app_data_dir
from core.audio.audio_file_utils import (
    DEFAULT_AUDIO_EXTENSIONS,
    find_audio_by_stem,
    list_unique_audio_stems,
)
from core.audio.runtime_audio import get_runtime_audio_manager
from core.utils.logger import get_logger
from widgets.preview_feedback import PreviewFailure, report_preview_failure
from pages.audio_status_badge import (
    build_health_detail_tooltip,
    collect_category_health,
    create_badge_label,
    is_style_enabled,
    render_badges,
    resolve_style,
    resource_badge,
    resource_hint,
    stale_style_name,
)
from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
from ui_style_applier import keep_single_line
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
from widgets.status_strip import StatusStrip
from widgets.style_library import StyleLibrary
from widgets.weapon_board import BoardScrollArea


class DeathSoundPage(QWidget):
    """被击杀音效设置页面。"""

    DISABLED_STYLE_TEXT = "不启用"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("DeathSoundPage")
        self.audio_manager = get_runtime_audio_manager()
        self.death_styles: list[str] = []

        self._ensure_config_defaults()
        self.audio_manager.ensure_styles_scanned()

        self._init_ui()
        self.load_settings()

        self.logger.info("被击杀音效页面初始化完成")

        # UP-038: 直接把 mp3 拖到页面上就打开「新建风格」并预填文件。
        # StyleCreatorDialog 早就支持 initial_files 了,以前只是没人接这根线——
        # 用户想加一个音效得先找到菜单里的"新建风格…",再在对话框里选文件。
        try:
            from widgets.drop_import_mixin import enable_file_drop, enable_pack_drop

            enable_file_drop(self, DEFAULT_AUDIO_EXTENSIONS, self._on_audio_files_dropped)
            enable_pack_drop(self)          # 批 123：下好的整包拖进来 ⇒ 转交「导入资源」
        except Exception:
            self.logger.exception("音频拖拽导入初始化失败(不影响其它功能)")

    def _ensure_config_defaults(self):
        if not isinstance(getattr(config, "death_sound_style", "0"), str):
            config.death_sound_style = "0"
        if not hasattr(config, "death_sound_enabled"):
            config.death_sound_enabled = False

    @staticmethod
    def _compact_text(text, fallback="未选择", max_length=12):
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    # ------------------------------- 「配了、但那个风格已经不在了」（RN-033）
    #
    # 本页原先有**三个各说各话的出口**（2026-08-17 探针实测，配置里写着
    # 一个已被删除的风格名）：
    #
    #   徽章        「开关 · 已启用」「样式 · 已删除的风格」
    #   下拉框      「不启用」                （`_reset_style_items` 找不到就退回第 0 项）
    #   选择卡      「当前已选择"已删除的风格"，**切换后可以直接点击测试**确认实际听感」
    #   点「测试」  「还没选风格」            （读的是下拉框）
    #
    # ⇒ 页面明确指示用户去点测试，测试回答"你还没选"。**这是个闭环矛盾**，
    #   而且这一页比 kill_sound 那次更严重：那边只是两个数对不上，这边是
    #   一句明确的操作指引把用户送进一个必然失败的动作。
    #
    # 单一真相源：全页只准通过 `_effective_style_value()` 问"现在到底生效什么"。
    # （武器网格那四页的同款实现在 `pages/sound_page_base.py`；这一页数据模型不同
    #  ——只有一个全局风格、没有 per-weapon 字典——所以不并进那个 mixin。）

    def _configured_style_value(self) -> str:
        """配置里写着的原始值（可能指向一个已经不存在的风格）。"""
        return str(getattr(config, "death_sound_style", "0") or "0")

    def _effective_style_value(self) -> str:
        """**当前真正生效**的风格；配了但风格已经不在了就返回 `"0"`。

        RN-046：解析这一步本身走 `resolve_style()`（全仓唯一一份）。
        上一轮这里是本页自己写的三行 —— 逻辑没错，但它是**第二份副本**，
        而 gun_sound / special_sound 又各要一份 ⇒ 四份。
        RN-002 / RN-031 / RN-032 已经证过三次：**只要还有第二份，
        修好一份就等于没修**，而且漂的时候不报错。
        """
        return resolve_style(self._configured_style_value(), self.death_styles or [])

    def _stale_style_name(self) -> str:
        """配过、但那个风格已经不在了 —— 返回它的名字；否则空串。

        这个名字是唯一可行动的信息（"你原来选的是它，它没了，重新选一个"），
        而它以前在界面上**根本没出现过**：徽章把它当成生效值显示，
        下拉框把它当成不存在直接忽略，两边都没说"它没了"。
        """
        return stale_style_name(self._configured_style_value(), self.death_styles or [])

    def _init_ui(self):
        """页头 → 有事才出现的状态条 → 一个滚动区（风格库）。结构同四个音效页。

        这一页只有一个全局风格，没有武器板：点一张卡就用它，再点一下取消。
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = PageHeader(
            "被击杀音效设置",
            description="自己被击杀时播放一段音效。点一张风格卡就用它，卡上的播放键能试听。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["death_sound"])

        self.status_card = StatusStrip()
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(0, 0, 0, 0)
        status_card_layout.setSpacing(8)

        # RN-189：就地总开关。首页「功能开关」里有「被击杀修改」，而站在这一页上
        # 拨不到它 —— 实测首页 17 颗开关里有 8 颗是这个样子。
        # ⚠ 拨动一律走 `MainWindow.set_feature_enabled` ⇒ 首页那颗开关 ⇒ 一整串副作用。
        # **同一件事只能有一条链路**，这里绝不自己 `setattr(config, ...)`。
        from widgets.master_switch_link import make_master_switch_row

        self.master_switch_row = make_master_switch_row(
            self, "death_sound_enabled", "被击杀音效", header=header)

        status_header = QHBoxLayout()
        status_header.setSpacing(10)
        self.status_badge_label = create_badge_label()
        status_header.addWidget(self.status_badge_label, 1)
        status_header.addStretch()
        status_card_layout.addLayout(status_header)

        layout.addWidget(self.status_card)

        self.content_scroll = BoardScrollArea(self)
        content = QWidget(self.content_scroll)
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 12)
        body.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        title = QLabel("风格库")
        title.setObjectName("cardTitle")
        head.addWidget(title)
        self.library_hint = keep_single_line(QLabel("点一张就用它，再点一下取消"))
        self.library_hint.setObjectName("hintLabel")
        head.addWidget(self.library_hint)

        self.action_bar = PageActionBar(content, inline=True)
        self.action_bar.configure_extra("新建风格", self._open_style_creator, visible=True)
        # RN-165：记下 extra 的原样，空库态要借用这个位置。
        self._extra_default = (self.action_bar.extra_btn.text(),
                               self.action_bar._extra_callback,
                               self.action_bar.extra_btn.menu())
        self.action_bar.configure_secondary("刷新风格列表", self._refresh_style_catalog, visible=True)
        self.action_bar.configure_primary("打开音频资源", self._open_audio_resource_root, visible=True)
        head.addWidget(self.action_bar, 1)
        body.addLayout(head)

        # RN-180：空库时的第一步放在风格库这里 —— 困惑发生的位置。
        from widgets.community_library import EmptyLibraryCallout

        self.empty_callout = EmptyLibraryCallout(content, large=True)
        body.addWidget(self.empty_callout.frame)

        self.style_library = StyleLibrary(content, focus_after=self.action_bar.primary_btn)
        self.style_library.brushChanged.connect(self._on_style_changed)
        self.style_library.auditionRequested.connect(self._test_sound)
        body.addWidget(self.style_library)

        # 有事才说：原来选的风格没了、素材目录不对。选中的是谁，卡片上看得见。
        self.selection_state_label = QLabel("")
        self.selection_state_label.setObjectName("hintLabel")
        self.selection_state_label.setWordWrap(True)
        self.selection_state_label.hide()
        from widgets import community_library as _cl  # RN-197 出口接线

        _cl.wire_stale_route(self.selection_state_label,
                             lambda: self.COMMUNITY_CATEGORY_KEY)
        body.addWidget(self.selection_state_label)
        body.addStretch(1)

        self.content_scroll.setWidget(content)
        layout.addWidget(self.content_scroll, 1)

    def _scan_death_styles(self):
        death_dir = getattr(self.audio_manager, "death_sounds_dir", "")
        self.death_styles = list_unique_audio_stems(
            death_dir,
            extensions=DEFAULT_AUDIO_EXTENSIONS,
            sort=True,
        )

    def _sync_library(self) -> None:
        """卡片跟着磁盘和配置走。

        ⚠ 这不是用户在选，所以不发信号：风格没了也不能把配置改成「不启用」，
        否则说不出「原来选的 X 没了」，那个风格回来了也接不上（RN-033）。
        """
        library = self.style_library
        current = self._effective_style_value()
        blocked = library.blockSignals(True)
        library.set_styles([(style, "正在用" if style == current else "")
                            for style in self.death_styles if is_style_enabled(style)])
        library.set_brush(current if is_style_enabled(current) else "")
        library.blockSignals(blocked)

    def _refresh_style_catalog(self):
        self._scan_death_styles()
        self._refresh_status_badge()
        self.logger.info("被击杀音效风格列表已刷新")

    @staticmethod
    def _open_audio_resource_root():
        audio_root = get_app_data_dir(os.path.join("resources", "audio", "death"))
        QDesktopServices.openUrl(QUrl.fromLocalFile(audio_root))


    def _on_audio_files_dropped(self, paths):
        """UP-038: 拖入音频 → 直接打开「新建风格」对话框并预填。"""
        files = [p for p in (paths or []) if str(p).lower().endswith(DEFAULT_AUDIO_EXTENSIONS)]
        if not files:
            return
        self._open_style_creator(initial_files=files)

    def _open_style_creator(self, initial_files=None):
        """v2.2.1: 一步式新建风格——拖入 1 个音频文件，自动按风格名落盘并刷新。"""
        from dialogs.style_creator_dialog import StyleCreatorDialog

        dialog = StyleCreatorDialog("death_sound", self, audio_manager=self.audio_manager, initial_files=initial_files)
        dialog.style_created.connect(self._on_style_created)
        dialog.exec()

    def _on_style_created(self, style_name: str, _weapon: str):
        self._refresh_style_catalog()
        self.style_library.set_brush(style_name)      # 新建完就用它（走同一条落配置的路）
        self.logger.info(f"新建风格已就绪: {style_name}")

    def showEvent(self, event):
        """v2.2.1: 进页自动重扫（10s 冷却）——手动放文件后不再需要手动点刷新。"""
        super().showEvent(event)
        import time as _time

        now = _time.monotonic()
        last = getattr(self, "_last_auto_refresh", 0.0)
        import core.resource_generation as resource_generation

        imported = resource_generation.take_news(self)      # 批 123：刚导过包就不看冷却
        if imported or now - last >= 10.0:
            self._last_auto_refresh = now
            try:
                self._refresh_style_catalog()
            except Exception:
                self.logger.exception("进页自动刷新风格列表失败")

    def load_settings(self):
        self._scan_death_styles()
        self._refresh_status_badge()
        self.logger.debug(f"加载被击杀音效设置: {self._configured_style_value()}")

    def _on_style_changed(self, style: str):
        style_value = str(style or "0")
        old_style = self._configured_style_value()
        if old_style == style_value:
            self._refresh_status_badge()
            return

        config.death_sound_style = style_value
        config.save_config()
        self._refresh_status_badge()

        self.logger.info(f"被击杀音效风格更新: {old_style} -> {style_value}")

    def _test_sound(self, style: str):
        """卡上的试听：放这张卡的风格，不改配置。"""
        style_value = str(style)
        sound_key = f"death-{style_value}"
        sounds = getattr(self.audio_manager, "_sounds", {})

        if sound_key not in sounds:
            sound_file = find_audio_by_stem(
                getattr(self.audio_manager, "death_sounds_dir", ""),
                style_value,
                extensions=DEFAULT_AUDIO_EXTENSIONS,
            )
            if not sound_file:
                self.logger.warning(f"音效文件不存在: {style_value}.mp3/.wav/.ogg")
                report_preview_failure(self, PreviewFailure.NO_FILE, style_value)
                return

            self.audio_manager.load_sound(
                sound_key,
                sound_file,
                "death_sound",
                style=style_value,
            )

        self.logger.info(f"测试被击杀音效: {sound_key}")
        if not self.audio_manager.play_sound(sound_key):
            report_preview_failure(self, PreviewFailure.DEVICE, style_value)

    #: 这一页在社区站的资源分类（RN-165，机制与 RN-153 的音效家族四页同源）。
    COMMUNITY_CATEGORY_KEY = "death_sound"

    def _library_is_empty(self) -> bool:
        """一个可用风格都没有——这才叫空库（不是"没配"，是"根本没得配"）。

        ⚠ 「没配」是用户的选择，「没得配」是软件不带素材 ——
        两者的修法完全相反：没配 ⇒ 去配；没得配 ⇒ 先去拿素材。
        """
        return not self.death_styles

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
            cta_text="去社区拿一套被击杀音效",
            keep_text="打开音频资源",
            keep_callback=self._open_audio_resource_root,
            message=community_library.empty_library_message("风格"),
            callout=getattr(self, "empty_callout", None),   # RN-180
            what="风格",
            refresh_label="刷新风格列表",
        )
        # 空库时只留那一块引导。没有风格卡，开关也没有东西可管（批 145，RN-734）。
        self.style_library.setVisible(not applied and bool(self.death_styles))
        self.library_hint.setVisible(not applied)
        self.master_switch_row.set_has_content(not applied)
        if not applied:
            # ⚠ **借了要还**：空库态借用了 extra 那个位置。
            bar.configure_primary("打开音频资源", self._open_audio_resource_root,
                                  visible=True)
            text, callback, menu = getattr(
                self, "_extra_default", ("新建风格", None, None))
            bar.configure_extra(text, callback, visible=True)
            bar.extra_btn.setMenu(menu)

    def on_master_switch_synced(self):
        """总开关被别处拨动后，把本页状态重算一遍（RN-189）。

        ⭐ 全仓统一的钩子名（`widgets/master_switch_link` 调它）。
        少了这一下，开关动了而徽章不动 —— 同屏两处说法不一致（RN-107 族）。
        """
        self._refresh_status_badge()

    def _refresh_status_badge(self, *_args):
        self._sync_library()
        enabled = bool(getattr(config, "death_sound_enabled", False))
        # RN-033：这里原来直接读配置的原始值当"当前样式"，而下拉框读的是解析后的值。
        # 统一到用户眼睛看到的那一边 —— 解析不出来就是"没生效"，别再显示成生效。
        current_style = self._effective_style_value()
        style_enabled = is_style_enabled(current_style)
        stale_style = self._stale_style_name()
        available_count = len(getattr(self, "death_styles", []))

        health = collect_category_health(("death",))
        detail_tooltip = build_health_detail_tooltip(health)

        if stale_style:
            # ⚠ 文案必须短到能单行放下（kill_sound 那轮把徽章撑成两行、
            # 比同排另外三颗高一截，而排版审计三条判据一条都没看见）。
            style_badge = ("warn", "风格 · 已失效")
        else:
            style_badge = (
                "success" if style_enabled else "info",
                f"风格 · {self._compact_text(current_style if style_enabled else '未选择')}",
            )
        badges = [
            ("success" if enabled else "warn", f"开关 · {'已开启' if enabled else '未开启'}"),
            style_badge,
            ("success" if available_count else "info", f"候选 · {available_count}"),
            # RN-035：分级收进 `resource_badge()` 一份 —— 七个音效页原先各抄一遍，
            # 七份都把"素材目录还没建"（全新安装的样子）报成**红色异常**。
            resource_badge(health),
        ]

        detail_lines = [
            f"总开关：{'已开启' if enabled else '未开启'}",
            f"当前风格：{current_style if style_enabled else self.DISABLED_STYLE_TEXT}",
            f"已扫描风格：{available_count}",
        ]
        if detail_tooltip:
            detail_lines.append(detail_tooltip)

        summary_text = "\n".join(detail_lines)
        render_badges(self.status_badge_label, badges, detail_tooltip=summary_text)
        self.status_card.setToolTip(summary_text)
        self._sync_selection_state(stale_style, health)
        if hasattr(self, "action_bar"):
            if style_enabled:
                action_message = (
                    f"当前风格：{current_style} · 已扫描 {available_count} 个候选；"
                    "新增素材后可直接刷新风格列表。"
                )
            else:
                action_message = (
                    f"当前未启用风格 · 已扫描 {available_count} 个候选；"
                    "可先打开资源目录补充音频，再回来刷新。"
                )
            self.action_bar.set_message(action_message)
        # RN-165：空库引导（逻辑在 community_library，只有一份）
        self._sync_community_guidance()

    def _sync_selection_state(self, stale_style: str, health: dict | None) -> None:
        """风格库下面那一行：有事才说。"""
        health = health or {}
        if stale_style:
            # RN-033：这一行原先在失效时说的是「当前已选择"<那个已经没了的风格>"，
            # 切换后可以直接点击测试确认实际听感」—— 把用户直接送进一个必然失败的动作。
            from widgets import community_library as _cl  # RN-197

            text = (f"原来选的“{self._compact_text(stale_style)}”已经不在了"
                    "（被改名或删除），重新选一个即可。"
                    + _cl.stale_style_route(self.COMMUNITY_CATEGORY_KEY))
        elif health.get("invalid") or health.get("empty"):
            # RN-035：资源状态那句人话要落在**可见**的行上
            text = resource_hint(health)
        else:
            text = ""   # 还没有素材：上面那条空库引导已经在说
        self.selection_state_label.setText(text)
        self.selection_state_label.setVisible(bool(text))
