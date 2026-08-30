#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
音乐播放器设置页面
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, 
    QComboBox, QCheckBox, QPushButton, QSlider, QGroupBox, QListWidget, 
    QListWidgetItem, QRadioButton, QButtonGroup, QFileDialog, QMessageBox,
    QBoxLayout,
    QInputDialog, QSizePolicy, QGridLayout
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from config import config
from core.utils.logger import get_logger
from core.utils.format_utils import format_percent
from music_player import get_music_player, normalize_music_play_mode
from pages.audio_status_badge import create_badge_label, render_badges
from page_theme_helper import style_as_danger_button, style_as_secondary_button
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
import os
import weakref



# 播放控制栏已移至全局 (music_control_bar.py)


def _link_state_word(link_enabled: bool) -> str:
    """「联动」这一格现在该写哪两个字（RN-407 家族，批 18）。

    ⚠⚠ 这里原来只看子开关 `music_game_link_enabled`，写死「已启用 / 已关闭」。
    于是总开关关着时，同一屏上**总开关写着「未开启」而这里写着「已启用」**。
    实测：外审在这一页 **2/45 判「会以为已经生效」**，措辞直指这颗胶囊
    （「总开关未开启却显示『联动 · 已启用』，极易误导玩家功能已生效」）。

    ⭐⭐ 批 16 把状态胶囊退成了**中性色**，却没有动它说的**话** ——
    颜色不再喊「运行中」了，字还在喊。
    ⭐ **「这个设置开着」和「这件事正在发生」是两回事**，
    而「已启用」这三个字同时承担了这两个意思。
    ⇒ 三态：总开关关着 + 子开关开 = 「**已配置**」（配好了，但没在跑）。
    """
    if not link_enabled:
        return "已关闭"
    return "已启用" if bool(getattr(config, "music_enabled", False)) else "已配置"


