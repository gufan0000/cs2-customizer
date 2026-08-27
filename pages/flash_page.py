#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Flash 闪光效果页面 - 完全参照原版CustomTkinter布局
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QBoxLayout, QLabel, QPushButton,
    QSlider, QComboBox, QCheckBox, QScrollArea, QFrame,
    QTabWidget, QRadioButton, QButtonGroup, QGridLayout,
    QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from config import config, get_app_data_dir
from core.utils.logger import get_logger
from core.utils.format_utils import format_percent
from flash_process_manager import FlashProcessManager
from pages.audio_status_badge import create_badge_label, render_badges
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from widgets.flash_preview_widget import FlashPreviewWidget
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
import os


class FlashPage(QWidget):
    """闪光效果设置页面"""

    STYLE_TEXT_MAP = {
        "standard": "标准",
        "blur": "模糊",
        "rainbow": "彩虹",
        "wave": "波纹",
        "flicker": "闪烁",
        "spiral": "旋转",
        "particles": "颗粒",
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = config
        self.logger = get_logger("FlashPage")
        
        # 样式参数控件
        self.style_param_frames = {}
        
        # 创建闪光进程管理器
        self.process_manager = FlashProcessManager(config)
        
        # 预览持续时间（秒）
        self.preview_duration = 3
        
        self.init_ui()
        self.load_settings()
        
        # 如果闪光效果已启用，初始化进程
        if hasattr(config, 'flash_enabled') and config.flash_enabled:
            self._init_flash_process()

    @staticmethod
    def _compact_text(text, fallback="未设置", max_length=10):
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    def _current_tab_text(self):
        if not hasattr(self, "tab_widget") or self.tab_widget.count() == 0:
            return "未分组"
        index = self.tab_widget.currentIndex()
        if index < 0:
            index = 0
        return self.tab_widget.tabText(index)

    def _current_style_text(self):
        combo = getattr(self, "style_combo", None)
        if combo is not None and hasattr(combo, "currentText"):
            text = combo.currentText().strip()
            if text:
                return text
        return self.STYLE_TEXT_MAP.get(getattr(config, "flash_style", "standard"), "标准")

    def _current_image_style_text(self):
        style = str(getattr(config, "flash_image_style", "none") or "none")
        if style == "none":
            return "关闭"
        combo = getattr(self, "image_style_combo", None)
        if combo is not None and hasattr(combo, "currentText"):
            text = combo.currentText().strip()
            if text and text != "不使用图片":
                return text
        return style

    def _current_audio_style_text(self):
        style = str(getattr(config, "flash_audio_style", "none") or "none")
        if style == "none":
            return "关闭"
        combo = getattr(self, "audio_style_combo", None)
        if combo is not None and hasattr(combo, "currentText"):
            text = combo.currentText().strip()
            if text and text != "不使用音频":
                return text
        return style

    def _current_media_text(self):
        parts = []
        if str(getattr(config, "flash_image_style", "none") or "none") != "none":
            parts.append("图像")
        if bool(getattr(config, "flash_audio_enabled", False)) and str(getattr(config, "flash_audio_style", "none") or "none") != "none":
            parts.append("音频")
        return "+".join(parts) if parts else "纯背景"

    def _current_bg_color_text(self):
        combo = getattr(self, "bg_color_combo", None)
        if combo is not None and hasattr(combo, "currentText"):
            text = combo.currentText().strip()
            if text:
                return text
        color_map_reverse = {
            "white": "白色",
            "black": "黑色",
            "red": "红色",
            "green": "绿色",
            "blue": "蓝色",
            "yellow": "黄色",
            "cyan": "青色",
            "magenta": "品红",
            "orange": "橙色",
        }
        return color_map_reverse.get(getattr(config, "flash_bg_color", "white"), "白色")

    def _current_transition_text(self):
        fade_in = bool(getattr(config, "flash_fade_in_enabled", True))
        fade_out = bool(getattr(config, "flash_fade_out_enabled", True))
        return f"淡入{'开' if fade_in else '关'} / 淡出{'开' if fade_out else '关'}"

    def _current_runtime_text(self):
        status_text = str(getattr(getattr(self, "preview_status_label", None), "text", lambda: "就绪")()).strip()
        running = bool(getattr(getattr(self, "process_manager", None), "is_running", False))
        if status_text.startswith("预览中"):
            return "预览中", "success"
        if status_text.startswith("正在启动"):
            return "启动中", "info"
        if status_text.startswith("预览失败") or status_text.startswith("打开文件夹失败"):
            return "异常", "danger"
        if running:
            return "已就绪", "success"
        return "待启动", "warn"

    def _set_preview_status(self, text):
        if hasattr(self, "preview_status_label"):
            self.preview_status_label.setText(text)
        self._sync_overview_status()

    def _open_preview_tab(self):
        if hasattr(self, "tab_widget") and self.tab_widget.count() > 0:
            self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)

    def _enable_and_start(self):
        """RN-079：在本页就把总开关打开并启动，不用去别的页找。

        原状是：底栏最醒目的主按钮叫「前往效果预览」—— 一个**不改变任何状态**的
        导航动作，而顶部胶囊常年「效果·未启用 / 运行·待启动」，全页没有任何启动入口。
        外审改前改后都是 **3/3 全票判「高」**，措辞集中在
        「配完不知道怎么让它在 CS2 里生效」。

        ⚠ 写 `config.flash_enabled` 之后**必须回写首页那颗开关**
        （`sync_feature_switch`），否则会出现「首页显示关、实际已开」的三态不一致 ——
        `self.switches` 在 RN-089 之前是个写了从没读过的字典。
        """
        if not bool(getattr(config, "flash_enabled", False)):
            config.flash_enabled = True
            config.save_config()
            self.logger.info("闪光总开关已在本页打开（RN-079）")
            window = self.window()
            if hasattr(window, "sync_feature_switch"):
                window.sync_feature_switch("flash_enabled")
        if not getattr(self.process_manager, "is_running", False):
            self._set_preview_status("正在启动闪光进程...")
            self._init_flash_process()
        self._sync_overview_status()

    #: 这一页在社区站的资源分类（RN-165）。
    COMMUNITY_CATEGORY_KEY = "flash"

    def _image_library_is_empty(self) -> bool:
        combo = getattr(self, "image_style_combo", None)
        return combo is not None and combo.count() == 0

    def _audio_library_is_empty(self) -> bool:
        combo = getattr(self, "audio_style_combo", None)
        return combo is not None and combo.count() == 0

    def _guide_empty_library(self, empty, cta_text, keep_text, keep_callback,
                             refresh_label) -> bool:
        """空库时把底栏换成一条走得通的路。回报有没有改。

        ⚠ **这一页和别的页不一样**：它的主按钮本来就是个状态机
        （按页签在「打开文件夹 / 预览 / 启用 / 启动 / 前往预览」之间切）。
        所以引导只插在「图片设置 / 音频设置」两个页签上 ——
        那两个页签的主按钮正是 RN-165 要治的那种"打开一个空文件夹"。
        ⭐ 空了该长什么样仍然**只有一份**（`widgets/community_library`），
        这一页只决定"什么时候算空、原来那颗按钮是哪一颗"。
        """
        from widgets import community_library

        return community_library.guide_empty_library(
            self.action_bar,
            empty=bool(empty),
            category_key=self.COMMUNITY_CATEGORY_KEY,
            cta_text=cta_text,
            keep_text=keep_text,
            keep_callback=keep_callback,
            message=community_library.empty_library_message(
                "素材", refresh_label),
            callout=getattr(self, "empty_callout", None),   # RN-180
            what="素材",
            refresh_label=refresh_label,
        )

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        # RN-179：把「没得选」的下拉框置灰。
        # ⭐ 这一页正是那条判据**差点诬告**的对象：它的「25%预览」「自定义强度预览」
        # 预览的是软件自己合成的颜色叠加，一个素材都不用 —— 本来就该是亮的。
        # 共用件按"这个控件有没有东西可选"划范围，所以那几颗按钮不会被碰，
        # 而 `image_style_combo` / `audio_style_combo` 空的时候照样会被逮住。
        from widgets import community_library

        community_library.dim_controls_with_nothing_to_pick(
            self, reason=community_library.dim_reason("样式"))

        # RN-180：每次同步先把引导卡收掉。**只有**「图片设置 / 音频设置」两个
        # 页签会把它重新亮起来 —— 其余页签根本不调 `_guide_empty_library`，
        # 不先收就会把上一个页签的引导留在屏幕上（同 RN-153「借了要还」那条）。
        if getattr(self, "empty_callout", None) is not None:
            self.empty_callout.hide()

        current_tab = self._current_tab_text()
        runtime_text, _runtime_level = self._current_runtime_text()
        style_text = self._current_style_text()
        media_text = self._current_media_text()

        if current_tab == "图片设置":
            self.action_bar.configure_secondary("刷新样式列表", self._refresh_styles, visible=True)
            self.action_bar.configure_primary("打开图片文件夹", self._open_flash_images_folder, visible=True)
            action_message = (
                f"当前页面：{current_tab} · 图片样式 {self._current_image_style_text()} / 媒体 {media_text}"
                f" · 运行状态 {runtime_text}。"
            )
            # RN-165：一张图都没有的时候，「打开图片文件夹」点开是个空目录。
            if self._guide_empty_library(self._image_library_is_empty(),
                                         "去社区拿一套自定闪光",
                                         "打开图片文件夹",
                                         self._open_flash_images_folder,
                                         "刷新样式列表"):
                return
        elif current_tab == "音频设置":
            self.action_bar.configure_secondary("刷新音频列表", self._refresh_audio_styles, visible=True)
            self.action_bar.configure_primary("打开音频文件夹", self._open_flash_audio_folder, visible=True)
            action_message = (
                f"当前页面：{current_tab} · 音频 {'已启用' if bool(getattr(config, 'flash_audio_enabled', False)) else '未启用'}"
                f" / {self._current_audio_style_text()} · 运行状态 {runtime_text}。"
            )
            if self._guide_empty_library(self._audio_library_is_empty(),
                                         "去社区拿一套自定闪光",
                                         "打开音频文件夹",
                                         self._open_flash_audio_folder,
                                         "刷新音频列表"):
                return
        elif current_tab == "效果预览":
            self.action_bar.configure_secondary("50%预览", lambda: self._quick_preview(50), visible=True)
            self.action_bar.configure_primary("自定义强度预览", self._preview_flash, visible=True)
            action_message = (
                f"当前页面：{current_tab} · 预览强度 {getattr(self, 'preview_intensity_label', None).text() if hasattr(self, 'preview_intensity_label') else '75%'}"
                f" / {getattr(self, 'preview_status_label', None).text() if hasattr(self, 'preview_status_label') else '就绪'}。"
            )
        else:
            self.action_bar.configure_secondary("重置设置", self._reset_settings, visible=True)
            # ⚠ RN-079：主按钮必须是**能改变状态**的那一个。
            # 原来无条件写「前往效果预览」——一个不改变任何状态的导航动作，
            # 而胶囊常年「效果·未启用 / 运行·待启动」，全页没有启动入口。
            # 现在按当前状态给"下一步真正该做的事"；两样都齐了才退回导航。
            # ⚠ 名字必须说清"打开的是什么"。第一版叫「打开并启动」，外审 3/3 × 多张图
            # 判「高」：「不知道是开启闪光替换、启动后台监听、还是启动游戏」。
            #
            # ⚠⚠ RN-192：RN-189 把总开关搬进这一页的状态卡之后，这里那颗
            # 「启用自定闪光」就成了**第二个开启入口** —— 外审 6/6 票（两档各 3）
            # 「同时存在总开关拨钮与启用按钮，不知道点哪个才算真正生效」。
            # ⭐ 修法不是删掉一个，是**把两件事拆开**：
            #   开关负责「启用」，这颗按钮负责「启动后台监听」——
            #   它们本来就是两件事（`flash_enabled` 与 `process_manager.is_running`），
            #   只是以前被 `_enable_and_start` 合成了一颗按钮，看上去像同一件事。
            # ⚠ 没启用之前把它置灰而不是藏掉：藏掉的话用户不知道开完之后还有一步。
            running = getattr(getattr(self, "process_manager", None), "is_running", False)
            enabled = bool(getattr(config, "flash_enabled", False))
            if not running:
                self.action_bar.configure_primary("启动", self._enable_and_start, visible=True)
                self.action_bar.primary_btn.setEnabled(enabled)
                self.action_bar.primary_btn.setToolTip(
                    "" if enabled else "总开关还没打开——打开之后这里才能启动后台监听")
            else:
                self.action_bar.configure_primary("前往效果预览", self._open_preview_tab, visible=True)
                self.action_bar.primary_btn.setEnabled(True)
                self.action_bar.primary_btn.setToolTip("")
            action_message = (
                f"当前页面：{current_tab} · 闪光样式 {style_text} / 媒体 {media_text}"
                f" · 运行状态 {runtime_text}。"
            )
        self.action_bar.set_message(action_message)

    def on_master_switch_synced(self):
        """总开关被别处拨动后，把本页状态重算一遍（RN-189）。

        ⭐ 全仓统一的钩子名（`widgets/master_switch_link` 调它）。
        少了这一下，开关动了而徽章不动 —— 同屏两处说法不一致（RN-107 族）。
        """
        self._sync_overview_status()

    def _sync_overview_status(self, *_args):
        if not hasattr(self, "status_badge_label"):
            return

        enabled = bool(getattr(config, "flash_enabled", False))
        style_text = self._current_style_text()
        media_text = self._current_media_text()
        current_tab = self._current_tab_text()
        runtime_text, runtime_level = self._current_runtime_text()
        preview_text = str(getattr(getattr(self, "preview_status_label", None), "text", lambda: "就绪")()).strip() or "就绪"

        badges = [
            ("success" if enabled else "warn", f"效果 · {'已启用' if enabled else '未启用'}"),
            ("info", f"样式 · {self._compact_text(style_text)}"),
            ("info" if media_text == "纯背景" else "success", f"媒体 · {self._compact_text(media_text, '纯背景', 8)}"),
            ("info", f"页面 · {self._compact_text(current_tab, '未分组', 8)}"),
            (runtime_level, f"运行 · {runtime_text}"),
        ]

        bg_color_text = self._current_bg_color_text()
        opacity = int(round(float(getattr(config, "flash_max_opacity", 0.75)) * 100))
        fade_in = bool(getattr(config, "flash_fade_in_enabled", True))
        fade_out = bool(getattr(config, "flash_fade_out_enabled", True))
        transition_text = self._current_transition_text()
        image_rotation = str(getattr(config, "flash_image_rotation", "none") or "none")
        audio_enabled = bool(getattr(config, "flash_audio_enabled", False))
        audio_rotation = str(getattr(config, "flash_audio_rotation", "none") or "none")
        audio_volume = int(round(float(getattr(config, "flash_audio_volume", 1.0)) * 100))
        audio_auto_stop = bool(getattr(config, "flash_audio_auto_stop", True))
        x, y = getattr(config, "flash_image_position", (0.5, 0.5))
        w, h = getattr(config, "flash_image_size", (0.3, 0.3))
        preview_intensity = getattr(getattr(self, "preview_intensity_slider", None), "value", lambda: 75)()
        duration = getattr(self, "preview_duration", 3)
        process_running = bool(getattr(getattr(self, "process_manager", None), "is_running", False))

        detail_lines = [
            f"总开关：{'已启用' if enabled else '已关闭'}",
            f"当前页面：{current_tab}",
            f"背景：{bg_color_text} {opacity}% · 淡入{'开' if fade_in else '关'} / 淡出{'开' if fade_out else '关'}",
            f"闪光样式：{style_text}",
            f"图片：{self._current_image_style_text()} · 轮换 {image_rotation} · 不透明度 {format_percent(getattr(config, 'flash_image_opacity', 0.5))}",
            f"图片位置：X {format_percent(x)} / Y {format_percent(y)} · 大小 {format_percent(w)} x {format_percent(h)}",
            f"音频：{'已启用' if audio_enabled else '未启用'} · {self._current_audio_style_text()} · 轮换 {audio_rotation} · 音量 {audio_volume}%",
            f"音频自动停止：{'已启用' if audio_auto_stop else '未启用'}",
            f"预览：强度 {preview_intensity}% · 持续 {duration} 秒 · 状态 {preview_text}",
            f"进程状态：{'已运行' if process_running else '未运行'}",
        ]

        summary_text = "\n".join(detail_lines)
        render_badges(self.status_badge_label, badges, detail_tooltip=summary_text)
        self.status_card.setToolTip(summary_text)
        if hasattr(self, "basic_overview_title_label"):
            self.basic_overview_title_label.setText(f"{bg_color_text}背景 · {opacity}%")
        if hasattr(self, "basic_overview_meta_label"):
            self.basic_overview_meta_label.setText(f"{style_text} · {media_text} · {transition_text}")
        if hasattr(self, "basic_overview_hint_label"):
            image_text = self._current_image_style_text()
            audio_text = self._current_audio_style_text() if audio_enabled else "关闭"
            self.basic_overview_hint_label.setText(
                f"图片 {image_text} · 音频 {audio_text} · 状态 {preview_text} · 运行 {runtime_text}"
            )
        self._sync_action_bar()


    @staticmethod
    def _set_compact_heights(*controls, height=34):
        for control in controls:
            if control is not None:
                control.setMinimumHeight(height)

    @staticmethod
    def _create_slider_row(label_text, slider, value_label, label_width=78):
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel(label_text)
        label.setMinimumWidth(label_width)
        row.addWidget(label)
        row.addWidget(slider, 1)
        value_label.setMinimumWidth(52)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(value_label)
        return row
    
    def init_ui(self):
        """初始化UI"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)
        
        # 页面标题
        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "闪光效果设置",
            # RN-192：「启用自定闪光」这颗按钮已经不存在了（启用归总开关，
            # 按钮只管启动）。⭐ 文案点名的控件名必须跟调用方一起走（RN-167）。
            description="被闪的时候，用你自己的颜色、图片和音效替换游戏默认的闪白。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        main_layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["flash"])

        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(14, 12, 14, 12)
        status_card_layout.setSpacing(8)

        # RN-189：就地总开关。首页「功能开关」里有「自定闪光」，而站在这一页上
        # 拨不到它 —— 实测首页 17 颗开关里有 8 颗是这个样子。
        # ⚠ 拨动一律走 `MainWindow.set_feature_enabled` ⇒ 首页那颗开关 ⇒ 一整串副作用。
        # **同一件事只能有一条链路**，这里绝不自己 `setattr(config, ...)`。
        from widgets.master_switch_link import make_master_switch_row

        self.master_switch_row = make_master_switch_row(
            self, "flash_enabled", "自定闪光")
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

        # ⚠ RN-009：这里原来有一个 `self.summary_label` —— 建出来就 `hide()`，
        # 全仓没有任何一处让它显示回来，而每次状态同步还照给它 `setText` 十行详情。
        # 那十行本来就已经由徽章的 detail_tooltip 和 `status_card.setToolTip()` 给出，
        # 删掉不丢任何信息。
        main_layout.addWidget(self.status_card)

        # RN-180：空库时的第一步放进页面上部，不放底栏。
        # ⚠ 这一页的"空"是**按页签**算的（图片库 / 音频库各一份），
        # 所以这张卡跟着当前页签走 —— `_sync_action_bar` 每次切页签都会重算。
        from widgets.community_library import EmptyLibraryCallout

        self.empty_callout = EmptyLibraryCallout(self)
        main_layout.addWidget(self.empty_callout.frame)
        
        # 创建TabWidget
        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self._sync_overview_status)
        main_layout.addWidget(self.tab_widget, 1)
        
        # 创建5个标签页
        self._create_basic_tab()      # 基础设置
        self._create_style_tab()      # 样式设置
        self._create_image_tab()      # 图片设置
        self._create_audio_tab()      # 音频设置
        self._create_preview_tab()    # 效果预览

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(124)
        self.action_bar.primary_btn.setMinimumWidth(148)
        main_layout.addWidget(self.action_bar, 0)
        self._sync_overview_status()
        self._update_compact_layout()
    
    def _create_basic_tab(self):
        """创建基础设置标签页

        UP-095：这个页签原本**整个没有滚动区**（本文件五个页签里，样式/图片/音频
        三个都有）。它的最小高实测 **599px**，而 1280×800 窗口下页签可视区只有
        458px——Qt 满足不了最小高时不会自己长出滚动条，而是**把控件压扁**，
        实拍到的后果是卡片标题与正文字形直接重叠、不可读。

        为什么会超：`basic_top_layout` 在页宽 < 1180 时按响应式规则改成竖排
        （见 `_apply_responsive_layout`），两张卡从并排 max(159,145) 变成
        相加 159+145+10=314；再加上预览卡的 259（`basic_preview_widget`
        的 minimumHeight 是 180）——8+314+10+259+8 = 599。
        **竖排本身是设计内的**，缺的是"竖排之后装不下怎么办"。

        修法与同文件其它三个页签一致：套一层 `QScrollArea`。装得下时
        `widgetResizable` 让内容跟着可视区长高，预览卡照旧填满下半屏，观感不变；
        装不下时出滚动条，而不是把控件压扁。
        """
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        controls_card, controls_layout = SettingsCard.make(
            "基础参数",
            "被闪时用什么颜色、盖得多浓、淡入淡出多快。",
        )
        controls_grid = QGridLayout()
        controls_grid.setContentsMargins(0, 2, 0, 0)
        controls_grid.setHorizontalSpacing(14)
        controls_grid.setVerticalSpacing(10)

        color_layout = QHBoxLayout()
        color_layout.setSpacing(8)
        self.bg_color_combo = QComboBox()
        self.bg_color_combo.addItems(["白色", "黑色", "红色", "绿色", "蓝色", "黄色", "青色", "品红", "橙色"])
        self.bg_color_combo.setMinimumWidth(132)
        self._set_compact_heights(self.bg_color_combo)
        self.bg_color_combo.currentTextChanged.connect(self._on_bg_color_changed)
        color_layout.addWidget(self.bg_color_combo)
        self.color_preview = QLabel()
        self.color_preview.setFixedSize(30, 30)
        color_layout.addWidget(self.color_preview)
        color_layout.addStretch()
        controls_grid.addWidget(QLabel("背景颜色:"), 0, 0)
        controls_grid.addLayout(color_layout, 0, 1)

        opacity_layout = QHBoxLayout()
        opacity_layout.setSpacing(8)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(1, 100)
        self.opacity_slider.setValue(75)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_layout.addWidget(self.opacity_slider)
        self.opacity_label = QLabel("75%")
        self.opacity_label.setMinimumWidth(50)
        opacity_layout.addWidget(self.opacity_label)
        controls_grid.addWidget(QLabel("背景不透明度:"), 1, 0)
        controls_grid.addLayout(opacity_layout, 1, 1, 1, 3)

        fade_layout = QHBoxLayout()
        fade_layout.setSpacing(8)
        self.fade_in_checkbox = QCheckBox("启用淡入")
        self.fade_in_checkbox.setChecked(True)
        self.fade_in_checkbox.toggled.connect(self._on_fade_in_toggled)
        fade_layout.addWidget(self.fade_in_checkbox)
        self.fade_out_checkbox = QCheckBox("启用淡出")
        self.fade_out_checkbox.setChecked(True)
        self.fade_out_checkbox.toggled.connect(self._on_fade_out_toggled)
        fade_layout.addWidget(self.fade_out_checkbox)
        fade_layout.addStretch()
        controls_grid.addWidget(QLabel("过渡方式:"), 0, 2)
        controls_grid.addLayout(fade_layout, 0, 3)
        controls_grid.setColumnStretch(1, 2)
        controls_grid.setColumnStretch(3, 2)

        controls_layout.addLayout(controls_grid)

        # UP-102: 这个网格里「过渡方式」在第 0 行第 3 列、「背景不透明度」在第 1 行，
        # 但**创建顺序**是 颜色 → 不透明度 → 过渡 —— 而 Qt 的默认 Tab 链跟的是
        # 创建顺序，不是网格位置。于是键盘用户按 Tab 会从「背景颜色」直接跳到
        # 下面一行的不透明度滑块，再**跳回上一行**的两个淡入淡出复选框。
        # 排版毫无异常，坏的只有键盘顺序，所以一直没人看见——与 R8d 在 music 页
        # 查出的那 2 处是同一类缺陷（`UP-077` 的真缺陷部分）。
        #
        # ⚠ 这三行必须写在 `addLayout(controls_grid)` **之后**。写在前面无效：
        # 那时这些控件还没有父控件，等布局被挂到卡片上时它们才被 reparent，
        # 而 reparent 会按插入顺序**重建焦点链**，把 setTabOrder 的结果冲掉。
        # 第一版就写在前面，判据照旧报红——这也是"判据跑红先查前提"的反面：
        # 前提成立时，红就是真的。
        self.setTabOrder(self.bg_color_combo, self.fade_in_checkbox)
        self.setTabOrder(self.fade_in_checkbox, self.fade_out_checkbox)
        self.setTabOrder(self.fade_out_checkbox, self.opacity_slider)

        controls_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.basic_controls_card = controls_card

        overview_card, overview_layout = SettingsCard.make(
            "当前组合",
            "当前这一套配置的摘要：颜色、媒体和预览状态。",
        )
        overview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.basic_overview_card = overview_card

        self.basic_overview_title_label = QLabel("")
        self.basic_overview_title_label.setObjectName("statusLabel")
        overview_layout.addWidget(self.basic_overview_title_label)

        self.basic_overview_meta_label = QLabel("")
        self.basic_overview_meta_label.setObjectName("hintLabel")
        self.basic_overview_meta_label.setWordWrap(True)
        overview_layout.addWidget(self.basic_overview_meta_label)

        self.basic_overview_hint_label = QLabel("")
        self.basic_overview_hint_label.setObjectName("hintLabel")
        self.basic_overview_hint_label.setWordWrap(True)
        overview_layout.addWidget(self.basic_overview_hint_label)

        self.basic_top_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self.basic_top_layout.setSpacing(10)
        self.basic_top_layout.addWidget(controls_card, 5, Qt.AlignTop)
        self.basic_top_layout.addWidget(overview_card, 4, Qt.AlignTop)

        layout.addLayout(self.basic_top_layout)

        # 实时预览卡片（v3.3 新增 — 填充下半屏空白，提供即时视觉反馈）
        preview_card, preview_layout = SettingsCard.make(
            "实时预览",
            "按你当前的颜色和不透明度合成出实际观感；点一下预览区就模拟一次淡入。",
        )
        preview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.basic_preview_widget = FlashPreviewWidget()
        preview_layout.addWidget(self.basic_preview_widget, 1)
        # RN-407 第③件：预览照常合成，旁边一句话说清楚游戏里看不看得到。
        from widgets.master_switch_effect import make_preview_effect_caption

        self.preview_effect_caption = make_preview_effect_caption()
        preview_layout.addWidget(self.preview_effect_caption)
        layout.addWidget(preview_card, 1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.tab_widget.addTab(tab, "基础设置")
    
    def _create_style_tab(self):
        """创建样式设置标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        # 样式选择
        style_layout = QHBoxLayout()
        style_layout.addWidget(QLabel("闪光样式:"))
        
        self.style_combo = QComboBox()
        self.style_combo.addItems(["标准", "模糊", "彩虹", "波纹", "闪烁", "旋转", "颗粒"])
        self.style_combo.setMinimumWidth(150)
        self._set_compact_heights(self.style_combo)
        self.style_combo.currentTextChanged.connect(self._on_style_changed)
        style_layout.addWidget(self.style_combo)
        style_layout.addStretch()
        
        layout.addLayout(style_layout)
        
        # 样式参数区域（可滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        scroll_content = QWidget()
        self.style_params_layout = QVBoxLayout(scroll_content)
        self.style_params_layout.setSpacing(12)
        
        # 创建所有样式的参数卡片（初始隐藏）
        self._create_style_param_cards()
        
        self.style_params_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        # 显示标准样式参数
        self._show_style_params("标准")
        
        self.tab_widget.addTab(tab, "样式设置")
    
    def _create_style_param_cards(self):
        """创建所有样式参数卡片"""
        # 模糊参数
        self.style_param_frames["模糊"] = self._create_param_card(
            "模糊效果参数",
            [
                ("模糊范围:", 0.1, 1.0, 0.3, "_blur_factor"),
                ("模糊层数:", 3, 10, 5, "_blur_layers", True)
            ]
        )
        
        # 彩虹参数
        self.style_param_frames["彩虹"] = self._create_param_card(
            "彩虹效果参数",
            [
                ("颜色速度:", 0.5, 5.0, 2.0, "_rainbow_speed"),
                ("颜色强度:", 0.1, 1.0, 0.3, "_rainbow_intensity")
            ]
        )
        
        # 波纹参数
        self.style_param_frames["波纹"] = self._create_param_card(
            "波纹效果参数",
            [
                ("波纹速度:", 0.5, 5.0, 2.0, "_wave_speed"),
                ("波纹数量:", 1, 10, 3, "_wave_count", True)
            ]
        )
        
        # 闪烁参数
        self.style_param_frames["闪烁"] = self._create_param_card(
            "闪烁效果参数",
            [
                ("闪烁速度:", 1.0, 30.0, 15.0, "_flicker_speed"),
                ("闪烁强度:", 0.1, 1.0, 0.3, "_flicker_intensity")
            ]
        )
        
        # 旋转参数
        self.style_param_frames["旋转"] = self._create_param_card(
            "旋转效果参数",
            [
                ("旋转速度:", 0.5, 5.0, 2.0, "_spiral_speed"),
                ("射线数量:", 3, 30, 12, "_spiral_rays", True)
            ]
        )
        
        # 颗粒参数
        self.style_param_frames["颗粒"] = self._create_param_card(
            "颗粒效果参数",
            [
                ("颗粒数量:", 50, 500, 200, "_particle_count", True),
                ("颗粒大小:", 1, 20, 4, "_particle_size", True)
            ]
        )
    
    def _create_param_card(self, title, params):
        """创建参数卡片"""
        card = QFrame()
        card.setObjectName("card")
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # 标题
        title_label = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        layout.addWidget(title_label)
        
        # 参数滑块
        for param in params:
            if len(param) == 5:
                label_text, min_val, max_val, default_val, attr_name = param
                is_int = False
            else:
                label_text, min_val, max_val, default_val, attr_name, is_int = param
            
            param_layout = QHBoxLayout()
            param_layout.addWidget(QLabel(label_text))
            
            slider = QSlider(Qt.Horizontal)
            if is_int:
                slider.setRange(int(min_val), int(max_val))
                slider.setValue(int(default_val))
            else:
                slider.setRange(int(min_val * 100), int(max_val * 100))
                slider.setValue(int(default_val * 100))
            
            slider.valueChanged.connect(lambda v, a=attr_name, i=is_int: self._on_param_changed(v, a, i))
            param_layout.addWidget(slider)
            
            value_label = QLabel(f"{default_val:.2f}" if not is_int else str(int(default_val)))
            value_label.setMinimumWidth(60)
            param_layout.addWidget(value_label)
            
            # 保存引用
            setattr(self, f"{attr_name}_slider", slider)
            setattr(self, f"{attr_name}_label", value_label)
            
            layout.addLayout(param_layout)
        
        card.hide()  # 初始隐藏
        self.style_params_layout.addWidget(card)
        
        return card
    
    def _create_image_tab(self):
        """创建图片设置标签页"""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(tab)

        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        source_card, source_layout = SettingsCard.make(
            "图片来源",
            "选一套闪光图片。自己往图片文件夹里加了素材，点「刷新样式列表」才会出现在这里。",
        )
        self.image_style_combo = QComboBox()
        self.image_style_combo.addItem("不使用图片", "none")
        self._load_image_styles()
        self.image_style_combo.setMinimumWidth(200)
        self._set_compact_heights(self.image_style_combo)
        self.image_style_combo.currentIndexChanged.connect(self._on_image_style_changed)
        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_row.addWidget(QLabel("图片样式:"))
        source_row.addWidget(self.image_style_combo, 1)
        source_layout.addLayout(source_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        refresh_btn = QPushButton("刷新样式列表")
        refresh_btn.clicked.connect(self._refresh_styles)
        folder_btn = QPushButton("打开图片文件夹")
        folder_btn.clicked.connect(self._open_flash_images_folder)
        reset_btn = QPushButton("重置设置")
        reset_btn.clicked.connect(self._reset_settings)
        self._set_compact_heights(refresh_btn, folder_btn, reset_btn)
        action_row.addWidget(refresh_btn)
        action_row.addWidget(folder_btn)
        action_row.addWidget(reset_btn)
        action_row.addStretch()
        source_layout.addLayout(action_row)
        source_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        behavior_card, behavior_layout = SettingsCard.make(
            "呈现方式",
            "多张图片要不要换着出现，以及图片盖上去有多实。",
        )
        self.image_rotation_combo = QComboBox()
        self.image_rotation_combo.addItem("不轮换", "none")
        self.image_rotation_combo.addItem("随机轮换", "random")
        self.image_rotation_combo.addItem("顺序轮换", "sequence")
        self.image_rotation_combo.setMinimumWidth(150)
        self._set_compact_heights(self.image_rotation_combo)
        self.image_rotation_combo.currentIndexChanged.connect(self._on_image_rotation_changed)
        rotation_row = QHBoxLayout()
        rotation_row.setSpacing(8)
        rotation_row.addWidget(QLabel("图片轮换:"))
        rotation_row.addWidget(self.image_rotation_combo, 1)
        behavior_layout.addLayout(rotation_row)

        self.image_opacity_slider = QSlider(Qt.Horizontal)
        self.image_opacity_slider.setRange(0, 100)
        self.image_opacity_slider.setValue(50)
        self.image_opacity_slider.valueChanged.connect(self._on_image_opacity_changed)
        self.image_opacity_label = QLabel("50%")
        behavior_layout.addLayout(
            self._create_slider_row("图片不透明度:", self.image_opacity_slider, self.image_opacity_label, 92)
        )
        behavior_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(source_card, 5, Qt.AlignTop)
        top_row.addWidget(behavior_card, 4, Qt.AlignTop)
        layout.addLayout(top_row)

        position_card, position_layout = SettingsCard.make(
            "图片位置",
            "用 X / Y 直接微调素材落点，适合和游戏 HUD 避开冲突区域。",
        )
        self.image_x_slider = QSlider(Qt.Horizontal)
        self.image_x_slider.setRange(0, 100)
        self.image_x_slider.setValue(50)
        self.image_x_slider.valueChanged.connect(self._on_image_position_changed)
        self.image_x_label = QLabel("50%")
        position_layout.addLayout(self._create_slider_row("X 轴位置:", self.image_x_slider, self.image_x_label, 86))

        self.image_y_slider = QSlider(Qt.Horizontal)
        self.image_y_slider.setRange(0, 100)
        self.image_y_slider.setValue(50)
        self.image_y_slider.valueChanged.connect(self._on_image_position_changed)
        self.image_y_label = QLabel("50%")
        position_layout.addLayout(self._create_slider_row("Y 轴位置:", self.image_y_slider, self.image_y_label, 86))
        position_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        size_card, size_layout = SettingsCard.make(
            "图片大小",
            "宽高单独控制，裁切类素材和海报类素材都能快速试到顺眼比例。",
        )
        self.image_w_slider = QSlider(Qt.Horizontal)
        self.image_w_slider.setRange(10, 100)
        self.image_w_slider.setValue(30)
        self.image_w_slider.valueChanged.connect(self._on_image_size_changed)
        self.image_w_label = QLabel("30%")
        size_layout.addLayout(self._create_slider_row("宽度占比:", self.image_w_slider, self.image_w_label, 86))

        self.image_h_slider = QSlider(Qt.Horizontal)
        self.image_h_slider.setRange(10, 100)
        self.image_h_slider.setValue(30)
        self.image_h_slider.valueChanged.connect(self._on_image_size_changed)
        self.image_h_label = QLabel("30%")
        size_layout.addLayout(self._create_slider_row("高度占比:", self.image_h_slider, self.image_h_label, 86))
        size_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)
        bottom_row.addWidget(position_card, 1, Qt.AlignTop)
        bottom_row.addWidget(size_card, 1, Qt.AlignTop)
        layout.addLayout(bottom_row)
        layout.addStretch()

        self.tab_widget.addTab(scroll, "图片设置")
    
    def _create_audio_tab(self):
        """创建音频设置标签页"""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(tab)

        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        source_card, source_layout = SettingsCard.make(
            "音频来源",
            "启用开关、样式选择和试听集中展示，调试媒体时更顺手。",
        )
        self.audio_enabled_checkbox = QCheckBox("启用闪光音频")
        self.audio_enabled_checkbox.setChecked(False)
        self.audio_enabled_checkbox.toggled.connect(self._on_audio_enabled_toggled)
        source_layout.addWidget(self.audio_enabled_checkbox)

        self.audio_style_combo = QComboBox()
        self.audio_style_combo.addItem("不使用音频", "none")
        self._load_audio_styles()
        self.audio_style_combo.setMinimumWidth(200)
        self.audio_style_combo.setEnabled(False)
        self._set_compact_heights(self.audio_style_combo)
        self.audio_style_combo.currentIndexChanged.connect(self._on_audio_style_changed)

        self.audio_preview_btn = QPushButton("预览")
        self.audio_preview_btn.setEnabled(False)
        self._set_compact_heights(self.audio_preview_btn)
        self.audio_preview_btn.clicked.connect(self._preview_audio)
        audio_source_row = QHBoxLayout()
        audio_source_row.setSpacing(8)
        audio_source_row.addWidget(QLabel("音频样式:"))
        audio_source_row.addWidget(self.audio_style_combo, 1)
        audio_source_row.addWidget(self.audio_preview_btn)
        source_layout.addLayout(audio_source_row)

        audio_btn_row = QHBoxLayout()
        audio_btn_row.setSpacing(8)
        open_audio_folder_btn = QPushButton("打开音频文件夹")
        open_audio_folder_btn.clicked.connect(self._open_flash_audio_folder)
        refresh_audio_btn = QPushButton("刷新音频列表")
        refresh_audio_btn.clicked.connect(self._refresh_audio_styles)
        self._set_compact_heights(open_audio_folder_btn, refresh_audio_btn)
        audio_btn_row.addWidget(open_audio_folder_btn)
        audio_btn_row.addWidget(refresh_audio_btn)
        audio_btn_row.addStretch()
        source_layout.addLayout(audio_btn_row)
        source_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        behavior_card, behavior_layout = SettingsCard.make(
            "播放行为",
            "被闪时这段音效怎么播：换不换着播、多大声、闪光结束后要不要跟着停。",
        )
        self.audio_rotation_combo = QComboBox()
        self.audio_rotation_combo.addItems(["不轮换", "随机", "顺序"])
        self.audio_rotation_combo.setEnabled(False)
        self.audio_rotation_combo.setMinimumWidth(120)
        self._set_compact_heights(self.audio_rotation_combo)
        self.audio_rotation_combo.currentTextChanged.connect(self._on_audio_rotation_changed)
        rotation_row = QHBoxLayout()
        rotation_row.setSpacing(8)
        rotation_row.addWidget(QLabel("音频轮换:"))
        rotation_row.addWidget(self.audio_rotation_combo, 1)
        behavior_layout.addLayout(rotation_row)

        self.audio_volume_slider = QSlider(Qt.Horizontal)
        self.audio_volume_slider.setRange(0, 100)
        self.audio_volume_slider.setValue(100)
        self.audio_volume_slider.setEnabled(False)
        self.audio_volume_slider.valueChanged.connect(self._on_audio_volume_changed)
        self.audio_volume_label = QLabel("100%")
        behavior_layout.addLayout(
            self._create_slider_row("音频音量:", self.audio_volume_slider, self.audio_volume_label, 78)
        )

        self.audio_auto_stop_checkbox = QCheckBox("闪光结束时自动停止音频")
        self.audio_auto_stop_checkbox.setChecked(True)
        self.audio_auto_stop_checkbox.setEnabled(False)
        self.audio_auto_stop_checkbox.toggled.connect(self._on_audio_auto_stop_toggled)
        behavior_layout.addWidget(self.audio_auto_stop_checkbox)
        behavior_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(source_card, 5, Qt.AlignTop)
        top_row.addWidget(behavior_card, 4, Qt.AlignTop)
        layout.addLayout(top_row)
        layout.addStretch()

        self.tab_widget.addTab(scroll, "音频设置")
    
    def _create_preview_tab(self):
        """创建效果预览标签页

        UP-095 顺带：这是全仓 12 个建页签方法里**最后一个**没有滚动区的。
        它当前不溢出（最小高 346px < 可视 458px），属潜伏风险；补上之后
        「每个页签都要有滚动区」这条判据就能写成 12/12 无豁免，
        不用挂一份会慢慢变长的豁免名单。
        """
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        control_card, control_layout = SettingsCard.make(
            "预览控制",
            "不用进游戏也能试：定好强度和时长，直接放一次看效果。",
        )
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(QLabel("当前状态:"))
        self.preview_status_label = QLabel("就绪")
        self.preview_status_label.setObjectName("badgeLabel")
        self.preview_status_label.setAlignment(Qt.AlignCenter)
        self.preview_status_label.setMinimumWidth(110)
        self.preview_status_label.setMinimumHeight(34)
        status_row.addWidget(self.preview_status_label)
        status_row.addStretch()
        self.preview_btn = QPushButton("自定义强度预览")
        self.preview_btn.setMinimumHeight(40)
        self.preview_btn.clicked.connect(self._preview_flash)
        status_row.addWidget(self.preview_btn)
        control_layout.addLayout(status_row)

        self.preview_intensity_slider = QSlider(Qt.Horizontal)
        self.preview_intensity_slider.setRange(0, 100)
        self.preview_intensity_slider.setValue(75)
        self.preview_intensity_slider.valueChanged.connect(self._on_preview_intensity_changed)
        self.preview_intensity_label = QLabel("75%")
        control_layout.addLayout(
            self._create_slider_row("预览强度:", self.preview_intensity_slider, self.preview_intensity_label, 78)
        )

        duration_layout = QHBoxLayout()
        duration_layout.setSpacing(8)
        duration_layout.addWidget(QLabel("预览持续时间:"))
        self.duration_group = QButtonGroup()
        for duration in [1, 2, 3, 5]:
            radio = QRadioButton(f"{duration}秒")
            radio.setProperty("duration", duration)
            radio.toggled.connect(lambda checked, d=duration: self._on_duration_changed(d) if checked else None)
            self.duration_group.addButton(radio)
            duration_layout.addWidget(radio)
            if duration == 3:
                radio.setChecked(True)
        duration_layout.addStretch()
        control_layout.addLayout(duration_layout)
        control_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout.addWidget(control_card)

        quick_card, quick_layout = SettingsCard.make(
            "快速触发",
            "点一下就按这个强度放一次，不必先调上面的滑块。",
        )
        button_grid = QGridLayout()
        button_grid.setHorizontalSpacing(8)
        button_grid.setVerticalSpacing(8)
        for intensity in [25, 50, 75, 100]:
            btn = QPushButton(f"{intensity}%预览")
            btn.setMinimumHeight(40)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda checked, i=intensity: self._quick_preview(i))
            button_grid.addWidget(btn, 0, [25, 50, 75, 100].index(intensity))
        quick_layout.addLayout(button_grid)
        quick_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout.addWidget(quick_card)

        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.tab_widget.addTab(tab, "效果预览")

    def _update_compact_layout(self):
        if not hasattr(self, "basic_top_layout"):
            return

        direction = QBoxLayout.TopToBottom if self.width() < 1180 else QBoxLayout.LeftToRight
        if self.basic_top_layout.direction() != direction:
            self.basic_top_layout.setDirection(direction)

        if hasattr(self, "basic_overview_card"):
            if direction == QBoxLayout.TopToBottom:
                self.basic_overview_card.setMinimumWidth(0)
                self.basic_overview_card.setMaximumWidth(16777215)
            else:
                self.basic_overview_card.setMinimumWidth(320)
                self.basic_overview_card.setMaximumWidth(380)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_compact_layout()
    
    # ====================  辅助方法  ====================
    
    def _load_image_styles(self):
        """加载图片样式列表"""
        try:
            flash_images_dir = os.path.join(get_app_data_dir(), "resources", "flash_images")
            if os.path.exists(flash_images_dir):
                for folder in os.listdir(flash_images_dir):
                    folder_path = os.path.join(flash_images_dir, folder)
                    if os.path.isdir(folder_path):
                        self.image_style_combo.addItem(folder, folder)
        except Exception as e:
            self.logger.error(f"加载闪光图片列表失败: {e}")
    
    def _load_audio_styles(self):
        """加载音频样式列表"""
        try:
            # 注意：路径应该是 resources/flash_audio，而不是 resources/audio/flash_sounds
            flash_audio_dir = os.path.join(get_app_data_dir(), "resources", "flash_audio")
            if os.path.exists(flash_audio_dir):
                for folder in os.listdir(flash_audio_dir):
                    folder_path = os.path.join(flash_audio_dir, folder)
                    if os.path.isdir(folder_path):
                        self.audio_style_combo.addItem(folder, folder)
        except Exception as e:
            self.logger.error(f"加载闪光音频列表失败: {e}")
    
    def _show_style_params(self, style_name):
        """显示指定样式的参数"""
        # 隐藏所有参数卡片
        for frame in self.style_param_frames.values():
            frame.hide()
        
        # 显示当前样式的参数卡片
        if style_name in self.style_param_frames:
            self.style_param_frames[style_name].show()
    
    # ====================  事件处理  ====================
    
    def _on_bg_color_changed(self, text):
        """背景颜色改变"""
        color_map = {
            "白色": "white", "黑色": "black", "红色": "red",
            "绿色": "green", "蓝色": "blue", "黄色": "yellow",
            "青色": "cyan", "品红": "magenta", "橙色": "orange"
        }
        
        if text in color_map:
            color = color_map[text]
            # 保存到配置
            config.flash_bg_color = color
            config.save_config()
            # 通知进程管理器更新
            if hasattr(self, 'process_manager') and self.process_manager:
                self.process_manager.update_settings(bg_color=color)
                self.logger.info(f"背景颜色已更新: {text}")
            self._sync_overview_status()
            self._sync_basic_preview()

    def _on_opacity_changed(self, value):
        """不透明度改变"""
        self.opacity_label.setText(f"{value}%")
        opacity = value / 100.0
        config.flash_max_opacity = opacity
        config.save_config()
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            self.process_manager.update_settings(max_opacity=opacity)
            self.logger.info(f"背景不透明度已更新: {value}%")
        self._sync_overview_status()
        self._sync_basic_preview()

    def _on_fade_in_toggled(self, checked):
        """淡入效果开关"""
        config.flash_fade_in_enabled = checked
        config.save_config()
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            self.process_manager.update_fade_settings(fade_in_enabled=checked)
            self.logger.info(f"淡入效果: {'启用' if checked else '禁用'}")
        self._sync_overview_status()
        self._sync_basic_preview()

    def _on_fade_out_toggled(self, checked):
        """淡出效果开关"""
        config.flash_fade_out_enabled = checked
        config.save_config()
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            self.process_manager.update_fade_settings(fade_out_enabled=checked)
            self.logger.info(f"淡出效果: {'启用' if checked else '禁用'}")
        self._sync_overview_status()
        self._sync_basic_preview()

    def _sync_basic_preview(self):
        """把当前基础参数推送给预览组件。"""
        widget = getattr(self, "basic_preview_widget", None)
        if widget is None:
            return
        widget.update_settings(
            bg_color=self.bg_color_combo.currentText() if hasattr(self, "bg_color_combo") else None,
            opacity_pct=self.opacity_slider.value() if hasattr(self, "opacity_slider") else None,
            fade_in=self.fade_in_checkbox.isChecked() if hasattr(self, "fade_in_checkbox") else None,
            fade_out=self.fade_out_checkbox.isChecked() if hasattr(self, "fade_out_checkbox") else None,
        )
    
    def _on_style_changed(self, text):
        """样式改变"""
        style_map = {
            "标准": "standard", "模糊": "blur", "彩虹": "rainbow",
            "波纹": "wave", "闪烁": "flicker", "旋转": "spiral", "颗粒": "particles"
        }
        
        if text in style_map:
            style = style_map[text]
            config.flash_style = style
            config.save_config()
            self._show_style_params(text)
            # 通知进程管理器更新
            if hasattr(self, 'process_manager') and self.process_manager:
                self.process_manager.update_flash_style(style)
                self.logger.info(f"闪光样式已更新: {text}")
            self._sync_overview_status()
    
    def _on_param_changed(self, value, attr_name, is_int):
        """样式参数改变"""
        actual_value = value if is_int else value / 100.0
        label = getattr(self, f"{attr_name}_label", None)
        if label:
            if is_int:
                label.setText(str(value))
            else:
                label.setText(f"{actual_value:.2f}")
        
        # 保存样式参数到config
        if not hasattr(config, 'flash_style_params'):
            config.flash_style_params = {}
        
        current_style = config.flash_style
        if current_style not in config.flash_style_params:
            config.flash_style_params[current_style] = {}
        
        # 根据属性名确定参数键名
        param_key = attr_name.lstrip('_')
        config.flash_style_params[current_style][param_key] = actual_value
        config.save_config()
        
        # 更新flash_process_manager
        if hasattr(self, 'process_manager') and self.process_manager.is_running:
            self.process_manager.update_style_parameters(config.flash_style_params[current_style])
        self._sync_overview_status()
    
    def _on_image_style_changed(self, index):
        """图片样式改变"""
        style = self.image_style_combo.currentData()
        config.flash_image_style = style
        config.save_config()
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            if style and style != "none":
                self.process_manager.load_flash_image(style)
                self.logger.info(f"图片样式已更新: {style}")
            else:
                self.process_manager.load_flash_image("none")
                self.logger.info("已禁用图片")
        self._sync_overview_status()
    
    def _on_image_opacity_changed(self, value):
        """图片不透明度改变"""
        self.image_opacity_label.setText(f"{value}%")
        opacity = value / 100.0
        config.flash_image_opacity = opacity
        config.save_config()
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            self.process_manager.update_settings(image_opacity=opacity)
            self.logger.info(f"图片不透明度已更新: {value}%")
        self._sync_overview_status()
    
    def _on_image_position_changed(self):
        """图片位置改变"""
        x = self.image_x_slider.value() / 100.0
        y = self.image_y_slider.value() / 100.0
        self.image_x_label.setText(format_percent(x))
        self.image_y_label.setText(format_percent(y))
        position = (x, y)
        config.flash_image_position = position
        config.save_config()
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            self.process_manager.update_settings(image_position=position)
        self._sync_overview_status()
    
    def _on_image_size_changed(self):
        """图片大小改变"""
        w = self.image_w_slider.value() / 100.0
        h = self.image_h_slider.value() / 100.0
        self.image_w_label.setText(format_percent(w))
        self.image_h_label.setText(format_percent(h))
        size = (w, h)
        config.flash_image_size = size
        config.save_config()
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            self.process_manager.update_settings(image_size=size)
        self._sync_overview_status()
    
    def _on_image_rotation_changed(self, index):
        """图片轮换模式改变"""
        rotation = self.image_rotation_combo.currentData()
        config.flash_image_rotation = rotation
        config.save_config()
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            self.process_manager.update_image_rotation(rotation)
            self.logger.info(f"图片轮换模式已更新: {rotation}")
        self._sync_overview_status()
    
    def _on_audio_enabled_toggled(self, checked):
        """音频开关"""
        config.flash_audio_enabled = checked
        config.save_config()
        
        self.audio_style_combo.setEnabled(checked)
        self.audio_rotation_combo.setEnabled(checked)
        self.audio_volume_slider.setEnabled(checked)
        self.audio_auto_stop_checkbox.setEnabled(checked)
        self.audio_preview_btn.setEnabled(checked and self.audio_style_combo.currentData() != "none")
        
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            self.process_manager.update_audio_enabled(checked)
            self.logger.info(f"音频功能: {'启用' if checked else '禁用'}")
        self._sync_overview_status()
    
    def _on_audio_style_changed(self, index):
        """音频样式改变"""
        style = self.audio_style_combo.currentData()
        config.flash_audio_style = style
        config.save_config()
        
        self.audio_preview_btn.setEnabled(self.audio_enabled_checkbox.isChecked() and style != "none")
        
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            self.process_manager.update_audio_style(style)
            self.logger.info(f"音频样式已更新: {style}")
        self._sync_overview_status()
    
    def _on_audio_rotation_changed(self, text):
        """音频轮换改变"""
        rotation_map = {"不轮换": "none", "随机": "random", "顺序": "sequence"}
        if text in rotation_map:
            rotation = rotation_map[text]
            config.flash_audio_rotation = rotation
            config.save_config()
            # 注意：音频轮换不需要通知process_manager，它是在播放时决定的
            self.logger.info(f"音频轮换模式已更新: {text}")
            self._sync_overview_status()
    
    def _on_audio_volume_changed(self, value):
        """音频音量改变"""
        self.audio_volume_label.setText(f"{value}%")
        volume = value / 100.0
        config.flash_audio_volume = volume
        config.save_config()
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            self.process_manager.update_audio_volume(volume)
            self.logger.info(f"音频音量已更新: {value}%")
        self._sync_overview_status()
    
    def _on_audio_auto_stop_toggled(self, checked):
        """自动停止音频"""
        config.flash_audio_auto_stop = checked
        config.save_config()
        # 通知进程管理器更新
        if hasattr(self, 'process_manager') and self.process_manager:
            self.process_manager.update_auto_stop_setting(checked)
            self.logger.info(f"音频自动停止: {'启用' if checked else '禁用'}")
        self._sync_overview_status()
    
    def _on_preview_intensity_changed(self, value):
        """预览强度改变"""
        self.preview_intensity_label.setText(f"{value}%")
        self._sync_overview_status()
    
    def _refresh_styles(self):
        """刷新样式列表"""
        self.logger.info("刷新闪光样式列表")
        self.image_style_combo.clear()
        self.image_style_combo.addItem("不使用图片", "none")
        self._load_image_styles()
        
        self._set_preview_status("样式列表已刷新")
    
    def _open_flash_images_folder(self):
        """打开闪光图片文件夹"""
        try:
            flash_images_dir = os.path.join(get_app_data_dir(), "resources", "flash_images")
            os.makedirs(flash_images_dir, exist_ok=True)
            os.startfile(flash_images_dir)
            self._set_preview_status("已打开图片文件夹")
            self.logger.info(f"已打开图片文件夹: {flash_images_dir}")
        except Exception as e:
            self.logger.error(f"打开图片文件夹失败: {e}")
            self._set_preview_status(f"打开文件夹失败: {e}")
    
    def _open_flash_audio_folder(self):
        """打开闪光音频文件夹"""
        try:
            flash_audio_dir = os.path.join(get_app_data_dir(), "resources", "flash_audio")
            os.makedirs(flash_audio_dir, exist_ok=True)
            os.startfile(flash_audio_dir)
            self._set_preview_status("已打开音频文件夹")
            self.logger.info(f"已打开音频文件夹: {flash_audio_dir}")
        except Exception as e:
            self.logger.error(f"打开音频文件夹失败: {e}")
            self._set_preview_status(f"打开文件夹失败: {e}")
    
    def _refresh_audio_styles(self):
        """刷新音频样式列表"""
        self.logger.info("刷新闪光音频列表")
        self.audio_style_combo.clear()
        self.audio_style_combo.addItem("不使用音频", "none")
        self._load_audio_styles()
        self._set_preview_status("音频列表已刷新")
        self.logger.info("音频样式列表已刷新")
    
    def _reset_settings(self):
        """重置设置"""
        self.logger.info("重置闪光设置")
        
        # 重置为默认值
        config.flash_bg_color = "white"
        config.flash_max_opacity = 0.75
        config.flash_image_style = "none"
        config.flash_image_opacity = 0.5
        config.flash_image_position = (0.5, 0.5)
        config.flash_image_size = (0.3, 0.3)
        config.flash_style = "standard"
        config.save_config()
        
        # 重新加载设置
        self.load_settings()
        self._set_preview_status("设置已重置为默认值")
    
    def _preview_audio(self):
        """预览音频"""
        try:
            # 检查进程是否运行
            if not self.process_manager.is_running:
                self.logger.warning("闪光进程未运行，无法预览音频")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "提示", "请先在效果预览页面启动闪光进程")
                return
            
            # 检查是否选择了音频样式
            if config.flash_audio_style == "none":
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "提示", "请先选择音频样式")
                return
            
            self.logger.info("预览闪光音频")
            # 调用flash_process_manager的测试音频方法
            self.process_manager.play_test_audio()
            self._set_preview_status("音频预览已触发")
        except Exception as e:
            self.logger.error(f"预览音频失败: {e}")
            self._set_preview_status(f"预览失败: {e}")
    
    def _init_flash_process(self):
        """初始化闪光效果进程"""
        try:
            # 获取主显示器的实际分辨率（考虑DPI缩放）
            from PySide6.QtWidgets import QApplication
            
            screen = QApplication.primaryScreen()
            
            # 使用availableGeometry获取可用屏幕区域（排除任务栏）
            # 或使用geometry获取完整屏幕区域
            screen_geometry = screen.geometry()
            
            # 获取设备像素比率（DPI缩放）
            device_pixel_ratio = screen.devicePixelRatio()
            
            # 计算实际像素尺寸
            screen_width = int(screen_geometry.width() * device_pixel_ratio)
            screen_height = int(screen_geometry.height() * device_pixel_ratio)
            
            self.logger.info(f"屏幕信息: 逻辑尺寸={screen_geometry.width()}x{screen_geometry.height()}, "
                           f"DPI比率={device_pixel_ratio}, 实际尺寸={screen_width}x{screen_height}")
            
            # 启动闪光进程（使用实际像素尺寸以确保全屏覆盖）
            # 对于高DPI显示器（125%、150%等），必须使用物理像素尺寸
            self.process_manager.start_process(screen_width, screen_height)
            self.logger.info(f"闪光效果进程已初始化，使用尺寸: {screen_width}x{screen_height}")
            self._sync_overview_status()
        except Exception as e:
            self.logger.error(f"初始化闪光进程失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            self._set_preview_status(f"初始化失败: {e}")
    
    def _on_duration_changed(self, duration):
        """预览持续时间改变"""
        self.preview_duration = duration
        self.logger.info(f"预览持续时间设置为: {duration}秒")
        self._sync_overview_status()
    
    def _quick_preview(self, intensity):
        """快速预览指定强度的闪光效果"""
        self._preview_with_intensity(intensity / 100.0)
    
    def _preview_flash(self):
        """预览闪光效果（使用自定义强度）"""
        intensity = self.preview_intensity_slider.value() / 100.0
        self._preview_with_intensity(intensity)
    
    def _preview_with_intensity(self, intensity):
        """执行闪光预览"""
        # 检查进程是否运行
        if not self.process_manager.is_running:
            self._set_preview_status("正在启动闪光进程...")
            self._init_flash_process()
            
            # 等待进程启动
            from PySide6.QtCore import QTimer
            QTimer.singleShot(500, lambda: self._do_preview(intensity))
        else:
            self._do_preview(intensity)
    
    def _do_preview(self, intensity):
        """实际执行预览"""
        try:
            self.logger.info(f"开始预览闪光效果: 强度={intensity:.2f}, 持续时间={self.preview_duration}秒")
            self._set_preview_status(f"预览中... ({format_percent(intensity)}, {self.preview_duration}秒)")
            
            # 调用flash_process_manager的preview_flash方法
            self.process_manager.preview_flash(intensity, self.preview_duration)
            
            # 设置定时器恢复状态
            from PySide6.QtCore import QTimer
            QTimer.singleShot(self.preview_duration * 1000 + 500, self._reset_preview_status)
        except Exception as e:
            self.logger.error(f"预览闪光效果失败: {e}")
            self._set_preview_status(f"预览失败: {e}")
    
    def _reset_preview_status(self):
        """重置预览状态"""
        self._set_preview_status("就绪")
    
    def load_settings(self):
        """加载设置"""
        # 加载背景颜色
        color_map_reverse = {
            "white": "白色", "black": "黑色", "red": "红色",
            "green": "绿色", "blue": "蓝色", "yellow": "黄色",
            "cyan": "青色", "magenta": "品红", "orange": "橙色"
        }
        
        bg_color_text = color_map_reverse.get(config.flash_bg_color, "白色")
        index = self.bg_color_combo.findText(bg_color_text)
        if index >= 0:
            self.bg_color_combo.setCurrentIndex(index)
        
        # 加载不透明度
        self.opacity_slider.setValue(int(config.flash_max_opacity * 100))
        
        # 加载淡入淡出
        self.fade_in_checkbox.setChecked(config.flash_fade_in_enabled)
        self.fade_out_checkbox.setChecked(config.flash_fade_out_enabled)

        # 同步预览组件初始状态
        self._sync_basic_preview()

        # 加载样式
        style_map_reverse = {
            "standard": "标准", "blur": "模糊", "rainbow": "彩虹",
            "wave": "波纹", "flicker": "闪烁", "spiral": "旋转", "particles": "颗粒"
        }
        
        style_text = style_map_reverse.get(config.flash_style, "标准")
        style_index = self.style_combo.findText(style_text)
        if style_index >= 0:
            self.style_combo.setCurrentIndex(style_index)
        
        # 加载图片设置
        img_style_index = self.image_style_combo.findData(config.flash_image_style)
        if img_style_index >= 0:
            self.image_style_combo.setCurrentIndex(img_style_index)
        
        self.image_opacity_slider.setValue(int(config.flash_image_opacity * 100))
        
        x, y = config.flash_image_position
        self.image_x_slider.setValue(int(x * 100))
        self.image_y_slider.setValue(int(y * 100))
        
        w, h = config.flash_image_size
        self.image_w_slider.setValue(int(w * 100))
        self.image_h_slider.setValue(int(h * 100))
        
        # 加载图片轮换模式
        img_rotation_index = self.image_rotation_combo.findData(config.flash_image_rotation)
        if img_rotation_index >= 0:
            self.image_rotation_combo.setCurrentIndex(img_rotation_index)
        
        # 加载音频设置
        self.audio_enabled_checkbox.setChecked(config.flash_audio_enabled)
        
        audio_style_index = self.audio_style_combo.findData(config.flash_audio_style)
        if audio_style_index >= 0:
            self.audio_style_combo.setCurrentIndex(audio_style_index)
        
        rotation_map_reverse = {"none": "不轮换", "random": "随机", "sequence": "顺序"}
        rotation_text = rotation_map_reverse.get(config.flash_audio_rotation, "不轮换")
        rotation_index = self.audio_rotation_combo.findText(rotation_text)
        if rotation_index >= 0:
            self.audio_rotation_combo.setCurrentIndex(rotation_index)
        
        self.audio_volume_slider.setValue(int(config.flash_audio_volume * 100))
        self.audio_auto_stop_checkbox.setChecked(config.flash_audio_auto_stop)
        self._sync_overview_status()

    def cleanup(self):
        """清理资源：停止闪光效果进程"""
        if hasattr(self, 'process_manager'):
            self.process_manager.stop_process()
        self._sync_overview_status()
        self.logger.info("闪光效果页面清理完成")
