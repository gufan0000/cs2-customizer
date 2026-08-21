# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""音效页共用脚手架（UP-057）。

**范围是量出来的，不是照计划书抄的。** 05 计划写「四个音效页 90% 雷同」，
实测（`ast` + `difflib` 逐方法比对）纠正为：

    kill_sound ↔ kill_voice        方法名重合 93%，同名方法正文相似 99%
    switch_weapon ↔ reload_sound   78% / 96%
    kill_sound ↔ switch_weapon     52% / 91%
    gun_sound ↔ 其余各页            19~34% / 45~64%   ← **不在这个簇里**

所以基类只服务 kill_sound / kill_voice / switch_weapon / reload_sound 四页；
`gun_sound`（方法体 586 行，最大的一个）强行并进来只会把异类塞进基类。
`death_sound` / `special_sound` 结构也不同，同样不并。

**第一阶段（R8c）只收与风格模型无关的那部分**：进页自动重扫、拖入导入、
打开资源目录、文案压缩、打开新建风格对话框。当时的判断是"四页的风格模型不统一，
凡是碰风格目录的方法都不能无脑上提"。

**第二阶段（R9-D）把这个前提收窄了。** 重新逐行 diff 之后发现：
「风格模型不统一」是真的，但它只体现在**四个取值点**上，不是结构性的分歧——

    _init_ui               kill_sound vs kill_voice：75 行里 72 行完全相同
                           kill_sound vs switch_weapon：75 行里 64 行相同
    _create_category_tab   kill_sound vs kill_voice：54 行里 48 行相同

差异收敛成：风格来源（`audio_manager.<cat>_styles` ↔ 本地 per-weapon 字典）、
配置字典名、选项拼装方式、试听回调名。四个钩子方法就能吃掉，
**不需要先把数据模型统一**。所以这一阶段把 `_init_ui` 与 `_create_category_tab`
也上提了，子类只覆盖钩子。

⚠ 顺带记一笔方法论：我一开始用"抹掉标识符后的 AST 结构相似度"来判断能不能抽，
`_init_ui` 只得 59%，差点据此判定"结构本就不同、抽不动"。**那个指标不可信**
（它把 `ast.walk` 的节点类型序列拿去比，对顺序极其敏感）。原始 diff 才是真相，
一看就是 72/75 行相同。度量工具本身也会骗人。
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import get_app_data_dir
from core.audio.audio_file_utils import DEFAULT_AUDIO_EXTENSIONS


#: 空库时主按钮的兜底文案（子类没写 `EMPTY_PRIMARY_TEXT` 时用）。
DEFAULT_EMPTY_PRIMARY_TEXT = "去社区拿一套"
#: 空库时底栏那句话。⭐ 第一件事是**承认软件本来就不带素材** ——
#: 不说的话用户会以为是自己装坏了（RN-145 的原话）。
EMPTY_LIBRARY_MESSAGE = (
    "还没有任何可用风格 —— 本软件不带素材。三步：去社区拿一个包 → "
    "「打开音频资源」把音频放进去 → 点「刷新风格列表」。"
)


