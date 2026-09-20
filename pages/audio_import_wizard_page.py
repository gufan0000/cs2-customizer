#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resource import wizard page."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import config
from core.audio.audio_task_runner import submit_import_refresh_task
from core.resource_import_source import (
    ImportCancelled,
    ImportSourceError,
    open_source,
)
from widgets.kill_icon_import_task import KillIconImportTask
from widgets.page_notice_bar import PageNoticeBar
from core.resource_import_wizard import (
    apply_resource_import_plan,
    plan_from_decisions,
    prepare_decisions,
    remember_decisions,
    undo_import,
)
from core.utils.logger import get_logger
from pages.audio_status_badge import create_badge_label, render_badges
from resource_manager import ResourceManager
from widgets.page_action_bar import PageActionBar
from widgets.settings_card import SettingsCard
from widgets.page_header import PageHeader


# v2.2.1: 未识别原因中文化——旧版直接把英文 reason 打给用户，无从下手
_REASON_TRANSLATIONS = {
    "source directory missing": "源目录不存在",
    "path does not include a supported resource category root": "路径里没有可识别的分类目录名（如 kill_sounds）",
    "path does not include a supported audio category root": "路径里没有可识别的分类目录名（如 kill_sounds）",
    "resource category not supported in current mode": "该分类不属于当前导入模式（试试切换 音频/视觉/全部）",
    "resolved target escapes resources root": "目标路径越界，已拦截",
    "resolved target escapes audio root": "目标路径越界，已拦截",
    "invalid plan item": "条目信息不完整",
}


def _translate_reason(reason: str) -> str:
    text = str(reason or "").strip()
    if text in _REASON_TRANSLATIONS:
        return _REASON_TRANSLATIONS[text]
    if text.startswith("unsupported file extension"):
        return "文件扩展名不被该分类支持"
    return text  # io_validation 等已是中文的原样保留


_STRUCTURE_GUIDE = (
    "\n[未识别文件怎么办]\n"
    "方式一（推荐）：点上方“把未识别音频导入为新风格…”，选择类别和风格名即可自动改名落盘，无需整理目录。\n"
    "方式二：把素材整理成标准结构后重新扫描，例如：\n"
    "  你的目录/kill_sounds/我的风格/1.mp3 … 5.mp3      （击杀音效，1-5 对应连杀数）\n"
    "  你的目录/kill_voices/我的风格/1.mp3 … 5.mp3      （击杀语音）\n"
    "  你的目录/switch_weapons/weapon_ak47/我的风格/任意.mp3（切枪音效）\n"
    "  你的目录/death/风格名.mp3                        （被击杀音效，文件名即风格名）\n"
)


