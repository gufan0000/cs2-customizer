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
        self._scan_report = None
        self._last_import_result = None
        self._init_ui()
        # 对标主流：把文件夹/音频文件直接拖进页面即可填入并扫描
        self.setAcceptDrops(True)

    # ---------------- 拖拽导入（对标修缮） ----------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        try:
            import os

            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if not path:
                    continue
                # ⭐ 目录直接用；**文件也直接用**（多半是刚下载的 zip）。
                # ⛔ 不许再退回"取它所在的目录"——那会去扫用户整个下载文件夹。
                #    认不认得这个文件交给 `open_source`：它按文件头判，
                #    连改名的 RAR 都能说出一句该怎么办的话。
                if os.path.isdir(path) or os.path.isfile(path):
                    self.source_edit.setText(path)
                    self.logger.info(f"拖拽导入: {path}")
                    try:
                        from ui_toast import toast_info

                        toast_info(
                            "已填入拖入的%s，正在识别…"
                            % ("文件夹" if os.path.isdir(path) else "压缩包"),
                            2400)
                    except Exception:
                        pass
                    self._scan_source()
                    event.acceptProposedAction()
                    return
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
            description="先扫描外部素材、看清识别成了什么，确认无误再写入资源目录 —— 确认之前不动你现有的音效库。",
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
        self.summary_label = QLabel("请先选择目录并扫描。")
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
            "第 1 步 选目录并扫描",
            "扫描只看不写，不会动你现有的音效库。导入模式和「只预演」都在这一步定。",
        )

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_label = QLabel("源目录")
        source_label.setMinimumWidth(64)
        source_row.addWidget(source_label)

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("请选择包含音频资源的根目录")
        self.source_edit.setMinimumHeight(34)
        source_row.addWidget(self.source_edit, 1)

        self.browse_btn = browse_btn = QPushButton("选择目录")
        browse_btn.setObjectName("secondaryButton")
        browse_btn.setMinimumHeight(34)
        browse_btn.clicked.connect(self._choose_source_dir)
        source_row.addWidget(browse_btn)

        # ⭐ 2026-09-16：社区站下下来的是 `资源标题.zip`，而旧向导只收目录 ——
        #   用户得先自己解压一次，那一次解压正是"导入很麻烦"的起点。
        # ⚠ 这颗放在**源行**（和「选择目录」并列，同属"选什么"），不放动作行：
        #   那一行五颗按钮在紧凑档已经装不下，UP-100 为此分过两组。
        self.browse_archive_btn = QPushButton("选择压缩包…")
        self.browse_archive_btn.setObjectName("secondaryButton")
        self.browse_archive_btn.setMinimumHeight(34)
        self.browse_archive_btn.clicked.connect(self._choose_source_archive)
        source_row.addWidget(self.browse_archive_btn)

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
        self.scan_btn = QPushButton("扫描目录")
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
        self.open_source_btn = QPushButton("打开源目录")
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
        self.preview_text.setPlaceholderText(
            f"还没有扫描结果。\n\n"
            f"选好源目录后点「{self.scan_btn.text()}」，"
            f"这里会列出：能认出来的、有冲突的、没认出来的条目各多少。\n"
            f"扫描只看不写，不会动你现有的音效库。")
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
                f"当前模式：{mode_text} · 已选中源目录 {self._compact_source_text(source_dir)}，"
                "建议先扫描再决定是否导入。"
            )
        else:
            action_message = f"当前模式：{mode_text} · 先选择源目录并扫描，确认识别结果后再执行导入。"
        self.action_bar.set_message(action_message)

    def _sync_first_step(self, has_source: bool):
        """⭐ 那一颗紫的必须是**当下的第一步**（批 44 RN-450 的裁定）。

        没选源目录 ⇒ 第一步是「选择目录」（这时点扫描只会报错）；
        选了 ⇒ 第一步是「扫描目录」（副标题写着「先选源目录，再决定导入模式」）。
        ⚠ 两个都是**安全动作**（都不写任何文件），所以在它们之间换
          不触碰 RN-506 那条线。
        """
        from page_theme_helper import style_as_primary_button, style_as_secondary_button

        first, other = ((self.scan_btn, self.browse_btn) if has_source
                        else (self.browse_btn, self.scan_btn))
        style_as_primary_button(first)
        style_as_secondary_button(other)
        for btn in (first, other):
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _sync_status_strip(self):
        source_dir = self.source_edit.text().strip()
        mode_text = self._mode_text()
        dry_run = bool(self.dry_run_checkbox.isChecked())

        badges = [
            ("positive" if source_dir else "warning", f"源目录 · {self._compact_source_text(source_dir)}"),
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
                "先选择源目录并扫描，再决定是否导入。"
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
        """选一个压缩包。⚠ 过滤器写 zip，但**认格式不看扩展名** ——
        改名的 RAR 会在 `open_source` 里被文件头认出来并给一句人话。"""
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择要导入的资源压缩包",
            self.source_edit.text().strip() or os.path.expanduser("~"),
            "资源包 (*.zip);;所有文件 (*.*)",
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
        prepared = prepare_decisions(source)
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
        """
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
            self._last_import_result = None
            self._render_report(report)
            warnings = [str(line) for line in (report.get("warnings") or [])]
            if warnings:
                # ⭐ 仿击杀图标「缺等级只提示不拦」：这些是"装进去了但不会响"，
                #   要在**落盘之前**讲出来。
                # ⚠ 合成一条说 —— 几条分别弹窗，后面几条必然被连点掉。
                self.notice_bar.show_message("导入前请注意：" + "；".join(warnings))
        finally:
            # ⚠ 报告里存的是**绝对路径**，指向临时解压目录 ——
            #   所以清理必须等到真正落盘之后，见 `_run_import`。
            self._pending_source = source

    def _current_mode(self) -> str:
        return str(self.mode_combo.currentData() or "audio")

    def _mode_text(self) -> str:
        return str(self.mode_combo.currentText() or "音频")

    def _on_mode_changed(self):
        mode_text = self._mode_text()
        self.source_edit.setPlaceholderText(f"请选择包含{mode_text}资源的根目录")
        self._scan_report = None
        self._last_import_result = None
        self.summary_label.setText(f"当前模式：{mode_text}。请选择目录并扫描。")
        self.preview_text.clear()
        self._sync_status_strip()

    def _scan_source(self):
        """⭐ 2026-09-16 起统一走 `_scan_unified`。

        新链路的 `certain` 档**就是**旧规则（路径里带 spec 目录名），
        规范包的行为与改之前一致；多出来的只有"认不出时问一次"。
        ⚠ 旧的 `scan_resource_import_candidates` 没有删 ——
        它是个纯函数，判据 `test_resource_import_wizard.py` 直接测它。
        """
        self._scan_unified()

    def _run_import(self):
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
            holder["result"] = apply_resource_import_plan(
                self._scan_report,
                dry_run=dry_run,
                overwrite_existing=False,
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
        if skipped:
            parts.append(f"冲突跳过 {skipped}（同名的旧素材没被覆盖）")
        if failed:
            parts.append(f"失败 {failed}")
        if rolled:
            # ⭐ 回滚发生过就要说 —— 不说的话用户以为"失败几个"是"其余都进去了"。
            parts.append("这一次已整体收回，资源目录没有留下半套素材")
        # ⭐ 撤销只在**真写了东西**的时候给：一个点下去什么都不会发生的按钮，
        #   比没有还糟。
        can_undo = bool(copied) and not dry_run and not rolled
        self.notice_bar.show_message(
            "；".join(parts),
            undo_callback=(lambda: self._undo_last_import(result)) if can_undo else None,
        )

        if not dry_run:
            self._scan_source()
        else:
            self._render_report(self._scan_report, result)

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
        self._scan_report = None
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