class SoundPageBase:
    """音效页共用行为。

    这是个 **mixin**，不继承 QWidget —— 四个页面都是 `class XxxPage(QWidget)`，
    让 mixin 站在 QWidget 前面即可（`class XxxPage(SoundPageBase, QWidget)`），
    避免多继承时的 metaclass 纠缠。

    子类需要提供：
      · `SOUND_CATEGORY`  —— 传给 `StyleCreatorDialog` 的类别串
      · `WEAPON_NAMES`    —— 武器名映射（各页已有）
      · `audio_manager` / `logger` —— 各页 `__init__` 里已有
      · `_refresh_style_catalog()` / `_on_style_created()` —— 各页自己的实现
    """

    #: 传给 StyleCreatorDialog 的类别串，子类必须覆盖
    SOUND_CATEGORY: str = ""

    #: 进页自动重扫的冷却秒数。原本四页各写一份 10.0，行为完全一致。
    AUTO_REFRESH_COOLDOWN: float = 10.0

    # ------------------------------------------------ 页面骨架的参数（R9-D）
    #: 页头标题与副标题
    PAGE_TITLE: str = ""
    PAGE_LEAD: str = ""
    #: `PAGE_HELP_TEXTS` 的键；默认与 SOUND_CATEGORY 同名
    HELP_KEY: str = ""
    #: 试听是否支持连杀档位。只有击杀音效有（`[1, 2, 3, 4, 5]`），其余页为 None。
    TEST_LEVELS: list[int] | None = None
    #: 底部动作条的「风格工具」形态：
    #: True  = 下拉菜单（新建 / 管理），kill_sound / kill_voice
    #: False = 单个「新建风格」按钮，switch_weapon / reload_sound
    STYLE_TOOLS_MENU: bool = False
    #: 这一页的总开关在 config 里叫什么、在界面上叫什么（RN-144 升级版）。
    #: 给状态卡上那一行「总开关」用；**留空就不建那一行**。
    #:
    #: ⚠ 第一版只有 `reload_sound` 填了 —— 那时的裁定只覆盖三页，
    #: 另外三个音效页挂在 RN-147 等自己那一轮。本轮（RN-144 升级为就地开关）
    #: 把 RN-147 一起收了：**既然要把跳转换成开关，就没有理由让另外三页
    #: 先补一颗马上要拆掉的跳转按钮** —— 那是一次注定要返工的改动。
    #: ⭐ 改动范围要和裁定范围对得上；范围变了就把范围写下来，别让钩子空着装诚实。
    MASTER_SWITCH_KEY: str = ""
    MASTER_SWITCH_NAME: str = ""

    #: 这一页在社区站的资源分类键（`widgets/community_library`）。RN-153。
    #: **留空就不做空库引导** —— 四个音效页各填自己的。
    COMMUNITY_CATEGORY_KEY: str = ""
    #: 空库时那颗主按钮的文案。用页面自己的名字，别写"素材"这种谁都看不懂的词。
    EMPTY_PRIMARY_TEXT: str = ""

    def _library_is_empty(self) -> bool:
        """**一把枪都没有可用风格** —— 这才叫空库。

        ⚠ 不是"没配"（那是 `_configured_weapon_count`，是用户的选择），
        是"根本没得配"。两者的修法完全相反：没配 ⇒ 去配；没得配 ⇒ 先去拿素材。
        """
        return not any(self._weapon_styles(weapon)
                       for weapon in self._get_all_weapons())

    def _sync_community_guidance(self) -> None:
        """空库时把底栏主按钮换成「去社区拿一套」（RN-153）。

        ⭐ **"打开一个空文件夹"不是一条路。** 全新安装时底栏最抢眼的那颗按钮
        是「打开音频资源」，点开是个空目录 —— 用户手上没有文件，
        那儿什么也解决不了。外审原话：「冷启动门槛极高」「操作路径极其割裂」。

        与 RN-145（击杀图标）同一条裁定：**不内置素材，就把"没得挑"
        变成一条走得通的路**。

        ⚠ 没有社区站时（开源版）**退回原来那颗按钮** ——
        一颗指向空地址的按钮比没有按钮更糟。
        """
        bar = getattr(self, "action_bar", None)
        if bar is None or not self.COMMUNITY_CATEGORY_KEY:
            return

        from widgets import community_library

        empty = self._library_is_empty()
        reachable = community_library.has_category(self.COMMUNITY_CATEGORY_KEY)
        if empty and reachable:
            bar.configure_primary(
                self.EMPTY_PRIMARY_TEXT or DEFAULT_EMPTY_PRIMARY_TEXT,
                self._open_community_library, visible=True)
            # ⚠ **第一版把「打开音频资源」整个换掉了，那是把链路砍断了一半。**
            # 外审当场两发独立点破：「文案提示『放进资源目录』却没有打开目录的入口，
            # 从社区下载后卡在找路径环节」。
            # ⭐ 我修好了第一步（去哪儿拿），却顺手删掉了第二步（放哪儿去）——
            # **一条三步的路，只把第一步做顺是走不通的。**
            # ⇒ 空库态的三颗按钮就是那三步：拿 → 放 → 刷新。
            #   「新建风格」在没有素材时本来就没用，把位置让出来。
            bar.extra_btn.setMenu(None)
            bar.configure_extra("打开音频资源", self._open_audio_resource_root,
                                visible=True)
            bar.set_message(EMPTY_LIBRARY_MESSAGE)
        else:
            bar.configure_primary("打开音频资源", self._open_audio_resource_root,
                                  visible=True)
            text, callback, menu = getattr(
                self, "_extra_default", ("新建风格", None, None))
            bar.configure_extra(text, callback, visible=True)
            bar.extra_btn.setMenu(menu)

    def _open_community_library(self) -> None:
        from widgets import community_library

        community_library.open_category(self.COMMUNITY_CATEGORY_KEY)

    def on_master_switch_synced(self):
        """总开关被别处拨动后，把状态徽章重算一遍。

        ⭐ 全仓统一的钩子名（`widgets/master_switch_link` 调它）。
        少了这一下，开关动了而「开关 · 未启用」不动 —— 同屏两处说法
        不一致，RN-107 族。放在基类：四页共用一个骨架，别各写一份。
        """
        refresh = getattr(self, "_refresh_status_badge", None)
        if callable(refresh):
            refresh()

    # ---------------------------------------------------------------- 钩子
    # 这四个就是「风格模型不统一」的全部落点。除此之外两个大方法逐行相同。

    def _weapon_styles(self, weapon: str) -> list[str]:
        """这把武器有哪些可选风格。

        kill_sound / kill_voice 取全局的 `audio_manager.weapon_<cat>_styles`，
        switch_weapon / reload_sound 取本地扫描出来的 per-weapon 字典。
        """
        raise NotImplementedError

    def _configured_style(self, weapon: str) -> str:
        """这把武器当前配的是哪个风格（配置里的原始值，未做显示转换）。"""
        raise NotImplementedError

    def _style_options_for(self, weapon: str) -> list[str]:
        """下拉框要给出的完整选项列表。

        kill_* 与 switch_weapon 是「通用选项 + 该武器专属风格（去重）」，
        reload_sound 是「不启用 + 该武器专属风格」——两种拼法都保留原样。
        """
        raise NotImplementedError

    def _test_weapon(self, weapon: str, level=None) -> None:
        """试听。各页的实现名字不同（`_test_weapon_sound` / `_test_switch_sound` …）。"""
        raise NotImplementedError

    # -------------------------------- 「配了、但那个风格已经不在了」（RN-026 / RN-033）
    #
    # 这一族页面天生有**两个口径**：
    #   · 每一行下拉框显示的是 `_get_style_display_text()` —— 解析不出来就显示「不启用」；
    #   · 而徽章 / 分类计数 / 已配置示例数的却是**配置里的原始值**。
    # 于是风格目录一动（改名、删除、换机器、素材没跟着走），两边就永久对不上，
    # **而没有任何东西报错** —— 没异常、没日志、没判据。
    #
    # 实测四页全中（2026-08-17）：造出「3 把枪配着已删除的风格」之后
    #   kill_sound / kill_voice / switch_weapon / reload_sound
    # 顶部一律写「已配置 · 3」，而下面三行**全部显示「不启用」**。
    #
    # ⭐ 所以这里是**单一真相源**：全页只准通过 `_resolved_style(s)` 问
    # "这把枪现在到底生效什么"，统一到**用户眼睛看到的那一边**。
    # 原先 kill_sound 自己写过一份，kill_voice 压根没修 —— 上提到基类，四页共用。

    @staticmethod
    def _is_style_enabled(style_value) -> bool:
        """「这个值算配了吗」。**只认空串和 `"0"` 两种"没配"。**

        ⚠ 故意**不用** `audio_status_badge.is_style_enabled()` —— 那一份的
        `DISABLED_STYLE_VALUES` 还额外把 `none / off / disabled / 不启用 / 未启用`
        算作没配。两份规则并存本身就是缺陷（`switch_weapon` / `reload_sound`
        原先**同一页里两个口径各用一份**：`selected_count` 走宽的，
        `_configured_count_for_weapons` 走窄的），但这里取窄的那一份，
        因为 `kill_sound` / `kill_voice` 两页**已关档、已锁基线**，
        换成宽的会改动它们的既有行为 —— 那就不是等价重构了。
        """
        return str(style_value or "").strip() not in {"", "0"}

    def _get_all_weapons(self) -> list[str]:
        weapons: list[str] = []
        for category_weapons in self.CATEGORIES.values():
            weapons.extend(category_weapons)
        return weapons

    def _resolved_style(self, weapon: str) -> str:
        """这把枪**当前真正生效**的风格；配了但风格已经不在了就返回 `"0"`。"""
        display = self._get_style_display_text(self._configured_style(weapon), weapon)
        return "0" if display == self.DISABLED_STYLE_TEXT else display

    def _resolved_styles(self) -> dict[str, str]:
        """一次算出全部武器**当前真正生效**的风格。

        ⚠ 存在的理由是**实测**：三个统计口径各自逐把调 `_resolved_style()`，
        39 把枪就是 117 次解析，同机紧邻 A/B 量出建页 39.1 → 41.3ms（+5.6%）。
        没超 10% 的线，但方向不对 —— 那一轮本来是在**删**重复工作。
        算一次传下去就回到 39 次。
        """
        return {weapon: self._resolved_style(weapon) for weapon in self._get_all_weapons()}

    def _configured_weapon_count(self, weapons: list[str] | None = None,
                                 resolved: dict[str, str] | None = None) -> int:
        target_weapons = weapons if weapons is not None else self._get_all_weapons()
        if resolved is None:
            return sum(1 for weapon in target_weapons
                       if self._is_style_enabled(self._resolved_style(weapon)))
        return sum(1 for weapon in target_weapons
                   if self._is_style_enabled(resolved.get(weapon, "0")))

    def _stale_weapon_count(self, resolved: dict[str, str] | None = None) -> int:
        """配了、但那个风格已经不在了的武器数。

        这个数以前是**隐形**的：它被算进「已配置」里，用户只看到一个对不上的数字，
        看不到"有 N 项失效了"这件事本身 —— 而它恰恰是唯一可行动的信息（重新选风格）。
        """
        if resolved is None:
            resolved = self._resolved_styles()
        return sum(
            1 for weapon in self._get_all_weapons()
            if self._is_style_enabled(self._configured_style(weapon))
            and not self._is_style_enabled(resolved.get(weapon, "0"))
        )

    def _configured_weapon_names(self, max_items: int = 4,
                                 resolved: dict[str, str] | None = None) -> list[str]:
        names: list[str] = []
        for weapon in self._get_all_weapons():
            style = (resolved.get(weapon, "0") if resolved is not None
                     else self._resolved_style(weapon))
            if self._is_style_enabled(style):
                names.append(self.WEAPON_NAMES.get(weapon, weapon))
            if len(names) >= max_items:
                break
        return names

    def _configured_badge(self, selected_count: int, stale_count: int) -> tuple[str, str]:
        """「已配置」那颗徽章。失效项要**说出来**，但文案必须短到能单行放下。

        ⚠ 第一版写的是「已配置 · 0 · 37 项配置已失效」，芯片当场**换行**、
        比同排另外四颗高一截，整排肉眼可见地错位 —— 而排版审计当时的三条判据
        一条都没看见（换行既不溢出也不截断）。那次之后才加了第 4 条"同排芯片齐平"。
        """
        if stale_count:
            return "warn", f"已配置 · {selected_count} · {stale_count} 项失效"
        return ("success" if selected_count else "info", f"已配置 · {selected_count}")

    def _stale_style_hint(self, stale_count: int) -> str:
        """失效项的「怎么修」。**必须落在可见的控件上。**

        ⚠ RN-009：`summary_label` 建出来就 `hide()`，全仓没有任何地方再显示它。
        kill_sound 那轮我把这句话写进过它，等于没写 —— 外审复跑一句
        「醒目报错却无修复引导，易让玩家误判为软件损坏」直接点破。
        """
        if not stale_count:
            return ""
        return (f"有 {stale_count} 把枪配的风格已经不在了（被改名或删除），"
                "下面显示成「不启用」，重新选一个即可。")

    # ---------------------------------------------------------------- 文案

    @staticmethod
    def _compact_text(text, fallback="未分组", max_length=8):
        """把过长文案压成带省略号的短串。

        ⚠ 合并时核对过全部调用点：四页各调一次，**实际参数完全一致**
        （都是 `('未分组', 8)`），只是 kill_sound/kill_voice 显式传参、
        switch_weapon/reload_sound 靠默认值。所以默认值取后者的那套，
        四页行为逐字节不变。原先 kill_sound 那份默认 `('未设置', 12)`
        从来没有被任何调用点用到。
        """
        value = str(text or "").strip() or fallback
        if len(value) > max_length:
            return value[: max_length - 1] + "…"
        return value

    # ---------------------------------------------------------------- 资源

    @staticmethod
    def _open_audio_resource_root():
        audio_root = get_app_data_dir(os.path.join("resources", "audio"))
        QDesktopServices.openUrl(QUrl.fromLocalFile(audio_root))

    # ---------------------------------------------------------------- 导入

    def _on_audio_files_dropped(self, paths):
        """UP-038: 拖入音频 → 直接打开「新建风格」对话框并预填。"""
        files = [p for p in (paths or []) if str(p).lower().endswith(DEFAULT_AUDIO_EXTENSIONS)]
        if not files:
            return
        self._open_style_creator(initial_files=files)

    def _style_creator_extra_kwargs(self) -> dict:
        """给 `StyleCreatorDialog` 补的额外参数，默认没有。

        存在的唯一原因：`reload_sound` 会多传一个 `preselect_weapon`
        （取当前页签的第一把武器）。为这一个差异保留一个钩子，
        比让四页各留一份完整的 `_open_style_creator` 划算。
        """
        return {}

    def _open_style_creator(self, initial_files=None):
        """v2.2.1: 一步式新建风格——拖入任意命名文件，自动改名落盘并刷新。"""
        from dialogs.style_creator_dialog import StyleCreatorDialog

        dialog = StyleCreatorDialog(
            self.SOUND_CATEGORY,
            self,
            weapons=self.WEAPON_NAMES,
            audio_manager=self.audio_manager,
            initial_files=initial_files,
            **self._style_creator_extra_kwargs(),
        )
        dialog.style_created.connect(self._on_style_created)
        dialog.exec()

    # ---------------------------------------------------------- 页面骨架

    def _build_sound_page_ui(self) -> None:
        """四个武器音效页的 `_init_ui` 正文（R9-D 上提）。

        页面结构：页头 → 当前状态卡 → 分类页签 → 底部动作条。
        原来四份实现里 75 行有 64~72 行逐字相同，剩下的差异都由类属性表达。
        """
        from pages.audio_status_badge import create_badge_label
        from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
        from widgets.page_action_bar import PageActionBar
        from widgets.page_header import PageHeader

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = PageHeader(
            self.PAGE_TITLE,
            description=self.PAGE_LEAD,
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(
            header.title_row, header.body,
            PAGE_HELP_TEXTS[self.HELP_KEY or self.SOUND_CATEGORY],
        )

        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(14, 12, 14, 12)
        status_card_layout.setSpacing(8)

        if self.MASTER_SWITCH_KEY:
            # RN-144 升级版（第二稿）：**总开关独占卡片第一行、贴左边**。
            # 第一稿把它塞在状态行右端，外审 84 发里 12 发说"藏在角落"、
            # 15 发说"配完极易漏开"——七页全中。⭐ 左上角是这张卡的第一个扫视落点。
            from widgets.master_switch_link import make_master_switch_row

            self.master_switch_row = make_master_switch_row(
                self, self.MASTER_SWITCH_KEY,
                self.MASTER_SWITCH_NAME or self.PAGE_TITLE)
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

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        status_card_layout.addWidget(self.summary_label)

        self.category_overview_title_label = QLabel("")
        self.category_overview_title_label.setObjectName("statusLabel")
        status_card_layout.addWidget(self.category_overview_title_label)

        self.category_overview_meta_label = QLabel("")
        self.category_overview_meta_label.setObjectName("hintLabel")
        self.category_overview_meta_label.setWordWrap(True)
        status_card_layout.addWidget(self.category_overview_meta_label)

        self.category_overview_hint_label = QLabel("")
        self.category_overview_hint_label.setObjectName("hintLabel")
        self.category_overview_hint_label.setWordWrap(True)
        status_card_layout.addWidget(self.category_overview_hint_label)
        layout.addWidget(self.status_card)

        self.tab_widget = QTabWidget()
        # 先 addTab 再 connect：加首个 tab 会触发 currentChanged，
        # 此刻 action_bar 尚未创建，回调只靠 hasattr 守卫幸免
        for category, weapons in self.CATEGORIES.items():
            self.tab_widget.addTab(self._create_category_tab(weapons), category)
        self.tab_widget.currentChanged.connect(self._refresh_status_badge)
        layout.addWidget(self.tab_widget, 1)

        self.action_bar = PageActionBar(self)
        if self.STYLE_TOOLS_MENU:
            # v2.2.1: 风格工具菜单（新建/管理）
            from PySide6.QtWidgets import QMenu

            style_menu = QMenu(self)
            style_menu.addAction("新建风格…", self._open_style_creator)
            style_menu.addAction("管理风格（重命名/删除）…", self._open_style_manager)
            self.action_bar.configure_extra("风格工具", None, visible=True)
            self.action_bar.extra_btn.setMenu(style_menu)
        else:
            self.action_bar.configure_extra("新建风格", self._open_style_creator, visible=True)
        # RN-153：记下「风格工具/新建风格」的原样 —— 空库态要把这个位置
        # 借给「打开音频资源」，恢复时得原样放回去。
        self._extra_default = (self.action_bar.extra_btn.text(),
                               self.action_bar._extra_callback,
                               self.action_bar.extra_btn.menu())
        self.action_bar.configure_secondary("刷新风格列表", self._refresh_style_catalog, visible=True)
        self.action_bar.configure_primary("打开音频资源", self._open_audio_resource_root, visible=True)
        self.action_bar.extra_btn.setMinimumWidth(120)
        self.action_bar.secondary_btn.setMinimumWidth(148)
        self.action_bar.primary_btn.setMinimumWidth(148)
        layout.addWidget(self.action_bar, 0)

    def _create_category_tab(self, weapons: list[str]) -> QWidget:
        """一个分类页签：滚动区 → 卡片 → 响应式武器网格（R9-D 上提）。"""
        from widgets.responsive_grid import ResponsiveGrid
        from widgets.weapon_row_widget import WeaponRowWidget

        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_widget = QWidget()
        scroll_outer_layout = QVBoxLayout(scroll_widget)
        scroll_outer_layout.setContentsMargins(6, 6, 6, 6)
        scroll_outer_layout.setSpacing(0)

        list_frame = QFrame()
        list_frame.setObjectName("card")
        list_frame_layout = QVBoxLayout(list_frame)
        list_frame_layout.setContentsMargins(10, 10, 10, 10)
        list_frame_layout.setSpacing(6)

        # v2.2 响应式：grid 宽 >= 1500 三列、>= 1000 两列、其它单列
        # 阈值按 grid 实际宽度（已减去侧栏与边距）设计
        responsive_grid = ResponsiveGrid(
            breakpoints=[(1500, 3), (1000, 2), (0, 1)],
            spacing=6,
        )
        list_frame_layout.addWidget(responsive_grid)

        for weapon in weapons:
            all_options = self._style_options_for(weapon)
            display_style = self._get_style_display_text(self._configured_style(weapon), weapon)
            kwargs = {}
            if self.TEST_LEVELS is not None:
                kwargs["test_levels"] = self.TEST_LEVELS
            weapon_row = WeaponRowWidget(
                self.WEAPON_NAMES.get(weapon, weapon),
                weapon,
                all_options,
                display_style,
                **kwargs,
            )
            weapon_row.styleChanged.connect(
                lambda style, w=weapon: self._on_weapon_style_changed(w, style))
            weapon_row.testClicked.connect(lambda w=weapon: self._test_weapon(w))
            weapon_row.testLevelClicked.connect(
                lambda level, w=weapon: self._test_weapon(w, level))
            responsive_grid.addItem(weapon_row)
            self.weapon_rows[weapon] = weapon_row

        scroll_outer_layout.addWidget(list_frame)
        scroll_outer_layout.addStretch()
        scroll.setWidget(scroll_widget)
        tab_layout.addWidget(scroll)
        return tab

    # ---------------------------------------------------------------- 进页

    def showEvent(self, event):
        """v2.2.1: 进页自动重扫（10s 冷却）——手动放文件后不再需要手动点刷新。"""
        super().showEvent(event)

        now = time.monotonic()
        last = getattr(self, "_last_auto_refresh", 0.0)
        if now - last >= self.AUTO_REFRESH_COOLDOWN:
            self._last_auto_refresh = now
            try:
                self._refresh_style_catalog()
            except Exception:
                self.logger.exception("进页自动刷新风格列表失败")