class AudioImportWizardPage(QWidget):
    """Import external resources into app resource directories."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger("AudioImportWizardPage")
        self.audio_root = ResourceManager.get_app_data_path("resources/audio")
        self.resources_root = ResourceManager.get_app_data_path("resources")
        # ⛔ 这两个字段必须**一起动** —— 一律走 `_invalidate_scan()`，
        #   别在各处分别赋值（那正是本轮修掉的那种"各自列举"）。
        self._invalidate_scan()
        self._last_import_result = None
        self._init_ui()
        # 对标主流：把文件夹/音频文件直接拖进页面即可填入并扫描
        self.setAcceptDrops(True)

    # ---------------- 拖拽导入（对标修缮） ----------------

    def dragEnterEvent(self, event):
        # ⛔ 不许写回 `event.mimeData().hasUrls()`（RN-674，理由在 `urls_from_drop`）。
        from widgets.drop_import_mixin import urls_from_drop

        if urls_from_drop(event):
            self._set_drop_highlight(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        # ⚠ 少这一条，高亮就留在屏上不走 —— 界面一直说「松手即可放入」而那时松手没用。
        self._set_drop_highlight(False)
        super().dragLeaveEvent(event)

    def _set_drop_highlight(self, on: bool):
        """把第 2 步那个大框点亮成**看得见的投放区**（RN-674，叙事见登记册）。

        ⛔ 颜色每次现取，不许在 `__init__` 里算一份存着 —— 主题随时可换
        （RN-672 那条「对话框 `setStyleSheet` 是构造时的快照」同族）。
        """
        box = getattr(self, "preview_text", None)
        if box is None:
            return
        if not on:
            box.setStyleSheet(getattr(self, "_preview_base_qss", ""))
            return
        try:
            from theme_manager import get_color

            accent = get_color("accent_primary")
        except Exception:
            accent = "#7C5CFF"
        box.setStyleSheet(
            getattr(self, "_preview_base_qss", "")
            + "\nQTextEdit { border: 2px dashed %s; }" % accent)

    @staticmethod
    def _drop_noun(path):
        """拖进来的这个东西该叫什么 —— 判断在 `resource_import_source`，这里只兜底。

        ⚠ 这行文案原来写死成「文件夹 / 压缩包」二选一，那是**加单文件那条路
        之前**的世界；加完之后拖一个 `爆头音效.mp3` 进来会被告知
        「已填入拖入的**压缩包**」，而它根本不是。
        ⭐ 每一层单独看都对，错在层与层之间的假设：新入口加在 `open_source`
        那一层，而说这句话的是页面这一层。
        """
        try:
            from core.resource_import_source import source_noun

            return source_noun(path)
        except Exception:
            import os

            return "文件夹" if os.path.isdir(path) else "文件"

    def dropEvent(self, event):
        # ⚠ 放在最外面：下面每一条出路（收下 / 不是本地文件 / 抛异常）
        #   都得把高亮撤掉，而"每条路各写一遍"正是漏掉一条的写法。
        self._set_drop_highlight(False)
        try:
            import os

            # ⭐ 一次拖进来好几个是常事（一口气选中三个下载好的包）。
            #   这个页面一次只处理一个源 —— 那没问题，**但不许不说**：
            #   默默只导第一个，用户会以为三个都进去了。
            from widgets.drop_import_mixin import urls_from_drop

            dropped = [url.toLocalFile() for url in urls_from_drop(event)]
            dropped = [p for p in dropped if p and (os.path.isdir(p) or os.path.isfile(p))]
            if dropped:
                # ⭐ 目录直接用；**文件也直接用**（多半是刚下载的 zip）。
                # ⛔ 不许再退回"取它所在的目录"——那会去扫用户整个下载文件夹。
                #    认不认得这个文件交给 `open_source`：它按文件头判，
                #    连改名的 RAR 都能说出一句该怎么办的话。
                path = dropped[0]
                self.source_edit.setText(path)
                self.logger.info(f"拖拽导入: {path}（共拖入 {len(dropped)} 个）")
                try:
                    from ui_toast import toast_info

                    # ⚠ 这句话放 toast 不放提示条：提示条紧接着就会被扫描结果
                    #   （`_scan_unified` 那条"导入前请注意"）顶掉，等于没说。
                    extra = ("" if len(dropped) == 1
                             else "（共 %d 个，先处理这一个）" % len(dropped))
                    toast_info(
                        "已填入拖入的%s%s，正在识别…" % (self._drop_noun(path), extra),
                        2400 if len(dropped) == 1 else 4000)
                except Exception:
                    pass
                self._scan_source()
                event.acceptProposedAction()
                return
            # ⚠ 走到这里说明拖进来的东西**不是本地文件**（最常见的是从浏览器
            #   拖了一个下载链接）。原来是一句 `event.ignore()` —— 鼠标显示
            #   「可以放」，放下之后什么都不发生，**也不说一句**。
            # ⭐ 拒绝要看得见：一个没有反应的界面，用户只会再试几次然后放弃。
            try:
                from ui_toast import toast_warning

                toast_warning("拖进来的不是本地文件。请先把资源下载到本地，"
                              "再把下载好的压缩包或文件夹拖进来。", 3600)
            except Exception:
                pass
            event.ignore()
        except Exception:
            self.logger.exception("处理拖拽失败")
            event.ignore()

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
            "导入资源",
            # ⚠ 外审 5 发点到同一件事：这一页叫「导入资源」、管着 17 类
            #   （12 音频 + 5 视觉），而页头到输入框通篇写「音效库 / 音频资源」⇒
            #   手里拿着击杀图标或综合包的玩家会以为进错了页面。
            # ⭐ 第一句先说**能吃什么**，而不是先说流程 —— 玩家最想确认的是
            #   "我手上这个东西这里收不收"。
            description=("压缩包、文件夹，或单个素材文件都能直接拖进来，不用先解压。"
                         "软件先认出它是哪一类（音效、语音、击杀图标、准心…），"
                         "给你看清了再写入 —— 确认之前不动你现有的素材。"),
            title_font_size=None,
            spacing=12,
        )
        self.page_lead_label = header.description_label
        layout.addWidget(header)
        # ⚠ 批 45（RN-001b）：只往 `PAGE_HELP_TEXTS` 加一段是不够的 ——
        #   那颗「?」要每页自己装，否则表里有、屏幕上没有。
        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["audio_import_wizard"])

        card, card_layout = SettingsCard.make("当前状态")
        self.status_card = card

        self.status_badge_label = create_badge_label()
        card_layout.addWidget(self.status_badge_label)
        self.summary_label = QLabel("请先选择素材并扫描。")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("hintLabel")
        self.summary_label.hide()
        card_layout.addWidget(self.summary_label)
        layout.addWidget(card)

        # ⭐⭐ RN-508（2026-09-05 批 48）：外审 3 发逐字报「虽叫向导却无分步流程」。
        #   这一页**确实是三步**（选目录 → 扫描 → 确认后导入），页头那句话也是这么写的，
        #   只是屏幕上没有任何地方说得出「我现在在第几步」。
        # ⛔ 没有去重排布局（那几颗按钮参与 `actions_row` 的紧凑模式响应式切换，
        #   动它要另一轮审查）。⇒ 先把**步骤显式化**：卡片标题就是步骤名。
        #   哪一步是"当下该做的"仍由 `_sync_first_step()` 按状态定（批 46 的裁定）。
        controls_card, controls_layout = SettingsCard.make(
            # ⚠ 标题里**不许有 `·` 或 `：`**：搜索索引把「X · Y」「X：Y」当成
            #   状态条文案整条丢掉（`_STATUS_COMPOSITE` / `_STATUS_LABELED`），
            #   逗号同理（`_SENTENCE`）。第一版写成「第 1 步 · 选目录，然后扫描」，
            #   索引里这一页的卡片标题**一条都不剩**，判据当场点名（批 40 同族）。
            "第 1 步 选中素材并扫描",
            "扫描只看不写，不会动你现有的素材。压缩包不用先解压。"
            "导入模式和「只预演」都在这一步定。",
        )

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_label = QLabel("素材来源")
        source_label.setMinimumWidth(64)
        source_row.addWidget(source_label)

        self.source_edit = QLineEdit()
        self.source_edit.setMinimumHeight(34)
        source_row.addWidget(self.source_edit, 1)
        # ⚠ 占位文案**只有一处真源**（`_source_placeholder`），且要等
        #   `mode_combo` 建好才取得到模式名 ⇒ 在下面那一行统一设。

        # ⭐ 2026-09-16：社区站下下来的是 `资源标题.zip`，而旧向导只收目录 ——
        #   用户得先自己解压一次，那一次解压正是"导入很麻烦"的起点。
        # ⚠ 这颗放在**源行**（和「选择文件夹」并列，同属"选什么"），不放动作行：
        #   那一行五颗按钮在紧凑档已经装不下，UP-100 为此分过两组。
        # ⭐⭐ RN-674：它排在「选择文件夹」**前面**，开局也由它当主按钮。
        # ⛔ 不合并成一个入口（RN-667 已裁定：合并会重演 RN-185）。
        # ⚠ 焦点链走**构造顺序**（`tab_order_audit.py`）⇒ 真挪到前面建，不是只调 addWidget。
        self.browse_archive_btn = QPushButton("选择压缩包 / 文件…")
        self.browse_archive_btn.setObjectName("secondaryButton")
        self.browse_archive_btn.setMinimumHeight(34)
        self.browse_archive_btn.clicked.connect(self._choose_source_archive)
        source_row.addWidget(self.browse_archive_btn)

        self.browse_btn = browse_btn = QPushButton("选择文件夹")
        browse_btn.setObjectName("secondaryButton")
        browse_btn.setMinimumHeight(34)
        browse_btn.clicked.connect(self._choose_source_dir)
        source_row.addWidget(browse_btn)

        # ⭐ 页内提示条取代弹窗：一次导入可能连着有三种话要说
        #   （认出了几类 / 有几条不会响 / 冲突跳过几个），
        #   三个弹窗排队点过去，用户会把最后一个也当成"确定"点掉。
        self.notice_bar = PageNoticeBar(self)
        controls_layout.addLayout(source_row)
        controls_layout.addWidget(self.notice_bar)

        options_row = QHBoxLayout()
        options_row.setSpacing(8)
        options_row.addWidget(QLabel("导入模式"))

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("音频", "audio")
        self.mode_combo.addItem("视觉", "visual")
        self.mode_combo.addItem("全部", "all")
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.setMinimumHeight(34)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        options_row.addWidget(self.mode_combo, 0)

        self.dry_run_checkbox = QCheckBox("仅生成建议（不复制文件）")
        self.dry_run_checkbox.setChecked(False)
        options_row.addWidget(self.dry_run_checkbox)
        options_row.addStretch()
        controls_layout.addLayout(options_row)

        # ⚠ 位置就得在这儿：`_source_placeholder()` 要读 `mode_combo`。
        self.source_edit.setPlaceholderText(self._source_placeholder())

        # UP-100: 原本是一个 QHBoxLayout 平铺 5 个按钮。五个按钮的 sizeHint 合计
        # 实测 967(x1.0) / 996(x1.1) / 1062(x1.25) px，而紧凑模式（860×640）的
        # 内容视口只有 854px —— 三个按钮的文案被打省略号（「一键导入（保守）」
        # 可用区 121px 需 128px 等，8/24 个主题×字号组合命中）。
        #
        # 改成两组：outer 是 QBoxLayout，横排时 [扫描/导入/归类][打开源/打开资源]
        # 两个子行并排，内外间距都是 8 —— 与改之前的单行**逐像素相同**；
        # 装不下时 outer 竖过来，变成两行。分组本身也讲得通：前三个是"干活"，
        # 后两个是"打开目录"。
        actions = QBoxLayout(QBoxLayout.LeftToRight)
        actions.setSpacing(8)
        self.actions_row = actions

        # ⭐ 批 46：底栏那颗变身式主按钮撤掉之后，这一屏一颗主按钮都不剩，
        #   外审当场报「按钮平级、无视觉重心」。⇒ 把**第一步**升为主按钮，
        #   且**恒定不变**（不像底栏那颗随状态换词）。这一页的第一步是「扫描目录」：外审 3 发逐字报「玩家想图快直奔一键导入却不知必须先扫描」。
        self.scan_btn = QPushButton("扫描素材")
        # ⚠ 主/次由 `_sync_first_step()` 按「选没选源目录」定，不在这里写死 ——
        #   批 46 第一版把「扫描目录」恒定为主，外审 3 发报
        #   「未选目录时『扫描目录』却是唯一高亮，极易诱导玩家开局盲点导致报错」。
        self.scan_btn.setObjectName("secondaryButton")
        # RN-508：「保守」是内部说法。外审 5/6 报「不知道保守会动什么、不敢点」。
        #   ⇒ 按钮上直接写它的安全性质。
        self.import_btn = QPushButton("开始导入（不覆盖已有文件）")
        self.import_btn.setObjectName("secondaryButton")
        # v2.2.1: 未识别文件不再是死胡同——手动归类为新风格
        self.classify_btn = QPushButton("把未识别音频导入为新风格…")
        self.classify_btn.setObjectName("secondaryButton")
        self.classify_btn.setEnabled(False)
        self.open_source_btn = QPushButton("打开来源位置")
        self.open_source_btn.setObjectName("secondaryButton")
        self.open_resource_btn = QPushButton("打开资源目录")
        self.open_resource_btn.setObjectName("secondaryButton")
        for button in (self.scan_btn, self.import_btn, self.classify_btn, self.open_source_btn, self.open_resource_btn):
            button.setMinimumHeight(34)

        # ⭐⭐⭐ RN-508 改完复跑（外审 **6/6 全报同一条**，两档六发）：
        #   「一键导入」原来和「扫描目录」并排放在**第 1 步**里，于是
        #   「第 2 步 看清结果再导入」那句话说完，本区一颗按钮都没有 ——
        #   玩家看完结果得**倒回上一张卡**才找得到导入。
        # ⚠ 我第一版只把这件事写进副标题（「确认无误后点…」），
        #   而版面自述那条判据（RN-077）当场判它违规：**描述版面的文案会随版面腐烂**。
        #   ⇒ 真正的修法不是换句话说，是**把按钮搬到它该在的那一步**。
        # ⛔ 搬不是复制：第 1 步里这两颗**没有留下副本**（RN-102）。
        work_row = QHBoxLayout()
        work_row.setSpacing(8)
        work_row.setContentsMargins(0, 0, 0, 0)
        work_row.addWidget(self.scan_btn)

        open_row = QHBoxLayout()
        open_row.setSpacing(8)
        open_row.setContentsMargins(0, 0, 0, 0)
        open_row.addWidget(self.open_source_btn)
        open_row.addWidget(self.open_resource_btn)

        actions.addLayout(work_row)
        actions.addLayout(open_row)
        actions.addStretch()
        controls_layout.addLayout(actions)
        layout.addWidget(controls_card)

        preview_card, preview_layout = SettingsCard.make(
            "第 2 步 看清结果再导入",
            "这里列出能认出来的、有冲突的和没认出来的条目。"
            "确认无误后再导入。",
        )

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(400)
        # ⭐ RN-520：扫描之前这里是**一整块纯黑**，外审 4/6 报「易误以为卡死」。
        #   一个 400px 高、什么都不说的框，和一个坏掉的框长得一模一样。
        # ⛔ 文案里那个按钮名**从按钮读**，别抄一份（RN-519 的棘轮盯着）。
        # ⭐⭐⭐ 外审 S4 的判断题「玩家会不会知道可以直接拖 zip 进来」
        #   **12 发里 10 发答「绝对不会知道」**，而且几乎每一发都点到同一件事：
        #   「占大半屏的这个空框最像投放区，却只写着『还没有扫描结果』」。
        # ⚠ 而「不用先解压」正是这一整件事要卖的那句话 ——
        #   界面上一个字都没说，等于没做。
        # ⛔ 文案里那个按钮名**从按钮读**，别抄一份（RN-519 的棘轮盯着）。
        # ⭐⭐⭐ RN-674：`setPlaceholderText` 在屏幕上**只画第一行** ⇒ 空状态改写进
        #   **正文**，占位只留那一行。（原来四行占位，后三行一个像素都没有，
        #   而判据一直为它们打绿 —— 叙事见登记册。）
        self.preview_text.setPlaceholderText(self._EMPTY_LEAD)
        self._show_empty_preview()
        # ⭐ 拖拽高亮要能**原样复原** —— 记下底样式，别用 `setStyleSheet("")` 抹。
        self._preview_base_qss = self.preview_text.styleSheet()
        preview_layout.addWidget(self.preview_text)

        # 「确认无误后再导入」——那就把导入放在确认的地方。
        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        import_row.setContentsMargins(0, 0, 0, 0)
        import_row.addWidget(self.import_btn)
        import_row.addWidget(self.classify_btn)
        import_row.addStretch()
        preview_layout.addLayout(import_row)

        layout.addWidget(preview_card)
        layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.action_bar = PageActionBar(self)
        self.action_bar.secondary_btn.setMinimumWidth(116)
        self.action_bar.primary_btn.setMinimumWidth(148)
        root.addWidget(self.action_bar, 0)

        self.scan_btn.clicked.connect(self._scan_source)
        self.import_btn.clicked.connect(self._run_import)
        self.classify_btn.clicked.connect(self._classify_unrecognized)
        self.open_source_btn.clicked.connect(self._open_source_dir)
        self.open_resource_btn.clicked.connect(self._open_resource_dir)
        self.source_edit.textChanged.connect(lambda _text: self._sync_status_strip())
        self.dry_run_checkbox.toggled.connect(lambda _checked: self._sync_status_strip())
        self._sync_status_strip()

    # UP-100: 页宽阈值。实测锚点：紧凑模式页宽 **860**（必须竖排——那一档实测
    # 三个按钮的文案被打省略号）；完整模式页宽 **1000**（窗口 1200，CI 与页面指纹
    # 都用这一档）与 **1080**（窗口 1280）必须保持横排。取 960 = 两个锚点之间，
    # 下留 100px、上留 40px 余量。
    #
    # ⚠ 这里先写过一版"实测法"——量五个按钮的 `minimumSizeHint()` 合计（967/996/
    # 1062px 三档）跟可用宽比，想着自带字号缩放不变性。它**判过头了**：
    # 在 1200×800（可用约 946px）下就换成了竖排，而那一档排版审计明明是绿的。
    # 原因是 `minimumSizeHint` 里含 QSS 的 padding，padding 被压缩不等于文字被裁——
    # **判据必须对准缺陷本身**。页面指纹当场逮住了这次判过头（16 个控件挪位）。
    _ACTIONS_ROW_MIN_WIDTH = 960

    def _update_actions_layout(self):
        """窄到装不下时，把动作行的两组按钮从并排改成上下两行（UP-100）。"""
        row = getattr(self, "actions_row", None)
        if row is None:
            return
        direction = (QBoxLayout.TopToBottom
                     if self.width() < self._ACTIONS_ROW_MIN_WIDTH
                     else QBoxLayout.LeftToRight)
        if row.direction() != direction:
            row.setDirection(direction)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_actions_layout()

    def _compact_source_text(self, path: str) -> str:
        source_dir = str(path or "").strip()
        if not source_dir:
            return "未选择"
        name = os.path.basename(source_dir.rstrip("\\/")) or source_dir
        if len(name) > 12:
            name = name[:11] + "…"
        return name

    def _sync_action_bar(self):
        if not hasattr(self, "action_bar"):
            return

        source_dir = self.source_edit.text().strip()
        mode_text = self._mode_text()
        dry_run = bool(self.dry_run_checkbox.isChecked())
        # ⛔ RN-102 / RN-506（2026-09-04 批 46）：底栏这两颗**全是副本**——
        #   「扫描目录」与「导入设置」卡里那颗是同一个方法；而主按钮在
        #   **四种**状态之间换文案（打开资源目录 / 生成建议 / 一键导入（保守）/
        #   打开源目录 / 打开资源目录），四个动作卡内全都有。
        # ⭐⭐ 这是这一族里变身最夸张的一页 —— 同一个位置，四种含义。
        # ⇒ 底栏不放按钮，动作全留「导入设置」卡（它的副标题就是语境）。
        self.action_bar.configure_secondary("", None, visible=False)
        self.action_bar.configure_primary("", None, visible=False)
        self._sync_first_step(bool(source_dir))

        if self._last_import_result:
            summary = self._last_import_result.get("summary", {}) or {}
            copied = int(summary.get("copied_count", 0) or 0)
            skipped = int(summary.get("skipped_conflicts_count", 0) or 0)
            failed = int(summary.get("failed_count", 0) or 0)
            action_message = (
                f"当前模式：{mode_text} · 最近一次{'预演' if dry_run else '导入'}结果 "
                f"{copied}/{skipped}/{failed}，可点上面「{self.open_resource_btn.text()}」继续核对。"
            )
        elif self._scan_report:
            summary = (self._scan_report or {}).get("summary", {}) or {}
            recognized = int(summary.get("recognized_count", 0) or 0)
            conflicts = int(summary.get("conflict_count", 0) or 0)
            action_message = (
                f"当前模式：{mode_text} · 已扫描 {recognized} 个可识别条目、{conflicts} 个冲突；"
                f"下一步可直接{'生成建议' if dry_run else '开始导入'}。"
            )
        elif source_dir:
            action_message = (
                f"当前模式：{mode_text} · 已选中 {self._compact_source_text(source_dir)}，"
                "建议先扫描再决定是否导入。"
            )
        else:
            action_message = f"当前模式：{mode_text} · 先选中素材并扫描，确认识别结果后再执行导入。"
        self.action_bar.set_message(action_message)

    def _sync_first_step(self, has_source: bool):
        """⭐ 那一颗紫的必须是**当下的第一步**（批 44 RN-450 的裁定）。

        没选素材 ⇒ 第一步是「选择压缩包 / 文件…」（RN-674：社区站下下来的就是 zip）；
        选了 ⇒ 是「扫描素材」。
        ⚠ 两个都是**安全动作**（都不写任何文件），在它们之间换不触碰 RN-506 那条线。
        ⭐⭐⭐ RN-450 当年只拿掉了「扫描」的**高亮**，没拿掉「点了报错」——
        按钮一直可点，开局点下去弹一句「请先选择压缩包或目录」。
        ⇒ 真没东西可做时就**禁用**，并在 tooltip 里说清为什么。
        """
        from page_theme_helper import style_as_primary_button, style_as_secondary_button

        first = self.scan_btn if has_source else self.browse_archive_btn
        buttons = (self.scan_btn, self.browse_btn, self.browse_archive_btn)
        for btn in buttons:
            if btn is first:
                style_as_primary_button(btn)
            else:
                style_as_secondary_button(btn)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

        # ⛔ 这两颗**一起动**：它们空点下去是同一个死胡同
        #   （`_run_import` 没报告就自己去 `_scan_source`，撞的是同一句提示）。
        blocked_tip = "" if has_source else "先选中素材（压缩包、文件夹，或单个素材文件），这一步才有东西可做。"
        # ⚠⚠ 外审 S4 **3/3** 报「旁边两颗『打开…』比置灰的扫描更抢眼」——**现象是真的**：
        #   `#secondaryButton:disabled` 是 `background-color: transparent`，禁用之后
        #   屏幕上只剩一行灰字。⛔ 但**这里不修**：RN-150 那条判据逐字定过全站口径
        #   （次按钮启用/禁用都是透明露底，差别在**文字色和边框色**上），
        #   一页一页地改填充是绕开裁定；真要改是主题层的事，得单开一批带外审。
        # ⭐ 我为此串行试了三版（低特异度选择器不生效 → 加底色 → 才发现
        #   `ui_style_applier` 会把控件级样式整个抹掉，除非声明 `fp_keep_style`），
        #   按 §0「同一件事三轮不稳就停」停在这里，已立案。
        for btn in (self.scan_btn, self.import_btn):
            btn.setEnabled(has_source)
            btn.setToolTip(blocked_tip)

    def _sync_status_strip(self):
        source_dir = self.source_edit.text().strip()
        mode_text = self._mode_text()
        dry_run = bool(self.dry_run_checkbox.isChecked())

        badges = [
            ("positive" if source_dir else "warning", f"素材来源 · {self._compact_source_text(source_dir)}"),
            ("info", f"模式 · {mode_text}"),
            ("info" if dry_run else "positive", f"策略 · {'只预演' if dry_run else '不覆盖已有'}"),
        ]

        if self._last_import_result:
            summary = self._last_import_result.get("summary", {}) or {}
            copied = int(summary.get("copied_count", 0) or 0)
            skipped = int(summary.get("skipped_conflicts_count", 0) or 0)
            failed = int(summary.get("failed_count", 0) or 0)
            badges.append(("positive" if failed == 0 else "warning", f"结果 · {copied}/{skipped}/{failed}"))
            detail_text = (
                f"当前使用“{mode_text}”模式，"
                f"{'只做预演，不写入文件' if dry_run else '导入时不覆盖已有文件'}。"
                f"最近一次执行结果：成功 {copied}，冲突跳过 {skipped}，失败 {failed}。"
            )
        elif self._scan_report:
            summary = (self._scan_report or {}).get("summary", {}) or {}
            recognized = int(summary.get("recognized_count", 0) or 0)
            conflicts = int(summary.get("conflict_count", 0) or 0)
            unrecognized = int(summary.get("unrecognized_count", 0) or 0)
            badges.append(("positive" if recognized > 0 else "warning", f"扫描 · {recognized}/{conflicts}"))
            detail_text = (
                f"当前使用“{mode_text}”模式，已完成扫描。"
                f"识别 {recognized} 项，冲突 {conflicts} 项，未识别 {unrecognized} 项。"
            )
        else:
            badges.append(("warning" if source_dir else "info", "结果 · 待扫描"))
            detail_text = (
                f"当前使用“{mode_text}”模式，"
                f"{'只做预演，不写入文件' if dry_run else '导入时不覆盖已有文件'}。"
                "先选中素材并扫描，再决定是否导入。"
            )

        render_badges(self.status_badge_label, badges, detail_tooltip=detail_text)
        self.summary_label.setToolTip(detail_text)
        self.status_card.setToolTip(detail_text)
        self._sync_action_bar()

    def _choose_source_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择要导入的资源目录",
            self.source_edit.text().strip() or os.path.expanduser("~"),
        )
        if directory:
            self.source_edit.setText(directory)
            self._scan_source()

    def _choose_source_archive(self):
        """选一个压缩包**或单个素材文件**。

        ⚠ 过滤器写 zip，但**认格式不看扩展名** —— 改名的 RAR 会在
        `open_source` 里被文件头认出来并给一句人话。
        ⚠⚠ 外审点出来的一条：单个素材文件**只能拖进来，没有选取入口** ——
        而"从群里存下来一个 mp3"是玩家最常见的情形之一，
        ⭐ 一个只能拖、不能选的入口，对不用拖拽的用户等于不存在。
        """
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择压缩包或单个素材文件",
            self.source_edit.text().strip() or os.path.expanduser("~"),
            "资源包与素材 (*.zip *.mp3 *.wav *.ogg *.png *.jpg *.jpeg *.xchr);;"
            "压缩包 (*.zip);;所有文件 (*.*)",
        )
        if path:
            self.source_edit.setText(path)
            self._scan_source()

    def _open_import_source(self):
        """把输入框里那个路径打开成导入源。失败就地报错并返回 None。

        ⚠ 解压走**后台线程**（大包在 UI 线程上解会把界面冻住，
        而冻多久由用户的素材大小决定）。这里用一个局部事件循环等它，
        期间界面照常重绘、「取消」照常响应。
        """
        raw = self.source_edit.text().strip()
        if not raw:
            QMessageBox.information(self, "提示", "请先选择压缩包或目录。")
            return None

        holder = {}

        def work(progress, should_cancel):
            holder["source"] = open_source(
                raw, progress=progress, should_cancel=should_cancel)
            return holder["source"]

        ok = self._run_in_background(work, "正在读取资源包")
        if not ok:
            return None
        return holder.get("source")

    def _run_in_background(self, work, label) -> bool:
        """跑一段后台活，期间显示进度、允许取消。返回 True=成功。

        ⭐ 线程模型复用击杀图标那条已经验证过的线（`KillIconImportTask`），
        它接受调用方自己的异常类 ⇒ 这里的取消/失败语义原样保留。
        """
        from PySide6.QtCore import QEventLoop

        task = KillIconImportTask(self)
        loop = QEventLoop(self)
        state = {"ok": False, "error": "", "cancelled": False}

        progress_box = QProgressDialog(label, "取消", 0, 0, self)
        progress_box.setWindowModality(Qt.WindowModal)
        # ⛔ 不许它自己弹出来（CLAUDE.md §3：跑测试/审计时不弹真窗口）——
        #   只有真的花了时间才显示。
        progress_box.setMinimumDuration(400)
        progress_box.setAutoClose(False)
        progress_box.setAutoReset(False)
        progress_box.canceled.connect(task.cancel)

        def on_progress(done, total, stage):
            if total > 0:
                progress_box.setMaximum(total)
                progress_box.setValue(done)
            progress_box.setLabelText(f"{label}\n{stage}")

        def on_finished(_result):
            state["ok"] = True
            loop.quit()

        def on_failed(message):
            state["error"] = str(message)
            loop.quit()

        def on_cancelled():
            state["cancelled"] = True
            loop.quit()

        task.progress.connect(on_progress)
        task.finished.connect(on_finished)
        task.failed.connect(on_failed)
        task.cancelled.connect(on_cancelled)

        started = task.start(work, label,
                             cancelled_exc=ImportCancelled,
                             error_exc=ImportSourceError)
        if not started:
            return False
        loop.exec()
        progress_box.close()

        if state["cancelled"]:
            return False
        if state["error"]:
            # ⭐ 这里的消息是**能照着做**的（"这是 RAR，请先解压"），直接展示。
            QMessageBox.warning(self, "打不开这个资源", state["error"])
            return False
        return state["ok"]

    def _decide_groups(self, source):
        """识别 → 拿不准就问一次 → 决定清单。用户取消返回 None。"""
        # ⭐ 业务逻辑在 core（`prepare_decisions`）——页面只负责"问"这一步。
        # ⚠ 模式（音频 / 视觉 / 全部）以前**没传进去** ⇒ 那个下拉框不起作用，
        #   选「视觉」照样把音频整包导进去。⭐ 不起作用的控件比没有还糟。
        prepared = prepare_decisions(source, self._current_mode())
        self._domain_skipped = list(prepared.get("skipped_by_domain") or [])
        if not prepared["groups"]:
            return []
        decided = prepared["decided"]
        manifest_style = str(prepared["default_style"])
        unsure = prepared["unsure"]
        if not unsure:
            return decided

        from dialogs.resource_import_decision_dialog import (
            ResourceImportDecisionDialog,
        )

        dialog = ResourceImportDecisionDialog(
            unsure, parent=self, default_style_name=manifest_style)
        if dialog.exec() != QDialog.Accepted:
            return None
        picked = dialog.decisions()
        # ⭐ 记下这一次的选择：同样结构的素材下次不再问。
        #   ⚠ 只记问过的那几组（`unsure`），顺序与对话框里的一一对应。
        remember_decisions(unsure, picked)
        return decided + picked

    def _scan_unified(self):
        """统一扫描：压缩包与目录同一条路。

        ⭐ 新链路的 `certain` 档**就是**旧规则（路径里带 spec 目录名），
        所以规范包的行为与改之前一致；只有认不出的才多一次确认。

        ⛔⛔ **不管从哪条路退出，都必须先把上一次的报告作废**（见下面第一行）。
        端到端实测逮到的：导完一个包，再喂一个 `.tar.gz`，它被正确拒绝、
        错误也弹了 —— 而紧接着"导入"却报「导入完成：成功 1」，
        **把上一个包又导了一遍**（落到另一个风格目录里）。
        ⭐⭐⭐ 每一层单独看都对：拒绝是对的、报错是对的、导入也照着报告干了活；
        错在**报告的寿命没有跟源绑定**。这一刀单元判据一条都没红。
        """
        # ⚠ 位置就得在这儿 —— 在任何一个 `return` 之前。
        self._invalidate_scan()
        # ⭐ 提示条也要归零：实测里 `.tar.gz` 被正确拒绝之后，条上仍写着
        #   上一次的「导入完成：成功 1」—— 一句过期的好消息压在一条错误上面。
        # ⛔ 这一句不许搬进 `_invalidate_scan()`：撤销那条路是先 `show_message`
        #   再作废报告，搬进去会把「已撤销」当场擦掉。
        self.notice_bar.clear()
        source = self._open_import_source()
        if source is None:
            return
        try:
            decisions = self._decide_groups(source)
            if decisions is None:      # 用户在确认框里取消
                return
            if not decisions:
                QMessageBox.information(
                    self, "没有可导入的内容",
                    "这个包里没有认得出来的资源文件。")
                return
            report = plan_from_decisions(source, decisions, self.resources_root)
            self._scan_report = report
            self._scan_report_source = self.source_edit.text().strip()
            self._last_import_result = None
            self._render_report(report)
            warnings = [str(line) for line in (report.get("warnings") or [])]
            skipped = len(getattr(self, "_domain_skipped", []) or [])
            if skipped:
                # ⭐ 被「导入模式」挡掉的也要说：用户看到"成功 0"而不知道为什么，
                #   比报一句错还难受。
                warnings.insert(0, (
                    f"当前模式是「{self._mode_text()}」，"
                    f"包里有 {skipped} 组不属于这一类的素材没有导入 —— "
                    f"要一起导就把模式切到「全部」再扫一次"))
            aside = self._aside_notice(source)
            if aside:
                # ⭐ 摘出来没导入的那些**必须讲出来** —— 悄悄扔掉别人的文件，
                #   和悄悄把垃圾导进资源库一样不该。位置是"结果可见"，不是弹窗。
                warnings.insert(0, aside)
            if warnings:
                # ⭐ 仿击杀图标「缺等级只提示不拦」：这些是"装进去了但不会响"，
                #   要在**落盘之前**讲出来。
                # ⚠ 合成一条说 —— 几条分别弹窗，后面几条必然被连点掉。
                self.notice_bar.show_message("导入前请注意：" + "；".join(warnings))
        finally:
            # ⚠ 报告里存的是**绝对路径**，指向临时解压目录 ——
            #   所以清理必须等到真正落盘之后，见 `_run_import`。
            self._pending_source = source

    @staticmethod
    def _aside_notice(source) -> str:
        """包里**没有导入**的那些东西，说一句。

        ⚠ 两类分开说，因为用户要做的事不一样：
        - 作者的附带文件（`说明.txt` / 封面图）**点名** —— 他可能想自己留着；
        - 系统临时文件（`__MACOSX/` / `Thumbs.db`）**只报个数** ——
          对它们没有任何决定要做，点名只是噪声。
        """
        import os as _os

        companions = [str(p) for p in (getattr(source, "companions", None) or [])]
        junk = int(getattr(source, "junk_count", 0) or 0)
        parts = []
        if companions:
            shown = "、".join(_os.path.basename(p) for p in companions[:3])
            more = f"等 {len(companions)} 个文件" if len(companions) > 3 else ""
            parts.append(f"包里的 {shown}{more} 不是素材，没有导入")
        if junk:
            parts.append(f"另丢掉 {junk} 个系统临时文件")
        return "；".join(parts)

    # ⚠ 第一行单独拎出来：`setPlaceholderText` 只画得出这一行，
    #   所以占位与正文共用它，谁也不会比谁多说一句（RN-674）。
    # ⚠⚠ 这一行**必须自成一句完整的话**，后面紧跟空行：紧凑档（860×640）里
    #   第 2 步那张卡只露得出一行多一点，切口落在哪由字号档决定 ——
    #   ⭐ 第一版把「扫描只看不写」另起一行，外审 S3 **3/3 报「高」**：
    #     那一行被底栏**切成两半**，字符残缺。切口躲不掉，能选的只有
    #     **让它落在空行上**。
    # ⛔ 也不许把那句话并进这一行凑长度：紧挨着的第 1 步副标题**逐字说过**，
    #   外审 S4 3/3 报「同一句话在三四处反复说教，反而淹没了操作入口」。
    _EMPTY_LEAD = "把压缩包、文件夹，或单个素材文件直接拖到这里 —— 不用先解压。"

    def _show_empty_preview(self):
        """第 2 步那个框在扫描之前该说的话 —— 写进**正文**。

        ⛔ 点名的按钮名一律**从按钮读**，不许抄一份（RN-519 的棘轮盯着）。
        ⛔ 不许改回 `setPlaceholderText` 的多行写法：那样只有第一行看得见。
        """
        self.preview_text.setPlainText(
            f"{self._EMPTY_LEAD}\n\n"
            f"也可以点上面的「{self.browse_archive_btn.text()}」"
            f"或「{self.browse_btn.text()}」选一个，再点「{self.scan_btn.text()}」。\n\n"
            f"扫描之后这里会列出：能认出来的、有冲突的、没认出来的条目各多少；"
            f"扫描只看不写，确认之前不动你现有的素材。")

    def _source_placeholder(self) -> str:
        """源输入框的占位文案 —— **唯一真源**（原来两处各写一遍）。

        ⛔ RN-674：这一句**不许再自称投放区**（原文尾巴是「也可以直接拖进来」）。
        投放区只有一个 —— 第 2 步那个框，而且它拖上去真会亮。
        """
        return f"压缩包、文件夹，或单个{self._mode_text()}素材文件的路径"

    def _current_mode(self) -> str:
        return str(self.mode_combo.currentData() or "audio")

    def _mode_text(self) -> str:
        return str(self.mode_combo.currentText() or "音频")

    def _on_mode_changed(self):
        mode_text = self._mode_text()
        # ⚠ 这一行原来把源输入框的提示改回「请选择包含 X 资源的**根目录**」——
        #   等于一换模式就把"能拖 zip / 能选单文件"这件事又藏起来了。
        #   ⭐ 同一句话在两处各写一遍，改了一处等于没改 ⇒ RN-674 抽成
        #     `_source_placeholder()`，这里和 `_init_ui` 都只调它。
        self.source_edit.setPlaceholderText(self._source_placeholder())
        self._invalidate_scan()
        self._last_import_result = None
        self.summary_label.setText(f"当前模式：{mode_text}。请选择目录并扫描。")
        # ⚠ 原来是 `clear()` —— 换个模式，那个 400px 的框就又变回一整块纯黑，
        #   RN-520 修掉的东西原地复活（它当年只修了**开局**那一次）。
        self._show_empty_preview()
        self._sync_status_strip()

    def _scan_source(self):
        """⭐ 2026-09-16 起统一走 `_scan_unified`。

        新链路的 `certain` 档**就是**旧规则（路径里带 spec 目录名），
        规范包的行为与改之前一致；多出来的只有"认不出时问一次"。
        ⚠ 旧的 `scan_resource_import_candidates` 没有删 ——
        它是个纯函数，判据 `test_resource_import_wizard.py` 直接测它。
        """
        self._scan_unified()

    def _invalidate_scan(self):
        """把上一次的扫描报告作废。

        ⭐ 报告里存的是**那一个源**的绝对路径清单，所以它的寿命不能超过那个源。
        """
        self._scan_report = None
        self._scan_report_source = ""

    def _scan_is_stale(self) -> bool:
        """手上这份报告**还算不算数**。

        ⭐ 报告里存的是那一个源的绝对路径清单，所以它只对**当时那个路径**有效。
        改了路径却不重扫就点导入，导进去的是上一个包 —— 而界面上看不出任何异样。
        """
        if not self._scan_report:
            return False        # 没有报告不叫"过期"，叫"还没扫"
        return self._scan_report_source != self.source_edit.text().strip()

    def _run_import(self):
        if self._scan_is_stale():
            self._invalidate_scan()
        if not self._scan_report:
            self._scan_source()
            if not self._scan_report:
                return

        dry_run = bool(self.dry_run_checkbox.isChecked())
        if not dry_run and bool(getattr(config, "config_snapshot_auto_before_risky_ops", True)):
            try:
                from core.config_snapshot_manager import create_snapshot, prune_snapshots

                create_snapshot("resource_import_wizard")
                prune_snapshots(int(getattr(config, "config_snapshot_max_keep", 20) or 20))
            except Exception as exc:
                self.logger.warning(f"导入前自动快照失败: {exc}")

        # ⚠ 真正逐文件 `shutil.copy2` 的是这一步 —— 一个几百兆的包在 UI 线程上
        #   复制会把界面冻住，而冻多久由用户的素材大小决定。⇒ 也走后台。
        holder = {}

        def work(progress, should_cancel):
            # ⚠⚠ `progress` / `should_cancel` 原来**拿到了却一次都没用** ——
            #   写盘阶段点「取消」：进度框消失、界面解锁，而复制照常跑完
            #   并报「导入完成」。⭐ 一个点下去什么都不会发生的取消键，
            #   比没有取消键更糟。
            holder["result"] = apply_resource_import_plan(
                self._scan_report,
                dry_run=dry_run,
                overwrite_existing=False,
                progress=progress,
                should_cancel=should_cancel,
            )
            progress(1, 1, "已写入资源目录")
            return holder["result"]

        if not self._run_in_background(work, "正在写入资源目录"):
            return
        result = holder.get("result")
        if result is None:
            return
        self._last_import_result = result
        # ⚠ 临时解压目录只能在**落盘之后**清 —— 报告里存的是指向它的绝对路径。
        #   ⭐ 不清的代价是每导一个包在 `%TEMP%` 留一份副本，慢慢把盘填满。
        pending = getattr(self, "_pending_source", None)
        if pending is not None and not dry_run:
            pending.cleanup()
            self._pending_source = None

        if (
            not dry_run
            and result.get("summary", {}).get("copied_count", 0) > 0
            and any(str(item.get("domain", "")) == "audio" for item in result.get("copied", []) or [])
        ):
            try:
                submit_import_refresh_task("audio_import_wizard")
            except Exception as exc:
                self.logger.warning(f"导入后重扫失败: {exc}")

        copied = result.get("summary", {}).get("copied_count", 0)
        skipped = result.get("summary", {}).get("skipped_conflicts_count", 0)
        failed = result.get("summary", {}).get("failed_count", 0)
        mode_text = "建议预演完成" if dry_run else "导入完成"
        rolled = (result.get("rollback") or {}).get("rolled_back")
        parts = [f"{mode_text}：成功 {copied}"]
        # ⭐⭐ 「我们替用户动了他的文件」这件事必须**活到最后一条消息里**。
        #   实测：重命名的提示是在扫描那一步挂上去的，而导入结果紧接着把提示条
        #   整条顶掉 —— 于是文件被改了名，而用户从头到尾没看见过一个字。
        # ⛔ 只带"我们做了什么"，不带"你该注意什么"：后者在扫描那步已经看过，
        #   全带上会把这条消息撑成一段没人读的长文。
        did = [line for line in (self._scan_report or {}).get("warnings", []) or []
               if "替你重命名" in str(line) or "没有导入" in str(line)]
        parts.extend(str(line) for line in did[:2])
        if skipped:
            parts.append(f"冲突跳过 {skipped}（同名的旧素材没被覆盖）")
        if failed:
            parts.append(f"失败 {failed}")
        if result.get("cancelled"):
            # ⭐ 取消不是失败，但**必须说清停在哪** —— 已经写进去的那些还在。
            parts.insert(0, "已取消（前面写进去的还在，可以点撤销收回）")
        if rolled:
            # ⭐ 回滚发生过就要说 —— 不说的话用户以为"失败几个"是"其余都进去了"。
            stuck = int((result.get("rollback") or {}).get("stuck_count", 0) or 0)
            if stuck:
                # ⚠ 回滚**自己也会失败**。原来这里无条件说"没有留下半套素材"，
                #   而删不掉的那几个还躺在资源库里 ——
                #   ⭐ 一句不成立的保证比不给保证更坏。
                parts.append(
                    f"这一次已收回大部分，但有 {stuck} 个删不掉"
                    f"（多半正被别的程序占用），资源目录里还留着它们")
            else:
                parts.append("这一次已整体收回，资源目录没有留下半套素材")
        # ⭐ 撤销只在**真写了东西**的时候给：一个点下去什么都不会发生的按钮，
        #   比没有还糟。
        can_undo = bool(copied) and not dry_run and not rolled

        # ⛔⛔ 这里原来是 `if not dry_run: self._scan_source()` —— **导完立刻重扫**。
        #   三路审计各自独立发现，沙箱端到端也复现了它的三重代价：
        #   ① `_scan_unified` 第一件事是 `notice_bar.clear()` ⇒
        #      **「导入完成」和「撤销」当场被自己擦掉**，提示条上一片空白，
        #      撤销按钮用户根本点不到 —— 上一轮做的撤销功能等于不存在；
        #   ② 重扫的结果必然是"全是冲突"（文件刚落进去），屏幕上一片红，
        #      而那是**导入成功**的表现，看起来却像失败；
        #   ③ 拿不准的包会**再弹一次确认框**，且整包再解压一遍。
        # ⭐⭐⭐ 我上一轮的沙箱测试之所以"通过"，是因为脚本直接点了那个
        #   已经被隐藏的按钮 —— **能用代码点到，不等于用户点得到。**
        # ⇒ 先把这一次的结果画出来，再把报告作废（下次点导入自然会重扫）。
        self._render_report(self._scan_report, result)
        if not dry_run:
            self._invalidate_scan()
        self.notice_bar.show_message(
            "；".join(parts),
            undo_callback=(lambda: self._undo_last_import(result)) if can_undo else None,
        )

    def _undo_last_import(self, import_result):
        """把刚导进去的收回来。⭐ 走 core 的 `undo_import` ——
        它和"失败自动回滚"是同一个函数，两条路不会各自漂。"""
        outcome = undo_import(import_result)
        removed = int(outcome["summary"]["removed_count"])
        failed = int(outcome["summary"]["failed_count"])
        if failed:
            # ⚠ 点名按钮要**从按钮上读**，不能写死 —— 按钮改了名，
            #   这句话会静静地指向一个不存在的东西（判据 RN：文案点名按钮那条）。
            self.notice_bar.show_message(
                f"撤销了 {removed} 个文件，还有 {failed} 个删不掉"
                "（可能正被别的程序占用）。剩下的可以点"
                f"「{self.open_resource_btn.text()}」自己清。")
        else:
            self.notice_bar.show_message(f"已撤销，{removed} 个文件放回去了。")
        self._last_import_result = None
        self._invalidate_scan()
        self._sync_status_strip()

    def _unrecognized_audio_files(self) -> list[str]:
        """当前扫描结果中未识别、且确为音频的文件（按文件名自然排序）。"""
        from core.audio.audio_file_utils import is_audio_filename

        items = (self._scan_report or {}).get("unrecognized", []) or []
        paths = [
            str(item.get("source_path", ""))
            for item in items
            if item.get("source_path")
            and os.path.isfile(str(item.get("source_path", "")))
            and is_audio_filename(os.path.basename(str(item.get("source_path", ""))))
        ]

        def natural_key(path: str):
            import re

            name = os.path.basename(path).lower()
            return [int(seg) if seg.isdigit() else seg for seg in re.split(r"(\d+)", name)]

        return sorted(paths, key=natural_key)

    def _classify_unrecognized(self):
        """v2.2.1: 把未识别音频手动归类为新风格——选类别→复用新建风格向导自动改名落盘。"""
        files = self._unrecognized_audio_files()
        if not files:
            QMessageBox.information(self, "提示", "当前没有可归类的未识别音频文件，请先扫描目录。")
            return

        from PySide6.QtWidgets import QInputDialog

        from core.audio.style_creator import CATEGORY_TEMPLATES
        from dialogs.style_creator_dialog import StyleCreatorDialog
        from pages.kill_sound_page import KillSoundPage

        labels = {tpl.label: key for key, tpl in CATEGORY_TEMPLATES.items()}
        label, ok = QInputDialog.getItem(
            self,
            "选择音效类别",
            f"找到 {len(files)} 个未识别音频。\n它们属于哪类音效？（将按文件名顺序自动映射）",
            list(labels.keys()),
            0,
            False,
        )
        if not ok or not label:
            return

        category = labels[label]
        template = CATEGORY_TEMPLATES[category]
        selected = files[: template.max_files]
        if len(files) > template.max_files:
            if template.max_files > 1:
                hint = (
                    f"{template.label}最多 {template.max_files} 个文件，"
                    f"已按文件名顺序取前 {template.max_files} 个；其余可再次点击本按钮分批归类。"
                )
            else:
                hint = f"{template.label}只需 1 个文件，已取排序后的第 1 个；其余可再次归类。"
            QMessageBox.information(self, "提示", hint)

        dialog = StyleCreatorDialog(
            category,
            self,
            weapons=KillSoundPage.WEAPON_NAMES,
            initial_files=selected,
        )
        dialog.style_created.connect(lambda name, weapon: self._on_manual_classified(name, weapon, category))
        dialog.exec()

    def _on_manual_classified(self, style_name: str, weapon: str, category: str):
        try:
            submit_import_refresh_task("audio_import_wizard_manual")
        except Exception as exc:
            self.logger.warning(f"手动归类后重扫失败: {exc}")
        self.logger.info(f"手动归类完成: category={category}, style={style_name}, weapon={weapon or '全局'}")
        # 重新扫描以更新未识别列表（已归类的文件仍在源目录，但用户已明确处理过）
        self._scan_source()

    def _open_source_dir(self):
        source_dir = self.source_edit.text().strip()
        if not source_dir:
            QMessageBox.information(self, "提示", "请先选择源目录。")
            return
        self._open_path(source_dir)

    def _open_resource_dir(self):
        os.makedirs(self.resources_root, exist_ok=True)
        self._open_path(self.resources_root)

    def _open_path(self, path: str):
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:
            QMessageBox.warning(self, "打开失败", f"无法打开目录：{exc}\n{path}")

    def _render_report(self, report: dict, import_result: dict | None = None):
        summary = (report or {}).get("summary", {})
        mode_text = self._mode_text()
        self.summary_label.setText(
            f"扫描完成（{mode_text}）："
            f"资源文件 {summary.get('scanned_resource_files', 0)}，"
            f"可识别 {summary.get('recognized_count', 0)}，"
            f"冲突 {summary.get('conflict_count', 0)}，"
            f"未识别 {summary.get('unrecognized_count', 0)}"
        )

        lines = []
        lines.append("[导入向导扫描结果]")
        lines.append(f"源目录: {report.get('source_dir', '')}")
        lines.append(f"导入模式: {report.get('domain', self._current_mode())}")
        lines.append(f"目标目录: {report.get('resources_root', '')}")
        lines.append(
            "统计: "
            f"扫描资源={summary.get('scanned_resource_files', 0)}, "
            f"可识别={summary.get('recognized_count', 0)}, "
            f"冲突={summary.get('conflict_count', 0)}, "
            f"未识别={summary.get('unrecognized_count', 0)}"
        )
        lines.append("")

        recognized = report.get("recognized", []) or []
        lines.append(f"[可识别文件] {len(recognized)}")
        for item in recognized[:80]:
            tag = "冲突" if item.get("conflict") else "可导入"
            spec_label = str(item.get("spec_label", item.get("spec_key", "")) or "").strip()
            lines.append(
                f"- [{tag}] {spec_label}: {item.get('source_path', '')} -> {item.get('target_rel_path', '')}"
            )
        if len(recognized) > 80:
            lines.append(f"... 其余 {len(recognized) - 80} 条已省略")

        unrecognized = report.get("unrecognized", []) or []
        lines.append("")
        lines.append(f"[未识别文件] {len(unrecognized)}")
        for item in unrecognized[:80]:
            lines.append(f"- {item.get('source_path', '')}（{_translate_reason(item.get('reason', ''))}）")
        if len(unrecognized) > 80:
            lines.append(f"... 其余 {len(unrecognized) - 80} 条已省略")
        if unrecognized:
            lines.append(_STRUCTURE_GUIDE)
        # 手动归类按钮随扫描结果联动
        if hasattr(self, "classify_btn"):
            self.classify_btn.setEnabled(bool(self._unrecognized_audio_files()))

        if import_result:
            import_summary = import_result.get("summary", {})
            lines.append("")
            lines.append("[最近一次执行]")
            lines.append(f"模式: {'建议预演' if import_result.get('dry_run') else '实际导入'}")
            lines.append(
                "结果: "
                f"成功={import_summary.get('copied_count', 0)}, "
                f"冲突跳过={import_summary.get('skipped_conflicts_count', 0)}, "
                f"失败={import_summary.get('failed_count', 0)}"
            )

        self.preview_text.setPlainText("\n".join(lines))
        self._sync_status_strip()
