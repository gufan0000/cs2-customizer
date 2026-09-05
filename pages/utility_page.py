#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
道具瞄点页面 - PySide6 Widget版本
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QTabWidget, QScrollArea, QFrame, QLineEdit,
    QRadioButton, QButtonGroup, QTextEdit, QGridLayout, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QIntValidator

import os
import subprocess
import sys
import keyboard
import threading

from config import config
from core.utils.logger import get_logger
from core.utils.format_utils import format_percent
from pages.audio_status_badge import create_badge_label, render_badges
from theme_manager import get_theme_manager
from resource_manager import ResourceManager
from ui_help_panel import install_help_panel, PAGE_HELP_TEXTS
from ui_style_applier import keep_inline_style
from widgets.page_header import PageHeader
from widgets.page_action_bar import PageActionBar


class UtilityPage(QWidget):
    """道具瞄点页面"""
    
    # 信号
    map_info_updated = Signal(str, str)  # (map_name, team)
    hotkey_set = Signal(str)  # 快捷键设置完成
    _request_utility_list_update = Signal()  # 请求更新道具列表（线程安全）
    _request_map_info_update = Signal(str, str)  # 请求更新地图信息（线程安全）
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("UtilityPage")
        
        # 道具显示控制器引用
        self.utility_display = None
        
        # GSI处理器引用
        self.gsi_handler = None
        
        # 快捷键设置状态
        self.setting_hotkey = False
        
        # 当前地图和阵营
        self.current_map = None
        self.current_team = None
        self._themed_buttons = []
        
        self._create_ui()
        self._load_settings()
        
        # 连接信号
        self.hotkey_set.connect(self._on_hotkey_set)
        # 线程安全的UI更新信号
        self._request_utility_list_update.connect(self._do_update_utility_list)
        self._request_map_info_update.connect(self._do_update_map_info)
        
        self.logger.info("道具瞄点页面初始化完成")
    
    def _create_ui(self):
        """创建UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # 标题
        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        header = PageHeader(
            "道具瞄点",
            # RN-189：总开关已经搬到这一页的状态卡里；原文还**无条件**写"先去开"，
            # 而开关开着的时候它照说不误（RN-034 的最后一笔）。
            description="在游戏里叠一层道具投掷点位参考，按阵营自动切换。设好热键，进对局按一下就出。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["utility"])

        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(14, 12, 14, 12)
        status_card_layout.setSpacing(8)

        # RN-189：就地总开关。首页「功能开关」里有「道具瞄点」，而站在这一页上
        # 拨不到它 —— 实测首页 17 颗开关里有 8 颗是这个样子。
        # ⚠ 拨动一律走 `MainWindow.set_feature_enabled` ⇒ 首页那颗开关 ⇒ 一整串副作用。
        # **同一件事只能有一条链路**，这里绝不自己 `setattr(config, ...)`。
        from widgets.master_switch_link import make_master_switch_row

        self.master_switch_row = make_master_switch_row(
            self, "utility_guide_enabled", "道具瞄点")
        status_card_layout.addWidget(self.master_switch_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_title = QLabel("当前状态")
        status_title.setObjectName("statusLabel")
        status_row.addWidget(status_title)
        self.status_badge_label = create_badge_label()
        status_row.addWidget(self.status_badge_label, 1)
        status_row.addStretch()
        status_card_layout.addLayout(status_row)

        # ⚠⚠⚠ RN-300（批 36）：三颗「未检测到 / 未载入」胶囊就在这张卡上，
        # 而解释它们的话**一句都不在这一屏** —— 页面别处确实写了五处
        # （「等待进入对局」「进入对局后会自动识别…」等），但它们在
        # **「道具管理」页签**和折叠的帮助面板里，而默认页签是「基础设置」。
        # 外审 **6/6 答「不知道接下来该做什么」**。
        # ⭐ 修法不是「补一句指引」（已经有五句），是**把它放到困惑发生的位置**
        #   （批 32 那条）—— 也就是这三颗胶囊的正下方。
        # ⚠ 三颗的成因**不一样**：地图/阵营要**进对局**，道具要**放素材再刷新** ⇒
        #   一句笼统的「去社区拿」在这里是错的答案，得按当前状态分别说。
        self.state_hint_label = QLabel("")
        self.state_hint_label.setObjectName("hintLabel")
        self.state_hint_label.setWordWrap(True)
        status_card_layout.addWidget(self.state_hint_label)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        status_card_layout.addWidget(self.summary_label)
        layout.addWidget(self.status_card)
        
        # 创建选项卡
        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(lambda *_args: self._sync_action_bar())
        layout.addWidget(self.tab_widget, 1)
        
        # 创建各选项卡
        self._create_basic_tab()
        self._create_display_tab()
        self._create_manage_tab()

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(132)
        self.action_bar.primary_btn.setMinimumWidth(148)
        layout.addWidget(self.action_bar, 0)
        self._sync_status_strip()

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

    def _compact_badge_text(self, value, fallback="未检测到", max_length=12):
        text = str(value or "").strip() or fallback
        if len(text) > max_length:
            return text[: max_length - 1] + "…"
        return text

    def _current_utility_count(self):
        utility_data = getattr(self.utility_display, "utility_data", None)
        if not utility_data:
            return 0
        return sum(len(items or []) for items in utility_data.values())

    def _current_tab_text(self):
        if not hasattr(self, "tab_widget") or self.tab_widget.count() == 0:
            return "基础设置"
        index = self.tab_widget.currentIndex()
        if index < 0:
            index = 0
        return self.tab_widget.tabText(index)

    def _update_empty_utility_state(self, message: str | None = None):
        map_text = self.current_map_label.text() if hasattr(self, "current_map_label") else "未检测到"
        team_text = self.current_team_label.text() if hasattr(self, "current_team_label") else "未检测到"
        utility_count = self._current_utility_count()

        if utility_count:
            title = f"当前已载入 {utility_count} 项道具"
            default_message = "当前列表已经载入道具，切换地图或阵营后会自动刷新内容。"
            meta = f"当前来源：{map_text} / {team_text}，列表会按地图与阵营自动切换。"
            hint = "如果刚补过素材，可用下方工具栏手动刷新，让列表立即更新。"
        elif not self.current_map:
            title = "等待进入对局"
            default_message = "未在游戏中\n进入对局后，这里会自动列出当前地图与阵营的道具。"
            meta = "进入对局后会自动识别当前地图与阵营，这里会切换成对应道具列表。"
            hint = "也可以先打开道具文件夹，按地图 / T / CT 目录整理素材。"
        elif self.current_team:
            title = f"{team_text} 阵营暂未配置道具"
            default_message = f"当前阵营 {team_text} 暂无道具\n请在对应阵营文件夹下添加道具图片。"
            meta = f"当前地图：{map_text} · 当前阵营：{team_text}"
            hint = "请补充站位图和瞄点图后刷新列表，系统会自动载入。"
        else:
            title = "当前地图暂未载入道具"
            default_message = "当前地图暂无道具\n请在对应阵营文件夹下添加道具图片。"
            meta = f"当前地图：{map_text} · 阵营尚未识别"
            hint = "可先按 T / CT 子目录整理素材，识别到阵营后会自动切换。"

        if hasattr(self, "empty_utility_title_label"):
            self.empty_utility_title_label.setText(title)
        if hasattr(self, "empty_utility_list_label"):
            self.empty_utility_list_label.setText(message or default_message)
        if hasattr(self, "empty_utility_meta_label"):
            self.empty_utility_meta_label.setText(meta)
        if hasattr(self, "empty_utility_hint_label"):
            self.empty_utility_hint_label.setText(hint)

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        current_tab = self._current_tab_text()
        hotkey_text = self.hotkey_button.text().strip() if hasattr(self, "hotkey_button") else (config.utility_guide_hotkey or "")
        mode_text = "长按" if getattr(config, "utility_guide_mode", "hold") == "hold" else "切换"
        utility_count = self._current_utility_count()
        # ⚠⚠⚠ RN-452（批 36）：这里原来按页签往底栏放五个位置，而**五个都是
        # 卡内某颗按钮的第二份**（次位「打开道具文件夹」= `open_folder_btn`；
        # 主位「预览显示」= `preview_btn`；「打开当前阵营/地图文件夹」=
        # `open_team_folder_btn` / `open_map_folder_btn`；「刷新道具列表」= `refresh_btn`）。
        # ⭐⭐⭐ 批 31 量过全站 36 处这种重复，**没有一处是底栏独有的动作**；
        #   而这一页占 5 处，是**最多的一页** —— 底栏在这里是它那条结论的极端形态。
        # ⇒ 按批 31 的裁定规则②（都看得见时，留**离它作用的对象最近**的那一颗）：
        #   卡内那几颗就在它们的语境里（「快速操作」卡 / 显示设置卡），底栏这五个全撤。
        # ⚠ 底栏**留着** —— 那句回执（总开关关着 + 当前标签摘要）是它自己的活，
        #   不是副本。⭐ 同一条规则在 `fun_afterlife` 上给出的是相反答案
        #   （那一页没有页级主操作，连底栏都不加）——**而那正是它有内容的证据**。
        self.action_bar.configure_secondary("", None, visible=False)
        self.action_bar.configure_primary("", None, visible=False)

        if current_tab == "显示设置":
            opacity_text = self.opacity_label.text() if hasattr(self, "opacity_label") else "100%"
            scale_text = self.scale_label.text() if hasattr(self, "scale_label") else "100%"
            action_message = (
                f"当前标签：{current_tab} · 图片透明度 {opacity_text} / 缩放 {scale_text}，"
                "调完参数后可直接预览效果。"
            )
        elif current_tab == "道具管理":
            action_message = (
                f"当前标签：{current_tab} · 地图 {self.current_map_label.text() if hasattr(self, 'current_map_label') else '未检测到'}"
                f" / 阵营 {self.current_team_label.text() if hasattr(self, 'current_team_label') else '未检测到'}"
                f" · 已载入 {utility_count} 项道具。"
            )
        else:
            action_message = (
                f"当前标签：{current_tab} · 热键 {hotkey_text or '未设置'} / 模式 {mode_text}"
                f" · 当前已载入 {utility_count} 项道具。"
            )
        self.action_bar.set_message(action_message)

    def on_master_switch_synced(self):
        """总开关被别处拨动后，把本页状态重算一遍（RN-189）。

        ⭐ 全仓统一的钩子名（`widgets/master_switch_link` 调它）。
        少了这一下，开关动了而徽章不动 —— 同屏两处说法不一致（RN-107 族）。
        """
        self._sync_status_strip()

    def _gsi_cfg_ready(self) -> bool:
        """游戏里那份 GSI 配置文件在不在。

        ⚠ **结果缓存**：`_sync_status_strip` 每次刷新状态都会走到这里
        （切页签、改热键、GSI 每帧回调都算），不能每次去 stat 一次磁盘。
        ⭐ 缓存在「重选 CS2 目录」之后会过期 —— 那条路径会重写 cfg，
          而这一页不订阅它。所以缓存只在**本页实例的生命周期内**有效，
          切走再回来（懒加载页会保留实例）拿到的仍是旧值。
          ⚠ 这是**明写出来的取舍**，不是没想到：这句话的用途是「别把人推错方向」，
          而设完目录之后它退化成「进对局」那一句 —— 那一句在那个状态下是对的。

        ⚠ 查不出来的时候返回 **False**（＝显示「先去设目录」），不是 True。
        ⭐ 两个方向都会错，但错的代价不一样：
          说「进对局」而其实没配置 ⇒ 玩家进十局也没反应，判定软件坏了；
          说「去设目录」而其实已配置 ⇒ 玩家白跑一趟设置页，看见目录已经填好了。

        ⛔ **只看 `config.csgo_dir`，不许去全盘搜安装目录**（RN-473）。
        这里原来有一条 `find_cfg_path()` 兜底，它走注册表/磁盘去探测真实的 CS2 安装 ——
        于是这一页描述的是**这台机器**，而不是**这个软件的配置**：
        本机（装了 CS2）答"已装好"、CI（没装）答"还没装"，`utility` 的关档基线
        因此在两边永远对不上，而红的原因跟被判的那次改动毫无关系。
        ⭐ 而这条兜底在产品语义上也是多余的：这句话只在**地图和阵营都没认出来**时
          才显示；GSI 真在别处生效的话，地图早就认出来了，这句话根本不会出现。
        ⭐⭐ 它藏了很久，是因为上面那个 `if not ready:` 是**短路**的 ——
          审计沙箱里恰好攒着一份陈年 GSI cfg，第一支永远为真，
          于是探针量到"全盘搜 0 次调用"，看起来像"这条路不存在"。
        """
        cached = getattr(self, "_gsi_cfg_ready_cache", None)
        if cached is not None:
            return cached
        ready = False
        try:
            csgo_dir = str(getattr(config, "csgo_dir", "") or "").strip()
            if csgo_dir:
                ready = os.path.isfile(os.path.join(
                    csgo_dir, "game", "csgo", "cfg",
                    "gamestate_integration_cs2customizer.cfg"))
        except Exception:
            ready = False
        self._gsi_cfg_ready_cache = ready
        return ready

    def _sync_status_strip(self):
        hotkey_text = config.utility_guide_hotkey or ""
        if hasattr(self, "hotkey_button"):
            hotkey_text = self.hotkey_button.text().strip() or hotkey_text

        mode_text = "长按" if getattr(config, "utility_guide_mode", "hold") == "hold" else "切换"
        map_text = self._compact_badge_text(
            self.current_map_label.text() if hasattr(self, "current_map_label") else "",
            "未检测到",
        )
        team_text = self._compact_badge_text(
            self.current_team_label.text() if hasattr(self, "current_team_label") else "",
            "未检测到",
        )
        utility_count = self._current_utility_count()
        badges = [
            (
                "positive" if hotkey_text and hotkey_text != "按下新键..." else "warning",
                f"热键 · {self._compact_badge_text(hotkey_text, '未设置', 10)}",
            ),
            ("info", f"模式 · {mode_text}"),
            ("positive" if self.current_map else "warning", f"地图 · {map_text}"),
            ("positive" if self.current_team else "warning", f"阵营 · {team_text}"),
            (
                "positive" if utility_count else ("info" if self.current_map else "warning"),
                f"道具 · {utility_count} 项" if utility_count else "道具 · 未载入",
            ),
        ]

        detail_text = (
            f"当前热键：{hotkey_text or '未设置'}\n"
            f"显示模式：{mode_text}\n"
            f"地图：{self.current_map_label.text() if hasattr(self, 'current_map_label') else '未检测到'}\n"
            f"阵营：{self.current_team_label.text() if hasattr(self, 'current_team_label') else '未检测到'}\n"
            f"已载入道具：{utility_count} 项"
        )
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        if hasattr(self, "manage_context_badge_label"):
            render_badges(
                self.manage_context_badge_label,
                [
                    ("positive" if self.current_map else "warning", f"地图 · {map_text}"),
                    ("positive" if self.current_team else "warning", f"阵营 · {team_text}"),
                    (
                        "positive" if utility_count else ("info" if self.current_map else "warning"),
                        f"道具 · {utility_count} 项" if utility_count else "道具 · 未载入",
                    ),
                ],
                detail_tooltip=detail_text,
            )
            self.manage_context_label.setText(
                f"当前来源：{self.current_map_label.text() if hasattr(self, 'current_map_label') else '未检测到'}"
                f" / {self.current_team_label.text() if hasattr(self, 'current_team_label') else '未检测到'}，"
                f"已载入 {utility_count} 项道具。"
            )
            self.manage_context_label.setToolTip(detail_text)
        # RN-300：按当前状态说清「为什么是没有、接下来做什么」。
        # ⚠⚠⚠ 这里的第一版写的是「要进对局才认得出来（软件靠 GSI 读）」——
        # 改完复跑外审，**两轮 6 发都判高**：「未说明是否需安装 CS2 配置文件，
        # 玩家无法确认游戏联动是否已配置就绪」。核下来它说对了，而且比它说的更糟：
        # ⭐⭐⭐ **那句话在「GSI 配置文件还没写进游戏」这个状态下是假的** ——
        #   这种玩家进多少局都不会有地图，而我的指路把他推去进对局，
        #   然后他会得出「软件坏了」。
        # ⭐ 这正是批 32 那条的第二次现身：**一句正确的指路，会把「路的那一头
        #   看不见」变成一个新缺陷** —— 只是这次「路的那一头」是一个前置步骤。
        missing = []
        if not self.current_map or not self.current_team:
            if self._gsi_cfg_ready():
                missing.append("「地图」和「阵营」要进对局才认得出来（软件从游戏里实时读）")
            else:
                missing.append(
                    "「地图」和「阵营」现在还认不出来：软件要先往 CS2 里写一份配置文件才读得到，"
                    "去「高级设置」页选一次 CS2 安装目录就会自动写好")
        if not utility_count:
            missing.append(
                f"道具要先把图片放进道具文件夹，再点「{self.refresh_utility_btn.text()}」")
        self.state_hint_label.setText(
            "；".join(missing) + "。" if missing
            else "地图、阵营、道具都就位了，按热键就能在游戏里叫出来。"
        )

        self._update_empty_utility_state()
        self.summary_label.setText(detail_text)
        self.summary_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)
        self._sync_action_bar()
    
    def _create_basic_tab(self):
        """创建基础设置选项卡"""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(tab)
        
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        
        settings_frame = QFrame()
        settings_frame.setObjectName("card")
        settings_layout = QVBoxLayout(settings_frame)
        settings_layout.setContentsMargins(14, 14, 14, 14)
        settings_layout.setSpacing(8)

        settings_title = QLabel("快捷与模式")
        settings_title.setObjectName("statusLabel")
        settings_layout.addWidget(settings_title)
        # ⚠ RN-077（批 36）：这句原文是「热键和显示模式**放在一起**，改完可以立刻切到
        # 其他标签继续维护」—— 讲的是**版面决策**，不是这张卡能干什么。
        # ⭐ RN-077 那条判据（`test_no_layout_self_talk_sitewide`）**看不见它** ——
        #   它走 AST 认卡片工厂的 `description=` 实参，而这一页的卡是手搓的
        #   `QFrame(objectName="card")` + 裸 `QLabel`。⇒ 见批 36 那条新的运行期通路。
        settings_hint = QLabel("设定呼出点位图的按键，以及按住才显示还是按一下常驻。")
        settings_hint.setObjectName("hintLabel")
        settings_hint.setWordWrap(True)
        settings_layout.addWidget(settings_hint)
        
        # 快捷键设置
        hotkey_layout = QHBoxLayout()
        hotkey_layout.setSpacing(8)
        hotkey_layout.addWidget(QLabel("快捷键:"), 0)
        
        self.hotkey_button = QPushButton(config.utility_guide_hotkey)
        self.hotkey_button.setFixedWidth(108)
        self.hotkey_button.setFixedHeight(36)
        self.hotkey_button.clicked.connect(self._set_hotkey)
        self.hotkey_button.setCursor(Qt.PointingHandCursor)
        hotkey_layout.addWidget(self.hotkey_button, 0)
        
        hint = QLabel("(点击设置)")
        hint.setObjectName("hintLabel")
        hotkey_layout.addWidget(hint, 0)
        hotkey_layout.addStretch(1)
        
        settings_layout.addLayout(hotkey_layout)
        
        # 显示模式
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(8)
        mode_layout.addWidget(QLabel("显示模式:"), 0)
        
        self.mode_group = QButtonGroup(self)
        
        self.hold_radio = QRadioButton("长按显示")
        self.hold_radio.setChecked(config.utility_guide_mode == "hold")
        self.hold_radio.toggled.connect(self._update_mode)
        self.mode_group.addButton(self.hold_radio)
        mode_layout.addWidget(self.hold_radio, 0)
        
        self.toggle_radio = QRadioButton("切换显示")
        self.toggle_radio.setChecked(config.utility_guide_mode == "toggle")
        self.toggle_radio.toggled.connect(self._update_mode)
        self.mode_group.addButton(self.toggle_radio)
        mode_layout.addWidget(self.toggle_radio, 0)
        
        mode_layout.addStretch(1)
        settings_layout.addLayout(mode_layout)

        settings_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        button_frame = QFrame()
        button_frame.setObjectName("card")
        button_layout = QVBoxLayout(button_frame)
        button_layout.setContentsMargins(14, 14, 14, 14)
        button_layout.setSpacing(8)
        
        button_title = QLabel("快速操作")
        button_title.setObjectName("statusLabel")
        button_layout.addWidget(button_title)
        button_hint = QLabel("打开存放点位图的文件夹，或让软件重新读一遍里面的图片。")
        button_hint.setObjectName("hintLabel")
        button_hint.setWordWrap(True)
        button_layout.addWidget(button_hint)
        
        # 按钮样式（使用主题色）
        from theme_manager import get_color
        button_style = f"""
            QPushButton {{
                background-color: {get_color('bg_secondary')};
                color: {get_color('text_primary')};
                border: 1px solid {get_color('border_primary')};
                border-radius: 8px;
                padding: 8px 12px;
                text-align: center;
                font-weight: 600;
                min-height: 38px;
            }}
            QPushButton:hover {{
                background-color: {get_color('accent_hover')};
                border-color: {get_color('accent_primary')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('accent_pressed')};
                border-color: {get_color('accent_primary')};
            }}
            QPushButton:disabled {{
                background-color: {get_color('bg_tertiary')};
                color: {get_color('text_tertiary')};
                border-color: {get_color('border_primary')};
            }}
        """

        button_grid = QGridLayout()
        button_grid.setHorizontalSpacing(8)
        button_grid.setVerticalSpacing(8)
        button_grid.setColumnStretch(0, 1)
        button_grid.setColumnStretch(1, 1)

        open_folder_btn = QPushButton("打开道具文件夹")
        open_folder_btn.clicked.connect(self._open_utility_folder)
        open_folder_btn.setCursor(Qt.PointingHandCursor)
        open_folder_btn.setStyleSheet(button_style)
        self._themed_buttons.append(open_folder_btn)
        button_grid.addWidget(open_folder_btn, 0, 0)
        
        self.open_map_folder_btn = QPushButton("打开当前地图文件夹")
        # ⚠ RN-302（批 36）：这颗按钮在没进对局时是禁用的，而**鼠标停上去什么都不说** ——
        # 外审 6/6 答「有置灰按钮，但画面上没有说为什么」。
        # ⭐ 批 23（RN-150）管的是「看不看得出它禁用了」；这一条问的是「知不知道为什么」。
        self.open_map_folder_btn.setToolTip(
            "要先进对局：软件靠 GSI 认出你当前在哪张图，才知道该打开哪个文件夹。")
        self.open_map_folder_btn.clicked.connect(self._open_current_map_folder)
        self.open_map_folder_btn.setEnabled(False)
        self.open_map_folder_btn.setCursor(Qt.PointingHandCursor)
        self.open_map_folder_btn.setStyleSheet(button_style)
        self._themed_buttons.append(self.open_map_folder_btn)
        button_grid.addWidget(self.open_map_folder_btn, 0, 1)
        
        self.open_team_folder_btn = QPushButton("打开当前阵营文件夹")
        self.open_team_folder_btn.setToolTip(
            "要先进对局：阵营（T / CT）是进对局之后才知道的。")
        self.open_team_folder_btn.clicked.connect(self._open_current_team_folder)
        self.open_team_folder_btn.setEnabled(False)
        self.open_team_folder_btn.setCursor(Qt.PointingHandCursor)
        self.open_team_folder_btn.setStyleSheet(button_style)
        self._themed_buttons.append(self.open_team_folder_btn)
        button_grid.addWidget(self.open_team_folder_btn, 1, 0)
        
        # RN-519：状态条那句话要点名它，名字只能有一份。
        self.refresh_utility_btn = QPushButton("刷新道具列表")
        refresh_btn = self.refresh_utility_btn
        refresh_btn.clicked.connect(self._refresh_utilities)
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setStyleSheet(button_style)
        self._themed_buttons.append(refresh_btn)
        button_grid.addWidget(refresh_btn, 1, 1)
        button_layout.addLayout(button_grid)

        button_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top_cards_row = QHBoxLayout()
        top_cards_row.setSpacing(12)
        # ⚠ RN-470（批 36）：这两句原来是 `addWidget(..., Qt.AlignTop)` 配上
        # `QSizePolicy.Maximum` —— **两句各自都正确**（不想让卡无限拉伸、想让它贴顶），
        # 合在一起才产出「谁内容少谁短一截」：实测 158px vs 192px，**底部差 34px**。
        # ⭐ 又一次「两条各自正确的规则在交集处出错」（批 25）。
        # ⇒ 去掉 AlignTop、把纵向策略从 Maximum 放到 Preferred，
        #   HBox 就会把两张卡都拉到这一排的高度（= 两者中较高的那个）。
        top_cards_row.addWidget(settings_frame, 3)
        top_cards_row.addWidget(button_frame, 5)
        # v2.1.1: 稀疏内容上下夹 stretch 实现垂直居中, 避免底部大片空白
        layout.addStretch(1)
        layout.addLayout(top_cards_row)
        layout.addStretch(2)
        
        self.tab_widget.addTab(scroll, "基础设置")
        
        # Register theme change callback
        get_theme_manager().register_theme_changed_callback(self._apply_theme_styles)
    
    def _apply_theme_styles(self):
        """重新应用主题样式到所有按钮"""
        from theme_manager import get_color
        button_style = f"""
            QPushButton {{
                background-color: {get_color('bg_secondary')};
                color: {get_color('text_primary')};
                border: 1px solid {get_color('border_primary')};
                border-radius: 8px;
                padding: 8px 12px;
                text-align: center;
                font-weight: 600;
                min-height: 38px;
            }}
            QPushButton:hover {{
                background-color: {get_color('accent_hover')};
                border-color: {get_color('accent_primary')};
            }}
            QPushButton:pressed {{
                background-color: {get_color('accent_pressed')};
                border-color: {get_color('accent_primary')};
            }}
            QPushButton:disabled {{
                background-color: {get_color('bg_tertiary')};
                color: {get_color('text_tertiary')};
                border-color: {get_color('border_primary')};
            }}
        """
        for btn in self._themed_buttons:
            keep_inline_style(btn)  # UP-019: 样式由 token 现算,免于统一清理
            btn.setStyleSheet(button_style)

    def _create_display_tab(self):
        """创建显示设置选项卡"""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(tab)
        
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        settings_row = QHBoxLayout()
        settings_row.setSpacing(12)

        image_frame = QFrame()
        image_frame.setObjectName("card")
        image_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        image_layout = QVBoxLayout(image_frame)
        image_layout.setContentsMargins(14, 12, 14, 12)
        image_layout.setSpacing(8)

        image_title = QLabel("图片显示")
        image_title.setObjectName("statusLabel")
        image_layout.addWidget(image_title)
        image_hint = QLabel("透明度和缩放放在同一块，方便先把整体观感调顺。")
        image_hint.setObjectName("hintLabel")
        image_hint.setWordWrap(True)
        image_layout.addWidget(image_hint)
        
        opacity_layout = QHBoxLayout()
        opacity_layout.setSpacing(8)
        opacity_layout.addWidget(QLabel("图片透明度:"), 0)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(int(config.utility_guide_opacity * 100))
        self.opacity_slider.valueChanged.connect(self._update_opacity)
        opacity_layout.addWidget(self.opacity_slider, 1)
        self.opacity_label = QLabel(format_percent(config.utility_guide_opacity))
        self.opacity_label.setFixedWidth(48)
        self.opacity_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        opacity_layout.addWidget(self.opacity_label, 0)
        image_layout.addLayout(opacity_layout)

        scale_layout = QHBoxLayout()
        scale_layout.setSpacing(8)
        scale_layout.addWidget(QLabel("图片大小:"), 0)
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(50, 200)
        self.scale_slider.setValue(int(config.utility_guide_scale * 100))
        self.scale_slider.valueChanged.connect(self._update_scale)
        scale_layout.addWidget(self.scale_slider, 1)
        self.scale_label = QLabel(format_percent(config.utility_guide_scale, hi=2.0))
        self.scale_label.setFixedWidth(48)
        self.scale_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        scale_layout.addWidget(self.scale_label, 0)
        image_layout.addLayout(scale_layout)

        position_frame = QFrame()
        position_frame.setObjectName("card")
        position_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        position_layout = QVBoxLayout(position_frame)
        position_layout.setContentsMargins(14, 12, 14, 12)
        position_layout.setSpacing(8)

        position_title = QLabel("定位与预览")
        position_title.setObjectName("statusLabel")
        position_layout.addWidget(position_title)
        position_hint = QLabel("X / Y 是瞄点图相对默认位置的偏移，改完可以直接预览效果。")
        position_hint.setObjectName("hintLabel")
        position_hint.setWordWrap(True)
        position_layout.addWidget(position_hint)

        offset_row = QHBoxLayout()
        offset_row.setSpacing(8)
        offset_row.addWidget(QLabel("X:"), 0)
        self.x_offset_edit = QLineEdit(str(config.utility_guide_position_x))
        self.x_offset_edit.setFixedWidth(60)
        self.x_offset_edit.setValidator(QIntValidator(-1000, 1000))
        self.x_offset_edit.textChanged.connect(self._update_position)
        offset_row.addWidget(self.x_offset_edit, 0)
        offset_row.addWidget(QLabel("Y:"), 0)
        self.y_offset_edit = QLineEdit(str(config.utility_guide_position_y))
        self.y_offset_edit.setFixedWidth(60)
        self.y_offset_edit.setValidator(QIntValidator(-1000, 1000))
        self.y_offset_edit.textChanged.connect(self._update_position)
        offset_row.addWidget(self.y_offset_edit, 0)

        preview_btn = QPushButton("预览")
        preview_btn.setFixedWidth(92)
        preview_btn.clicked.connect(self._preview_display)
        preview_btn.setCursor(Qt.PointingHandCursor)
        offset_row.addWidget(preview_btn, 0)
        offset_row.addStretch(1)
        position_layout.addLayout(offset_row)

        position_tip = QLabel("正值向右 / 向下偏移，负值用于回拉。")
        position_tip.setObjectName("hintLabel")
        position_layout.addWidget(position_tip)
        self._themed_buttons.append(preview_btn)

        menu_frame = QFrame()
        menu_frame.setObjectName("card")
        menu_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        menu_layout = QVBoxLayout(menu_frame)
        menu_layout.setContentsMargins(14, 12, 14, 12)
        menu_layout.setSpacing(8)

        menu_title = QLabel("菜单显示")
        menu_title.setObjectName("statusLabel")
        menu_layout.addWidget(menu_title)
        menu_hint = QLabel("菜单层单独控制透明度和停留时长，切换模式下更直观。")
        menu_hint.setObjectName("hintLabel")
        menu_hint.setWordWrap(True)
        menu_layout.addWidget(menu_hint)
        
        menu_opacity_layout = QHBoxLayout()
        menu_opacity_layout.setSpacing(8)
        menu_opacity_layout.addWidget(QLabel("菜单透明度:"), 0)
        self.menu_opacity_slider = QSlider(Qt.Horizontal)
        self.menu_opacity_slider.setRange(50, 100)
        menu_opacity = getattr(config, 'utility_guide_menu_opacity', 0.8)
        self.menu_opacity_slider.setValue(int(menu_opacity * 100))
        self.menu_opacity_slider.valueChanged.connect(self._update_menu_opacity)
        menu_opacity_layout.addWidget(self.menu_opacity_slider, 1)
        self.menu_opacity_label = QLabel(format_percent(menu_opacity))
        self.menu_opacity_label.setFixedWidth(48)
        self.menu_opacity_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        menu_opacity_layout.addWidget(self.menu_opacity_label, 0)
        menu_layout.addLayout(menu_opacity_layout)

        duration_layout = QHBoxLayout()
        duration_layout.setSpacing(8)
        duration_layout.addWidget(QLabel("图片显示时长:"), 0)
        duration = getattr(config, 'utility_guide_display_duration', 10)
        self.duration_edit = QLineEdit(str(duration))
        self.duration_edit.setFixedWidth(60)
        self.duration_edit.setValidator(QIntValidator(0, 999))
        self.duration_edit.textChanged.connect(self._update_duration)
        duration_layout.addWidget(self.duration_edit, 0)
        duration_hint = QLabel("秒 (切换模式下，0=永久显示)")
        duration_hint.setObjectName("hintLabel")
        duration_hint.setWordWrap(True)
        duration_layout.addWidget(duration_hint, 0)
        duration_layout.addStretch(1)
        menu_layout.addLayout(duration_layout)

        settings_row.addWidget(image_frame, 4, Qt.AlignTop)
        settings_row.addWidget(position_frame, 3, Qt.AlignTop)
        settings_row.addWidget(menu_frame, 4, Qt.AlignTop)
        layout.addLayout(settings_row)
        layout.addStretch(1)
        self._apply_theme_styles()

        self.tab_widget.addTab(scroll, "显示设置")
    
    def _create_manage_tab(self):
        """创建道具管理选项卡"""
        # UP-072: 三个页签里只有这个没套滚动区，实测 1200x800 下最小高超出可视区 30px
        # (2/4 个主题x字号组合)。与另外两个页签保持一致。
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(tab)

        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        context_frame = QFrame()
        context_frame.setObjectName("card")
        context_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        context_layout = QVBoxLayout(context_frame)
        context_layout.setContentsMargins(14, 12, 14, 12)
        context_layout.setSpacing(8)

        context_title = QLabel("当前上下文")
        context_title.setObjectName("statusLabel")
        context_layout.addWidget(context_title)

        self.manage_context_badge_label = create_badge_label()
        context_layout.addWidget(self.manage_context_badge_label)

        self.current_map_label = QLabel("未检测到")
        self.current_team_label = QLabel("未检测到")
        self.manage_context_label = QLabel("地图和阵营会决定自动加载哪个目录，列表会周期刷新。")
        self.manage_context_label.setObjectName("hintLabel")
        self.manage_context_label.setWordWrap(True)
        context_layout.addWidget(self.manage_context_label)
        top_row.addWidget(context_frame, 4, Qt.AlignTop)

        list_frame = QFrame()
        list_frame.setObjectName("card")
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(14, 12, 14, 12)
        list_layout.setSpacing(8)
        
        list_title = QLabel("已加载道具:")
        list_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        list_layout.addWidget(list_title)
        
        self.utility_list_text = QTextEdit()
        self.utility_list_text.setReadOnly(True)
        self.utility_list_text.setMinimumHeight(260)
        self.utility_list_text.hide()
        list_layout.addWidget(self.utility_list_text)

        self.empty_utility_state_widget = QWidget()
        self.empty_utility_state_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        empty_state_outer_layout = QVBoxLayout(self.empty_utility_state_widget)
        empty_state_outer_layout.setContentsMargins(0, 8, 0, 8)
        empty_state_outer_layout.setSpacing(0)
        empty_state_outer_layout.addStretch(1)

        self.empty_utility_state_frame = QFrame()
        self.empty_utility_state_frame.setObjectName("card")
        self.empty_utility_state_frame.setMaximumWidth(560)
        empty_state_layout = QVBoxLayout(self.empty_utility_state_frame)
        empty_state_layout.setContentsMargins(18, 16, 18, 16)
        empty_state_layout.setSpacing(8)

        self.empty_utility_title_label = QLabel("等待进入对局")
        self.empty_utility_title_label.setObjectName("statusLabel")
        empty_state_layout.addWidget(self.empty_utility_title_label, 0, Qt.AlignHCenter)

        self.empty_utility_list_label = QLabel("未在游戏中\n进入对局后，这里会自动列出当前地图与阵营的道具。")
        self.empty_utility_list_label.setObjectName("hintLabel")
        self.empty_utility_list_label.setWordWrap(True)
        self.empty_utility_list_label.setAlignment(Qt.AlignCenter)
        empty_state_layout.addWidget(self.empty_utility_list_label)

        self.empty_utility_meta_label = QLabel("进入对局后会自动识别当前地图与阵营，这里会切换成对应道具列表。")
        self.empty_utility_meta_label.setObjectName("hintLabel")
        self.empty_utility_meta_label.setWordWrap(True)
        self.empty_utility_meta_label.setAlignment(Qt.AlignCenter)
        empty_state_layout.addWidget(self.empty_utility_meta_label)

        self.empty_utility_hint_label = QLabel("也可以先打开道具文件夹，按地图 / T / CT 目录整理素材。")
        self.empty_utility_hint_label.setObjectName("hintLabel")
        self.empty_utility_hint_label.setWordWrap(True)
        self.empty_utility_hint_label.setAlignment(Qt.AlignCenter)
        empty_state_layout.addWidget(self.empty_utility_hint_label)

        empty_state_outer_layout.addWidget(self.empty_utility_state_frame, 0, Qt.AlignHCenter)
        empty_state_outer_layout.addStretch(1)
        list_layout.addWidget(self.empty_utility_state_widget, 1)
        
        tip_frame = QFrame()
        tip_frame.setObjectName("card")
        tip_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        tip_layout = QVBoxLayout(tip_frame)
        tip_layout.setContentsMargins(14, 12, 14, 12)
        tip_layout.setSpacing(8)

        tip_title = QLabel("自动刷新")
        tip_title.setObjectName("statusLabel")
        tip_layout.addWidget(tip_title)

        tip_label = QLabel("系统会自动根据当前阵营加载对应道具，列表会周期刷新。")
        tip_label.setWordWrap(True)
        tip_label.setObjectName("hintLabel")
        tip_layout.addWidget(tip_label)
        top_row.addWidget(tip_frame, 3, Qt.AlignTop)

        layout.addLayout(top_row)
        layout.addWidget(list_frame, 1)
        
        self.tab_widget.addTab(scroll, "道具管理")
    
    def _set_hotkey(self):
        """设置快捷键"""
        if self.setting_hotkey:
            return
        
        self.setting_hotkey = True
        self.hotkey_button.setText("按下新键...")
        
        # 启动线程监听按键
        self._sync_status_strip()
        thread = threading.Thread(target=self._listen_for_hotkey, daemon=True, name="UtilityHotkeyCapture")
        thread.start()
    
    def _listen_for_hotkey(self):
        """监听新的快捷键"""
        key_captured = None
        
        def on_key_event(event):
            """键盘事件回调"""
            nonlocal key_captured
            if event.event_type == keyboard.KEY_DOWN and key_captured is None:
                key_captured = event.name
                self.logger.info(f"捕获到按键: {key_captured}")
                return False  # 停止监听
        
        capture_handle = None
        try:
            self.logger.info("等待按键输入... 请按任意键")

            # 使用hook监听按键（更可靠）
            capture_handle = keyboard.hook(on_key_event, suppress=False)

            # 等待捕获按键（最多等待30秒）
            import time
            start_time = time.time()
            while key_captured is None and (time.time() - start_time) < 30:
                time.sleep(0.1)

            # P2.1 修复：原来这里调用 keyboard.unhook_all()，会把放大镜/音板/
            # 瞄点引导键等**全系统钩子全部清掉**——改一次快捷键，别的功能热键
            # 就全失效。现在只摘自己这一个捕获钩子。
            if capture_handle is not None:
                keyboard.unhook(capture_handle)
                capture_handle = None
            
            if key_captured is None:
                self.logger.warning("未捕获到任何按键（超时）")
                self.hotkey_set.emit("")  # 让主线程恢复按钮文案
                return

            # 本线程只负责捕获；配置写入/Toast/按钮更新/监听重启统统属于
            # 主线程的事，经 hotkey_set 信号（queued）转交，避免跨线程碰 Qt
            self.hotkey_set.emit(key_captured)
            self.logger.info(f"道具瞄点快捷键捕获: {key_captured}")
        except Exception as e:
            self.logger.error(f"监听快捷键失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
        finally:
            # 确保摘除自己的捕获钩子（绝不能 unhook_all——会误杀其他功能的全局热键）
            if capture_handle is not None:
                try:
                    keyboard.unhook(capture_handle)
                except Exception:
                    pass
            self.setting_hotkey = False
    
    def _reinit_hotkey_listener(self):
        """重新初始化快捷键监听"""
        if self.gsi_handler:
            try:
                self.gsi_handler.reinit_hotkey_listener()
                self.logger.info("快捷键监听已更新")
            except Exception as e:
                self.logger.error(f"更新快捷键监听失败: {e}")
    
    def _on_hotkey_set(self, key_name):
        """快捷键捕获完成回调（主线程）：落配置、更新UI、重启监听"""
        if not key_name:
            # 捕获超时：恢复按钮文案
            self.hotkey_button.setText(config.utility_guide_hotkey or "设置快捷键")
            return

        conflict = config.check_hotkey_conflict(key_name, "道具瞄点")
        if conflict:
            from ui_toast import toast_warning
            toast_warning(f"快捷键 {key_name} 已被「{conflict}」使用", 4000)

        config.utility_guide_hotkey = key_name
        config.save_config()
        self.hotkey_button.setText(key_name)

        if self.gsi_handler:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._reinit_hotkey_listener)

        self.logger.info(f"道具瞄点快捷键设置为: {key_name}")
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "设置成功",
            f"快捷键已设置为: {key_name}\n\n在游戏中按下该键即可显示道具瞄点菜单。"
        )
        self.logger.info(f"快捷键设置成功并显示确认消息: {key_name}")
    
        self._sync_status_strip()

    def _update_mode(self):
        """更新显示模式"""
        mode = "hold" if self.hold_radio.isChecked() else "toggle"
        config.utility_guide_mode = mode
        config.save_config()
        
        # 重新初始化快捷键监听
        if self.gsi_handler:
            self._reinit_hotkey_listener()
        
        self._sync_status_strip()
        
        self.logger.info(f"显示模式: {mode}")
    
    def _update_opacity(self, value):
        """更新透明度"""
        opacity = value / 100.0
        config.utility_guide_opacity = opacity
        config.save_config()
        self.opacity_label.setText(f"{value}%")
        
        # 实时更新显示
        if self.utility_display:
            self.utility_display.update_settings(
                config.utility_guide_scale,
                config.utility_guide_opacity,
                config.utility_guide_position_x,
                config.utility_guide_position_y
            )
    
    def _update_scale(self, value):
        """更新缩放"""
        scale = value / 100.0
        config.utility_guide_scale = scale
        config.save_config()
        self.scale_label.setText(f"{value}%")
        
        # 实时更新显示
        if self.utility_display:
            self.utility_display.update_settings(
                config.utility_guide_scale,
                config.utility_guide_opacity,
                config.utility_guide_position_x,
                config.utility_guide_position_y
            )
    
    def _update_position(self):
        """更新位置"""
        try:
            x = int(self.x_offset_edit.text()) if self.x_offset_edit.text() else 0
            y = int(self.y_offset_edit.text()) if self.y_offset_edit.text() else 0
            
            config.utility_guide_position_x = x
            config.utility_guide_position_y = y
            config.save_config()
            
            # 实时更新显示
            if self.utility_display:
                self.utility_display.update_settings(
                    config.utility_guide_scale,
                    config.utility_guide_opacity,
                    config.utility_guide_position_x,
                    config.utility_guide_position_y
                )
        except ValueError:
            pass
    
    def _update_menu_opacity(self, value):
        """更新菜单透明度"""
        opacity = value / 100.0
        config.utility_guide_menu_opacity = opacity
        config.save_config()
        self.menu_opacity_label.setText(f"{value}%")
    
    def _update_duration(self):
        """更新显示时长"""
        try:
            duration = int(self.duration_edit.text()) if self.duration_edit.text() else 10
            config.utility_guide_display_duration = duration
            config.save_config()
        except ValueError:
            pass
    
    def _preview_display(self):
        """预览显示效果"""
        if not self.utility_display:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", "道具显示系统未初始化")
            return
        
        # 创建示例图片路径
        example_dir = ResourceManager.get_app_data_path("resources/utility_guides/example")
        os.makedirs(example_dir, exist_ok=True)
        
        stand_path = os.path.join(example_dir, "示例_站位.jpg")
        aim_path = os.path.join(example_dir, "示例_瞄准.jpg")
        
        if not os.path.exists(stand_path) or not os.path.exists(aim_path):
            # 创建简单的示例图片
            import pygame
            pygame.init()
            
            stand_surface = pygame.Surface((350, 250))
            stand_surface.fill((100, 100, 200))
            font = pygame.font.Font(None, 48)
            text = font.render("Stand Here", True, (255, 255, 255))
            text_rect = text.get_rect(center=(175, 125))
            stand_surface.blit(text, text_rect)
            pygame.image.save(stand_surface, stand_path)
            
            aim_surface = pygame.Surface((350, 250))
            aim_surface.fill((200, 100, 100))
            text = font.render("Aim Here", True, (255, 255, 255))
            text_rect = text.get_rect(center=(175, 125))
            aim_surface.blit(text, text_rect)
            pygame.image.save(aim_surface, aim_path)
            
            pygame.quit()
        
        # 显示示例图片
        self.utility_display._send_command(("show_images", stand_path, aim_path))
        
        # 3秒后自动隐藏
        from PySide6.QtCore import QTimer
        QTimer.singleShot(3000, lambda: self.utility_display.hide())
    
    def _open_utility_folder(self):
        """打开道具文件夹"""
        folder_path = ResourceManager.get_app_data_path("resources/utility_guides")
        os.makedirs(folder_path, exist_ok=True)
        
        if os.name == 'nt':
            os.startfile(folder_path)
        elif os.name == 'posix':
            subprocess.call(['open' if sys.platform == 'darwin' else 'xdg-open', folder_path])
    
    def _open_current_map_folder(self):
        """打开当前地图文件夹"""
        if self.current_map:
            folder_path = ResourceManager.get_app_data_path(f"resources/utility_guides/{self.current_map}")
            if not os.path.exists(folder_path):
                os.makedirs(folder_path, exist_ok=True)
                os.makedirs(os.path.join(folder_path, "T"), exist_ok=True)
                os.makedirs(os.path.join(folder_path, "CT"), exist_ok=True)
            
            if os.name == 'nt':
                os.startfile(folder_path)
            elif os.name == 'posix':
                subprocess.call(['open' if sys.platform == 'darwin' else 'xdg-open', folder_path])
    
    def _open_current_team_folder(self):
        """打开当前阵营文件夹"""
        if self.current_map and self.current_team:
            folder_path = ResourceManager.get_app_data_path(
                f"resources/utility_guides/{self.current_map}/{self.current_team}"
            )
            if not os.path.exists(folder_path):
                os.makedirs(folder_path, exist_ok=True)
            
            if os.name == 'nt':
                os.startfile(folder_path)
            elif os.name == 'posix':
                subprocess.call(['open' if sys.platform == 'darwin' else 'xdg-open', folder_path])
    
    def _refresh_utilities(self):
        """刷新道具列表"""
        if self.utility_display and self.current_map:
            self.utility_display.load_map_utilities(self.current_map, self.current_team)
            self.update_utility_list()
    
    def _load_settings(self):
        """加载设置"""
        # 模式
        if config.utility_guide_mode == "hold":
            self.hold_radio.setChecked(True)
        else:
            self.toggle_radio.setChecked(True)
        
        # 快捷键
        self.hotkey_button.setText(config.utility_guide_hotkey)
        self._sync_status_strip()
    
    def set_utility_display(self, display):
        """设置道具显示控制器"""
        self.utility_display = display
        self._sync_status_strip()
        self.logger.info("已设置道具显示控制器")
    
    def set_gsi_handler(self, handler):
        """设置GSI处理器引用"""
        self.gsi_handler = handler
        self.logger.info("已设置GSI处理器")
    
    def on_map_changed(self, map_name, team=None):
        """地图变化回调（GSI处理器调用）"""
        self.update_map_info(map_name, team)
    
    def update_map_info(self, map_name, team=None):
        """更新地图和阵营信息（线程安全）"""
        # 通过信号在主线程执行，避免线程安全问题
        self._request_map_info_update.emit(map_name or "", team or "")
    
    def _do_update_map_info(self, map_name, team):
        """实际执行地图信息更新（主线程）"""
        self.current_map = map_name if map_name else None
        self.current_team = team if team else None
        
        # 更新显示
        if map_name:
            from gsi_handler_utility import GSIHandlerUtility
            display_name = GSIHandlerUtility.CS2_MAPS.get(map_name, map_name)
            self.current_map_label.setText(display_name)
            self.open_map_folder_btn.setEnabled(True)
        else:
            self.current_map_label.setText("未检测到")
            self.open_map_folder_btn.setEnabled(False)
        
        if team:
            self.current_team_label.setText(team)
            self.open_team_folder_btn.setEnabled(True)
        else:
            self.current_team_label.setText("未检测到")
            self.open_team_folder_btn.setEnabled(False)
        
        # 刷新道具列表
        if self.utility_display:
            if map_name:
                self.utility_display.load_map_utilities(map_name, team)
            else:
                self.utility_display.utility_data.clear()
            self._do_update_utility_list()
        
        self._sync_status_strip()
        self.map_info_updated.emit(map_name or "", team or "")
    
    def update_utility_list(self):
        """更新道具列表显示（线程安全）"""
        # 通过信号在主线程执行，避免线程安全问题
        self._request_utility_list_update.emit()
    
    def _do_update_utility_list(self):
        """实际执行道具列表更新（主线程）"""
        if not self.utility_display:
            self._sync_status_strip()
            return
        
        self.utility_list_text.clear()
        self.utility_list_text.show()
        self.empty_utility_state_widget.hide()
        empty_text = ""
        
        if not self.current_map:
            empty_text = "未在游戏中\n进入对局后，这里会自动列出当前地图与阵营的道具。"
        elif self.utility_display.utility_data:
            if self.current_team:
                self.utility_list_text.append(f"当前阵营: {self.current_team}\n")
            
            for location, utilities in self.utility_display.utility_data.items():
                self.utility_list_text.append(f"▶ {location}")
                for utility in utilities:
                    self.utility_list_text.append(f"  • {utility}")
                self.utility_list_text.append("")
        else:
            if self.current_team:
                empty_text = f"当前阵营 {self.current_team} 暂无道具\n请在对应阵营文件夹下添加道具图片。"
            else:
                empty_text = "当前地图暂无道具\n请在对应阵营文件夹下添加道具图片。"

        if empty_text:
            self.utility_list_text.hide()
            self._update_empty_utility_state(empty_text)
            self.empty_utility_state_widget.show()

        self._sync_status_strip()

    def deleteLater(self):
        """清理：注销主题回调"""
        from theme_manager import get_theme_manager
        get_theme_manager().unregister_theme_changed_callback(self._apply_theme_styles)
        super().deleteLater()