class MusicPage(QWidget):
    """音乐播放器设置页面"""

    # 播放器回调可能来自工作线程（默认歌异步添加、加载线程等），
    # 经 queued signal 切回主线程再刷新 QListWidget
    _playlist_updated_sig = Signal()
    _playlist_changed_sig = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = config
        self.logger = get_logger("MusicPage")
        
        # 获取播放器实例
        self.player = get_music_player()
        
        # 设置回调
        self._playlist_update_callback = None
        self._playlist_change_callback = None
        self._bind_player_callbacks()
        
        # 选中的项目索引集合
        self.selected_indices = set()
        
        self.init_ui()
        self.load_settings()
    
    def _bind_player_callbacks(self):
        page_ref = weakref.ref(self)
        self._playlist_updated_sig.connect(self.refresh_playlist_display)
        self._playlist_changed_sig.connect(self.on_playlist_changed)

        def _playlist_update_callback():
            page = page_ref()
            if page is None:
                return
            try:
                page._playlist_updated_sig.emit()  # emit 线程安全，槽在主线程执行
            except RuntimeError:
                return

        def _playlist_change_callback(name=None):
            page = page_ref()
            if page is None:
                return
            try:
                page._playlist_changed_sig.emit(name)
            except RuntimeError:
                return

        self._playlist_update_callback = _playlist_update_callback
        self._playlist_change_callback = _playlist_change_callback
        self.player.on_playlist_update = _playlist_update_callback
        self.player.on_playlist_change = _playlist_change_callback

    def _detach_player_callbacks(self):
        player = getattr(self, "player", None)
        if player is None:
            return

        if getattr(player, "on_playlist_update", None) is self._playlist_update_callback:
            player.on_playlist_update = None
        if getattr(player, "on_playlist_change", None) is self._playlist_change_callback:
            player.on_playlist_change = None

    def init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 上方：设置区域（带滚动）
        settings_container = QWidget()
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(16, 16, 16, 0)
        settings_layout.setSpacing(12)
        
        # 页面标题
        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "音乐播放 / 联动设置",
            # ⚠⚠ RN-455（批 32）：这里原来写「底部控制栏是手动播放」——
            # 而对**没放过音乐的用户，那条栏根本没建**
            # （`playback_has_ever_started()` 为假 ⇒ 不建，RN-195/批 9，我自己改的）。
            # ⭐⭐⭐ **一个正确的收窄，把它自己的入口关在了自己后面**：
            # 控制栏要放过音乐才出现，而放音乐这件事原本就该由它来做。
            # 真正的入口只有双击列表项，而页面上提到它的只有一句在折线之下的小字。
            # 外审在「有歌、没播过」那一档 **7/8 发判高**（空列表那档只有 1/8 ——
            # 没歌当然放不了，那一档把问题遮住了）。
            description="放本地音乐或在线 URL，双击列表里的歌就开始放；"
                        "放起来之后窗口底部会常驻一条控制栏管暂停/切歌/音量。"
                        "「音乐联动」只管游戏要不要自动接管。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        settings_layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["music"])
        
        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.settings_scroll = scroll
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 16)
        scroll_layout.setSpacing(12)

        overview_card = QFrame()
        overview_card.setObjectName("card")
        self.music_overview_card = overview_card
        self.status_card = overview_card
        overview_layout = QVBoxLayout(overview_card)
        overview_layout.setContentsMargins(14, 12, 14, 12)
        overview_layout.setSpacing(8)

        # RN-189：就地总开关。首页「功能开关」里有「音乐联动」，而这一页
        # **连 `music_enabled` 这个键都没提过** —— 站在音乐页上拨不到音乐的总开关。
        # ⚠ 拨动一律走 `MainWindow.set_feature_enabled` ⇒ 首页那颗开关 ⇒ 一整串副作用。
        from widgets.master_switch_link import make_master_switch_row

        self.master_switch_row = make_master_switch_row(
            self, "music_enabled", "音乐联动")
        overview_layout.addWidget(self.master_switch_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        overview_title = QLabel("当前状态")
        overview_title.setObjectName("statusLabel")
        status_row.addWidget(overview_title)

        self.status_badge_label = create_badge_label()
        status_row.addWidget(self.status_badge_label, 1)
        status_row.addStretch()
        overview_layout.addLayout(status_row)

        # ⚠⚠ RN-458（批 32）：这里原来是 `music_summary_label` —— RN-009 那一族
        # 「建出来就 hide()、全仓 0 处 show()」的死控件（AST 实测），
        # 而每次同步都往里写 9 行 115 个字。
        # ⭐⭐⭐ 这一个多出来一层：**它身上挂着判据。**三条测试逐字断言那 9 行里
        # 写了什么，于是删它的成本被我们自己抬高了一整级 ——
        # **一个死控件活下来的机制，是有人给它写了判据。**
        # ⇒ 详情文本留着（它喂 `music_overview_card` 的 tooltip，用户悬停够得着），
        #   只把那个永远不会出现在屏幕上的载体删掉。
        scroll_layout.addWidget(overview_card)
        
        # ⚠⚠ RN-456（批 32）：**播放列表原来排在最后**，于是这一页 24 个可交互
        # 控件里 12 个露出 0%（第一屏只装得下 42%），而露出 0% 的正好是
        # 「播放模式」四选一 + 整个播放列表区 —— 一个叫「音乐播放」的页面，
        # 第一屏上一件跟「放音乐」有关的事都做不了。
        #
        # ⭐⭐⭐ 而这一条是被 RN-455 的修法**逼出来的**：我把真正的入口
        # （双击列表）写进了页头，改完复跑当场 **8/8** 报同一句新话 ——
        # 「文案提示『双击列表里的歌开始放』，但界面完全看不到歌曲列表」
        # （改前一发都没有）。⇒ 我把入口从「**不存在**的控件」改成了
        # 「**存在但在折线之下**的控件」。
        # ⭐⭐⭐ **一句正确的指路，会把「路的那一头看不见」变成一个新缺陷。**
        # ⇒ 两条不能分批做。列表是这一页的**内容**，联动是**配置**；内容在前。
        playlist_group = self._create_playlist_management()
        scroll_layout.addWidget(playlist_group)

        self.top_settings_row = QBoxLayout(QBoxLayout.LeftToRight)
        self.top_settings_row.setSpacing(12)
        game_link_group = self._create_game_link_settings()
        play_settings_group = self._create_play_settings()
        game_link_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        play_settings_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.game_link_column = QWidget()
        self.game_link_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        game_link_column_layout = QVBoxLayout(self.game_link_column)
        game_link_column_layout.setContentsMargins(0, 0, 0, 0)
        game_link_column_layout.setSpacing(0)
        game_link_column_layout.addWidget(game_link_group)
        game_link_column_layout.addStretch(1)

        self.play_settings_column = QWidget()
        self.play_settings_column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        play_settings_column_layout = QVBoxLayout(self.play_settings_column)
        play_settings_column_layout.setContentsMargins(0, 0, 0, 0)
        play_settings_column_layout.setSpacing(0)
        play_settings_column_layout.addWidget(play_settings_group)
        play_settings_column_layout.addStretch(1)

        self.top_settings_row.addWidget(self.game_link_column, 3)
        self.top_settings_row.addWidget(self.play_settings_column, 2)
        scroll_layout.addLayout(self.top_settings_row)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        settings_layout.addWidget(scroll)

        # UP-077: 这一行必须在建 action_bar **之前**。
        # `settings_container` 是无父创建的，直到 addWidget 才入焦点链；
        # 而 `PageActionBar(self)` 一创建就带父、当场入链。原先顺序反了，
        # 于是进音乐页按 Tab，焦点第一站是**底部动作条的「刷新列表」**，
        # 而不是页面顶部——排版没问题，坏的只有键盘顺序，所以一直没人看见。
        # kill_sound 页是先 add 内容再建动作条，所以它一直是对的（实测 0 处错位）。
        main_layout.addWidget(settings_container, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.configure_secondary("刷新列表", self._refresh_playlist_catalog, visible=True)
        self.action_bar.configure_primary("添加音乐", self._add_local_files, visible=True)
        self.action_bar.secondary_btn.setMinimumWidth(136)
        self.action_bar.primary_btn.setMinimumWidth(136)

        main_layout.addWidget(self.action_bar, 0)
        self._update_compact_layout()

    def _update_compact_layout(self):
        """Keep the top settings area readable without horizontal clipping."""
        if not hasattr(self, "top_settings_row"):
            return

        available_width = self.width()
        scroll = getattr(self, "settings_scroll", None)
        if scroll is not None and scroll.viewport() is not None:
            available_width = max(available_width, scroll.viewport().width())

        compact = available_width < 1210
        direction = QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight
        if self.top_settings_row.direction() != direction:
            self.top_settings_row.setDirection(direction)

        self.top_settings_row.setSpacing(10 if compact else 12)
        self.top_settings_row.setStretch(0, 0 if compact else 3)
        self.top_settings_row.setStretch(1, 0 if compact else 2)

        if hasattr(self, "link_content_layout"):
            link_direction = QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight
            if self.link_content_layout.direction() != link_direction:
                self.link_content_layout.setDirection(link_direction)
            self.link_content_layout.setSpacing(8 if compact else 10)
            self.link_content_layout.setStretch(0, 0 if compact else 1)
            self.link_content_layout.setStretch(1, 0 if compact else 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_compact_layout()

    def _create_badge_label(self):
        badge = QLabel()
        badge.setObjectName("badgeLabel")
        badge.setAlignment(Qt.AlignCenter)
        return badge

    def _set_badge_state(self, label, text, tone="info"):
        label.setText(text)
        label.setProperty("tone", tone)
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()

    def _create_panel_card(self, title, description=None):
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("statusLabel")
        layout.addWidget(title_label)

        if description:
            description_label = QLabel(description)
            description_label.setObjectName("hintLabel")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

        return card, layout

    def _format_play_mode_text(self):
        mode_map = {
            "sequence": "顺序播放",
            "shuffle": "随机播放",
            "repeat_one": "单曲循环",
            "repeat_all": "列表循环",
        }
        return mode_map.get(normalize_music_play_mode(config.music_play_mode), "顺序播放")

    @staticmethod
    def _compact_text(text, fallback="未设置", max_length=10):
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    def _current_runtime_badge(self, playlist):
        playlist_items = list(playlist or [])
        if not playlist_items:
            return ("warning", "播放 · 待播放")
        if getattr(self.player, "is_paused", False):
            return ("warning", "播放 · 已暂停")
        current_index = int(getattr(self.player, "current_index", -1))
        if 0 <= current_index < len(playlist_items) and getattr(self.player, "is_playing", False):
            return ("positive", "播放 · 播放中")
        return ("info", "播放 · 已就绪")

    @staticmethod
    def _format_duration(duration) -> str:
        try:
            total_seconds = int(float(duration or 0))
        except (TypeError, ValueError):
            total_seconds = 0
        if total_seconds <= 0:
            return "--:--"
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def _get_selected_playlist_rows(self) -> set[int]:
        if not hasattr(self, "playlist_widget"):
            return set()
        selected_rows: set[int] = set()
        for item in self.playlist_widget.selectedItems():
            row = self.playlist_widget.row(item)
            if row >= 0:
                selected_rows.add(row)
        return selected_rows

    def _restore_playlist_selection(self, selected_rows, item_count: int):
        if not hasattr(self, "playlist_widget"):
            return
        self.playlist_widget.blockSignals(True)
        for row in sorted(set(selected_rows or [])):
            if 0 <= int(row) < item_count:
                item = self.playlist_widget.item(int(row))
                if item is not None and bool(item.flags() & Qt.ItemIsSelectable):
                    item.setSelected(True)
        self.playlist_widget.blockSignals(False)
        self.selected_indices = self._get_selected_playlist_rows()

    def _current_track_summary(self, playlist):
        playlist_items = list(playlist or [])
        current_track_title = "未选择"
        current_track_state = "待播放"
        current_track_duration = "--:--"

        current_index = int(getattr(self.player, "current_index", -1))
        if playlist_items and 0 <= current_index < len(playlist_items):
            current_track = playlist_items[current_index] or {}
        else:
            current_track = getattr(self.player, "get_current_track", lambda: None)() or {}

        if current_track:
            current_track_title = str(current_track.get("title") or current_track.get("path") or "当前曲目")
            current_track_duration = self._format_duration(current_track.get("duration", 0))
            if getattr(self.player, "is_paused", False):
                current_track_state = "暂停中"
            elif getattr(self.player, "is_playing", False):
                current_track_state = "播放中"
            else:
                current_track_state = "待播放"

        return current_track_title, current_track_state, current_track_duration

    def _sync_playlist_panel_status(self):
        if not hasattr(self, "playlist_status_badge_label"):
            return

        playlist_name = str(
            self.player.current_playlist_name or getattr(config, "music_current_playlist", "") or "默认列表"
        )
        playlist = list(self.player.get_playlist() or [])
        selected_count = len(self.selected_indices if playlist else set())
        current_track_title, current_track_state, current_track_duration = self._current_track_summary(playlist)
        local_count = sum(1 for track in playlist if str(track.get("type", "local")).lower() != "url")
        url_count = max(0, len(playlist) - local_count)

        badges = [
            ("info", f"列表 · {self._compact_text(playlist_name, '默认列表', 12)}"),
            ("positive" if playlist else "warning", f"曲目 · {len(playlist)} 首"),
            ("positive" if selected_count else "info", f"选中 · {selected_count} 首"),
            ("positive" if playlist else "warning", f"当前 · {self._compact_text(current_track_title, '未选择', 12)}"),
        ]

        detail_lines = [
            f"当前列表：{playlist_name}",
            f"列表曲目：{len(playlist)} 首",
            f"已选曲目：{selected_count} 首",
            f"当前曲目：{current_track_title}",
            f"当前状态：{current_track_state}",
            f"曲目时长：{current_track_duration}",
            f"来源分布：本地 {local_count} / URL {url_count}",
        ]
        detail_text = "\n".join(detail_lines)

        render_badges(self.playlist_status_badge_label, badges, detail_tooltip=detail_text)
        self.playlist_group.setToolTip(detail_text)
        self.playlist_widget.setToolTip(detail_text)
        if hasattr(self, "playlist_meta_label"):
            self.playlist_meta_label.setText(
                f"当前曲目：{current_track_title} · 状态 {current_track_state} · 来源 本地 {local_count} / URL {url_count}"
            )
            self.playlist_meta_label.setToolTip(detail_text)

        if hasattr(self, "action_bar"):
            if playlist:
                if selected_count:
                    action_message = (
                        f"当前列表：{playlist_name} · 共 {len(playlist)} 首，已选 {selected_count} 首；"
                        "双击曲目可立即切歌。"
                    )
                else:
                    action_message = (
                        f"当前列表：{playlist_name} · 共 {len(playlist)} 首；"
                        "底部主按钮可继续添加本地音乐。"
                    )
            else:
                action_message = f"当前列表：{playlist_name} · 还没有曲目；先添加本地音乐，再按需补充 URL。"
            self.action_bar.set_message(action_message)

    def _sync_game_link_panel(self):
        if not hasattr(self, "link_policy_label"):
            return

        link_enabled = bool(getattr(config, "music_game_link_enabled", False))
        death_action = str(getattr(config, "music_death_action", "play") or "play")
        death_action_text = "阵亡后自动开始/继续播放" if death_action == "play" else "阵亡后不自动改动"
        death_volume_text = (
            f"自定义音量 {format_percent(getattr(config, 'music_death_volume', 1.0))}"
            if bool(getattr(config, "music_death_volume_custom", False))
            else "正常音量 100%"
        )

        alive_action = str(getattr(config, "music_revive_action", "lower") or "lower")
        if alive_action == "pause":
            alive_action_text = "存活时自动暂停播放"
        elif alive_action == "keep":
            alive_action_text = "存活时不自动改动"
        else:
            alive_action_text = f"存活时自动降低到 {format_percent(getattr(config, 'music_revive_volume', 0.4))}"

        fade_available = alive_action in {"pause", "lower"}
        fade_enabled = fade_available and bool(getattr(config, "music_fade_enabled", False))
        fade_text = (
            f"淡出 {float(getattr(config, 'music_fade_out_duration', 0.5)):.1f} 秒"
            if fade_enabled
            else ("不附加淡出" if fade_available else "当前策略无需淡出")
        )

        # ⚠ RN-407 家族：**总开关关着的时候，「已启用」是一句假话。**
        # `link_enabled` 只是那颗**子开关**的值，它不看总开关 `music_enabled`；
        # 于是总开关写着「未开启」而这里写着「联动已启用」——同一屏自相矛盾。
        # ⭐ 三态才是真话：关着 + 子开关开 = 「**已配置**」（配好了，但没在跑）。
        summary_text = (
            f"当前策略：联动{_link_state_word(link_enabled)} · "
            f"{death_action_text} · {alive_action_text} · {fade_text}"
        )
        self.link_policy_label.setText(summary_text)
        self.link_policy_label.setToolTip(summary_text)

        if hasattr(self, "death_summary_label"):
            death_text = f"{death_action_text} · {death_volume_text}"
            self.death_summary_label.setText(death_text)
            self.death_summary_label.setToolTip(death_text)

        if hasattr(self, "alive_summary_label"):
            alive_text = f"{alive_action_text} · {fade_text}"
            self.alive_summary_label.setText(alive_text)
            self.alive_summary_label.setToolTip(alive_text)

    def _sync_play_settings_panel(self):
        if not hasattr(self, "play_mode_badge_label"):
            return

        mode_text = self._format_play_mode_text()
        detail_text = (
            f"当前模式：{mode_text}\n"
            "这里只决定底部常驻播放器的默认切歌策略，手动切歌不受影响。"
        )
        render_badges(
            self.play_mode_badge_label,
            [
                ("info", f"当前 · {mode_text}"),
                ("positive", "范围 · 底部播放器"),
            ],
            detail_tooltip=detail_text,
        )
        self.play_settings_group.setToolTip(detail_text)

    def on_master_switch_synced(self):
        """总开关被别处拨动后，把本页状态重算一遍（RN-189）。

        ⭐ 全仓统一的钩子名（`widgets/master_switch_link` 调它）。
        少了这一下，开关动了而徽章不动 —— 同屏两处说法不一致（RN-107 族）。
        """
        self._sync_overview_status()

    def _sync_overview_status(self):
        if not hasattr(self, "status_badge_label"):
            return
        link_enabled = bool(config.music_game_link_enabled)
        mode_text = self._format_play_mode_text()
        playlist_name = str(
            self.player.current_playlist_name or getattr(config, "music_current_playlist", "") or "默认列表"
        )
        playlist = list(self.player.get_playlist() or [])
        runtime_level, runtime_text = self._current_runtime_badge(playlist)

        current_track_title = "未选择"
        current_track_state = "待播放"
        current_index = int(getattr(self.player, "current_index", -1))
        if playlist and 0 <= current_index < len(playlist):
            current_track = playlist[current_index] or {}
            current_track_title = str(current_track.get("title") or current_track.get("path") or "当前曲目")
            current_track_state = "暂停中" if getattr(self.player, "is_paused", False) else "播放中"

        badges = [
            ("positive" if link_enabled else "warning",
             f"联动 · {_link_state_word(link_enabled)}"),
            ("info", f"模式 · {mode_text}"),
            ("info", f"列表 · {self._compact_text(playlist_name, '默认列表', 10)}"),
            ("positive" if playlist else "warning", f"曲目 · {len(playlist)} 首"),
            (runtime_level, runtime_text),
        ]

        detail_lines = [
            f"游戏联动：{'已启用' if link_enabled else '已关闭'}",
            f"播放模式：{mode_text}",
            f"当前列表：{playlist_name}",
            f"列表曲目：{len(playlist)} 首",
            f"当前曲目：{current_track_title}",
            f"播放状态：{current_track_state}",
            f"死亡行为：{config.music_death_action} · 音量 {'自定义' if config.music_death_volume_custom else '正常'} {format_percent(config.music_death_volume)}",
            f"存活行为：{config.music_revive_action} · 恢复音量 {format_percent(config.music_revive_volume)}",
            f"淡出效果：{'已启用' if config.music_fade_enabled else '已关闭'} · {config.music_fade_out_duration:.1f} 秒",
        ]
        detail_text = "\n".join(detail_lines)
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        # RN-458：详情只往用户够得着的两处送 —— 胶囊条的 tooltip 和卡片的 tooltip。
        if hasattr(self, "music_overview_card"):
            self.music_overview_card.setToolTip(detail_text)
        self._sync_game_link_panel()
        self._sync_play_settings_panel()
        self._sync_playlist_panel_status()
    
    def _create_game_link_settings(self):
        """创建游戏状态联动设置"""
        group = self._create_group_box("游戏内自动联动")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        
        # 启用开关
        self.game_link_checkbox = QCheckBox("允许游戏状态自动控制音乐")
        self.game_link_checkbox.setChecked(config.music_game_link_enabled)
        self.game_link_checkbox.toggled.connect(self._on_game_link_toggled)
        layout.addWidget(self.game_link_checkbox)

        desc_label = QLabel(
            "说明：底部音乐控制栏可随时手动播放；这里的设置只决定游戏是否自动播放、暂停或调整音量。"
        )
        desc_label.setWordWrap(True)
        desc_label.setObjectName("hintLabel")
        layout.addWidget(desc_label)

        self.link_policy_label = QLabel("")
        self.link_policy_label.setObjectName("hintLabel")
        self.link_policy_label.setWordWrap(True)
        layout.addWidget(self.link_policy_label)
        
        # 联动内容框架
        self.link_content_frame = QFrame()
        self.link_content_frame.setObjectName("card")
        self.link_content_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.link_content_layout = QBoxLayout(QBoxLayout.LeftToRight, self.link_content_frame)
        self.link_content_layout.setContentsMargins(12, 12, 12, 12)
        self.link_content_layout.setSpacing(10)

        death_card, death_layout = self._create_panel_card(
            "死亡时",
            "决定阵亡后是否继续播，以及是否把底部播放器压到指定音量。",
        )
        self.death_summary_label = QLabel("")
        self.death_summary_label.setObjectName("hintLabel")
        self.death_summary_label.setWordWrap(True)
        death_layout.addWidget(self.death_summary_label)

        death_control_layout = QHBoxLayout()
        death_control_layout.addWidget(QLabel("播放控制:"))
        
        self.death_action_group = QButtonGroup()
        death_play_radio = QRadioButton("自动开始/继续播放")
        death_keep_radio = QRadioButton("不自动改动")
        self.death_action_group.addButton(death_play_radio, 0)
        self.death_action_group.addButton(death_keep_radio, 1)
        self.death_action_group.idClicked.connect(self._on_death_action_changed)
        death_control_layout.addWidget(death_play_radio)
        death_control_layout.addWidget(death_keep_radio)
        death_control_layout.addStretch()
        death_layout.addLayout(death_control_layout)
        
        death_volume_layout = QHBoxLayout()
        death_volume_layout.addWidget(QLabel("音量设置:"))
        
        self.death_volume_group = QButtonGroup()
        death_normal_radio = QRadioButton("正常音量 (100%)")
        death_custom_radio = QRadioButton("自定义音量:")
        self.death_volume_group.addButton(death_normal_radio, 0)
        self.death_volume_group.addButton(death_custom_radio, 1)
        self.death_volume_group.idClicked.connect(self._on_death_volume_mode_changed)
        death_volume_layout.addWidget(death_normal_radio)
        death_volume_layout.addWidget(death_custom_radio)
        
        self.death_volume_slider = QSlider(Qt.Horizontal)
        self.death_volume_slider.setRange(0, 100)
        self.death_volume_slider.setValue(int(config.music_death_volume * 100))
        self.death_volume_slider.setMaximumWidth(150)
        self.death_volume_slider.valueChanged.connect(self._on_death_volume_changed)
        death_volume_layout.addWidget(self.death_volume_slider)
        
        self.death_volume_label = QLabel(format_percent(config.music_death_volume))
        death_volume_layout.addWidget(self.death_volume_label)
        death_volume_layout.addStretch()
        death_layout.addLayout(death_volume_layout)

        alive_card, alive_layout = self._create_panel_card(
            "存活时",
            "游戏进行中或复活后，决定是暂停、压低音量还是保持当前播放状态。",
        )
        self.alive_summary_label = QLabel("")
        self.alive_summary_label.setObjectName("hintLabel")
        self.alive_summary_label.setWordWrap(True)
        alive_layout.addWidget(self.alive_summary_label)

        alive_control_layout = QHBoxLayout()
        alive_control_layout.addWidget(QLabel("播放控制:"))
        
        self.alive_action_group = QButtonGroup()
        alive_pause_radio = QRadioButton("自动暂停播放")
        alive_lower_radio = QRadioButton("自动降低音量")
        alive_keep_radio = QRadioButton("不自动改动")
        self.alive_action_group.addButton(alive_pause_radio, 0)
        self.alive_action_group.addButton(alive_lower_radio, 1)
        self.alive_action_group.addButton(alive_keep_radio, 2)
        self.alive_action_group.idClicked.connect(self._on_alive_action_changed)
        alive_control_layout.addWidget(alive_pause_radio)
        alive_control_layout.addWidget(alive_lower_radio)
        alive_control_layout.addWidget(alive_keep_radio)
        alive_control_layout.addStretch()
        alive_layout.addLayout(alive_control_layout)
        
        self.alive_volume_layout = QHBoxLayout()
        self.alive_volume_layout.addWidget(QLabel("降低至:"))
        
        self.alive_volume_slider = QSlider(Qt.Horizontal)
        self.alive_volume_slider.setRange(0, 100)
        self.alive_volume_slider.setValue(int(config.music_revive_volume * 100))
        self.alive_volume_slider.setMaximumWidth(150)
        self.alive_volume_slider.valueChanged.connect(self._on_alive_volume_changed)
        self.alive_volume_layout.addWidget(self.alive_volume_slider)
        
        self.alive_volume_label = QLabel(format_percent(config.music_revive_volume))
        self.alive_volume_layout.addWidget(self.alive_volume_label)
        self.alive_volume_layout.addStretch()
        alive_layout.addLayout(self.alive_volume_layout)
        
        self.alive_fade_layout = QHBoxLayout()
        self.alive_fade_checkbox = QCheckBox("淡出效果")
        self.alive_fade_checkbox.toggled.connect(self._on_fade_toggled)
        self.alive_fade_layout.addWidget(self.alive_fade_checkbox)
        
        self.fade_out_slider = QSlider(Qt.Horizontal)
        self.fade_out_slider.setRange(1, 20)  # 0.1-2.0秒，步长0.1
        self.fade_out_slider.setValue(int(config.music_fade_out_duration * 10))
        self.fade_out_slider.setMaximumWidth(100)
        self.fade_out_slider.valueChanged.connect(self._on_fade_out_duration_changed)
        self.alive_fade_layout.addWidget(self.fade_out_slider)
        
        self.fade_out_label = QLabel(f"{config.music_fade_out_duration:.1f}秒")
        self.alive_fade_layout.addWidget(self.fade_out_label)
        self.alive_fade_layout.addStretch()
        alive_layout.addLayout(self.alive_fade_layout)

        self.death_link_card = death_card
        self.alive_link_card = alive_card
        self.link_content_layout.addWidget(self.death_link_card, 1)
        self.link_content_layout.addWidget(self.alive_link_card, 1)
        
        layout.addWidget(self.link_content_frame)
        return group
    
    def _create_play_settings(self):
        """创建播放设置"""
        group = self._create_group_box("播放设置")
        self.play_settings_group = group
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # 播放模式
        mode_title = QLabel("播放模式")
        mode_title.setObjectName("subtitleLabel")
        layout.addWidget(mode_title)

        self.play_mode_badge_label = create_badge_label()
        layout.addWidget(self.play_mode_badge_label)

        # ⚠ RN-459（批 32）：这里原来还有两行 `hintLabel`，说的都是
        # 「只影响底部常驻播放器的默认切歌策略」——**同一件事在这张卡里说了 5 遍**
        # （胶囊「范围 · 底部播放器」+ 这两行 + 卡片描述 + tooltip），
        # 而这张卡真正的内容只有 4 个单选钮；当前值「顺序播放」还另外出现 3 次。
        # ⭐ 外审 18/18 发全部答对了「这个设置管的是底部播放器」——
        # **这件事早就传达成功了，多说的那几遍是纯成本。**
        self.play_mode_group = QButtonGroup()
        sequential_radio = QRadioButton("顺序播放")
        random_radio = QRadioButton("随机播放")
        single_radio = QRadioButton("单曲循环")
        loop_radio = QRadioButton("列表循环")

        for radio in (sequential_radio, random_radio, single_radio, loop_radio):
            radio.setFont(QFont("Microsoft YaHei", 10))
            radio.setMinimumHeight(30)

        self.play_mode_group.addButton(sequential_radio, 0)
        self.play_mode_group.addButton(random_radio, 1)
        self.play_mode_group.addButton(single_radio, 2)
        self.play_mode_group.addButton(loop_radio, 3)
        self.play_mode_group.idClicked.connect(self._on_play_mode_changed)

        mode_grid = QGridLayout()
        mode_grid.setContentsMargins(0, 2, 0, 0)
        mode_grid.setHorizontalSpacing(18)
        mode_grid.setVerticalSpacing(8)
        mode_grid.addWidget(sequential_radio, 0, 0)
        mode_grid.addWidget(random_radio, 0, 1)
        mode_grid.addWidget(single_radio, 1, 0)
        mode_grid.addWidget(loop_radio, 1, 1)
        mode_grid.setColumnStretch(0, 1)
        mode_grid.setColumnStretch(1, 1)

        mode_card, mode_layout = self._create_panel_card(
            "模式选择",
            "只影响底部常驻播放器的默认切歌策略，不会覆盖你手动切歌。",
        )
        mode_layout.addLayout(mode_grid)
        layout.addWidget(mode_card)
        # ⚠ 这里原来还有一句 `group.setToolTip("这里只决定底部全局播放器…")`，
        # 而 `_sync_play_settings_panel` 每次同步都对同一个 group `setToolTip(detail_text)`
        # ——它在 `load_settings()` 里就被调过了。⇒ **那句静态 tooltip 从建页那一刻起
        # 就被覆盖掉，一次都没生效过。**又一个「写了没人看得到」（RN-009 同族）。
        return group
    
    def _create_playlist_management(self):
        """创建播放列表管理区。"""
        group = self._create_group_box("播放列表")
        self.playlist_group = group
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        toolbar_card, toolbar_layout = self._create_panel_card(
            "列表切换",
            "双击列表项可立刻切歌；列表管理只影响当前选中的播放列表。",
        )
        top_control_layout = QHBoxLayout()
        top_control_layout.setSpacing(8)
        top_control_layout.addWidget(QLabel("当前列表:"))

        self.playlist_combo = QComboBox()
        self.playlist_combo.setMinimumWidth(180)
        self.playlist_combo.setFixedHeight(36)
        self.playlist_combo.currentTextChanged.connect(self._on_playlist_changed)
        top_control_layout.addWidget(self.playlist_combo)

        new_btn = QPushButton("新建")
        new_btn.setMaximumWidth(72)
        new_btn.setFixedHeight(34)
        style_as_secondary_button(new_btn)
        new_btn.clicked.connect(self._create_new_playlist)
        top_control_layout.addWidget(new_btn)

        rename_btn = QPushButton("重命名")
        rename_btn.setMaximumWidth(92)
        rename_btn.setFixedHeight(34)
        style_as_secondary_button(rename_btn)
        rename_btn.clicked.connect(self._rename_playlist)
        top_control_layout.addWidget(rename_btn)

        delete_btn = QPushButton("删除")
        delete_btn.setMaximumWidth(72)
        delete_btn.setFixedHeight(34)
        # R7/D-06: 删掉的是用户手工攒的整张歌单（含手动加的在线 URL），
        # 只有 8 秒 toast_undo 窗口，超时即永久丢失。
        style_as_danger_button(delete_btn)
        delete_btn.clicked.connect(self._delete_playlist)
        top_control_layout.addWidget(delete_btn)

        top_control_layout.addStretch()
        toolbar_layout.addLayout(top_control_layout)

        self.playlist_meta_label = QLabel("")
        self.playlist_meta_label.setObjectName("hintLabel")
        self.playlist_meta_label.setWordWrap(True)
        toolbar_layout.addWidget(self.playlist_meta_label)
        self.playlist_status_badge_label = create_badge_label()
        layout.addWidget(self.playlist_status_badge_label)

        self.playlist_widget = QListWidget()
        self.playlist_widget.setMinimumHeight(180)
        self.playlist_widget.setMaximumHeight(320)
        self.playlist_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.playlist_widget.itemSelectionChanged.connect(self._on_playlist_selection_changed)
        layout.addWidget(self.playlist_widget)

        bottom_control_layout = QHBoxLayout()
        bottom_control_layout.setSpacing(8)

        # 开源版只播放本地文件，没有"添加 URL"入口：
        # 上游的在线添加走的是音乐平台抓流解析器，已随开源裁剪整体移除。
        bottom_control_layout.addStretch()

        delete_selected_btn = QPushButton("删除选中")
        # R7/D-06: 直接从 config.music_playlists 摘曲目并落盘，同样只有 8 秒 undo
        style_as_danger_button(delete_selected_btn)
        delete_selected_btn.setFixedHeight(38)
        delete_selected_btn.clicked.connect(self._delete_selected)
        bottom_control_layout.addWidget(delete_selected_btn)

        clear_btn = QPushButton("清空列表")
        # R7/D-06 明文点名的场景，而且是这三兄弟里**唯一完全没有 undo 兜底**的
        style_as_danger_button(clear_btn)
        clear_btn.setFixedHeight(38)
        clear_btn.clicked.connect(self._clear_playlist)
        bottom_control_layout.addWidget(clear_btn)

        layout.addLayout(bottom_control_layout)

        # ⚠⚠ RN-456 第二刀（批 32 二版）：这张「列表切换」卡原来排在**这一组的最前面**，
        # 占掉 ~230px，把曲目列表往下顶。二版复跑 B 场景 ux 4/4 + render 4/4 报
        # 「歌曲列表被挤出视口」——⚠ **那句话假一半**：实测前 3 首清清楚楚，
        # 第 3 首被折线切一半，真相是「5 首只看得见 3 首」。
        # ⭐ 但机制被外审自己点破了：「把歌单管理（新建/重命名/删除）放在正中，
        #   导致新手把『歌单』误当成『歌曲』，找不到真正的曲目列表。」
        # ⇒ 同一条规则再降一层：**内容在前，管理在后。**
        # ⭐ 一个改动同时解决两条：列表往上顶 ~230px，而那颗删整张歌单的红按钮
        #   （12 发里 6 发点名它是第一屏最扎眼的东西）跟着退出第一屏。
        layout.addWidget(toolbar_card)
        self.playlist_widget.setToolTip("支持本地文件和 URL，双击列表项即可立即切换到对应曲目。")
        group.setToolTip("支持本地文件和 URL，双击列表项即可立即切换到对应曲目。")
        return group

    def _create_group_box(self, title):
        """创建统一样式的分组框"""
        group = QGroupBox(title)
        group.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        return group
    
    # ===== 事件处理器 =====
    
    def _on_game_link_toggled(self, checked):
        """游戏联动开关切换"""
        config.music_game_link_enabled = checked
        config.save_config()
        self.link_content_frame.setEnabled(checked)
        self._sync_overview_status()
        self.logger.info(f"音乐自动联动: {'启用' if checked else '禁用'}")
        # v2.2.1: 关闭联动时恢复被联动改掉的状态——旧版只写 config，
        # 若音乐正被联动暂停/降音量，会永久卡在该状态直到用户手动恢复
        if not checked:
            try:
                from gsi_handler_music import get_music_gsi_handler

                handler = get_music_gsi_handler()
                if handler is not None:
                    handler.restore_game_link_state("关闭游戏联动")
            except Exception:
                self.logger.exception("关闭联动时恢复音乐状态失败")

    def _on_death_action_changed(self, action_id):
        """死亡时播放行为切换"""
        action_map = {0: "play", 1: "keep"}
        config.music_death_action = action_map.get(int(action_id), "play")
        config.save_config()
        self._sync_overview_status()
        self.logger.info(f"死亡行为已更新: {config.music_death_action}")

    def _on_death_volume_mode_changed(self, mode_id):
        """死亡音量模式切换"""
        config.music_death_volume_custom = int(mode_id) == 1
        config.save_config()
        self._refresh_link_control_states()
        self._sync_overview_status()
        self.logger.info(
            f"死亡音量模式已更新: {'自定义' if config.music_death_volume_custom else '正常音量'}"
        )
    
    def _on_death_volume_changed(self, value):
        """死亡音量改变"""
        config.music_death_volume = value / 100.0
        config.save_config()
        self.death_volume_label.setText(f"{value}%")
        self._sync_overview_status()

    def _on_alive_action_changed(self, action_id):
        """存活时行为切换"""
        action_map = {0: "pause", 1: "lower", 2: "keep"}
        config.music_revive_action = action_map.get(int(action_id), "lower")
        config.save_config()
        self._refresh_link_control_states()
        self._sync_overview_status()
        self.logger.info(f"存活行为已更新: {config.music_revive_action}")
    
    def _on_alive_volume_changed(self, value):
        """存活音量改变（原复活音量）"""
        config.music_revive_volume = value / 100.0
        config.save_config()
        self.alive_volume_label.setText(f"{value}%")
        self._sync_overview_status()
        self.logger.info(f"存活音量已更新: {value}%")
    
    def _on_fade_toggled(self, checked):
        """淡出效果开关"""
        config.music_fade_enabled = checked
        config.save_config()
        self._refresh_link_control_states()
        self._sync_overview_status()
    
    def _on_fade_out_duration_changed(self, value):
        duration = value / 10.0
        config.music_fade_out_duration = duration
        config.save_config()
        self.fade_out_label.setText(f"{duration:.1f}秒")
        self._sync_overview_status()

    def _on_play_mode_changed(self, mode_id):
        """播放模式切换"""
        mode_map = {0: "sequence", 1: "shuffle", 2: "repeat_one", 3: "repeat_all"}
        play_mode = mode_map.get(int(mode_id), "sequence")
        self.player.set_play_mode(play_mode)
        config.music_play_mode = play_mode
        config.save_config()
        self._sync_overview_status()
        self.logger.info(f"播放模式已更新: {play_mode}")

    def _refresh_link_control_states(self):
        """根据当前配置刷新联动控件可用状态。"""
        death_custom = bool(config.music_death_volume_custom)
        self.death_volume_slider.setEnabled(death_custom)
        self.death_volume_label.setEnabled(death_custom)

        alive_action = str(getattr(config, "music_revive_action", "lower") or "lower")
        alive_lower_enabled = alive_action == "lower"
        alive_fade_enabled = alive_action in {"pause", "lower"}
        fade_controls_enabled = alive_fade_enabled and bool(config.music_fade_enabled)

        self.alive_volume_slider.setEnabled(alive_lower_enabled)
        self.alive_volume_label.setEnabled(alive_lower_enabled)
        self.alive_fade_checkbox.setEnabled(alive_fade_enabled)
        self.fade_out_slider.setEnabled(fade_controls_enabled)
        self.fade_out_label.setEnabled(fade_controls_enabled)
    
    def _on_playlist_selection_changed(self):
        self.selected_indices = self._get_selected_playlist_rows()
        self._sync_playlist_panel_status()

    def _refresh_playlist_catalog(self):
        current_playlist = str(
            self.playlist_combo.currentText()
            or self.player.current_playlist_name
            or getattr(config, "music_current_playlist", "")
        )
        selected_rows = self._get_selected_playlist_rows()
        playlists = list(self.player.get_all_playlists() or [])
        target_playlist = current_playlist
        if target_playlist not in playlists and playlists:
            player_playlist = str(getattr(self.player, "current_playlist_name", "") or "")
            target_playlist = player_playlist if player_playlist in playlists else playlists[0]

        self.playlist_combo.blockSignals(True)
        self.playlist_combo.clear()
        self.playlist_combo.addItems(playlists)
        if target_playlist:
            index = self.playlist_combo.findText(target_playlist)
            if index >= 0:
                self.playlist_combo.setCurrentIndex(index)
        self.playlist_combo.blockSignals(False)

        if target_playlist and str(getattr(self.player, "current_playlist_name", "") or "") != target_playlist:
            try:
                self.player.switch_playlist(target_playlist)
            except Exception as exc:
                self.logger.error(f"刷新播放列表失败: {exc}")

        self.selected_indices = set(selected_rows)
        self.refresh_playlist_display(selected_rows=selected_rows)
        self._sync_overview_status()
        self.logger.info("音乐播放列表已刷新")

    def _on_playlist_changed(self, playlist_name):
        if not playlist_name:
            return

        try:
            self.selected_indices = set()
            self.player.switch_playlist(playlist_name)
            self._sync_overview_status()
            self.logger.info(f"切换到播放列表: {playlist_name}")
        except Exception as e:
            self.logger.error(f"切换播放列表失败: {e}")

    def _on_item_double_clicked(self, item):
        row = self.playlist_widget.row(item)
        try:
            self.player.play(row)
            self._sync_overview_status()
            self.logger.info(f"双击播放: 索引={row}")
        except Exception as e:
            self.logger.error(f"播放失败: {e}")
            QMessageBox.warning(self, "播放失败", "无法播放该音乐：文件可能缺失、损坏或格式不支持，请重新添加后重试。")

    def _create_new_playlist(self):
        name, ok = QInputDialog.getText(self, "新建播放列表", "请输入播放列表名称:")
        if ok and name:
            if self.player.create_playlist(name):
                self._refresh_playlist_catalog()
                index = self.playlist_combo.findText(name)
                if index >= 0:
                    self.playlist_combo.setCurrentIndex(index)
                self.logger.info(f"创建播放列表: {name}")
                QMessageBox.information(self, "成功", f'播放列表 "{name}" 创建成功!')
            else:
                QMessageBox.warning(self, "失败", "播放列表已存在!")

    def _rename_playlist(self):
        current_name = self.playlist_combo.currentText()
        if current_name in ["默认", "收藏"]:
            QMessageBox.warning(self, "警告", "不能重命名默认或收藏播放列表!")
            return

        new_name, ok = QInputDialog.getText(self, "重命名播放列表", "请输入新名称:", text=current_name)
        if ok and new_name and new_name != current_name:
            if self.player.rename_playlist(current_name, new_name):
                self._refresh_playlist_catalog()
                index = self.playlist_combo.findText(new_name)
                if index >= 0:
                    self.playlist_combo.setCurrentIndex(index)
                self.logger.info(f"重命名播放列表: {current_name} -> {new_name}")
                QMessageBox.information(self, "成功", "重命名成功!")
            else:
                QMessageBox.warning(self, "失败", "新名称已存在!")

    def _delete_playlist(self):
        current_name = self.playlist_combo.currentText()
        if current_name in ["默认", "收藏"]:
            QMessageBox.warning(self, "警告", "不能删除默认或收藏播放列表!")
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            f'确定要删除播放列表 "{current_name}" 吗?',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            # R1-7: 删除前留底,toast 撤销精准还原(免去"删错重建"的痛)
            backup_tracks = [dict(t) for t in config.music_playlists.get(current_name, [])]
            if self.player.delete_playlist(current_name):
                self._refresh_playlist_catalog()
                self.logger.info(f"删除播放列表: {current_name}")

                def _undo(name=current_name, tracks=backup_tracks):
                    if name in config.music_playlists:
                        return  # 撤销窗口内被重建过,不覆盖
                    config.music_playlists[name] = tracks
                    config.save_config()
                    self._refresh_playlist_catalog()
                    self.logger.info(f"撤销删除播放列表: {name}")

                try:
                    from ui_toast import toast_undo

                    toast_undo(f'已删除播放列表 "{current_name}"', _undo)
                except Exception:
                    QMessageBox.information(self, "成功", "删除成功!")

    def _add_local_files(self):
        """添加本地音乐文件"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择音乐文件",
            "",
            "音频文件 (*.mp3 *.wav *.ogg *.flac);;所有文件 (*.*)"
        )
        
        if files:
            for file_path in files:
                try:
                    self.player.add_track(file_path)
                    self.logger.info(f"添加音乐: {file_path}")
                except Exception as e:
                    self.logger.error(f"添加音乐失败: {file_path}, 错误: {e}")
            
            # 刷新显示
            self.refresh_playlist_display()
            QMessageBox.information(self, "成功", f"已添加 {len(files)} 个音乐文件!")
    
    
    def _delete_selected(self):
        """删除选中的项"""
        selected_items = self.playlist_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "提示", "请先选择要删除的音乐!")
            return
        
        reply = QMessageBox.question(self, "确认删除", 
                                     f"确定要删除选中的 {len(selected_items)} 首音乐吗?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            # R1-7: 留底 (行号, 曲目) 以便撤销按原位插回
            playlist_name = self.player.current_playlist_name
            rows = sorted(self.playlist_widget.row(i) for i in selected_items)
            current = config.music_playlists.get(playlist_name, [])
            backup = [(r, dict(current[r])) for r in rows if 0 <= r < len(current)]

            # 从后往前删除，避免索引变化
            for item in reversed(selected_items):
                row = self.playlist_widget.row(item)
                self.player.remove_track(row)
                self.logger.info(f"删除音乐: 索引={row}")
            
            # 刷新显示
            self.refresh_playlist_display()

            def _undo(name=playlist_name, entries=backup):
                # ⚠⚠ RN-457（批 32）：这里原来往 `config.music_playlists` 里插回，
                # 而那是**下游** —— 真源是 `player.playlist`，它单向写进 config。
                # 实测点完撤销：config 5 首、`player.playlist` 4 首、屏幕 4 首。
                # ⭐ **写在下游的撤销，会安静地把内存和磁盘拆成两份。**
                if name != self.player.current_playlist_name:
                    return  # 撤销窗口内切走了别的列表，不越俎代庖
                tracks = list(self.player.get_playlist() or [])
                for row, track in entries:  # 升序插回原位
                    tracks.insert(min(row, len(tracks)), track)
                self.player.restore_playlist(tracks)
                self.refresh_playlist_display()
                self.logger.info(f"撤销删除 {len(entries)} 首音乐")

            try:
                from ui_toast import toast_undo

                if backup:
                    toast_undo(f"已删除 {len(backup)} 首音乐", _undo)
            except Exception:
                pass
    
    def _clear_playlist(self):
        """清空播放列表"""
        playlist = self.player.get_playlist()
        if not playlist:
            QMessageBox.information(self, "提示", "播放列表已经是空的!")
            return
        
        reply = QMessageBox.question(self, "确认清空",
                                     f"确定要清空当前播放列表的所有 {len(playlist)} 首音乐吗?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            # ⚠ RN-457（批 32）：这颗按钮跟旁边两颗红得**一模一样**，
            # 却是三颗里唯一完全没有撤销的一颗 —— 而它一次弄没的东西最多。
            # 外审 18/18 说「三颗红没有区分危险程度」，16/18 猜「删除」最难挽回，
            # 只有 2/18 提到这一颗。⭐ 他们按「名字听起来多严重」排序，
            # 而那个排序和真实的可挽回性正好错开。
            # ⇒ 修法不是把颜色改得不一样，是**把「三颗一样」这句话变成真的**。
            playlist_name = self.player.current_playlist_name
            backup = [dict(track) for track in playlist]
            self.player.clear_playlist()
            self.refresh_playlist_display()
            self.logger.info("清空播放列表")

            def _undo(name=playlist_name, tracks=backup):
                if name != self.player.current_playlist_name:
                    return  # 撤销窗口内切走了别的列表
                if self.player.get_playlist():
                    return  # 撤销窗口内又加了歌，不覆盖用户新做的事
                self.player.restore_playlist(tracks)
                self.refresh_playlist_display()
                self.logger.info(f"撤销清空播放列表: {name}（{len(tracks)} 首）")

            try:
                from ui_toast import toast_undo

                toast_undo(f"已清空 {len(backup)} 首音乐", _undo)
            except Exception:
                pass
    
    def refresh_playlist_display(self, selected_rows=None):
        """刷新播放列表显示，并尽量保留当前选择。"""
        if selected_rows is None:
            selected_rows = self._get_selected_playlist_rows()

        self.playlist_widget.clear()
        playlist = list(self.player.get_playlist() or [])
        self.selected_indices = set()

        if not playlist:
            # RN-455：原来只讲怎么加，不讲加完怎么放 —— 而这一页没有任何播放控件。
            item = QListWidgetItem("播放列表为空\n点右下角「添加音乐」，加完双击歌名就开始放")
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.NoItemFlags)
            self.playlist_widget.addItem(item)
            self._sync_overview_status()
            return

        for i, track in enumerate(playlist):
            title = track.get("title") or os.path.basename(str(track.get("path", "") or "")) or "未知标题"
            artist = str(track.get("artist", "") or "").strip()
            duration = track.get("duration", 0)

            icon = ""
            if self.player.current_index == i:
                if self.player.is_playing and not self.player.is_paused:
                    icon = "▶ "
                elif self.player.is_paused:
                    icon = "⏸ "

            text = f"{i + 1}. {icon}{title}"
            if artist:
                text += f" - {artist}"
            if duration:
                text += f" ({self._format_duration(duration)})"

            self.playlist_widget.addItem(QListWidgetItem(text))

        self._restore_playlist_selection(selected_rows, len(playlist))
        self._sync_overview_status()

    def on_playlist_changed(self, name=None):
        """播放列表切换回调（由播放器调用）"""
        # 更新下拉框选中项
        playlist_name = name if name else self.player.current_playlist_name
        index = self.playlist_combo.findText(playlist_name)
        if index >= 0:
            self.playlist_combo.blockSignals(True)
            self.playlist_combo.setCurrentIndex(index)
            self.playlist_combo.blockSignals(False)
        
        # 刷新播放列表显示
        self.refresh_playlist_display()
    
    def load_settings(self):
        """加载设置"""
        # 游戏联动设置
        self.game_link_checkbox.setChecked(config.music_game_link_enabled)
        self.link_content_frame.setEnabled(config.music_game_link_enabled)
        
        # 死亡设置
        death_action_index = 0 if config.music_death_action == "play" else 1
        self.death_action_group.button(death_action_index).setChecked(True)
        
        death_volume_mode = 1 if config.music_death_volume_custom else 0
        self.death_volume_group.button(death_volume_mode).setChecked(True)
        self.death_volume_slider.setValue(int(config.music_death_volume * 100))
        self.death_volume_label.setText(format_percent(config.music_death_volume))
        
        # 存活设置（原复活设置）
        alive_action_map = {"pause": 0, "lower": 1, "keep": 2}
        alive_action_index = alive_action_map.get(config.music_revive_action, 1)
        self.alive_action_group.button(alive_action_index).setChecked(True)
        self.logger.info(f"复活行为已更新: {config.music_revive_action}")
        
        self.alive_volume_slider.setValue(int(config.music_revive_volume * 100))
        self.alive_volume_label.setText(format_percent(config.music_revive_volume))
        
        self.alive_fade_checkbox.setChecked(config.music_fade_enabled)
        self.fade_out_slider.setValue(int(config.music_fade_out_duration * 10))
        self.fade_out_label.setText(f"{config.music_fade_out_duration:.1f}秒")
        self._refresh_link_control_states()
        
        # 播放模式
        mode_map = {"sequence": 0, "shuffle": 1, "repeat_one": 2, "repeat_all": 3}
        mode_index = mode_map.get(normalize_music_play_mode(config.music_play_mode), 0)
        self.play_mode_group.button(mode_index).setChecked(True)
        
        # 加载播放列表列表
        playlists = self.player.get_all_playlists()
        self.playlist_combo.clear()
        self.playlist_combo.addItems(playlists)
        
        # 设置当前播放列表
        current_playlist = config.music_current_playlist
        index = self.playlist_combo.findText(current_playlist)
        if index >= 0:
            self.playlist_combo.setCurrentIndex(index)
        
        # 刷新播放列表显示
        self.refresh_playlist_display()
        self._sync_overview_status()
        
        self.logger.info("音乐播放器设置已加载")
    def closeEvent(self, event):
        self._detach_player_callbacks()
        super().closeEvent(event)

    def deleteLater(self):
        self._detach_player_callbacks()
        super().deleteLater()
