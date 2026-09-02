#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Preset center page (HUD + Screen Effects + Special Sounds)."""

from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.presets.preset_center import (
    TYPE_LABELS,
    apply_bundle,
    export_bundle,
    mode_affects_result,
    validate_bundle,
)
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from resource_manager import ResourceManager
from page_theme_helper import style_as_danger_button
from widgets.page_action_bar import PageActionBar
from widgets.my_presets_section import MyPresetsMixin
from widgets.settings_card import SettingsCard
from widgets.page_header import PageHeader

#: RN-429：本页两跳能够到 `ui_osd`，但那是**切预设时顺带弹的提示**，不是玩家在这一页配置的产出物。⭐ 判据问的是「这一页配的东西会不会画到游戏上」，不是「能不能够到覆盖层」。
DRAWS_OVER_THE_GAME = False


class PresetCenterPage(MyPresetsMixin, QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("PresetCenterPage")
        self._current_bundle = None
        self._init_ui()
        self._render_preview()

    @staticmethod
    def _chain_tab_order(cards):
        """按**卡片的摆放顺序**重新串一遍焦点链。

        卡**内部**的构造顺序本来就等于阅读顺序，需要重排的只有卡与卡之间；
        所以这里把各卡的可聚焦后代按卡序拼起来，再逐对 `setTabOrder`。
        """
        chain = []
        for card in cards:
            chain += [w for w in card.findChildren(QWidget)
                      if w.focusPolicy() != Qt.NoFocus and w.isVisibleTo(card)]
        for previous, following in zip(chain, chain[1:]):
            QWidget.setTabOrder(previous, following)

    @staticmethod
    def _set_compact_heights(*controls, height=34):
        for control in controls:
            if control is not None:
                control.setMinimumHeight(height)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # UP-047: 页头改用 PageHeader。字号与间距按本页原值传入——
        # 这次重构不动一个像素，四种并存的字号是另一回事（UP-092）。
        from ui_help_panel import PAGE_HELP_TEXTS, install_help_panel
        header = PageHeader(
            "预设中心",
            description="把一整套设置打包成「预设」，可一键切换或导出分享给朋友。点右上角「?」看用法。",
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["preset_center"])

        status_card, card_layout = SettingsCard.make("当前状态", spacing=10)
        self.status_card = status_card

        self.status_badge_label = create_badge_label()
        card_layout.addWidget(self.status_badge_label)

        # RN-009（批 38 清掉本页那一处）：这里原来还有一个 `summary_label` ——
        # 建出来就 `hide()`、全仓无人 `show()`，而**四条路径持续维护它的文本与 tooltip**。
        # ⭐ 它活下来的机制和 music/account 那两处一样：有人给它写了判据
        #   （`test_tool_pages_ui_polish` 里两条，其中一条还逐字规定了它的 tooltip 该写什么）。
        # 它想说的那句话现在只留在 `status_card.setToolTip()` 上 —— 那一份是**看得见的**。
        layout.addWidget(status_card)

        # ⭐⭐⭐ RN-477（批 40）：这七个勾选框原来住在「预设工作台」卡的第一列里，
        #   而它其实是**页级**的 —— 导出文件、存为新预设、按地图保存、状态卡第一颗胶囊，
        #   四处的内容都由它决定。
        # ⚠⚠ 而立案时我把它写成「跨区域逆向联动」（一个**理解**问题），**实测推翻了**：
        #   外审问「这一屏上哪些操作会受这组勾选影响」——
        #     · 窗口图（折线以下看不见）  **6/6「找不到」**
        #     · 整页无折线图              **6/6「4 个」**，且 **6/6 说「依据：图上写着」**
        #   ⇒ ⭐⭐⭐ **只要看得见，理解一点问题都没有；唯一的缺陷是它在折线以下。**
        #     （改前实测 `cb_hud` 露出 27%、第二排 `cb_magnifier` 露出 **0%**。）
        # ⇒ 修法不是重新设计信息架构，是**把它提成页级卡、搬到第一屏**。
        # ⛔ 不并进「我的预设」卡：那会让它看起来归那张卡所有 ——
        #   正是它现在被工作台"收养"之后落到的下场。
        scope_card, scope_layout = SettingsCard.make(
            "保存/导出的范围",
            "导出文件、存为预设、按地图保存，都按这里勾的来。"
            "读入别人的文件时按文件里写的来，不看这里。",
            spacing=10,
        )
        scope_column = scope_layout
        selection_row = QHBoxLayout()
        selection_row.setSpacing(8)
        self.cb_hud = QCheckBox("HUD 规则")
        self.cb_hud.setChecked(True)
        self.cb_screen = QCheckBox("屏幕特效")
        self.cb_screen.setChecked(True)
        self.cb_special = QCheckBox("特殊音效")
        self.cb_special.setChecked(True)
        selection_row.addWidget(self.cb_hud)
        selection_row.addWidget(self.cb_screen)
        selection_row.addWidget(self.cb_special)
        selection_row.addStretch()
        scope_column.addLayout(selection_row)
        # R2-1 schema v2:四个纯配置域
        selection_row2 = QHBoxLayout()
        selection_row2.setSpacing(8)
        self.cb_crosshair = QCheckBox("准心")
        self.cb_crosshair.setChecked(True)
        self.cb_flash = QCheckBox("自定闪光")
        self.cb_flash.setChecked(True)
        self.cb_viewmodel = QCheckBox("局内视角")
        self.cb_viewmodel.setChecked(False)
        self.cb_magnifier = QCheckBox("开镜放大")
        self.cb_magnifier.setChecked(False)
        for cb in (self.cb_crosshair, self.cb_flash, self.cb_viewmodel, self.cb_magnifier):
            selection_row2.addWidget(cb)
        selection_row2.addStretch()
        scope_column.addLayout(selection_row2)
        layout.addWidget(scope_card)

        # ⭐⭐⭐ RN-484（批 40 补刀）：这张卡原来是**两列** —— 左边一整列「导入策略」
        #   （标题 + 说明 + 「导入模式」下拉 + 一句随下拉变的提示），右边才是两颗按钮。
        # ⚠ 那个下拉框只有**一个**消费者、且只在**一个**瞬间被读到：
        #   `_import_config_path` 里的 `mode = self.mode_combo.currentData()`
        #   （AST 实证：全仓再无第二处；另外三条应用通路全部硬写 `mode="merge"`）。
        # ⭐⭐⭐ 批 40 主刀那条规矩在这里第三次适用：
        #   **一个机制收窄到只剩一个用例之后，下一个该问的问题是：
        #   那一个用例，是不是也可以不由它来做。**
        # ⇒ 可以，而且更好：那个选择要等**有了文件**才做得了，
        #   所以它属于确认框（那时屏幕上正摆着这份文件里有什么），不属于这一屏。
        #
        # ⚠⚠ 而端到端实测把它降级得更彻底（`H:/tmp/b40_probe3_mode.py`，
        #   造包 → 复位 config → 两种模式各跑一遍 → 逐键深比对）：
        #     **64 个键里只有 5 个**在两种模式下结果不同
        #     （`hud_rules` / `hud_keymap_enabled` / `grenade_sound_styles` /
        #       `flash_style_params` / `magnifier` —— 全是 dict 型的那几个）；
        #     **7 类里有 3 类（准心 17 键 / 屏幕特效 4 键 / 局内视角 5 键）
        #     两种模式逐字节相同** —— 而准心正是最可能被分享的那一类。
        # ⭐ RN-415 那条「改不动任何像素的就必须禁用」的同族：
        #   **一个在多数使用场景里什么都不做的选择，不该摆在所有人的必经之路上。**
        # ⇒ 只有当这份文件真的碰到那 5 个键之一时，确认框才给两颗按钮；
        #   否则连问都不问（`mode_affects_result` 算这件事）。
        #
        # ⛔ 顺带撤掉那句「合并适合保留已有配置，覆盖适合**一键替换整套体验**」——
        #   后半句是**假的**：replace 只清掉那 5 个 dict 键里你自己加的条目，
        #   文件里没有的类别一个字节都不动。
        workbench_card, workbench_layout = SettingsCard.make(
            "和朋友交换配置",
            "把你这一套存成文件发给朋友；或者打开朋友发来的文件，直接用他那一套。",
            spacing=10
        )
        workbench_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        actions_column = QVBoxLayout()
        actions_column.setSpacing(8)
        # ⚠ RN-077（批 36）：原文「导出、导入和应用**放在一起**，连续处理预设包时更顺手」
        # 讲的是版面。同 `utility` 那两条，一起被 RN-077 的 AST 通路漏掉了
        # （全站 213 条可见 hintLabel 里就这 3 条命中，3 条都是手搓卡片）。
        # ⭐⭐⭐ RN-478（批 40）：这里原来是 **2×2 四颗按钮** ——
        #   「导出预设包 / 导入预设包」（`.json`）与「导出分享文件 / 导入分享文件」（`.cs2customizer`），
        #   外加第五颗「应用读入的预设包」。
        # ⚠ 实测外审 12 发问「朋友发给你一个文件，你点哪一个？点完会发生什么」：
        #   **12/12「有把握: 没有」**，候选数窗口图 3~4 个、整页图 2 个 —— 一发都没有把握。
        # ⭐ 而这两条路的**产物是同源的**：`.cs2customizer` = zip(manifest.json + bundle.json)，
        #   里面那份 bundle 与 `.json` 导出的**逐字节同源**（都出自 `export_bundle`）。
        #   ⇒ `.cs2customizer` 是 `.json` 的**真超集**（多了标题/作者/版本 + 五条安检红线）。
        # ⭐⭐ **摆在屏幕上的不该是两种容器格式，那是实现细节；玩家要做的动作只有两个 ——
        #   「把我这一套发出去」和「打开别人给的一份」。**
        # ⇒ 两颗按钮，两种扩展名都吃，按扩展名在**幕后**分派。
        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        # ⚠⚠ RN-485（批 40 补刀）：这颗按钮上一版叫「导出成文件**，**发给朋友」——
        #   而那个全角逗号让它**整条掉出了设置搜索索引**：
        #   `build_search_index.normalize()` 撞到 `_SENTENCE`（`[，。！？；、,;]`）
        #   就判定「这是句子不是设置项」，返回空串 ⇒ 这一页唯一的导出入口
        #   在全站搜索里一条都不剩（实测索引里 `导出成文件` 命中 0 条，
        #   而配对的「打开一份配置文件」还在）。
        # ⭐⭐⭐ 而 `build_search_index.py --check` **退出码仍然是 0** ——
        #   它只校验「重新生成一遍是不是逐字节相同」，
        #   **看不见「有一条根本没进去」**。
        #   ⇒ 一道跑着的、绿着的、以它命名的门禁，结构上照不到它该防的那件事。
        # ⇒ 文案里不留标点；这件事本身另配棘轮（`test_every_action_is_findable_by_search`）。
        self.export_btn = QPushButton("导出成文件发给朋友")
        self.export_btn.setObjectName("secondaryButton")
        self.export_btn.clicked.connect(self._export_config_file)
        self.export_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        actions.addWidget(self.export_btn, 0, 0)

        self.import_btn = QPushButton("打开一份配置文件")
        self.import_btn.setObjectName("secondaryButton")
        self.import_btn.clicked.connect(self._open_config_file)
        self.import_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        actions.addWidget(self.import_btn, 0, 1)
        self._set_compact_heights(self.export_btn, self.import_btn)

        # ⛔ 第五颗「应用读入的预设包」**整颗撤掉**，而理由不是版式：
        #   它服务的是「读进来了、还没应用」这个中间态，而这一批把两条导入路
        #   统一成了「确认 → 应用」⇒ **那个中间态不再存在**。
        # ⭐⭐⭐ 批 38 把 dirty 收窄到只剩唯一一个真源（`_import_bundle_from_file`），
        #   而这一批要问的下一个问题是：**那唯一的一个用例，是不是也可以不由它来做。**
        #   答案是可以，而且更好 —— 「先看清里面是什么再决定」由**确认对话框**做，
        #   它就在按下按钮的那一刻、在屏幕正中；而旧办法把答案放进预览卡，
        #   那张卡实测露出 **0%**（批 27/38 那条第四次：答案在页面上，只是不在屏幕上）。
        # ⇒ 本页不再继承 `DirtyPageMixin`，`is_dirty` / `mark_dirty` / `can_leave_page`
        #   在这一页**结构上不存在**，而不是"约好了不去调"。
        # ⚠ 这一行上一版逐字写成「`.cs2customizer`（推荐，带说明和安检）和 `.json`」——
        #   那对反引号是 markdown，而 QLabel 是纯文本：**屏幕上真的画出了六个反引号**。
        #   ⭐ 写文案时脑子里在写 markdown，落到屏幕上就成了乱码 —— 这一页没有渲染器。
        actions_hint = QLabel("两种文件都能打开：.cs2customizer（推荐，带说明和安检）和 .json。")
        actions_hint.setObjectName("hintLabel")
        actions_hint.setWordWrap(True)
        actions_column.addWidget(actions_hint)
        actions_column.addLayout(actions)
        workbench_layout.addLayout(actions_column)
        layout.addWidget(workbench_card)

        # UP-040: 「我的预设」——命名保存/一键应用/改名/删除。
        # 在此之前换一整套配置只能「导出文件再导入文件」，等于软件把
        # 它自己该做的事（记住几套具名配置）推给了文件系统。
        my_presets_card = self.build_my_presets_card(layout)

        # R2-2: 内置精选包(纯内置资源,零外部素材)
        starter_card, starter_layout = SettingsCard.make(
            "内置精选",
            # ⚠ 这句话原来的尾巴是「应用前自动备份当前配置，可在配置快照页回滚。」——
            #   而**底栏那一行常驻文案逐字说着同一件事，且和这张卡在同一屏上**。
            #   实测这一句在这一页出现了 **5 处**（这张卡 / 按地图那张卡 / 底栏 /
            #   导入确认框 / 导入成功的 toast），外审多发报「快照回滚在三四处重复堆叠」。
            #   ⭐ 批 32 RN-459 的同一个形状：**同一件事说五遍，多说的那几遍是纯成本。**
            #   ⇒ 屏幕上只留底栏那一份（它一直在）；确认框和 toast 那两份留着 ——
            #     它们不在这一屏上，一个在按下去的那一刻、一个在事后找回退路的时候。
            "三套开箱即用的体验包，不用先有文件也不用先存预设，选一套点「一键应用」就换过去。",
            spacing=10,
        )
        starter_row = QHBoxLayout()
        starter_row.setSpacing(8)
        self.starter_combo = QComboBox()
        self.starter_combo.setFixedHeight(34)
        self.starter_combo.setMinimumWidth(200)
        from core.presets.starter_packs import list_packs

        for pid, name, desc in list_packs():
            self.starter_combo.addItem(name, pid)
            self.starter_combo.setItemData(self.starter_combo.count() - 1, desc, Qt.ToolTipRole)
        starter_row.addWidget(self.starter_combo)

        self.starter_apply_btn = QPushButton("一键应用")
        self.starter_apply_btn.setObjectName("secondaryButton")
        self.starter_apply_btn.clicked.connect(self._apply_starter_pack)
        starter_row.addWidget(self.starter_apply_btn)
        starter_row.addStretch()
        self._set_compact_heights(self.starter_apply_btn)
        starter_layout.addLayout(starter_row)

        self.starter_desc_label = QLabel("")
        self.starter_desc_label.setObjectName("hintLabel")
        self.starter_desc_label.setWordWrap(True)
        starter_layout.addWidget(self.starter_desc_label)
        self.starter_combo.currentIndexChanged.connect(self._sync_starter_desc)
        self._sync_starter_desc()
        layout.addWidget(starter_card)

        # R2-4: 按地图自动切预设
        map_card, map_layout = SettingsCard.make(
            "按地图自动切换",
            "把「保存/导出的范围」勾中的类别存成某张图的预设；进这张图时自动套用。",
            spacing=10,
        )
        self.map_auto_check = QCheckBox("启用按地图自动切换")
        from config import config as _config

        self.map_auto_check.setChecked(bool(getattr(_config, "map_preset_enabled", False)))
        self.map_auto_check.toggled.connect(self._on_map_auto_toggled)
        map_layout.addWidget(self.map_auto_check)

        map_row = QHBoxLayout()
        map_row.setSpacing(8)
        self.map_combo = QComboBox()
        self.map_combo.setEditable(True)
        for m in ("de_dust2", "de_mirage", "de_inferno", "de_nuke", "de_ancient",
                  "de_anubis", "de_vertigo", "de_overpass", "de_train"):
            self.map_combo.addItem(m)
        self.map_combo.setFixedHeight(34)
        self.map_combo.setMinimumWidth(180)
        map_row.addWidget(self.map_combo)

        self.map_save_btn = QPushButton("保存当前范围为该图预设")
        self.map_save_btn.setObjectName("secondaryButton")
        self.map_save_btn.clicked.connect(self._on_map_rule_save)
        map_row.addWidget(self.map_save_btn)

        self.map_delete_btn = QPushButton("删除该图预设")
        # R7/D-06: 直接删掉地图→预设绑定，**连确认对话框都没有**
        # （_on_map_rule_delete 直接 delete_rule 然后弹「已删除」）
        style_as_danger_button(self.map_delete_btn)
        self.map_delete_btn.clicked.connect(self._on_map_rule_delete)
        map_row.addWidget(self.map_delete_btn)
        map_row.addStretch()
        self._set_compact_heights(self.map_save_btn, self.map_delete_btn)
        map_layout.addLayout(map_row)

        self.map_rules_label = QLabel("")
        self.map_rules_label.setObjectName("hintLabel")
        self.map_rules_label.setWordWrap(True)
        map_layout.addWidget(self.map_rules_label)
        layout.addWidget(map_card)
        # 换一张图 ⇒「删除该图预设」能不能点得跟着变（`_refresh_map_rules_label`）。
        self.map_combo.currentTextChanged.connect(
            lambda *_a: self._refresh_map_rules_label())
        self._refresh_map_rules_label()

        # ⭐⭐⭐ RN-476（批 40）：这张卡原来是一个 340px 高的只读框，
        #   里面逐字铺着 **8767 个字符 / 329 行**原始 JSON
        #   （`{"schema": "cs2customizer_preset_bundle", "schema_version": 2, "items": […`）。
        # ⚠ 而它的副标题逐字承诺自己是给人「快速确认内容范围」用的。
        #   外审 12 发问「你说得出这一套里有哪几类、每一类大概是什么吗」——
        #   **12/12「说不出」**，其中 8 发是在这个框**完整可见**的整页图上答的，
        #   10/12 的「读自」栏填「无」。
        # ⇒ ⭐⭐ **一个把全部信息都摊开的控件，可以同时是一个什么都没说的控件。**
        #   它不是"看着累"，是它承诺的那件事**一件都没做到**。
        # ⛔ 但不删那个框：对「打开了别人给的文件、想看清里面到底有什么」它是有用的
        #   —— 只是不该是**默认**那一屏。⇒ 收进一颗默认收起的开关后面。
        preview_card, preview_layout = SettingsCard.make(
            "范围里现在的内容",
            "下面这几行就是导出文件里会带走的东西，也是「存为新预设」会记住的东西。",
            spacing=10,
        )
        self.preview_summary_label = QLabel("")
        self.preview_summary_label.setObjectName("hintLabel")
        self.preview_summary_label.setWordWrap(True)
        self.preview_summary_label.setTextFormat(Qt.PlainText)
        preview_layout.addWidget(self.preview_summary_label)

        self.raw_toggle_btn = QPushButton("查看原始内容")
        self.raw_toggle_btn.setObjectName("secondaryButton")
        self.raw_toggle_btn.setCheckable(True)
        self.raw_toggle_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._set_compact_heights(self.raw_toggle_btn)
        self.raw_toggle_btn.toggled.connect(self._on_raw_toggled)
        preview_layout.addWidget(self.raw_toggle_btn)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(340)
        # ⚠ 这里是 `setVisible(False)`，不是 RN-009 那个「建出来就 `hide()`、
        #   全仓再没人 `show()`」的死控件 —— 上面那颗开关就是让它回来的那条路，
        #   而判据里配了阳性对照，专门证明它**回得来**。
        self.preview_text.setVisible(False)
        preview_layout.addWidget(self.preview_text)
        layout.addWidget(preview_card)

        # ⭐⭐ 卡片的**摆放顺序**在这里一处说清（批 38）。
        #
        # 改前实测（真窗 1280×800）：内容高 1851 / 视口 673 ⇒ **64% 的页面在折线以下**，
        # 而落在折线以下的正好是新手唯一想要的那两张 ——「内置精选」（y=1058）
        # 和「我的预设」；第一屏摆的是「保存/导出的范围 / 导入策略 / 导出分享文件」
        # 这些**要先有一个文件才用得上**的专家动作。
        # 外审改前窗口档 6/6 报「名为预设中心却没有预设列表或推荐模板，
        # 玩家找不到现成可直接一键套用的配置」，而同一页的整页无折线图上
        # 3/6 直接指向「三套开箱即用的体验包」⇒ ⭐ **答案在页面上，只是不在屏幕上。**
        #
        # ⇒ 按「要先有什么」从少到多排：什么都不用 → 自己存过的 → 得有个文件 → 高级 → 诊断。
        # ⚠ 构造顺序不能直接当摆放顺序：`build_my_presets_card()` 自己
        #   `parent_layout.addWidget(card)`（共用件，不为这一页改签名）。
        #   所以这里先让它们各自入队，再统一重排一次。
        # ⚠⚠ **从页头之后开始插，不是从 0 开始。**
        #   第一版写的是 `insertWidget(index, card)`，于是六张卡依次占住 0~5，
        #   把 `header` 一路推到了**整页最下面**（实测页头 top=1818，折线以下）。
        #   ⭐ 我重排的是「卡片」，而这条布局里的第一项不是卡片。
        #   ⭐⭐ 而那条只钉「一键应用露不露脸」的判据**照样是绿的** ——
        #     批 32 说「只许钉对象、不许钉数量」，它的背面是：
        #     **只钉一个对象的判据，看不见我把别的东西挤到哪儿去了。**
        #     ⇒ 下面那条 `test_the_page_header_is_still_the_first_thing` 补这一格。
        # ⭐ 批 40 在这条队里插了一张新卡：「保存/导出的范围」（RN-477）。
        #
        # ⚠⚠ 它排在哪儿是**量出来的，不是排出来的**。紧凑档（860×640）视口只有
        #   **554px**，第一屏装不下四张卡 —— 于是「一键应用要在第一屏」（批 38 的成果）
        #   和「七个勾选框要在第一屏」（本批）在这一档上**抢同一块地方**。
        #   ⇒ 让位的是「我的预设」：新用户那张卡本来就是空的
        #     （下拉框空白、按钮置灰，本轮外审也点了名），而另外两张对新用户都有内容。
        #   ⭐ **第一屏放不下的时候，让位的应该是那张对第一次来的人还没有内容的卡。**
        #
        # ⛔ 也**不能**把它排到「内置精选」**之前**：那会让人读成「这几个勾选框
        #   决定一键应用会套用哪几类」——而内置精选带着自己的 items，压根不看这里。
        #   ⭐ 一个控件摆在谁上面，就会被读成管着谁。
        # ⭐⭐⭐ RN-486（批 40 补刀）：上一版把工作台排在「我的预设」**之后**，
        #   而实测那把它整张推出了第一屏 —— 两颗按钮露出 **0%**
        #   （完整档折线 y=814，按钮 y=922~976；`H:/tmp/b40_probe2.py` 实测）。
        # ⚠⚠ 更要命的是**改前它还露着一截**：批 38 的窗口图上，
        #   「预设工作台」的标题和那句「读入别人发来的文件」还在第一屏底部；
        #   改后一个像素都没有 —— ⭐ **是我这一批把它推下去的**（插进来的范围卡占 146px）。
        # ⭐⭐⭐ 而它的代价有一组天然对照实验量出来了。同一份状态、同一个问题
        #   （「朋友发来一份配置文件，你会点哪个」），只差看不看得见折线以下：
        #     · 窗口图  6/6「有把握: **没有**」，答案乱猜（存为新预设 / 纯净提示 / ?）
        #     · 整页图  6/6「**打开一份配置文件**」· 候选数 1 · 「有把握: **有**」
        #   ⇒ 命名（RN-478）修好之后，**剩下的唯一障碍就是它不在第一屏上**。
        #     这与 RN-414（准心那次）同形：**「找不到入口」只在窗口图上报，
        #     那不是 RN-170 的折线假象 —— 窗口图就是用户真正的第一屏。**
        #     （对照：RN-170 那类「这块被切坏了」才是假象。判别看抱怨的是
        #      "画坏了" 还是 "找不到"。）
        # ⇒ 让位的是「我的预设」：⭐ **第一屏放不下的时候，让位的应该是那张
        #   对第一次来的人还没有内容的卡** —— 全新安装 `list_presets()` 为空，
        #   那张卡是一个空下拉框加四颗灰按钮；而交换配置这件事第一天就能用。
        #   （同一条原则本批已经用过一次：范围卡也是这么插到它前面去的。）
        card_order = (status_card, starter_card, scope_card,
                      workbench_card, my_presets_card, map_card, preview_card)
        first = layout.indexOf(header) + 1
        for offset, card in enumerate(card_order):
            layout.removeWidget(card)
            layout.insertWidget(first + offset, card)

        # ⚠⚠ **摆放顺序改了，Tab 键的顺序不会跟着改。**
        #   Qt 的焦点链默认走**构造顺序**，而这一批只动了**显示顺序** ——
        #   于是屏幕上第一张卡（内置精选）里的控件，按 Tab 要按到第 12 下才轮到。
        #   `scripts/tab_order_audit.py` 当场报 **[preset_center] 需挪动 8 个**。
        # ⭐⭐ 这一条是判据抓的，我自己出图、外审看图**都不可能看见它** ——
        #   焦点顺序不在任何一张截图里（同本批主刀那条：截图没有时间轴，也没有键盘）。
        self._chain_tab_order(card_order)

        layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll)

        self.action_bar = PageActionBar(self)
        # RN-283：底栏原来构造时写死「支持 HUD / 屏幕特效 / 特殊音效 三域预设。」——
        # 而同屏往上 250px 就摆着 **7 个**勾选框（引擎 `SUPPORTED_TYPES` 也是 7 类）。
        # 外审 12 发 **12/12 答「7 类」、12/12 答「矛盾: 有」**，11/12 逐字抄出了那句话。
        # ⭐ 更糟的是它是**一次性**的：`_refresh_dirty_ui` 一跑就换掉，再也回不来
        #   ⇒ **只有每个人的第一眼看得到它，而它是假的。**
        # ⇒ 首屏这句话不再单独写一份，交给和后面每一次刷新同一个出口。
        # RN-281 / RN-452：底栏那颗主按钮撤掉（同批 10 crosshair、批 28 magnifier）——
        # 它和工作台里那颗是同一个 `_save_changes`，而这个动作只在「读入过一份包」
        # 时才有对象，放在页级主按钮位上等于让每个人第一眼就想去点一颗空转的按钮
        # （行为题 ①**12/12** 都选了它）。
        self.action_bar.configure_primary("", None, visible=False)
        # ⛔ 次位那颗「重新预览」也撤掉，而理由不是版式 —— **它做的事是有害的**：
        #   `_render_preview()` 里第一句就是 `export_bundle(当前勾选)` 并覆盖
        #   `self._current_bundle`。于是「导入预设包」读进来一份、还没应用的时候，
        #   点一下「重新预览」会**一声不响地把那份包扔掉**，而页面仍然是 dirty、
        #   「应用读入的预设包」仍然亮着 —— 按下去应用的是**你自己的当前配置**。
        # ⚠⚠ 而它本来不显眼；是**我撤掉主按钮之后，它接管了底栏最响的位置** ——
        #   批 31 那条逐字再现：**一个控件怎么被读、有多大杀伤力，由它的邻居决定。**
        # ⭐ 另一半：预览本来就一直是最新的（勾选/模式一变就 `_render_preview`），
        #   所以这颗按钮**唯一的独有效果就是那个静默丢弃**。
        root.addWidget(self.action_bar, 0)
        self._refresh_bottom_message()

        for checkbox in (
            self.cb_hud, self.cb_screen, self.cb_special,
            self.cb_crosshair, self.cb_flash, self.cb_viewmodel, self.cb_magnifier,
        ):
            checkbox.toggled.connect(self._on_selection_changed)
        self._update_compact_layout()

        # R2-1: 拖 .cs2customizer 进页面即走导入确认流程
        try:
            from widgets.drop_import_mixin import enable_file_drop

            # ⚠ 这里原来把 `.cs2customizer` **写死**在字面量里 —— 开源子集的后缀是 `.cs2c`，
            #   于是那边拖一份自己导出的文件进来会被静默忽略（拖放没有错误提示）。
            #   ⭐ 同一份知识出现在第二个地方就会漂：后缀只有一个真源。
            from core.presets.share_file import LEGACY_SHARE_EXTS, SHARE_EXT

            enable_file_drop(
                self, (SHARE_EXT, *LEGACY_SHARE_EXTS, ".json"),
                self._on_share_file_dropped)
        except Exception:
            self.logger.exception("分享文件拖拽初始化失败")

    _TYPE_CHECKBOX_SPEC = (
        # ⚠ 这一格的显示名原来是「HUD」，而勾选框上写的是「HUD 规则」——
        #   **同一类东西在同一屏上有两个名字**（勾选框一个、预览/摘要/我的预设另一个）。
        #   改完复跑有一发逐字把这两处并排抄出来当矛盾报 ⇒ 统一成勾选框上的那个。
        ("cb_hud", "hud_rules", "HUD 规则"),
        ("cb_screen", "screen_effects", "屏幕特效"),
        ("cb_special", "special_sound", "特殊音效"),
        ("cb_crosshair", "crosshair", "准心"),
        ("cb_flash", "flash", "自定闪光"),
        ("cb_viewmodel", "viewmodel", "局内视角"),
        ("cb_magnifier", "magnifier", "开镜放大"),
    )

    def _selected_types(self):
        return [
            type_id
            for attr, type_id, _label in self._TYPE_CHECKBOX_SPEC
            if getattr(self, attr).isChecked()
        ]

    def _selected_type_labels(self):
        return [
            label
            for attr, _type_id, label in self._TYPE_CHECKBOX_SPEC
            if getattr(self, attr).isChecked()
        ]

    # ⛔ `_mode_label_text()` 撤掉：它服务的那个页级下拉框已经不存在了（RN-484）。
    #   导入模式现在是**每一次导入各自的一次性选择**，它的名字只活在确认框那一刻，
    #   ⭐ 所以它不该有一个能被这一页任何别处读到的"当前值"。

    def _update_compact_layout(self):
        # UP-100: 这一页原来有**两处**需要按页宽换向，阈值不同（工作台三列 1120，
        # 「我的预设」那一行 960），因为它们的最小宽本来就不一样。
        # ⚠ 批 40 撤掉「导入策略」那一列之后，工作台只剩一列（两颗按钮），
        #   **没有可换的向了** ⇒ 这里只剩「我的预设」那一处。
        #   ⭐ 换向逻辑是给「两列并排会挤」准备的；列数变成 1，它就不是"暂时用不上"，
        #     是**结构上不再有对象** —— 留着它等于留一个永远走同一支的分叉。
        self._update_my_presets_layout(self.width())

    def _sync_status_strip(self, bundle: dict | None = None):
        bundle = bundle or self._current_bundle or {}
        selected_labels = self._selected_type_labels()
        item_count = len((bundle or {}).get("items", []) or [])

        # RN-281：第四颗胶囊原来写「状态 · 待应用 / 已同步」——
        # 而「同步」这个词在这一页没有对应物（它不往任何地方同步），
        # 「待应用」在勾一下打包范围之后就会亮起，那时**什么都没变**。
        # ⭐ 立案说的是「未展示当前加载的预设名称，不清楚点应用会生效什么」，
        #   而根因就在这一格：屏幕上从来没说过**预览里那份东西是哪来的**。
        #   ⇒ 这颗胶囊改成回答那个问题。
        # ⚠⚠ 第一颗胶囊原来只写「范围 · 5 类」，而**改完复跑当场量出它的代价**：
        #   窗口档 6/6 把「这个软件的预设能装几类」答成了 **5**（改前 12/12 答 7）——
        #   因为本批的重排把那七个勾选框挪到了折线以下，第一屏上只剩这颗胶囊，
        #   而「5」是「你现在勾了几个」，不是「一共有几类」。
        #   ⭐⭐ 批 31 那条的另一个形态：**一个只在邻居在场时才说得清的标签，
        #     被搬家搬成了一句含糊话** —— 我搬走的是它的邻居，不是它。
        #   ⇒ 让它自己说全：`5/7`。
        # ⚠⚠ 批 40 撤掉了第三、第四颗：
        #   · 「内容 · N 项」 —— `export_bundle` 每一类产出**恰好一项**，
        #     所以这个 N **永远等于**第一颗里的那个 N ⇒ ⭐ **同一个数说了两遍，
        #     还起了两个名字**（外审在网页那条判据里早就记过：同一个数字出现两次
        #     会被读成两笔）。
        #   · 「来源 · …」 —— 它的两个取值靠 dirty 区分，而 dirty 这一批整个退场了
        #     （RN-478）：预览永远是「你现在的设置」⇒ 一颗**恒定**的胶囊，
        #     ⭐ 而恒定的状态显示不携带任何信息（RN-053 那一族）。
        #   · 「模式 · 合并」—— 批 40 补刀（RN-484）连它一起撤：那个页级下拉框
        #     整个退场之后，这颗胶囊报的是一个**不再存在的设定**。
        #     ⭐ 它和「来源」那颗同病：一颗恒定的、没有对应物的状态显示。
        # ⚠ 于是这张卡只剩一颗胶囊了，而它恰好是这一页唯一真正随操作变的那个数
        #   （勾几类）⇒ 让它把话说全，别再靠邻居。
        badges = [
            ("positive" if selected_labels else "warning",
             f"范围 · {len(selected_labels)}/{len(self._TYPE_CHECKBOX_SPEC)} 类"),
        ]

        if selected_labels:
            scope_text = " / ".join(selected_labels)
        else:
            scope_text = "当前未选择任何预设范围"
        detail_text = (
            f"当前选择范围：{scope_text}。"
            f"预览包内共 {item_count} 项。"
        )
        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.status_card.setToolTip(detail_text)

    def _on_selection_changed(self):
        # ⛔ 这里原来有一句 `self.mark_dirty()`，而它是本批的主刀。
        #
        # 勾一下「保存/导出的范围」是一次纯粹的**选择**：实测 config 里
        # **0 个键**发生变化（57 个会被写回的键逐个深拷贝比对过）。
        # 而 `mark_dirty()` 在 `DirtyPageMixin` 里带着一项权力 ——
        # `can_leave_page()` 会弹「当前页面有未保存修改，是否保存后离开？」拦住人。
        #
        # ⭐⭐⭐ 于是四步，每一步都长得完全正常，每一步都是假的：
        #   ① 胶囊「状态 · 待应用」        假状态
        #   ② 底栏「有未应用的预设变更。」  假句子
        #   ③ 模态框拦住离开               假拦截
        #   ④ 点「保存并离开」→ 改 0 个键，弹「已应用类型: …」  假成功
        # **一个假前提，会一路把四个各自正确的机制变成四句假话。**
        # 那四个机制单看都没写错，错的是它们共用的那个前提：
        # 「这一页有一种叫『未保存的修改』的东西」。
        #
        # ⚠ 另一半：`_render_preview()` 会拿当前勾选重新打包并覆盖 `_current_bundle`，
        #   所以**改勾选这个动作本身就把「刚读进来的那份包」扔掉了**。
        #   那么 dirty 就不该继续挂着 —— 挂着的话，「应用读入的预设包」还亮着，
        #   而按下去应用的是你自己的当前配置。
        #   ⭐ 这不是「顺手清一下标志位」：**是让标志位重新指向一个真实存在的东西。**
        #
        # ⭐⭐⭐ 批 40 走完了那条路的最后一步：**那个标志位本身也不该存在。**
        #   批 38 把 dirty 收窄到只剩一个真源（「读进来一份还没应用的包」），
        #   而这一批把两条导入路统一成「确认 → 应用」之后，那个状态不再产生。
        #   ⇒ **一个机制收窄到只剩一个用例之后，下一个该问的问题是：
        #     那一个用例，是不是也可以不由它来做。**
        self._render_preview()
        # 「我的预设」空态那句话现在**逐字念出当前勾选**，所以勾选一变它就得跟着变。
        # ⚠ 不跟着变的后果不是"没刷新"：那句话会**具体而肯定地说错**
        #   （批 30：一次「把文案写具体」的改动，把真话改成了假话）。
        self._sync_my_preset_hint()

    def _on_raw_toggled(self, checked: bool):
        self.preview_text.setVisible(bool(checked))
        self.raw_toggle_btn.setText("收起原始内容" if checked else "查看原始内容")

    def _render_preview(self):
        """预览**永远**是「你现在的设置」。

        ⭐ 批 40 之前它有两种含义（你的设置 / 刚读进来还没应用的那一份），
        而屏幕上靠一颗「来源 · …」胶囊区分。两种含义一撤，那颗胶囊就恒定了 ——
        ⇒ **一个控件只表达一件事的时候，说明它的那句话才可能是有信息的。**
        """
        bundle = export_bundle(self._selected_types())
        self._current_bundle = bundle
        self.preview_summary_label.setText(self._summary_text(bundle))
        self.preview_text.setPlainText(json.dumps(bundle, ensure_ascii=False, indent=2))
        self._sync_status_strip(bundle)

    @staticmethod
    def _summary_text(bundle: dict) -> str:
        """人话摘要（RN-476）。摘要**怎么说**由 `core.presets.preset_center` 一家决定，
        这里只管**怎么排**——导入确认框那一处排法不一样，但说的必须是同一句。
        """
        from core.presets.preset_center import describe_bundle

        rows = describe_bundle(bundle)
        if not rows:
            return "一类都没勾，这一套现在是空的。到上面「保存/导出的范围」勾上至少一类。"
        return "\n".join(f"· {label}：{detail}" for label, detail in rows)

    def showEvent(self, event):
        # ⚠⚠ RN-489（批 40 补刀）：`_refresh_bottom_message` 全仓原来只有
        #   `_init_ui` 一个调用方 ⇒ 那句按「危险操作前自动快照」分叉的话
        #   **被钉死在建页的那一刻**。用户之后到配置快照页把那个开关关掉再回来，
        #   底栏仍然承诺「可以在配置快照页回滚」——
        #   ⭐⭐ 上面那段注释自己写着「关掉之后照抄这句话就是假话」，
        #   而它防住了「写错」，没防住「**算过一次就不再算**」。
        #   ⭐ 一句随外部状态变的话，光有正确的算法不够，还得有人在状态变了之后叫它。
        super().showEvent(event)
        self._refresh_bottom_message()

    # ⛔ `_load_settings` 撤掉：它唯一的调用方是 `DirtyPageMixin.discard_changes()`
    #   里的 `getattr(self, "_load_settings", None)`，而本批把这一页的 mixin 整个摘了
    #   ⇒ 全仓再无任何调用点。⭐ 撤一个机制要连着撤它的挂钩，
    #   否则留下的是一个"看起来还有人用"的孤儿方法。

    def _refresh_bottom_message(self):
        # ⭐ 底栏这句话现在是**唯一**出口：首屏那一句也由它出（`_init_ui` 结尾调一次）。
        #   原来首屏另写死一句「支持 … 三域预设。」，被这里一冲就再也回不来 ——
        #   **一句没有第二个人负责的话，不会跟着状态走，也没人会去核对它**（RN-283）。
        # ⚠ 这句话要回答**第一屏**上的疑问，不能去指第一屏上没有的东西。
        #   第一版写的是「改这一页的勾选不会动到你的设置」—— 而重排之后
        #   那些勾选框已经落到折线以下了 ⇒ 批 32 那条（「一句正确的指路，
        #   会把路的那一头看不见变成一个新缺陷」）会当场再现一次。
        #   第一屏上是「内置精选」和「我的预设」，玩家在那儿的疑问只有一个：
        #   **点下去我现在的设置会怎么样。**
        # ⚠ 「会自动备份」不是全站事实，是一个**可以被关掉的开关**
        #   （配置快照页里的「危险操作前自动快照」）。关掉之后照抄这句话就是假话
        #   —— 批 24 那条：一句被当成事实的话，只要有一处不成立，在那儿就是假的。
        from config import config as _cfg

        # ⚠⚠ **这句话第一版写的是「都会立刻换掉你现在的设置」，改完复跑当场被逮**
        #   （紧凑窗口 3/3 报「和『模式 · 合并』互相矛盾」）—— 而它说得对：
        #   三条应用通路（内置精选 / 我的预设 / 按地图）**全都是 `mode="merge"`**，
        #   只动这份预设覆盖到的那些键，别的一个不碰。
        # ⭐ 批 36 那条第二次现身：**这一批最贵的一句话，是我自己补上去的那半句**。
        auto_snapshot = bool(getattr(_cfg, "config_snapshot_auto_before_risky_ops", True))
        self.action_bar.set_message(
            "应用一套预设，会立刻改掉这套预设覆盖到的那几类设置，别的不动" +
            ("；动手前会自动存一份快照，可以在配置快照页回滚。"
             if auto_snapshot else
             "。你把「危险操作前自动快照」关掉了，这一次改过去就回不来了。"))
        self._sync_status_strip()

    # ---------------- RN-478：一个动作一颗按钮，两种文件都吃 ----------------

    def _export_config_file(self):
        """导出这一套。默认写 `.cs2customizer`；仍然可以选 `.json`。

        ⭐ 玩家在对话框里选的是**文件类型**（发给朋友 / 自己留着改），
        不是在页面上先选一条技术路线 —— 那是批 31「一个动作一个入口」的
        文件格式版：**格式是实现细节，动作才是入口。**
        """
        from core.presets.share_file import SHARE_EXT, write_share_file

        types = self._selected_types()
        if not types:
            QMessageBox.information(
                self, "提示", "「保存/导出的范围」一类都没勾，导出来会是个空文件。")
            return
        bundle = export_bundle(types)
        default_dir = ResourceManager.get_app_data_path("presets")
        os.makedirs(default_dir, exist_ok=True)
        path, chosen = QFileDialog.getSaveFileName(
            self,
            "导出这一套配置",
            os.path.join(default_dir, f"我的配置{SHARE_EXT}"),
            f"CS2 Customizer 分享文件 (*{SHARE_EXT});;JSON 文件 (*.json)",
        )
        if not path:
            return
        if not path.lower().endswith((SHARE_EXT, ".json")):
            path += ".json" if "json" in (chosen or "").lower() else SHARE_EXT
        try:
            if path.lower().endswith(".json"):
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(bundle, handle, ensure_ascii=False, indent=2)
            else:
                write_share_file(
                    path, bundle, title=os.path.splitext(os.path.basename(path))[0])
            QMessageBox.information(
                self, "导出成功",
                f"{path}\n\n把这个文件发给朋友，拖进对方的预设中心即可导入。")
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

    def _open_config_file(self):
        # ⭐ `LEGACY_SHARE_EXTS` 在闭源版是空元组，在开源子集里是 `(".cs2customizer",)` ——
        #   两个仓的这条差异**收在那一个常量里**，这里不需要任何分支。
        from core.presets.share_file import LEGACY_SHARE_EXTS, SHARE_EXT

        patterns = " ".join(f"*{ext}" for ext in (SHARE_EXT, *LEGACY_SHARE_EXTS))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开一份配置文件",
            ResourceManager.get_app_data_path("presets"),
            f"配置文件 ({patterns} *.json)",
        )
        if path:
            self._import_config_path(path)

    def _read_config_file(self, path):
        """按扩展名读，返回 (bundle, 说明文字, warnings)；读不了就返回 (None, 原因, [])。

        ⚠ 两条路在这里**汇成一条**。旧版它们汇不到一起：`.cs2customizer` 走确认→应用，
        `.json` 走预览→再点一次按钮，而**决定走哪条的是用户看不见的扩展名**。
        ⭐ 一颗按钮两种行为，比两颗按钮更糟 —— 至少两颗按钮把选择摆在明面上。
        """
        from core.presets.share_file import (
            LEGACY_SHARE_EXTS,
            SHARE_EXT,
            describe,
            read_share_file,
        )

        # ⚠ 认后缀这一处也要吃旧后缀，否则开源子集里打开一份 `.cs2customizer`
        #   会掉进 `.json` 那条分支，读到一个 zip 的字节 ⇒「这个文件读不开」。
        if path.lower().endswith((SHARE_EXT, *LEGACY_SHARE_EXTS)):
            result = read_share_file(path)
            if not result.ok:
                return None, "\n".join(result.errors), []
            return result.bundle, describe(result), list(result.warnings)

        # ⚠⚠ RN-488（批 40 补刀）：这条 `.json` 路上一版**一个字节的上限都没有**，
        #   而紧挨在它上面那条 `.cs2customizer` 路有三道闸（压缩包 50MB / 解压总量 200MB /
        #   条目数 256）。⭐⭐ 本批把两条路「汇成一条」，汇的是**下游**
        #   （同一个确认框、同一次 apply），而**上游的安检没有跟着汇** ——
        #   于是「统一」这件事本身，给安检开了一个只有一半的口子。
        #   ⇒ 把体积闸补齐。同一个数字，取自同一个真源。
        try:
            from core.presets.share_file import MAX_ARCHIVE_BYTES

            size = os.path.getsize(path)
            if size > MAX_ARCHIVE_BYTES:
                return None, (
                    f"这个文件有 {size // 1024 // 1024} MB，超过了 "
                    f"{MAX_ARCHIVE_BYTES // 1024 // 1024} MB 的上限，没有打开。"
                ), []
            with open(path, "r", encoding="utf-8") as handle:
                bundle = json.load(handle)
        except Exception as exc:
            return None, f"这个文件读不开：{exc}", []
        validation = validate_bundle(bundle)
        if not validation.ok:
            return None, "\n".join(validation.errors), []
        # ⚠ 这里原来直接复用 `_summary_text(bundle)`，而那个函数的**空态分支**
        #   写的是给本页勾选框用的话（「一类都没勾…到上面「保存/导出的范围」勾上至少一类」）。
        #   ⭐ 于是打开一份 items 为空的 .json 时，确认框会叫用户去勾**自己的导出范围**
        #     —— 而导入这条路**根本不读那组勾选**（卡上那句话自己写着「不看这里」）。
        #   ⭐⭐ 一句话搬了个家，就从"对的"变成"答非所问且指错控件"：
        #     空态文案属于它所在的那张卡，不属于这个动作。
        items = bundle.get("items", []) or []
        if not items:
            return bundle, "这份文件里一类配置都没有，导入它不会改变任何设置。", list(
                validation.warnings)
        rows = self._summary_text(bundle)
        return bundle, f"包含 {len(items)} 类配置:\n{rows}", list(
            validation.warnings)

    # ---------------- R2-2: 内置精选包 ----------------

    def _sync_starter_desc(self):
        from core.presets.starter_packs import list_packs

        pid = self.starter_combo.currentData()
        for p, _name, desc in list_packs():
            if p == pid:
                self.starter_desc_label.setText(desc)
                return
        self.starter_desc_label.setText("")

    def _apply_starter_pack(self):
        from core.presets.starter_packs import get_pack_bundle

        pid = self.starter_combo.currentData()
        if not pid:
            return
        try:
            bundle = get_pack_bundle(pid)
        except KeyError:
            return
        reply = QMessageBox.question(
            self, "应用精选包?",
            f"将应用「{self.starter_combo.currentText()}」(merge 模式,应用前自动备份)。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        result = apply_bundle(bundle, mode="merge")
        if result.ok:
            self._render_preview()
            try:
                from ui_toast import toast_success, toast_warning

                name = self.starter_combo.currentText()
                if result.warnings:      # QA-013
                    toast_warning(f"已应用「{name}」，但{'；'.join(result.warnings)}")
                else:
                    toast_success(f"已应用「{name}」")
            except Exception:
                QMessageBox.information(self, "完成", "已应用")
        else:
            QMessageBox.warning(self, "应用失败", "\n".join(result.errors))

    # ---------------- R2-4: 按地图自动切预设 ----------------

    def _on_map_auto_toggled(self, checked):
        from config import config as _config

        _config.map_preset_enabled = bool(checked)
        _config.save_config()
        self.logger.info(f"按地图自动切预设: {'开' if checked else '关'}")

    def _on_map_rule_save(self):
        from core.presets.map_rules import save_rule

        map_name = self.map_combo.currentText()
        types = self._selected_types()
        if not types:
            QMessageBox.information(
                self, "提示", "「保存/导出的范围」一类都没勾，没有东西可以存给这张图。")
            return
        if save_rule(map_name, types):
            self._refresh_map_rules_label()
            QMessageBox.information(self, "已保存", f"进入 {map_name.strip().lower()} 时将自动套用这套配置")
        else:
            QMessageBox.warning(self, "保存失败", "地图名为空或范围为空")

    def _on_map_rule_delete(self):
        from core.presets.map_rules import delete_rule

        map_name = self.map_combo.currentText()
        if delete_rule(map_name):
            self._refresh_map_rules_label()
            QMessageBox.information(self, "已删除", f"{map_name.strip().lower()} 的绑定已移除")
        else:
            QMessageBox.information(self, "提示", "该地图没有已保存的绑定")

    def _refresh_map_rules_label(self):
        from core.presets.map_rules import list_rules

        rules = list_rules()
        self.map_rules_label.setText(
            "已绑定: " + ", ".join(rules) if rules else "尚无地图绑定。勾选范围 → 选图 → 保存即可。"
        )

        # ⭐ **同一页上同一件事，两张卡原来给了相反的处理。**
        #   「我的预设」一条都没有时会把「删除」禁掉（`refresh_my_presets`，UP-022），
        #   而这颗红色的「删除该图预设」在**一条绑定都没有**时照样是亮的 ——
        #   它还是全页唯一一颗红按钮，坐在一张写着「尚无地图绑定」的卡上。
        #   ⇒ 批 29 RN-447 那条（红「删除」全长在空槽位上）在这一页的实例。
        # ⚠ 判别到**这一张图**，不是「有没有任何绑定」：`_on_map_rule_delete`
        #   删的是当前下拉里那张图的绑定，别的图有绑定并不让这颗按钮有事可做。
        btn = getattr(self, "map_delete_btn", None)
        if btn is None:
            return
        current = str(self.map_combo.currentText()).strip().lower()
        bound = current in {str(r).strip().lower() for r in rules}
        btn.setEnabled(bound)
        btn.setToolTip(
            f"删掉「{current}」的绑定，进这张图时不再自动套用。"
            if bound else
            f"「{current or '这张图'}」还没有绑定过预设，没有可删的东西。")

    # ---------------- 打开一份配置文件：两种扩展名汇成一条路 ----------------

    def _on_share_file_dropped(self, paths):
        if paths:
            self._import_config_path(paths[0])

    def _import_config_path(self, path):
        """读取→（`.cs2customizer` 另加安检）→确认→应用（应用前自动建快照）。

        ⭐⭐ 两种扩展名在 `_read_config_file` 里汇成一条路，**从这一行往下完全一样**：
        同一个确认框、同一份摘要、同一次 `apply_bundle`。
        ⚠ 旧版 `.json` 走的是「塞进预览 + `mark_dirty()` + 等你再点一次按钮」，
          而那颗按钮和那张预览卡实测都在折线以下 ——
          ⭐ **把「你确认一下」放进一个看不见的地方，等于没有确认这一步。**
        """
        bundle, text, warnings = self._read_config_file(path)
        if bundle is None:
            QMessageBox.warning(self, "无法导入", text)
            self.logger.warning(f"配置文件被拒: {path} -> {text}")
            return

        if warnings:
            text += "\n\n注意: " + "; ".join(warnings)
        text += "\n\n应用前会自动备份当前配置,可在配置快照页回滚。"

        # ⭐⭐⭐ RN-484：导入模式从页面搬到这里 —— 这是它唯一被读到的那一刻，
        #   而且**只有到了这一刻才知道该不该问**：
        #   `mode_affects_result` 拿这份文件真正会写的键去比，
        #   一个 dict 型的都没碰到就说明两种模式结果逐字节相同 ⇒ **连问都不问**。
        # ⭐ 实测 7 类里有 3 类（准心 / 屏幕特效 / 局内视角）永远走这条不问的路。
        conflicts = mode_affects_result(bundle)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("确认导入这份配置?")
        box.setText(text)
        if conflicts:
            names = "、".join(sorted({TYPE_LABELS.get(t, t) for t, _k in conflicts}))
            box.setInformativeText(
                f"这份文件里有{names}的自定义条目，和你现在的条目不是同一批。\n"
                "要怎么处理你自己加的那些？"
            )
            box.addButton("留着，只补上文件里的", QMessageBox.AcceptRole)
            replace_btn = box.addButton("清掉，只要文件里的", QMessageBox.DestructiveRole)
        else:
            box.addButton("导入", QMessageBox.AcceptRole)
            replace_btn = None
        cancel_btn = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None or clicked is cancel_btn:
            return
        mode = "replace" if (replace_btn is not None and clicked is replace_btn) else "merge"

        apply_result = apply_bundle(bundle, mode=mode)
        if not apply_result.ok:
            QMessageBox.warning(self, "应用失败", "\n".join(apply_result.errors))
            return
        # ⚠ 应用完**重新按当前勾选出图**，而不是把导入的那份摆在预览里：
        #   config 已经变了，所以「你现在的设置」就是最新的那一份 ——
        #   ⭐ 预览只表达一件事，它才可能一直是真的。
        self._render_preview()
        self.logger.info(f"配置文件导入成功: {path} -> {apply_result.applied_types}")
        try:
            from ui_toast import toast_success, toast_warning

            # QA-013: 这句话直接承诺"可回滚"，快照没建成时必须换口径，别骗用户
            if apply_result.warnings:
                toast_warning(
                    f"已导入 {len(apply_result.applied_types)} 类配置，"
                    f"但{'；'.join(apply_result.warnings)}")
            else:
                toast_success(
                    f"已导入 {len(apply_result.applied_types)} 类配置,删错可去配置快照页回滚")
        except Exception:
            QMessageBox.information(self, "导入成功", f"已应用: {', '.join(apply_result.applied_types)}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_compact_layout()
