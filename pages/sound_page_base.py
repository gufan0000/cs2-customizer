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
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from config import get_app_data_dir
from core.audio.audio_file_utils import DEFAULT_AUDIO_EXTENSIONS
from ui_style_applier import keep_single_line
from widgets.status_strip import StatusStrip


#: 空库时主按钮的兜底文案（子类没写 `EMPTY_PRIMARY_TEXT` 时用）。
DEFAULT_EMPTY_PRIMARY_TEXT = "去社区拿一套"


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
        # RN-641：分母必须和下拉框一致。kill_sound / kill_voice 的风格有两个来源 ——
        # 全局池（`_get_style_options`）与每把枪自己的目录（`_weapon_styles`）；
        # 原来只数后者，于是用户把素材放在全局池里时，下拉框 39 把枪全有得选、
        # 横幅却写「还没有任何可用风格」（用户真实配置实测：全局 5 / per-weapon 0）。
        disabled = getattr(self, "DISABLED_STYLE_TEXT", "不启用")
        return not any(option != disabled
                       for weapon in self._get_all_weapons()
                       for option in self._style_options_for(weapon))

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

        # RN-179：先把「没得选」的下拉框和它那一行的试听按钮置灰。
        # ⚠ 这一步**不能放在下面那个 `if applied: return` 之后** ——
        # 那条 return 只表示"底栏换成了社区引导"，而没有社区站的发行版（开源版）
        # 走的是另一条分支，控件照样是死的。**置灰与有没有社区站无关。**
        community_library.dim_controls_with_nothing_to_pick(
            self, reason=community_library.dim_reason("风格"))

        # ⭐ **空库时该长什么样，全仓只有一份**（`community_library`）——
        # 八个页面「库空不空」各问各的（数据结构完全不同），
        # 但"空了给什么"必须同一份，否则八页会长出八个略有差别的空状态。
        applied = community_library.guide_empty_library(
            bar,
            empty=self._library_is_empty(),
            category_key=self.COMMUNITY_CATEGORY_KEY,
            cta_text=self.EMPTY_PRIMARY_TEXT or DEFAULT_EMPTY_PRIMARY_TEXT,
            keep_text="打开音频资源",
            keep_callback=self._open_audio_resource_root,
            message=community_library.empty_library_message("风格"),
            callout=getattr(self, "empty_callout", None),   # RN-180
            what="风格",
            refresh_label="刷新风格列表",
        )
        # 引导卡出来了就不铺 39 把枪：一片「不启用」只会让人以为第一步是逐把配（批 146 外审）。
        # ⚠ 没有社区站的发行版没有引导卡，武器板得留着（置灰），不然这一页什么都没有。
        self.weapon_section.setVisible(not applied)
        self.style_library.setVisible(not applied and bool(self.style_library.styles()))
        self.library_hint.setVisible(not applied)
        self._sync_library_hint()
        # 一个素材都没有时不说「当场生效」：开关开着，可游戏里什么都不会响（批 145 外审）。
        # 按库空不空判，不按引导卡出没出来：没有社区站的发行版空库时没有引导卡（批 152 开源同步）。
        self.master_switch_row.set_has_content(not self._library_is_empty())
        if applied:
            return

        # 有素材（或这个发行版没有社区站）：原样恢复。
        # ⚠ **借了要还** —— 空库态借用了 extra 那个位置放「打开音频资源」，
        # 不还回去就是一次静默的功能丢失：用户再也建不了风格，而没有任何一处报错。
        bar.configure_primary("打开音频资源", self._open_audio_resource_root,
                              visible=True)
        text, callback, menu = getattr(
            self, "_extra_default", ("新建风格", None, None))
        bar.configure_extra(text, callback, visible=True)
        bar.extra_btn.setMenu(menu)

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

    def _test_weapon(self, weapon: str, level=None, style=None) -> None:
        """试听。各页的实现名字不同（`_test_weapon_sound` / `_test_switch_sound` …）。

        `style` 给了就试听这个风格，不管这把枪现在配的是什么（风格卡上那颗按钮）。
        """
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

        ⭐⭐ RN-197（批 72）：原来只说「重新选一个即可」，默认**替代品是有的**，
        而玩家丢的往往正是他要的那一个 —— **一个只在极端状态下才给出口的引导，
        等于在所有正常状态下都没有出口**。出口的形状（零高度的链接，不是按钮）
        与理由见 `community_library.stale_style_route`。
        """
        from widgets import community_library

        if not stale_count:
            return ""
        text = (f"有 {stale_count} 把枪配的风格已经不在了（被改名或删除），"
                "下面显示成「不启用」，重新选一个即可。")
        return text + community_library.stale_style_route(
            self.COMMUNITY_CATEGORY_KEY, what="风格")

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

        存在的唯一原因：`reload_sound` 会多传一个 `preselect_weapon`。
        为这一个差异保留一个钩子，比让四页各留一份完整的 `_open_style_creator` 划算。
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
        """四个武器音效页的 `_init_ui` 正文（R9-D 上提，批 146 改版）。

        页面结构：页头 → 有事才出现的状态条 → 一个滚动区（风格库 → 武器板）。
        滚动区只有这一个，不嵌套：1280×800 下 39 把枪一屏看完，分类页签不需要了。
        """
        from pages.audio_status_badge import create_badge_label
        from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
        from widgets.page_header import PageHeader
        from widgets.weapon_board import BoardScrollArea

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

        self.status_card = StatusStrip()
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(0, 0, 0, 0)
        status_card_layout.setSpacing(8)

        if self.MASTER_SWITCH_KEY:
            # RN-144 升级版（第二稿）：**总开关独占卡片第一行、贴左边**。
            # 第一稿把它塞在状态行右端，外审 84 发里 12 发说"藏在角落"、
            # 15 发说"配完极易漏开"——七页全中。⭐ 左上角是这张卡的第一个扫视落点。
            from widgets.master_switch_link import make_master_switch_row

            self.master_switch_row = make_master_switch_row(
                self, self.MASTER_SWITCH_KEY,
                self.MASTER_SWITCH_NAME or self.PAGE_TITLE)

        status_header = QHBoxLayout()
        status_header.setSpacing(10)
        self.status_badge_label = create_badge_label()
        status_header.addWidget(self.status_badge_label, 1)
        status_header.addStretch()
        status_card_layout.addLayout(status_header)


        self.category_overview_hint_label = QLabel("")
        self.category_overview_hint_label.setObjectName("hintLabel")
        self.category_overview_hint_label.setWordWrap(True)
        self.category_overview_hint_label.hide()
        # RN-197：失效项那句话里带一条「去社区补回来」的链接（`_stale_style_hint`）。
        # ⚠ 链接**不走系统浏览器的默认打开**（`setOpenExternalLinks` 保持 False）：
        #   地址要由 `community_library` 那一份唯一真源来拼，页面不许自己拼 URL。
        from widgets import community_library as _cl

        _cl.wire_stale_route(self.category_overview_hint_label,
                             lambda: self.COMMUNITY_CATEGORY_KEY)
        status_card_layout.addWidget(self.category_overview_hint_label)
        layout.addWidget(self.status_card)

        self.content_scroll = BoardScrollArea(self)
        content = QWidget(self.content_scroll)
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 12)
        body.setSpacing(16)

        self._build_library_section(content, body)
        self._build_weapon_section(content, body)
        body.addStretch(1)

        self.content_scroll.setWidget(content)
        self.content_scroll.availableWidthChanged.connect(self.weapon_board.set_available_width)
        layout.addWidget(self.content_scroll, 1)

        # 建完页先同步一次「整套套用」那一行
        self._sync_apply_all_row()
        self._sync_library_hint()

    def _build_library_section(self, content: QWidget, body: QVBoxLayout) -> None:
        """风格库：标题行（说明 + 操作）→ 空库引导或风格卡。"""
        from PySide6.QtWidgets import QMenu

        from widgets.community_library import EmptyLibraryCallout
        from widgets.page_action_bar import PageActionBar
        from widgets.style_library import ShrinkingHintLabel, StyleLibrary

        section = QVBoxLayout()
        section.setContentsMargins(0, 0, 0, 0)
        section.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        title = QLabel("风格库")
        title.setObjectName("cardTitle")
        head.addWidget(title)
        self.library_hint = keep_single_line(ShrinkingHintLabel(""))
        self.library_hint.setObjectName("hintLabel")
        head.addWidget(self.library_hint, 1)

        self.action_bar = PageActionBar(content, inline=True)
        if self.STYLE_TOOLS_MENU:
            # v2.2.1: 风格工具菜单（新建/管理）
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
        head.addWidget(self.action_bar)
        section.addLayout(head)

        # RN-180：空库时的第一步放在风格库这里 —— 困惑发生的位置。
        self.empty_callout = EmptyLibraryCallout(content, large=True)
        section.addWidget(self.empty_callout.frame)

        self.style_library = StyleLibrary(content, focus_after=self.action_bar.primary_btn)
        self.style_library.brushChanged.connect(self._on_brush_changed)
        self.style_library.auditionRequested.connect(self._audition_style)
        section.addWidget(self.style_library)
        body.addLayout(section)

    def _build_weapon_section(self, content: QWidget, body: QVBoxLayout) -> None:
        """武器：标题行（已配置几把 + 整套套用）→ 武器板。"""
        self.weapon_section = QWidget(content)
        section = QVBoxLayout(self.weapon_section)
        section.setContentsMargins(0, 0, 0, 0)
        section.setSpacing(8)

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
        head.addStretch(1)
        # ⭐⭐⭐ RN-181（2026-09-05 批 50）：39 把武器要逐个下拉配置，
        #   外审 35 发 / 跨 10 页票数最高。批 50 的行为题调研更直接：
        #   问「你想让全部 34 把枪都用同一个风格，会怎么做」——**30/30 答「找不到」**，
        #   而他们在找的词是「应用到全部武器」（7 次）、「全局风格」（6 次）。
        # ⇒ 就叫他们说的那个词，紧挨着它要改的那片武器。
        head.addLayout(self._build_apply_all_row())
        section.addLayout(head)

        self.weapon_board = self._build_weapon_board()
        section.addWidget(self.weapon_board)
        body.addWidget(self.weapon_section)

    def _build_apply_all_row(self):
        """「整套套用」：选一个风格 → 套到这一页的全部武器（RN-181）。"""
        from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton

        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)

        self.apply_all_combo = QComboBox()
        self.apply_all_combo.setMinimumWidth(170)
        row.addWidget(self.apply_all_combo)

        self.apply_all_btn = QPushButton("应用到全部武器")
        self.apply_all_btn.setObjectName("secondaryButton")
        self.apply_all_btn.clicked.connect(self._apply_style_to_all_weapons)
        self.apply_all_combo.currentTextChanged.connect(
            lambda _t: self._sync_apply_all_hint())
        row.addWidget(self.apply_all_btn)
        return row

    def _sync_category_hint(self, stale_count, health) -> None:
        """有事要做才说：配过的风格没了、风格目录是空的。

        还没配、配了哪几把，页面上都看得见；还没有素材，上面那条引导已经说了。
        """
        health = health or {}
        self.category_overview_hint_label.setVisible(
            bool(stale_count or health.get("invalid") or health.get("empty")))

    def _apply_all_options(self) -> list[str]:
        """下拉里给出**任意一把武器有的**风格（并集）。

        ⚠⚠ 第一版取的是**交集**，而 `switch_weapon` / `reload_sound` 的风格是
        **per-weapon** 的（`switch_weapons/<武器>/<风格>/`）—— 交集在真实配置下
        几乎必然为空。⭐ **那会让这个功能恰好在最痛的那几页上没用**，
        而 RN-181 原文点名的正是那 34 把枪。
        （逮到它的是「让判据真的跑起来」：造了风格之后，四页里三页拿不到选项。）
        ⇒ 用并集，安全性交给**套用时跳过**那一步（见 `_weapons_supporting`）。
        """
        seen = set()
        for weapon in self._get_all_weapons():
            seen |= set(self._style_options_for(weapon))
        return sorted(seen)

    def _weapons_supporting(self, style: str) -> list[str]:
        """这些武器真的有这个风格 —— 其余的**跳过，绝不写一个解析不出来的值**。"""
        return [w for w in self._get_all_weapons()
                if style in self._style_options_for(w)]

    def _sync_apply_all_row(self) -> None:
        """刷新那一行：选项、可用性、那句说明。"""
        if not hasattr(self, "apply_all_combo"):
            return
        options = [o for o in self._apply_all_options()
                   if o != self.DISABLED_STYLE_TEXT]
        keep = self.apply_all_combo.currentText()
        self.apply_all_combo.blockSignals(True)
        self.apply_all_combo.clear()
        self.apply_all_combo.addItems(options)
        if keep in options:
            self.apply_all_combo.setCurrentText(keep)
        self.apply_all_combo.blockSignals(False)

        usable = bool(options)
        self.apply_all_combo.setEnabled(usable)
        self.apply_all_btn.setEnabled(usable)
        self._sync_apply_all_hint()

    def _sync_apply_all_hint(self) -> None:
        """换了下拉里的风格，那句说明要跟着重算 —— 能用它的武器数会变。"""
        if not hasattr(self, "apply_all_btn"):
            return
        if self.apply_all_combo.count():
            n = len(self._weapons_supporting(self.apply_all_combo.currentText()))
            self.apply_all_btn.setToolTip(f"把选中的风格一次配给能用它的 {n} 把武器")
        else:
            self.apply_all_btn.setToolTip("还没有可用的风格 —— 先导入或新建一个")

    def _apply_style_to_all_weapons(self) -> None:
        """把下拉里选中的风格套给本页**能用它的**武器。

        ⚠ 这是一个**会覆盖用户已有设置**的动作（RN-506 的「破坏性」那一侧），
        所以：① 先问一句，且那句话里带**确切的数**；② 走每页既有的
        `_on_weapon_style_changed` 落盘，不在这里造第二条写配置的路。
        """
        from PySide6.QtWidgets import QMessageBox

        style = self.apply_all_combo.currentText().strip()
        weapons = self._get_all_weapons()
        if not style or not weapons:
            return

        targets = self._weapons_supporting(style)
        skipped = len(weapons) - len(targets)
        if not targets:
            QMessageBox.information(
                self, "没有武器能用这个风格",
                f"这 {len(weapons)} 把武器都没有「{style}」这个风格。")
            return

        already = sum(1 for w in targets if self._configured_style(w) == style)
        changing = len(targets) - already
        if changing == 0:
            QMessageBox.information(
                self, "无需改动",
                f"能用「{style}」的那 {len(targets)} 把武器已经全都配好了。")
            return

        # ⭐ 把「配几把、跳几把」都说出来 —— 只说「全部」会让跳过的那几把
        #   变成一个用户以为配了、其实没配的沉默差额。
        skipped_line = (f"\n另有 {skipped} 把武器没有这个风格，会保持原样。"
                        if skipped else "")
        reply = QMessageBox.question(
            self, "应用到全部武器？",
            f"会把「{style}」配给 {len(targets)} 把武器，"
            f"其中 {changing} 把的当前设置会被覆盖。{skipped_line}\n\n继续吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for weapon in targets:
            row = self.weapon_rows.get(weapon)
            if row is not None:
                row.set_current_style(style)   # 会经 styleChanged 走既有落盘
            else:
                self._on_weapon_style_changed(weapon, style)
        self._refresh_status_badge()
        self._sync_apply_all_row()

    def _build_weapon_board(self) -> QWidget:
        """全部武器一张板，按分类分组。"""
        from widgets.weapon_board import WeaponBoard
        from widgets.weapon_row_widget import WeaponRowWidget

        board = WeaponBoard(self)
        kwargs = {}
        if self.TEST_LEVELS is not None:
            kwargs["test_levels"] = self.TEST_LEVELS
        for category, weapons in self.CATEGORIES.items():
            cells = []
            for weapon in weapons:
                cell = WeaponRowWidget(
                    self.WEAPON_NAMES.get(weapon, weapon),
                    weapon,
                    self._style_options_for(weapon),
                    self._get_style_display_text(self._configured_style(weapon), weapon),
                    parent=board,
                    **kwargs,
                )
                cell.styleChanged.connect(
                    lambda style, w=weapon: self._on_weapon_style_changed(w, style))
                cell.testClicked.connect(lambda w=weapon: self._test_weapon(w))
                cell.testLevelClicked.connect(
                    lambda level, w=weapon: self._test_weapon(w, level))
                cell.nameClicked.connect(lambda w=weapon: self._on_weapon_name_clicked(w))
                self.weapon_rows[weapon] = cell
                cells.append(cell)
            board.add_group(category, cells)
        return board

    # ---------------------------------------------------------------- 风格库和武器板

    def _sync_weapon_board(self, resolved: dict[str, str] | None = None) -> None:
        """格子的样子、风格卡的小字、「已配置几把」都从这一份解析结果来。"""
        from collections import Counter

        from widgets.weapon_row_widget import STATE_CONFIGURED, STATE_STALE

        if resolved is None:
            resolved = self._resolved_styles()
        used: Counter = Counter()
        for weapon, cell in self.weapon_rows.items():
            style = resolved.get(weapon, "0")
            if self._is_style_enabled(style):
                used[style] += 1
                cell.set_cell_state(STATE_CONFIGURED)
            elif self._is_style_enabled(self._configured_style(weapon)):
                cell.set_cell_state(STATE_STALE)
            else:
                cell.set_cell_state("")
        self.style_library.set_styles([
            (style, f"用在 {used[style]} 把枪上" if used[style] else "未使用")
            for style in self._apply_all_options() if style != self.DISABLED_STYLE_TEXT
        ])
        self.weapon_count_label.setText(
            f"已配置 {sum(used.values())} / {len(self.weapon_rows)}")
        self._sync_apply_all_row()

    def _on_brush_changed(self, style: str) -> None:
        from widgets.weapon_row_widget import BRUSH_CAN, BRUSH_CANNOT

        supporting = set(self._weapons_supporting(style)) if style else set()
        for weapon, cell in self.weapon_rows.items():
            cell.set_brush_state(
                "" if not style else (BRUSH_CAN if weapon in supporting else BRUSH_CANNOT))
        # 选中的风格同时就是「应用到全部武器」要套的那个
        if style and self.apply_all_combo.findText(style) >= 0:
            self.apply_all_combo.setCurrentText(style)
        self._sync_library_hint()

    def _sync_library_hint(self) -> None:
        brush = self.style_library.brush()
        if brush:
            text = f"点枪名配上「{brush}」，再点一次取消"
        elif not self.style_library.styles():
            # 没有社区站的发行版空库时只剩这一句能说话（有社区站时引导卡顶替了它）
            text = "还没有风格：放进音频后点「刷新风格列表」"
        else:
            text = "选一个风格，再点下面的枪名"
        self.library_hint.setText(text)

    def _on_weapon_name_clicked(self, weapon: str) -> None:
        """有刷子：配给这把枪，已经是这个风格就取消。没刷子：不改任何东西。"""
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QToolTip

        cell = self.weapon_rows[weapon]
        brush = self.style_library.brush()
        if not brush:
            QToolTip.showText(QCursor.pos(), "先在风格库里选一个风格", cell)
            return
        if brush not in self._style_options_for(weapon):
            QToolTip.showText(QCursor.pos(), f"这把枪没有「{brush}」这个风格", cell)
            return
        current = cell.get_current_style()
        cell.set_current_style(self.DISABLED_STYLE_TEXT if current == brush else brush)

    def _audition_style(self, style: str) -> None:
        """试听一个风格，不用先配给谁。用第一把有这个风格的枪走各页既有的试听。"""
        weapons = self._weapons_supporting(style)
        if weapons:
            self._test_weapon(weapons[0], style=style)

    # ---------------------------------------------------------------- 进页

    def showEvent(self, event):
        """v2.2.1: 进页自动重扫（10s 冷却）——手动放文件后不再需要手动点刷新。"""
        super().showEvent(event)

        now = time.monotonic()
        last = getattr(self, "_last_auto_refresh", 0.0)
        # 批 123：刚在「导入资源」装过包 ⇒ 不看冷却（否则「导入成功、回来下拉里没有」）
        import core.resource_generation as resource_generation

        imported = resource_generation.take_news(self)
        if imported or now - last >= self.AUTO_REFRESH_COOLDOWN:
            self._last_auto_refresh = now
            try:
                self._refresh_style_catalog()
            except Exception:
                self.logger.exception("进页自动刷新风格列表失败")
        # 风格清单可能刚变过 ⇒「整套套用」的选项跟着走。
        # ⚠ 放在冷却判断**外面**：冷却挡的是重扫磁盘，不该连带把这一行冻住。
        try:
            self._sync_apply_all_row()
        except Exception:
            self.logger.exception("同步「整套套用」那一行失败")
